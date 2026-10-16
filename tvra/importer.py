from __future__ import annotations

"""Read local source files without modifying them or inferring a vehicle per file."""

import csv
import hashlib
import io
import json
import math
import re
import unicodedata
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from tvra.domain import ImportResult, Passage


_ALIASES = {
    "plate": ("车牌", "车牌号", "号牌", "号牌号码", "车牌号码", "车辆号牌", "车辆编号", "plate", "licenseplate"),
    "time": ("时间", "过车时间", "通过时间", "卡口时间", "采集时间", "抓拍时间", "行驶时间", "通行时间", "time", "timestamp", "datetime", "passtime", "passagetime"),
    "plate_type": ("号牌种类", "车牌种类", "号牌颜色", "车牌颜色", "platetype", "platecolor"),
    "vehicle_type": ("车型", "车辆类型", "车辆种类", "vehicletype"),
    "owner": ("企业", "企业名称", "所属企业", "所属单位", "运输企业", "所属公司", "公司名称", "车主", "所有人", "车辆所有人", "owner", "company"),
    "checkpoint": ("卡口", "卡口名称", "卡口编号", "卡口点位", "监测点", "点位", "点位名称", "经过地点", "行驶地点", "地点", "checkpoint", "location"),
    "area": ("区域", "行政区域", "行政区划", "行政区", "区县", "所在区域", "行驶区域", "地区", "area", "region"),
    "location_tag": ("地点标签", "地点类型", "风险地点", "风险标签", "位置标签", "敏感地点", "locationtag", "risktag"),
    "longitude": ("经度", "longitude", "lng", "lon"),
    "latitude": ("纬度", "latitude", "lat"),
    "checkpoint_type": ("卡口类型", "点位类型", "道口类型", "高速进出类型", "进出类型", "道路类型", "checkpointtype"),
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def _header(value: Any) -> str:
    return re.sub(r"[\s_\-:：()（）]+", "", _text(value)).lower()


_HEADER_MAP = {_header(alias): field for field, names in _ALIASES.items() for alias in names}


def _filename_plate(path: Path) -> str:
    """Backward compatibility only for an unambiguous Chinese plate filename."""
    candidate = re.sub(r"\s+", "", _text(path.stem)).upper()
    return candidate if re.fullmatch(r"[\u4e00-\u9fff][A-Z][A-Z0-9]{5,6}", candidate) else ""


def _parse_time(value: Any, epoch: datetime | None = None) -> str:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, date):
        # A date without a time cannot support trajectory time-gap rules.
        raise ValueError("过车时间仅含日期，缺少时分秒")
    elif isinstance(value, (float, int)) and not isinstance(value, bool) and epoch is not None:
        if not math.isfinite(value) or value < 1 or value > 100000:
            raise ValueError("Excel 日期数值超出可识别范围")
        from openpyxl.utils.datetime import from_excel

        result = from_excel(value, epoch=epoch)
        if not isinstance(result, datetime):
            raise ValueError("过车时间缺少日期")
    else:
        raw = _text(value)
        if not raw:
            raise ValueError("缺少过车时间")
        raw = raw.replace("年", "-").replace("月", "-").replace("日", " ").replace("时", ":").replace("分", ":").replace("秒", "")
        raw = re.sub(r"\s+", " ", raw).strip()
        if re.fullmatch(r"\d{14}", raw):
            result = datetime.strptime(raw, "%Y%m%d%H%M%S")
        else:
            if not re.search(r"\d{1,2}:\d{1,2}", raw):
                raise ValueError("过车时间须包含日期和时分")
            iso = raw.replace("/", "-")
            if iso.endswith("Z"):
                iso = iso[:-1] + "+00:00"
            try:
                result = datetime.fromisoformat(iso)
            except ValueError:
                result = None
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M"):
                    try:
                        result = datetime.strptime(iso, fmt)
                        break
                    except ValueError:
                        pass
                if result is None:
                    raise ValueError("无法识别过车时间，请使用 YYYY-MM-DD HH:MM:SS")
    if result.tzinfo is not None:
        result = result.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    if not 1900 <= result.year <= 2100:
        raise ValueError("过车时间年份应为 1900 至 2100")
    return result.strftime("%Y-%m-%d %H:%M:%S")


def _coordinate(value: Any, limit: float, field: str) -> float | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        raise ValueError(field + "不是有效数值")
    if not math.isfinite(number) or not -limit <= number <= limit:
        raise ValueError(field + "超出有效范围")
    return round(number, 7)


def _passage(data: dict, fallback_plate: str, epoch: datetime | None) -> Passage:
    plate = re.sub(r"\s+", "", _text(data.get("plate"))).upper() or fallback_plate
    if not plate or plate.lower() in ("nan", "none", "null"):
        raise ValueError("缺少车辆号牌；多车文件必须逐行填写车牌")
    if not 2 <= len(plate) <= 32 or not re.fullmatch(r"[A-Z0-9\u3400-\u9fff·\-]+", plate) or not re.search(r"[A-Z\u3400-\u9fff]", plate):
        raise ValueError("车辆号牌格式无效：应为 2–32 位中文、字母、数字及常见号牌分隔符")
    if plate in ("无牌", "无车牌", "未知", "未识别", "UNKNOWN"):
        raise ValueError("车辆号牌未识别，不能把未知车辆合并分析")
    values = {key: _text(data.get(key)) for key in ("plate_type", "vehicle_type", "owner", "checkpoint", "area", "location_tag", "checkpoint_type")}
    values.update(plate=plate, time=_parse_time(data.get("time"), epoch))
    values["longitude"] = _coordinate(data.get("longitude"), 180, "经度")
    values["latitude"] = _coordinate(data.get("latitude"), 90, "纬度")
    if (values["longitude"] is None) != (values["latitude"] is None):
        raise ValueError("经纬度必须成对填写或同时留空")
    identity = [values[k] for k in ("plate", "plate_type", "time", "checkpoint", "area", "longitude", "latitude")]
    record_key = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return Passage(record_key=record_key, **values)


def _read_rows(rows: Iterable, path: Path, sheet: str, result: ImportResult, epoch: datetime | None = None) -> list[Passage]:
    columns = None
    records = []
    fallback = _filename_plate(path)
    found_data = False
    for row_num, row in enumerate(rows, 1):
        if not any(_text(value) for value in row):
            continue
        if columns is None:
            mapped = {index: _HEADER_MAP[_header(value)] for index, value in enumerate(row) if _header(value) in _HEADER_MAP}
            if "time" in mapped.values() and ("plate" in mapped.values() or fallback):
                # Ambiguous duplicate mapped columns would otherwise overwrite silently.
                if len(mapped.values()) != len(set(mapped.values())):
                    result.errors.append({"source": path.name, "sheet": sheet, "row": row_num, "message": "存在对应同一字段的重复表头，请保留一列"})
                    return records
                columns = mapped
                if "plate" not in mapped.values():
                    result.warnings.append(path.name + ": 未设置车牌列，按明确车牌文件名识别单车；建议使用标准模板。")
                continue
            if row_num >= 10:
                break
            continue
        found_data = True
        try:
            records.append(_passage({field: row[index] if index < len(row) else None for index, field in columns.items()}, fallback, epoch))
        except (ValueError, TypeError, OverflowError) as exc:
            result.errors.append({"source": path.name, "sheet": sheet, "row": row_num, "message": str(exc)})
    if columns is None:
        result.errors.append({"source": path.name, "sheet": sheet, "row": 0, "message": "前 10 行未找到必需表头：车牌号、过车时间（建议使用标准模板）"})
    elif not found_data:
        result.warnings.append(path.name + (" / " + sheet if sheet else "") + ": 只有表头，没有数据行。")
    return records


def _metadata_order(record: Passage) -> tuple:
    fields = (record.vehicle_type, record.owner, record.location_tag, record.checkpoint_type)
    return (-sum(bool(v) for v in fields), fields)


def _enrich(first: Passage, second: Passage) -> Passage:
    return replace(first, **{field: getattr(first, field) or getattr(second, field) for field in ("vehicle_type", "owner", "location_tag", "checkpoint_type")})


def deduplicate(records: Iterable[Passage]) -> tuple[list[Passage], int]:
    """Keep the earliest observation for same-vehicle, same-checkpoint bursts <10s.

    Compare with the retained observation, preventing a chain of ten-second
    duplicates from collapsing hours of genuine observations. Exposed so the
    service can apply the same rule across separate import batches.
    """
    ordered = sorted(records, key=lambda r: (r.plate, r.plate_type, r.time, r.record_key, _metadata_order(r)))
    exact = {}
    count = 0
    for record in ordered:
        if record.record_key in exact:
            exact[record.record_key] = _enrich(exact[record.record_key], record)
            count += 1
        else:
            exact[record.record_key] = record
    output = []
    latest = {}
    for record in sorted(exact.values(), key=lambda r: (r.plate, r.plate_type, r.time, r.record_key)):
        key = (record.plate, record.plate_type, record.checkpoint, record.area)
        index = latest.get(key) if record.checkpoint else None
        if index is not None and 0 <= (record.when - output[index].when).total_seconds() < 10:
            output[index] = _enrich(output[index], record)
            count += 1
            continue
        output.append(record)
        if record.checkpoint:
            latest[key] = len(output) - 1
    return sorted(output, key=lambda r: (r.time, r.plate, r.plate_type, r.record_key)), count


def load_records(
    paths: Iterable[str | Path] | str | Path,
    *,
    deduplicate_input: bool = True,
) -> ImportResult:
    """Load and validate source rows.

    ``deduplicate_input`` controls only the within-call cleanup pass.  The
    default keeps the historical behaviour (exact and ten-second burst
    duplicates are removed).  Callers that combine several imports, such as
    the service's cross-batch ingestion path, can pass ``False`` to retain
    every validated candidate and run :func:`deduplicate` once over the full
    set.  In that mode ``duplicate_count`` is deliberately zero because no
    duplicate decision was made by this function.
    """
    result = ImportResult()
    candidates = []
    if isinstance(paths, (str, Path)):
        paths = [paths]
    for item in paths:
        path = Path(item)
        try:
            data = path.read_bytes()
            result.source_hashes.append(hashlib.sha256(data).hexdigest())
            suffix = path.suffix.lower()
            if suffix in (".xlsx", ".xlsm"):
                from openpyxl import load_workbook

                workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
                try:
                    for sheet in workbook.worksheets:
                        if re.sub(r"\s+", "", sheet.title) in ("填写说明", "数据说明", "使用说明", "导入说明", "说明"):
                            continue
                        candidates.extend(_read_rows(sheet.iter_rows(values_only=True), path, sheet.title, result, workbook.epoch))
                finally:
                    workbook.close()
            elif suffix == ".csv":
                try:
                    decoded = data.decode("utf-8-sig")
                except UnicodeDecodeError:
                    decoded = data.decode("gb18030")
                try:
                    dialect = csv.Sniffer().sniff(decoded[:8192], delimiters=",;\t")
                except csv.Error:
                    dialect = csv.excel
                candidates.extend(_read_rows(csv.reader(io.StringIO(decoded), dialect=dialect), path, "", result))
            else:
                raise ValueError("仅支持 .xlsx、.xlsm 和 .csv；旧版 .xls 请先另存为 .xlsx")
        except Exception as exc:
            # A bad workbook must not prevent other selected files from loading.
            result.errors.append({"source": path.name, "sheet": "", "row": 0, "message": "读取失败：" + str(exc)})
    if deduplicate_input:
        result.records, result.duplicate_count = deduplicate(candidates)
    else:
        # Keep parse order and all validated rows.  A later caller can make a
        # single deterministic decision across multiple source batches.
        result.records = candidates
        result.duplicate_count = 0
    if result.records:
        if not any(r.checkpoint or (r.longitude is not None and r.latitude is not None) for r in result.records):
            result.warnings.append("缺少精确卡口和完整坐标，无法评估疑似停留及高速停返；行政区域时间间隔不会作为停车证据。")
        if not any(r.owner for r in result.records):
            result.warnings.append("缺少企业字段，企业多车异常规则未评估。")
        if not any(r.location_tag for r in result.records):
            result.warnings.append("缺少风险地点标签，风险地点疑似停留规则未评估。")
        if not any(r.checkpoint_type or "高速" in r.checkpoint for r in result.records):
            result.warnings.append("缺少明确高速出入口语义，高速脱离停返规则可能无法评估。")
    return result
