"""Acquisition-owned import of existing frames, within the caller's transaction.

This capability does not create a Database, open a write lock, or commit.
"""

from dataclasses import dataclass
import hashlib
import json
import sqlite3
import struct
from typing import Any


@dataclass(frozen=True)
class ImportedBand:
    ccd_index: int
    points_count: int
    frames: list[list[int]]


@dataclass(frozen=True)
class ImportedAcquisition:
    name: str
    layout_id: int
    method_version_id: int | None
    method_id: int | None
    method_version: int | None
    sample_name: str
    original_sample_name: str
    source_record_id: str
    source_sha256: str
    measure_time: str | None
    interval_start: int
    frame_count: int
    bands: list[ImportedBand]
    actor_user_id: int | None
    created_at: str


def _import_json(value: Any) -> str:
    # Existing EDT import fingerprints sort keys; native acquisition JSON does not.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _import_sha(value: Any) -> str:
    data = value if isinstance(value, bytes) else _import_json(value).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class AcquisitionRecordImporter:
    def bind(self, connection: sqlite3.Connection) -> "AcquisitionImportTransaction":
        return AcquisitionImportTransaction(connection)


class AcquisitionImportTransaction:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def import_record(self, record: ImportedAcquisition) -> tuple[int, int]:
        db = self._connection
        now = record.created_at
        selected = [band.ccd_index for band in record.bands]
        if not selected or len(selected) != len(set(selected)):
            raise ValueError("imported CCD indices must be nonempty and unique")
        for band in record.bands:
            if len(band.frames) != record.frame_count or not band.frames or any(len(frame) != band.points_count for frame in band.frames):
                raise ValueError("imported frame shape does not match metadata")
        task_cursor = db.execute(
            "INSERT INTO acquisition_tasks(task_kind,name,status,device_profile_id,ccd_layout_id,method_version_id,method_id,method_version,sample_name,sample_kind,naming_mode,storage_mode,repeat_count,current_repeat_index,completed_repeats,burn_frame_count,dark_frame_count,countdown_seconds,countdown_remaining,pre_excitation_seconds,sampling_period_seconds,burn_cycle_seconds,dark_cycle_seconds,ccd_indices_json,excitation_condition_json,evaporation_condition_json,simulator_json,created_by,created_at,updated_at,completed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("sample", record.name, "completed", 1, record.layout_id, record.method_version_id, record.method_id, record.method_version, record.sample_name, "normal", "pre_recorded", "full_interval", 1, 0, 1, record.frame_count, 0, 0, 0, 0, 1, 1, 1, _import_json(selected), "{}", "{}", _import_json({"source_record_id": record.source_record_id, "source_sha256": record.source_sha256, "measure_time": record.measure_time}), record.actor_user_id, now, now, now),
        )
        task_id = int(task_cursor.lastrowid)
        sample_cursor = db.execute(
            "INSERT INTO acquisition_samples(task_id,repeat_index,sample_name_original,sample_name,sample_kind,storage_mode,status,finalized,result_sha256,created_at,completed_at,updated_at) VALUES (?,?,?,?,?,'full_interval','completed',1,?,?,?,?)",
            (task_id, 0, record.original_sample_name, record.sample_name, "normal", None, now, now, now),
        )
        sample_id = int(sample_cursor.lastrowid)
        band_hashes: list[str] = []
        for band in record.bands:
            target_ccd, points, values = band.ccd_index, band.points_count, band.frames
            mean = [sum(frame[point] for frame in values) / len(values) for point in range(points)]
            mean_blob = struct.pack(f"<{len(mean)}f", *mean)
            burn_blob = b"".join(struct.pack(f"<{points}H", *frame) for frame in values)
            mean_sha, burn_sha = _import_sha(mean_blob), _import_sha(burn_blob)
            band_hashes.extend([mean_sha, burn_sha])
            db.execute("INSERT INTO acquisition_sample_bands(sample_id,ccd_index,storage_mode,points_count,burn_frame_count,dark_frame_count,mean_blob,mean_sha256,burn_frames_blob,burn_sha256,created_at) VALUES (?,?,?,?,?,0,?,?,?,?,?)", (sample_id, target_ccd, "full_interval", points, len(values), mean_blob, mean_sha, burn_blob, burn_sha, now))
            for frame_index, frame_values in enumerate(values):
                raw_blob = struct.pack(f"<{points}H", *frame_values)
                db.execute("INSERT INTO acquisition_frames(task_id,sample_id,repeat_index,phase,frame_index,ccd_index,points_blob,points_count,points_sha256,raw_transfer_sha256,raw_byte_length,headers_json,virtual_time_ms,peak_value,peak_position,integral_value,damaged,captured_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)", (task_id, sample_id, 0, "burn", frame_index, target_ccd, raw_blob, points, _import_sha(raw_blob), record.source_sha256, len(raw_blob), _import_json({"source_record_id": record.source_record_id, "source_frame_index": frame_index + record.interval_start - 1}), float(frame_index), max(frame_values), frame_values.index(max(frame_values)), float(sum(frame_values)), now))
        result_hash = _import_sha(band_hashes)
        db.execute("UPDATE acquisition_samples SET result_sha256=? WHERE id=?", (result_hash, sample_id))
        db.execute("UPDATE acquisition_tasks SET result_sha256=? WHERE id=?", (result_hash, task_id))
        return task_id, sample_id
