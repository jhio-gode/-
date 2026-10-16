from __future__ import annotations

import csv
from datetime import datetime

from openpyxl import Workbook

from tvra.importer import load_records


def write_csv(path, rows, encoding="utf-8-sig"):
    with path.open("w", encoding=encoding, newline="") as stream:
        csv.writer(stream).writerows(rows)
    return path


def test_one_file_contains_multiple_vehicles_and_alias_headers(tmp_path):
    path = write_csv(tmp_path / "batch.csv", [
        ["号牌号码", "通过时间", "号牌颜色", "车型", "卡口名称", "所属企业"],
        ["测试A01", "2026/10/14 10:00:00", "蓝", "轻型厢货", "模拟卡口", "模拟企业"],
        ["测试B02", "2026/10/14 11:00:00", "黄", "普通客车", "模拟卡口", "模拟企业"],
    ])
    result = load_records([path])
    assert not result.errors
    assert {r.plate for r in result.records} == {"测试A01", "测试B02"}
    assert result.records[0].time == "2026-10-14 10:00:00"
    assert result.records[0].plate_type == "蓝"


def test_rejects_bad_rows_without_discarding_good_rows(tmp_path):
    path = write_csv(tmp_path / "batch.csv", [
        ["车牌号", "过车时间", "经度", "纬度"],
        ["模拟001", "2026-10-14 10:00:00", 112.1, 37.1],
        ["", "2026-10-14 10:00:00", "", ""],
        ["模拟002", "bad-date", "", ""],
        ["模拟003", "2026-10-14 10:00:00", 181, 37.1],
        ["模拟004", "2026-10-14 10:00:00", 112, ""],
        ["模拟005", "2026-10-14", "", ""],
    ])
    result = load_records(path)
    assert len(result.records) == 1
    assert [e["row"] for e in result.errors] == [3, 4, 5, 6, 7]
    assert all(e["source"] == "batch.csv" for e in result.errors)


def test_xlsx_datetime_header_offset_and_gb18030_csv(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["模拟导出说明"])
    sheet.append(["车牌号", "抓拍时间", "卡口"])
    sheet.append(["模拟001", datetime(2026, 10, 14, 12, 30), "测试点"])
    xlsx = tmp_path / "input.xlsx"
    workbook.save(xlsx)
    csv_path = write_csv(tmp_path / "input.csv", [["车牌号", "过车时间", "卡口"], ["模拟002", "2026-10-14 10:30", "测试点"]], "gb18030")
    before = xlsx.read_bytes()
    result = load_records([xlsx, csv_path])
    assert len(result.records) == 2
    assert not result.errors
    assert xlsx.read_bytes() == before


def test_dedup_exact_and_burst_are_deterministic_and_plate_type_safe(tmp_path):
    header = ["车牌号", "过车时间", "卡口", "号牌种类"]
    a = write_csv(tmp_path / "a.csv", [header,
        ["模拟001", "2026-10-14 10:00:00", "甲", "蓝"],
        ["模拟001", "2026-10-14 10:00:00", "甲", "蓝"],
        ["模拟001", "2026-10-14 10:00:09", "甲", "蓝"],
        ["模拟001", "2026-10-14 10:00:10", "甲", "蓝"],
        ["模拟001", "2026-10-14 10:00:00", "甲", "黄"],
    ])
    b = write_csv(tmp_path / "b.csv", [header, ["模拟002", "2026-10-14 10:00:00", "乙", "蓝"]])
    result = load_records([a, b])
    reverse = load_records([b, a])
    assert len(result.records) == 4
    assert result.duplicate_count == 2
    assert result.records == reverse.records
    assert {r.plate_type for r in result.records if r.plate == "模拟001"} == {"蓝", "黄"}


def test_no_checkpoint_does_not_collapse_different_timestamps(tmp_path):
    path = write_csv(tmp_path / "batch.csv", [
        ["车牌号", "过车时间", "行政区域"],
        ["模拟001", "2026-10-14 10:00:00", "甲区"],
        ["模拟001", "2026-10-14 10:00:05", "甲区"],
    ])
    result = load_records(path)
    assert len(result.records) == 2
    assert any("行政区域时间间隔不会" in w for w in result.warnings)


def test_legacy_filename_fallback_is_limited_to_a_clear_plate(tmp_path):
    path = write_csv(tmp_path / "晋A00000.csv", [["过车时间", "卡口"], ["2026-10-14 10:00", "模拟点"]])
    result = load_records(path)
    assert len(result.records) == 1
    assert result.records[0].plate == "晋A00000"
    assert any("文件名" in w for w in result.warnings)
    ambiguous = write_csv(tmp_path / "全部车辆.csv", [["过车时间", "卡口"], ["2026-10-14 10:00", "模拟点"]])
    assert not load_records(ambiguous).records


def test_timezone_normalizes_to_business_timezone(tmp_path):
    path = write_csv(tmp_path / "batch.csv", [["车牌号", "过车时间"], ["模拟001", "2026-10-14T01:30:00Z"]])
    assert load_records(path).records[0].time == "2026-10-14 09:30:00"


def test_disable_input_dedup_preserves_sub_ten_second_rows_for_cross_batch_merge(tmp_path):
    path = write_csv(tmp_path / "batch.csv", [
        ["车牌号", "过车时间", "卡口"],
        ["模拟001", "2026-10-14 09:00:00", "甲"],
        ["模拟001", "2026-10-14 09:00:09", "甲"],
        ["模拟001", "2026-10-14 09:00:10", "甲"],
    ])
    retained = load_records(path, deduplicate_input=False)
    assert [r.time for r in retained.records] == [
        "2026-10-14 09:00:00",
        "2026-10-14 09:00:09",
        "2026-10-14 09:00:10",
    ]
    assert retained.duplicate_count == 0
    collapsed = load_records(path)
    # Dedup compares every candidate with the retained observation: 09s is a
    # burst duplicate of 00s, while 10s is exactly at the ten-second boundary
    # and remains a valid observation for a later cross-batch merge.
    assert [r.time for r in collapsed.records] == [
        "2026-10-14 09:00:00",
        "2026-10-14 09:00:10",
    ]
    assert collapsed.duplicate_count == 1
