"""CCD 几何、波长换算与参考点定位。"""

from __future__ import annotations

import json
import math
import sqlite3


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

