"""Public analysis service and algorithms; implementation is organized by responsibility."""

from .errors import AnalysisError
from .service import AnalysisService
from .algorithms import repeat_statistics, fit_curve, evaluate_curve, legacy_gaussian

__all__ = ['AnalysisError', 'AnalysisService', 'repeat_statistics', 'fit_curve', 'evaluate_curve', 'legacy_gaussian']
