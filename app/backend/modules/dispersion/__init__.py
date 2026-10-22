"""Public module entry; implementations have one owner per responsibility."""

from .codec import _pack_points, _unpack_points
from .values import DispersionState, DispersionError, _json, _finite, _TaskContext, _task_command
from .fitting import _gaussian_solve, _fit_polynomial, _evaluate, _calibration_position
from .service import DispersionService
