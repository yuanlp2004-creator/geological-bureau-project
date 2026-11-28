"""Deterministic SQLite records in the retired v1 storage format."""

import hashlib
import json
import struct

from backend.modules.methods import MethodService

STAMP = "2026-01-01T00:00:00+00:00"
HARDWARE = "/api/v1/hardware-acquisitions"
MERCURY = "/api/v1/mercury-calibrations"
RETIRED_PERMISSIONS = {
    "hardware-acquisition.write", "mercury-calibration.write",
    "mercury-calibration.execute", "results.read", "results.export",
}


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def _insert(db, table, **columns):
    placeholders = ", ".join("?" for _ in columns)
    return db.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", tuple(columns.values())
    ).lastrowid


def _exposure(db, task_id, step_id, ccd, plan, attempt, confirmed, factor):
    points = [100] * 2048
    # Anchor the method's default reference correction at its expected pixel.
    points[769] = 500
    points[1024] = 100 + round(4000 * factor)
    frame_count = plan["end_frame"]
    frames = []
    for frame_index in range(1, frame_count + 1):
        values = points.copy()
        values[1024] += frame_index - 2
        blob = struct.pack("<2048H", *values)
        frames.append((values, blob))
        _insert(db, "hardware_exposure_frames", task_id=task_id, step_id=step_id, attempt=attempt,
                frame_index=frame_index, ccd_index=ccd, points_blob=blob, points_count=len(values),
                points_sha256=digest(blob), captured_at=STAMP)
    selected = frames[plan["start_frame"] - 1:]
    mean = struct.pack("<2048f", *(sum(values) / len(selected) for values in zip(*(frame[0] for frame in selected))))
    full = b"".join(frame[1] for frame in selected) if plan["storage_mode"] == "full_interval" else None
    _insert(db, "hardware_frames", task_id=task_id, step_id=step_id, attempt=attempt, ccd_index=ccd,
            points_blob=blob, points_count=len(points), points_sha256=digest(blob), raw_byte_length=len(blob),
            confirmed=int(confirmed), anomaly_kind=None if confirmed else "peak_shift", captured_at=STAMP)
    _insert(db, "hardware_exposure_results", task_id=task_id, step_id=step_id, attempt=attempt, ccd_index=ccd,
            storage_mode=plan["storage_mode"], start_frame=plan["start_frame"], end_frame=frame_count,
            points_count=len(points), mean_blob=mean, mean_sha256=digest(mean),
            frames_blob=full, frames_sha256=digest(full) if full else None, created_at=STAMP)


def seed_hardware_task(database, name, *, method=None, plans=None, factor=1, retry=False, manual=False, draft=False):
    """Seed legacy frames and summaries with explicit accepted and rejected attempts."""
    if plans is None:
        plans = [{"angle_deg": 12, "start_frame": 2, "end_frame": 3,
                  "storage_mode": "full_interval", "ccd_indices": [0]}]
    plan = [dict(item, order_index=index, wavelength_nm=None if manual else 280 + index * 10)
            for index, item in enumerate(plans)]
    if manual:
        plan[0]["duration_seconds"] = 0.5
    with database.write() as db:
        layout_id = 1
        if method:
            methods = MethodService(database)
            version = methods.bind_snapshots(db).for_print(*method)
            layout_id = methods.bind_geometry(db, version.payload["conditions"]).layout_id
            for item in plan:
                item["method_content_sha256"] = version.content_sha256
        method_id, method_version = method or (None, None)
        task_id = _insert(
            db, "hardware_tasks", name=name, sample_name=name, status="draft" if draft else "completed",
            device_profile_id=1, ccd_layout_id=layout_id, transport="simulator", strategy="short_to_long",
            anomaly_policy="retry_then_stop", ccd_indices_json=json.dumps(sorted({ccd for item in plan for ccd in item["ccd_indices"]})),
            plan_json=json.dumps(plan), execution_mode="manual" if manual else "automatic",
            method_id=method_id, method_version=method_version, total_steps=len(plan),
            completed_steps=0 if draft else len(plan), created_at=STAMP, updated_at=STAMP,
            completed_at=None if draft else STAMP, result_sha256=None if draft else digest(name.encode()),
        )
        for index, item in enumerate(plan):
            retried = retry and index == 0
            step_id = _insert(
                db, "hardware_plan_steps", task_id=task_id, order_index=index, source_index=index,
                angle_deg=item["angle_deg"], wavelength_nm=item["wavelength_nm"], expected_peak_position=1024,
                status="pending" if draft else "confirmed", last_attempt=-1 if draft else int(retried),
                retry_count=int(retried), created_at=STAMP, updated_at=STAMP,
            )
            if draft:
                continue
            for ccd in item["ccd_indices"]:
                if retried:
                    _exposure(db, task_id, step_id, ccd, item, 0, False, factor * 2)
                _exposure(db, task_id, step_id, ccd, item, int(retried), True, factor)
            if retried:
                _insert(db, "hardware_decisions", task_id=task_id, step_id=step_id, attempt=0,
                        anomaly_kind="peak_shift", decision="retry", observed_json='{"peak_position": 1060}',
                        threshold_json='{"peak_shift_limit": 24}', reason="historical retry", created_at=STAMP)
        if not draft:
            _insert(db, "hardware_traces", task_id=task_id, sequence_no=1, direction="internal", kind="safety",
                    name="safe_off", payload_sha256=digest(b"{}"), correlation_id=f"history-{task_id}",
                    safe_state="off", created_at=STAMP)
    return task_id


def seed_mercury_history(database):
    """Seed an applied version followed by a candidate whose activation was rolled back."""
    with database.write() as db:
        def version(number, offset, parent=None, session=None):
            snapshot = json.dumps({"offset_points": offset})
            return _insert(
                db, "mercury_alignment_versions", device_profile_id=1, ccd_layout_id=1, version=number,
                offset_points=offset, parent_version_id=parent, source_session_id=session,
                before_rms=abs(offset), after_rms=0, max_before_offset=abs(offset), max_after_offset=0,
                point_count=1, snapshot_json=snapshot, snapshot_sha256=digest(snapshot.encode()), created_at=STAMP,
            )
        active = version(1, 0)
        sessions = []
        for index, status in enumerate(("applied", "rolled_back"), 2):
            session_id = _insert(
                db, "mercury_sessions", name=status, status=status, device_profile_id=1, ccd_layout_id=1,
                transport="simulator", stabilization_frames=1, stabilized_frames=1, tolerance_points=1,
                search_radius_points=24, correction_limit_points=20, before_version_id=active,
                created_at=STAMP, updated_at=STAMP, completed_at=STAMP,
            )
            ref_line = db.execute("SELECT id,wavelength_nm FROM mercury_reference_lines WHERE wavelength_nm=253.6517").fetchone()
            _insert(db, "mercury_session_lines", session_id=session_id, reference_line_id=ref_line["id"],
                    wavelength_nm=ref_line["wavelength_nm"], expected_ccd_index=0, expected_position=1024,
                    observed_ccd_index=0, observed_position=1024 + index, offset_points=index,
                    after_offset_points=0, state="located", created_at=STAMP)
            points = [100] * 2048
            points[1024 + index] = 2500
            blob = struct.pack("<2048H", *points)
            _insert(db, "mercury_frames", session_id=session_id, phase="measurement", frame_index=0,
                    ccd_index=0, points_blob=blob, points_count=len(points), points_sha256=digest(blob),
                    frame_sha256=digest(blob), captured_at=STAMP)
            candidate = version(index, index, active, session_id)
            db.execute("UPDATE mercury_sessions SET candidate_version_id=? WHERE id=?", (candidate, session_id))
            if status == "applied":
                active = candidate
            sessions.append(session_id)
        _insert(db, "mercury_active_alignments", device_profile_id=1, ccd_layout_id=1,
                version_id=active, updated_at=STAMP)
    return tuple(sessions)
