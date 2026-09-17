"""Observe debug-process survival; this is not a UI-ready or natural-exit check."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
import tempfile
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
TAURI_EXE = APP_ROOT / "src-tauri" / "target" / "debug" / "geospectrum.exe"


def main() -> int:
    if not TAURI_EXE.exists():
        print(json.dumps({"status": "missing", "path": str(TAURI_EXE)}, ensure_ascii=False))
        return 1
    output_root = APP_ROOT / ".local" / "test-runs"
    output_root.mkdir(parents=True, exist_ok=True)
    data_dir = Path(tempfile.mkdtemp(prefix="tauri-startup-", dir=output_root))
    env = os.environ.copy()
    env["SPECTRUM_DATA_DIR"] = str(data_dir)
    started = time.perf_counter()
    with (data_dir / "stdout.log").open("w", encoding="utf-8") as stdout, (data_dir / "stderr.log").open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            [str(TAURI_EXE)],
            cwd=APP_ROOT,
            env=env,
            stdout=stdout,
            stderr=stderr,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    while time.perf_counter() - started < 8 and process.poll() is None:
        time.sleep(0.1)
    observation_seconds = round(time.perf_counter() - started, 3)
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
        "observation_seconds": observation_seconds,
        "running_after_start_window": running,
        "test_process_terminated": process.returncode is not None,
        "natural_window_close_tested": False,
        "process_returncode": process.returncode,
        "log_dir_created": (data_dir / "logs").exists(),
        "stderr_path": str(data_dir / "stderr.log"),
    }
    success = running and result["test_process_terminated"]
    if success:
        shutil.rmtree(data_dir, ignore_errors=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
