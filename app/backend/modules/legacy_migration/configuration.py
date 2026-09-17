"""旧 CFG/OPT 编码、INI 字段和配置转换。"""

from __future__ import annotations

import configparser
from pathlib import Path
from typing import Any
from .errors import LegacyMigrationError


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
