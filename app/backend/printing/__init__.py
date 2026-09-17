"""系统打印机枚举、虚拟打印机声明和系统调度。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


VIRTUAL_PDF_PRINTER = "geospectrum-pdf"


class SystemPrinters:

    @staticmethod
    def _system_printers() -> list[dict[str, Any]]:
        if os.name != "nt":
            return []
        try:
            import win32print  # type: ignore[import-not-found]

            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            rows = win32print.EnumPrinters(flags)
            default = win32print.GetDefaultPrinter()
            return [
                {
                    "name": row[2],
                    "display_name": row[2],
                    "virtual": False,
                    "system": True,
                    "default": row[2] == default,
                }
                for row in rows
                if row[2]
            ]
        except Exception:
            pass
        script = (
            "$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new();"
            "Get-CimInstance Win32_Printer | Select-Object Name,Default | ConvertTo-Json -Compress"
        )
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
                check=True,
            )
            payload = json.loads(completed.stdout.lstrip("\ufeff") or "[]")
            rows = payload if isinstance(payload, list) else [payload]
            return [
                {
                    "name": row["Name"],
                    "display_name": row["Name"],
                    "virtual": False,
                    "system": True,
                    "default": bool(row.get("Default")),
                }
                for row in rows
                if isinstance(row, dict) and row.get("Name")
            ]
        except Exception:
            return []

    def printers(self) -> list[dict[str, Any]]:
        return [
            {
                "name": VIRTUAL_PDF_PRINTER,
                "display_name": "GeoSpectrum PDF（虚拟打印机）",
                "virtual": True,
                "system": False,
                "default": True,
            },
            *self._system_printers(),
        ]

    @staticmethod
    def dispatch_pdf(pdf_path: Path, printer_name: str) -> None:
        if os.name != "nt":
            raise RuntimeError("当前系统不支持 Windows 打印调度")
        try:
            import win32api  # type: ignore[import-not-found]

            result = win32api.ShellExecute(0, "printto", str(pdf_path), f'"{printer_name}"', str(pdf_path.parent), 0)
            if result <= 32:
                raise RuntimeError(f"ShellExecute printto failed: {result}")
            return
        except ImportError as exc:
            raise RuntimeError("缺少 pywin32，无法调度系统打印机") from exc

