from __future__ import annotations

import hashlib
import json
import math
import struct
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..db import Database, utc_now
from .legacy_migration import LegacyMigrationService
from .methods import _json


DAT_HEAD = 0x0A64
PDT_HEAD = 0x0A70
EXP_SEG_PDT_HEAD = 0x0A73
NAME_WIDTH = 10
ELEMENT_WIDTH = 4
MAX_SAMPLES = 1000
MAX_LINES = 300
MAX_PDT_BANDS = 320
PARSER_VERSION = "s09-result-1"
SUPPORTED_FORMATS = {"dat", "pdt"}


class ResultMigrationError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _snapshot(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        raw = path.read_bytes()
    except OSError as exc:
        raise ResultMigrationError("result_source_unreadable", f"Unable to read result file: {path}", details={"reason": str(exc)}) from exc
    if not path.is_file():
        raise ResultMigrationError("result_source_not_file", f"Result source is not a file: {path}")
    return {"path": str(path.resolve()), "name": path.name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="milliseconds"), "sha256": hashlib.sha256(raw).hexdigest()}


class ResultMigrationService:
    """Strict, read-only importer for SpecDirect .dat/.pdt result matrices."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _time(raw_value: float) -> str:
        if not math.isfinite(raw_value):
            raise ResultMigrationError("result_datetime_invalid", "MeasureTime is not finite")
        value = datetime(1899, 12, 30, tzinfo=timezone.utc) + timedelta(days=raw_value)
        return value.isoformat(timespec="milliseconds")

    @staticmethod
    def _decode(raw: bytes, position: int, width: int, field: str) -> tuple[str, int, str]:
        if position + width + 1 > len(raw):
            raise ResultMigrationError("result_file_truncated", f"Truncated {field} short string", details={"offset": position})
        length = raw[position]
        if length > width:
            raise ResultMigrationError("result_short_string_invalid", f"Invalid {field} short string length", details={"length": length, "max": width})
        field_bytes = raw[position + 1 : position + 1 + width]
        active = field_bytes[:length]
        if not active:
            return "", position + 1 + width, "ascii"
        for encoding in ("gb18030", "utf-8", "cp1252"):
            try:
                return active.decode(encoding), position + 1 + width, encoding
            except UnicodeDecodeError:
                continue
        raise ResultMigrationError("result_encoding_invalid", f"Unable to decode {field} short string")

    @staticmethod
    def _bounds(count: int, maximum: int, field: str) -> None:
        if not 1 <= count <= maximum:
            raise ResultMigrationError("result_count_invalid", f"{field} is outside the supported legacy range", details={"count": count, "max": maximum})

    @staticmethod
    def _samples(values: list[Any], columns: int, *, kind: str) -> list[dict[str, Any]]:
        if not values or columns <= 0:
            return []
        total_rows = len(values) // columns
        indexes = sorted({0, len(values) - 1, len(values) // 2})
        result: list[dict[str, Any]] = []
        for flat in indexes:
            row, column = divmod(flat, columns)
            item: dict[str, Any] = {"row": row, "column": column, "kind": kind}
            if kind == "peak_back":
                item["peak"], item["back"] = values[flat]
            else:
                item["value"] = values[flat]
            result.append(item)
        return result

    @classmethod
    def _parse(cls, raw: bytes, fmt: str, source: dict[str, Any]) -> dict[str, Any]:
        if len(raw) < 2:
            raise ResultMigrationError("result_file_truncated", "Result file is shorter than its header")
        header = struct.unpack_from("<H", raw, 0)[0]
        if fmt == "dat" and header != DAT_HEAD:
            raise ResultMigrationError("result_header_unknown", "Unknown .dat header", details={"header": hex(header), "expected": hex(DAT_HEAD)})
        if fmt == "pdt" and header not in {PDT_HEAD, EXP_SEG_PDT_HEAD}:
            raise ResultMigrationError("result_header_unknown", "Unknown .pdt header", details={"header": hex(header), "expected": [hex(PDT_HEAD), hex(EXP_SEG_PDT_HEAD)]})
        position = 2
        encodings: set[str] = set()
        if fmt == "dat":
            if len(raw) < position + 12:
                raise ResultMigrationError("result_file_truncated", "Truncated .dat metadata")
            measure_raw = struct.unpack_from("<d", raw, position)[0]; position += 8
            sample_count, line_count = struct.unpack_from("<hh", raw, position); position += 4
            cls._bounds(sample_count, MAX_SAMPLES, "sample_count")
            cls._bounds(line_count, MAX_LINES, "line_count")
            sample_names: list[str] = []
            for index in range(sample_count):
                value, position, encoding = cls._decode(raw, position, NAME_WIDTH, f"sample[{index}]")
                sample_names.append(value); encodings.add(encoding)
            elements: list[str] = []
            for index in range(line_count):
                value, position, encoding = cls._decode(raw, position, ELEMENT_WIDTH, f"element[{index}]")
                elements.append(value); encodings.add(encoding)
            if position + line_count * 2 > len(raw):
                raise ResultMigrationError("result_file_truncated", "Truncated .dat digit metadata")
            digits = list(struct.unpack_from(f"<{line_count}h", raw, position)); position += line_count * 2
            matrix_size = line_count * sample_count * 4
            expected = position + matrix_size
            if len(raw) < expected:
                raise ResultMigrationError("result_file_truncated", "Truncated .dat matrix", details={"expected": expected, "actual": len(raw)})
            if len(raw) > expected:
                raise ResultMigrationError("result_file_layout_invalid", "Unexpected trailing bytes in .dat file", details={"expected": expected, "actual": len(raw)})
            matrix_blob = raw[position:expected]
            values = list(struct.unpack(f"<{line_count * sample_count}f", matrix_blob))
            if not all(math.isfinite(value) for value in values):
                raise ResultMigrationError("result_matrix_nonfinite", "The .dat matrix contains a non-finite value")
            lines = [{"index": index, "element": elements[index], "wavelength_nm": None, "back": None, "digits": digits[index]} for index in range(line_count)]
            band_count = sample_count
            kind = "value"
            method_legacy_id = None
            exp_segments: list[dict[str, int]] = []
        else:
            if len(raw) < position + 16:
                raise ResultMigrationError("result_file_truncated", "Truncated .pdt metadata")
            method_legacy_id = struct.unpack_from("<i", raw, position)[0]; position += 4
            measure_raw = struct.unpack_from("<d", raw, position)[0]; position += 8
            sample_count, line_count = struct.unpack_from("<hh", raw, position); position += 4
            cls._bounds(sample_count, MAX_SAMPLES, "sample_count")
            cls._bounds(line_count, MAX_LINES, "line_count")
            sample_names = []
            for index in range(sample_count):
                value, position, encoding = cls._decode(raw, position, NAME_WIDTH, f"sample[{index}]")
                sample_names.append(value); encodings.add(encoding)
            if position + sample_count * 2 > len(raw):
                raise ResultMigrationError("result_file_truncated", "Truncated .pdt repeat metadata")
            sample_reps = list(struct.unpack_from(f"<{sample_count}h", raw, position)); position += sample_count * 2
            if any(repeat <= 0 for repeat in sample_reps):
                raise ResultMigrationError("result_repeat_invalid", "Every .pdt sample repeat count must be positive")
            band_count = sum(sample_reps)
            cls._bounds(band_count, MAX_PDT_BANDS, "expanded_band_count")
            elements = []
            for index in range(line_count):
                value, position, encoding = cls._decode(raw, position, ELEMENT_WIDTH, f"element[{index}]")
                elements.append(value); encodings.add(encoding)
            metadata_size = line_count * (4 + 2 + 2)
            if position + metadata_size > len(raw):
                raise ResultMigrationError("result_file_truncated", "Truncated .pdt line metadata")
            waves = list(struct.unpack_from(f"<{line_count}f", raw, position)); position += line_count * 4
            backs = list(struct.unpack_from(f"<{line_count}h", raw, position)); position += line_count * 2
            digits = list(struct.unpack_from(f"<{line_count}h", raw, position)); position += line_count * 2
            exp_segments = []
            if header == EXP_SEG_PDT_HEAD:
                if position + line_count * 2 > len(raw):
                    raise ResultMigrationError("result_file_truncated", "Truncated .pdt exposure segments")
                for index in range(line_count):
                    left, right = struct.unpack_from("<BB", raw, position); position += 2
                    exp_segments.append({"left": left, "right": right})
            matrix_size = line_count * band_count * 8
            expected = position + matrix_size
            if len(raw) < expected:
                raise ResultMigrationError("result_file_truncated", "Truncated .pdt matrix", details={"expected": expected, "actual": len(raw)})
            if len(raw) > expected:
                raise ResultMigrationError("result_file_layout_invalid", "Unexpected trailing bytes in .pdt file", details={"expected": expected, "actual": len(raw)})
            matrix_blob = raw[position:expected]
            values = list(struct.iter_unpack("<ff", matrix_blob))
            if not all(math.isfinite(value) for pair in values for value in pair):
                raise ResultMigrationError("result_matrix_nonfinite", "The .pdt matrix contains a non-finite value")
            lines = [{"index": index, "element": elements[index], "wavelength_nm": waves[index], "back": backs[index], "digits": digits[index]} for index in range(line_count)]
            kind = "peak_back"
        measure_time = cls._time(measure_raw)
        sample_rows: list[dict[str, Any]] = []
        if fmt == "dat":
            sample_rows = [{"expanded_index": index, "sample_index": index, "repeat_index": 1, "name": sample_names[index]} for index in range(sample_count)]
        else:
            expanded = 0
            for sample_index, repeat in enumerate(sample_reps):
                for repeat_index in range(1, repeat + 1):
                    sample_rows.append({"expanded_index": expanded, "sample_index": sample_index, "repeat_index": repeat_index, "name": sample_names[sample_index]})
                    expanded += 1
        method_target_id = None
        method_match_status = "not_present" if method_legacy_id is None else "orphan"
        issues: list[dict[str, Any]] = []
        if method_legacy_id is not None:
            method_target_id = LegacyMigrationService(source.get("database")) .resolve_method_id(method_legacy_id) if source.get("database") is not None else None
            if method_target_id is not None:
                method_match_status = "matched"
            else:
                issues.append({"level": "warning", "code": "result_method_orphan", "message": "No imported method matches the legacy method id; result retained read-only."})
        matrix_samples = cls._samples(values if fmt == "dat" else values, sample_count if fmt == "dat" else band_count, kind=kind)
        payload: dict[str, Any] = {
            "header": header,
            "format": fmt,
            "method_legacy_id": method_legacy_id,
            "method_target_id": method_target_id,
            "method_match_status": method_match_status,
            "measure_time": measure_time,
            "measure_time_raw": measure_raw,
            "sample_count": sample_count,
            "line_count": line_count,
            "band_count": band_count,
            "sample_names": sample_names,
            "sample_reps": sample_reps if fmt == "pdt" else [1] * sample_count,
            "sample_rows": sample_rows,
            "lines": lines,
            "exposure_segments": exp_segments,
            "matrix_kind": kind,
            "matrix_order": "line-major, expanded-sample-minor",
            "matrix_sha256": hashlib.sha256(matrix_blob).hexdigest(),
            "matrix_samples": matrix_samples,
            "endianness": "little",
            "encoding": "gb18030" if any(item == "gb18030" for item in encodings) else ("utf-8" if "utf-8" in encodings else "ascii"),
        }
        if method_target_id is not None:
            payload["method_match_status"] = "matched"
        return {"payload": payload, "matrix_blob": matrix_blob, "issues": issues}

    @staticmethod
    def _run_dict(row: Any, *, include_staging: bool = True, already_committed: bool = False) -> dict[str, Any]:
        result = {"id": row["id"], "fingerprint": row["fingerprint"], "format": row["format"], "status": row["status"], "source_file": json.loads(row["source_json"]), "parser": json.loads(row["parser_json"]), "report": json.loads(row["report_json"]), "error": {"code": row["error_code"], "message": row["error_message"]} if row["error_code"] else None, "created_at": row["created_at"], "updated_at": row["updated_at"], "committed_at": row["committed_at"], "already_committed": already_committed}
        if include_staging:
            result["staging"] = json.loads(row["staging_json"])
        return result

    def diagnostics(self) -> dict[str, Any]:
        return {"available": True, "code": "result_parser_ready", "message": "Strict little-endian .dat/.pdt parser ready", "formats": ["dat", "pdt"], "headers": {"dat": hex(DAT_HEAD), "pdt": [hex(PDT_HEAD), hex(EXP_SEG_PDT_HEAD)]}, "read_only": True, "parser_version": PARSER_VERSION, "short_strings": {"sample_name_bytes": NAME_WIDTH + 1, "element_bytes": ELEMENT_WIDTH + 1}}

    @staticmethod
    def _source_snapshot(path: Path) -> dict[str, Any]:
        return _snapshot(path)

    def stage(self, path_value: str, actor_user_id: int) -> dict[str, Any]:
        path = Path(path_value).expanduser()
        fmt = path.suffix.lower().lstrip(".")
        if fmt not in SUPPORTED_FORMATS:
            raise ResultMigrationError("result_source_extension_invalid", "Only .dat and .pdt files are accepted")
        source = self._source_snapshot(path)
        fingerprint = source["sha256"]
        with self.database.read() as db:
            existing = db.execute("SELECT * FROM result_migration_runs WHERE fingerprint=?", (fingerprint,)).fetchone()
            if existing is not None and existing["status"] == "committed":
                return self._run_dict(existing, already_committed=True)
        raw = path.read_bytes()
        parsed = self._parse(raw, fmt, {**source, "database": self.database})
        if self._source_snapshot(path) != source:
            raise ResultMigrationError("result_source_changed", "Source changed while it was being parsed")
        payload = parsed["payload"]
        issues = parsed["issues"]
        public_staging = {"records": [payload], "record_count": 1, "parser_version": PARSER_VERSION, "issues": issues}
        report = {"phase": "staged", "format": fmt, "counts": {"files": 1, "samples": payload["sample_count"], "lines": payload["line_count"], "bands": payload["band_count"], "matrix_values": payload["line_count"] * payload["band_count"]}, "checks": {"header_known": True, "metadata_complete": True, "repeat_counts_valid": True, "matrix_shape_valid": True, "matrix_values_finite": True, "source_unchanged": True, "hashes_verified": True, "read_only": True, "atomic_commit": None, "idempotency_guarded": True}, "issues": issues, "method_match_status": payload["method_match_status"], "sampled_values": payload["matrix_samples"], "atomic_scope": "single_source_file", "already_committed": False}
        now = utc_now(); run_id = existing["id"] if existing is not None else str(uuid.uuid4())
        try:
            with self.database.write() as db:
                db.execute("INSERT INTO result_migration_runs(id, fingerprint, format, status, source_json, parser_json, staging_json, report_json, created_by, created_at, updated_at) VALUES (?, ?, ?, 'staged', ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(fingerprint) DO UPDATE SET id=excluded.id, format=excluded.format, status='staged', source_json=excluded.source_json, parser_json=excluded.parser_json, staging_json=excluded.staging_json, report_json=excluded.report_json, error_code=NULL, error_message=NULL, created_by=excluded.created_by, updated_at=excluded.updated_at, committed_at=NULL", (run_id, fingerprint, fmt, _json(source), _json({"parser_version": PARSER_VERSION, "header": payload["header"], "endianness": "little", "encoding": payload["encoding"]}), _json(public_staging), _json(report), actor_user_id, now, now))
                db.execute("DELETE FROM result_migration_staging_records WHERE run_id=?", (run_id,))
                db.execute("INSERT INTO result_migration_staging_records(run_id, record_index, payload_json, matrix_blob, matrix_sha256) VALUES (?, 0, ?, ?, ?)", (run_id, _json(payload), parsed["matrix_blob"], payload["matrix_sha256"]))
                db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'result_migration.stage', 'result_migration', NULL, ?, ?)", (actor_user_id, _json({"run_id": run_id, "source_sha256": fingerprint, "format": fmt}), now))
                row = db.execute("SELECT * FROM result_migration_runs WHERE id=?", (run_id,)).fetchone()
                return self._run_dict(row)
        except ResultMigrationError:
            raise
        except Exception as exc:
            raise ResultMigrationError("result_stage_failed", "Failed to stage result file", details={"reason": str(exc)}) from exc

    def commit(self, run_id: str, actor_user_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM result_migration_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise ResultMigrationError("result_run_not_found", "Result migration run not found", status_code=404)
            if row["status"] == "committed":
                return self._run_dict(row, already_committed=True)
            source = json.loads(row["source_json"]); fingerprint = row["fingerprint"]
        current = self._source_snapshot(Path(source["path"]))
        if current != source:
            raise ResultMigrationError("result_source_changed_since_stage", "Source changed after staging", details={"before": source, "current": current})
        now = utc_now()
        try:
            with self.database.write() as db:
                if db.execute("SELECT 1 FROM result_matrices WHERE source_sha256=? LIMIT 1", (fingerprint,)).fetchone():
                    raise ResultMigrationError("result_source_already_imported", "Source SHA-256 is already committed", status_code=409)
                staging = db.execute("SELECT * FROM result_migration_staging_records WHERE run_id=? ORDER BY record_index", (run_id,)).fetchall()
                for item in staging:
                    db.execute("INSERT INTO result_matrices(import_run_id, source_sha256, record_index, format, payload_json, matrix_blob, matrix_sha256) VALUES (?, ?, ?, ?, ?, ?, ?)", (run_id, fingerprint, item["record_index"], row["format"], item["payload_json"], item["matrix_blob"], item["matrix_sha256"]))
                report = json.loads(row["report_json"])
                report.update({"phase": "committed", "checks": {**report["checks"], "atomic_commit": True}, "already_committed": False, "imported": {"result_matrices": len(staging)}})
                db.execute("UPDATE result_migration_runs SET status='committed', report_json=?, updated_at=?, committed_at=? WHERE id=?", (_json(report), now, now, run_id))
                db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'result_migration.commit', 'result_migration', NULL, ?, ?)", (actor_user_id, _json({"run_id": run_id, "source_sha256": fingerprint, "record_count": len(staging)}), now))
        except ResultMigrationError as exc:
            with self.database.write() as db:
                db.execute("UPDATE result_migration_runs SET status='failed', error_code=?, error_message=?, updated_at=? WHERE id=?", (exc.code, exc.message[:1000], utc_now(), run_id))
            raise
        except Exception as exc:
            with self.database.write() as db:
                db.execute("UPDATE result_migration_runs SET status='failed', error_code='result_commit_failed', error_message=?, updated_at=? WHERE id=?", (str(exc)[:1000], utc_now(), run_id))
            raise ResultMigrationError("result_commit_failed", "Result commit failed and was rolled back", details={"reason": str(exc)}) from exc
        return self.get(run_id)

    def get(self, run_id: str, *, already_committed: bool = False) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM result_migration_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise ResultMigrationError("result_run_not_found", "Result migration run not found", status_code=404)
            return self._run_dict(row, already_committed=already_committed)

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.database.read() as db:
            rows = db.execute("SELECT * FROM result_migration_runs ORDER BY created_at DESC LIMIT ?", (max(1, min(100, limit)),)).fetchall()
            return [self._run_dict(row, include_staging=False) for row in rows]
