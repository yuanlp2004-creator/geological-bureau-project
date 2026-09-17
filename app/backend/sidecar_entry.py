"""供 Tauri 桌面壳调用的冻结后端入口。

本入口建立单次启动的进程边界，在经过校验的副本上升级数据，
之后才导入并启动 FastAPI 组合根。
"""

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
    from backend.upgrade import prepare_database_upgrade, prepare_legacy_data_directory

    data_dir = _data_dir()
    legacy_data_dir = os.environ.get("GEOSPECTRUM_LEGACY_DATA_DIR")
    if legacy_data_dir:
        prepare_legacy_data_directory(Path(legacy_data_dir), data_dir)
    prepare_database_upgrade(data_dir / "geospectrum.sqlite3")
    # 推迟导入 ``backend.main``，直到磁盘数据可以安全打开；
    # 应用工厂只装配对象，lifespan 在启动时打开已经校验的数据库。
    from backend import main as main_module

    from backend.config import AppConfig
    from backend.runtime import Runtime

    runtime = Runtime(AppConfig(data_dir=data_dir), process_key=process_key)
    application = main_module.create_app(runtime=runtime)
    uvicorn.run(application, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
