from __future__ import annotations
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from ..legacy_migration import LegacyMigrationError
from ..legacy_migration.reader import LegacyAccessReader


class SpectrumAccessReader:
    def read(self, source: Path, before: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        legacy = LegacyAccessReader()
        diagnostic = legacy.diagnostics()
        if not diagnostic["available"]:
            raise LegacyMigrationError(
                "legacy_reader_unavailable", diagnostic["message"], status_code=503, details=diagnostic
            )
        candidate = legacy.streaming_command()
        if candidate is None:
            raise LegacyMigrationError(
                "spectrum_streaming_reader_unavailable",
                "未找到支持分块 BLOB 输出的 32 位 Jet 读取器",
                status_code=503,
                details=diagnostic,
            )

        bundle = Path(tempfile.mkdtemp(prefix="geospectrum-s08-"))
        copied = bundle / source.name
        output = bundle / "reader-output"
        output.mkdir()
        timeout_seconds = max(120, min(540, int(before["size"] / (1024 * 1024) * 1.5) + 120))
        try:
            shutil.copy2(source, copied)
            command = [*candidate[1], "-Path", str(copied), "-OutputDirectory", str(output)]
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", timeout=timeout_seconds, check=False
            )
            if result.returncode != 0:
                raise LegacyMigrationError(
                    "legacy_reader_failed",
                    "Jet 无法分块读取旧谱文件临时副本",
                    details={"exit_code": result.returncode, "stderr": result.stderr.strip()[-1000:]},
                )
            try:
                manifest = json.loads(result.stdout.strip().splitlines()[-1])
            except (IndexError, json.JSONDecodeError) as exc:
                raise LegacyMigrationError("legacy_reader_output_invalid", "旧谱读取器返回了无效 JSON") from exc
            if manifest.get("format_version") != 2:
                raise LegacyMigrationError("legacy_reader_version_invalid", "旧谱分块读取器输出版本不兼容")

            tables: dict[str, list[dict[str, Any]]] = {}
            rows_path = (output / str(manifest.get("rows_file", ""))).resolve()
            if output.resolve() not in rows_path.parents or not rows_path.is_file():
                raise LegacyMigrationError("legacy_reader_output_invalid", "旧谱分块读取器缺少行清单")
            with rows_path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise LegacyMigrationError(
                            "legacy_reader_output_invalid", "旧谱分块读取器行清单无效", details={"line": line_number}
                        ) from exc
                    table = str(record.get("table", ""))
                    values = record.get("values")
                    if not table or not isinstance(values, dict):
                        raise LegacyMigrationError(
                            "legacy_reader_output_invalid",
                            "旧谱分块读取器行清单字段无效",
                            details={"line": line_number},
                        )
                    for value in values.values():
                        if isinstance(value, dict) and value.get("kind") == "blob_file":
                            blob_path = (output / str(value.get("file", ""))).resolve()
                            if output.resolve() not in blob_path.parents or not blob_path.is_file():
                                raise LegacyMigrationError(
                                    "legacy_reader_output_invalid",
                                    "旧谱分块读取器 BLOB 文件无效",
                                    details={"line": line_number},
                                )
                            value["path"] = str(blob_path)
                    tables.setdefault(table, []).append(values)
            payload = {
                "format_version": 2,
                "provider": manifest.get("provider"),
                "mode": manifest.get("mode"),
                "file": manifest.get("file"),
                "tables": tables,
                "_streaming_bundle": str(bundle),
            }
            return payload, {
                **diagnostic,
                "reader": candidate[0],
                "streaming_blobs": True,
                "timeout_seconds": timeout_seconds,
            }
        except Exception:
            shutil.rmtree(bundle, ignore_errors=True)
            raise
