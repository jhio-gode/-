from __future__ import annotations

"""Deterministic, explainable screening rules. Events are clues, not findings."""

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import timedelta
from typing import Iterable

from tvra import RULE_VERSION
from tvra.domain import Event, Passage, RuleConfig


RULE_WEIGHTS = {"E01": 25, "E02": 40, "E03": 20, "E04": 40, "E05": 20, "E06": 35}
_UNCERTAINTY = "过车观测间隔不能证明车辆实际停车或违法；须结合卡口覆盖、道路行程和人工核查。"


def _level(score: int) -> int:
    return 1 if score >= 70 else 2 if score >= 40 else 3


def _distance(first: Passage, second: Passage) -> float | None:
    if any(v is None for v in (first.longitude, first.latitude, second.longitude, second.latitude)):
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (first.latitude, first.longitude, second.latitude, second.longitude))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def _near(first: Passage, second: Passage, config: RuleConfig) -> str:
    distance = _distance(first, second)
    if distance is not None:
        if distance <= config.near_distance_km:
            return "两次观测坐标相距 {:.3f} 公里（阈值 {:.3f} 公里）".format(distance, config.near_distance_km)
        return ""  # Explicit contradictory coordinates override a reused name.
    if first.area and second.area and first.area != second.area:
        return ""
    if first.checkpoint and first.checkpoint == second.checkpoint:
        suffix = "（行政区域不完整，仅按卡口名称匹配）" if not first.area or not second.area else ""
        return "同名卡口「{}」{}".format(first.checkpoint, suffix)
    return ""


def _place(record: Passage) -> str:
    if record.checkpoint:
        return record.checkpoint + (" / " + record.area if record.area else "")
    if record.longitude is not None and record.latitude is not None:
        return "坐标 {:.6f}, {:.6f}".format(record.longitude, record.latitude)
    return record.area or "未提供地点"


def _night(record: Passage, config: RuleConfig) -> bool:
    hour = record.when.hour
    if config.night_start < config.night_end:
        return config.night_start <= hour < config.night_end
    return hour >= config.night_start or hour < config.night_end


def _sensitive(record: Passage) -> bool:
    tag = record.location_tag.strip().lower()
    if not tag or tag in ("0", "false", "no", "否", "无", "普通", "正常", "普通道路", "非风险", "非敏感", "无风险", "无风险地点"):
        return False
    if any(token in tag for token in ("非风险", "非敏感", "无风险", "无异常")):
        return False
    return tag in ("1", "true", "yes", "是") or any(token in tag for token in ("风险", "敏感", "异常", "可疑", "烟花", "爆竹", "危化", "危险品", "化工", "装卸", "仓储", "仓库"))


def _hazardous_tanker(record: Passage) -> bool:
    return "罐" in record.vehicle_type and any(token in record.vehicle_type for token in ("危化", "危险", "化学"))


def _highway_direction(record: Passage) -> str:
    kind = record.checkpoint_type.strip().lower().replace("-", "_").replace(" ", "_")
    if kind in ("exit", "highway_exit", "expressway_exit"):
        return "exit"
    if kind in ("entry", "entrance", "highway_entry", "highway_entrance", "expressway_entry"):
        return "entry"
    value = record.checkpoint_type + " " + record.checkpoint
    # Generic 出口/入口 and 高速出入口 contain insufficient direction semantics.
    if any(token in value for token in ("高速出口", "高速公路出口", "驶出高速", "下高速")):
        return "exit"
    if any(token in value for token in ("高速入口", "高速公路入口", "驶入高速", "上高速")):
        return "entry"
    return ""


def _is_surface(record: Passage) -> bool:
    return bool(record.checkpoint or record.longitude is not None) and not _highway_direction(record) and "高速" not in (record.checkpoint + record.checkpoint_type)


def _same_interchange(first: Passage, second: Passage, config: RuleConfig) -> bool:
    distance = _distance(first, second)
    if distance is not None and distance > config.near_distance_km:
        return False
    if distance is None and first.area and second.area and first.area != second.area:
        return False
    if _near(first, second, config):
        return True
    def name(value: str) -> str:
        for token in ("高速公路出口", "高速公路入口", "高速出口", "高速入口", "收费站出口", "收费站入口", "出口", "入口", "驶出高速", "驶入高速"):
            value = value.replace(token, "")
        return re.sub(r"[\s_\-（）()]+", "", value)
    a, b = name(first.checkpoint), name(second.checkpoint)
    return bool(a and b and a == b)


def _quality(records: list[Passage]) -> list[str]:
    result = [_UNCERTAINTY]
    if len(records) < 3:
        result.append("该车辆仅有 {} 条观测，行为画像与后续去向证据不足。".format(len(records)))
    if not any(r.longitude is not None and r.latitude is not None for r in records):
        result.append("缺少坐标，位置比对仅依赖相同卡口名称；名称不一致的卡口不会按同一地点处理。")
    else:
        result.append("坐标距离假设输入使用同一坐标系；本规则不自动转换坐标系。")
    if not any(_highway_direction(r) for r in records):
        result.append("缺少明确高速进出语义，E02 高速脱离停返未评估。")
    if not any(r.owner for r in records):
        result.append("缺少企业信息，E05 企业多车异常未评估。")
    if not any(r.location_tag for r in records):
        result.append("缺少风险地点标签，E04 风险地点疑似停留未评估。")
    if not any(r.area for r in records):
        result.append("缺少行政区域，E06 区域高频往返未评估。")
    return result


def _event(kind: str, title: str, records: list[Passage], evidence: list[str], quality: list[str], score: int | None = None) -> Event:
    ordered = sorted({r.record_key: r for r in records}.values(), key=lambda r: (r.time, r.record_key))
    first, last = ordered[0], ordered[-1]
    keys = [r.record_key for r in ordered]
    identity = json.dumps([RULE_VERSION, kind, first.vehicle_key, keys], ensure_ascii=False, separators=(",", ":"))
    event_id = kind + "-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    initial = RULE_WEIGHTS[kind] if score is None else score
    model = "危化品" if any(_hazardous_tanker(r) for r in ordered) else "烟花爆竹" if any(any(t in r.location_tag for t in ("烟花", "爆竹")) for r in ordered) else "通用"
    return Event(event_id=event_id, plate=first.plate, vehicle_key=first.vehicle_key, event_type=kind, title=title, level=_level(initial), start=first.time, end=last.time, score=initial, evidence=evidence, record_keys=keys, model=model, data_quality=list(quality))


def _stays(records: list[Passage], config: RuleConfig, quality: list[str]) -> list[Event]:
    events = []
    for index, (first, second) in enumerate(zip(records, records[1:])):
        minutes = (second.when - first.when).total_seconds() / 60
        position = _near(first, second, config)
        if not position:
            continue
        observed = [first, second]
        details = ["{} 至 {}，{}，观测间隔 {:.1f} 分钟。".format(first.time, second.time, position, minutes), "地点：{}。".format(_place(first))]
        if config.short_stop_min <= minutes <= config.short_stop_max:
            evidence = details + ["疑似短停区间：{}–{} 分钟。".format(config.short_stop_min, config.short_stop_max)]
            if index + 2 < len(records) and not _near(second, records[index + 2], config):
                following = records[index + 2]
                evidence.append("后续观测：{}，{}，提示随后继续移动。".format(following.time, _place(following)))
                # Keep time extent restricted to the suspected stay; the following
                # observation is contextual, and must not fuse unrelated later events.
            events.append(_event("E01", "同地点疑似短停", observed, evidence, quality))
        if minutes >= config.sensitive_stay_minutes and (_sensitive(first) or _sensitive(second)):
            # A tag at one endpoint plus geographic proximity is disclosed, not
            # silently equated to both endpoints being in the same tagged polygon.
            tags = sorted({r.location_tag for r in observed if _sensitive(r)})
            long_stay = minutes >= config.long_stay_minutes
            high = long_stay and any(_hazardous_tanker(r) for r in observed)
            evidence = details + ["输入风险地点标签：{}；疑似{}停留，至少 {} 分钟阈值。".format("、".join(tags), "长时" if long_stay else "短时", config.sensitive_stay_minutes)]
            if high:
                evidence.append("车型明确为危化品罐车，风险地点间隔达到 {} 分钟长停阈值，按优先规则列为一级待核查。".format(config.long_stay_minutes))
            events.append(_event("E04", "风险地点疑似长时停留" if long_stay else "风险地点疑似停留", observed, evidence, quality, 80 if high else None))
    return events


def _highway(records: list[Passage], config: RuleConfig, quality: list[str]) -> list[Event]:
    events = []
    for i, first in enumerate(records):
        if _highway_direction(first) != "exit":
            continue
        for j in range(i + 1, len(records)):
            last = records[j]
            if (last.when - first.when).total_seconds() > config.highway_return_hours * 3600:
                break
            direction = _highway_direction(last)
            if direction == "exit":
                break  # Another exit invalidates an otherwise incomplete episode.
            if direction != "entry":
                continue
            middle = records[i + 1:j]
            if not _same_interchange(first, last, config):
                break
            stays = []
            for a, b in zip(middle, middle[1:]):
                minutes = (b.when - a.when).total_seconds() / 60
                if _is_surface(a) and _is_surface(b) and _near(a, b, config) and config.short_stop_min <= minutes <= config.short_stop_max:
                    stays.extend([a, b])
            if stays:
                episode = [first] + stays + [last]
                evidence = ["{}：明确高速出口，{}。".format(first.time, _place(first)), "{}：{}，随后 {}：{}；地面相近位置观测符合疑似短停阈值。".format(stays[0].time, _place(stays[0]), stays[-1].time, _place(stays[-1])), "{}：明确高速入口，{}；与出口属同节点名称或相近坐标，离返总时长 {:.1f} 小时（阈值 {} 小时）。".format(last.time, _place(last), (last.when - first.when).total_seconds() / 3600, config.highway_return_hours), "完整出—地面疑似停留—返链条满足优先规则，列为一级待核查。"]
                events.append(_event("E02", "高速脱离后疑似停留并返回", episode, evidence, quality, 80))
            break
    return events


def _frequent(records: list[Passage], config: RuleConfig, quality: list[str]) -> list[Event]:
    # Missing areas interrupt a sequence instead of creating a guessed transition.
    segments = [[]]
    previous_area = ""
    previous_time = ""
    by_time = defaultdict(set)
    for record in records:
        if record.area:
            by_time[record.time].add(record.area)
    for record in records:
        if not record.area or len(by_time[record.time]) > 1:
            if segments[-1]:
                segments.append([])
            previous_area = ""
            previous_time = ""
            continue
        if record.area != previous_area and record.time != previous_time:
            segments[-1].append(record)
        previous_area = record.area
        previous_time = record.time
    events = []
    for visits in segments:
        events.extend(_frequent_segment(visits, config, quality))
    return events


def _frequent_segment(visits: list[Passage], config: RuleConfig, quality: list[str]) -> list[Event]:
    events = []
    consumed = set()
    for start, first in enumerate(visits):
        if start in consumed:
            continue
        end_limit = first.when + timedelta(hours=config.frequent_window_hours)
        window = []
        matches = 0
        for index in range(start, len(visits)):
            current = visits[index]
            if current.when > end_limit:
                break
            window.append(current)
            if current.area == first.area:
                matches += 1
            if matches >= config.frequent_min_visits and len({r.area for r in window}) >= 2:
                # Each return must have a known different area in between; a
                # missing-area row alone is not evidence of leaving and returning.
                positions = [n for n, r in enumerate(window) if r.area == first.area]
                if not all(any(r.area != first.area for r in window[a + 1:b]) for a, b in zip(positions, positions[1:])):
                    continue
                evidence = ["{} 至 {}，{} 小时窗口内区域序列：{}。".format(window[0].time, window[-1].time, config.frequent_window_hours, " → ".join(r.area for r in window)), "区域「{}」发生 {} 次到访，每次返回之间均有其他区域观测（阈值 {} 次）。".format(first.area, matches, config.frequent_min_visits), "地点依次为：{}。".format(" → ".join(_place(r) for r in window))]
                events.append(_event("E06", "区域高频往返", window, evidence, quality))
                consumed.update(range(start, index + 1))
                break
    return events


def _night_combinations(events: list[Event], records: list[Passage], config: RuleConfig, quality: list[str]) -> list[Event]:
    by_key = {r.record_key: r for r in records}
    combined = {}
    for event in events:
        if event.event_type not in ("E01", "E02", "E04", "E06"):
            continue
        observed = [by_key[k] for k in event.record_keys if k in by_key]
        nights = [r for r in observed if _night(r, config)]
        if not nights:
            continue
        evidence = ["已存在 {}「{}」事件；夜间活动与其他异常行为组合，夜间单独不触发风险。".format(event.event_type, event.title), "夜间定义：{:02d}:00 至 {:02d}:00（结束时刻不包含）。".format(config.night_start, config.night_end), "夜间实际观测：{}。".format("；".join(r.time + " / " + _place(r) for r in nights))]
        result = _event("E03", "夜间活动与异常行为组合", observed, evidence, quality)
        if result.event_id not in combined:
            combined[result.event_id] = result
        else:
            combined[result.event_id].evidence[0] += " 同时触发 {}。".format(event.event_type)
    return list(combined.values())


def _companies(base: list[Event], groups: dict, config: RuleConfig) -> list[Event]:
    by_key = {r.record_key: r for records in groups.values() for r in records}
    enterprise = defaultdict(list)
    for event in base:
        if event.event_type not in ("E01", "E02", "E04", "E06"):
            continue
        event_records = [by_key[k] for k in event.record_keys]
        names = {r.owner for r in event_records if r.owner}
        # Contradictory ownership within one event must not make a guessed link.
        if len(names) == 1:
            enterprise[next(iter(names))].append(event)
    output = []
    for owner, candidates in sorted(enterprise.items()):
        candidates.sort(key=lambda e: (e.start, e.vehicle_key, e.event_id))
        left = right = 0
        counts = defaultdict(int)
        while left < len(candidates):
            deadline = by_key[candidates[left].record_keys[0]].when + timedelta(hours=config.company_window_hours)
            while right < len(candidates) and by_key[candidates[right].record_keys[0]].when <= deadline:
                counts[candidates[right].vehicle_key] += 1
                right += 1
            if len(counts) < config.company_min_vehicles:
                old_key = candidates[left].vehicle_key
                counts[old_key] -= 1
                if not counts[old_key]:
                    del counts[old_key]
                left += 1
                continue
            window = candidates[left:right]
            vehicles = set(counts)
            # Each participating vehicle retains its own evidence keys. Other
            # vehicles' identifiers are context, not passages attributed to it.
            for vehicle in sorted(vehicles):
                matching = [e for e in window if e.vehicle_key == vehicle]
                own_records = sorted({k: by_key[k] for e in matching for k in e.record_keys}.values(), key=lambda r: (r.time, r.record_key))
                group_records = groups[(own_records[0].plate, own_records[0].plate_type)]
                evidence = ["企业字段「{}」关联 {} 辆具有独立异常事件的车辆，事件起始时间在 {} 小时窗口内（阈值 {} 辆）。".format(owner, len(vehicles), config.company_window_hours, config.company_min_vehicles), "关联车辆：{}。".format("、".join(sorted(vehicles))), "本车独立触发：{}；本车地点：{}。".format("、".join(sorted({e.event_type for e in matching})), " → ".join(_place(r) for r in own_records)), "企业同名关联未校验统一社会信用代码；群体时间关联不能证明协同行为。"]
                result = _event("E05", "同企业多车异常时间关联", own_records, evidence, _quality(group_records))
                output.append(result)
            # Consume this qualified observation window. This avoids producing
            # quadratic overlapping enterprise reports for a large fleet. If a
            # window is not qualified, its left edge advances one event at a time.
            left = right
            counts.clear()
    return output


def _fuse(events: list[Event]) -> list[Event]:
    groups = defaultdict(list)
    for event in events:
        groups[event.vehicle_key].append(event)
    for vehicle_events in groups.values():
        ordered = sorted(vehicle_events, key=lambda e: (e.start, e.end, e.event_type, e.event_id))
        clusters = []
        cluster = []
        last_end = ""
        for event in ordered:
            if cluster and event.start > last_end:
                clusters.append(cluster)
                cluster = []
                last_end = ""
            cluster.append(event)
            last_end = max(last_end, event.end)
        if cluster:
            clusters.append(cluster)
        for cluster in clusters:
            kinds = sorted({event.event_type for event in cluster})
            score = min(95, sum(RULE_WEIGHTS[k] for k in kinds))
            score = max(score, max(event.score for event in cluster))
            note = "同车时间重叠事件融合：{}；每种规则仅计一次，排序分 {}，{}级；分数未经概率校准，须人工复核。".format(" + ".join(kinds), score, _level(score))
            for event in cluster:
                event.score = score
                event.level = _level(score)
                event.evidence.append(note)
    return sorted(events, key=lambda e: (e.start, e.vehicle_key, e.event_type, e.event_id))


def _validate(config: RuleConfig) -> None:
    if not 1 <= config.short_stop_min <= config.short_stop_max:
        raise ValueError("疑似短停阈值须为正数，且最短时间不大于最长时间")
    if not 0 < config.near_distance_km <= 100:
        raise ValueError("相近坐标距离阈值须大于 0 且不大于 100 公里")
    if not 0 <= config.night_start <= 23 or not 0 <= config.night_end <= 23 or config.night_start == config.night_end:
        raise ValueError("夜间起止小时须在 0–23 且不同")
    if config.frequent_min_visits < 2 or config.company_min_vehicles < 2:
        raise ValueError("往返次数和企业车辆阈值须至少为 2")
    if min(config.frequent_window_hours, config.company_window_hours, config.highway_return_hours, config.sensitive_stay_minutes, config.long_stay_minutes) <= 0:
        raise ValueError("时间窗口与停留阈值必须大于 0")


def analyze(records: Iterable[Passage], config: RuleConfig | None = None) -> list[Event]:
    config = config or RuleConfig()
    _validate(config)
    grouped = defaultdict(list)
    unique = {r.record_key: r for r in records}
    for record in unique.values():
        grouped[(record.plate, record.plate_type)].append(record)
    result = []
    for vehicle, passages in sorted(grouped.items()):
        passages.sort(key=lambda r: (r.time, r.record_key))
        quality = _quality(passages)
        events = _stays(passages, config, quality) + _highway(passages, config, quality) + _frequent(passages, config, quality)
        result.extend(events + _night_combinations(events, passages, config, quality))
    result.extend(_companies(result, grouped, config))
    # Distinct algorithm paths can intentionally identify the same record set.
    result = list({event.event_id: event for event in result}.values())
    return _fuse(result)
