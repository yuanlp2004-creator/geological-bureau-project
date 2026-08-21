from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_data_dir() -> Path:
    configured = os.environ.get("SPECTRUM_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "cn.geospectrum.desktop"
    return Path.home() / ".geospectrum"


@dataclass(frozen=True)
class AppConfig:
    app_name: str = "GeoSpectrum"
    version: str = "0.1.0"
    api_version: str = "v1"
    data_dir: Path = _default_data_dir()

    @property
    def database_path(self) -> Path:
        return self.data_dir / "geospectrum.sqlite3"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def runtime_log_path(self) -> Path:
        return self.log_dir / "runtime.jsonl"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


config = AppConfig()
