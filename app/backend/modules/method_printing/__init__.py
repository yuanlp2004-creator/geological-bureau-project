"""保持既有调用入口；实现按职责归位。"""

from .service import MethodPrintService
from .document import _display, _weighted_length, _wrap, PAPER_MM, CONDITION_LABELS, LINE_TYPE_LABELS, PEAK_LABELS, FIT_LABELS, COORDINATE_LABELS, INTERNAL_LABELS
from .rendering import _register_font, FONT_NAME, FONT_BOLD
