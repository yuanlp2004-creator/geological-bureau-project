"""Project public business/device events into the existing operator message log."""
from __future__ import annotations

from collections import OrderedDict, deque
import logging
import threading
from typing import Any

from .schemas.system import RuntimeEventCreate
from .services import AppService


class RuntimeMessages:
    def __init__(self, service: AppService):
        self.service = service
        self._lock = threading.RLock()
        self._seen: set[str] = set()
        self._order: deque[str] = deque()
        self._task_heads: OrderedDict[tuple[str, int], int] = OrderedDict()
        self._loaded = False

    def _write(self, key: str, category: str, channel: str, severity: str, message: str, **details: Any) -> None:
        # A log failure must not turn an already committed device command into a
        # failed response and invite the operator to repeat that command.
        try:
            with self._lock:
                if not self._loaded:
                    for event in self.service.list_events(limit=500):
                        previous_details = event.get('details') or {}
                        previous = previous_details.get('source_key')
                        if previous:
                            self._seen.add(previous)
                            self._order.append(previous)
                        if previous_details.get('message_id') is not None:
                            task_key = (previous_details['source'], previous_details['task_id'])
                            self._task_heads[task_key] = max(self._task_heads.get(task_key, 0), previous_details['message_id'])
                    self._loaded = True
                task_key = (details.get('source'), details.get('task_id'))
                message_id = details.get('message_id')
                if message_id is not None and message_id <= self._task_heads.get(task_key, 0):
                    return
                if key in self._seen:
                    return
                self.service.append_event(RuntimeEventCreate(
                    category=category, severity=severity, message=message[:500],
                    details={'channel': channel, 'source_key': key, **details},
                ))
                self._seen.add(key)
                self._order.append(key)
                if message_id is not None:
                    self._task_heads[task_key] = message_id
                    self._task_heads.move_to_end(task_key)
                    while len(self._task_heads) > 1024:
                        self._task_heads.popitem(last=False)
                while len(self._order) > 4096:
                    self._seen.discard(self._order.popleft())
        except Exception:
            logging.getLogger(__name__).exception('Unable to record operator information')

    def device(self, result: dict[str, Any], *, source: str = 'devices') -> dict[str, Any]:
        event = result.get('event') or result.get('last_event')
        if not isinstance(event, dict) or not event.get('event_type'):
            return result
        kind = str(event['event_type'])
        frame = event.get('frame_index')
        message = str(event.get('message') or {'frame': '收到 CCD 数据帧'}.get(kind, kind))
        if frame is not None:
            message += f' · 帧 {frame}'
        key = f"{source}:device:{event.get('correlation_id')}:{event.get('occurred_at')}:{kind}:{frame}"
        severity = 'error' if kind == 'fault' else ('debug' if kind == 'frame' else 'info')
        self._write(key, 'acquisition', 'communication', severity, message,
                    source=source, event_type=kind, state=event.get('state'), frame_index=frame)
        return result

    def task(self, result: dict[str, Any], *, source: str, category: str = 'acquisition') -> dict[str, Any]:
        # Only consume the module's public response. Do not read its internal tables.
        for item in sorted(result.get('messages') or [], key=lambda row: row.get('id', 0)):
            if not item.get('message') or item.get('id') is None:
                continue
            level = item.get('level', 'info')
            severity = level if level in {'debug', 'info', 'success', 'warning', 'error'} else 'info'
            self._write(f"{source}:message:{item['id']}", category, 'general', severity,
                        str(item['message']), source=source, task_id=result.get('id'), message_id=item['id'], code=item.get('code'))
        if category == 'acquisition':
            self.device(result, source=source)
        return result
