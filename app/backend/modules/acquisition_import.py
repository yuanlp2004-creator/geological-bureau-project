"""Acquisition-owned import of existing frames, within the caller's transaction.

This capability does not create a Database, open a write lock, or commit.
"""

from dataclasses import dataclass, field
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
    dark_frames: list[list[int]] = field(default_factory=list)


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
    storage_mode: str = 'full_interval'
    pre_excitation_seconds: float = 0
    sampling_period_seconds: float = 1
    burn_cycle_seconds: float = 1
    dark_cycle_seconds: float = 1


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

    def confirmed_source(self, source_record_id: str) -> dict | None:
        from .acquisition.confirmed_import import find_confirmed_source
        return find_confirmed_source(self._connection, source_record_id)

    def import_confirmed(self, record, actor_user_id: int | None) -> dict:
        from .acquisition.confirmed_import import import_confirmed_spectrum
        return import_confirmed_spectrum(self._connection, record, actor_user_id)

    def import_record(self, record: ImportedAcquisition) -> tuple[int, int]:
        from .acquisition import average_points

        db, now = self._connection, record.created_at
        selected = [band.ccd_index for band in record.bands]
        if not selected or len(selected) != len(set(selected)) or record.storage_mode not in {'averaged', 'full_interval'}:
            raise ValueError('invalid imported CCDs or storage mode')
        dark_count = len(record.bands[0].dark_frames)
        for band in record.bands:
            if len(band.frames) != record.frame_count or not band.frames or len(band.dark_frames) != dark_count:
                raise ValueError('imported frame count does not match metadata')
            if any(len(frame) != band.points_count for frame in band.frames + band.dark_frames):
                raise ValueError('imported frame shape does not match metadata')
        metadata = {'source_record_id': record.source_record_id, 'source_sha256': record.source_sha256,
                    'measure_time': record.measure_time, 'source_interval_start': record.interval_start}
        task_id = db.execute(
            'INSERT INTO acquisition_tasks(task_kind,name,status,device_profile_id,ccd_layout_id,method_version_id,'
            'method_id,method_version,sample_name,sample_kind,naming_mode,storage_mode,repeat_count,current_repeat_index,'
            'completed_repeats,burn_frame_count,dark_frame_count,countdown_seconds,countdown_remaining,pre_excitation_seconds,'
            'sampling_period_seconds,burn_cycle_seconds,dark_cycle_seconds,ccd_indices_json,excitation_condition_json,'
            'evaporation_condition_json,simulator_json,created_by,created_at,updated_at,completed_at) VALUES (' + ','.join('?' for _ in range(31)) + ')',
            ('sample', record.name, 'completed', 1, record.layout_id, record.method_version_id, record.method_id,
             record.method_version, record.sample_name, 'normal', 'pre_recorded', record.storage_mode, 1, 0, 1,
             record.frame_count, dark_count, 0, 0, record.pre_excitation_seconds, record.sampling_period_seconds,
             record.burn_cycle_seconds, record.dark_cycle_seconds, _import_json(selected),
             _import_json({'pre_excitation_seconds': record.pre_excitation_seconds}), '{}', _import_json(metadata),
             record.actor_user_id, now, now, now)).lastrowid
        sample_id = db.execute(
            'INSERT INTO acquisition_samples(task_id,repeat_index,sample_name_original,sample_name,sample_kind,storage_mode,'
            "status,finalized,created_at,completed_at,updated_at) VALUES (?,?,?,?,?,?,'completed',1,?,?,?)",
            (task_id, 0, record.original_sample_name, record.sample_name, 'normal', record.storage_mode, now, now, now)).lastrowid
        hashes = []
        for band in record.bands:
            points = band.points_count
            burn = [struct.pack(f'<{points}H', *frame) for frame in band.frames]
            dark = [struct.pack(f'<{points}H', *frame) for frame in band.dark_frames]
            mean_blob = average_points(burn, dark, points, burn_cycle_seconds=record.burn_cycle_seconds,
                                       dark_cycle_seconds=record.dark_cycle_seconds)
            burn_blob = b''.join(burn) if record.storage_mode == 'full_interval' else None
            dark_blob = b''.join(dark) if record.storage_mode == 'full_interval' and dark else None
            mean_hash = _import_sha(mean_blob)
            burn_hash, dark_hash = _import_sha(burn_blob) if burn_blob else None, _import_sha(dark_blob) if dark_blob else None
            hashes.extend([mean_hash, burn_hash, dark_hash])
            db.execute('INSERT INTO acquisition_sample_bands(sample_id,ccd_index,storage_mode,points_count,burn_frame_count,'
                       'dark_frame_count,mean_blob,mean_sha256,burn_frames_blob,burn_sha256,dark_frames_blob,dark_sha256,created_at) '
                       'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (sample_id, band.ccd_index, record.storage_mode, points, len(burn), len(dark), mean_blob, mean_hash,
                        burn_blob, burn_hash, dark_blob, dark_hash, now))
            if record.storage_mode == 'full_interval':
                for phase, blobs, period in [('burn', burn, record.burn_cycle_seconds), ('dark', dark, record.dark_cycle_seconds)]:
                    for index, blob in enumerate(blobs):
                        values = struct.unpack(f'<{points}H', blob)
                        db.execute('INSERT INTO acquisition_frames(task_id,sample_id,repeat_index,phase,frame_index,ccd_index,'
                                   'points_blob,points_count,points_sha256,raw_transfer_sha256,raw_byte_length,headers_json,'
                                   'virtual_time_ms,peak_value,peak_position,integral_value,damaged,captured_at) '
                                   'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)',
                                   (task_id, sample_id, 0, phase, index, band.ccd_index, blob, points, _import_sha(blob),
                                    record.source_sha256, len(blob), _import_json({'source_record_id': record.source_record_id,
                                    'source_frame_index': index + record.interval_start - 1 if phase == 'burn' else index}),
                                    index * period * 1000, max(values), values.index(max(values)), float(sum(values)), now))
        result_hash = _import_sha(hashes)
        db.execute('UPDATE acquisition_samples SET result_sha256=? WHERE id=?', (result_hash, sample_id))
        db.execute('UPDATE acquisition_tasks SET result_sha256=? WHERE id=?', (result_hash, task_id))
        return int(task_id), int(sample_id)

    def import_legacy_group(
        self,
        rows: list[dict],
        method,
        layout_id: int,
        sample_kind: str,
        actor: int | None,
        now: str,
        *,
        analytical_name: str | None = None,
    ) -> list[int]:
        """Import one explicitly mapped legacy repeat group; never synthesize raw frames."""
        from .acquisition import average_points

        db = self._connection
        first = rows[0]
        geometry = json.loads(first["layout_json"])
        ignition = json.loads(first["ignition_json"])
        analytical_name = analytical_name if analytical_name is not None else first["sample_name"]
        count = int(ignition.get("burn_count") or 0)
        dark_count = int(ignition.get("dark_count") or 0)
        storage = "averaged" if first["format"] == "cdt" else "full_interval"
        metadata = {
            "source_format": first["format"],
            "source_sha256": first["source_sha256"],
            "source_record_ids": [row["id"] for row in rows],
            "source_frame_count": count if storage == "full_interval" else None,
            "source_layout": geometry,
            "measure_time": first["measure_time"],
            "method_sha256": method.content_sha256,
        }
        metadata.update(source_sample_name=first["sample_name"], analysis_sample_name=analytical_name)
        previous = db.execute(
            "SELECT id FROM acquisition_tasks WHERE method_version_id=? AND simulator_json=? AND status='completed'",
            (method.version_id, _import_json(metadata)),
        ).fetchone()
        if previous:
            return [
                row[0]
                for row in db.execute(
                    "SELECT id FROM acquisition_samples WHERE task_id=? ORDER BY repeat_index", (previous["id"],)
                )
            ]
        task = db.execute(
            (
                "INSERT INTO acquisition_tasks(task_kind,name,status,device_profile_id,ccd_layout"
                "_id,method_version_id,method_id,method_version,sample_name,sample_kind,naming_mo"
                "de,storage_mode,repeat_count,current_repeat_index,completed_repeats,burn_frame_c"
                "ount,dark_frame_count,countdown_seconds,countdown_remaining,pre_excitation_secon"
                "ds,sampling_period_seconds,burn_cycle_seconds,dark_cycle_seconds,ccd_indices_jso"
                "n,simulator_json,created_by,created_at,updated_at,completed_at) VALUES "
                "('sample',?,'completed',1,?,?,?,?,?,?,'pre_recorded',?,?,?,?,?,?,0,0,0,1,?,?,?, "
                "?,?,?,?,?)"
            ),
            (
                "旧样品 " + str(first["sample_name"]),
                layout_id,
                method.version_id,
                method.method.id,
                method.version,
                analytical_name,
                sample_kind,
                storage,
                len(rows),
                len(rows) - 1,
                len(rows),
                max(count, 1),
                dark_count,
                float(ignition.get("burn_cyc") or 1),
                float(ignition.get("dark_cyc") or 1),
                _import_json(geometry["ccd_indices"]),
                _import_json(metadata),
                actor,
                now,
                now,
                now,
            ),
        ).lastrowid
        sample_ids = []
        for repeat, row in enumerate(rows):
            sample = db.execute(
                (
                    "INSERT INTO acquisition_samples(task_id,repeat_index,sample_name_original,sample"
                    "_name,sample_kind,storage_mode,status,finalized,created_at,completed_at,updated_"
                    "at) VALUES (?,?,?,?,?,?,'completed',1,?,?,?)"
                ),
                (task, repeat, row["sample_name"], analytical_name, sample_kind, storage, now, now, now),
            ).lastrowid
            hashes = []
            points = geometry["points_per_ccd"]
            ccd_count = len(geometry["ccd_indices"])
            for slot, index in enumerate(geometry["ccd_indices"]):
                raw_by_phase = {}
                for phase, n in [("burn", count), ("dark", dark_count)]:
                    blob = bytes(row[phase + "_adcs_blob"] or b"")
                    if len(blob) != n * ccd_count * points * 2:
                        raise ValueError("legacy raw frame shape mismatch")
                    raw_by_phase[phase] = [
                        blob[(frame * ccd_count + slot) * points * 2 : (frame * ccd_count + slot + 1) * points * 2]
                        for frame in range(n)
                    ]
                if storage == "averaged":
                    blob = bytes(row["mean_blob"] or b"")
                    if len(blob) != ccd_count * points * 4:
                        raise ValueError("legacy mean shape mismatch")
                    mean = blob[slot * points * 4 : (slot + 1) * points * 4]
                else:
                    if json.loads(row["bad_frame_indices_json"] or "[]"):
                        raise ValueError("legacy damaged frames require explicit review")
                    mean = average_points(
                        raw_by_phase["burn"],
                        raw_by_phase["dark"],
                        points,
                        burn_cycle_seconds=float(ignition.get("burn_cyc") or 1),
                        dark_cycle_seconds=float(ignition.get("dark_cyc") or 1),
                    )
                if not all(__import__("math").isfinite(value) for value in struct.unpack(f"<{points}f", mean)):
                    raise ValueError("legacy mean contains non-finite values")
                burn = b"".join(raw_by_phase["burn"])
                dark = b"".join(raw_by_phase["dark"])
                mean_hash = _import_sha(mean)
                hashes.append(mean_hash)
                db.execute(
                    (
                        "INSERT INTO acquisition_sample_bands(sample_id,ccd_index,storage_mode,points_cou"
                        "nt,burn_frame_count,dark_frame_count,mean_blob,mean_sha256,burn_frames_blob,burn"
                        "_sha256,dark_frames_blob,dark_sha256,created_at) VALUES "
                        "(?,?,?,?,?,?,?,?,?,?,?,?,?)"
                    ),
                    (
                        sample,
                        index,
                        storage,
                        points,
                        max(count, 1),
                        dark_count,
                        mean,
                        mean_hash,
                        burn or None,
                        _import_sha(burn) if burn else None,
                        dark or None,
                        _import_sha(dark) if dark else None,
                        now,
                    ),
                )
                for phase in ("burn", "dark"):
                    for frame_index, raw in enumerate(raw_by_phase[phase]):
                        values = list(struct.unpack(f"<{points}H", raw))
                        db.execute(
                            (
                                "INSERT INTO acquisition_frames(task_id,sample_id,repeat_index,phase,frame_index,"
                                "ccd_index,points_blob,points_count,points_sha256,raw_transfer_sha256,raw_byte_le"
                                "ngth,headers_json,virtual_time_ms,peak_value,peak_position,integral_value,damage"
                                "d,captured_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)"
                            ),
                            (
                                task,
                                sample,
                                repeat,
                                phase,
                                frame_index,
                                index,
                                raw,
                                points,
                                _import_sha(raw),
                                row["source_sha256"],
                                len(raw),
                                _import_json({"source_record_id": row["id"], "source_frame_index": frame_index}),
                                frame_index * float(ignition.get(phase + "_cyc") or 1) * 1000,
                                max(values),
                                values.index(max(values)),
                                sum(values),
                                row["measure_time"] or now,
                            ),
                        )
            db.execute(
                "UPDATE acquisition_samples SET result_sha256=? WHERE id=?",
                (
                    _import_sha(
                        {"mean_hashes": hashes, "source_record_id": row["id"], "source_sha256": row["source_sha256"]}
                    ),
                    sample,
                ),
            )
            sample_ids.append(sample)
        db.execute("UPDATE acquisition_tasks SET result_sha256=? WHERE id=?", (_import_sha(metadata), task))
        return sample_ids
