# Internal integration contract

`tvra.domain` owns Passage, ImportResult, RuleConfig and Event dataclasses.
All times are local business timestamps, normalized as `YYYY-MM-DD HH:MM:SS`.
SQLite connections must be opened per operation for GUI background jobs.

`tvra.importer.load_records(paths) -> ImportResult`: XLSX/CSV loading, aliases,
validation and deterministic deduplication. No writes to input files.

`tvra.engine.analyze(records, config=None) -> list[Event]`: deterministic event
rules, stable identifiers. Never assert actual parking from administrative-area
time gaps. Event level 1 is highest; vehicles with no event have risk level 0.

`tvra.service.Service(data_dir)` exposes:

- import_files(paths) -> dict: new_records, record_count, duplicate_count,
  error_count, errors, event_count, batch_id, warnings.
- reanalyze() -> dict; summary() -> dict with vehicles, records, events,
  level1, level2, level3, last_import, event_types, coverage_start, coverage_end.
- list_events(filters=None) -> list[dict]. Filters: keyword, level, event_type,
  date_from, date_to. Events include Event fields plus vehicle_type and owner.
- list_vehicles(keyword='') -> list[dict]: plate, plate_type, vehicle_type, owner,
  record_count, event_count, risk_level, night_ratio, main_areas, first_seen,
  last_seen, vehicle_key. Identity is (plate, plate_type), `Passage.vehicle_key`
  is the internal lookup key; plain plate lookup is only valid when unambiguous.
- vehicle_detail(vehicle_key) -> dict | None: vehicle (above), records, events, history,
  rule_version. History is analysis/import history, never treated as new trips.
- get_settings() -> dict; save_settings(dict) -> dict (validates and reanalyzes).
- imports() -> list[dict]; close() -> None.

`tvra.reports`: export_rankings(vehicles, events, path, metadata=None) -> str;
export_vehicle_report(detail, path, metadata=None) -> str;
create_template(path) -> str. Writes only to explicitly supplied output paths.

`tvra.gui`: MainWindow(service), run_desktop(service). No import-time event loop.
GUI uses the above service APIs, and worker threads for imports/reanalysis/export.

The user requested a complete deliverable. Implement source, GUI, repeatable
packaging, synthetic demo data, tests and documentation. Do not include uploaded
real databases, logs, venv binaries or real vehicle records in release artifacts.
