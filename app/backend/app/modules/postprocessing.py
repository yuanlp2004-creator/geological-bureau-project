from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import sqlite3
import struct
import tempfile
import uuid
from pathlib import Path
from typing import Any

from ..db import Database, utc_now
from .analysis import AnalysisError, AnalysisService, evaluate_curve
from .spectral_lines import canonical_lines


class PostProcessingError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: Any) -> str:
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _unpack_uint16(blob: bytes, count: int) -> list[int]:
    if len(blob) != count * 2:
        raise PostProcessingError("postprocessing_blob_invalid", "原始 CCD 帧长度与布局不一致", status_code=500, details={"expected": count * 2, "actual": len(blob)})
    return list(struct.unpack(f"<{count}H", blob))


def _pack_float32(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def _xml_escape(value: Any) -> str:
    text = str(value)
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


class PostProcessingService:
    """S18 post-processing application service.

    Legacy migration rows and result matrices are read-only inputs. Converted
    samples and recalculation/export records are append-only snapshots.
    """

    def __init__(self, database: Database):
        self.database = database

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
        with self.database.write() as db:
            existing = db.execute("SELECT * FROM postprocessing_conversion_runs WHERE input_sha256=?", (fingerprint,)).fetchone()
            if existing is not None:
                return self._conversion_dict(existing)
            rows = [self._raw(identifier, db) for identifier in record_ids]
            if any(row["format"] != "edt" for row in rows):
                raise PostProcessingError("postprocessing_edt_required", "蒸发转换只接受 EDT 记录")
            source_hashes = [str(row["source_sha256"]) for row in rows]
            tasks: list[int] = []
            samples: list[int] = []
            now = utc_now()
            for row in rows:
                frames, count, source_ccd_count, points = self._raw_frames(row, "burn")
                end = count if interval_end is None else int(interval_end)
                if not 1 <= interval_start <= end <= count:
                    raise PostProcessingError("postprocessing_interval_invalid", "选择区间不适用于所有 EDT 记录", details={"record_id": self._id("raw", row["id"]), "frame_count": count})
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
                    method_row = db.execute("SELECT id, method_id, version FROM method_versions WHERE id=? AND state='published'", (int(method_version_id),)).fetchone()
                    if method_row is None:
                        raise PostProcessingError("postprocessing_method_not_found", "目标方法版本不存在或未发布", status_code=404)
                task_cursor = db.execute(
                    "INSERT INTO acquisition_tasks(task_kind,name,status,device_profile_id,ccd_layout_id,method_version_id,method_id,method_version,sample_name,sample_kind,naming_mode,storage_mode,repeat_count,current_repeat_index,completed_repeats,burn_frame_count,dark_frame_count,countdown_seconds,countdown_remaining,pre_excitation_seconds,sampling_period_seconds,burn_cycle_seconds,dark_cycle_seconds,ccd_indices_json,excitation_condition_json,evaporation_condition_json,simulator_json,created_by,created_at,updated_at,completed_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("sample", task_name, "completed", 1, layout["id"], method_version_id, method_row["method_id"] if method_row else None, method_row["version"] if method_row else None, row["sample_name"] or row["band_name"] or f"EDT-{row['id']}", "normal", "pre_recorded", "full_interval", 1, 0, 1, end - interval_start + 1, 0, 0, 0, 0, 1, 1, 1, _json(selected), "{}", "{}", _json({"source_record_id": self._id("raw", row["id"]), "source_sha256": row["source_sha256"], "measure_time": row["measure_time"]}), actor_user_id, now, now, now),
                )
                task_id = int(task_cursor.lastrowid)
                sample_cursor = db.execute(
                    "INSERT INTO acquisition_samples(task_id,repeat_index,sample_name_original,sample_name,sample_kind,storage_mode,status,finalized,result_sha256,created_at,completed_at,updated_at) VALUES (?,?,?,?,?,'full_interval','completed',1,?,?,?,?)",
                    (task_id, 0, row["sample_name"] or "", row["sample_name"] or row["band_name"] or f"EDT-{row['id']}", "normal", None, now, now, now),
                )
                sample_id = int(sample_cursor.lastrowid)
                band_hashes: list[str] = []
                for target_ccd in selected:
                    source_ccd = source_indices.index(target_ccd)
                    values = [frames[index][source_ccd] for index in range(interval_start - 1, end)]
                    mean = [sum(frame[point] for frame in values) / len(values) for point in range(points)]
                    mean_blob = _pack_float32(mean)
                    burn_blob = b"".join(struct.pack(f"<{points}H", *frame) for frame in values)
                    mean_sha, burn_sha = _sha(mean_blob), _sha(burn_blob)
                    band_hashes.extend([mean_sha, burn_sha])
                    db.execute("INSERT INTO acquisition_sample_bands(sample_id,ccd_index,storage_mode,points_count,burn_frame_count,dark_frame_count,mean_blob,mean_sha256,burn_frames_blob,burn_sha256,created_at) VALUES (?,?,?,?,?,0,?,?,?,?,?)", (sample_id, target_ccd, "full_interval", points, len(values), mean_blob, mean_sha, burn_blob, burn_sha, now))
                    for frame_index, frame_values in enumerate(values):
                        raw_blob = struct.pack(f"<{points}H", *frame_values)
                        db.execute("INSERT INTO acquisition_frames(task_id,sample_id,repeat_index,phase,frame_index,ccd_index,points_blob,points_count,points_sha256,raw_transfer_sha256,raw_byte_length,headers_json,virtual_time_ms,peak_value,peak_position,integral_value,damaged,captured_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)", (task_id, sample_id, 0, "burn", frame_index, target_ccd, raw_blob, points, _sha(raw_blob), row["source_sha256"], len(raw_blob), _json({"source_record_id": self._id("raw", row["id"]), "source_frame_index": frame_index + interval_start - 1}), float(frame_index), max(frame_values), frame_values.index(max(frame_values)), float(sum(frame_values)), now))
                result_hash = _sha(band_hashes)
                db.execute("UPDATE acquisition_samples SET result_sha256=? WHERE id=?", (result_hash, sample_id))
                db.execute("UPDATE acquisition_tasks SET result_sha256=? WHERE id=?", (result_hash, task_id))
                tasks.append(task_id)
                samples.append(sample_id)
            run_id = f"s18-conv-{uuid.uuid4().hex}"
            report = {"source_count": len(rows), "converted_count": len(samples), "source_hashes": source_hashes, "target_ccd_layout_id": layout_id}
            db.execute("INSERT INTO postprocessing_conversion_runs(id,input_sha256,status,source_record_ids_json,source_hashes_json,interval_start,interval_end,target_ccd_layout_id,method_version_id,sample_ids_json,task_ids_json,report_json,result_sha256,created_by,created_at,completed_at) VALUES (?,?, 'converted',?,?,?,?,?,?,?,?,?,?,?, ?,?)", (run_id, fingerprint, _json(record_ids), _json(source_hashes), interval_start, max(int(interval_end or 0), interval_start), layout_id, payload.get("method_version_id"), _json(samples), _json(tasks), _json(report), _sha({"samples": samples, "hashes": source_hashes}), actor_user_id, now, now))
            db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) VALUES (?, 'postprocessing.edt.convert', 'postprocessing', NULL, ?, ?)", (actor_user_id, _json(report | {"run_id": run_id}), now))
            return {"id": run_id, "status": "converted", "input_sha256": fingerprint, "source_record_ids": record_ids, "source_hashes": source_hashes, "sample_ids": samples, "task_ids": tasks, "report": report}

    @staticmethod
    def _conversion_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "status": row["status"], "input_sha256": row["input_sha256"], "source_record_ids": json.loads(row["source_record_ids_json"]), "source_hashes": json.loads(row["source_hashes_json"]), "sample_ids": json.loads(row["sample_ids_json"]), "task_ids": json.loads(row["task_ids_json"]), "report": json.loads(row["report_json"])}

    def conversions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            return [self._conversion_dict(row) for row in db.execute("SELECT * FROM postprocessing_conversion_runs ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)).fetchall()]

    def recalculation_options(self, limit: int = 300) -> dict[str, Any]:
        maximum = max(1, min(int(limit), 500))
        with self.database.read() as db:
            methods = [dict(row) for row in db.execute(
                "SELECT mv.id AS method_version_id, mv.method_id, mv.version, m.name "
                "FROM method_versions mv JOIN methods m ON m.id=mv.method_id "
                "WHERE mv.state='published' ORDER BY m.name, mv.version DESC"
            ).fetchall()]
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
                "ar.method_version_id, ar.calculation_profile, m.name AS method_name, mv.version AS method_version "
                "FROM analysis_curve_snapshots cs JOIN analysis_runs ar ON ar.id=cs.run_id "
                "JOIN method_versions mv ON mv.id=ar.method_version_id JOIN methods m ON m.id=mv.method_id "
                "WHERE cs.publishable=1 ORDER BY cs.id DESC LIMIT ?",
                (maximum,),
            ).fetchall()]
        return {"methods": methods, "sources": sources, "curve_snapshots": curves}

    @staticmethod
    def _method_lines(method_payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            line for line in canonical_lines(method_payload.get("lines"), method_payload.get("conditions", {}))
            if line.get("enabled")
        ]

    @staticmethod
    def _match_source_line(target: dict[str, Any], source_lines: list[dict[str, Any]]) -> int | None:
        element = str(target.get("element") or "").strip().casefold()
        wavelength = float(target.get("wavelength_nm") or 0.0)
        matches = [
            index for index, line in enumerate(source_lines)
            if str(line.get("element") or "").strip().casefold() == element
            and line.get("wavelength_nm") is not None
            and math.isclose(float(line["wavelength_nm"]), wavelength, rel_tol=0.0, abs_tol=0.01)
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _legacy_net(pair: tuple[float, float], source_line: dict[str, Any], *, background_ratio: bool = False) -> float:
        peak, background = (float(pair[0]), float(pair[1]))
        has_background = int(source_line.get("back") or 0) != 0
        if background_ratio:
            if not has_background or abs(background) < 1e-12:
                raise PostProcessingError("postprocessing_background_invalid", "背景内标需要非零背景强度")
            value = peak / background
        else:
            value = peak - background if has_background else peak
        return max(1e-5, value)

    def _recalculate_legacy_result(
        self,
        row: sqlite3.Row,
        method_payload: dict[str, Any],
        evaluators: dict[str, dict[str, Any]],
        calculation_profile: str,
    ) -> dict[str, Any]:
        if row["format"] != "pdt":
            raise PostProcessingError("postprocessing_result_not_recalculable", "只有保存 Peak/Back 的 PDT 强度结果可以精确重算")
        if calculation_profile != "legacy_2_0_2":
            raise PostProcessingError("postprocessing_result_profile_invalid", "旧 PDT 不含 modern_v1 所需峰面积，只能使用 legacy_2_0_2 重算")
        payload = json.loads(row["payload_json"] or "{}")
        source_lines = list(payload.get("lines") or [])
        band_count = int(payload.get("band_count") or 0)
        line_count = int(payload.get("line_count") or len(source_lines))
        raw = bytes(row["matrix_blob"] or b"")
        if band_count <= 0 or line_count != len(source_lines) or len(raw) != line_count * band_count * 8:
            raise PostProcessingError(
                "postprocessing_result_matrix_invalid", "PDT 强度矩阵与元数据不一致", status_code=409,
                details={"line_count": line_count, "band_count": band_count, "expected_bytes": line_count * band_count * 8, "actual_bytes": len(raw)},
            )
        values = list(struct.iter_unpack("<ff", raw))
        matrix = [values[index * band_count:(index + 1) * band_count] for index in range(line_count)]
        method_lines = self._method_lines(method_payload)
        by_id = {str(line.get("id")): line for line in method_lines}
        sample_rows = list(payload.get("sample_rows") or [])
        diagnostics: list[dict[str, Any]] = []
        calculated: list[dict[str, Any]] = []
        for line in (item for item in method_lines if item.get("line_type") == "analysis"):
            line_id = str(line.get("id"))
            source_index = self._match_source_line(line, source_lines)
            evaluator = evaluators.get(line_id)
            if source_index is None:
                diagnostics.append({"line_id": line_id, "code": "source_line_missing"})
                continue
            if evaluator is None:
                diagnostics.append({"line_id": line_id, "code": "curve_snapshot_missing"})
                continue
            internal_source_index: int | None = None
            mode = str(line.get("internal_standard_mode") or "none")
            if mode == "line":
                internal = by_id.get(str(line.get("internal_standard_line_id") or ""))
                internal_source_index = self._match_source_line(internal, source_lines) if internal is not None else None
                if internal_source_index is None:
                    diagnostics.append({"line_id": line_id, "code": "internal_standard_line_missing"})
                    continue
            for sample_index in range(band_count):
                try:
                    signal = self._legacy_net(matrix[source_index][sample_index], source_lines[source_index], background_ratio=mode == "background")
                    if internal_source_index is not None:
                        internal = self._legacy_net(matrix[internal_source_index][sample_index], source_lines[internal_source_index])
                        signal = max(1e-5, signal / internal)
                    value = evaluate_curve(evaluator["fit"], signal, evaluator["coordinate_type"])
                except (AnalysisError, PostProcessingError) as exc:
                    code = exc.code if isinstance(exc, (AnalysisError, PostProcessingError)) else "postprocessing_recalculation_failed"
                    diagnostics.append({"line_id": line_id, "sample_index": sample_index, "code": code})
                    continue
                sample = sample_rows[sample_index] if sample_index < len(sample_rows) else {"expanded_index": sample_index, "name": f"#{sample_index + 1}"}
                calculated.append({
                    "sample_index": int(sample.get("expanded_index", sample_index)), "sample_name": str(sample.get("name") or f"#{sample_index + 1}"),
                    "repeat_index": int(sample.get("repeat_index", 1)), "line_id": line_id, "element": line.get("element"),
                    "wavelength_nm": float(line.get("wavelength_nm") or 0.0), "quantitative_signal": signal,
                    "calculated_value": value, "curve_snapshot_id": evaluator["curve_snapshot_id"], "calculation_profile": calculation_profile,
                })
        if not calculated:
            raise PostProcessingError("postprocessing_recalculation_no_lines", "没有可按所选方法和曲线重算的 PDT 谱线", details={"diagnostics": diagnostics})
        return {
            "source_sha256": row["source_sha256"], "status": "partial" if diagnostics else "recalculated",
            "line_count": len({item["line_id"] for item in calculated}), "sample_count": band_count,
            "lines": calculated, "diagnostics": diagnostics,
        }

    def recalculate(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        source_ids = list(dict.fromkeys(str(value) for value in payload.get("source_record_ids") or []))
        if not source_ids:
            raise PostProcessingError("postprocessing_selection_empty", "至少选择一个重算源")
        method_version_id = int(payload.get("method_version_id"))
        profile = str(payload.get("calculation_profile") or "legacy_2_0_2")
        curve_ids = [int(value) for value in payload.get("curve_snapshot_ids") or []]
        expected_measure_time = payload.get("expected_measure_time")
        fingerprint = _sha({"source_record_ids": source_ids, "method_version_id": method_version_id, "calculation_profile": profile, "curve_snapshot_ids": curve_ids, "expected_measure_time": expected_measure_time})
        with self.database.read() as db:
            existing = db.execute("SELECT * FROM postprocessing_recalculation_runs WHERE input_sha256=?", (fingerprint,)).fetchone()
            method = db.execute("SELECT id, method_id, version, payload_json FROM method_versions WHERE id=? AND state='published'", (method_version_id,)).fetchone()
        if existing is not None:
            return self._recalc_dict(existing)
        if method is None:
            raise PostProcessingError("postprocessing_method_not_found", "目标方法版本不存在或未发布", status_code=404)
        try:
            evaluators = AnalysisService(self.database).curve_evaluators(curve_ids, method_version_id, profile)
        except AnalysisError as exc:
            raise PostProcessingError(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc
        method_payload = json.loads(method["payload_json"])
        analysis_results: dict[str, dict[str, Any]] = {}
        analysis_blocked: list[dict[str, Any]] = []
        created_analysis_runs: list[int] = []
        sample_sources = [identifier for identifier in source_ids if self._split(identifier)[0] == "sample"]
        for sample_source in sample_sources:
            try:
                analysis_run = AnalysisService(self.database).create_run({"name": "S18 精确版本重算", "acquisition_sample_ids": [int(self._split(sample_source)[1])], "method_version_id": method_version_id, "calculation_profile": profile}, actor_user_id)
                created_analysis_runs.append(int(analysis_run["id"]))
                analysis_run = AnalysisService(self.database).start(int(analysis_run["id"]), actor_user_id)
                while analysis_run.get("status") == "running":
                    analysis_run = AnalysisService(self.database).step(int(analysis_run["id"]), actor_user_id)
                if analysis_run.get("status") != "completed":
                    analysis_blocked.append({"id": sample_source, "code": "analysis_run_not_completed", "analysis_run_id": analysis_run.get("id"), "status": analysis_run.get("status")})
                else:
                    diagnostics: list[dict[str, Any]] = []
                    lines: list[dict[str, Any]] = []
                    sample_names = {int(item["position"]): str(item["sample_name"]) for item in analysis_run.get("samples", [])}
                    for item in analysis_run.get("line_results", []):
                        if item.get("line_type") != "analysis":
                            continue
                        evaluator = evaluators.get(str(item.get("line_id")))
                        if evaluator is None:
                            diagnostics.append({"line_id": item.get("line_id"), "code": "curve_snapshot_missing"})
                            continue
                        value = evaluate_curve(evaluator["fit"], float(item["quantitative_signal"]), evaluator["coordinate_type"])
                        lines.append({
                            "sample_index": int(item["sample_position"]), "sample_name": sample_names.get(int(item["sample_position"]), sample_source),
                            "repeat_index": 1, "line_id": item["line_id"], "element": item["element"], "wavelength_nm": item["wavelength_nm"],
                            "quantitative_signal": item["quantitative_signal"], "calculated_value": value,
                            "curve_snapshot_id": evaluator["curve_snapshot_id"], "calculation_profile": profile,
                        })
                    if not lines:
                        analysis_blocked.append({"id": sample_source, "code": "postprocessing_recalculation_no_lines", "analysis_run_id": analysis_run.get("id"), "diagnostics": diagnostics})
                    else:
                        analysis_results[sample_source] = {"analysis_run_id": analysis_run.get("id"), "status": "partial" if diagnostics else "recalculated", "lines": lines, "diagnostics": diagnostics}
            except AnalysisError as exc:
                analysis_blocked.append({"id": sample_source, "code": exc.code, "message": exc.message, "details": exc.details})
        with self.database.write() as db:
            existing = db.execute("SELECT * FROM postprocessing_recalculation_runs WHERE input_sha256=?", (fingerprint,)).fetchone()
            if existing is not None:
                if created_analysis_runs:
                    db.executemany("DELETE FROM analysis_runs WHERE id=?", [(created_id,) for created_id in created_analysis_runs])
                return self._recalc_dict(existing)
            method = db.execute("SELECT id, method_id, version, payload_json FROM method_versions WHERE id=? AND state='published'", (method_version_id,)).fetchone()
            if method is None:
                raise PostProcessingError("postprocessing_method_not_found", "目标方法版本不存在或未发布", status_code=404)
            result: dict[str, Any] = {"sources": [], "method_version_id": method_version_id, "calculation_profile": profile, "curve_snapshot_ids": curve_ids}
            blocked: list[dict[str, Any]] = []
            for source_id in source_ids:
                kind, value = self._split(source_id)
                if not value.isdigit() and kind != "recalc":
                    raise PostProcessingError("postprocessing_record_invalid", "源记录 ID 无效")
                if kind == "result":
                    row = db.execute("SELECT * FROM result_matrices WHERE id=?", (int(value),)).fetchone()
                    if row is None:
                        raise PostProcessingError("postprocessing_result_not_found", "结果矩阵不存在", status_code=404)
                    payload_json = json.loads(row["payload_json"] or "{}")
                    legacy_target = payload_json.get("method_target_id")
                    if legacy_target is not None and str(legacy_target) != str(method["method_id"]):
                        blocked.append({"id": source_id, "code": "method_version_mismatch", "source_method_target_id": legacy_target})
                        continue
                    if expected_measure_time and payload_json.get("measure_time") and str(payload_json["measure_time"]) != str(expected_measure_time):
                        blocked.append({"id": source_id, "code": "measure_time_mismatch", "source_measure_time": payload_json["measure_time"], "expected_measure_time": expected_measure_time})
                        continue
                    try:
                        recalculated = self._recalculate_legacy_result(row, method_payload, evaluators, profile)
                    except PostProcessingError as exc:
                        blocked.append({"id": source_id, "code": exc.code, "message": exc.message, "details": exc.details})
                        continue
                    result["sources"].append({"id": source_id, **recalculated})
                elif kind == "sample":
                    sample = db.execute("SELECT s.id, s.result_sha256, t.method_version_id, json_extract(t.simulator_json, '$.measure_time') AS measure_time FROM acquisition_samples s JOIN acquisition_tasks t ON t.id=s.task_id WHERE s.id=? AND s.finalized=1", (int(value),)).fetchone()
                    if sample is None:
                        raise PostProcessingError("postprocessing_sample_not_found", "转换样品不存在或尚未固化", status_code=404)
                    if int(sample["method_version_id"] or 0) != method_version_id:
                        blocked.append({"id": source_id, "code": "method_version_mismatch", "sample_method_version_id": sample["method_version_id"]})
                        continue
                    if expected_measure_time and sample["measure_time"] and str(sample["measure_time"]) != str(expected_measure_time):
                        blocked.append({"id": source_id, "code": "measure_time_mismatch", "source_measure_time": sample["measure_time"], "expected_measure_time": expected_measure_time})
                        continue
                    if int(sample["method_version_id"] or 0) != method_version_id:
                        blocked.append({"id": source_id, "code": "method_version_mismatch", "sample_method_version_id": sample["method_version_id"]})
                    elif source_id in analysis_results:
                        result["sources"].append({"id": source_id, "source_sha256": sample["result_sha256"], **analysis_results[source_id]})
                    else:
                        matching_block = next((item for item in analysis_blocked if item.get("id") == source_id), None)
                        if matching_block is None:
                            blocked.append({"id": source_id, "code": "analysis_run_not_completed"})
                elif kind == "recalc":
                    row = db.execute("SELECT result_json, result_sha256, method_version_id, calculation_profile, curve_snapshot_ids_json FROM postprocessing_recalculation_runs WHERE id=?", (value,)).fetchone()
                    if row is None:
                        raise PostProcessingError("postprocessing_recalc_not_found", "重算批次不存在", status_code=404)
                    if int(row["method_version_id"]) != method_version_id or str(row["calculation_profile"]) != profile or json.loads(row["curve_snapshot_ids_json"]) != curve_ids:
                        blocked.append({"id": source_id, "code": "recalculation_version_mismatch"})
                    else:
                        previous = json.loads(row["result_json"])
                        result["sources"].append({"id": source_id, "source_sha256": row["result_sha256"], "status": "recalculated", "lines": [line for source in previous.get("sources", []) for line in source.get("lines", [])]})
                else:
                    raise PostProcessingError("postprocessing_source_kind_invalid", "重算源必须是 result、sample 或 recalc")
            blocked.extend(item for item in analysis_blocked if item not in blocked)
            if blocked:
                result["discarded_sources"] = [item["id"] for item in result["sources"]]
                result["sources"] = []
                if created_analysis_runs:
                    db.executemany("DELETE FROM analysis_runs WHERE id=?", [(run_id,) for run_id in created_analysis_runs])
            status = "blocked" if blocked else "completed"
            result["blocked"] = blocked
            digest = _sha(result)
            run_id = f"s18-recalc-{uuid.uuid4().hex}"
            report = {"source_count": len(source_ids), "completed_count": len(result["sources"]), "blocked_count": len(blocked), "atomic_rollback": bool(blocked), "idempotent_input_sha256": fingerprint}
            first_block = blocked[0] if blocked else None
            db.execute("INSERT INTO postprocessing_recalculation_runs(id,input_sha256,status,source_record_ids_json,source_hashes_json,method_version_id,calculation_profile,curve_snapshot_ids_json,result_json,report_json,result_sha256,created_by,created_at,completed_at,error_code,error_message) VALUES (?,?,?, ?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id, fingerprint, status, _json(source_ids), _json([item.get("source_sha256") for item in result["sources"]]), method_version_id, profile, _json(curve_ids), _json(result), _json(report), digest, actor_user_id, utc_now(), utc_now(), first_block.get("code") if first_block else None, first_block.get("message", "重算批次因输入或版本校验失败而回滚") if first_block else None))
            db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) VALUES (?, 'postprocessing.recalculate', 'postprocessing', NULL, ?, ?)", (actor_user_id, _json(report | {"run_id": run_id}), utc_now()))
            return {"id": run_id, "status": status, "input_sha256": fingerprint, "result": result, "report": report}

    @staticmethod
    def _recalc_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "status": row["status"], "input_sha256": row["input_sha256"], "result": json.loads(row["result_json"]), "report": json.loads(row["report_json"]), "result_sha256": row["result_sha256"]}

    def recalculations(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            return [self._recalc_dict(row) for row in db.execute("SELECT * FROM postprocessing_recalculation_runs ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)).fetchall()]

    def _rows_for_export(self, record_ids: list[str], kind: str, db: sqlite3.Connection) -> tuple[list[str], list[list[Any]]]:
        if kind not in {"raw_intensity", "processed_intensity", "result_matrix"}:
            raise PostProcessingError("postprocessing_export_kind_invalid", "不支持的导出矩阵类型")
        if kind == "result_matrix":
            rows: list[list[Any]] = [["source_id", "source_sha256", "status", "sample_name", "repeat_index", "line_id", "element", "wavelength_nm", "quantitative_signal", "calculated_value", "curve_snapshot_id", "calculation_profile"]]
            for identifier in record_ids:
                kind_name, value = self._split(identifier)
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
            kind_name, value = self._split(identifier)
            if kind_name == "raw":
                row = self._raw(identifier, db)
                frames, count, ccd_count, points = self._raw_frames(row, "burn")
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
                return self._export_dict(existing)
            header, data = self._rows_for_export(record_ids, kind, db)
            content, media_type, extension = self._encode([header, *data], fmt)
            target = self._atomic_write(directory, requested_name, content, extension, strategy)
            export_id = f"s18-export-{uuid.uuid4().hex}"
            report = {"row_count": len(data), "column_count": len(header), "media_type": media_type, "encoding": "utf-8-bom" if fmt in {"txt", "csv"} else "utf-8", "atomic": True}
            db.execute("INSERT INTO postprocessing_exports(id,input_sha256,status,source_record_ids_json,kind,format,output_directory,requested_name,actual_path,same_name_strategy,content_sha256,byte_length,report_json,created_by,created_at,completed_at) VALUES (?,?, 'completed',?,?,?,?,?,?,?,?,?,?,?,?,?)", (export_id, fingerprint, _json(record_ids), kind, fmt, str(directory), requested_name, str(target), strategy, _sha(content), len(content), _json(report), actor_user_id, utc_now(), utc_now()))
            db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) VALUES (?, 'postprocessing.export', 'postprocessing', NULL, ?, ?)", (actor_user_id, _json(report | {"export_id": export_id, "path": str(target), "sha256": _sha(content)}), utc_now()))
            return {"id": export_id, "status": "completed", "input_sha256": fingerprint, "path": str(target), "content_sha256": _sha(content), "byte_length": len(content), "report": report}

    @staticmethod
    def _export_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "status": row["status"], "input_sha256": row["input_sha256"], "path": row["actual_path"], "content_sha256": row["content_sha256"], "byte_length": int(row["byte_length"]), "report": json.loads(row["report_json"])}

    def exports(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            return [self._export_dict(row) for row in db.execute("SELECT * FROM postprocessing_exports ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)).fetchall()]
