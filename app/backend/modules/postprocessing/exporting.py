"""导出行、文件编码和原子文件写入。"""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import struct
import tempfile
import uuid
from pathlib import Path
from typing import Any
from ...db import Database, utc_now
from .errors import PostProcessingError
from .serialization import _json, _sha
from .repository import PostProcessingRepository

def _xml_escape(value: Any) -> str:
    text = str(value)
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


class ExportService:
    def __init__(self, database: Database, repository: PostProcessingRepository):
        self.database = database
        self.repository = repository

    def _rows_for_export(self, record_ids: list[str], kind: str, db: sqlite3.Connection) -> tuple[list[str], list[list[Any]]]:
        if kind not in {"raw_intensity", "processed_intensity", "result_matrix"}:
            raise PostProcessingError("postprocessing_export_kind_invalid", "不支持的导出矩阵类型")
        if kind == "result_matrix":
            rows: list[list[Any]] = [["source_id", "source_sha256", "status", "sample_name", "repeat_index", "line_id", "element", "wavelength_nm", "quantitative_signal", "calculated_value", "curve_snapshot_id", "calculation_profile"]]
            for identifier in record_ids:
                kind_name, value = self.repository._split(identifier)
                if kind_name == "recalc":
                    recalc = db.execute("SELECT result_json FROM postprocessing_recalculation_runs WHERE id=?", (value,)).fetchone()
                    if recalc is None:
                        raise PostProcessingError("postprocessing_recalc_not_found", "重算批次不存在", status_code=404)
                    payload = json.loads(recalc["result_json"])
                    for source in payload.get("sources", []):
                        for line in source.get("lines", []):
                            rows.append([identifier, source.get("source_sha256"), source.get("status"), line.get("sample_name"), line.get("repeat_index"), line.get("line_id"), line.get("element"), line.get("wavelength_nm"), line.get("quantitative_signal"), line.get("calculated_value"), line.get("curve_snapshot_id"), line.get("calculation_profile")])
                elif kind_name == "result":
                    row = db.execute("SELECT source_sha256, payload_json FROM result_matrices WHERE id=?", (int(value),)).fetchone()
                    if row is None:
                        raise PostProcessingError("postprocessing_result_not_found", "结果矩阵不存在", status_code=404)
                    payload = json.loads(row["payload_json"] or "{}")
                    for line in payload.get("lines", []) or payload.get("sample_rows", []):
                        rows.append([identifier, row["source_sha256"], "source", line.get("name"), line.get("repeat_index"), line.get("line_id"), line.get("element"), line.get("wavelength_nm"), line.get("quantitative_signal", line.get("value")), line.get("calculated_value"), line.get("curve_snapshot_id"), line.get("calculation_profile")])
            return rows[0], rows[1:]
        rows = [["source_id", "source_sha256", "measure_time", "ccd", "frame_index", "point_index", "value"]]
        for identifier in record_ids:
            kind_name, value = self.repository._split(identifier)
            if kind_name == "raw":
                row = self.repository._raw(identifier, db)
                frames, count, ccd_count, points = self.repository._raw_frames(row, "burn")
                if kind == "processed_intensity":
                    for ccd in range(ccd_count):
                        values = [[frame[ccd][point] for frame in frames] for point in range(points)]
                        for point, values_at_point in enumerate(values):
                            rows.append([identifier, row["source_sha256"], row["measure_time"], ccd, "mean", point, sum(values_at_point) / len(values_at_point)])
                else:
                    for frame_index, frame in enumerate(frames, start=1):
                        for ccd in range(ccd_count):
                            for point, value_at_point in enumerate(frame[ccd]):
                                rows.append([identifier, row["source_sha256"], row["measure_time"], ccd, frame_index, point, value_at_point])
            elif kind_name == "sample":
                sample = db.execute("SELECT s.result_sha256, t.sample_name FROM acquisition_samples s JOIN acquisition_tasks t ON t.id=s.task_id WHERE s.id=?", (int(value),)).fetchone()
                if sample is None:
                    raise PostProcessingError("postprocessing_sample_not_found", "转换样品不存在", status_code=404)
                bands = db.execute("SELECT ccd_index, points_count, mean_blob FROM acquisition_sample_bands WHERE sample_id=? ORDER BY ccd_index", (int(value),)).fetchall()
                for band in bands:
                    for point, value_at_point in enumerate(struct.unpack(f"<{int(band['points_count'])}f", bytes(band["mean_blob"]))):
                        rows.append([identifier, sample["result_sha256"], None, band["ccd_index"], "mean", point, value_at_point])
        return rows[0], rows[1:]

    @staticmethod
    def _encode(rows: list[list[Any]], fmt: str) -> tuple[bytes, str, str]:
        if fmt not in {"txt", "csv", "excel"}:
            raise PostProcessingError("postprocessing_export_format_invalid", "导出格式必须为 txt、csv 或 excel")
        if fmt in {"txt", "csv"}:
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, delimiter="\t" if fmt == "txt" else ",", lineterminator="\n")
            writer.writerows(rows)
            content = ("\ufeff" + stream.getvalue()).encode("utf-8")
            return content, "text/plain; charset=utf-8" if fmt == "txt" else "text/csv; charset=utf-8", ".txt" if fmt == "txt" else ".csv"
        parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<?mso-application progid="Excel.Sheet"?>', '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="Matrix"><Table>']
        for row in rows:
            cells = []
            for value in row:
                value_type = "Number" if isinstance(value, (int, float)) and not isinstance(value, bool) else "String"
                cells.append(f'<Cell><Data ss:Type="{value_type}">{_xml_escape(value if value is not None else "")}</Data></Cell>')
            parts.append("<Row>" + "".join(cells) + "</Row>")
        parts.append("</Table></Worksheet></Workbook>")
        return "".join(parts).encode("utf-8"), "application/vnd.ms-excel", ".xls"

    @staticmethod
    def _atomic_write(directory: Path, requested_name: str, content: bytes, extension: str, strategy: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = Path(requested_name).name or "s18-export"
        if not safe_name.lower().endswith(extension):
            safe_name += extension
        target = directory / safe_name
        if target.exists():
            if strategy == "error":
                raise PostProcessingError("postprocessing_export_exists", "目标文件已存在", status_code=409, details={"path": str(target)})
            if strategy == "suffix":
                stem = target.stem
                index = 2
                while (directory / f"{stem} ({index}){extension}").exists():
                    index += 1
                target = directory / f"{stem} ({index}){extension}"
        handle, temp_name = tempfile.mkstemp(prefix=".s18-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
        return target

    def export(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        record_ids = list(dict.fromkeys(str(value) for value in payload.get("record_ids") or []))
        if not record_ids:
            raise PostProcessingError("postprocessing_selection_empty", "至少选择一个导出源")
        kind, fmt = str(payload.get("kind")), str(payload.get("format"))
        directory = Path(str(payload.get("output_directory") or "")).expanduser()
        if not str(directory):
            raise PostProcessingError("postprocessing_output_directory_required", "必须提供输出目录")
        requested_name = str(payload.get("filename") or f"s18-{kind}")
        strategy = str(payload.get("same_name_strategy") or "suffix")
        fingerprint = _sha({"record_ids": record_ids, "kind": kind, "format": fmt, "output_directory": str(directory), "filename": requested_name, "same_name_strategy": strategy})
        with self.database.write() as db:
            existing = db.execute("SELECT * FROM postprocessing_exports WHERE input_sha256=?", (fingerprint,)).fetchone()
            if existing is not None and existing["status"] == "completed" and existing["actual_path"] and Path(existing["actual_path"]).exists():
                return self.repository._export_dict(existing)
            header, data = self._rows_for_export(record_ids, kind, db)
            content, media_type, extension = self._encode([header, *data], fmt)
            target = self._atomic_write(directory, requested_name, content, extension, strategy)
            export_id = f"s18-export-{uuid.uuid4().hex}"
            report = {"row_count": len(data), "column_count": len(header), "media_type": media_type, "encoding": "utf-8-bom" if fmt in {"txt", "csv"} else "utf-8", "atomic": True}
            db.execute("INSERT INTO postprocessing_exports(id,input_sha256,status,source_record_ids_json,kind,format,output_directory,requested_name,actual_path,same_name_strategy,content_sha256,byte_length,report_json,created_by,created_at,completed_at) VALUES (?,?, 'completed',?,?,?,?,?,?,?,?,?,?,?,?,?)", (export_id, fingerprint, _json(record_ids), kind, fmt, str(directory), requested_name, str(target), strategy, _sha(content), len(content), _json(report), actor_user_id, utc_now(), utc_now()))
            db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) VALUES (?, 'postprocessing.export', 'postprocessing', NULL, ?, ?)", (actor_user_id, _json(report | {"export_id": export_id, "path": str(target), "sha256": _sha(content)}), utc_now()))
            return {"id": export_id, "status": "completed", "input_sha256": fingerprint, "path": str(target), "content_sha256": _sha(content), "byte_length": len(content), "report": report}

