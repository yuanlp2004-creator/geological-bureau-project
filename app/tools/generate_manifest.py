from __future__ import annotations

import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.app.modules.manifest import registered_manifests, validate_manifests  # noqa: E402


def main() -> int:
    manifests = registered_manifests()
    validate_manifests(manifests)
    output = APP_ROOT / "manifest.generated.json"
    output.write_text(
        json.dumps({"schema_version": 1, "modules": [manifest.to_dict() for manifest in manifests]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output} ({len(manifests)} modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
