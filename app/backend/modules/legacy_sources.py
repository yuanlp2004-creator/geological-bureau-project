"""Bounded, read-only discovery shared by the three legacy import entry points."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Any, Literal

from .legacy_migration import LegacyMigrationError

SourceKind = Literal["methods", "spectra", "results"]
MAX_ENTRIES = 10_000
MAX_CANDIDATES = 500
MAX_DEPTH = 6
SKIP_DIRECTORIES = {".git", ".local", "node_modules", "target", "__pycache__"}


def default_roots() -> list[Path]:
    # Frozen programs must use their executable location, never PyInstaller's temp folder.
    bases = [Path(sys.executable).parent] if getattr(sys, "frozen", False) else [Path(__file__).resolve().parents[3]]
    bases.append(Path.cwd())
    roots: list[Path] = []
    for base in bases:
        for parent in (base, base.parent):
            for relative in ("Spec2.02", "Spec Source/Bin", "Spec Source/Res", "SpecDirect"):
                candidate = parent / relative
                if candidate.is_dir():
                    roots.append(candidate)
        if (base / "DIRECT.MTD").is_file():
            roots.append(base)
    return list(dict.fromkeys(path.resolve() for path in roots))


def discover_sources(kind: SourceKind, root: str | None = None) -> dict[str, Any]:
    if root is not None:
        supplied = root.strip()
        if not supplied or "\x00" in supplied:
            raise LegacyMigrationError("legacy_directory_invalid", "请选择有效的旧版目录")
        try:
            directory = Path(supplied).expanduser().resolve(strict=True)
            if not directory.is_dir():
                raise OSError("不是目录")
        except (OSError, ValueError, RuntimeError) as exc:
            raise LegacyMigrationError("legacy_directory_invalid", "旧版目录不存在或无法访问") from exc
        roots = [directory]
    else:
        roots = default_roots()

    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[Path] = set()
    inspected = 0
    truncated = False
    suffixes = {"spectra": {".cdt", ".cmt", ".edt", ".wdt"}, "results": {".dat", ".pdt"}}
    pending = [(path, 0) for path in reversed(roots)]
    while pending and not truncated:
        directory, depth = pending.pop()
        if directory in seen:
            continue
        seen.add(directory)
        files: dict[str, tuple[Path, os.stat_result]] = {}
        children: list[Path] = []
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    inspected += 1
                    if inspected > MAX_ENTRIES:
                        truncated = True
                        break
                    info = entry.stat(follow_symlinks=False)
                    # Do not traverse symlinks, Windows junctions or cloud placeholders.
                    if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                        continue
                    path = Path(entry.path)
                    if stat.S_ISDIR(info.st_mode):
                        if entry.name.casefold() not in SKIP_DIRECTORIES:
                            if depth < MAX_DEPTH:
                                children.append(path)
                            else:
                                warnings.append(f"目录层级超过 {MAX_DEPTH} 层，请单独选择：{path}")
                    elif stat.S_ISREG(info.st_mode):
                        files[entry.name.casefold()] = (path, info)
        except OSError:
            warnings.append(f"无法完整读取目录：{directory}")
        if kind == "methods":
            if "direct.mtd" in files:
                paths = {key: str(files[name][0]) if name in files else "" for key, name in (
                    ("mtd_path", "direct.mtd"), ("cfg_path", "direct.cfg"), ("opt_path", "direct.opt"))}
                missing = [name.upper() for name in ("direct.cfg", "direct.opt") if name not in files]
                candidates.append({"path": paths["mtd_path"], "name": "DIRECT.MTD + CFG + OPT", "directory": str(directory),
                                   "paths": paths, "missing": missing, "size": sum(info.st_size for name, (_, info) in files.items() if name in {"direct.mtd", "direct.cfg", "direct.opt"})})
        else:
            for path, info in sorted(files.values(), key=lambda item: item[0].name.casefold()):
                if path.suffix.casefold() in suffixes[kind]:
                    candidates.append({"path": str(path), "name": path.name, "directory": str(directory),
                                       "size": info.st_size, "missing": [], "paths": {}})
                    if len(candidates) >= MAX_CANDIDATES:
                        truncated = True
                        break
        if len(candidates) >= MAX_CANDIDATES:
            truncated = True
        pending.extend((child, depth + 1) for child in reversed(sorted(children)))
    if truncated:
        warnings.append("扫描达到数量上限，结果不完整。请选择更具体的旧版数据目录继续检测。")
    return {"candidates": candidates, "roots": [str(path) for path in roots], "warnings": warnings[:30], "truncated": truncated}
