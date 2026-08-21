from __future__ import annotations

import json
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
    assert "tauri_plugin_single_instance::init" in rust
    assert ".sidecar(\"geospectrum-backend\")" in rust
    assert "child.kill()" in rust
    assert "RunEvent::ExitRequested" in rust
    assert "tauri_plugin_dialog::init()" in rust
    assert "async fn save_export_file(" in rust
    assert "validate_export(&file_name, &content_type, &bytes)?" in rust
    assert "blocking_save_file()" in rust
    assert "write_export_file(&path, &bytes)?" in rust
    assert "std::fs::write(path, bytes)" in rust
    assert "generate_handler![runtime_config, save_export_file]" in rust
    assert '"pdf" => "application/pdf"' in rust
    assert '"txt" | "log" | "sam" => "text/plain"' in rust
    assert 'std::env::var("GEOSPECTRUM_DEV_API_BASE")' in rust
    assert "#[cfg(not(debug_assertions))]\nfn development_api_base()" in rust
    assert "let Some(port) = port else" in rust
