"""后处理源数据查询与结果记录装配。"""

from __future__ import annotations

import json
import sqlite3
import struct
from typing import Any
from ..methods import MethodService
from ...db import Database
from .errors import PostProcessingError
from .serialization import _sha


def _unpack_uint16(blob: bytes, count: int) -> list[int]:
    if len(blob) != count * 2:
        raise PostProcessingError("postprocessing_blob_invalid", "原始 CCD 帧长度与布局不一致", status_code=500, details={"expected": count * 2, "actual": len(blob)})
    return list(struct.unpack(f"<{count}H", blob))


def _pack_float32(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


class PostProcessingRepository:
    def __init__(self, database: Database, *, methods: MethodService):
        self.database = database
        self.methods = methods

    @staticmethod
    def _id(kind: str, value: int | str) -> str:
        return f"{kind}:{value}"

    @staticmethod
    def _split(identifier: str) -> tuple[str, str]:
        try:
            kind, value = str(identifier).split(":", 1)
        except ValueError:
            raise PostProcessingError("postprocessing_record_invalid", "记录 ID 必须为 raw:<id>、sample:<id> 或 result:<id>") from None
        if kind not in {"raw", "sample", "result", "recalc"} or not value:
            raise PostProcessingError("postprocessing_record_invalid", "不支持的后处理记录 ID")
        return kind, value

    def edt_records(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.database.read() as db:
            rows = db.execute(
                "SELECT id, format, source_sha256, record_index, sample_no, sample_name, band_name, long_name, measure_time, "
                "frame_count, ccd_count, points_per_ccd, ccd_indices_json, layout_json, ignition_json, details_json "
                "FROM spectrum_bands WHERE format IN ('edt','cmt') ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [
            {
                "id": self._id("raw", int(row["id"])),
                "kind": "raw",
                "format": row["format"],
                "source_sha256": row["source_sha256"],
                "record_index": int(row["record_index"]),
                "sample_no": row["sample_no"],
                "sample_name": row["sample_name"],
                "band_name": row["band_name"] or row["long_name"],
                "measure_time": row["measure_time"],
                "frame_count": int(row["frame_count"]),
                "ccd_count": int(row["ccd_count"]),
                "points_per_ccd": int(row["points_per_ccd"]),
                "ccd_indices": json.loads(row["ccd_indices_json"] or "[]"),
                "layout": json.loads(row["layout_json"] or "{}"),
                "ignition": json.loads(row["ignition_json"] or "{}"),
                "details": json.loads(row["details_json"] or "{}"),
            }
            for row in rows
        ]

    def _raw(self, identifier: str, db: sqlite3.Connection | None = None) -> sqlite3.Row:
        kind, value = self._split(identifier)
        if kind != "raw" or not value.isdigit():
            raise PostProcessingError("postprocessing_raw_required", "此操作只接受 raw:<id> 记录")
        if db is None:
            with self.database.read() as connection:
                return self._raw(identifier, connection)
        row = db.execute("SELECT * FROM spectrum_bands WHERE id=? AND format IN ('edt','cmt')", (int(value),)).fetchone()
        if row is None:
            raise PostProcessingError("postprocessing_full_interval_not_found", "未找到已提交的 EDT/CMT 全时记录", status_code=404, details={"record_id": identifier})
        return row

    @staticmethod
    def _raw_frames(row: sqlite3.Row, phase: str = "burn") -> tuple[list[list[list[int]]], int, int, int]:
        ignition = json.loads(row["ignition_json"] or "{}")
        count = int(ignition.get(f"{phase}_count") or 0)
        ccd_count = int(row["ccd_count"])
        points = int(row["points_per_ccd"])
        blob = bytes((row["burn_adcs_blob"] if phase == "burn" else row["dark_adcs_blob"]) or b"")
        expected = count * ccd_count * points * 2
        if count <= 0 or len(blob) != expected:
            raise PostProcessingError("postprocessing_frame_unavailable", "源记录没有完整的原始帧", status_code=409, details={"phase": phase, "expected": expected, "actual": len(blob)})
        frames: list[list[list[int]]] = []
        stride = ccd_count * points
        for frame_index in range(count):
            frames.append([_unpack_uint16(blob[(frame_index * stride + ccd * points) * 2:(frame_index * stride + (ccd + 1) * points) * 2], points) for ccd in range(ccd_count)])
        return frames, count, ccd_count, points

    def interval(self, record_id: str, *, ccd: int = 0, start_frame: int = 1, end_frame: int | None = None, phase: str = "burn") -> dict[str, Any]:
        with self.database.read() as db:
            row = self._raw(record_id, db)
            frames, count, ccd_count, points = self._raw_frames(row, phase)
        if not 0 <= ccd < ccd_count:
            raise PostProcessingError("postprocessing_ccd_invalid", "CCD 选择超出源布局", details={"ccd_count": ccd_count})
        end = count if end_frame is None else int(end_frame)
        start = int(start_frame)
        if not 1 <= start <= end <= count:
            raise PostProcessingError("postprocessing_interval_invalid", "曝光区间超出源帧范围", details={"frame_count": count, "start": start, "end": end})
        selected = [frames[index][ccd] for index in range(start - 1, end)]
        mean = [sum(frame[index] for frame in selected) / len(selected) for index in range(points)]
        return {
            "id": record_id,
            "source_sha256": row["source_sha256"],
            "measure_time": row["measure_time"],
            "format": row["format"],
            "ccd": ccd,
            "phase": phase,
            "start_frame": start,
            "end_frame": end,
            "frame_count": len(selected),
            "points_per_ccd": points,
            "frames": [{"frame_index": index, "adc": values, "sha256": _sha(struct.pack(f"<{len(values)}H", *values))} for index, values in enumerate(selected, start=start)],
            "mean": {"values": mean, "sha256": _sha(_pack_float32(mean))},
        }

    @staticmethod
    def _conversion_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "status": row["status"], "input_sha256": row["input_sha256"], "source_record_ids": json.loads(row["source_record_ids_json"]), "source_hashes": json.loads(row["source_hashes_json"]), "sample_ids": json.loads(row["sample_ids_json"]), "task_ids": json.loads(row["task_ids_json"]), "report": json.loads(row["report_json"])}

    def conversions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            return [self._conversion_dict(row) for row in db.execute("SELECT * FROM postprocessing_conversion_runs ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)).fetchall()]

    def recalculation_options(self, limit: int = 300) -> dict[str, Any]:
        maximum = max(1, min(int(limit), 500))
        with self.database.read() as db:
            reader = self.methods.bind_snapshots(db)
            methods = [{"method_version_id": item.version_id, "method_id": item.method.id,
                        "version": item.version, "name": item.method.name} for item in reader.published()]
            sources: list[dict[str, Any]] = []
            for row in db.execute(
                "SELECT rm.id, rm.source_sha256, rm.format, rm.payload_json FROM result_matrices rm ORDER BY rm.id DESC LIMIT ?",
                (maximum,),
            ).fetchall():
                payload = json.loads(row["payload_json"] or "{}")
                sources.append({
                    "id": self._id("result", row["id"]), "kind": "result", "label": f"{str(row['format']).upper()} 结果 #{row['id']}",
                    "source_sha256": row["source_sha256"], "method_id": payload.get("method_target_id"),
                    "method_match_status": payload.get("method_match_status"), "measure_time": payload.get("measure_time"),
                })
            for row in db.execute(
                "SELECT s.id, s.result_sha256, s.sample_name, t.method_version_id, json_extract(t.simulator_json, '$.measure_time') AS measure_time "
                "FROM acquisition_samples s JOIN acquisition_tasks t ON t.id=s.task_id "
                "WHERE s.finalized=1 ORDER BY s.id DESC LIMIT ?",
                (maximum,),
            ).fetchall():
                sources.append({
                    "id": self._id("sample", row["id"]), "kind": "sample", "label": row["sample_name"],
                    "source_sha256": row["result_sha256"], "method_version_id": row["method_version_id"], "measure_time": row["measure_time"],
                })
            curves = [dict(row) for row in db.execute(
                "SELECT cs.id, cs.line_id, cs.fit_mode, cs.coordinate_type, cs.result_sha256, "
                "ar.method_version_id, ar.calculation_profile "
                "FROM analysis_curve_snapshots cs JOIN analysis_runs ar ON ar.id=cs.run_id "
                "WHERE cs.publishable=1 ORDER BY cs.id DESC LIMIT ?",
                (maximum,),
            ).fetchall()]
            versions = reader.by_ids([item["method_version_id"] for item in curves])
            curves = [{**item, "method_name": versions[item["method_version_id"]].method.name,
                       "method_version": versions[item["method_version_id"]].version}
                      for item in curves if item["method_version_id"] in versions]
        return {"methods": methods, "sources": sources, "curve_snapshots": curves}

    @staticmethod
    def _recalc_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "status": row["status"], "input_sha256": row["input_sha256"], "result": json.loads(row["result_json"]), "report": json.loads(row["report_json"]), "result_sha256": row["result_sha256"]}

    def recalculations(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            return [self._recalc_dict(row) for row in db.execute("SELECT * FROM postprocessing_recalculation_runs ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)).fetchall()]

    @staticmethod
    def _export_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "status": row["status"], "input_sha256": row["input_sha256"], "path": row["actual_path"], "content_sha256": row["content_sha256"], "byte_length": int(row["byte_length"]), "report": json.loads(row["report_json"])}

    def exports(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            return [self._export_dict(row) for row in db.execute("SELECT * FROM postprocessing_exports ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)).fetchall()]

