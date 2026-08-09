from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def main() -> int:
    port = free_port()
    data_dir = APP_ROOT / "data" / "startup-check"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)
    env = os.environ.copy()
    env["SPECTRUM_DATA_DIR"] = str(data_dir)
    stdout_path = data_dir / "stdout.log"
    stderr_path = data_dir / "stderr.log"
    command = [str(PYTHON), "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(port)]
    started = time.perf_counter()
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=APP_ROOT, env=env, stdout=stdout, stderr=stderr)
        health = None
        while time.perf_counter() - started < 8:
            if process.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.4) as response:
                    health = json.loads(response.read().decode("utf-8"))
                    break
            except Exception:
                time.sleep(0.05)
        startup_seconds = round(time.perf_counter() - started, 3)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    clean_exit = process.returncode is not None
    result = {
        "port": port,
        "startup_seconds": startup_seconds,
        "health_status": health.get("status") if health else None,
        "schema_version": health.get("schema_version") if health else None,
        "clean_exit": clean_exit,
        "process_returncode": process.returncode,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    shutil.rmtree(data_dir, ignore_errors=True)
    return 0 if health and startup_seconds <= 8 and clean_exit else 1


if __name__ == "__main__":
    raise SystemExit(main())
