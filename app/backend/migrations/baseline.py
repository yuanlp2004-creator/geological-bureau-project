"""Original baseline schema and pre-migration compatibility additions."""

import sqlite3

from .sql import _execute_sql_script, _columns


def create_baseline(connection: sqlite3.Connection) -> None:
    _execute_sql_script(
        connection,
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
                CREATE TABLE IF NOT EXISTS device_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    transport TEXT NOT NULL CHECK(transport IN ('simulator','serial')),
                    port INTEGER NOT NULL CHECK(port >= 1 AND port <= 256),
                    baud_rate INTEGER NOT NULL,
                    mirror INTEGER NOT NULL DEFAULT 0 CHECK(mirror IN (0,1)),
                    frame_count INTEGER NOT NULL CHECK(frame_count >= 1 AND frame_count <= 32),
                    ccds_per_frame INTEGER NOT NULL CHECK(ccds_per_frame >= 1 AND ccds_per_frame <= 8),
                    points_per_ccd INTEGER NOT NULL CHECK(points_per_ccd >= 1 AND points_per_ccd <= 4096),
                    ccd_indices_json TEXT NOT NULL,
                    point_width_um REAL NOT NULL,
                    protection_time_ms REAL NOT NULL,
                    screen_width_mm REAL NOT NULL,
                    screen_resolution_px INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_device_profiles_enabled ON device_profiles(enabled, id);
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
                CREATE TABLE IF NOT EXISTS dispersion_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','pre_excitation','burn','dark','paused','stopping','completed','failed','stopped')),
                    paused_from TEXT,
                    device_profile_id INTEGER NOT NULL REFERENCES device_profiles(id),
                    ccd_layout_id INTEGER NOT NULL REFERENCES ccd_layouts(id),
                    method_id INTEGER REFERENCES methods(id),
                    method_version INTEGER,
                    frame_count INTEGER NOT NULL CHECK(frame_count >= 1 AND frame_count <= 255),
                    dark_frame_count INTEGER NOT NULL DEFAULT 0 CHECK(dark_frame_count >= 0 AND dark_frame_count <= 20),
                    pre_excitation_seconds REAL NOT NULL DEFAULT 3,
                    sampling_period_seconds REAL NOT NULL DEFAULT 1,
                    residual_limit_points REAL NOT NULL DEFAULT 2,
                    ccd_indices_json TEXT NOT NULL,
                    condition_json TEXT NOT NULL DEFAULT '{}',
                    adapter_session_id TEXT,
                    burn_frames_captured INTEGER NOT NULL DEFAULT 0,
                    dark_frames_captured INTEGER NOT NULL DEFAULT 0,
                    last_frame_index INTEGER,
                    last_event_json TEXT,
                    failure_code TEXT,
                    failure_message TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_dispersion_tasks_status ON dispersion_tasks(status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS dispersion_task_frames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES dispersion_tasks(id) ON DELETE CASCADE,
                    phase TEXT NOT NULL CHECK(phase IN ('burn','dark')),
                    frame_index INTEGER NOT NULL CHECK(frame_index >= 0),
                    ccd_index INTEGER NOT NULL CHECK(ccd_index >= 0),
                    points_blob BLOB NOT NULL,
                    points_count INTEGER NOT NULL CHECK(points_count > 0),
                    dtype TEXT NOT NULL DEFAULT 'uint16' CHECK(dtype = 'uint16'),
                    endianness TEXT NOT NULL DEFAULT 'little' CHECK(endianness = 'little'),
                    compression TEXT NOT NULL DEFAULT 'zlib' CHECK(compression = 'zlib'),
                    points_sha256 TEXT NOT NULL,
                    raw_transfer_sha256 TEXT NOT NULL,
                    headers_json TEXT NOT NULL DEFAULT '[]',
                    raw_byte_length INTEGER NOT NULL CHECK(raw_byte_length > 0),
                    virtual_time_ms REAL NOT NULL DEFAULT 0,
                    captured_at TEXT NOT NULL,
                    UNIQUE(task_id, phase, frame_index, ccd_index)
                );
                CREATE INDEX IF NOT EXISTS idx_dispersion_task_frames_task ON dispersion_task_frames(task_id, phase, frame_index, ccd_index);
                CREATE TABLE IF NOT EXISTS dispersion_task_lines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES dispersion_tasks(id) ON DELETE CASCADE,
                    element TEXT NOT NULL,
                    wavelength_nm REAL NOT NULL,
                    ccd_index INTEGER NOT NULL CHECK(ccd_index >= 0),
                    expected_position REAL,
                    located_position REAL,
                    saved_position REAL,
                    position_state TEXT NOT NULL DEFAULT 'pending' CHECK(position_state IN ('pending','located','saved')),
                    position_source TEXT,
                    position_frame_id INTEGER REFERENCES dispersion_task_frames(id),
                    adjustment_points REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, element, wavelength_nm, ccd_index)
                );
                CREATE INDEX IF NOT EXISTS idx_dispersion_task_lines_task ON dispersion_task_lines(task_id, wavelength_nm, ccd_index);
                CREATE TABLE IF NOT EXISTS dispersion_calibration_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('draft','published','superseded')),
                    calibration_id INTEGER REFERENCES dispersion_calibrations(id),
                    ccd_layout_id INTEGER NOT NULL REFERENCES ccd_layouts(id),
                    source_task_id INTEGER REFERENCES dispersion_tasks(id),
                    coefficients_json TEXT NOT NULL,
                    residuals_json TEXT NOT NULL DEFAULT '[]',
                    wavelength_min REAL NOT NULL,
                    wavelength_max REAL NOT NULL,
                    residual_rms REAL NOT NULL,
                    residual_max REAL NOT NULL,
                    point_count INTEGER NOT NULL,
                    residual_limit_points REAL NOT NULL,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    UNIQUE(name, version)
                );
                CREATE INDEX IF NOT EXISTS idx_dispersion_calibration_versions_state ON dispersion_calibration_versions(state, ccd_layout_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS method_calibration_bindings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    method_version_id INTEGER NOT NULL UNIQUE REFERENCES method_versions(id),
                    method_id INTEGER NOT NULL REFERENCES methods(id),
                    method_version INTEGER NOT NULL,
                    calibration_version_id INTEGER NOT NULL REFERENCES dispersion_calibration_versions(id),
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    UNIQUE(method_id, method_version, calibration_version_id)
                );
                CREATE INDEX IF NOT EXISTS idx_method_calibration_bindings_calibration ON method_calibration_bindings(calibration_version_id);
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
                CREATE TABLE IF NOT EXISTS acquisition_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_kind TEXT NOT NULL CHECK(task_kind IN ('evaporation','sample')),
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','countdown','pre_excitation','burn','dark','between_repeats','paused','stopping','completed','failed','stopped')),
                    paused_from TEXT,
                    device_profile_id INTEGER NOT NULL REFERENCES device_profiles(id),
                    ccd_layout_id INTEGER NOT NULL REFERENCES ccd_layouts(id),
                    method_version_id INTEGER REFERENCES method_versions(id),
                    method_id INTEGER REFERENCES methods(id),
                    method_version INTEGER,
                    queue_id INTEGER REFERENCES sample_queues(id) ON DELETE SET NULL,
                    queue_item_id INTEGER REFERENCES sample_queue_items(id) ON DELETE SET NULL,
                    sample_name TEXT NOT NULL DEFAULT '',
                    sample_kind TEXT NOT NULL CHECK(sample_kind IN ('evaporation','blank','normal','standard','test','preheat')),
                    naming_mode TEXT NOT NULL CHECK(naming_mode IN ('pre_recorded','temporary','post')),
                    storage_mode TEXT NOT NULL CHECK(storage_mode IN ('averaged','full_interval')),
                    repeat_count INTEGER NOT NULL DEFAULT 1 CHECK(repeat_count >= 1 AND repeat_count <= 10),
                    current_repeat_index INTEGER NOT NULL DEFAULT 0 CHECK(current_repeat_index >= 0),
                    completed_repeats INTEGER NOT NULL DEFAULT 0 CHECK(completed_repeats >= 0),
                    burn_frame_count INTEGER NOT NULL CHECK(burn_frame_count >= 1 AND burn_frame_count <= 255),
                    dark_frame_count INTEGER NOT NULL DEFAULT 0 CHECK(dark_frame_count >= 0 AND dark_frame_count <= 20),
                    countdown_seconds REAL NOT NULL DEFAULT 0 CHECK(countdown_seconds >= 0 AND countdown_seconds <= 600),
                    countdown_remaining REAL NOT NULL DEFAULT 0 CHECK(countdown_remaining >= 0),
                    pre_excitation_seconds REAL NOT NULL DEFAULT 0 CHECK(pre_excitation_seconds >= 0 AND pre_excitation_seconds <= 600),
                    sampling_period_seconds REAL NOT NULL DEFAULT 1 CHECK(sampling_period_seconds > 0 AND sampling_period_seconds <= 60),
                    burn_cycle_seconds REAL NOT NULL DEFAULT 1 CHECK(burn_cycle_seconds > 0 AND burn_cycle_seconds <= 60),
                    dark_cycle_seconds REAL NOT NULL DEFAULT 1 CHECK(dark_cycle_seconds > 0 AND dark_cycle_seconds <= 60),
                    ccd_indices_json TEXT NOT NULL,
                    excitation_condition_json TEXT NOT NULL DEFAULT '{}',
                    evaporation_condition_json TEXT NOT NULL DEFAULT '{}',
                    simulator_json TEXT NOT NULL DEFAULT '{}',
                    adapter_session_id TEXT,
                    burn_frames_captured INTEGER NOT NULL DEFAULT 0,
                    dark_frames_captured INTEGER NOT NULL DEFAULT 0,
                    last_event_json TEXT,
                    last_message TEXT NOT NULL DEFAULT '',
                    result_sha256 TEXT,
                    failure_code TEXT,
                    failure_message TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_acquisition_tasks_status ON acquisition_tasks(status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_acquisition_tasks_queue ON acquisition_tasks(queue_id, queue_item_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS acquisition_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES acquisition_tasks(id) ON DELETE CASCADE,
                    queue_item_id INTEGER REFERENCES sample_queue_items(id) ON DELETE SET NULL,
                    repeat_index INTEGER NOT NULL CHECK(repeat_index >= 0),
                    sample_name_original TEXT NOT NULL DEFAULT '',
                    sample_name TEXT NOT NULL DEFAULT '',
                    sample_kind TEXT NOT NULL CHECK(sample_kind IN ('evaporation','blank','normal','standard','test','preheat')),
                    storage_mode TEXT NOT NULL CHECK(storage_mode IN ('averaged','full_interval')),
                    status TEXT NOT NULL CHECK(status IN ('collecting','completed','failed','stopped')),
                    finalized INTEGER NOT NULL DEFAULT 0 CHECK(finalized IN (0,1)),
                    result_sha256 TEXT,
                    failure_code TEXT,
                    failure_message TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, repeat_index)
                );
                CREATE INDEX IF NOT EXISTS idx_acquisition_samples_task ON acquisition_samples(task_id, repeat_index);
                CREATE TABLE IF NOT EXISTS acquisition_frames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES acquisition_tasks(id) ON DELETE CASCADE,
                    sample_id INTEGER NOT NULL REFERENCES acquisition_samples(id) ON DELETE CASCADE,
                    repeat_index INTEGER NOT NULL CHECK(repeat_index >= 0),
                    phase TEXT NOT NULL CHECK(phase IN ('burn','dark')),
                    frame_index INTEGER NOT NULL CHECK(frame_index >= 0),
                    ccd_index INTEGER NOT NULL CHECK(ccd_index >= 0),
                    points_blob BLOB,
                    points_count INTEGER NOT NULL DEFAULT 0 CHECK(points_count >= 0),
                    dtype TEXT NOT NULL DEFAULT 'uint16' CHECK(dtype = 'uint16'),
                    endianness TEXT NOT NULL DEFAULT 'little' CHECK(endianness = 'little'),
                    points_sha256 TEXT,
                    raw_transfer_sha256 TEXT,
                    raw_byte_length INTEGER NOT NULL DEFAULT 0,
                    headers_json TEXT NOT NULL DEFAULT '[]',
                    virtual_time_ms REAL NOT NULL DEFAULT 0,
                    peak_value REAL,
                    peak_position INTEGER,
                    integral_value REAL,
                    interval_label TEXT,
                    damaged INTEGER NOT NULL DEFAULT 0 CHECK(damaged IN (0,1)),
                    damage_code TEXT,
                    damage_message TEXT,
                    captured_at TEXT NOT NULL,
                    UNIQUE(task_id, repeat_index, phase, frame_index, ccd_index)
                );
                CREATE INDEX IF NOT EXISTS idx_acquisition_frames_task ON acquisition_frames(task_id, repeat_index, phase, frame_index, ccd_index);
                CREATE TABLE IF NOT EXISTS acquisition_sample_bands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sample_id INTEGER NOT NULL REFERENCES acquisition_samples(id) ON DELETE CASCADE,
                    ccd_index INTEGER NOT NULL CHECK(ccd_index >= 0),
                    storage_mode TEXT NOT NULL CHECK(storage_mode IN ('averaged','full_interval')),
                    points_count INTEGER NOT NULL CHECK(points_count > 0),
                    burn_frame_count INTEGER NOT NULL CHECK(burn_frame_count > 0),
                    dark_frame_count INTEGER NOT NULL CHECK(dark_frame_count >= 0),
                    mean_blob BLOB NOT NULL,
                    mean_dtype TEXT NOT NULL DEFAULT 'float32' CHECK(mean_dtype = 'float32'),
                    endianness TEXT NOT NULL DEFAULT 'little' CHECK(endianness = 'little'),
                    mean_sha256 TEXT NOT NULL,
                    burn_frames_blob BLOB,
                    burn_sha256 TEXT,
                    dark_frames_blob BLOB,
                    dark_sha256 TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(sample_id, ccd_index)
                );
                CREATE INDEX IF NOT EXISTS idx_acquisition_bands_sample ON acquisition_sample_bands(sample_id, ccd_index);
                CREATE TABLE IF NOT EXISTS acquisition_intervals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES acquisition_tasks(id) ON DELETE CASCADE,
                    repeat_index INTEGER NOT NULL CHECK(repeat_index >= 0),
                    label TEXT NOT NULL,
                    start_frame_index INTEGER NOT NULL CHECK(start_frame_index >= 0),
                    end_frame_index INTEGER NOT NULL CHECK(end_frame_index >= start_frame_index),
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, repeat_index, label)
                );
                CREATE INDEX IF NOT EXISTS idx_acquisition_intervals_task ON acquisition_intervals(task_id, repeat_index, start_frame_index);
                CREATE TABLE IF NOT EXISTS acquisition_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES acquisition_tasks(id) ON DELETE CASCADE,
                    level TEXT NOT NULL CHECK(level IN ('info','warning','error','success')),
                    code TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_acquisition_messages_task ON acquisition_messages(task_id, id);
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','running','paused','completed','cancelled','failed')),
                    method_id INTEGER NOT NULL REFERENCES methods(id),
                    method_version_id INTEGER NOT NULL REFERENCES method_versions(id),
                    method_version INTEGER NOT NULL,
                    calculation_profile TEXT NOT NULL CHECK(calculation_profile IN ('legacy_2_0_2','modern_v1')),
                    slow_mode INTEGER NOT NULL DEFAULT 0 CHECK(slow_mode IN (0,1)),
                    intervention_timeout_seconds REAL NOT NULL CHECK(intervention_timeout_seconds > 0),
                    current_sample_position INTEGER NOT NULL DEFAULT 0 CHECK(current_sample_position >= 0),
                    current_line_position INTEGER NOT NULL DEFAULT 0 CHECK(current_line_position >= 0),
                    input_snapshot_json TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL,
                    result_sha256 TEXT,
                    failure_code TEXT,
                    failure_message TEXT,
                    failure_details_json TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_runs_status ON analysis_runs(status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS analysis_run_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL CHECK(position >= 0),
                    acquisition_sample_id INTEGER NOT NULL REFERENCES acquisition_samples(id),
                    sample_name TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL,
                    result_matrix_json TEXT,
                    result_sha256 TEXT,
                    completed_at TEXT,
                    UNIQUE(run_id, position),
                    UNIQUE(run_id, acquisition_sample_id)
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_run_samples_run ON analysis_run_samples(run_id, position);
                CREATE TABLE IF NOT EXISTS analysis_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL CHECK(sequence >= 1),
                    sample_position INTEGER NOT NULL CHECK(sample_position >= 0),
                    line_position INTEGER NOT NULL CHECK(line_position >= 0),
                    line_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','accepted','discarded','cancelled')),
                    automatic_position INTEGER NOT NULL,
                    accepted_position INTEGER,
                    window_start INTEGER NOT NULL,
                    window_end INTEGER NOT NULL,
                    spectrum_window_json TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    deadline_at TEXT NOT NULL,
                    resolved_at TEXT,
                    UNIQUE(run_id, sequence)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_checkpoint_pending ON analysis_checkpoints(run_id) WHERE status='pending';
                CREATE TABLE IF NOT EXISTS analysis_interventions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    checkpoint_id INTEGER NOT NULL REFERENCES analysis_checkpoints(id),
                    action TEXT NOT NULL CHECK(action IN ('accept','discard')),
                    before_position INTEGER NOT NULL,
                    after_position INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    actor_user_id INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_interventions_run ON analysis_interventions(run_id, id);
                CREATE TABLE IF NOT EXISTS analysis_line_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    sample_position INTEGER NOT NULL CHECK(sample_position >= 0),
                    line_position INTEGER NOT NULL CHECK(line_position >= 0),
                    line_id TEXT NOT NULL,
                    line_type TEXT NOT NULL,
                    element TEXT NOT NULL,
                    wavelength_nm REAL NOT NULL,
                    ccd_index INTEGER NOT NULL,
                    expected_position REAL NOT NULL,
                    peak_position INTEGER NOT NULL,
                    peak_height REAL NOT NULL,
                    background REAL NOT NULL,
                    net_signal REAL NOT NULL,
                    gaussian_center REAL,
                    gaussian_peak_height REAL,
                    gaussian_sigma REAL,
                    gaussian_area REAL,
                    quantitative_signal REAL NOT NULL,
                    calculation_profile TEXT NOT NULL,
                    intervention_id INTEGER REFERENCES analysis_interventions(id),
                    intermediates_json TEXT NOT NULL,
                    result_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, sample_position, line_position)
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_line_results_run ON analysis_line_results(run_id, sample_position, line_position);
                CREATE TABLE IF NOT EXISTS analysis_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    level TEXT NOT NULL CHECK(level IN ('info','warning','error','success')),
                    code TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_messages_run ON analysis_messages(run_id, id);
                CREATE TABLE IF NOT EXISTS analysis_qc_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    acquisition_task_id INTEGER NOT NULL REFERENCES acquisition_tasks(id),
                    line_id TEXT NOT NULL,
                    line_result_id INTEGER REFERENCES analysis_line_results(id),
                    action TEXT NOT NULL CHECK(action IN ('accept','exclude','restore')),
                    before_included INTEGER CHECK(before_included IN (0,1)),
                    after_included INTEGER CHECK(after_included IN (0,1)),
                    reason TEXT NOT NULL,
                    actor_user_id INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_qc_decisions_run ON analysis_qc_decisions(run_id, acquisition_task_id, line_id, id);
                CREATE TABLE IF NOT EXISTS analysis_qc_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL CHECK(sequence >= 1),
                    groups_json TEXT NOT NULL,
                    publishable INTEGER NOT NULL CHECK(publishable IN (0,1)),
                    result_sha256 TEXT NOT NULL,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_qc_snapshots_run ON analysis_qc_snapshots(run_id, sequence DESC);
                CREATE TABLE IF NOT EXISTS analysis_curve_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    line_id TEXT NOT NULL,
                    qc_snapshot_id INTEGER NOT NULL REFERENCES analysis_qc_snapshots(id),
                    action TEXT NOT NULL CHECK(action IN ('set_fit','set_coordinate','set_active','adjust','restore','restore_all')),
                    point_index INTEGER,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    actor_user_id INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_curve_actions_run ON analysis_curve_actions(run_id, line_id, qc_snapshot_id, id);
                CREATE TABLE IF NOT EXISTS analysis_curve_adjustment_sets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    line_id TEXT NOT NULL,
                    qc_snapshot_id INTEGER NOT NULL REFERENCES analysis_qc_snapshots(id),
                    sequence INTEGER NOT NULL CHECK(sequence >= 1),
                    fit_mode TEXT NOT NULL CHECK(fit_mode IN ('linear','quadratic','cubic','spline')),
                    coordinate_type TEXT NOT NULL CHECK(coordinate_type IN ('normal','logarithmic')),
                    points_json TEXT NOT NULL,
                    workspace_sha256 TEXT NOT NULL,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, line_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_curve_adjustments_run ON analysis_curve_adjustment_sets(run_id, line_id, sequence DESC);
                CREATE TABLE IF NOT EXISTS analysis_curve_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    line_id TEXT NOT NULL,
                    qc_snapshot_id INTEGER NOT NULL REFERENCES analysis_qc_snapshots(id),
                    adjustment_set_id INTEGER NOT NULL REFERENCES analysis_curve_adjustment_sets(id),
                    sequence INTEGER NOT NULL CHECK(sequence >= 1),
                    fit_mode TEXT NOT NULL CHECK(fit_mode IN ('linear','quadratic','cubic','spline')),
                    coordinate_type TEXT NOT NULL CHECK(coordinate_type IN ('normal','logarithmic')),
                    points_json TEXT NOT NULL,
                    fit_json TEXT NOT NULL,
                    diagnostics_json TEXT NOT NULL,
                    chart_json TEXT NOT NULL,
                    publishable INTEGER NOT NULL CHECK(publishable IN (0,1)),
                    result_sha256 TEXT NOT NULL,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, line_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_curve_snapshots_run ON analysis_curve_snapshots(run_id, line_id, sequence DESC);
                CREATE TABLE IF NOT EXISTS analysis_active_curves (
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    line_id TEXT NOT NULL,
                    curve_snapshot_id INTEGER NOT NULL REFERENCES analysis_curve_snapshots(id),
                    updated_by INTEGER REFERENCES users(id),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, line_id)
                );
                CREATE TABLE IF NOT EXISTS analysis_curve_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    curve_snapshot_id INTEGER NOT NULL REFERENCES analysis_curve_snapshots(id),
                    acquisition_task_id INTEGER NOT NULL REFERENCES acquisition_tasks(id),
                    sample_name TEXT NOT NULL,
                    sample_kind TEXT NOT NULL,
                    is_standard INTEGER NOT NULL CHECK(is_standard IN (0,1)),
                    standard_value REAL,
                    effective_count INTEGER NOT NULL CHECK(effective_count >= 0),
                    intensity REAL NOT NULL,
                    calculated_value REAL NOT NULL,
                    result_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(curve_snapshot_id, acquisition_task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_curve_results_run ON analysis_curve_results(run_id, curve_snapshot_id, acquisition_task_id);
                CREATE TABLE IF NOT EXISTS analysis_result_merges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL CHECK(sequence >= 1),
                    curve_snapshot_ids_json TEXT NOT NULL,
                    results_json TEXT NOT NULL,
                    result_sha256 TEXT NOT NULL,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_result_merges_run ON analysis_result_merges(run_id, sequence DESC);
                CREATE TABLE IF NOT EXISTS analysis_curve_print_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    curve_snapshot_id INTEGER NOT NULL REFERENCES analysis_curve_snapshots(id),
                    mode TEXT NOT NULL CHECK(mode IN ('image','text')),
                    request_json TEXT NOT NULL,
                    content_blob BLOB NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    byte_length INTEGER NOT NULL CHECK(byte_length > 0),
                    actor_user_id INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_curve_print_jobs_run ON analysis_curve_print_jobs(run_id, curve_snapshot_id, id);
                CREATE TABLE IF NOT EXISTS hardware_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','connecting','connected','pre_excitation','turning','collecting','anomaly','manual_intervention','paused','stopping','completed','failed','stopped','safety_stopped','deferred_external')),
                    paused_from TEXT,
                    device_profile_id INTEGER NOT NULL REFERENCES device_profiles(id),
                    ccd_layout_id INTEGER NOT NULL REFERENCES ccd_layouts(id),
                    transport TEXT NOT NULL CHECK(transport IN ('simulator','serial')),
                    strategy TEXT NOT NULL CHECK(strategy IN ('short_to_long','key_first')),
                    anomaly_policy TEXT NOT NULL CHECK(anomaly_policy IN ('retry_then_stop','manual')),
                    sample_name TEXT NOT NULL DEFAULT '',
                    method_id INTEGER REFERENCES methods(id),
                    method_version INTEGER,
                    retry_limit INTEGER NOT NULL DEFAULT 1 CHECK(retry_limit >= 0 AND retry_limit <= 5),
                    pre_excitation_seconds REAL NOT NULL DEFAULT 1 CHECK(pre_excitation_seconds >= 0 AND pre_excitation_seconds <= 600),
                    sampling_period_seconds REAL NOT NULL DEFAULT 1 CHECK(sampling_period_seconds > 0 AND sampling_period_seconds <= 60),
                    ccd_indices_json TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    thresholds_json TEXT NOT NULL DEFAULT '{}',
                    simulator_json TEXT NOT NULL DEFAULT '{}',
                    total_steps INTEGER NOT NULL CHECK(total_steps >= 1 AND total_steps <= 300),
                    current_step_index INTEGER NOT NULL DEFAULT 0 CHECK(current_step_index >= 0),
                    current_retry_count INTEGER NOT NULL DEFAULT 0 CHECK(current_retry_count >= 0),
                    completed_steps INTEGER NOT NULL DEFAULT 0 CHECK(completed_steps >= 0),
                    adapter_session_id TEXT,
                    last_event_json TEXT,
                    last_message TEXT NOT NULL DEFAULT '',
                    result_sha256 TEXT,
                    failure_code TEXT,
                    failure_message TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_hardware_tasks_status ON hardware_tasks(status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS hardware_plan_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES hardware_tasks(id) ON DELETE CASCADE,
                    order_index INTEGER NOT NULL CHECK(order_index >= 0),
                    source_index INTEGER NOT NULL CHECK(source_index >= 0),
                    angle_deg REAL NOT NULL,
                    wavelength_nm REAL NOT NULL CHECK(wavelength_nm >= 160 AND wavelength_nm <= 800),
                    priority INTEGER NOT NULL DEFAULT 0 CHECK(priority >= 0 AND priority <= 100),
                    key_band INTEGER NOT NULL DEFAULT 0 CHECK(key_band IN (0,1)),
                    expected_peak_position REAL NOT NULL CHECK(expected_peak_position >= 0),
                    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','turning','collecting','confirmed','retry_pending','manual','failed','skipped')),
                    retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
                    last_attempt INTEGER NOT NULL DEFAULT -1 CHECK(last_attempt >= -1),
                    correction_offset REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, order_index),
                    UNIQUE(task_id, source_index)
                );
                CREATE INDEX IF NOT EXISTS idx_hardware_plan_steps_task ON hardware_plan_steps(task_id, order_index);
                CREATE TABLE IF NOT EXISTS hardware_frames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES hardware_tasks(id) ON DELETE CASCADE,
                    step_id INTEGER NOT NULL REFERENCES hardware_plan_steps(id) ON DELETE CASCADE,
                    attempt INTEGER NOT NULL CHECK(attempt >= 0),
                    ccd_index INTEGER NOT NULL CHECK(ccd_index >= 0),
                    points_blob BLOB,
                    points_count INTEGER NOT NULL DEFAULT 0 CHECK(points_count >= 0),
                    points_sha256 TEXT,
                    raw_transfer_sha256 TEXT,
                    raw_byte_length INTEGER NOT NULL DEFAULT 0,
                    headers_json TEXT NOT NULL DEFAULT '[]',
                    baseline_intensity REAL,
                    baseline_position REAL,
                    expected_peak_position REAL,
                    peak_position REAL,
                    peak_value REAL,
                    virtual_time_ms REAL NOT NULL DEFAULT 0,
                    damaged INTEGER NOT NULL DEFAULT 0 CHECK(damaged IN (0,1)),
                    confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0,1)),
                    anomaly_kind TEXT,
                    damage_code TEXT,
                    damage_message TEXT,
                    captured_at TEXT NOT NULL,
                    UNIQUE(task_id, step_id, attempt, ccd_index)
                );
                CREATE INDEX IF NOT EXISTS idx_hardware_frames_task ON hardware_frames(task_id, step_id, attempt, ccd_index);
                CREATE TABLE IF NOT EXISTS hardware_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES hardware_tasks(id) ON DELETE CASCADE,
                    sequence_no INTEGER NOT NULL,
                    direction TEXT NOT NULL CHECK(direction IN ('outbound','inbound','internal')),
                    kind TEXT NOT NULL CHECK(kind IN ('connection','command','response','frame','event','safety')),
                    name TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    payload_sha256 TEXT NOT NULL,
                    raw_payload BLOB,
                    correlation_id TEXT NOT NULL,
                    safe_state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, sequence_no)
                );
                CREATE INDEX IF NOT EXISTS idx_hardware_traces_task ON hardware_traces(task_id, sequence_no);
                CREATE TABLE IF NOT EXISTS hardware_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES hardware_tasks(id) ON DELETE CASCADE,
                    step_id INTEGER REFERENCES hardware_plan_steps(id) ON DELETE SET NULL,
                    attempt INTEGER NOT NULL CHECK(attempt >= 0),
                    anomaly_kind TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('accept','retry','correct','manual','stop')),
                    observed_json TEXT NOT NULL DEFAULT '{}',
                    threshold_json TEXT NOT NULL DEFAULT '{}',
                    reason TEXT NOT NULL,
                    actor_user_id INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_hardware_decisions_task ON hardware_decisions(task_id, created_at);
                CREATE TABLE IF NOT EXISTS hardware_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES hardware_tasks(id) ON DELETE CASCADE,
                    level TEXT NOT NULL CHECK(level IN ('info','warning','error','success')),
                    code TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_hardware_messages_task ON hardware_messages(task_id, id);
                CREATE TABLE IF NOT EXISTS mercury_reference_lines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    wavelength_nm REAL NOT NULL UNIQUE CHECK(wavelength_nm > 0),
                    relative_intensity INTEGER NOT NULL CHECK(relative_intensity > 0),
                    source_name TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mercury_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','stabilizing','acquiring','ready','applied','rolled_back','stopped','safe_off','deferred_external')),
                    device_profile_id INTEGER NOT NULL REFERENCES device_profiles(id),
                    ccd_layout_id INTEGER NOT NULL REFERENCES ccd_layouts(id),
                    transport TEXT NOT NULL CHECK(transport IN ('simulator','serial')),
                    stabilization_frames INTEGER NOT NULL CHECK(stabilization_frames >= 1 AND stabilization_frames <= 20),
                    stabilized_frames INTEGER NOT NULL DEFAULT 0 CHECK(stabilized_frames >= 0),
                    tolerance_points REAL NOT NULL CHECK(tolerance_points > 0),
                    search_radius_points INTEGER NOT NULL CHECK(search_radius_points >= 1 AND search_radius_points <= 500),
                    correction_limit_points REAL NOT NULL CHECK(correction_limit_points > 0),
                    simulator_json TEXT NOT NULL DEFAULT '{}',
                    adapter_session_id TEXT,
                    before_version_id INTEGER REFERENCES mercury_alignment_versions(id),
                    candidate_version_id INTEGER REFERENCES mercury_alignment_versions(id),
                    analysis_json TEXT,
                    last_event_json TEXT,
                    last_message TEXT NOT NULL DEFAULT '',
                    failure_code TEXT,
                    failure_message TEXT,
                    safe_off INTEGER NOT NULL DEFAULT 1 CHECK(safe_off IN (0,1)),
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_mercury_sessions_status ON mercury_sessions(status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS mercury_session_lines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES mercury_sessions(id) ON DELETE CASCADE,
                    reference_line_id INTEGER NOT NULL REFERENCES mercury_reference_lines(id),
                    wavelength_nm REAL NOT NULL,
                    expected_ccd_index INTEGER NOT NULL,
                    expected_position REAL NOT NULL,
                    observed_ccd_index INTEGER,
                    observed_position REAL,
                    peak_value REAL,
                    offset_points REAL,
                    after_offset_points REAL,
                    state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','located','not_found')),
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, reference_line_id)
                );
                CREATE INDEX IF NOT EXISTS idx_mercury_session_lines_session ON mercury_session_lines(session_id, wavelength_nm);
                CREATE TABLE IF NOT EXISTS mercury_frames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES mercury_sessions(id) ON DELETE CASCADE,
                    phase TEXT NOT NULL CHECK(phase IN ('stabilization','measurement')),
                    frame_index INTEGER NOT NULL CHECK(frame_index >= 0),
                    ccd_index INTEGER NOT NULL CHECK(ccd_index >= 0),
                    points_blob BLOB NOT NULL,
                    points_count INTEGER NOT NULL CHECK(points_count > 0),
                    points_sha256 TEXT NOT NULL,
                    frame_sha256 TEXT NOT NULL,
                    virtual_time_ms REAL NOT NULL DEFAULT 0,
                    captured_at TEXT NOT NULL,
                    UNIQUE(session_id, phase, frame_index, ccd_index)
                );
                CREATE INDEX IF NOT EXISTS idx_mercury_frames_session ON mercury_frames(session_id, phase, frame_index, ccd_index);
                CREATE TABLE IF NOT EXISTS mercury_alignment_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_profile_id INTEGER NOT NULL REFERENCES device_profiles(id),
                    ccd_layout_id INTEGER NOT NULL REFERENCES ccd_layouts(id),
                    version INTEGER NOT NULL CHECK(version >= 1),
                    source_session_id INTEGER REFERENCES mercury_sessions(id),
                    parent_version_id INTEGER REFERENCES mercury_alignment_versions(id),
                    offset_points REAL NOT NULL,
                    before_rms REAL NOT NULL CHECK(before_rms >= 0),
                    after_rms REAL NOT NULL CHECK(after_rms >= 0),
                    max_before_offset REAL NOT NULL CHECK(max_before_offset >= 0),
                    max_after_offset REAL NOT NULL CHECK(max_after_offset >= 0),
                    point_count INTEGER NOT NULL CHECK(point_count >= 0),
                    snapshot_json TEXT NOT NULL,
                    snapshot_sha256 TEXT NOT NULL UNIQUE,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    UNIQUE(device_profile_id, ccd_layout_id, version)
                );
                CREATE TABLE IF NOT EXISTS mercury_active_alignments (
                    device_profile_id INTEGER NOT NULL REFERENCES device_profiles(id),
                    ccd_layout_id INTEGER NOT NULL REFERENCES ccd_layouts(id),
                    version_id INTEGER NOT NULL REFERENCES mercury_alignment_versions(id),
                    updated_by INTEGER REFERENCES users(id),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(device_profile_id, ccd_layout_id)
                );
                CREATE TABLE IF NOT EXISTS mercury_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES mercury_sessions(id) ON DELETE CASCADE,
                    sequence_no INTEGER NOT NULL,
                    direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound','internal')),
                    kind TEXT NOT NULL CHECK(kind IN ('connection','frame','event','safety')),
                    name TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    payload_sha256 TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    safe_state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, sequence_no)
                );
                CREATE INDEX IF NOT EXISTS idx_mercury_traces_session ON mercury_traces(session_id, sequence_no);
                CREATE TABLE IF NOT EXISTS mercury_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES mercury_sessions(id) ON DELETE CASCADE,
                    level TEXT NOT NULL CHECK(level IN ('info','warning','error','success')),
                    code TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mercury_messages_session ON mercury_messages(session_id, id);
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
                CREATE TABLE IF NOT EXISTS postprocessing_conversion_runs (
                    id TEXT PRIMARY KEY,
                    input_sha256 TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('converted','failed')),
                    source_record_ids_json TEXT NOT NULL,
                    source_hashes_json TEXT NOT NULL,
                    interval_start INTEGER NOT NULL CHECK(interval_start >= 1),
                    interval_end INTEGER NOT NULL CHECK(interval_end >= interval_start),
                    target_ccd_layout_id INTEGER NOT NULL REFERENCES ccd_layouts(id),
                    method_version_id INTEGER REFERENCES method_versions(id),
                    sample_ids_json TEXT NOT NULL,
                    task_ids_json TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    result_sha256 TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_postprocessing_conversion_created
                    ON postprocessing_conversion_runs(created_at DESC);
                CREATE TABLE IF NOT EXISTS postprocessing_recalculation_runs (
                    id TEXT PRIMARY KEY,
                    input_sha256 TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('completed','blocked','failed')),
                    source_record_ids_json TEXT NOT NULL,
                    source_hashes_json TEXT NOT NULL,
                    method_version_id INTEGER NOT NULL REFERENCES method_versions(id),
                    calculation_profile TEXT NOT NULL,
                    curve_snapshot_ids_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    result_sha256 TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_postprocessing_recalculation_created
                    ON postprocessing_recalculation_runs(created_at DESC);
                CREATE TABLE IF NOT EXISTS postprocessing_exports (
                    id TEXT PRIMARY KEY,
                    input_sha256 TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('completed','failed')),
                    source_record_ids_json TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('raw_intensity','processed_intensity','result_matrix')),
                    format TEXT NOT NULL CHECK(format IN ('txt','csv','excel')),
                    output_directory TEXT NOT NULL,
                    requested_name TEXT NOT NULL,
                    actual_path TEXT,
                    same_name_strategy TEXT NOT NULL CHECK(same_name_strategy IN ('suffix','error','overwrite')),
                    content_sha256 TEXT,
                    byte_length INTEGER NOT NULL DEFAULT 0,
                    report_json TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_postprocessing_export_created
                    ON postprocessing_exports(created_at DESC);
                CREATE TABLE IF NOT EXISTS report_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    schema_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_number TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    template_id INTEGER NOT NULL REFERENCES report_templates(id),
                    source_run_ids_json TEXT NOT NULL,
                    filter_json TEXT NOT NULL,
                    arrangement TEXT NOT NULL CHECK(arrangement IN ('standard','exchange')),
                    model_json TEXT NOT NULL,
                    model_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('draft','confirmed','published')),
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(report_number, version)
                );
                CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at DESC);
                CREATE TABLE IF NOT EXISTS report_exports (
                    id TEXT PRIMARY KEY,
                    report_id INTEGER NOT NULL REFERENCES reports(id),
                    format TEXT NOT NULL CHECK(format IN ('txt','csv','excel','pdf','print')),
                    status TEXT NOT NULL CHECK(status IN ('completed','failed')),
                    output_directory TEXT,
                    requested_name TEXT NOT NULL,
                    actual_path TEXT,
                    same_name_strategy TEXT NOT NULL CHECK(same_name_strategy IN ('suffix','error','overwrite')),
                    content_sha256 TEXT,
                    byte_length INTEGER NOT NULL DEFAULT 0,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    report_json TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_report_exports_report ON report_exports(report_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS maintenance_backups (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK(kind IN ('online','rehearsal')),
                    source_path TEXT NOT NULL,
                    backup_path TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    backup_sha256 TEXT NOT NULL,
                    byte_length INTEGER NOT NULL,
                    integrity TEXT NOT NULL,
                    foreign_keys INTEGER NOT NULL,
                    entity_counts_json TEXT NOT NULL,
                    blob_samples_json TEXT NOT NULL,
                    retention_expires_at TEXT,
                    status TEXT NOT NULL CHECK(status IN ('completed','verified','failed')),
                    error_code TEXT,
                    error_message TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_maintenance_backups_created
                    ON maintenance_backups(created_at DESC);
                CREATE TABLE IF NOT EXISTS maintenance_operations (
                    id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL CHECK(operation IN ('backup','checkpoint','optimize','reclaim','logs','temp','restore_rehearsal','retention')),
                    status TEXT NOT NULL CHECK(status IN ('completed','failed','blocked')),
                    details_json TEXT NOT NULL,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_maintenance_operations_created
                    ON maintenance_operations(created_at DESC);
                CREATE TABLE IF NOT EXISTS help_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    section TEXT NOT NULL,
                    keywords_json TEXT NOT NULL,
                    body TEXT NOT NULL,
                    related_routes_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))
                );
                CREATE INDEX IF NOT EXISTS idx_help_topics_section ON help_topics(section, slug);
                """
    )
    # S03 was started against an S02 database before this column was
    # present. Keep initialization safe for both that database and a
    # clean install without rewriting a published migration.
    layout_columns = _columns(connection, "ccd_layouts")
    if "allow_drift_um" not in layout_columns:
        connection.execute(
            "ALTER TABLE ccd_layouts ADD COLUMN allow_drift_um REAL NOT NULL DEFAULT 300"
        )
    queue_columns = _columns(connection, "sample_queues")
    if "source_sha256" not in queue_columns:
        connection.execute("ALTER TABLE sample_queues ADD COLUMN source_sha256 TEXT")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sample_queues_source_sha256 ON sample_queues(source_sha256) WHERE source_sha256 IS NOT NULL")
    dispersion_frame_columns = _columns(connection, "dispersion_task_frames")
    if "virtual_time_ms" not in dispersion_frame_columns:
        connection.execute("ALTER TABLE dispersion_task_frames ADD COLUMN virtual_time_ms REAL NOT NULL DEFAULT 0")
