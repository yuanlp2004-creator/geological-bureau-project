from __future__ import annotations
from typing import Any
from ..methods.units import unit_scale
from ..spectral_lines import canonical_lines


def _operational_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    lines = [
        line for line in canonical_lines(payload.get("lines"), payload.get("conditions", {})) if line.get("enabled")
    ]
    return (
        [line for line in lines if line.get("line_type") == "baseline"]
        + [line for line in lines if line.get("line_type") in {"positioning", "internal_standard"}]
        + [line for line in lines if line.get("line_type") == "analysis"]
    )


def _analysis_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        line
        for line in canonical_lines(payload.get("lines"), payload.get("conditions", {}))
        if line.get("enabled") and line.get("line_type") == "analysis"
    ]


def _base_curve_points(line: dict[str, Any], groups: list[dict[str, Any]],
                       stored_points: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for group in groups:
        if group["line_id"] == str(line.get("id")) and group.get("sample_kind") == "standard":
            by_name[str(group.get("sample_name") or "").strip().casefold()] = group
    points: list[dict[str, Any]] = []
    known = {str(point.get('name') or f'S{index + 1}').strip().casefold() for index, point in enumerate(line.get('standard_points') or [])}
    selected_count = sum(name in known and group['statistics'].get('mean') is not None and group['statistics'].get('effective_count', 0) > 0 for name, group in by_name.items())
    reuse = stored_points is not None and selected_count < 4
    stored = {point['name'].strip().casefold(): point for point in stored_points or []}
    for index, standard in enumerate(line.get("standard_points") or []):
        name = str(standard.get("name") or f"S{index + 1}").strip()
        group = by_name.get(name.casefold())
        mean = group["statistics"]["mean"] if group and not reuse else None
        old = stored.get(name.casefold()) if reuse else None
        if old and (not old.get('intensity_valid', True) or abs(float(old.get('standard_value', old.get('value', 0))) - float(standard['value'])) * unit_scale(line.get('unit', '')) >= 1e-7):
            old = None
        if old:
            mean = old.get('adjusted_intensity')
        points.append(
            {
                "point_index": index,
                "name": name,
                "standard_value": float(standard["value"]),
                "original_intensity": old.get('original_intensity', mean) if old else mean,
                "adjusted_intensity": mean,
                "original_active": bool(standard.get("active", True)),
                "active": bool(old.get('active', True)) if old else bool(standard.get("active", True)),
                "source": "stored_standard" if old else "current_measurement",
                "qc_group": {
                    "acquisition_task_id": group["acquisition_task_id"],
                    "effective_count": group["statistics"]["effective_count"],
                }
                if group
                else None,
            }
        )
    return points
