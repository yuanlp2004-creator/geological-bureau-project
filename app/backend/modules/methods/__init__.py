"""方法模块公共入口，保留既有消费者使用的显式导出。"""

from .errors import MethodDomainError
from .service import MethodService
from .values import DEFAULT_CONDITIONS, NAME_MAX_GB18030_BYTES, METHOD_NAME_INVALID, validate_method_name, _json, _condition_patch, _normalize_conditions
