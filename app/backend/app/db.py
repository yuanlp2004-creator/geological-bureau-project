from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 10


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Database:
    """SQLite gateway with one process-wide write lock and idempotent migrations."""

    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT,
                    correlation_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runtime_events_created
                    ON runtime_events(created_at DESC);
                CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS roles (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, description TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS permissions (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE NOT NULL, description TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS user_roles (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE, PRIMARY KEY(user_id, role_id));
                CREATE TABLE IF NOT EXISTS role_permissions (role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE, permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE, PRIMARY KEY(role_id, permission_id));
                CREATE TABLE IF NOT EXISTS audit_events (id INTEGER PRIMARY KEY AUTOINCREMENT, actor_user_id INTEGER REFERENCES users(id), action TEXT NOT NULL, target_type TEXT NOT NULL, target_id INTEGER, details_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at DESC);
                CREATE TABLE IF NOT EXISTS methods (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    work_type TEXT NOT NULL DEFAULT 'spectral',
                    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','deleted')),
                    current_version INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS method_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    method_id INTEGER NOT NULL REFERENCES methods(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('draft','published')),
                    payload_json TEXT NOT NULL,
                    validation_errors_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    created_by INTEGER REFERENCES users(id),
                    UNIQUE(method_id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_method_versions_method ON method_versions(method_id, version DESC);
                CREATE TABLE IF NOT EXISTS ccd_layouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    frame_count INTEGER NOT NULL,
                    ccds_per_frame INTEGER NOT NULL,
                    points_per_ccd INTEGER NOT NULL,
                    point_width REAL NOT NULL,
                    gap_points_json TEXT NOT NULL DEFAULT '[]',
                    ccd_indices_json TEXT NOT NULL DEFAULT '[]',
                    wavelength_min REAL NOT NULL DEFAULT 160,
                    wavelength_max REAL NOT NULL DEFAULT 800,
                    allow_drift_um REAL NOT NULL DEFAULT 300,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dispersion_calibrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    ccd_layout_id INTEGER REFERENCES ccd_layouts(id),
                    wavelength_min REAL NOT NULL DEFAULT 160,
                    wavelength_max REAL NOT NULL DEFAULT 800,
                    coefficients_json TEXT NOT NULL DEFAULT '[]',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS method_runtime_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    current_method_id INTEGER REFERENCES methods(id),
                    current_version INTEGER,
                    action_state TEXT NOT NULL DEFAULT 'idle',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS method_print_jobs (
                    id TEXT PRIMARY KEY,
                    method_id INTEGER NOT NULL REFERENCES methods(id),
                    method_version INTEGER NOT NULL,
                    printer_name TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('rendered','queued','completed','failed')),
                    settings_json TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    pdf_path TEXT NOT NULL,
                    output_path TEXT,
                    page_count INTEGER NOT NULL,
                    field_count INTEGER NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_method_print_jobs_method
                    ON method_print_jobs(method_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS legacy_migration_runs (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('staged','committed','failed')),
                    source_files_json TEXT NOT NULL,
                    reader_json TEXT NOT NULL,
                    staging_json TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    committed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_legacy_migration_runs_created
                    ON legacy_migration_runs(created_at DESC);
                CREATE TABLE IF NOT EXISTS legacy_import_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES legacy_migration_runs(id),
                    source_sha256 TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    legacy_key TEXT NOT NULL,
                    target_id INTEGER,
                    payload_sha256 TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_sha256, entity_type, legacy_key)
                );
                CREATE INDEX IF NOT EXISTS idx_legacy_import_entities_run
                    ON legacy_import_entities(run_id, entity_type);
                CREATE TABLE IF NOT EXISTS legacy_configuration_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE REFERENCES legacy_migration_runs(id),
                    name TEXT NOT NULL,
                    cfg_source_sha256 TEXT NOT NULL,
                    opt_source_sha256 TEXT NOT NULL,
                    cfg_json TEXT NOT NULL,
                    opt_json TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sample_queues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','ready','completed')),
                    source_sha256 TEXT UNIQUE,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sample_queue_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_id INTEGER NOT NULL REFERENCES sample_queues(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    source_name TEXT NOT NULL,
                    pre_name TEXT NOT NULL,
                    post_name TEXT,
                    repeats INTEGER NOT NULL CHECK(repeats >= 0 AND repeats <= 10),
                    expanded_bands INTEGER NOT NULL CHECK(expanded_bands >= 1),
                    spectrum_hash TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(queue_id, position)
                );
                CREATE INDEX IF NOT EXISTS idx_sample_queue_items_queue ON sample_queue_items(queue_id, position);
                CREATE TABLE IF NOT EXISTS spectrum_migration_runs (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    format TEXT NOT NULL CHECK(format IN ('cdt','cmt','edt','wdt')),
                    status TEXT NOT NULL CHECK(status IN ('staged','committed','failed')),
                    source_json TEXT NOT NULL,
                    reader_json TEXT NOT NULL,
                    staging_json TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    committed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_spectrum_migration_runs_created
                    ON spectrum_migration_runs(created_at DESC);
                CREATE TABLE IF NOT EXISTS spectrum_migration_staging_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES spectrum_migration_runs(id) ON DELETE CASCADE,
                    record_index INTEGER NOT NULL,
                    band_id INTEGER,
                    sample_no INTEGER,
                    sample_name TEXT NOT NULL DEFAULT '',
                    band_name TEXT NOT NULL DEFAULT '',
                    long_name TEXT NOT NULL DEFAULT '',
                    measure_time TEXT,
                    real_ref_step REAL,
                    frame_count INTEGER NOT NULL,
                    ccds_per_frame INTEGER NOT NULL,
                    points_per_ccd INTEGER NOT NULL,
                    ccd_count INTEGER NOT NULL,
                    ccd_indices_json TEXT NOT NULL,
                    layout_json TEXT NOT NULL,
                    ignition_json TEXT NOT NULL,
                    bad_frame_indices_json TEXT NOT NULL,
                    mean_blob BLOB,
                    burn_adcs_blob BLOB,
                    dark_adcs_blob BLOB,
                    mean_sha256 TEXT,
                    burn_sha256 TEXT,
                    dark_sha256 TEXT,
                    sampled_values_json TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    UNIQUE(run_id, record_index)
                );
                CREATE INDEX IF NOT EXISTS idx_spectrum_migration_staging_run
                    ON spectrum_migration_staging_records(run_id, record_index);
                CREATE TABLE IF NOT EXISTS spectrum_bands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    import_run_id TEXT NOT NULL REFERENCES spectrum_migration_runs(id),
                    source_sha256 TEXT NOT NULL,
                    record_index INTEGER NOT NULL,
                    format TEXT NOT NULL CHECK(format IN ('cdt','cmt','edt','wdt')),
                    band_id INTEGER,
                    sample_no INTEGER,
                    sample_name TEXT NOT NULL DEFAULT '',
                    band_name TEXT NOT NULL DEFAULT '',
                    long_name TEXT NOT NULL DEFAULT '',
                    measure_time TEXT,
                    real_ref_step REAL,
                    frame_count INTEGER NOT NULL,
                    ccds_per_frame INTEGER NOT NULL,
                    points_per_ccd INTEGER NOT NULL,
                    ccd_count INTEGER NOT NULL,
                    ccd_indices_json TEXT NOT NULL,
                    layout_json TEXT NOT NULL,
                    ignition_json TEXT NOT NULL,
                    bad_frame_indices_json TEXT NOT NULL,
                    mean_blob BLOB,
                    burn_adcs_blob BLOB,
                    dark_adcs_blob BLOB,
                    mean_sha256 TEXT,
                    burn_sha256 TEXT,
                    dark_sha256 TEXT,
                    sampled_values_json TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    UNIQUE(source_sha256, record_index)
                );
                CREATE INDEX IF NOT EXISTS idx_spectrum_bands_source
                    ON spectrum_bands(source_sha256, record_index);
                CREATE TABLE IF NOT EXISTS result_migration_runs (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    format TEXT NOT NULL CHECK(format IN ('dat','pdt')),
                    status TEXT NOT NULL CHECK(status IN ('staged','committed','failed')),
                    source_json TEXT NOT NULL,
                    parser_json TEXT NOT NULL,
                    staging_json TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    committed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_result_migration_runs_created
                    ON result_migration_runs(created_at DESC);
                CREATE TABLE IF NOT EXISTS result_migration_staging_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES result_migration_runs(id) ON DELETE CASCADE,
                    record_index INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    matrix_blob BLOB NOT NULL,
                    matrix_sha256 TEXT NOT NULL,
                    UNIQUE(run_id, record_index)
                );
                CREATE INDEX IF NOT EXISTS idx_result_migration_staging_run
                    ON result_migration_staging_records(run_id, record_index);
                CREATE TABLE IF NOT EXISTS result_matrices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    import_run_id TEXT NOT NULL REFERENCES result_migration_runs(id),
                    source_sha256 TEXT NOT NULL,
                    record_index INTEGER NOT NULL,
                    format TEXT NOT NULL CHECK(format IN ('dat','pdt')),
                    payload_json TEXT NOT NULL,
                    matrix_blob BLOB NOT NULL,
                    matrix_sha256 TEXT NOT NULL,
                    UNIQUE(source_sha256, record_index)
                );
                CREATE INDEX IF NOT EXISTS idx_result_matrices_source
                    ON result_matrices(source_sha256, record_index);
                """
            )
            # S03 was started against an S02 database before this column was
            # present. Keep initialization safe for both that database and a
            # clean install without rewriting a published migration.
            layout_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(ccd_layouts)").fetchall()
            }
            if "allow_drift_um" not in layout_columns:
                connection.execute(
                    "ALTER TABLE ccd_layouts ADD COLUMN allow_drift_um REAL NOT NULL DEFAULT 300"
                )
            queue_columns = {row["name"] for row in connection.execute("PRAGMA table_info(sample_queues)").fetchall()}
            if "source_sha256" not in queue_columns:
                connection.execute("ALTER TABLE sample_queues ADD COLUMN source_sha256 TEXT")
                connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sample_queues_source_sha256 ON sample_queues(source_sha256) WHERE source_sha256 IS NOT NULL")
            now = utc_now()
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
            connection.execute(
                "INSERT OR IGNORE INTO method_runtime_state(id, action_state, updated_at) VALUES (1, 'idle', ?)",
                (now,),
            )
            connection.executescript(
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
                """
            )
            applied = connection.execute(
                "SELECT version FROM schema_migrations WHERE version = ?", (SCHEMA_VERSION,)
            ).fetchone()
            if applied is None:
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, now),
                )
            connection.executemany(
                "INSERT INTO app_metadata(key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                [("schema_version", str(SCHEMA_VERSION), now), ("app_name", "GeoSpectrum", now)],
            )

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            connection = self.connect()
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
