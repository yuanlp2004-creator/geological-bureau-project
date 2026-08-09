from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.app.config import _default_data_dir


def test_default_data_dir_uses_local_app_data(monkeypatch) -> None:
    monkeypatch.delenv("SPECTRUM_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\\Users\\test\\AppData\\Local")
    assert _default_data_dir() == Path(r"C:\\Users\\test\\AppData\\Local") / "GeoSpectrum"


def test_default_data_dir_prefers_explicit_setting(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path / "configured"))
    monkeypatch.setenv("LOCALAPPDATA", r"C:\\ignored")
    assert _default_data_dir() == (tmp_path / "configured").resolve()


def test_default_data_dir_falls_back_to_home(monkeypatch) -> None:
    monkeypatch.delenv("SPECTRUM_DATA_DIR", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert _default_data_dir() == Path.home() / ".geospectrum"
