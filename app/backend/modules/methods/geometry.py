"""CCD 几何、波长换算与参考点定位。"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import NamedTuple


class LinePosition(NamedTuple):
    ccd_index: int
    point: float
    within_margin: bool


class MethodLineLocator:
    """方法模块公开的定位快照；调用方不接触布局表或数据库行。"""

    def __init__(self, layout: sqlite3.Row, dispersion: sqlite3.Row, geometry: MethodGeometry):
        self._layout = layout
        self._dispersion = dispersion
        self._geometry = geometry

    @property
    def layout_id(self) -> int:
        return int(self._layout['id'])

    def accepts_legacy_layout(self, source: dict) -> bool:
        gaps = json.loads(self._layout['gap_points_json'])
        coefficients = json.loads(self._dispersion['coefficients_json'])
        indices = json.loads(self._layout['ccd_indices_json'])
        return (source.get('points_per_ccd') == self._layout['points_per_ccd']
                and set(source.get('ccd_indices', [])) <= set(indices)
                and len(gaps) == len(source.get('gap_points', []))
                and all(math.isclose(a,b,rel_tol=0,abs_tol=1e-4) for a,b in zip(gaps,source['gap_points']))
                and len(source.get('ws_cof', [])) >= 3 and len(coefficients) >= 3
                and all(math.isclose(a,b,rel_tol=0,abs_tol=1e-4) for a,b in zip(coefficients[:3],source['ws_cof'][:3])))

    def locate(self, wavelength_nm: float) -> LinePosition | None:
        """沿用方法的波长换算和 CCD 边界规则，越界返回 None。"""
        position = self._geometry._reference_position(wavelength_nm, self._layout, self._dispersion)
        return LinePosition(*position) if position is not None else None

    def wavelength_at(self, ccd_index: int, point: float) -> float:
        geometry = next(item for item in self._geometry._layout_geometry(self._layout) if item['ccd_index'] == ccd_index)
        coefficients = json.loads(self._dispersion['coefficients_json'])
        return self._geometry._step_to_wave(float(geometry['left_step']) + point, coefficients)


class MethodGeometry:

    @staticmethod
    def _layout_geometry(layout: sqlite3.Row) -> list[dict[str, float | int]]:
        indices = [int(value) for value in json.loads(layout["ccd_indices_json"] or "[]")]
        gaps = [float(value) for value in json.loads(layout["gap_points_json"] or "[]")]
        points = int(layout["points_per_ccd"])
        result: list[dict[str, float | int]] = []
        for ccd_index in indices:
            left = ccd_index * points + sum(gaps[:ccd_index])
            result.append(
                {
                    "ccd_index": ccd_index,
                    "left_step": left,
                    "right_step": left + points - 1,
                }
            )
        return result

    @staticmethod
    def _wave_to_step(wave: float, coefficients: list[float]) -> float:
        if len(coefficients) < 3:
            raise ValueError("dispersion coefficients are incomplete")
        a, b, c = coefficients[:3]
        return wave * (a * wave + b) + c

    @staticmethod
    def _step_to_wave(step: float, coefficients: list[float]) -> float:
        a, b, c = coefficients[:3]
        if math.isclose(a, 0.0):
            if math.isclose(b, 0.0):
                raise ValueError("dispersion coefficients are invalid")
            return (step - c) / b
        discriminant = b * b - 4.0 * a * (c - step)
        if discriminant < 0:
            raise ValueError("dispersion step is outside the calibrated domain")
        return (math.sqrt(discriminant) - b) / (2.0 * a)

    def _reference_position(
        self, wave: float, layout: sqlite3.Row, dispersion: sqlite3.Row
    ) -> tuple[int, float, bool] | None:
        coefficients = [float(value) for value in json.loads(dispersion["coefficients_json"] or "[]")]
        try:
            step = self._wave_to_step(wave, coefficients)
        except ValueError:
            return None
        margin = 2.0 * float(layout["allow_drift_um"]) / float(layout["point_width"])
        for item in self._layout_geometry(layout):
            left = float(item["left_step"])
            right = float(item["right_step"])
            if left <= step <= right:
                return int(item["ccd_index"]), step - left, left + margin <= step <= right - margin
        return None

