"""Time-limited, read-only sharing on a listener separate from the desktop API."""
from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Event, Lock, Thread

from ..schemas.system import ModuleDiagnostic


def diagnostic_snapshot(modules: list[ModuleDiagnostic], events: list[dict], checked_at: datetime) -> bytes:
    categories = {
        "system": "系统运行事件", "action": "设备或界面操作事件", "acquisition": "摄谱运行事件",
        "analysis": "分析运行事件", "import": "导入运行事件", "export": "导出运行事件",
    }
    severities = {"info", "success", "warning", "error", "debug"}
    sources = {"devices", "acquisition", "dispersion", "hardware", "mercury", "analysis"}
    signals = {"fault", "ccd_transfer", "connected", "disconnected", "timeout", "stopped"}
    logs = []
    for event in events:
        category, severity = event["category"], event["severity"]
        if category not in categories or severity not in severities:
            continue
        row = {"created_at": event["created_at"], "category": category, "severity": severity, "message": categories[category]}
        details = event.get("details")
        if isinstance(details, dict):
            for key, permitted in (("source", sources), ("event_type", signals)):
                value = details.get(key)
                if isinstance(value, str) and value in permitted:
                    row[key] = value
        logs.append(row)
    return json.dumps({
        "version": 1,
        "checked_at": checked_at.isoformat(),
        "modules": [
            {"key": module.key, "version": module.version, "enabled": module.enabled,
             "status": module.status, "self_test_http_status": module.http_status}
            for module in modules
        ],
        # Share only fixed text and structured classifications. Raw messages,
        # arbitrary details, actor identities and correlation IDs stay local.
        "logs": logs,
    }, ensure_ascii=False).encode("utf-8")


class SupportConflict(ValueError):
    pass


class SupportSession:
    def __init__(self, snapshot: tuple[datetime, bytes], minutes: int, operator_authorized: Callable[[], bool]):
        self.token = secrets.token_urlsafe(32)
        self.expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        self._deadline = time.monotonic() + minutes * 60
        self._stop = Event()
        self.snapshot = snapshot
        self._operator_authorized = operator_authorized
        session = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self) -> None:
                self.request.settimeout(1)
                super().setup()

            def log_message(self, *_args) -> None:
                pass

            def _reply(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path != "/api/v1/support/snapshot":
                    self._reply(404, b'{"code":"support_not_found"}')
                    return
                supplied = self.headers.get("Authorization", "")
                if self.headers.get("Origin") or (not supplied.isascii()) or not secrets.compare_digest(
                    supplied, f"Bearer {session.token}"
                ):
                    self._reply(401, b'{"code":"support_unauthorized"}')
                    return
                if not session.active():
                    self._reply(410, b'{"code":"support_closed"}')
                    return
                self._reply(200, session.snapshot[1])

            def do_POST(self) -> None:
                self._reply(405, b'{"code":"support_read_only"}')

            do_DELETE = do_PATCH = do_PUT = do_HEAD = do_OPTIONS = do_POST

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._server.timeout = 0.15
        self._thread = Thread(target=self._serve, name="support-diagnostics", daemon=True)

    @property
    def port(self) -> int:
        return self._server.server_port

    def active(self) -> bool:
        return not self._stop.is_set() and time.monotonic() < self._deadline and self._operator_authorized()

    def _serve(self) -> None:
        try:
            while self.active():
                self._server.handle_request()
        finally:
            self._server.server_close()

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread.ident is None:
            self._server.server_close()
        else:
            self._thread.join(timeout=1.5)


class SupportDiagnostics:
    def __init__(self):
        self._lock = Lock()
        self._session: SupportSession | None = None

    def active_session(self) -> SupportSession | None:
        with self._lock:
            if self._session and self._session.active():
                return self._session
            return None

    def status(self) -> dict:
        session = self.active_session()
        if session:
            return {"active": True, "port": session.port, "expires_at": session.expires_at,
                    "checked_at": session.snapshot[0]}
        return {"active": False, "port": None, "expires_at": None, "checked_at": None}

    def open(self, snapshot: tuple[datetime, bytes], minutes: int, operator_authorized: Callable[[], bool],
             audit: Callable[[], None]) -> dict:
        with self._lock:
            if self._session and self._session.active():
                raise SupportConflict("已有远程诊断会话，请先结束")
            if not operator_authorized():
                raise SupportConflict("当前操作员会话已结束，请重新登录")
            session = SupportSession(snapshot, minutes, operator_authorized)
            try:
                audit()
                session.start()
            except BaseException:
                session.close()
                raise
            self._session = session
            return {"active": True, "port": session.port, "expires_at": session.expires_at,
                    "checked_at": session.snapshot[0], "access_token": session.token}

    def refresh(self, expected: SupportSession, snapshot: tuple[datetime, bytes], audit: Callable[[], None]) -> dict:
        with self._lock:
            if self._session is not expected or not expected.active():
                raise SupportConflict("诊断会话已结束，请重新开启")
            audit()
            if snapshot[0] > expected.snapshot[0]:
                expected.snapshot = snapshot
            return {"active": True, "port": expected.port, "expires_at": expected.expires_at,
                    "checked_at": expected.snapshot[0]}

    def close(self) -> bool:
        with self._lock:
            if self._session is None:
                return False
            was_active = self._session.active()
            self._session.close()
            self._session = None
            return was_active
