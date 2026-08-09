from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import Database, utc_now
from .schemas import RuntimeEventCreate, SettingsPatch

DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
    "directories": {
        "data": "data",
        "methods": "methods",
        "samples": "samples",
        "exports": "exports",
        "backups": "backups",
    },
    "logging": {"level": "info", "max_bytes": 5242880, "retention_days": 30},
    "display": {"theme": "light", "density": "comfortable", "show_status_bar": True},
    "printing": {
        "default_printer": "geospectrum-pdf",
        "paper": "A4",
        "orientation": "portrait",
        "margin_top_mm": 12,
        "margin_right_mm": 12,
        "margin_bottom_mm": 12,
        "margin_left_mm": 12,
        "layout": "standard",
        "font_size_pt": 9,
        "copies": 1,
        "duplex": "none",
        "color": False,
        "preview_before_print": True,
    },
    "time": {"timezone": "Asia/Shanghai", "format": "YYYY-MM-DD HH:mm:ss"},
}

ALLOWED_SETTING_GROUPS = frozenset(DEFAULT_SETTINGS)
LOG_LEVEL_PRIORITY = {"debug": 10, "info": 20, "success": 20, "warning": 30, "error": 40}


class AppService:
    def __init__(self, database: Database, log_path: Path | None = None):
        self.database = database
        self.log_path = log_path or database.path.parent / "logs" / "runtime.jsonl"
        self._log_lock = threading.Lock()
        self.started_at = time.monotonic()

    def get_settings(self) -> dict[str, dict[str, Any]]:
        result = {group: values.copy() for group, values in DEFAULT_SETTINGS.items()}
        with self.database.read() as connection:
            rows = connection.execute("SELECT key, value_json FROM app_settings").fetchall()
        for row in rows:
            try:
                group, name = row["key"].split(".", 1)
                if group in result:
                    result[group][name] = json.loads(row["value_json"])
            except (ValueError, json.JSONDecodeError):
                continue
        return result

    def update_settings(self, patch: SettingsPatch, actor_user_id: int | None = None) -> dict[str, dict[str, Any]]:
        update_data = patch.model_dump(exclude_none=True)
        unknown = set(update_data).difference(ALLOWED_SETTING_GROUPS)
        if unknown:
            raise ValueError(f"unknown settings group: {sorted(unknown)[0]}")
        current = self.get_settings()
        before = {group: values.copy() for group, values in current.items()}
        now = utc_now()
        with self.database.write() as connection:
            for group, values in update_data.items():
                if not isinstance(values, dict):
                    raise ValueError(f"settings group must be an object: {group}")
                for name, value in values.items():
                    if name not in DEFAULT_SETTINGS[group]:
                        raise ValueError(f"unknown setting: {group}.{name}")
                    current[group][name] = value
                    connection.execute(
                        "INSERT INTO app_settings(key, value_json, updated_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                        (f"{group}.{name}", json.dumps(value, ensure_ascii=False), now),
                    )
            connection.execute(
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) "
                "VALUES (?, 'settings.update', 'settings', NULL, ?, ?)",
                (
                    actor_user_id,
                    json.dumps(
                        self._redact({
                            "changed_groups": sorted(update_data),
                            "before": {group: before[group] for group in update_data},
                            "after": {group: current[group] for group in update_data},
                        }),
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
        self.append_event(
            RuntimeEventCreate(category="action", severity="success", message="软件设置已保存")
        )
        return current

    def reset_settings(self, actor_user_id: int) -> dict[str, dict[str, Any]]:
        before = self.get_settings()
        now = utc_now()
        with self.database.write() as connection:
            connection.execute("DELETE FROM app_settings")
            connection.execute(
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) "
                "VALUES (?, 'settings.reset', 'settings', NULL, ?, ?)",
                (actor_user_id, json.dumps(self._redact({"before": before, "after": DEFAULT_SETTINGS}), ensure_ascii=False), now),
            )
        settings = self.get_settings()
        self.append_event(
            RuntimeEventCreate(category="action", severity="warning", message="软件设置已恢复默认值")
        )
        return settings

    @staticmethod
    def _redact(value: Any) -> Any:
        sensitive = re.compile(r"password|passwd|token|secret|authorization|api[_-]?key|private[_-]?key", re.I)
        if isinstance(value, dict):
            return {key: "[REDACTED]" if sensitive.search(str(key)) else AppService._redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [AppService._redact(item) for item in value]
        if isinstance(value, str):
            return re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[REDACTED]", value)
        return value

    def _append_file_log(self, event: dict[str, Any]) -> None:
        settings = self.get_settings()["logging"]
        configured_level = str(settings.get("level", "info")).lower()
        threshold = LOG_LEVEL_PRIORITY.get(configured_level, LOG_LEVEL_PRIORITY["info"])
        event_level = LOG_LEVEL_PRIORITY.get(str(event.get("severity", "info")).lower(), LOG_LEVEL_PRIORITY["info"])
        if event_level < threshold:
            return
        max_bytes = max(int(settings.get("max_bytes", 5 * 1024 * 1024)), 1024)
        retention_days = max(int(settings.get("retention_days", 30)), 1)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(self._redact(event), ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._log_lock:
            if self.log_path.exists() and self.log_path.stat().st_size + len(line.encode("utf-8")) > max_bytes:
                self._rotate_logs(retention_days)
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()

    def _rotate_logs(self, retention_days: int) -> None:
        rotated = self.log_path.with_suffix(self.log_path.suffix + ".1")
        if rotated.exists():
            rotated.unlink()
        if self.log_path.exists():
            self.log_path.replace(rotated)
        cutoff = time.time() - retention_days * 86400
        for candidate in self.log_path.parent.glob(f"{self.log_path.name}.*"):
            if candidate == rotated:
                continue
            try:
                if candidate.stat().st_mtime < cutoff:
                    candidate.unlink()
            except FileNotFoundError:
                pass

    def append_event(
        self,
        event: RuntimeEventCreate,
        *,
        actor_user_id: int | None = None,
        audit_action: str | None = None,
    ) -> dict[str, Any]:
        created_at = utc_now()
        details = json.dumps(event.details, ensure_ascii=False) if event.details is not None else None
        with self.database.write() as connection:
            cursor = connection.execute(
                "INSERT INTO runtime_events(category, severity, message, details_json, correlation_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event.category, event.severity, event.message, details, event.correlation_id, created_at),
            )
            event_id = cursor.lastrowid
            if audit_action:
                connection.execute(
                    "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) "
                    "VALUES (?, ?, 'runtime_event', ?, ?, ?)",
                    (
                        actor_user_id,
                        audit_action,
                        event_id,
                        json.dumps(self._redact({"category": event.category, "severity": event.severity, "message": event.message, "correlation_id": event.correlation_id}), ensure_ascii=False),
                        created_at,
                    ),
                )
        result = {
            "id": event_id,
            "category": event.category,
            "severity": event.severity,
            "message": event.message,
            "details": event.details,
            "correlation_id": event.correlation_id,
            "created_at": created_at,
        }
        self._append_file_log(result)
        return result

    def list_events(self, *, category: str | None = None, severity: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.database.read() as connection:
            rows = connection.execute(
                f"SELECT id, category, severity, message, details_json, correlation_id, created_at "
                f"FROM runtime_events {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        events = []
        for row in rows:
            try:
                details = json.loads(row["details_json"]) if row["details_json"] else None
            except json.JSONDecodeError:
                details = None
            events.append({**dict(row), "details": details})
            events[-1].pop("details_json", None)
        return events

    def clear_events(self, ids: Iterable[int] | None = None, *, actor_user_id: int | None = None) -> int:
        with self.database.write() as connection:
            if ids is None:
                cursor = connection.execute("DELETE FROM runtime_events")
            else:
                id_list = list(ids)
                if not id_list:
                    return 0
                placeholders = ",".join("?" for _ in id_list)
                cursor = connection.execute(f"DELETE FROM runtime_events WHERE id IN ({placeholders})", id_list)
            deleted = cursor.rowcount
            connection.execute(
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) "
                "VALUES (?, 'runtime_event.clear', 'runtime_event', NULL, ?, ?)",
                (actor_user_id, json.dumps({"deleted": deleted}, ensure_ascii=False), utc_now()),
            )
        return deleted

    def health(self) -> dict[str, Any]:
        with self.database.read() as connection:
            connection.execute("SELECT 1").fetchone()
            schema_version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
        return {
            "status": "ok",
            "app": "GeoSpectrum",
            "version": "0.1.0",
            "schema_version": schema_version,
            "database": "ok",
            "uptime_seconds": round(time.monotonic() - self.started_at, 3),
        }
