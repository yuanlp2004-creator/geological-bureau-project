"""Pure legacy intensity and curve evaluation; only decoded values enter here."""

from dataclasses import dataclass
import math
import struct
from typing import Any
from ..analysis.algorithms import evaluate_curve
from ..analysis.errors import AnalysisError
from .errors import PostProcessingError


@dataclass(frozen=True)
class LegacyIntensity:
    source_sha256: str
    source_lines: list[dict[str, Any]]
    sample_rows: list[dict[str, Any]]
    matrix: list[list[tuple[float, float]]]
    band_count: int


def match_source_line(target: dict[str, Any], source_lines: list[dict[str, Any]]) -> int | None:
    element = str(target.get("element") or "")
    wavelength = float(target.get("wavelength_nm") or 0.0)
    matches = [
        index
        for index, line in enumerate(source_lines)
        if str(line.get("element") or "") == element
        and line.get("wavelength_nm") is not None
        and struct.pack('<f', float(line['wavelength_nm'])) == struct.pack('<f', wavelength)
        and (target.get('_exposure_interval') is None or target['_exposure_interval'] == line.get('_exposure_interval'))
    ]
    return matches[0] if len(matches) == 1 else None


def legacy_net(pair: tuple[float, float], source_line: dict[str, Any], *, background_ratio: bool = False,
               back_position: int | None = None) -> float:
    peak, background = (float(pair[0]), float(pair[1]))
    has_background = (int(source_line.get("back") or 0) if back_position is None else back_position) != 0
    if background_ratio:
        if not has_background or abs(background) < 1e-12:
            raise PostProcessingError("postprocessing_background_invalid", "背景内标需要非零背景强度")
        value = peak / background
    else:
        value = peak - background if has_background else peak
    return max(1e-5, value)


def recalculate_legacy(
    source: LegacyIntensity,
    method_lines: list[dict[str, Any]],
    evaluators: dict[str, dict[str, Any]],
    calculation_profile: str,
) -> dict[str, Any]:
    source_lines, matrix, band_count = source.source_lines, source.matrix, source.band_count
    by_id = {str(line.get("id")): line for line in method_lines}
    sample_rows = source.sample_rows
    diagnostics: list[dict[str, Any]] = []
    calculated: list[dict[str, Any]] = []
    for line in (item for item in method_lines if item.get("line_type") == "analysis"):
        line_id = str(line.get("id"))
        source_index = match_source_line(line, source_lines)
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
            internal_source_index = match_source_line({**internal, '_exposure_interval': line.get('_exposure_interval')}, source_lines) if internal is not None else None
            if internal_source_index is None:
                diagnostics.append({"line_id": line_id, "code": "internal_standard_line_missing"})
                continue
        for sample_index in range(band_count):
            try:
                signal = legacy_net(
                    matrix[source_index][sample_index],
                    source_lines[source_index],
                    background_ratio=mode == "background",
                )
                if internal_source_index is not None:
                    internal = legacy_net(
                        matrix[internal_source_index][sample_index], source_lines[internal_source_index],
                        back_position=int(source_lines[source_index].get('back') or 0)
                        if calculation_profile == 'legacy_2_0_2' else None,
                    )
                    signal = max(1e-5, signal / internal)
                value = evaluate_curve(evaluator["fit"], signal, evaluator["coordinate_type"])
            except (AnalysisError, PostProcessingError) as exc:
                code = (
                    exc.code
                    if isinstance(exc, (AnalysisError, PostProcessingError))
                    else "postprocessing_recalculation_failed"
                )
                diagnostics.append({"line_id": line_id, "sample_index": sample_index, "code": code})
                continue
            sample = (
                sample_rows[sample_index]
                if sample_index < len(sample_rows)
                else {"expanded_index": sample_index, "name": f"#{sample_index + 1}"}
            )
            calculated.append(
                {
                    "sample_index": int(sample.get("expanded_index", sample_index)),
                    "sample_name": str(sample.get("name") or f"#{sample_index + 1}"),
                    "repeat_index": int(sample.get("repeat_index", 1)),
                    "line_id": line_id,
                    "element": line.get("element"),
                    "wavelength_nm": float(line.get("wavelength_nm") or 0.0),
                    "quantitative_signal": signal,
                    "calculated_value": value,
                    "unit": line.get("unit", ""),
                    "curve_snapshot_id": evaluator["curve_snapshot_id"],
                    "calculation_profile": calculation_profile,
                }
            )
    if not calculated:
        raise PostProcessingError(
            "postprocessing_recalculation_no_lines",
            "没有可按所选方法和曲线重算的 PDT 谱线",
            details={"diagnostics": diagnostics},
        )
    return {
        "source_sha256": source.source_sha256,
        "status": "partial" if diagnostics else "recalculated",
        "line_count": len({item["line_id"] for item in calculated}),
        "sample_count": band_count,
        "lines": calculated,
        "diagnostics": diagnostics,
    }
