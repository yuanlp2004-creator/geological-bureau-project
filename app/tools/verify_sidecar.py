from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
SIDECAR = APP_ROOT / "src-tauri" / "binaries" / "geospectrum-backend-x86_64-pc-windows-msvc.exe"


def main() -> int:
    if not SIDECAR.exists():
        print(json.dumps({"status": "missing", "path": str(SIDECAR)}, ensure_ascii=False))
        return 1
    data_dir = APP_ROOT / "data" / "sidecar-check"
    shutil.rmtree(data_dir, ignore_errors=True)
    data_dir.mkdir(parents=True)
    env = os.environ.copy()
    env["SPECTRUM_DATA_DIR"] = str(data_dir)
    port = 8791
    process = subprocess.Popen(
        [str(SIDECAR), "--host", "127.0.0.1", "--port", str(port)],
        cwd=APP_ROOT,
        env=env,
        stdout=(data_dir / "stdout.log").open("w", encoding="utf-8"),
        stderr=(data_dir / "stderr.log").open("w", encoding="utf-8"),
    )
    health: dict | None = None
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and process.poll() is None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                    health = json.loads(response.read().decode("utf-8"))
                    break
            except Exception:
                time.sleep(0.1)
        running_before_stop = process.poll() is None
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    result = {
        "sidecar_bytes": SIDECAR.stat().st_size,
        "health_status": health.get("status") if health else None,
        "schema_version": health.get("schema_version") if health else None,
        "running_before_stop": running_before_stop,
        "clean_exit": process.returncode is not None,
        "process_returncode": process.returncode,
    }
    shutil.rmtree(data_dir, ignore_errors=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if health and health.get("status") == "ok" and running_before_stop and result["clean_exit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
