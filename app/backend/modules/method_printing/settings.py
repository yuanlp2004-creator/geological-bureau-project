"""Validated application values; defaults and HTTP validation stay at the boundary."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PrintSettings:
    default_printer: str
    paper: str
    orientation: str
    margin_top_mm: float
    margin_right_mm: float
    margin_bottom_mm: float
    margin_left_mm: float
    layout: str
    font_size_pt: int
    copies: int
    duplex: str
    color: bool
    preview_before_print: bool
