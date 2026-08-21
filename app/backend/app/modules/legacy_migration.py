from __future__ import annotations

import base64
import configparser
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import uuid
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from typing import Any

from ..db import Database, utc_now
from .methods import DEFAULT_CONDITIONS, MethodService, _json


READER_FORMAT_VERSION = 1
REQUIRED_TABLES = {"MTD_PRIM", "MTD_BURN", "MTD_WSTC", "LINES", "WSTC", "USER"}
LINE_TYPES = {0: "analysis", 1: "internal_standard", 2: "positioning"}
PEAK_MODES = {0: "max_single_point", 1: "gaussian"}
FIT_MODES = {0: "linear", 1: "quadratic", 2: "cubic", 3: "spline"}


class LegacyMigrationError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_json(value).encode("utf-8"))


def _number(value: Any, *, integer: bool = False, default: float | int = 0) -> float | int:
    if isinstance(value, dict) and value.get("kind") == "number":
        value = value.get("value")
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(str(value)) if integer else float(str(value))
    except (TypeError, ValueError):
        return default


def _blob(value: Any, *, field: str, expected_lengths: set[int] | None = None) -> tuple[bytes, dict[str, Any]]:
    if not isinstance(value, dict) or value.get("kind") != "blob":
        raise LegacyMigrationError("legacy_blob_missing", f"{field} 不是有效的旧版 BLOB")
    try:
        raw = base64.b64decode(str(value["base64"]), validate=True)
    except (KeyError, ValueError) as exc:
        raise LegacyMigrationError("legacy_blob_base64_invalid", f"{field} 的 BLOB 编码无效") from exc
    if int(value.get("byte_length", -1)) != len(raw) or value.get("sha256") != _sha256_bytes(raw):
        raise LegacyMigrationError("legacy_blob_hash_mismatch", f"{field} 的长度或 SHA-256 校验失败")
    if expected_lengths is not None and len(raw) not in expected_lengths:
        raise LegacyMigrationError(
            "legacy_blob_length_invalid",
            f"{field} 的 BLOB 长度不受支持",
            details={"actual": len(raw), "expected": sorted(expected_lengths)},
        )
    return raw, {"byte_length": len(raw), "sha256": _sha256_bytes(raw), "base64": value["base64"]}


def _source_snapshot(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        raw = path.read_bytes()
    except OSError as exc:
        raise LegacyMigrationError(
            "legacy_source_unreadable", f"无法读取旧版源文件：{path}", details={"reason": str(exc)}
        ) from exc
    return {
        "path": str(path.resolve()),
        "name": path.name,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _sha256_bytes(raw),
    }


def _decode_ini(path: Path) -> tuple[dict[str, dict[str, str]], str]:
    raw = path.read_bytes()
    encoding = "utf-8-sig"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        encoding = "gb18030"
        text = raw.decode(encoding)
    parser = configparser.RawConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise LegacyMigrationError(
            "legacy_ini_invalid", f"{path.name} 不是有效的 INI 配置", details={"reason": str(exc)}
        ) from exc
    return {section: dict(parser.items(section)) for section in parser.sections()}, encoding


def _ini_value(sections: dict[str, dict[str, str]], section: str, key: str, default: Any, cast: type) -> Any:
    value = sections.get(section, {}).get(key)
    if value is None:
        return default
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def _typed_cfg(sections: dict[str, dict[str, str]]) -> dict[str, Any]:
    return {
        "analyze": {
            "log_analysis": bool(_ini_value(sections, "ANALYZE", "LogAna", 0, int)),
            "look_band": bool(_ini_value(sections, "ANALYZE", "LookBand", 0, int)),
            "wait_time_ms": min(5000, max(0, _ini_value(sections, "ANALYZE", "WaitTime", 100, int))),
            "dark_round_time": _ini_value(sections, "ANALYZE", "RoundDarkTime", 8, int),
        },
        "safety": {
            "timer_delay_ms": _ini_value(sections, "SAFETIME", "TimerDelay", 25, int),
            "safe_total_ms": _ini_value(sections, "SAFETIME", "SafeTotal", 200, int),
            "safe_pre_ms": _ini_value(sections, "SAFETIME", "SafePre", 100, int),
        },
    }


def _typed_opt(sections: dict[str, dict[str, str]]) -> dict[str, Any]:
    indices = [
        max(0, int(item.strip()) - 1)
        for item in sections.get("CCD", {}).get("CcdIndexs", "1,2,3,5,6").split(",")
        if item.strip().isdigit()
    ]
    return {
        "communication": {
            "port": _ini_value(sections, "PComm", "Port", 1, int),
            "baud": _ini_value(sections, "PComm", "Baud", 115200, int),
        },
        "screen": {"width": _ini_value(sections, "SCREEN", "ScreenWidth", 0.0, float)},
        "ccd": {
            "mirror": bool(_ini_value(sections, "CCD", "Mirror", 0, int)),
            "frame_count": _ini_value(sections, "CCD", "FrameCount", 3, int),
            "ccds_per_frame": _ini_value(sections, "CCD", "CcdsPerFrame", 2, int),
            "points_per_ccd": _ini_value(sections, "CCD", "PointsPerCcd", 2048, int),
            "point_width_um": _ini_value(sections, "CCD", "PointWidth", 14.0, float),
            "ccd_indices": indices,
            "allow_gap_error": _ini_value(sections, "CCD", "AllowGapError", 150.0, float),
            "allow_ccd_drift_um": _ini_value(sections, "CCD", "AllowCcdDrift", 300.0, float),
        },
        "page_setup": {
            "font_size": _ini_value(sections, "PAGESETUP", "FontSize", 10, int),
            "elements_per_line": _ini_value(sections, "PAGESETUP", "ElePerLine", 15, int),
            "samples_per_page": _ini_value(sections, "PAGESETUP", "SampPerPage", 50, int),
            "time_mode": _ini_value(sections, "PAGESETUP", "TimeMode", 0, int),
        },
        "printer": {
            "paper_size": _ini_value(sections, "PRINTER", "PaperSize", 9, int),
            "orientation": _ini_value(sections, "PRINTER", "Orientation", 1, int),
        },
        "protection": {
            key: bool(_ini_value(sections, "PROTECT", old, 0, int))
            for key, old in {
                "log_commands": "LogCmd",
                "full_debug": "FullDebug",
                "print_unseen": "PrintUnSeen",
                "allow_auto_ignite": "AllowAutoIgnit",
            }.items()
        },
    }


class LegacyMigrationService:
    """Read-only SpecDirect MTD staging and atomic import service."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.methods = MethodService(database)

    def resolve_method_id(self, legacy_id: int) -> int | None:
        """Resolve a legacy method id through the migration service contract."""
        with self.database.read() as db:
            row = db.execute(
                "SELECT target_id FROM legacy_import_entities WHERE entity_type='method' AND legacy_key=? AND target_id IS NOT NULL ORDER BY id DESC LIMIT 1",
                (str(int(legacy_id)),),
            ).fetchone()
            return int(row["target_id"]) if row is not None else None

    @staticmethod
    def _reader_candidates() -> list[tuple[str, list[str]]]:
        app_root = Path(__file__).resolve().parents[3]
        configured = os.environ.get("GEOSPECTRUM_LEGACY_READER")
        candidates: list[tuple[str, list[str]]] = []
        if configured:
            candidates.append(("configured-win-x86", [configured]))
        reader_root = app_root / "tools" / "legacy-mdb-reader"
        packaged = reader_root / "GeoSpectrum.LegacyReader.exe"
        if packaged.exists():
            candidates.append(("dotnet-win-x86", [str(packaged)]))
        powershell = Path(os.environ.get("WINDIR", r"C:\Windows")) / "SysWOW64" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        packaged_script = files("backend.app.resources.legacy_reader").joinpath("read_access.ps1")
        script = Path(str(packaged_script))
        if powershell.exists() and script.exists():
            candidates.append(
                (
                    "windows-powershell-x86",
                    [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                )
            )
        return candidates

    def diagnostics(self) -> dict[str, Any]:
        attempts: list[dict[str, Any]] = []
        for name, command in self._reader_candidates():
            probe = [*command, "-Probe"] if name == "windows-powershell-x86" else [*command, "--probe"]
            try:
                result = subprocess.run(probe, capture_output=True, text=True, encoding="utf-8", timeout=10, check=False)
                payload = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                attempts.append({"reader": name, "available": False, "message": str(exc)})
                continue
            attempts.append({"reader": name, **payload})
            if result.returncode == 0 and payload.get("available"):
                return {
                    "available": True,
                    "code": "legacy_reader_ready",
                    "message": "32 位 Jet 4.0 旧方法读取器可用",
                    "reader": name,
                    "provider": payload.get("provider"),
                    "process_bits": payload.get("process_bits"),
                    "attempts": attempts,
                }
        return {
            "available": False,
            "code": "legacy_reader_unavailable",
            "message": "未检测到可用的 32 位 Jet 4.0 提供程序；常规启动和其他功能不受影响",
            "reader": None,
            "provider": "Microsoft.Jet.OLEDB.4.0",
            "process_bits": None,
            "attempts": attempts,
        }

    def _read_access(self, source: Path, before: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        diagnostic = self.diagnostics()
        if not diagnostic["available"]:
            raise LegacyMigrationError(
                "legacy_reader_unavailable", diagnostic["message"], status_code=503, details=diagnostic
            )
        candidate = next(item for item in self._reader_candidates() if item[0] == diagnostic["reader"])
        with tempfile.TemporaryDirectory(prefix="geospectrum-s06-") as temporary:
            copied = Path(temporary) / source.name
            shutil.copy2(source, copied)
            command = [*candidate[1], "-Path", str(copied)] if candidate[0] == "windows-powershell-x86" else [*candidate[1], "--path", str(copied)]
            try:
                result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise LegacyMigrationError(
                    "legacy_reader_failed", "旧方法读取器执行失败", status_code=503, details={"reason": str(exc)}
                ) from exc
            if result.returncode != 0:
                raise LegacyMigrationError(
                    "legacy_reader_failed",
                    "Jet 无法读取旧方法临时副本",
                    details={"exit_code": result.returncode, "stderr": result.stderr.strip()[-1000:]},
                )
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise LegacyMigrationError("legacy_reader_output_invalid", "旧方法读取器返回了无效 JSON") from exc
        after = _source_snapshot(source)
        if before != after:
            raise LegacyMigrationError(
                "legacy_source_changed", "读取期间旧方法源文件发生变化，已中止暂存", details={"before": before, "after": after}
            )
        if payload.get("format_version") != READER_FORMAT_VERSION:
            raise LegacyMigrationError("legacy_reader_version_invalid", "旧方法读取器输出版本不兼容")
        return payload, diagnostic

    @staticmethod
    def _standard_blob(value: Any, field: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        raw, evidence = _blob(value, field=field, expected_lengths={224, 700})
        record_count = len(raw) // 14
        parsed: list[dict[str, Any]] = []
        for index in range(record_count):
            content, raw_black, current_black, valid, active = struct.unpack_from("<fffBB", raw, index * 14)
            if not all(math.isfinite(item) for item in (content, raw_black, current_black)):
                raise LegacyMigrationError("legacy_standard_nonfinite", f"{field} 包含非有限浮点数")
            if valid:
                parsed.append(
                    {
                        "index": index,
                        "content": content,
                        "raw_black": raw_black,
                        "current_black": current_black,
                        "valid": bool(valid),
                        "active": bool(active),
                    }
                )
        evidence.update({"record_size": 14, "record_count": record_count, "valid_count": len(parsed), "records": parsed})
        return [
            {"name": f"S{item['index'] + 1}", "value": item["content"], "active": item["active"]}
            for item in parsed
        ], evidence

    @staticmethod
    def _wstc(row: dict[str, Any], *, field: str) -> dict[str, Any]:
        count = int(_number(row.get("CcdCount"), integer=True, default=0))
        gaps_raw, gaps_evidence = _blob(row.get("CcdGapPoints"), field=f"{field}.CcdGapPoints")
        indices_raw, indices_evidence = _blob(row.get("CcdIndexs"), field=f"{field}.CcdIndexs")
        coefficients_raw, coefficients_evidence = _blob(row.get("WsCof"), field=f"{field}.WsCof")
        if len(gaps_raw) != count * 4 or len(indices_raw) != count:
            raise LegacyMigrationError("legacy_wstc_shape_invalid", f"{field} 的 CCD BLOB 与 CcdCount 不一致")
        expected_coefficients = int(_number(row.get("FrameCount"), integer=True)) * int(_number(row.get("CcdsPerFrame"), integer=True))
        if len(coefficients_raw) != expected_coefficients * 4:
            raise LegacyMigrationError("legacy_wstc_shape_invalid", f"{field} 的色散系数数量不一致")
        return {
            "legacy_id": int(_number(row.get("WsId"), integer=True, default=-1)),
            "name": str(row.get("WsName") or "未命名色散"),
            "modified_at": row.get("ModifyTime"),
            "frame_count": int(_number(row.get("FrameCount"), integer=True)),
            "ccds_per_frame": int(_number(row.get("CcdsPerFrame"), integer=True)),
            "points_per_ccd": int(_number(row.get("PointsPerCcd"), integer=True)),
            "point_width": float(_number(row.get("PointWidth"))),
            "gap_points": list(struct.unpack(f"<{count}f", gaps_raw)),
            "ccd_indices": list(indices_raw),
            "coefficients": list(struct.unpack(f"<{expected_coefficients}f", coefficients_raw)),
            "blob_evidence": {
                "CcdGapPoints": gaps_evidence,
                "CcdIndexs": indices_evidence,
                "WsCof": coefficients_evidence,
            },
        }

    def _normalize_access(
        self,
        access: dict[str, Any],
        cfg: dict[str, dict[str, str]],
        opt: dict[str, dict[str, str]],
        cfg_encoding: str,
        opt_encoding: str,
    ) -> dict[str, Any]:
        tables = access.get("tables")
        if not isinstance(tables, dict):
            raise LegacyMigrationError("legacy_tables_missing", "旧方法读取结果缺少表集合")
        missing = sorted(REQUIRED_TABLES.difference(tables))
        if missing:
            raise LegacyMigrationError("legacy_tables_missing", "旧方法库缺少必需表", details={"tables": missing})

        table_counts = {name: len(rows) if isinstance(rows, list) else -1 for name, rows in tables.items()}
        prim_rows = tables["MTD_PRIM"]
        burn_by_id = {int(_number(row.get("MtdId"), integer=True)): row for row in tables["MTD_BURN"]}
        method_wstc_by_id = {int(_number(row.get("MtdId"), integer=True)): row for row in tables["MTD_WSTC"]}
        lines_by_id: dict[int, list[dict[str, Any]]] = {}
        for row in tables["LINES"]:
            lines_by_id.setdefault(int(_number(row.get("MtdId"), integer=True)), []).append(row)

        dispersions = [self._wstc(row, field=f"WSTC[{index}]") for index, row in enumerate(tables["WSTC"])]
        dispersion_by_name = {item["name"]: item for item in dispersions}
        dispersion_names = set(dispersion_by_name)
        issues: list[dict[str, Any]] = []
        methods: list[dict[str, Any]] = []
        migrated_line_count = 0

        for method_index, primary in enumerate(prim_rows):
            legacy_id = int(_number(primary.get("MtdId"), integer=True))
            burn = burn_by_id.get(legacy_id)
            method_wstc = method_wstc_by_id.get(legacy_id)
            if burn is None or method_wstc is None:
                raise LegacyMigrationError(
                    "legacy_method_reference_missing", "方法、燃烧条件与色散条件无法一一配对", details={"mtd_id": legacy_id}
                )
            dispersion_name = str(method_wstc.get("WsName") or "")
            if dispersion_name not in dispersion_names:
                raise LegacyMigrationError(
                    "legacy_dispersion_reference_missing", "方法引用的色散曲线不在 WSTC 表中", details={"mtd_id": legacy_id, "name": dispersion_name}
                )
            paired_dispersion = dispersion_by_name[dispersion_name]
            scalar_pairs = {
                "FrameCount": "frame_count",
                "CcdsPerFrame": "ccds_per_frame",
                "PointsPerCcd": "points_per_ccd",
                "PointWidth": "point_width",
            }
            for legacy_field, normalized_field in scalar_pairs.items():
                if not math.isclose(
                    float(_number(method_wstc.get(legacy_field))),
                    float(paired_dispersion[normalized_field]),
                    rel_tol=0,
                    abs_tol=1e-6,
                ):
                    raise LegacyMigrationError(
                        "legacy_method_dispersion_mismatch",
                        "方法内嵌色散参数与 WSTC 曲线不一致",
                        details={"mtd_id": legacy_id, "field": legacy_field, "name": dispersion_name},
                    )
            for blob_field in ("CcdGapPoints", "CcdIndexs", "WsCof"):
                embedded = method_wstc.get(blob_field)
                if not isinstance(embedded, dict) or embedded.get("sha256") != paired_dispersion["blob_evidence"][blob_field]["sha256"]:
                    raise LegacyMigrationError(
                        "legacy_method_dispersion_blob_mismatch",
                        "方法内嵌色散 BLOB 与 WSTC 曲线不一致",
                        details={"mtd_id": legacy_id, "field": blob_field, "name": dispersion_name},
                    )
            raw_lines = sorted(lines_by_id.get(legacy_id, []), key=lambda row: int(_number(row.get("Order"), integer=True)))
            line_ids = [f"legacy-{legacy_id}-{index + 1}" for index in range(len(raw_lines))]
            wave_targets = [(float(_number(row.get("Wave"))), line_ids[index], int(_number(row.get("LineType"), integer=True))) for index, row in enumerate(raw_lines)]

            def reference_for(wave: float, allowed: set[int]) -> str | None:
                if math.isclose(wave, 0.0, abs_tol=1e-7):
                    return None
                candidates = [item for item in wave_targets if item[2] in allowed]
                target = min(candidates, key=lambda item: abs(item[0] - wave), default=None)
                return target[1] if target is not None and abs(target[0] - wave) <= 0.01 else None

            normalized_lines: list[dict[str, Any]] = []
            line_evidence: list[dict[str, Any]] = []
            for index, row in enumerate(raw_lines):
                line_type_value = int(_number(row.get("LineType"), integer=True, default=-1))
                if line_type_value not in LINE_TYPES:
                    raise LegacyMigrationError("legacy_line_type_invalid", "旧谱线类型无法识别", details={"mtd_id": legacy_id, "index": index})
                standard_points, standard_evidence = self._standard_blob(row.get("Stds"), f"LINES[{legacy_id}:{index}].Stds")
                line_type = LINE_TYPES[line_type_value]
                inter_wave = float(_number(row.get("InterWave")))
                align_wave = float(_number(row.get("AlignWave")))
                internal_reference = reference_for(inter_wave, {1})
                alignment_reference = reference_for(align_wave, {1, 2})
                if not math.isclose(inter_wave, 0.0, abs_tol=1e-7) and internal_reference is None:
                    raise LegacyMigrationError("legacy_line_reference_missing", "旧谱线内标引用无法配对", details={"mtd_id": legacy_id, "wave": inter_wave})
                if not math.isclose(align_wave, 0.0, abs_tol=1e-7) and alignment_reference is None:
                    raise LegacyMigrationError("legacy_line_reference_missing", "旧谱线定位引用无法配对", details={"mtd_id": legacy_id, "wave": align_wave})
                peak_mode = PEAK_MODES.get(int(_number(row.get("PeakMode"), integer=True)), "max_single_point")
                peak_width = int(_number(row.get("PeakWidth"), integer=True, default=1))
                if peak_mode == "max_single_point":
                    peak_width = 1
                line = {
                    "id": line_ids[index],
                    "order": index + 1,
                    "line_type": line_type,
                    "element": str(row.get("Ele") or "?").strip(),
                    "wavelength_nm": float(_number(row.get("Wave"))),
                    "actual_wavelength_nm": float(_number(row.get("RealWave"))),
                    "enabled": True,
                    "critical_band": False,
                    "priority": max(0, min(100, int(_number(row.get("PriLevel"), integer=True)))),
                    "background_line_id": None,
                    "alignment_line_id": alignment_reference,
                    "internal_standard_mode": "line" if line_type == "analysis" and internal_reference else "none",
                    "internal_standard_line_id": internal_reference if line_type == "analysis" else None,
                    "scan_width_points": int(_number(row.get("SeekWidth"), integer=True, default=9)),
                    "background_offset_points": int(_number(row.get("Back"), integer=True)),
                    "peak_mode": peak_mode,
                    "peak_width_points": peak_width,
                    "fit_mode": FIT_MODES.get(int(_number(row.get("FitMode"), integer=True)), "linear"),
                    "coordinate_type": "logarithmic" if int(_number(row.get("CoordType"), integer=True)) > 0 else "normal",
                    "unit": str(primary.get("MtdUnit") or "ug/g"),
                    "value_kind": "content",
                    "decimal_places": int(_number(row.get("Digit"), integer=True, default=2)),
                    "lower_peak": int(_number(row.get("LowPeak"), integer=True, default=300)),
                    "minimum_peak_ratio": float(_number(row.get("LowRatio"), default=1.5)),
                    "valid_range_min": 0.0,
                    "valid_range_max": 9_999_999.0,
                    "over_limit_tolerance_percent": 0.0,
                    "standard_points": standard_points if line_type == "analysis" else [],
                    "reference_baseline": False,
                }
                normalized_lines.append(line)
                line_evidence.append(
                    {
                        "legacy_order": int(_number(row.get("Order"), integer=True)),
                        "legacy_element": row.get("Ele"),
                        "legacy_inter_wave": inter_wave,
                        "legacy_align_wave": align_wave,
                        "normalized_id": line_ids[index],
                        "standards_blob": standard_evidence,
                    }
                )
            migrated_line_count += len(normalized_lines)
            frame_count = int(_number(burn.get("BurnCount"), integer=True, default=20))
            conditions = deepcopy(DEFAULT_CONDITIONS)
            conditions.update(
                {
                    "ccd_layout_id": None,
                    "dispersion_calibration_id": None,
                    "legacy_dispersion_name": dispersion_name,
                    "selected_ccds": list(_blob(method_wstc.get("CcdIndexs"), field=f"MTD_WSTC[{legacy_id}].CcdIndexs")[0]),
                    "reference_wavelength_nm": float(_number(primary.get("RefWave"))),
                    "actual_reference_wavelength_nm": float(_number(primary.get("RealRefWave"))),
                    "reference_width_points": int(_number(primary.get("RefWidth"), integer=True, default=21)),
                    "analysis_unit": str(primary.get("MtdUnit") or "ug/g"),
                    "calculation_profile": "legacy_2_0_2",
                    "pre_excitation_seconds": float(_number(burn.get("PreBurn"), default=3.0)),
                    "sampling_period_seconds": float(_number(burn.get("BurnCyc"), default=1.0)),
                    "frame_count": frame_count,
                    "dark_frame_count": int(_number(burn.get("DarkCount"), integer=True, default=8)),
                    "sample_repeats": int(_number(primary.get("RepOfSam"), integer=True, default=1)),
                    "standard_repeats": int(_number(primary.get("RepOfStd"), integer=True, default=3)),
                    "control_repeats": int(_number(primary.get("RepOfDiag"), integer=True, default=1)),
                    "standard_sample_name": str(primary.get("DefaultSamName") or ""),
                    "maximum_id_deviation": float(_number(primary.get("LimitIda"), default=5.0)),
                    "rsd_enabled": bool(primary.get("CheckRsd")),
                    "rsd_threshold": float(_number(primary.get("LimitRsd"), default=5.0)),
                    "angle_exposures": [{"angle_deg": 0.0, "storage_mode": "averaged", "start_frame": 1, "end_frame": frame_count}],
                    "storage_profile": "legacy_specdirect_202",
                }
            )
            issues.append(
                {
                    "level": "warning",
                    "code": "legacy_angle_exposure_synthesized",
                    "field": f"methods.{legacy_id}.conditions.angle_exposures",
                    "message": "旧方法没有当前模型的转角区间字段，已按完整采样帧范围生成单一区间",
                }
            )
            methods.append(
                {
                    "legacy_id": legacy_id,
                    "name": str(primary.get("MtdName") or f"旧方法 {legacy_id}"),
                    "description": str(primary.get("MtdMemo") or "从 SpecDirect 2.0.2 迁移"),
                    "modified_at": primary.get("ModifyTime"),
                    "conditions": conditions,
                    "lines": normalized_lines,
                    "evidence": {"primary": primary, "burn": burn, "method_wstc": method_wstc, "lines": line_evidence},
                }
            )

        orphan_ids = sorted(set(burn_by_id).union(method_wstc_by_id).union(lines_by_id).difference(int(_number(row.get("MtdId"), integer=True)) for row in prim_rows))
        if orphan_ids:
            raise LegacyMigrationError("legacy_orphan_records", "旧方法表中存在无法配对的孤立记录", details={"mtd_ids": orphan_ids})

        issues.append(
            {
                "level": "warning",
                "code": "legacy_ccd_boundary_compatibility",
                "field": "configuration.opt.CCD.AllowCcdDrift",
                "message": "旧版 AllowCcdDrift 是漂移诊断阈值，不等同于当前谱线边界禁入宽度；原值完整保留在配置快照，迁移布局不附加边界禁入宽度",
            }
        )

        return {
            "format_version": 1,
            "counts": {
                "methods": len(methods),
                "spectral_lines": migrated_line_count,
                "dispersion_curves": len(dispersions),
                "users_ignored": table_counts.get("USER", 0),
            },
            "table_counts": table_counts,
            "methods": methods,
            "dispersions": dispersions,
            "configuration": {
                "cfg": {"encoding": cfg_encoding, "sections": cfg, "normalized": _typed_cfg(cfg)},
                "opt": {"encoding": opt_encoding, "sections": opt, "normalized": _typed_opt(opt)},
            },
            "issues": issues,
            "checks": {
                "required_tables_present": True,
                "method_burn_pairing": len(methods) == len(burn_by_id),
                "method_dispersion_pairing": len(methods) == len(method_wstc_by_id),
                "method_dispersion_blob_pairing": True,
                "line_references_resolved": True,
                "blob_hashes_verified": True,
            },
            "raw_table_counts": table_counts,
        }

    @staticmethod
    def _fingerprint(sources: dict[str, dict[str, Any]]) -> str:
        return _sha256_json({name: item["sha256"] for name, item in sorted(sources.items())})

    @staticmethod
    def _run_dict(row: Any, *, include_staging: bool = True) -> dict[str, Any]:
        result = {
            "id": row["id"],
            "fingerprint": row["fingerprint"],
            "status": row["status"],
            "source_files": json.loads(row["source_files_json"]),
            "reader": json.loads(row["reader_json"]),
            "report": json.loads(row["report_json"]),
            "error": {"code": row["error_code"], "message": row["error_message"]} if row["error_code"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "committed_at": row["committed_at"],
        }
        if include_staging:
            result["staging"] = json.loads(row["staging_json"])
        return result

    def stage(self, mtd_path: str, cfg_path: str, opt_path: str, actor_user_id: int) -> dict[str, Any]:
        paths = {"mtd": Path(mtd_path).expanduser(), "cfg": Path(cfg_path).expanduser(), "opt": Path(opt_path).expanduser()}
        expected = {"mtd": ".mtd", "cfg": ".cfg", "opt": ".opt"}
        for key, path in paths.items():
            if path.suffix.lower() != expected[key]:
                raise LegacyMigrationError("legacy_source_extension_invalid", f"{key.upper()} 文件扩展名必须是 {expected[key]}")
        sources = {name: _source_snapshot(path) for name, path in paths.items()}
        fingerprint = self._fingerprint(sources)
        with self.database.read() as db:
            existing = db.execute("SELECT * FROM legacy_migration_runs WHERE fingerprint=?", (fingerprint,)).fetchone()
            if existing is not None and existing["status"] == "committed":
                result = self._run_dict(existing)
                result["already_committed"] = True
                return result

        access, reader = self._read_access(paths["mtd"], sources["mtd"])
        cfg, cfg_encoding = _decode_ini(paths["cfg"])
        opt, opt_encoding = _decode_ini(paths["opt"])
        after_sources = {name: _source_snapshot(path) for name, path in paths.items()}
        if sources != after_sources:
            raise LegacyMigrationError("legacy_source_changed", "暂存期间旧版源文件发生变化，已中止")
        staging = self._normalize_access(access, cfg, opt, cfg_encoding, opt_encoding)
        staging["fingerprint"] = fingerprint
        staging["sources_unchanged"] = True
        report = {
            "phase": "staged",
            "counts": staging["counts"],
            "checks": {**staging["checks"], "sources_unchanged": True},
            "issues": staging["issues"],
            "atomic_scope": "source_set",
            "already_committed": False,
        }
        now = utc_now()
        run_id = existing["id"] if existing is not None else str(uuid.uuid4())
        with self.database.write() as db:
            db.execute(
                "INSERT INTO legacy_migration_runs(id, fingerprint, status, source_files_json, reader_json, staging_json, report_json, error_code, error_message, created_by, created_at, updated_at, committed_at) "
                "VALUES (?, ?, 'staged', ?, ?, ?, ?, NULL, NULL, ?, ?, ?, NULL) "
                "ON CONFLICT(fingerprint) DO UPDATE SET status='staged', source_files_json=excluded.source_files_json, reader_json=excluded.reader_json, staging_json=excluded.staging_json, report_json=excluded.report_json, error_code=NULL, error_message=NULL, created_by=excluded.created_by, updated_at=excluded.updated_at, committed_at=NULL",
                (run_id, fingerprint, _json(sources), _json(reader), _json(staging), _json(report), actor_user_id, now, now),
            )
            db.execute(
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'legacy_migration.stage', 'legacy_migration', NULL, ?, ?)",
                (actor_user_id, _json({"run_id": run_id, "fingerprint": fingerprint, "counts": staging["counts"]}), now),
            )
            row = db.execute("SELECT * FROM legacy_migration_runs WHERE fingerprint=?", (fingerprint,)).fetchone()
            return {**self._run_dict(row), "already_committed": False}

    @staticmethod
    def _unique_name(db: Any, table: str, desired: str, fingerprint: str) -> str:
        if db.execute(f"SELECT 1 FROM {table} WHERE name=? COLLATE NOCASE", (desired,)).fetchone() is None:
            return desired
        return f"{desired} · 旧版 {fingerprint[:6]}"

    @staticmethod
    def _record_entity(
        db: Any,
        *,
        run_id: str,
        source_sha256: str,
        entity_type: str,
        legacy_key: str,
        target_id: int | None,
        payload: Any,
        details: Any,
        now: str,
    ) -> None:
        db.execute(
            "INSERT INTO legacy_import_entities(run_id, source_sha256, entity_type, legacy_key, target_id, payload_sha256, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, source_sha256, entity_type, legacy_key, target_id, _sha256_json(payload), _json(details), now),
        )

    def _after_entity_insert(self, _entity_type: str, _legacy_key: str) -> None:
        """Test seam for proving transaction rollback; production intentionally does nothing."""

    def _assert_sources_current(self, sources: dict[str, dict[str, Any]]) -> None:
        for source in sources.values():
            current = _source_snapshot(Path(source["path"]))
            if current != source:
                raise LegacyMigrationError(
                    "legacy_source_changed_since_stage",
                    "源文件在暂存后发生变化，请重新暂存",
                    details={"before": source, "current": current},
                )

    def commit(self, run_id: str, actor_user_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM legacy_migration_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise LegacyMigrationError("legacy_run_not_found", "迁移任务不存在", status_code=404)
            if row["status"] == "committed":
                result = self._run_dict(row)
                result["already_committed"] = True
                return result
            staging = json.loads(row["staging_json"])
            sources = json.loads(row["source_files_json"])
            fingerprint = row["fingerprint"]
        self._assert_sources_current(sources)

        now = utc_now()
        mtd_hash = sources["mtd"]["sha256"]
        imported = {"methods": [], "spectral_lines": staging["counts"]["spectral_lines"], "dispersion_curves": [], "ccd_layouts": [], "configuration_profile_id": None}
        try:
            with self.database.write() as db:
                if db.execute("SELECT 1 FROM legacy_import_entities WHERE source_sha256=? LIMIT 1", (mtd_hash,)).fetchone():
                    raise LegacyMigrationError("legacy_source_already_imported", "该 MTD 内容已由其他迁移任务导入", status_code=409)

                layout_ids: dict[str, int] = {}
                calibration_ids: dict[str, int] = {}
                for dispersion in staging["dispersions"]:
                    geometry = {key: dispersion[key] for key in ("frame_count", "ccds_per_frame", "points_per_ccd", "point_width", "gap_points", "ccd_indices")}
                    geometry_key = _sha256_json(geometry)
                    if geometry_key not in layout_ids:
                        layout_name = self._unique_name(db, "ccd_layouts", f"旧版布局 · {dispersion['name']}", fingerprint)
                        cursor = db.execute(
                            "INSERT INTO ccd_layouts(name, frame_count, ccds_per_frame, points_per_ccd, point_width, gap_points_json, ccd_indices_json, wavelength_min, wavelength_max, allow_drift_um, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 160, 800, ?, ?)",
                            (layout_name, dispersion["frame_count"], dispersion["ccds_per_frame"], dispersion["points_per_ccd"], dispersion["point_width"], _json(dispersion["gap_points"]), _json(dispersion["ccd_indices"]), 0.0, now),
                        )
                        layout_id = int(cursor.lastrowid)
                        layout_ids[geometry_key] = layout_id
                        imported["ccd_layouts"].append(layout_id)
                        self._record_entity(db, run_id=run_id, source_sha256=mtd_hash, entity_type="ccd_layout", legacy_key=geometry_key, target_id=layout_id, payload=geometry, details={"name": layout_name}, now=now)
                        self._after_entity_insert("ccd_layout", geometry_key)
                    layout_id = layout_ids[geometry_key]
                    calibration_name = self._unique_name(db, "dispersion_calibrations", dispersion["name"], fingerprint)
                    cursor = db.execute(
                        "INSERT INTO dispersion_calibrations(name, ccd_layout_id, wavelength_min, wavelength_max, coefficients_json, enabled, created_at) VALUES (?, ?, 160, 800, ?, 1, ?)",
                        (calibration_name, layout_id, _json(dispersion["coefficients"]), now),
                    )
                    calibration_id = int(cursor.lastrowid)
                    calibration_ids[dispersion["name"]] = calibration_id
                    imported["dispersion_curves"].append(calibration_id)
                    self._record_entity(db, run_id=run_id, source_sha256=mtd_hash, entity_type="dispersion_calibration", legacy_key=str(dispersion["legacy_id"]), target_id=calibration_id, payload=dispersion, details={"name": calibration_name, "blob_evidence": dispersion["blob_evidence"]}, now=now)
                    self._after_entity_insert("dispersion_calibration", str(dispersion["legacy_id"]))

                for method in staging["methods"]:
                    desired_name = method["name"]
                    target_name = self._unique_name(db, "methods", desired_name, fingerprint)
                    conditions = deepcopy(method["conditions"])
                    dispersion_name = conditions.pop("legacy_dispersion_name")
                    calibration_id = calibration_ids[dispersion_name]
                    calibration_row = db.execute("SELECT ccd_layout_id FROM dispersion_calibrations WHERE id=?", (calibration_id,)).fetchone()
                    conditions["dispersion_calibration_id"] = calibration_id
                    conditions["ccd_layout_id"] = int(calibration_row[0])
                    payload = {
                        "conditions": conditions,
                        "lines": method["lines"],
                        "legacy_migration": {
                            "run_id": run_id,
                            "source_sha256": mtd_hash,
                            "legacy_method_id": method["legacy_id"],
                            "evidence_sha256": _sha256_json(method["evidence"]),
                        },
                    }
                    canonical, validation_errors = self.methods._validate_payload(payload, db)
                    if validation_errors:
                        raise LegacyMigrationError(
                            "legacy_normalized_method_invalid",
                            f"旧方法“{desired_name}”转换后未通过当前规则校验",
                            details={"legacy_id": method["legacy_id"], "validation_errors": validation_errors},
                        )
                    cursor = db.execute(
                        "INSERT INTO methods(name, description, work_type, status, current_version, created_at, updated_at) VALUES (?, ?, 'spectral', 'active', 1, ?, ?)",
                        (target_name, method["description"], now, now),
                    )
                    method_id = int(cursor.lastrowid)
                    db.execute(
                        "INSERT INTO method_versions(method_id, version, state, payload_json, validation_errors_json, created_at, created_by) VALUES (?, 1, 'published', ?, '[]', ?, ?)",
                        (method_id, _json(canonical), now, actor_user_id),
                    )
                    imported["methods"].append(method_id)
                    self._record_entity(db, run_id=run_id, source_sha256=mtd_hash, entity_type="method", legacy_key=str(method["legacy_id"]), target_id=method_id, payload=canonical, details={"legacy_name": desired_name, "target_name": target_name, "evidence": method["evidence"]}, now=now)
                    self._after_entity_insert("method", str(method["legacy_id"]))

                cursor = db.execute(
                    "INSERT INTO legacy_configuration_profiles(run_id, name, cfg_source_sha256, opt_source_sha256, cfg_json, opt_json, active, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                    (run_id, f"SpecDirect 2.0.2 · {fingerprint[:8]}", sources["cfg"]["sha256"], sources["opt"]["sha256"], _json(staging["configuration"]["cfg"]), _json(staging["configuration"]["opt"]), now),
                )
                imported["configuration_profile_id"] = int(cursor.lastrowid)
                self._record_entity(db, run_id=run_id, source_sha256=fingerprint, entity_type="configuration_profile", legacy_key="DIRECT.CFG+DIRECT.OPT", target_id=imported["configuration_profile_id"], payload=staging["configuration"], details={"active": False}, now=now)
                self._after_entity_insert("configuration_profile", "DIRECT.CFG+DIRECT.OPT")

                report = {
                    "phase": "committed",
                    "counts": staging["counts"],
                    "checks": {**staging["checks"], "sources_unchanged": True, "target_validation_passed": True, "atomic_commit": True, "idempotency_guarded": True},
                    "issues": staging["issues"],
                    "atomic_scope": "source_set",
                    "already_committed": False,
                    "imported": imported,
                }
                db.execute(
                    "UPDATE legacy_migration_runs SET status='committed', report_json=?, error_code=NULL, error_message=NULL, updated_at=?, committed_at=? WHERE id=?",
                    (_json(report), now, now, run_id),
                )
                db.execute(
                    "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'legacy_migration.commit', 'legacy_migration', NULL, ?, ?)",
                    (actor_user_id, _json({"run_id": run_id, "fingerprint": fingerprint, "counts": staging["counts"], "imported": imported}), now),
                )
        except Exception as exc:
            code = exc.code if isinstance(exc, LegacyMigrationError) else "legacy_commit_failed"
            message = exc.message if isinstance(exc, LegacyMigrationError) else str(exc)
            with self.database.write() as db:
                db.execute(
                    "UPDATE legacy_migration_runs SET status='failed', error_code=?, error_message=?, updated_at=? WHERE id=?",
                    (code, message[:1000], utc_now(), run_id),
                )
            if isinstance(exc, LegacyMigrationError):
                raise
            raise LegacyMigrationError("legacy_commit_failed", "旧方法提交失败，已完整回滚", details={"reason": message}) from exc

        return self.get(run_id, already_committed=False)

    def get(self, run_id: str, *, already_committed: bool | None = None) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM legacy_migration_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise LegacyMigrationError("legacy_run_not_found", "迁移任务不存在", status_code=404)
            result = self._run_dict(row)
            result["already_committed"] = bool(already_committed)
            return result

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.database.read() as db:
            rows = db.execute("SELECT * FROM legacy_migration_runs ORDER BY created_at DESC LIMIT ?", (max(1, min(100, limit)),)).fetchall()
            return [self._run_dict(row, include_staging=False) for row in rows]
