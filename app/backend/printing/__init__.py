"""Windows printer discovery and direct GDI output; no PDF file association."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any

# Recognized only when reading defaults saved by earlier versions.
VIRTUAL_PDF_PRINTER = "geospectrum-pdf"

class PrintCancelled(RuntimeError):
    pass

class SystemPrinters:
    @staticmethod
    def _system_printers() -> list[dict[str, Any]]:
        if os.name != "nt":
            return []
        import win32print
        try:
            default = win32print.GetDefaultPrinter()
        except win32print.error:
            default = None
        rows = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
        return [{"name": row[2], "display_name": row[2], "virtual": False, "system": True,
                 "default": row[2] == default} for row in rows if row[2]]

    def printers(self) -> list[dict[str, Any]]:
        return self._system_printers()

    def default_printer(self) -> str:
        rows = self.printers()
        return next((row['name'] for row in rows if row['default']), rows[0]['name'] if rows else 'system')

    @staticmethod
    def papers(printer_name: str) -> list[dict[str, Any]]:
        from .windows import printer_papers
        return printer_papers(printer_name)

    @staticmethod
    def check_connection(printer_name: str, settings: dict) -> dict:
        from .windows import printer_connection
        return printer_connection(printer_name, settings)

    @staticmethod
    def dispatch_pdf(pdf_path: Path, printer_name: str, settings: dict | None = None) -> dict:
        from .windows import print_pdf
        return print_pdf(pdf_path, printer_name, settings or {})
