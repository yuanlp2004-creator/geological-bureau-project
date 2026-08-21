from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
SIDECAR = APP_ROOT / "src-tauri" / "binaries" / "geospectrum-backend-x86_64-pc-windows-msvc.exe"
EXPECTED_SAMPLE_SHA256 = "EF130DE0BDE91CDB084333002207493380AD4B776FC2CE1C6960D19E0E164C0C"


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def sidecar_pids() -> set[int]:
    if os.name != "nt":
        return set()
    target = str(SIDECAR).replace("'", "''")
    name = SIDECAR.stem.replace("'", "''")
    command = (
        f"$target='{target}'; "
        f"Get-Process -Name '{name}' -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -eq $target } | ForEach-Object { $_.Id }"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return {int(line) for line in completed.stdout.splitlines() if line.strip().isdigit()}


def stop_process_tree(process: subprocess.Popen[str], preserve_pids: set[int]) -> set[int]:
    if process.poll() is None:
        tree_stopped = False
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            tree_stopped = completed.returncode == 0
        if not tree_stopped and process.poll() is None:
            process.terminate()
    if os.name == "nt":
        for _ in range(20):
            remaining = sidecar_pids() - preserve_pids
            if not remaining:
                break
            for pid in remaining:
                try:
                    os.kill(pid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
            time.sleep(0.1)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    return sidecar_pids() - preserve_pids


def request_json(
    port: int,
    process_key: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    headers = {"X-GeoSpectrum-Process-Key": process_key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            content = response.read()
            return json.loads(content.decode("utf-8")) if content else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc


def main() -> int:
    if not SIDECAR.exists():
        print(json.dumps({"status": "missing", "path": str(SIDECAR)}, ensure_ascii=False))
        return 1
    with tempfile.TemporaryDirectory(prefix="geospectrum-sidecar-check-", ignore_cleanup_errors=True) as temporary:
        data_dir = Path(temporary)
        env = os.environ.copy()
        env["SPECTRUM_DATA_DIR"] = str(data_dir)
        process_key = uuid.uuid4().hex
        port = free_port()
        preserve_pids = sidecar_pids()
        stdout_handle = (data_dir / "stdout.log").open("w", encoding="utf-8")
        stderr_handle = (data_dir / "stderr.log").open("w", encoding="utf-8")
        process = subprocess.Popen(
            [str(SIDECAR), "--host", "127.0.0.1", "--port", str(port)],
            cwd=APP_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
        )
        assert process.stdin is not None
        process.stdin.write(process_key + "\n")
        process.stdin.flush()
        process.stdin.close()
        health: dict | None = None
        business: dict[str, Any] | None = None
        error: str | None = None
        running_before_stop = False
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    health = request_json(port, process_key, "GET", "/health")
                    break
                except Exception:
                    time.sleep(0.1)
            if not health:
                raise RuntimeError("sidecar health endpoint did not become ready")

            username = f"sidecar-{uuid.uuid4().hex[:12]}"
            password = f"Acceptance-{uuid.uuid4().hex}"
            request_json(
                port,
                process_key,
                "POST",
                "/api/v1/auth/bootstrap",
                payload={"username": username, "password": password},
            )
            login = request_json(
                port,
                process_key,
                "POST",
                "/api/v1/auth/login",
                payload={"username": username, "password": password},
            )
            token = login["access_token"]
            profiles = request_json(port, process_key, "GET", "/api/v1/devices/profiles", token=token)
            if not profiles:
                raise RuntimeError("sidecar has no default simulator profile")
            connected = request_json(
                port,
                process_key,
                "POST",
                "/api/v1/devices/connect",
                token=token,
                payload={"profile_id": profiles[0]["id"]},
            )
            started = request_json(
                port,
                process_key,
                "POST",
                "/api/v1/devices/debug/start",
                token=token,
                payload={"sample": "280-288.acq", "seed": 19},
            )
            stepped = request_json(port, process_key, "POST", "/api/v1/devices/debug/step", token=token)
            stopped = request_json(port, process_key, "POST", "/api/v1/devices/debug/stop", token=token)
            legacy = request_json(
                port,
                process_key,
                "GET",
                "/api/v1/legacy-migration/diagnostics",
                token=token,
            )
            source_sha256 = str(started["event"]["details"]["sha256"]).upper()
            legacy_readers = [item.get("reader") for item in legacy.get("attempts", [])]
            business = {
                "profile_connected": connected["diagnostics"]["connected"],
                "start_ccd_count": len(started["event"]["ccds"]),
                "step_frame_index": stepped["event"]["frame_index"],
                "source_sha256": source_sha256,
                "stopped_state": stopped["event"]["state"],
                "legacy_reader_attempts": legacy_readers,
            }
            if not business["profile_connected"]:
                raise RuntimeError("sidecar simulator did not connect")
            if business["start_ccd_count"] == 0 or business["step_frame_index"] != 1:
                raise RuntimeError("sidecar simulator did not return CCD frame data")
            if source_sha256 != EXPECTED_SAMPLE_SHA256:
                raise RuntimeError("sidecar simulator sample hash does not match the packaged ACQ file")
            if "windows-powershell-x86" not in legacy_readers:
                raise RuntimeError("sidecar legacy migration diagnostics cannot see the packaged PowerShell reader")
            running_before_stop = process.poll() is None
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            remaining_sidecar_pids = stop_process_tree(process, preserve_pids)
            stdout_handle.close()
            stderr_handle.close()
    result = {
        "sidecar_bytes": SIDECAR.stat().st_size,
        "health_status": health.get("status") if health else None,
        "schema_version": health.get("schema_version") if health else None,
        "running_before_stop": running_before_stop,
        "clean_exit": process.returncode is not None,
        "process_returncode": process.returncode,
        "remaining_sidecar_pids": sorted(remaining_sidecar_pids),
        "business": business,
        "error": error,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if health and health.get("status") == "ok" and health.get("schema_version") == 20 and business and not error and running_before_stop and result["clean_exit"] and not remaining_sidecar_pids else 1


if __name__ == "__main__":
    raise SystemExit(main())
