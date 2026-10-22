from __future__ import annotations
import json
from typing import Any


def _run_dict(row: Any, *, include_staging: bool = True) -> dict[str, Any]:
    result = {
        "id": row["id"],
        "fingerprint": row["fingerprint"],
        "format": row["format"],
        "status": row["status"],
        "source_file": json.loads(row["source_json"]),
        "reader": json.loads(row["reader_json"]),
        "report": json.loads(row["report_json"]),
        "error": {"code": row["error_code"], "message": row["error_message"]} if row["error_code"] else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "committed_at": row["committed_at"],
    }
    if include_staging:
        result["staging"] = json.loads(row["staging_json"])
    return result
