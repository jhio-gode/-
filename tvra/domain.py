from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Passage:
    record_key: str
    plate: str
    time: str
    plate_type: str = ""
    vehicle_type: str = ""
    owner: str = ""
    checkpoint: str = ""
    area: str = ""
    location_tag: str = ""
    longitude: float | None = None
    latitude: float | None = None
    checkpoint_type: str = ""

    @property
    def when(self) -> datetime:
        return datetime.fromisoformat(self.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def vehicle_key(self) -> str:
        return self.plate if not self.plate_type else self.plate + " [" + self.plate_type + "]"


@dataclass
class ImportResult:
    records: list[Passage] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    duplicate_count: int = 0
    source_hashes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class RuleConfig:
    short_stop_min: int = 30
    short_stop_max: int = 180
    near_distance_km: float = 1.0
    night_start: int = 22
    night_end: int = 6
    frequent_window_hours: int = 6
    frequent_min_visits: int = 3
    company_window_hours: int = 24
    company_min_vehicles: int = 3
    highway_return_hours: int = 6
    sensitive_stay_minutes: int = 30
    long_stay_minutes: int = 180


@dataclass
class Event:
    event_id: str
    plate: str
    event_type: str
    title: str
    level: int
    start: str
    end: str
    score: int
    evidence: list[str]
    record_keys: list[str]
    model: str = "通用"
    data_quality: list[str] = field(default_factory=list)
    vehicle_key: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
