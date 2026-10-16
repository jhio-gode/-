from __future__ import annotations

import bisect
import hashlib
import json
import os
import sqlite3
import threading
from collections import Counter, defaultdict
from dataclasses import asdict, fields, replace
from datetime import datetime, timedelta
from pathlib import Path

from . import RULE_VERSION
from .domain import Passage, RuleConfig
from .engine import analyze
from .importer import load_records


def default_data_dir() -> Path:
    override = os.environ.get("TVRA_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TVRA"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "tvra"


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Service:
    """Local transactional workspace. Input files are never modified."""

    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir or default_data_dir()).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "tvra_v3.sqlite3"
        self._lock = threading.RLock()
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    record_key TEXT PRIMARY KEY, vehicle_key TEXT NOT NULL,
                    time TEXT NOT NULL, checkpoint TEXT NOT NULL, area TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS record_identity_time
                    ON records(vehicle_key, checkpoint, area, time);
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY, vehicle_key TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    sources TEXT NOT NULL, source_hashes TEXT NOT NULL,
                    new_records INTEGER NOT NULL, duplicates INTEGER NOT NULL,
                    errors TEXT NOT NULL, warnings TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    name TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    reason TEXT NOT NULL, rule_config TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    run_id TEXT NOT NULL, vehicle_key TEXT NOT NULL,
                    risk_level INTEGER NOT NULL, event_count INTEGER NOT NULL,
                    PRIMARY KEY(run_id, vehicle_key)
                );
                PRAGMA user_version = 1;
            """)

    def _connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _records(db):
        return [Passage(**json.loads(r[0])) for r in db.execute(
            "SELECT payload FROM records ORDER BY vehicle_key, time, record_key")]

    @staticmethod
    def _config(db):
        row = db.execute("SELECT payload FROM settings WHERE name='rules'").fetchone()
        return RuleConfig(**json.loads(row[0])) if row else RuleConfig()

    def get_settings(self) -> dict:
        with self._lock, self._connect() as db:
            return asdict(self._config(db))

    @staticmethod
    def _validated_config(values):
        allowed = {f.name for f in fields(RuleConfig)}
        if set(values) - allowed:
            raise ValueError("未知规则字段：" + ", ".join(sorted(set(values) - allowed)))
        defaults = asdict(RuleConfig())
        defaults.update(values)
        for key, value in defaults.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("规则参数必须是数字：" + key)
            if key == "near_distance_km":
                if not 0 < value <= 50:
                    raise ValueError("相近地点距离须大于0且不超过50公里")
                defaults[key] = float(value)
            else:
                if int(value) != value:
                    raise ValueError("规则参数必须是整数：" + key)
                defaults[key] = int(value)
                if key in ("night_start", "night_end"):
                    if not 0 <= value <= 23:
                        raise ValueError("夜间小时须在0至23之间")
                elif not 1 <= value <= 10000:
                    raise ValueError("规则参数须在1至10000之间：" + key)
        if defaults["short_stop_min"] > defaults["short_stop_max"]:
            raise ValueError("短停最短时间不能大于最长时间")
        if defaults["night_start"] == defaults["night_end"]:
            raise ValueError("夜间开始和结束小时不能相同")
        if min(defaults["company_min_vehicles"], defaults["frequent_min_visits"]) < 2:
            raise ValueError("企业车辆数和往返次数至少为2")
        return RuleConfig(**defaults)

    def save_settings(self, values) -> dict:
        with self._lock, self._connect() as db:
            current = asdict(self._config(db))
            current.update(values)
            config = self._validated_config(current)
            records = self._records(db)
            events = analyze(records, config)
            db.execute("INSERT OR REPLACE INTO settings VALUES('rules', ?)", (_json(asdict(config)),))
            self._save_analysis(db, records, events, config, "规则调整后重新分析")
            return {"settings": asdict(config), "event_count": len(events)}

    @staticmethod
    def _save_analysis(db, records, events, config, reason):
        by_plate = defaultdict(list)
        for record in records:
            by_plate[record.plate].append(record.vehicle_key)
        payloads = []
        for event in events:
            payload = event.to_dict()
            identity = payload.get("vehicle_key")
            if not identity:
                identities = set(by_plate.get(event.plate, []))
                if len(identities) != 1:
                    raise ValueError("事件缺少明确车辆身份：" + event.plate)
                identity = next(iter(identities))
                payload["vehicle_key"] = identity
            payloads.append(payload)
        db.execute("DELETE FROM events")
        db.executemany("INSERT INTO events VALUES (?, ?, ?)", [
            (e["event_id"], e["vehicle_key"], _json(e)) for e in payloads])
        signature = _json([r.to_dict() for r in sorted(records, key=lambda p: p.record_key)]) + _json(asdict(config)) + RULE_VERSION
        run_id = hashlib.sha256(signature.encode("utf-8")).hexdigest()
        existed = db.execute("SELECT 1 FROM analysis_runs WHERE run_id=?", (run_id,)).fetchone()
        if not existed and records:
            db.execute("INSERT INTO analysis_runs VALUES (?, ?, ?, ?)",
                       (run_id, _stamp(), reason, _json(asdict(config))))
            levels, counts = {}, Counter()
            for e in payloads:
                key = e["vehicle_key"]
                levels[key] = min(levels.get(key, 4), e["level"])
                counts[key] += 1
            db.executemany("INSERT INTO snapshots VALUES (?, ?, ?, ?)", [
                (run_id, key, levels.get(key, 0), counts[key])
                for key in sorted({r.vehicle_key for r in records})])

    def import_files(self, paths) -> dict:
        paths = [str(Path(p).expanduser().resolve()) for p in paths]
        if not paths:
            raise ValueError("请选择至少一个 Excel 或 CSV 文件")
        loaded = load_records(paths, deduplicate_input=False)
        if not loaded.records and not loaded.errors:
            raise ValueError("文件没有可导入的过车记录")
        fingerprint = _json([r.to_dict() for r in sorted(loaded.records, key=lambda p: p.record_key)])
        # Include invalid rows so that each distinct import failure remains inspectable.
        batch_id = hashlib.sha256((fingerprint + _json(loaded.errors)).encode("utf-8")).hexdigest()
        with self._lock, self._connect() as db:
            existing_batch = db.execute("SELECT 1 FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
            existing = self._records(db)
            existing_by_key = {r.record_key: r for r in existing}
            existing_keys = {r.record_key for r in existing}
            proximity = defaultdict(list)
            for r in existing:
                if r.checkpoint:
                    proximity[(r.vehicle_key, r.checkpoint, r.area)].append(r.when)
            for times in proximity.values():
                times.sort()
            accepted, updates, duplicate_count = [], {}, loaded.duplicate_count
            for r in sorted(loaded.records, key=lambda p: (p.vehicle_key, p.time, p.record_key)):
                if r.record_key in existing_keys:
                    duplicate_count += 1
                    old = existing_by_key.get(r.record_key)
                    if old is not None:
                        enriched = replace(old, **{name: getattr(r, name) or getattr(old, name)
                            for name in ("owner", "vehicle_type", "location_tag", "checkpoint_type")})
                        if enriched != old:
                            updates[r.record_key] = enriched
                    continue
                if r.checkpoint:
                    times = proximity[(r.vehicle_key, r.checkpoint, r.area)]
                    i = bisect.bisect_left(times, r.when)
                    adjacent = times[max(0, i - 1):i + 1]
                    if any(abs((r.when - t).total_seconds()) < 10 for t in adjacent):
                        duplicate_count += 1
                        continue
                    bisect.insort(times, r.when)
                accepted.append(r)
                existing_keys.add(r.record_key)
            combined = [updates.get(r.record_key, r) for r in existing] + accepted
            config = self._config(db)
            events = analyze(combined, config)
            db.executemany("INSERT INTO records VALUES (?, ?, ?, ?, ?, ?)", [
                (r.record_key, r.vehicle_key, r.time, r.checkpoint, r.area, _json(r.to_dict()))
                for r in accepted])
            db.executemany("UPDATE records SET payload=? WHERE record_key=?", [
                (_json(r.to_dict()), r.record_key) for r in updates.values()])
            warnings = list(loaded.warnings)
            if updates:
                warnings.append("已补充或更新 {} 条已有记录的车型、企业或地点标签；未新增重复过车记录。".format(len(updates)))
            if existing_batch:
                warnings.append("该批数据已导入，本次不会重复新增记录或分析历史。")
            else:
                db.execute("INSERT INTO batches VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
                    batch_id, _stamp(), _json(paths), _json(loaded.source_hashes),
                    len(accepted), duplicate_count, _json(loaded.errors), _json(warnings)))
            self._save_analysis(db, combined, events, config, "导入数据后分析")
            return {
                "batch_id": batch_id, "new_records": len(accepted), "updated_records": len(updates),
                "record_count": len(combined), "duplicate_count": duplicate_count,
                "error_count": len(loaded.errors), "errors": loaded.errors,
                "event_count": len(events), "warnings": warnings,
            }

    def reanalyze(self) -> dict:
        with self._lock, self._connect() as db:
            records = self._records(db)
            config = self._config(db)
            events = analyze(records, config)
            self._save_analysis(db, records, events, config, "手动重新分析")
            return {"record_count": len(records), "event_count": len(events)}

    @staticmethod
    def _events(db):
        return [json.loads(r[0]) for r in db.execute("SELECT payload FROM events")]

    def list_vehicles(self, keyword="") -> list:
        with self._lock, self._connect() as db:
            return self._vehicles(self._records(db), self._events(db), keyword, self._config(db))

    @staticmethod
    def _vehicles(records, events, keyword="", config=None):
        config = config or RuleConfig()
        grouped, event_groups = defaultdict(list), defaultdict(list)
        for r in records:
            grouped[r.vehicle_key].append(r)
        for event in events:
            event_groups[event["vehicle_key"]].append(event)
        result = []
        for identity, rows in grouped.items():
            rows.sort(key=lambda r: (r.time, r.record_key))
            latest = rows[-1]
            owner = next((r.owner for r in reversed(rows) if r.owner), "")
            vtype = next((r.vehicle_type for r in reversed(rows) if r.vehicle_type), "")
            if keyword.strip() and keyword.strip().lower() not in (identity + owner + vtype).lower():
                continue
            vehicle_events = event_groups[identity]
            def is_night(r):
                h = r.when.hour
                return ((h >= config.night_start or h < config.night_end)
                        if config.night_start > config.night_end
                        else config.night_start <= h < config.night_end)
            areas = Counter(r.area for r in rows if r.area)
            result.append({
                "vehicle_key": identity, "plate": latest.plate,
                "plate_type": latest.plate_type, "vehicle_type": vtype, "owner": owner,
                "record_count": len(rows), "event_count": len(vehicle_events),
                "risk_level": min((e["level"] for e in vehicle_events), default=0),
                "night_ratio": sum(is_night(r) for r in rows) / len(rows),
                "main_areas": [a for a, _ in areas.most_common(3)],
                "first_seen": rows[0].time, "last_seen": rows[-1].time,
                "assessments": {
                    "停留线索": "可评估部分观测" if any(r.checkpoint or r.longitude is not None for r in rows) else "缺少精确位置，无法评估",
                    "风险地点": "具备部分地点标签" if any(r.location_tag for r in rows) else "缺少地点标签，无法评估",
                    "高速出入": "具备部分出入口标签" if any(r.checkpoint_type for r in rows) else "未提供高速出入口标签",
                    "企业群体": "已提供所有人" if owner else "缺少企业归属",
                },
            })
        return sorted(result, key=lambda v: (v["risk_level"] or 4, -v["event_count"], v["vehicle_key"]))

    def list_events(self, filters=None) -> list:
        filters = filters or {}
        with self._lock, self._connect() as db:
            events = self._events(db)
            vehicles = {v["vehicle_key"]: v for v in self._vehicles(self._records(db), events, config=self._config(db))}
        result = []
        for event in events:
            item = dict(event)
            vehicle = vehicles.get(item["vehicle_key"], {})
            item.update({"owner": vehicle.get("owner", ""), "vehicle_type": vehicle.get("vehicle_type", ""),
                         "plate_type": vehicle.get("plate_type", "")})
            keyword = str(filters.get("keyword", "")).strip().lower()
            if keyword and keyword not in (item["plate"] + item["owner"] + item["title"] + item["vehicle_type"]).lower():
                continue
            if filters.get("level") and str(item["level"]) != str(filters["level"]):
                continue
            if filters.get("event_type") and item["event_type"] != filters["event_type"]:
                continue
            if filters.get("date_from") and item["end"][:10] < str(filters["date_from"])[:10]:
                continue
            if filters.get("date_to") and item["start"][:10] > str(filters["date_to"])[:10]:
                continue
            result.append(item)
        return sorted(result, key=lambda e: (e["level"], e["start"], e["event_id"]))

    def imports(self) -> list:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT * FROM batches ORDER BY created_at DESC, batch_id DESC").fetchall()
        return [{
            "batch_id": r["batch_id"], "created_at": r["created_at"], "sources": json.loads(r["sources"]),
            "new_records": r["new_records"], "duplicate_count": r["duplicates"],
            "error_count": len(json.loads(r["errors"])), "errors": json.loads(r["errors"]),
            "warnings": json.loads(r["warnings"]),
        } for r in rows]

    def summary(self) -> dict:
        with self._lock, self._connect() as db:
            records, events = self._records(db), self._events(db)
            vehicles = self._vehicles(records, events, config=self._config(db))
        batches = self.imports()
        limitations = ["卡口观测间隔仅支持疑似停留推断，不能证明真实停车或违法。",
                       "本地规则输出为人工核查线索，分值只用于排序，不表示违法概率。",
                       "未提供规定运输路线与真实查获标签，不评估路线偏离或货物实际种类。"]
        if any(not r.checkpoint and (r.latitude is None or r.longitude is None) for r in records):
            limitations.append("部分记录缺少卡口标识或坐标，其停留条件无法充分评估。")
        if records and not any(r.location_tag for r in records):
            limitations.append("当前数据缺少地点标签，未评估风险地点停留。")
        if records and not any(r.checkpoint_type for r in records):
            limitations.append("当前数据缺少高速出入口标签，未评估高速脱离返回。")
        times = sorted(r.time for r in records)
        return {
            "vehicles": len(vehicles), "records": len(records), "events": len(events),
            "level1": sum(e["level"] == 1 for e in events),
            "level2": sum(e["level"] == 2 for e in events),
            "level3": sum(e["level"] == 3 for e in events),
            "last_import": batches[0]["created_at"] if batches else "暂无",
            "event_types": dict(Counter(e["title"] for e in events)),
            "coverage_start": times[0] if times else "暂无", "coverage_end": times[-1] if times else "暂无",
            "rule_version": RULE_VERSION, "limitations": limitations,
            "source_paths": sorted({p for b in batches for p in b["sources"]}),
            "assessment_scope": "已导入数据范围；全部时间均按源数据的本地业务时间解释",
            "data_dir": str(self.data_dir),
        }

    def vehicle_detail(self, vehicle_key):
        with self._lock, self._connect() as db:
            records, events = self._records(db), self._events(db)
            vehicles = self._vehicles(records, events, config=self._config(db))
            matches = [v for v in vehicles if v["vehicle_key"] == vehicle_key]
            if not matches:
                matches = [v for v in vehicles if v["plate"] == vehicle_key]
            if len(matches) > 1:
                raise ValueError("该号牌对应多个号牌种类，请选择具体车辆身份")
            if not matches:
                return None
            vehicle = matches[0]
            identity = vehicle["vehicle_key"]
            history = [dict(r) for r in db.execute("""
                SELECT s.run_id AS batch_id, a.created_at, a.reason,
                    s.risk_level, s.event_count FROM snapshots s
                JOIN analysis_runs a ON s.run_id=a.run_id
                WHERE s.vehicle_key=? ORDER BY a.created_at DESC, a.rowid DESC
            """, (identity,))]
            for row in history:
                row["rule_version"] = RULE_VERSION
        return {
            "vehicle": vehicle,
            "records": [r.to_dict() for r in records if r.vehicle_key == identity],
            "events": sorted((e for e in events if e["vehicle_key"] == identity), key=lambda e: e["start"]),
            "history": history, "rule_version": RULE_VERSION,
            "limitations": self.summary()["limitations"],
        }

    def close(self):
        # Connections are operation-scoped and never shared across worker threads.
        pass
