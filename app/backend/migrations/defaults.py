"""Original default records and immutable triggers, applied after migrations."""

import hashlib
import json
import sqlite3

from .sql import _execute_sql_script
from ..modules.offline_help import HELP_TOPICS, HELP_TOPIC_ALIASES


REPORT_TEMPLATE = (
    "analysis-standard", "分析结果报告", 1, 1,
    json.dumps({
        "columns": ["report_number", "sample_name", "element", "wavelength_nm", "quantitative_signal",
                    "calculation_profile", "qc_status"],
        "arrangements": ["standard", "exchange"],
    }, separators=(",", ":")),
)
CCD_INDICES = "[0,1,2,4,5]"
WAVELENGTH_RANGE = (249.4941856, 331.5919579)
CCD_LAYOUT = (
    "default", 3, 2, 2048, 14.0, json.dumps([700.6428833007812] * 5, separators=(",", ":")),
    CCD_INDICES, *WAVELENGTH_RANGE, 300,
)
DEFAULT_CALIBRATION = (
    *WAVELENGTH_RANGE,
    json.dumps([
        0.09324149042367935, 138.15292358398438, -40272.38671875, 0.0052640484645962715,
        249.77330017089844, 328.06829833984375,
    ], separators=(",", ":")),
)
RUNTIME_STATE = (1, "idle")
SIMULATOR_PROFILE = (
    "S11 模拟器", "simulator", 3, 460800, 0, 3, 2, 2048, CCD_INDICES, 14.0, 200.0, 40.9199981689453, 1920, 1,
)
MERCURY_SOURCE = ("NIST Strong Lines of Mercury", "https://physics.nist.gov/PhysRefData/Handbook/Tables/mercurytable2.htm")
MERCURY_LINES = (
    ("Hg I 253.6517 nm", 253.6517, 1000),
    ("Hg I 296.7280 nm", 296.7280, 250),
    ("Hg I 302.1498 nm", 302.1498, 70),
    ("Hg I 312.5668 nm", 312.5668, 90),
    ("Hg I 313.1548 nm", 313.1548, 80),
)
DEFAULTS_SHA256 = hashlib.sha256(json.dumps(
    (REPORT_TEMPLATE, CCD_LAYOUT, DEFAULT_CALIBRATION, RUNTIME_STATE, SIMULATOR_PROFILE, MERCURY_SOURCE, MERCURY_LINES),
    ensure_ascii=False,
).encode("utf-8")).hexdigest()


def initialize_defaults(connection: sqlite3.Connection, now: str, *, force: bool = False) -> None:
    fingerprint = connection.execute("SELECT value FROM app_metadata WHERE key='defaults_sha256'").fetchone()
    if force or fingerprint is None or fingerprint[0] != DEFAULTS_SHA256:
        _seed_default_records(connection, now)
        connection.execute(
            "INSERT INTO app_metadata(key, value, updated_at) VALUES ('defaults_sha256', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (DEFAULTS_SHA256, now),
        )
    _refresh_help(connection, now)


def _seed_default_records(connection: sqlite3.Connection, now: str) -> None:
    connection.execute(
        "INSERT INTO report_templates(key, name, version, enabled, schema_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
        "name=excluded.name, schema_json=excluded.schema_json, enabled=excluded.enabled, updated_at=excluded.updated_at",
        (*REPORT_TEMPLATE, now, now),
    )
    connection.execute(
        "INSERT INTO ccd_layouts(name, frame_count, ccds_per_frame, points_per_ccd, point_width, gap_points_json, ccd_indices_json, wavelength_min, wavelength_max, allow_drift_um, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET frame_count=excluded.frame_count, ccds_per_frame=excluded.ccds_per_frame, "
        "points_per_ccd=excluded.points_per_ccd, point_width=excluded.point_width, gap_points_json=excluded.gap_points_json, "
        "ccd_indices_json=excluded.ccd_indices_json, wavelength_min=excluded.wavelength_min, wavelength_max=excluded.wavelength_max, "
        "allow_drift_um=excluded.allow_drift_um",
        (*CCD_LAYOUT, now),
    )
    default_layout = connection.execute("SELECT id FROM ccd_layouts WHERE name='default'").fetchone()[0]
    connection.execute(
        "INSERT INTO dispersion_calibrations(name, ccd_layout_id, wavelength_min, wavelength_max, coefficients_json, created_at) "
        "VALUES ('default', ?, ?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET ccd_layout_id=excluded.ccd_layout_id, wavelength_min=excluded.wavelength_min, "
        "wavelength_max=excluded.wavelength_max, coefficients_json=excluded.coefficients_json, enabled=1",
        (default_layout, *DEFAULT_CALIBRATION, now),
    )
    default_calibration = connection.execute(
        "SELECT id, ccd_layout_id, wavelength_min, wavelength_max, coefficients_json FROM dispersion_calibrations WHERE name='default'"
    ).fetchone()
    if default_calibration is not None:
        connection.execute(
            "INSERT OR IGNORE INTO dispersion_calibration_versions(name, version, state, calibration_id, ccd_layout_id, source_task_id, coefficients_json, residuals_json, wavelength_min, wavelength_max, residual_rms, residual_max, point_count, residual_limit_points, created_at) "
            "VALUES ('default', 1, 'published', ?, ?, NULL, ?, '[]', ?, ?, 0, 0, 0, 2, ?)",
            (
                default_calibration[0],
                default_calibration[1],
                default_calibration[4],
                default_calibration[2],
                default_calibration[3],
                now,
            ),
        )
    connection.execute(
        "INSERT OR IGNORE INTO method_runtime_state(id, action_state, updated_at) VALUES (?, ?, ?)",
        (*RUNTIME_STATE, now),
    )
    connection.execute(
        "INSERT OR IGNORE INTO device_profiles(name, transport, port, baud_rate, mirror, frame_count, ccds_per_frame, points_per_ccd, ccd_indices_json, point_width_um, protection_time_ms, screen_width_mm, screen_resolution_px, enabled, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (*SIMULATOR_PROFILE, now, now),
    )
    connection.executemany(
        "INSERT INTO mercury_reference_lines(label, wavelength_nm, relative_intensity, source_name, source_url, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?) "
        "ON CONFLICT(wavelength_nm) DO UPDATE SET label=excluded.label, relative_intensity=excluded.relative_intensity, "
        "source_name=excluded.source_name, source_url=excluded.source_url, enabled=1",
        [(*line, *MERCURY_SOURCE, now) for line in MERCURY_LINES],
    )


IMMUTABLE_TABLES = {
    "method_versions": "method revisions are immutable",
    "method_calibration_bindings": "method calibration bindings are immutable",
    "acquisition_sample_bands": "finalized acquisition bands are immutable",
    "dispersion_task_frames": "dispersion frames are immutable",
    "analysis_line_results": "analysis line results are immutable",
    "analysis_interventions": "analysis interventions are immutable",
    "analysis_qc_decisions": "analysis QC decisions are immutable",
    "analysis_qc_snapshots": "analysis QC snapshots are immutable",
    "analysis_curve_actions": "analysis curve actions are immutable",
    "analysis_curve_adjustment_sets": "analysis curve adjustment sets are immutable",
    "analysis_curve_snapshots": "analysis curve snapshots are immutable",
    "analysis_curve_results": "analysis curve results are immutable",
    "analysis_result_merges": "analysis result merges are immutable",
    "analysis_curve_print_jobs": "analysis curve print jobs are immutable",
    "postprocessing_conversion_runs": "postprocessing conversion runs are immutable",
    "postprocessing_recalculation_runs": "postprocessing recalculation runs are immutable",
    "postprocessing_exports": "postprocessing exports are immutable",
    "report_exports": "report exports are immutable",
    "hardware_traces": "hardware traces are immutable",
    "hardware_decisions": "hardware decisions are immutable",
    "mercury_frames": "mercury frames are immutable",
    "mercury_alignment_versions": "mercury alignment versions are immutable",
    "mercury_traces": "mercury traces are immutable",
    "maintenance_backups": "maintenance backup records are immutable",
    "maintenance_operations": "maintenance operation records are immutable",
}


def install_triggers(connection: sqlite3.Connection) -> None:
    for table, message in IMMUTABLE_TABLES.items():
        for operation in ("UPDATE", "DELETE"):
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_{operation.lower()} "
                f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, '{message}'); END;"
            )
    _execute_sql_script(
        connection,
        """
                CREATE TRIGGER IF NOT EXISTS dispersion_calibration_versions_immutable_update
                BEFORE UPDATE ON dispersion_calibration_versions
                WHEN OLD.state = 'published'
                BEGIN
                    SELECT RAISE(ABORT, 'published calibration versions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS dispersion_calibration_versions_immutable_delete
                BEFORE DELETE ON dispersion_calibration_versions
                WHEN OLD.state = 'published'
                BEGIN
                    SELECT RAISE(ABORT, 'published calibration versions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS acquisition_frames_raw_immutable_update
                BEFORE UPDATE ON acquisition_frames
                WHEN OLD.points_blob IS NOT NEW.points_blob
                  OR OLD.points_sha256 IS NOT NEW.points_sha256
                  OR OLD.raw_transfer_sha256 IS NOT NEW.raw_transfer_sha256
                  OR OLD.damaged IS NOT NEW.damaged
                  OR OLD.damage_code IS NOT NEW.damage_code
                BEGIN
                    SELECT RAISE(ABORT, 'acquisition frame payload is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS dispersion_task_frames_storage_insert
                BEFORE INSERT ON dispersion_task_frames
                WHEN NEW.points_blob IS NULL
                  OR NEW.points_count <= 0
                  OR NEW.compression <> 'zlib'
                  OR NEW.points_sha256 IS NULL
                  OR NEW.raw_transfer_sha256 IS NULL
                  OR NEW.raw_byte_length <= 0
                BEGIN
                    SELECT RAISE(ABORT, 'dispersion frame storage contract failed');
                END;
                CREATE TRIGGER IF NOT EXISTS acquisition_samples_finalized_delete
                BEFORE DELETE ON acquisition_samples
                WHEN OLD.finalized = 1
                BEGIN
                    SELECT RAISE(ABORT, 'finalized acquisition samples are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS reports_model_immutable_update
                BEFORE UPDATE ON reports
                WHEN OLD.report_number IS NOT NEW.report_number
                  OR OLD.version IS NOT NEW.version
                  OR OLD.template_id IS NOT NEW.template_id
                  OR OLD.source_run_ids_json IS NOT NEW.source_run_ids_json
                  OR OLD.filter_json IS NOT NEW.filter_json
                  OR OLD.arrangement IS NOT NEW.arrangement
                  OR OLD.model_json IS NOT NEW.model_json
                  OR OLD.model_sha256 IS NOT NEW.model_sha256
                BEGIN
                    SELECT RAISE(ABORT, 'report models are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS reports_immutable_delete
                BEFORE DELETE ON reports
                BEGIN
                    SELECT RAISE(ABORT, 'reports are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS hardware_frames_raw_immutable_update
                BEFORE UPDATE ON hardware_frames
                WHEN OLD.points_blob IS NOT NEW.points_blob
                  OR OLD.points_sha256 IS NOT NEW.points_sha256
                  OR OLD.raw_transfer_sha256 IS NOT NEW.raw_transfer_sha256
                  OR OLD.raw_byte_length IS NOT NEW.raw_byte_length
                  OR OLD.damaged IS NOT NEW.damaged
                  OR OLD.damage_code IS NOT NEW.damage_code
                BEGIN
                    SELECT RAISE(ABORT, 'hardware frame payload is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS hardware_frames_immutable_delete
                BEFORE DELETE ON hardware_frames
                BEGIN
                    SELECT RAISE(ABORT, 'hardware frames are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS hardware_plan_core_immutable_update
                BEFORE UPDATE ON hardware_plan_steps
                WHEN OLD.angle_deg IS NOT NEW.angle_deg
                  OR OLD.wavelength_nm IS NOT NEW.wavelength_nm
                  OR OLD.priority IS NOT NEW.priority
                  OR OLD.key_band IS NOT NEW.key_band
                  OR OLD.expected_peak_position IS NOT NEW.expected_peak_position
                BEGIN
                    SELECT RAISE(ABORT, 'hardware turn plan is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS mercury_reference_lines_immutable_update
                BEFORE UPDATE ON mercury_reference_lines
                WHEN OLD.label IS NOT NEW.label
                  OR OLD.wavelength_nm IS NOT NEW.wavelength_nm
                  OR OLD.relative_intensity IS NOT NEW.relative_intensity
                  OR OLD.source_name IS NOT NEW.source_name
                  OR OLD.source_url IS NOT NEW.source_url
                BEGIN
                    SELECT RAISE(ABORT, 'mercury reference line facts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS mercury_session_line_core_immutable_update
                BEFORE UPDATE ON mercury_session_lines
                WHEN OLD.reference_line_id IS NOT NEW.reference_line_id
                  OR OLD.wavelength_nm IS NOT NEW.wavelength_nm
                  OR OLD.expected_ccd_index IS NOT NEW.expected_ccd_index
                  OR OLD.expected_position IS NOT NEW.expected_position
                BEGIN
                    SELECT RAISE(ABORT, 'mercury session line selection is immutable');
                END;
                """
    )


HELP_RECORDS = {
    slug: (title, section, json.dumps(keywords, ensure_ascii=False), body, json.dumps(routes, ensure_ascii=False), 1)
    for slug, title, section, keywords, body, routes in HELP_TOPICS
}


def _refresh_help(connection: sqlite3.Connection, now: str) -> None:
    slugs = (*HELP_RECORDS, *HELP_TOPIC_ALIASES)
    placeholders = ",".join("?" for _ in slugs)
    existing = {
        row[0]: tuple(row)[1:]
        for row in connection.execute(
            "SELECT slug, title, section, keywords_json, body, related_routes_json, enabled "
            f"FROM help_topics WHERE slug IN ({placeholders})", slugs,
        )
    }
    # Retire only the built-in articles merged by this manual revision. Keep the
    # records for old topic URLs, without showing duplicate pages in the index.
    retired = [(slug,) for slug in HELP_TOPIC_ALIASES if slug in existing and existing[slug][-1]]
    if retired:
        connection.executemany("UPDATE help_topics SET enabled=0 WHERE slug=?", retired)
    changed = [(slug, *record, now) for slug, record in HELP_RECORDS.items() if existing.get(slug) != record]
    if changed:
        connection.executemany(
            "INSERT INTO help_topics(slug, title, section, keywords_json, body, related_routes_json, enabled, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(slug) DO UPDATE SET "
            "title=excluded.title, section=excluded.section, keywords_json=excluded.keywords_json, body=excluded.body, "
            "related_routes_json=excluded.related_routes_json, enabled=excluded.enabled, updated_at=excluded.updated_at",
            changed,
        )
