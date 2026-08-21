from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import BinaryIO

import uvicorn


def _data_dir() -> Path:
    configured = os.environ.get("SPECTRUM_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    return Path(local_app_data) / "cn.geospectrum.desktop" if local_app_data else Path.home() / ".geospectrum"


def _read_process_key(stream: BinaryIO | None = None) -> str:
    pipe = stream if stream is not None else sys.stdin.buffer
    raw = pipe.readline(129)
    if not raw.endswith(b"\n"):
        raise RuntimeError("process key pipe closed before a complete key was received")
    try:
        key = raw.strip().decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError("process key must be ASCII") from exc
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        raise RuntimeError("process key has an invalid format")
    return key


def main() -> None:
    parser = argparse.ArgumentParser(description="GeoSpectrum FastAPI sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    process_key = _read_process_key()
    from backend.app.upgrade import prepare_database_upgrade, prepare_legacy_data_directory

    data_dir = _data_dir()
    legacy_data_dir = os.environ.get("GEOSPECTRUM_LEGACY_DATA_DIR")
    if legacy_data_dir:
        prepare_legacy_data_directory(Path(legacy_data_dir), data_dir)
    prepare_database_upgrade(data_dir / "geospectrum.sqlite3")
    from backend.app import main as main_module

    previous_process_key = main_module.PROCESS_KEY
    main_module.PROCESS_KEY = process_key
    try:
        uvicorn.run(main_module.app, host=args.host, port=args.port, log_level="info")
    finally:
        main_module.PROCESS_KEY = previous_process_key


if __name__ == "__main__":
    main()
