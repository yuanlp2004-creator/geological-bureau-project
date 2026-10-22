"""Original default records and immutable triggers, applied after migrations."""

import json
import sqlite3

from .sql import _execute_sql_script
from ..modules.offline_help import HELP_TOPICS, HELP_TOPIC_ALIASES


def initialize_defaults(connection: sqlite3.Connection, now: str) -> None:
    connection.execute(
        "INSERT INTO report_templates(key, name, version, schema_json, enabled, created_at, updated_at) VALUES ('analysis-standard', '分析结果报告', 1, ?, 1, ?, ?) ON CONFLICT(key) DO UPDATE SET name=excluded.name, schema_json=excluded.schema_json, enabled=1, updated_at=excluded.updated_at",
        (json.dumps({"columns": ["report_number", "sample_name", "element", "wavelength_nm", "quantitative_signal", "calculation_profile", "qc_status"], "arrangements": ["standard", "exchange"]}, ensure_ascii=False, separators=(",", ":")), now, now),
    )
    connection.execute(
        "INSERT INTO ccd_layouts(name, frame_count, ccds_per_frame, points_per_ccd, point_width, gap_points_json, ccd_indices_json, wavelength_min, wavelength_max, allow_drift_um, created_at) "
        "VALUES ('default', 3, 2, 2048, 14.0, ?, ?, 249.4941856, 331.5919579, 300, ?) "
        "ON CONFLICT(name) DO UPDATE SET frame_count=excluded.frame_count, ccds_per_frame=excluded.ccds_per_frame, "
        "points_per_ccd=excluded.points_per_ccd, point_width=excluded.point_width, gap_points_json=excluded.gap_points_json, "
        "ccd_indices_json=excluded.ccd_indices_json, wavelength_min=excluded.wavelength_min, wavelength_max=excluded.wavelength_max, "
        "allow_drift_um=excluded.allow_drift_um",
        (
            json.dumps([700.6428833007812] * 5, separators=(",", ":")),
            json.dumps([0, 1, 2, 4, 5], separators=(",", ":")),
            now,
        ),
    )
    default_layout = connection.execute("SELECT id FROM ccd_layouts WHERE name='default'").fetchone()[0]
    connection.execute(
        "INSERT INTO dispersion_calibrations(name, ccd_layout_id, wavelength_min, wavelength_max, coefficients_json, created_at) "
        "VALUES ('default', ?, 249.4941856, 331.5919579, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET ccd_layout_id=excluded.ccd_layout_id, wavelength_min=excluded.wavelength_min, "
        "wavelength_max=excluded.wavelength_max, coefficients_json=excluded.coefficients_json, enabled=1",
        (
            default_layout,
            json.dumps(
                [
                    0.09324149042367935,
                    138.15292358398438,
                    -40272.38671875,
                    0.0052640484645962715,
                    249.77330017089844,
                    328.06829833984375,
                ],
                separators=(",", ":"),
            ),
            now,
        ),
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
        "INSERT OR IGNORE INTO method_runtime_state(id, action_state, updated_at) VALUES (1, 'idle', ?)",
        (now,),
    )
    connection.execute(
        "INSERT INTO device_profiles(name, transport, port, baud_rate, mirror, frame_count, ccds_per_frame, points_per_ccd, ccd_indices_json, point_width_um, protection_time_ms, screen_width_mm, screen_resolution_px, enabled, created_at, updated_at) "
        "VALUES ('S11 模拟器', 'simulator', 3, 460800, 0, 3, 2, 2048, ?, 14.0, 200.0, 40.9199981689453, 1920, 1, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET transport=excluded.transport, port=excluded.port, baud_rate=excluded.baud_rate, mirror=excluded.mirror, frame_count=excluded.frame_count, ccds_per_frame=excluded.ccds_per_frame, points_per_ccd=excluded.points_per_ccd, ccd_indices_json=excluded.ccd_indices_json, point_width_um=excluded.point_width_um, protection_time_ms=excluded.protection_time_ms, screen_width_mm=excluded.screen_width_mm, screen_resolution_px=excluded.screen_resolution_px, enabled=1, updated_at=excluded.updated_at",
        (json.dumps([0, 1, 2, 4, 5], separators=(",", ":")), now, now),
    )
    connection.executemany(
        "INSERT INTO mercury_reference_lines(label, wavelength_nm, relative_intensity, source_name, source_url, enabled, created_at) "
        "VALUES (?, ?, ?, 'NIST Strong Lines of Mercury', 'https://physics.nist.gov/PhysRefData/Handbook/Tables/mercurytable2.htm', 1, ?) "
        "ON CONFLICT(wavelength_nm) DO UPDATE SET label=excluded.label, relative_intensity=excluded.relative_intensity, "
        "source_name=excluded.source_name, source_url=excluded.source_url, enabled=1",
        [
            ("Hg I 253.6517 nm", 253.6517, 1000, now),
            ("Hg I 296.7280 nm", 296.7280, 250, now),
            ("Hg I 302.1498 nm", 302.1498, 70, now),
            ("Hg I 312.5668 nm", 312.5668, 90, now),
            ("Hg I 313.1548 nm", 313.1548, 80, now),
        ],
    )
    _execute_sql_script(
        connection,
        """
                CREATE TRIGGER IF NOT EXISTS method_versions_immutable_update
                BEFORE UPDATE ON method_versions
                BEGIN
                    SELECT RAISE(ABORT, 'method revisions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS method_versions_immutable_delete
                BEFORE DELETE ON method_versions
                BEGIN
                    SELECT RAISE(ABORT, 'method revisions are immutable');
                END;
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
                CREATE TRIGGER IF NOT EXISTS method_calibration_bindings_immutable_update
                BEFORE UPDATE ON method_calibration_bindings
                BEGIN
                    SELECT RAISE(ABORT, 'method calibration bindings are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS method_calibration_bindings_immutable_delete
                BEFORE DELETE ON method_calibration_bindings
                BEGIN
                    SELECT RAISE(ABORT, 'method calibration bindings are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS acquisition_sample_bands_immutable_update
                BEFORE UPDATE ON acquisition_sample_bands
                BEGIN
                    SELECT RAISE(ABORT, 'finalized acquisition bands are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS acquisition_sample_bands_immutable_delete
                BEFORE DELETE ON acquisition_sample_bands
                BEGIN
                    SELECT RAISE(ABORT, 'finalized acquisition bands are immutable');
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
                CREATE TRIGGER IF NOT EXISTS dispersion_task_frames_immutable_update
                BEFORE UPDATE ON dispersion_task_frames
                BEGIN
                    SELECT RAISE(ABORT, 'dispersion frames are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS dispersion_task_frames_immutable_delete
                BEFORE DELETE ON dispersion_task_frames
                BEGIN
                    SELECT RAISE(ABORT, 'dispersion frames are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS acquisition_samples_finalized_delete
                BEFORE DELETE ON acquisition_samples
                WHEN OLD.finalized = 1
                BEGIN
                    SELECT RAISE(ABORT, 'finalized acquisition samples are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_line_results_immutable_update
                BEFORE UPDATE ON analysis_line_results
                BEGIN
                    SELECT RAISE(ABORT, 'analysis line results are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_line_results_immutable_delete
                BEFORE DELETE ON analysis_line_results
                BEGIN
                    SELECT RAISE(ABORT, 'analysis line results are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_interventions_immutable_update
                BEFORE UPDATE ON analysis_interventions
                BEGIN
                    SELECT RAISE(ABORT, 'analysis interventions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_interventions_immutable_delete
                BEFORE DELETE ON analysis_interventions
                BEGIN
                    SELECT RAISE(ABORT, 'analysis interventions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_qc_decisions_immutable_update
                BEFORE UPDATE ON analysis_qc_decisions
                BEGIN
                    SELECT RAISE(ABORT, 'analysis QC decisions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_qc_decisions_immutable_delete
                BEFORE DELETE ON analysis_qc_decisions
                BEGIN
                    SELECT RAISE(ABORT, 'analysis QC decisions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_qc_snapshots_immutable_update
                BEFORE UPDATE ON analysis_qc_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'analysis QC snapshots are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_qc_snapshots_immutable_delete
                BEFORE DELETE ON analysis_qc_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'analysis QC snapshots are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_curve_actions_immutable_update
                BEFORE UPDATE ON analysis_curve_actions
                BEGIN
                    SELECT RAISE(ABORT, 'analysis curve actions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_curve_actions_immutable_delete
                BEFORE DELETE ON analysis_curve_actions
                BEGIN
                    SELECT RAISE(ABORT, 'analysis curve actions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_curve_adjustment_sets_immutable_update
                BEFORE UPDATE ON analysis_curve_adjustment_sets
                BEGIN
                    SELECT RAISE(ABORT, 'analysis curve adjustment sets are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_curve_adjustment_sets_immutable_delete
                BEFORE DELETE ON analysis_curve_adjustment_sets
                BEGIN
                    SELECT RAISE(ABORT, 'analysis curve adjustment sets are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_curve_snapshots_immutable_update
                BEFORE UPDATE ON analysis_curve_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'analysis curve snapshots are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_curve_snapshots_immutable_delete
                BEFORE DELETE ON analysis_curve_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'analysis curve snapshots are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_curve_results_immutable_update
                BEFORE UPDATE ON analysis_curve_results
                BEGIN
                    SELECT RAISE(ABORT, 'analysis curve results are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_curve_results_immutable_delete
                BEFORE DELETE ON analysis_curve_results
                BEGIN
                    SELECT RAISE(ABORT, 'analysis curve results are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_result_merges_immutable_update
                BEFORE UPDATE ON analysis_result_merges
                BEGIN
                    SELECT RAISE(ABORT, 'analysis result merges are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_result_merges_immutable_delete
                BEFORE DELETE ON analysis_result_merges
                BEGIN
                    SELECT RAISE(ABORT, 'analysis result merges are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_curve_print_jobs_immutable_update
                BEFORE UPDATE ON analysis_curve_print_jobs
                BEGIN
                    SELECT RAISE(ABORT, 'analysis curve print jobs are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS analysis_curve_print_jobs_immutable_delete
                BEFORE DELETE ON analysis_curve_print_jobs
                BEGIN
                    SELECT RAISE(ABORT, 'analysis curve print jobs are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS postprocessing_conversion_runs_immutable_update
                BEFORE UPDATE ON postprocessing_conversion_runs
                BEGIN
                    SELECT RAISE(ABORT, 'postprocessing conversion runs are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS postprocessing_conversion_runs_immutable_delete
                BEFORE DELETE ON postprocessing_conversion_runs
                BEGIN
                    SELECT RAISE(ABORT, 'postprocessing conversion runs are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS postprocessing_recalculation_runs_immutable_update
                BEFORE UPDATE ON postprocessing_recalculation_runs
                BEGIN
                    SELECT RAISE(ABORT, 'postprocessing recalculation runs are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS postprocessing_recalculation_runs_immutable_delete
                BEFORE DELETE ON postprocessing_recalculation_runs
                BEGIN
                    SELECT RAISE(ABORT, 'postprocessing recalculation runs are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS postprocessing_exports_immutable_update
                BEFORE UPDATE ON postprocessing_exports
                BEGIN
                    SELECT RAISE(ABORT, 'postprocessing exports are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS postprocessing_exports_immutable_delete
                BEFORE DELETE ON postprocessing_exports
                BEGIN
                    SELECT RAISE(ABORT, 'postprocessing exports are immutable');
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
                CREATE TRIGGER IF NOT EXISTS report_exports_immutable_update
                BEFORE UPDATE ON report_exports
                BEGIN
                    SELECT RAISE(ABORT, 'report exports are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS report_exports_immutable_delete
                BEFORE DELETE ON report_exports
                BEGIN
                    SELECT RAISE(ABORT, 'report exports are immutable');
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
                CREATE TRIGGER IF NOT EXISTS hardware_traces_immutable_update
                BEFORE UPDATE ON hardware_traces
                BEGIN
                    SELECT RAISE(ABORT, 'hardware traces are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS hardware_traces_immutable_delete
                BEFORE DELETE ON hardware_traces
                BEGIN
                    SELECT RAISE(ABORT, 'hardware traces are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS hardware_decisions_immutable_update
                BEFORE UPDATE ON hardware_decisions
                BEGIN
                    SELECT RAISE(ABORT, 'hardware decisions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS hardware_decisions_immutable_delete
                BEFORE DELETE ON hardware_decisions
                BEGIN
                    SELECT RAISE(ABORT, 'hardware decisions are immutable');
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
                CREATE TRIGGER IF NOT EXISTS mercury_frames_immutable_update
                BEFORE UPDATE ON mercury_frames
                BEGIN
                    SELECT RAISE(ABORT, 'mercury frames are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS mercury_frames_immutable_delete
                BEFORE DELETE ON mercury_frames
                BEGIN
                    SELECT RAISE(ABORT, 'mercury frames are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS mercury_alignment_versions_immutable_update
                BEFORE UPDATE ON mercury_alignment_versions
                BEGIN
                    SELECT RAISE(ABORT, 'mercury alignment versions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS mercury_alignment_versions_immutable_delete
                BEFORE DELETE ON mercury_alignment_versions
                BEGIN
                    SELECT RAISE(ABORT, 'mercury alignment versions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS mercury_traces_immutable_update
                BEFORE UPDATE ON mercury_traces
                BEGIN
                    SELECT RAISE(ABORT, 'mercury traces are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS mercury_traces_immutable_delete
                BEFORE DELETE ON mercury_traces
                BEGIN
                    SELECT RAISE(ABORT, 'mercury traces are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS maintenance_backups_immutable_update
                BEFORE UPDATE ON maintenance_backups
                BEGIN
                    SELECT RAISE(ABORT, 'maintenance backup records are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS maintenance_backups_immutable_delete
                BEFORE DELETE ON maintenance_backups
                BEGIN
                    SELECT RAISE(ABORT, 'maintenance backup records are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS maintenance_operations_immutable_update
                BEFORE UPDATE ON maintenance_operations
                BEGIN
                    SELECT RAISE(ABORT, 'maintenance operation records are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS maintenance_operations_immutable_delete
                BEFORE DELETE ON maintenance_operations
                BEGIN
                    SELECT RAISE(ABORT, 'maintenance operation records are immutable');
                END;
                """
    )
    help_topics = HELP_TOPICS
    # Retire only the built-in articles merged by this manual revision. Keep the
    # records for old topic URLs, without showing duplicate pages in the index.
    connection.executemany(
        "UPDATE help_topics SET enabled=0 WHERE slug=?",
        [(slug,) for slug in HELP_TOPIC_ALIASES],
    )
    connection.executemany(
        "INSERT INTO help_topics(slug, title, section, keywords_json, body, related_routes_json, updated_at, enabled) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1) ON CONFLICT(slug) DO UPDATE SET title=excluded.title, section=excluded.section, keywords_json=excluded.keywords_json, body=excluded.body, related_routes_json=excluded.related_routes_json, updated_at=excluded.updated_at, enabled=1",
        [
            (slug, title, section, json.dumps(keywords, ensure_ascii=False), body, json.dumps(routes, ensure_ascii=False), now)
            for slug, title, section, keywords, body, routes in help_topics
        ],
    )
