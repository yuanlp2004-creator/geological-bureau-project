"""Project public business/device events into the existing operator message log."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import logging
import threading
import time
from typing import Any

from .schemas.system import RuntimeEventCreate
from .services import AppService


class RuntimeMessages:
    def __init__(self, service: AppService):
        self.service = service
        self._lock = threading.RLock()
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._task_heads: OrderedDict[tuple[str, int], int] = OrderedDict()
        self._loaded = False
        self._serial_events = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ccd-log')

    def close(self) -> None:
        self._serial_events.shutdown(wait=True)

    def _write_serial(self, *args: Any, **details: Any) -> None:
        # Persist outside the serial reader so a SQLite write cannot delay
        # reception of the next transfer. The single worker preserves order.
        try:
            self._serial_events.submit(self._write, *args, **details)
        except RuntimeError:
            logging.getLogger(__name__).exception('Unable to queue CCD communication record')

    def serial_notice(self, kind: str, message: str, severity: str, details: dict[str, Any], *,
                      source: str, task_id: int | None = None) -> None:
        self._write_serial(
            f"{source}:serial:{details['session_id']}:{details['tick_ns']}:{kind}",
            'acquisition', 'communication', severity, message,
            source=source, task_id=task_id, event_type=kind, transport='serial', **details,
        )

    def _write(self, key: str, category: str, channel: str, severity: str, message: str, **details: Any) -> None:
        # A log failure must not turn an already committed device command into a
        # failed response and invite the operator to repeat that command.
        try:
            with self._lock:
                if not self._loaded:
                    for event in reversed(self.service.list_events(limit=500)):
                        previous_details = event.get('details') or {}
                        previous = previous_details.get('source_key')
                        if previous:
                            self._seen[previous] = None
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
                self._seen[key] = None
                if message_id is not None:
                    self._task_heads[task_key] = message_id
                    self._task_heads.move_to_end(task_key)
                    while len(self._task_heads) > 1024:
                        self._task_heads.popitem(last=False)
                if len(self._seen) > 4096:
                    self._seen.popitem(last=False)
        except Exception:
            logging.getLogger(__name__).exception('Unable to record operator information')

    def device(self, result: dict[str, Any], *, source: str = 'devices') -> dict[str, Any]:
        event = result.get('event') or result.get('last_event')
        if not isinstance(event, dict) or not event.get('event_type'):
            return result
        kind = str(event['event_type'])
        frame = event.get('frame_index')
        key = f"{source}:device:{event.get('correlation_id')}:{event.get('occurred_at')}:{kind}:{frame}"
        timing = event.get('details') or {}
        if kind == 'frame' and 'receive_end_ms' in timing:
            if source == 'devices' and frame is not None:
                self.capture_frame(None, 'burn', frame, timing, source=source,
                                   key=key, heading=event.get('message') or '')
                return result
            # Acquisition services record the frame only after its storage
            # transaction commits, even when the serial reader runs off-page.
            if source in {'acquisition', 'dispersion'}:
                return result
        message = str(event.get('message') or {'frame': '收到 CCD 数据帧'}.get(kind, kind))
        if frame is not None:
            message += f' · 帧 {frame}'
        severity = 'error' if kind == 'fault' else ('debug' if kind == 'frame' else 'info')
        self._write(key, 'acquisition', 'communication', severity, message,
                    source=source, event_type=kind, state=event.get('state'), frame_index=frame)
        return result

    def capture_frame(self, task_id: int | None, phase: str, frame_index: int, timing: dict[str, Any],
                      repeat_index: int | None = None, *, source: str, key: str | None = None,
                      heading: str = '') -> None:
        receive_start = timing.get('receive_start_ms')
        receive_end = timing.get('receive_end_ms')
        if receive_start is None or receive_end is None:
            return
        stored = time.perf_counter_ns() // 1_000_000
        transport = timing.get('transport')
        receiving, received = ('接收空白', '空白收到') if phase == 'dark' else ('接收信号', '信号收到')
        prefix = '【模拟】' if transport == 'simulator' else ''
        if heading:
            prefix += f'{heading} · '
        writer = self._write_serial if transport == 'serial' else self._write
        byte_length = timing.get('byte_length')
        size = f' · {byte_length} 字节' if transport == 'serial' and byte_length is not None else ''
        writer(
            key or f'{source}:ccd:{task_id}:{repeat_index}:{phase}:{frame_index}:{receive_start}',
            'acquisition', 'communication', 'debug' if task_id is None else 'info',
            f'{prefix}{receiving} Freq: {receive_start} · {received} Freq: {receive_end}'
            f' 第 {frame_index + 1} 次 · 转存完成 Freq: {stored}{size}',
            source=source, task_id=task_id, event_type='ccd_transfer', phase=phase,
            frame_index=frame_index, repeat_index=repeat_index, transport=transport,
            receive_start_ms=receive_start, receive_end_ms=receive_end, stored_ms=stored, byte_length=byte_length,
        )

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
