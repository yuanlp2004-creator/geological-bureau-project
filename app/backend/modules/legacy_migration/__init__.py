"""旧方法迁移公共入口；保持现有谱图/结果迁移消费者的显式导出。"""

from .service import LegacyMigrationService
from .errors import LegacyMigrationError
from .sources import _sha256_bytes, _sha256_json, _source_snapshot
from .records import _number, _blob
from .configuration import _decode_ini, _ini_value, _typed_cfg, _typed_opt
from .reader import READER_FORMAT_VERSION
from .normalization import REQUIRED_TABLES, LINE_TYPES, PEAK_MODES, FIT_MODES
