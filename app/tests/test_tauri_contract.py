from __future__ import annotations

import json
import re
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]


def test_tauri_minimal_capability_and_lifecycle_contract() -> None:
    config = json.loads((APP_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    capabilities = json.loads((APP_ROOT / "src-tauri" / "capabilities" / "default.json").read_text(encoding="utf-8"))
    rust = (APP_ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    assert "binaries/geospectrum-backend" in config["bundle"]["externalBin"]
    assert config["plugins"]["shell"]["open"] is True
    assert "dialog:allow-open" in capabilities["permissions"]
    assert "shell:allow-execute" in capabilities["permissions"]
    assert capabilities["windows"] == ["main"]
    assert "tauri_plugin_single_instance::init" in rust
    assert re.findall(r'\.sidecar\s*\(\s*"([^"]+)"', rust) == ["geospectrum-backend"]
    assert "RunEvent::ExitRequested" in rust
    assert "WindowEvent::CloseRequested" in rust
    assert "tauri_plugin_dialog::init" in rust
    handlers = re.search(r"generate_handler!\s*\[([^]]+)\]", rust)
    assert handlers is not None
    assert {name.strip() for name in handlers.group(1).split(',') if name.strip()} == {
        'runtime_config', 'save_export_file', 'select_backup_directory',
        'select_legacy_directory', 'select_legacy_files', 'select_sample_file',
        'open_bluetooth_settings',
    }
    assert "ms-settings:bluetooth" in rust
