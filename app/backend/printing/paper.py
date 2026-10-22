"""Driver paper identifiers and physical sizes shared by renderers and Windows."""
from __future__ import annotations

import re

PAPER_MM = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "Letter": (215.9, 279.4)}
PAPER_IDS = {"A4": 9, "A3": 8, "Letter": 1}
PAPER_PATTERN = r"^(?:A4|A3|Letter|win:[1-9][0-9]{0,4}:[1-9][0-9]{1,4}:[1-9][0-9]{1,4})$"


def paper_mm(paper: str) -> tuple[float, float]:
    if paper in PAPER_MM:
        return PAPER_MM[paper]
    if not re.fullmatch(PAPER_PATTERN, paper):
        raise ValueError("纸张标识无效")
    _, _, width, height = paper.split(":")
    return int(width) / 10, int(height) / 10


def paper_code(identifier: int, width: int, height: int) -> str:
    for name, identifier2 in PAPER_IDS.items():
        if identifier2 == identifier and PAPER_MM[name] == (width / 10, height / 10):
            return name
    return f"win:{identifier}:{width}:{height}"


def paper_id(paper: str) -> int:
    paper_mm(paper)
    return PAPER_IDS[paper] if paper in PAPER_IDS else int(paper.split(":")[1])


def paper_css(paper: str, orientation: str) -> str:
    width, height = paper_mm(paper)
    if orientation == "landscape":
        width, height = height, width
    return f"{width:g}mm {height:g}mm"
