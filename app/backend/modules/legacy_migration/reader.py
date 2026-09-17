"""读取器探测与临时副本上的只读 Access 读取。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import Any
from .errors import LegacyMigrationError
from .sources import _source_snapshot


READER_FORMAT_VERSION = 1


class LegacyAccessReader:

    @staticmethod
    def _reader_candidates() -> list[tuple[str, list[str]]]:
        app_root = Path(__file__).resolve().parents[3]
        configured = os.environ.get("GEOSPECTRUM_LEGACY_READER")
        candidates: list[tuple[str, list[str]]] = []
        if configured:
            candidates.append(("configured-win-x86", [configured]))
        reader_root = app_root / "tools" / "legacy-mdb-reader"
        packaged = reader_root / "GeoSpectrum.LegacyReader.exe"
        if packaged.exists():
            candidates.append(("dotnet-win-x86", [str(packaged)]))
        powershell = Path(os.environ.get("WINDIR", r"C:\Windows")) / "SysWOW64" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        packaged_script = files("backend.resources.legacy_reader").joinpath("read_access.ps1")
        script = Path(str(packaged_script))
        if powershell.exists() and script.exists():
            candidates.append(
                (
                    "windows-powershell-x86",
                    [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                )
            )
        return candidates

    def diagnostics(self) -> dict[str, Any]:
        attempts: list[dict[str, Any]] = []
        for name, command in self._reader_candidates():
            probe = [*command, "-Probe"] if name == "windows-powershell-x86" else [*command, "--probe"]
            try:
                result = subprocess.run(probe, capture_output=True, text=True, encoding="utf-8", timeout=10, check=False)
                payload = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                attempts.append({"reader": name, "available": False, "message": str(exc)})
                continue
            attempts.append({"reader": name, **payload})
            if result.returncode == 0 and payload.get("available"):
                return {
                    "available": True,
                    "code": "legacy_reader_ready",
                    "message": "32 位 Jet 4.0 旧方法读取器可用",
                    "reader": name,
                    "provider": payload.get("provider"),
                    "process_bits": payload.get("process_bits"),
                    "attempts": attempts,
                }
        return {
            "available": False,
            "code": "legacy_reader_unavailable",
            "message": "未检测到可用的 32 位 Jet 4.0 提供程序；常规启动和其他功能不受影响",
            "reader": None,
            "provider": "Microsoft.Jet.OLEDB.4.0",
            "process_bits": None,
            "attempts": attempts,
        }

    def _read_access(self, source: Path, before: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        diagnostic = self.diagnostics()
        if not diagnostic["available"]:
            raise LegacyMigrationError(
                "legacy_reader_unavailable", diagnostic["message"], status_code=503, details=diagnostic
            )
        candidate = next(item for item in self._reader_candidates() if item[0] == diagnostic["reader"])
        with tempfile.TemporaryDirectory(prefix="geospectrum-s06-") as temporary:
            copied = Path(temporary) / source.name
            shutil.copy2(source, copied)
            command = [*candidate[1], "-Path", str(copied)] if candidate[0] == "windows-powershell-x86" else [*candidate[1], "--path", str(copied)]
            try:
                result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise LegacyMigrationError(
                    "legacy_reader_failed", "旧方法读取器执行失败", status_code=503, details={"reason": str(exc)}
                ) from exc
            if result.returncode != 0:
                raise LegacyMigrationError(
                    "legacy_reader_failed",
                    "Jet 无法读取旧方法临时副本",
                    details={"exit_code": result.returncode, "stderr": result.stderr.strip()[-1000:]},
                )
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise LegacyMigrationError("legacy_reader_output_invalid", "旧方法读取器返回了无效 JSON") from exc
        after = _source_snapshot(source)
        if before != after:
            raise LegacyMigrationError(
                "legacy_source_changed", "读取期间旧方法源文件发生变化，已中止暂存", details={"before": before, "after": after}
            )
        if payload.get("format_version") != READER_FORMAT_VERSION:
            raise LegacyMigrationError("legacy_reader_version_invalid", "旧方法读取器输出版本不兼容")
        return payload, diagnostic

