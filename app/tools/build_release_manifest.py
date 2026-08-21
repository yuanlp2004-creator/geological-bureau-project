from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from tools.runtime_resources import RESOURCE_MANIFEST, load_runtime_resources


REPO_ROOT = APP_ROOT.parent
FORBIDDEN_PARTS = {".local", "tests", "__pycache__", ".pytest_cache", "node_modules", "target", "data"}
EXTERNAL_ACCEPTANCE_STEPS = {"S01", "S14", "S15"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def artifact(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(REPO_ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}


def package_version() -> str:
    package = json.loads((APP_ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    tauri = json.loads((APP_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))["version"]
    frontend = json.loads((APP_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["version"]
    cargo_text = (APP_ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    cargo = re.search(r'^version\s*=\s*"([^"]+)"', cargo_text, re.MULTILINE)
    backend_text = (APP_ROOT / "backend" / "app" / "__init__.py").read_text(encoding="utf-8")
    backend = re.search(r'__version__\s*=\s*"([^"]+)"', backend_text)
    versions = {"package": package, "tauri": tauri, "frontend": frontend, "cargo": cargo.group(1) if cargo else "", "backend": backend.group(1) if backend else ""}
    if len(set(versions.values())) != 1:
        raise RuntimeError(f"component version mismatch: {versions}")
    return package


def authenticode(path: Path) -> dict[str, str]:
    escaped_path = str(path).replace("'", "''")
    windows_root = Path(os.environ.get("WINDIR", r"C:\Windows"))
    windows_powershell = windows_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    environment = os.environ.copy()
    environment["PSModulePath"] = os.pathsep.join(
        [
            str(windows_root / "System32" / "WindowsPowerShell" / "v1.0" / "Modules"),
            str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WindowsPowerShell" / "Modules"),
        ]
    )
    command = [
        str(windows_powershell),
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
        f"$s=Get-AuthenticodeSignature -LiteralPath '{escaped_path}'; "
        "$subject=if ($null -eq $s.SignerCertificate) { '' } else { $s.SignerCertificate.Subject }; "
        "[pscustomobject]@{status=$s.Status.ToString();subject=$subject}|ConvertTo-Json -Compress",
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Authenticode inspection failed for {path}: {completed.stderr.strip()}")
    payload = json.loads(completed.stdout)
    return {"status": str(payload.get("status") or "Unknown"), "subject": str(payload.get("subject") or "")}


def acceptance_statuses() -> dict[str, str]:
    index = (REPO_ROOT / "docs" / "acceptance-reports" / "README.md").read_text(encoding="utf-8")
    statuses = {
        step: status
        for step, status in re.findall(
            r"^\|\s*(S\d{2})\s*\|\s*`?([a-z_]+)`?\s*\|",
            index,
            re.MULTILINE,
        )
    }
    required = {f"S{number:02d}" for number in range(21)}
    missing = sorted(required - statuses.keys())
    if missing:
        raise RuntimeError(f"acceptance index is missing software gates: {missing}")
    blocked = {
        step: statuses[step]
        for step in sorted(required)
        if statuses[step] != "passed"
        and not (step in EXTERNAL_ACCEPTANCE_STEPS and statuses[step] == "deferred_external")
    }
    if blocked:
        raise RuntimeError(f"software acceptance gates are not closed: {blocked}")
    return {step: statuses[step] for step in sorted(required)}


def validate_sidecar_build(sidecar: Path, sidecar_metadata: Path) -> dict[str, Any]:
    sidecar_build = json.loads(sidecar_metadata.read_text(encoding="utf-8"))
    if (
        sidecar_build.get("schema_version") != 20
        or sidecar_build.get("stage") != "S21"
        or sidecar_build.get("sha256") != sha256(sidecar)
        or sidecar_build.get("bytes") != sidecar.stat().st_size
    ):
        raise RuntimeError("sidecar build metadata does not match the S21 executable")

    resource_manifest = load_runtime_resources()
    expected_resources = [
        {
            "key": item["key"],
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in resource_manifest["resources"]
    ]
    if (
        sidecar_build.get("resource_schema_version") != resource_manifest["schema_version"]
        or sidecar_build.get("resource_manifest_sha256") != sha256(RESOURCE_MANIFEST)
        or sidecar_build.get("resources") != expected_resources
    ):
        raise RuntimeError("sidecar runtime resource metadata is missing or stale")
    return sidecar_build


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the auditable internal-test release manifest")
    parser.add_argument("--allow-missing-installer", action="store_true")
    args = parser.parse_args()
    version = package_version()
    tauri_config = json.loads((APP_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    webview_install_mode = tauri_config.get("bundle", {}).get("windows", {}).get("webviewInstallMode", {}).get("type")
    if webview_install_mode != "offlineInstaller":
        raise RuntimeError("S21 Windows package must embed the WebView2 offline installer")
    frontend_dist = APP_ROOT / "frontend" / "dist"
    sidecar = APP_ROOT / "src-tauri" / "binaries" / "geospectrum-backend-x86_64-pc-windows-msvc.exe"
    sidecar_metadata = sidecar.with_suffix(".build.json")
    generated_manifest = APP_ROOT / "manifest.generated.json"
    required = [sidecar, sidecar_metadata, generated_manifest, frontend_dist / "index.html"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing release input: {missing}")
    frontend_assets = sorted(path for path in frontend_dist.rglob("*") if path.is_file())
    validate_sidecar_build(sidecar, sidecar_metadata)
    input_paths = [sidecar, generated_manifest, *frontend_assets]
    contaminated = [str(path) for path in input_paths if FORBIDDEN_PARTS.intersection(path.relative_to(APP_ROOT).parts)]
    if contaminated:
        raise RuntimeError(f"forbidden release input: {contaminated}")
    installers = sorted((APP_ROOT / "src-tauri" / "target" / "release" / "bundle" / "nsis").glob("*.exe"))
    if not installers and not args.allow_missing_installer:
        raise FileNotFoundError("NSIS installer was not generated")
    installer_records = []
    for path in installers:
        record = artifact(path)
        record["authenticode"] = authenticode(path)
        installer_records.append(record)
    module_manifest = json.loads(generated_manifest.read_text(encoding="utf-8"))
    module_keys = [item["key"] for item in module_manifest["modules"]]
    if any(key.startswith("s21-") for key in module_keys):
        raise RuntimeError("test-only extension leaked into the formal module manifest")
    software_acceptance = acceptance_statuses()
    gates = {
        "clean_windows_10_vm": "pending_external",
        "clean_windows_11_vm": "pending_external",
        "code_signing_certificate": "missing_external",
        "real_turntable_hardware": "deferred_external",
        "real_mercury_lamp_hardware": "deferred_external",
    }
    payload = {
        "product": "GeoSpectrum",
        "version": version,
        "channel": "internal-test",
        "signed": False,
        "publishable_as_formal_release": False,
        "webview2_install_mode": webview_install_mode,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "plan_sha256": sha256(REPO_ROOT / "PLAN.md"),
        "module_manifest_sha256": sha256(generated_manifest),
        "module_keys": module_keys,
        "components": {
            "sidecar": artifact(sidecar),
            "frontend": [artifact(path) for path in frontend_assets],
            "module_manifest": artifact(generated_manifest),
        },
        "installers": installer_records,
        "release_gates": gates,
        "software_acceptance": software_acceptance,
        "software_acceptance_gate": "passed",
        "excluded": ["app/.local", "tests", "test output", "cache", "debug files", "node_modules", "src-tauri/target intermediates"],
    }
    output_dir = REPO_ROOT / "docs" / "releases" / version
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "internal-test-manifest.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
