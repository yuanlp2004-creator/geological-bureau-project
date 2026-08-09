from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = APP_ROOT / "data" / "sidecar-build"
TARGET = APP_ROOT / "src-tauri" / "binaries" / "geospectrum-backend-x86_64-pc-windows-msvc.exe"


def main() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
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
        str(OUTPUT_ROOT / "dist"),
        "--workpath",
        str(OUTPUT_ROOT / "work"),
        "--specpath",
        str(OUTPUT_ROOT),
        "--paths",
        str(APP_ROOT),
        "--collect-all",
        "uvicorn",
        str(APP_ROOT / "backend" / "sidecar_entry.py"),
    ]
    completed = subprocess.run(command, cwd=APP_ROOT)
    if completed.returncode != 0:
        return completed.returncode
    source = OUTPUT_ROOT / "dist" / "geospectrum-backend.exe"
    if not source.exists():
        raise FileNotFoundError(source)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, TARGET)
    print(f"sidecar={TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
