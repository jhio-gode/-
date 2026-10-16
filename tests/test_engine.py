from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from tvra.domain import Passage, RuleConfig
from tvra.engine import analyze


def record(key, minute=0, plate="模拟001", base="2026-10-14 10:00:00", **kwargs):
    timestamp = datetime.fromisoformat(base) + timedelta(minutes=minute)
    return Passage(record_key=key, plate=plate, time=timestamp.strftime("%Y-%m-%d %H:%M:%S"), **kwargs)


def kinds(events):
    return {e.event_type for e in events}


def test_vehicle_type_night_and_same_area_alone_are_not_abnormal():
    data = [record("a", base="2026-10-14 01:00:00", vehicle_type="危化品罐车", area="同一区"), record("b", 90, base="2026-10-14 01:00:00", vehicle_type="危化品罐车", area="同一区")]
    assert analyze(data) == []


def test_short_stop_uses_precise_checkpoint_not_area():
    events = analyze([record("a", checkpoint="模拟点"), record("b", 45, checkpoint="模拟点")])
    assert kinds(events) == {"E01"}
    event = events[0]
    assert event.level == 3 and event.score == 25
    assert event.record_keys == ["a", "b"]
    assert any("45.0" in e and "模拟点" in e for e in event.evidence)
    assert any("不能证明" in q for q in event.data_quality)


def test_coordinates_support_proximity_and_far_coordinates_do_not():
    near = [record("a", longitude=112.0, latitude=37.0), record("b", 45, longitude=112.001, latitude=37.001)]
    assert kinds(analyze(near)) == {"E01"}
    far = [near[0], replace(near[1], longitude=115.0)]
    assert not analyze(far)


def test_intermediate_different_point_prevents_false_stay():
    data = [record("a", checkpoint="甲"), record("b", 20, checkpoint="乙"), record("c", 60, checkpoint="甲")]
    assert not analyze(data)


def test_night_and_sensitive_stay_fuse_with_stable_ids():
    data = [record("a", base="2026-10-14 23:00:00", checkpoint="模拟仓库点", location_tag="烟花仓储风险点"), record("b", 45, base="2026-10-14 23:00:00", checkpoint="模拟仓库点", location_tag="烟花仓储风险点")]
    events = analyze(data)
    assert kinds(events) == {"E01", "E03", "E04"}
    assert all(e.level == 1 and e.score == 85 for e in events)
    assert [e.to_dict() for e in events] == [e.to_dict() for e in analyze(reversed(data))]
    assert all(e.model == "烟花爆竹" for e in events)


def test_crossing_night_without_actual_night_observation_is_not_night_event():
    data = [record("a", base="2026-10-14 21:00:00", checkpoint="甲", location_tag="风险地点"), record("b", 600, base="2026-10-14 21:00:00", checkpoint="甲", location_tag="风险地点")]
    assert kinds(analyze(data)) == {"E04"}


def test_negative_location_tag_is_not_a_risk_site():
    data = [record("a", checkpoint="甲", location_tag="非风险地点"), record("b", 45, checkpoint="甲", location_tag="非风险地点")]
    assert kinds(analyze(data)) == {"E01"}


def test_hazardous_tanker_long_stay_has_priority_but_type_alone_does_not():
    data = [record("a", checkpoint="甲", location_tag="危化风险点", vehicle_type="危险品罐车"), record("b", 240, checkpoint="甲", location_tag="危化风险点", vehicle_type="危险品罐车")]
    events = analyze(data)
    assert kinds(events) == {"E04"}
    assert events[0].level == 1 and events[0].score == 80


def test_highway_requires_real_directions_and_surface_stay():
    data = [record("a", checkpoint="模拟枢纽高速出口", checkpoint_type="高速出口"), record("b", 20, checkpoint="模拟地面点"), record("c", 70, checkpoint="模拟地面点"), record("d", 90, checkpoint="模拟枢纽高速入口", checkpoint_type="高速入口")]
    events = analyze(data)
    assert "E02" in kinds(events)
    highway = next(e for e in events if e.event_type == "E02")
    assert highway.level == 1 and highway.record_keys == ["a", "b", "c", "d"]
    ambiguous = [replace(r, checkpoint="一般出入口" if r.record_key in ("a", "d") else r.checkpoint, checkpoint_type="出入口" if r.record_key in ("a", "d") else "") for r in data]
    assert "E02" not in kinds(analyze(ambiguous))
    different_node = data[:-1] + [replace(data[-1], checkpoint="其他节点高速入口")]
    assert "E02" not in kinds(analyze(different_node))


def test_frequent_area_visits_require_leaving_and_returning():
    data = [record(str(i), i * 30, checkpoint="点" + str(i), area=area) for i, area in enumerate(("甲区", "乙区", "甲区", "乙区", "甲区"))]
    assert "E06" in kinds(analyze(data))
    same_area = [replace(r, area="甲区") for r in data]
    assert "E06" not in kinds(analyze(same_area))
    spaced = [replace(r, time=(datetime(2026, 10, 14) + timedelta(hours=i * 3)).isoformat(sep=" ")) for i, r in enumerate(data)]
    assert "E06" not in kinds(analyze(spaced))


def test_company_requires_independent_events_and_unique_vehicles():
    data = []
    for number in range(3):
        for n, minute in enumerate((0, 45)):
            data.append(record("{}-{}".format(number, n), minute, plate="模拟00" + str(number), checkpoint="模拟点", owner="模拟企业"))
    events = analyze(data)
    company = [e for e in events if e.event_type == "E05"]
    assert len(company) == 3
    assert all(len(e.record_keys) == 2 for e in company)
    assert all(e.level == 2 for e in company)
    assert "E05" not in kinds(analyze([replace(r, plate="同一车辆", record_key="new-" + r.record_key) for r in data]))
    plain = [replace(r, checkpoint="", area="同一区") for r in data]
    assert not analyze(plain)


def test_same_plate_different_plate_types_never_form_a_stay():
    data = [record("a", checkpoint="点", plate_type="蓝"), record("b", 45, checkpoint="点", plate_type="黄")]
    assert not analyze(data)
    data.append(record("c", 90, checkpoint="点", plate_type="蓝"))
    events = analyze(data)
    assert all(e.vehicle_key == "模拟001 [蓝]" for e in events)


def test_same_second_different_points_do_not_start_a_stay_or_return_chain():
    data = [
        record("a", checkpoint="甲"),
        record("b", checkpoint="乙"),
        record("c", 45, checkpoint="甲"),
    ]
    assert "E01" not in kinds(analyze(data))
    assert "E04" not in kinds(analyze(data))


def test_same_checkpoint_name_in_different_areas_is_not_same_place():
    data = [
        record("a", checkpoint="同名卡口", area="甲区"),
        record("b", 45, checkpoint="同名卡口", area="乙区"),
    ]
    assert not analyze(data)


def test_far_coordinates_override_a_reused_checkpoint_name():
    data = [
        record("a", checkpoint="同名卡口", longitude=112.0, latitude=37.0),
        record("b", 45, checkpoint="同名卡口", longitude=115.0, latitude=37.0),
    ]
    assert not analyze(data)


def test_highway_chain_without_return_entry_is_not_an_event():
    data = [
        record("a", checkpoint="模拟枢纽高速出口", checkpoint_type="高速出口"),
        record("b", 30, checkpoint="模拟地面点"),
        record("c", 75, checkpoint="模拟地面点"),
    ]
    assert "E02" not in kinds(analyze(data))


def test_unlabeled_same_place_is_only_generic_short_stop():
    data = [
        record("a", checkpoint="未标注点"),
        record("b", 45, checkpoint="未标注点"),
    ]
    events = analyze(data)
    assert kinds(events) == {"E01"}
    assert "E04" not in kinds(events)


def test_disjoint_episodes_do_not_accumulate_scores_over_history():
    data = [record("a", checkpoint="甲"), record("b", 45, checkpoint="甲"), record("c", 1440, checkpoint="乙"), record("d", 1485, checkpoint="乙")]
    events = analyze(data)
    assert len(events) == 2
    assert all(e.score == 25 for e in events)
    assert analyze(data + data) == events


def test_invalid_thresholds_fail_clearly():
    with pytest.raises(ValueError):
        analyze([], RuleConfig(short_stop_min=200, short_stop_max=30))
