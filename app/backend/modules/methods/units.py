"""质量比单位换算；只在显式编辑草稿时使用，不改写既有快照。"""
from copy import deepcopy
from decimal import Decimal
from typing import Any
import math


# 一个单位相当于多少 ug/g；% 的数值 1 表示百分之一。
UNIT_POWERS = {"ug/g": 0, "mg/g": 3, "%": 4}


def unit_scale(unit: str) -> int:
    return 10 ** (UNIT_POWERS.get(unit, 0) if isinstance(unit, str) else 0)


def decimal_limit(unit: str) -> int:
    return 6 + (UNIT_POWERS.get(unit, 0) if isinstance(unit, str) else 0)


def convert_value(value: float, source: str, target: str) -> float:
    return float(Decimal(str(value)) * Decimal(unit_scale(source)) / Decimal(unit_scale(target)))


def convert_line_unit(line: dict[str, Any], target: str) -> dict[str, Any]:
    """已知质量比单位同步换算；未知单位保持原值和原标签。"""
    result = deepcopy(line)
    source = result.get("unit", "")
    if not isinstance(source, str) or not isinstance(target, str) or source not in UNIT_POWERS or target not in UNIT_POWERS or source == target:
        return result
    for field in ("valid_range_min", "valid_range_max"):
        value = result.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            result[field] = convert_value(value, source, target)
    for point in result.get("standard_points", []):
        value = point.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            point["value"] = convert_value(value, source, target)
    digits = result.get("decimal_places", 2)
    if isinstance(digits, int) and not isinstance(digits, bool) and 0 <= digits <= decimal_limit(source):
        result["decimal_places"] = max(0, min(decimal_limit(target), digits + UNIT_POWERS[target] - UNIT_POWERS[source]))
    result["unit"] = target
    return result
