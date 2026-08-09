from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
TAURI_EXE = APP_ROOT / "src-tauri" / "target" / "debug" / "geospectrum.exe"


def main() -> int:
    if not TAURI_EXE.exists():
        print(json.dumps({"status": "missing", "path": str(TAURI_EXE)}, ensure_ascii=False))
        return 1
    data_dir = APP_ROOT / "data" / "tauri-startup-check"
    shutil.rmtree(data_dir, ignore_errors=True)
    data_dir.mkdir(parents=True)
    env = os.environ.copy()
    env["SPECTRUM_DATA_DIR"] = str(data_dir)
    started = time.perf_counter()
    process = subprocess.Popen(
        [str(TAURI_EXE)],
        cwd=APP_ROOT,
        env=env,
        stdout=(data_dir / "stdout.log").open("w", encoding="utf-8"),
        stderr=(data_dir / "stderr.log").open("w", encoding="utf-8"),
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    while time.perf_counter() - started < 8 and process.poll() is None:
        time.sleep(0.1)
    startup_seconds = round(time.perf_counter() - started, 3)
    running = process.poll() is None
    if running:
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        except (AttributeError, OSError):
            process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    result = {
        "startup_seconds": startup_seconds,
        "running_after_start_window": running,
        "clean_exit": process.returncode is not None,
        "process_returncode": process.returncode,
        "log_dir_created": (data_dir / "logs").exists(),
        "stderr_path": str(data_dir / "stderr.log"),
    }
    success = running and result["clean_exit"] and startup_seconds <= 8
    if success:
        shutil.rmtree(data_dir, ignore_errors=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
