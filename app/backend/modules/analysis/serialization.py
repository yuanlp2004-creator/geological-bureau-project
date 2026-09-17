"""稳定 JSON 编码与内容哈希，保持既有快照格式。"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()
