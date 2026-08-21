from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from tools.runtime_resources import RESOURCE_MANIFEST, RESOURCE_ROOT, load_runtime_resources, sha256


TARGET = APP_ROOT / "src-tauri" / "binaries" / "geospectrum-backend-x86_64-pc-windows-msvc.exe"
METADATA = TARGET.with_suffix(".build.json")


def main() -> int:
    resource_manifest = load_runtime_resources()
    resource_data: list[tuple[Path, str]] = [
        (RESOURCE_MANIFEST, "backend/app/resources"),
    ]
    resource_data.extend(
        (
            RESOURCE_ROOT / item["path"],
            f"backend/app/resources/{Path(item['path']).parent.as_posix()}",
        )
        for item in resource_manifest["resources"]
    )
    add_data_arguments = [
        argument
        for source, destination in resource_data
        for argument in ("--add-data", f"{source}{os.pathsep}{destination}")
    ]
    with tempfile.TemporaryDirectory(prefix="geospectrum-sidecar-") as temporary:
        output_root = Path(temporary)
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            "geospectrum-backend",
            "--distpath",
            str(output_root / "dist"),
            "--workpath",
            str(output_root / "work"),
            "--specpath",
            str(output_root),
            "--paths",
            str(APP_ROOT),
            "--collect-all",
            "uvicorn",
            *add_data_arguments,
            str(APP_ROOT / "backend" / "sidecar_entry.py"),
        ]
        completed = subprocess.run(command, cwd=APP_ROOT)
        if completed.returncode != 0:
            return completed.returncode
        source = output_root / "dist" / "geospectrum-backend.exe"
        if not source.exists():
            raise FileNotFoundError(source)
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, TARGET)
        resources = [
            {
                "key": item["key"],
                "path": item["path"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in resource_manifest["resources"]
        ]
        METADATA.write_text(
            json.dumps(
                {
                    "schema_version": 20,
                    "stage": "S21",
                    "sha256": sha256(TARGET),
                    "bytes": TARGET.stat().st_size,
                    "resource_schema_version": resource_manifest["schema_version"],
                    "resource_manifest_sha256": sha256(RESOURCE_MANIFEST),
                    "resources": resources,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    print(f"sidecar={TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
