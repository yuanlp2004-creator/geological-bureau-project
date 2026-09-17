"""蒸发区间转换与完整写入事务。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from ..methods import MethodService
from ...db import Database, utc_now
from .errors import PostProcessingError
from .serialization import _json, _sha
from ..acquisition_import import AcquisitionRecordImporter, AcquisitionImportTransaction, ImportedAcquisition, ImportedBand
from .repository import PostProcessingRepository


@dataclass(frozen=True)
class ConversionTransaction:
    connection: sqlite3.Connection
    acquisitions: AcquisitionImportTransaction


class ConversionUnitOfWork:
    def __init__(self, database: Database, acquisitions: AcquisitionRecordImporter):
        self.database = database
        self.acquisitions = acquisitions

    @contextmanager
    def write(self) -> Iterator[ConversionTransaction]:
        with self.database.write() as connection:
            yield ConversionTransaction(connection, self.acquisitions.bind(connection))


class ConversionService:
    def __init__(self, database: Database, repository: PostProcessingRepository, *, methods: MethodService, acquisitions: AcquisitionRecordImporter):
        self.database = database
        self.methods = methods
        self.repository = repository
        self.work = ConversionUnitOfWork(database, acquisitions)

    def _target_layout(self, db: sqlite3.Connection, layout_id: int, source_points: int, selected: list[int] | None) -> tuple[sqlite3.Row, list[int]]:
        layout = db.execute("SELECT * FROM ccd_layouts WHERE id=?", (layout_id,)).fetchone()
        if layout is None:
            raise PostProcessingError("postprocessing_layout_not_found", "目标 CCD 布局不存在", status_code=404)
        if int(layout["points_per_ccd"]) != source_points:
            raise PostProcessingError("postprocessing_no_resample", "源与目标 CCD 点数不一致，禁止隐式重采样", status_code=409, details={"source_points": source_points, "target_points": int(layout["points_per_ccd"])})
        allowed = [int(value) for value in json.loads(layout["ccd_indices_json"] or "[]")]
        chosen = [int(value) for value in (selected or allowed)]
        if not chosen or len(chosen) != len(set(chosen)) or any(value not in allowed for value in chosen):
            raise PostProcessingError("postprocessing_ccd_indices_invalid", "目标 CCD 选择不是布局的有效子集", details={"allowed": allowed})
        return layout, chosen

    def convert_edt(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        record_ids = list(dict.fromkeys(str(value) for value in payload.get("record_ids") or []))
        if not record_ids:
            raise PostProcessingError("postprocessing_selection_empty", "至少选择一个 EDT 记录")
        interval_start = int(payload.get("start_frame", 1))
        interval_end = payload.get("end_frame")
        layout_id = int(payload.get("target_ccd_layout_id"))
        input_data = {"record_ids": record_ids, "start_frame": interval_start, "end_frame": interval_end, "target_ccd_layout_id": layout_id, "target_ccd_indices": payload.get("target_ccd_indices"), "method_version_id": payload.get("method_version_id")}
        fingerprint = _sha(input_data)
        with self.work.write() as transaction:
            db = transaction.connection
            existing = db.execute("SELECT * FROM postprocessing_conversion_runs WHERE input_sha256=?", (fingerprint,)).fetchone()
            if existing is not None:
                return self.repository._conversion_dict(existing)
            rows = [self.repository._raw(identifier, db) for identifier in record_ids]
            if any(row["format"] != "edt" for row in rows):
                raise PostProcessingError("postprocessing_edt_required", "蒸发转换只接受 EDT 记录")
            source_hashes = [str(row["source_sha256"]) for row in rows]
            tasks: list[int] = []
            samples: list[int] = []
            now = utc_now()
            for row in rows:
                frames, count, source_ccd_count, points = self.repository._raw_frames(row, "burn")
                end = count if interval_end is None else int(interval_end)
                if not 1 <= interval_start <= end <= count:
                    raise PostProcessingError("postprocessing_interval_invalid", "选择区间不适用于所有 EDT 记录", details={"record_id": self.repository._id("raw", row["id"]), "frame_count": count})
                layout, selected = self._target_layout(db, layout_id, points, payload.get("target_ccd_indices"))
                source_indices = [int(value) for value in json.loads(row["ccd_indices_json"] or "[]")]
                missing_source_indices = [value for value in selected if value not in source_indices]
                if len(source_indices) != source_ccd_count or missing_source_indices:
                    raise PostProcessingError(
                        "postprocessing_ccd_mapping_invalid",
                        "目标 CCD 无法映射到源记录，禁止隐式重排或插值",
                        status_code=409,
                        details={
                            "source_indices": source_indices,
                            "source_ccd_count": source_ccd_count,
                            "missing_target_indices": missing_source_indices,
                        },
                    )
                task_name = str(payload.get("name") or "S18 EDT 转换").strip()
                method_version_id = payload.get("method_version_id")
                method_row = None
                if method_version_id is not None:
                    method_row = self.methods.bind_snapshots(db).by_id(int(method_version_id), published_only=True)
                    if method_row is None:
                        raise PostProcessingError("postprocessing_method_not_found", "目标方法版本不存在或未发布", status_code=404)
                task_id, sample_id = transaction.acquisitions.import_record(ImportedAcquisition(
                    name=task_name, layout_id=layout["id"], method_version_id=method_version_id,
                    method_id=method_row.method.id if method_row else None,
                    method_version=method_row.version if method_row else None,
                    sample_name=row["sample_name"] or row["band_name"] or f"EDT-{row['id']}",
                    original_sample_name=row["sample_name"] or "", source_record_id=self.repository._id("raw", row["id"]),
                    source_sha256=row["source_sha256"], measure_time=row["measure_time"],
                    interval_start=interval_start, frame_count=end - interval_start + 1,
                    bands=[ImportedBand(target_ccd, points,
                                        [frames[index][source_indices.index(target_ccd)] for index in range(interval_start - 1, end)])
                           for target_ccd in selected],
                    actor_user_id=actor_user_id, created_at=now,
                ))
                tasks.append(task_id)
                samples.append(sample_id)
            run_id = f"s18-conv-{uuid.uuid4().hex}"
            report = {"source_count": len(rows), "converted_count": len(samples), "source_hashes": source_hashes, "target_ccd_layout_id": layout_id}
            db.execute("INSERT INTO postprocessing_conversion_runs(id,input_sha256,status,source_record_ids_json,source_hashes_json,interval_start,interval_end,target_ccd_layout_id,method_version_id,sample_ids_json,task_ids_json,report_json,result_sha256,created_by,created_at,completed_at) VALUES (?,?, 'converted',?,?,?,?,?,?,?,?,?,?,?, ?,?)", (run_id, fingerprint, _json(record_ids), _json(source_hashes), interval_start, max(int(interval_end or 0), interval_start), layout_id, payload.get("method_version_id"), _json(samples), _json(tasks), _json(report), _sha({"samples": samples, "hashes": source_hashes}), actor_user_id, now, now))
            db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) VALUES (?, 'postprocessing.edt.convert', 'postprocessing', NULL, ?, ?)", (actor_user_id, _json(report | {"run_id": run_id}), now))
            return {"id": run_id, "status": "converted", "input_sha256": fingerprint, "source_record_ids": record_ids, "source_hashes": source_hashes, "sample_ids": samples, "task_ids": tasks, "report": report}

