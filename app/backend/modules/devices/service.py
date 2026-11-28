from __future__ import annotations
import json
import uuid
import threading
import time
import re
from contextlib import contextmanager
from functools import wraps
from typing import Any
from ...db import Database, utc_now
from .profiles import screen_conversion, validate_profile
from .simulator import AcqSimulatorAdapter
from .factory import create_device_adapter
from .motor_turn import motor_binding, prepare_motor_turn, save_motor_binding
from .ownership import DeviceOwnership
from .values import DeviceError, DeviceEvent
from .ports import bluetooth_connections as system_bluetooth_connections


def device_command(method):
    @wraps(method)
    def execute(self, *args, **kwargs):
        with self._control:
            return method(self, *args, **kwargs)
    return execute


class DeviceService:
    def __init__(self, database: Database, *, exit_gate=None, on_serial_notice=None, ownership=None):
        self.database = database
        self.adapter = AcqSimulatorAdapter()
        self._control = threading.RLock()
        self._turn_changed = threading.Condition(self._control)
        self._turn_cancel: threading.Event | None = None
        self._turn_stoppers = 0
        self._unconfirmed_motor = None
        self._angle: float | None = None
        self._settled_at: float | None = None
        self._exit_gate = exit_gate
        self._on_serial_notice = on_serial_notice
        self._ownership = ownership or DeviceOwnership(exit_gate)
        self._alignment = None
        self._connection_test = None

    def bluetooth_devices(self) -> dict[str, Any]:
        result = system_bluetooth_connections()
        with self.database.read() as db:
            hidden = {row['address'] for row in db.execute('SELECT address FROM device_bluetooth_hidden')}
        return {'devices': [item for item in result['devices'] if item['address'].upper() not in hidden]}

    @device_command
    def hide_bluetooth_device(self, address: str, actor_user_id: int) -> dict[str, bool]:
        address = address.upper()
        if not re.fullmatch(r'[0-9A-F]{12}', address):
            raise DeviceError('bluetooth_address_invalid', '请选择有效的蓝牙设备')
        if self.adapter.diagnostics()['connected']:
            raise DeviceError('device_busy', '请先停止并断开设备，再从列表删除', status_code=409)
        with self.database.read() as db:
            if db.execute('SELECT 1 FROM device_bluetooth_hidden WHERE address=?', (address,)).fetchone():
                return {'deleted': True}
        device = next((item for item in system_bluetooth_connections()['devices'] if item['address'].upper() == address), None)
        if device is None:
            raise DeviceError('bluetooth_device_not_found', '设备列表已变化，请刷新后重试', status_code=404)
        now = utc_now()
        with self.database.write() as db:
            db.execute('INSERT INTO device_bluetooth_hidden(address,name,hidden_at,actor_user_id) VALUES (?,?,?,?)',
                       (address, device['name'], now, actor_user_id))
            db.execute('''INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at)
                          VALUES (?, 'device.bluetooth.hide', 'bluetooth_device', ?, ?, ?)''',
                       (actor_user_id, address, json.dumps({'name': device['name']}, ensure_ascii=False), now))
        return {'deleted': True}


    @staticmethod
    def _serialize(row: Any) -> dict[str, Any]:
        result = dict(row)
        result["ccd_indices"] = json.loads(result.pop("ccd_indices_json"))
        result["mirror"] = bool(result["mirror"])
        result["enabled"] = bool(result["enabled"])
        result["screen_conversion"] = screen_conversion(result)
        return result

    def profiles(self) -> list[dict[str, Any]]:
        with self.database.read() as db:
            return [self._serialize(row) for row in db.execute("SELECT * FROM device_profiles ORDER BY id").fetchall()]

    def current_profile(self) -> dict[str, Any] | None:
        with self.database.read() as db:
            row = db.execute('SELECT p.* FROM device_runtime_state s JOIN device_profiles p '
                             'ON p.id=s.profile_id WHERE s.id=1 AND p.enabled=1').fetchone()
            return self._serialize(row) if row else None

    @device_command
    def select_profile(self, profile_id: int, actor_user_id: int) -> dict[str, Any]:
        profile = self.profile(profile_id)
        if self.adapter.diagnostics()['connected'] and self.adapter.profile.get('id') != profile_id:
            raise DeviceError('device_busy', '请先停止并断开当前设备，再切换设备档案', status_code=409)
        if not profile['enabled']:
            raise DeviceError('device_profile_disabled', '请先启用设备档案')
        with self.database.write() as db:
            db.execute('INSERT INTO device_runtime_state VALUES (1,?,?) ON CONFLICT(id) '
                       'DO UPDATE SET profile_id=excluded.profile_id, updated_at=excluded.updated_at',
                       (profile_id, utc_now()))
            db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) "
                       "VALUES (?, 'device.profile.select', 'device_profile', ?, '{}', ?)",
                       (actor_user_id, profile_id, utc_now()))
        return profile

    def profile(self, profile_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM device_profiles WHERE id=?", (profile_id,)).fetchone()
        if row is None:
            raise DeviceError(
                "device_profile_not_found",
                "Device profile was not found",
                details={"profile_id": profile_id},
                status_code=404,
            )
        return self._serialize(row)

    @device_command
    def select_port(self, transport: str, port: int | None, actor_user_id: int) -> dict[str, Any]:
        """Select a COM port directly; retain profiles as internal, compatible records."""
        if transport not in {'serial', 'simulator'} or (transport == 'serial' and (port is None or not 1 <= port <= 256)):
            raise DeviceError('device_port_invalid', '请选择有效的COM口或模拟器')
        profiles = self.profiles()
        current = self.current_profile()
        matches = [profile for profile in profiles if profile['enabled'] and profile['transport'] == transport
                   and (transport == 'simulator' or profile['port'] == port)]
        chosen = next((profile for profile in matches if current and profile['id'] == current['id']), None)
        chosen = chosen or next(iter(matches), None)
        if self.adapter.diagnostics()['connected'] and (not chosen or self.adapter.profile.get('id') != chosen['id']):
            raise DeviceError('device_busy', '请先停止并断开当前设备，再切换通讯口', status_code=409)
        if chosen is None:
            base = current or next((profile for profile in profiles if profile['enabled']), None)
            values = {key: value for key, value in (base or {}).items()
                      if key not in {'id', 'name', 'transport', 'port', 'enabled', 'created_at', 'updated_at', 'screen_conversion'}}
            name = f'串口 COM{port}' if transport == 'serial' else '模拟器'
            original_name = name
            suffix = 2
            while any(profile['name'] == name for profile in profiles):
                name = f'{original_name} ({suffix})'
                suffix += 1
            # A simulator may contain an arbitrary test baud; use the confirmed
            # legacy rate when first creating a real connection from it.
            if transport == 'serial' and (base is None or base['transport'] != 'serial'):
                values['baud_rate'] = 460800
            chosen = self.create_profile({**values, 'name': name, 'transport': transport,
                                          'port': port if transport == 'serial' else 3, 'enabled': True}, actor_user_id)
        return self.select_profile(chosen['id'], actor_user_id)

    def create_profile(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        normalized = validate_profile(payload)
        now = utc_now()
        try:
            with self.database.write() as db:
                cursor = db.execute(
                    (
                        "INSERT INTO device_profiles(name, transport, port, baud_rate, mirror, "
                        "frame_count, ccds_per_frame, points_per_ccd, ccd_indices_json, point_width_um, "
                        "protection_time_ms, screen_width_mm, screen_resolution_px, enabled, created_at, "
                        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    (
                        normalized["name"],
                        normalized["transport"],
                        normalized["port"],
                        normalized["baud_rate"],
                        int(normalized["mirror"]),
                        normalized["frame_count"],
                        normalized["ccds_per_frame"],
                        normalized["points_per_ccd"],
                        json.dumps(normalized["ccd_indices"], separators=(",", ":")),
                        normalized["point_width_um"],
                        normalized["protection_time_ms"],
                        normalized["screen_width_mm"],
                        normalized["screen_resolution_px"],
                        int(normalized["enabled"]),
                        now,
                        now,
                    ),
                )
                profile_id = int(cursor.lastrowid)
                db.execute(
                    (
                        "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, "
                        "details_json, created_at) VALUES (?, 'device_profile.create', 'device_profile', "
                        "?, ?, ?)"
                    ),
                    (actor_user_id, profile_id, json.dumps({"name": normalized["name"]}, ensure_ascii=False), now),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise DeviceError(
                    "device_profile_duplicate", "A device profile with this name already exists", status_code=409
                ) from exc
            raise
        return self.profile(profile_id)

    @device_command
    def update_profile(
        self, profile_id: int, payload: dict[str, Any], actor_user_id: int | None = None
    ) -> dict[str, Any]:
        current = self.profile(profile_id)
        if self.adapter.diagnostics()['connected'] and self.adapter.profile.get('id') == profile_id:
            raise DeviceError('device_busy', '请先停止并断开当前设备，再修改连接参数', status_code=409)
        merged = {**current, **payload}
        normalized = validate_profile(merged)
        now = utc_now()
        try:
            with self.database.write() as db:
                db.execute(
                    (
                        "UPDATE device_profiles SET name=?, transport=?, port=?, baud_rate=?, mirror=?, "
                        "frame_count=?, ccds_per_frame=?, points_per_ccd=?, ccd_indices_json=?, "
                        "point_width_um=?, protection_time_ms=?, screen_width_mm=?, "
                        "screen_resolution_px=?, enabled=?, updated_at=? WHERE id=?"
                    ),
                    (
                        normalized["name"],
                        normalized["transport"],
                        normalized["port"],
                        normalized["baud_rate"],
                        int(normalized["mirror"]),
                        normalized["frame_count"],
                        normalized["ccds_per_frame"],
                        normalized["points_per_ccd"],
                        json.dumps(normalized["ccd_indices"], separators=(",", ":")),
                        normalized["point_width_um"],
                        normalized["protection_time_ms"],
                        normalized["screen_width_mm"],
                        normalized["screen_resolution_px"],
                        int(normalized["enabled"]),
                        now,
                        profile_id,
                    ),
                )
                db.execute(
                    (
                        "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, "
                        "details_json, created_at) VALUES (?, 'device_profile.update', 'device_profile', "
                        "?, ?, ?)"
                    ),
                    (actor_user_id, profile_id, json.dumps({"changed": sorted(payload)}, ensure_ascii=False), now),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise DeviceError(
                    "device_profile_duplicate", "A device profile with this name already exists", status_code=409
                ) from exc
            raise
        return self.profile(profile_id)

    def connect(self, profile_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        self._ownership.check_alignment(self._alignment)
        with self._control:
            return self._connect(profile_id, actor_user_id)

    def _connect(self, profile_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        self._assert_turn_idle()
        profile = self.profile(profile_id)
        correlation_id = str(uuid.uuid4())
        use = None
        previous = self._alignment
        try:
            diagnostics = self.adapter.diagnostics()
            if diagnostics["connected"] and (
                profile["transport"] == "serial" or diagnostics["adapter"] != "acq-simulator"
            ):
                raise DeviceError("device_busy", "请先停止并断开当前设备再切换档案", status_code=409)
            if previous is not None:
                self._ownership.begin_alignment(previous, 'connecting')
                use = previous
            else:
                use, _ = self._ownership.reserve('alignment', profile, 'connecting')
            self._alignment = use
            if not (profile["transport"] == "simulator" and isinstance(self.adapter, AcqSimulatorAdapter)):
                self.adapter = create_device_adapter(
                    profile, exit_gate=self._exit_gate, on_serial_notice=self._on_serial_notice,
                )
            event = self.adapter.connect(profile, correlation_id=correlation_id)
            self._ownership.update(use, 'connected', profile_id=profile_id)
            self._angle = self._settled_at = None
        except DeviceError as exc:
            if use is not None:
                if exc.code == 'serial_stop_unconfirmed':
                    self._ownership.update(use, 'stop_unconfirmed', error=exc.detail())
                elif use is previous:
                    self._update_alignment()
                else:
                    self._ownership.release(use)
                    self._alignment = None
            exc.details.setdefault("correlation_id", correlation_id)
            self._audit(
                actor_user_id, "device.connect.failed", profile_id, {**exc.detail(), "correlation_id": correlation_id}
            )
            raise
        self._audit(
            actor_user_id,
            "device.connect",
            profile_id,
            {"state": event.state.value, "correlation_id": correlation_id, "transport": profile["transport"]},
        )
        return {"profile": profile, "diagnostics": self.diagnostics(), "event": event.to_dict()}

    def shutdown(self) -> list[dict[str, Any]]:
        try:
            self.disconnect()
        except DeviceError as exc:
            return [exc.detail()]
        return []

    @device_command
    def release_for_capture(self, profile_id: int, actor_user_id: int | None) -> None:
        self._assert_turn_idle()
        if not self.adapter.diagnostics()["connected"]:
            return
        if self.adapter.state.value != "connected" or self.adapter.profile.get("id") != profile_id:
            raise DeviceError("device_busy", "请先停止并断开当前调试，再开始摄谱", status_code=409)
        self._disconnect_alignment(actor_user_id)

    @contextmanager
    def capture_session(self, owner, profile_id, actor_user_id, *, position_controlled=False):
        profile = self.profile(profile_id)
        if profile['transport'] != 'serial':
            yield
            return
        with self._connection_reservation(owner, profile, actor_user_id, handoff=True,
                                          position_controlled=position_controlled) as use:
            if not position_controlled:
                self.test_connection(profile_id, actor_user_id=actor_user_id, reservation=use)
            if use.cancel.is_set():
                raise DeviceError('device_operation_cancelled', '设备操作已停止', status_code=409)
            yield

    @contextmanager
    def _connection_reservation(self, owner, profile, actor, *, handoff, position_controlled=False):
        transfer = None
        if handoff:
            if position_controlled:
                transfer = lambda _: None
            else:
                transfer = lambda profile_id: self.release_for_capture(profile_id, actor)
        use, _ = self._ownership.reserve(owner, profile, 'reserved' if position_controlled else 'testing',
                                         handoff=transfer)
        with self._control:
            try:
                if use.cancel.is_set() or self._exit_gate is not None and self._exit_gate.is_set():
                    raise DeviceError('device_operation_cancelled', '设备操作已停止', status_code=409)
                yield use
            finally:
                if use.state != 'stop_unconfirmed':
                    self._ownership.release(use, restore=self._alignment if position_controlled else None)

    def test_connection(self, profile_id: int, actor_user_id: int | None = None, *, handoff: bool = False,
                        owner='alignment', reservation=None) -> dict[str, Any]:
        profile = self.profile(profile_id)
        if reservation is not None:
            return self._test_connection(profile, actor_user_id, reservation)
        with self._connection_reservation(owner, profile, actor_user_id, handoff=handoff) as use:
            return self._test_connection(profile, actor_user_id, use)

    def _test_connection(self, profile, actor_user_id, use) -> dict[str, Any]:
        """Old FmOptHardWare test: one CCD frame, no sample records, then close."""
        profile_id = profile['id']
        correlation_id = str(uuid.uuid4())
        adapter = create_device_adapter(profile, exit_gate=self._exit_gate, on_serial_notice=self._on_serial_notice)
        self._connection_test = (use, adapter)
        frame = None
        failure = None
        try:
            adapter.connect(profile, correlation_id=correlation_id)
            if profile["transport"] == "serial":
                adapter.prepare_capture(pre_seconds=0, burn_seconds=1, burn_count=1,
                                        dark_seconds=0, dark_count=0, correlation_id=correlation_id)
                if use.cancel.is_set():
                    raise DeviceError('device_operation_cancelled', '连接测试已停止', status_code=409)
                adapter.begin_capture()
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if use.cancel.is_set():
                        raise DeviceError('device_operation_cancelled', '连接测试已停止', status_code=409)
                    event = adapter.next_capture_event()
                    if event is not None:
                        frame = event
                    if adapter.capture_error:
                        raise adapter.capture_error
                    if adapter.state.value != "debugging":
                        break
                    time.sleep(.02)
                if frame is None or adapter.state.value != "connected":
                    raise DeviceError("serial_no_response", "未收到有效CCD响应，连接测试未通过", status_code=409)
        except DeviceError as exc:
            failure = exc
        finally:
            try:
                adapter.disconnect(correlation_id=correlation_id)
            except DeviceError as exc:
                failure = exc
                self._ownership.update(use, 'stop_unconfirmed', error=exc.detail())
            else:
                self._connection_test = None
        diagnostics = adapter.diagnostics()
        details = {"profile_id": profile_id, "transport": profile["transport"],
                   "correlation_id": correlation_id, "connected": diagnostics["connected"]}
        if failure:
            self._audit(actor_user_id, "device.connection_test.failed", profile_id, {**details, **failure.detail()})
            raise DeviceError("device_connection_test_failed",
                              f"COM{profile['port']}连接测试失败：{failure.message}；请检查设备参数中的串口和仪器连接",
                              details={**details, "reason": failure.code}, status_code=409) from failure
        result = {**details, "passed": True, "instrument_responded": frame is not None,
                  "frame_sha256": frame.details.get("sha256") if frame else None,
                  "diagnostics": diagnostics}
        self._audit(actor_user_id, "device.connection_test", profile_id, result)
        return result

    def _cancel_connection_test(self):
        test = self._connection_test
        if test is not None:
            use, adapter = test
            use.cancel.set()
            if hasattr(adapter, 'request_stop'):
                adapter.request_stop()

    def _confirm_connection_test_stop(self):
        if self._connection_test is not None:
            use, adapter = self._connection_test
            correlation_id = 'connection-test-stop'
            adapter.confirm_stop(correlation_id=correlation_id)
            adapter.disconnect(correlation_id=correlation_id)
            self._connection_test = None
            self._ownership.release(use)

    def disconnect(self, actor_user_id: int | None = None) -> dict[str, Any]:
        self._cancel_connection_test()
        with self._control:
            self._confirm_connection_test_stop()
            return self._disconnect_alignment(actor_user_id)

    def _disconnect_alignment(self, actor_user_id):
        correlation_id = str(uuid.uuid4())
        use = self._alignment
        self._ownership.update(use, 'stopping')
        try:
            self._cancel_turn_and_wait(correlation_id)
            if hasattr(self.adapter, 'confirm_stop'):
                self.adapter.confirm_stop(correlation_id=correlation_id)
            event = self.adapter.disconnect(correlation_id=correlation_id)
        except DeviceError as exc:
            self._ownership.update(use, 'stop_unconfirmed', error=exc.detail())
            raise
        self._ownership.release(use)
        self._alignment = None
        self._angle = self._settled_at = None
        self._audit(
            actor_user_id, "device.disconnect", None, {"state": event.state.value, "correlation_id": correlation_id}
        )
        return {"diagnostics": self.diagnostics(), "event": event.to_dict()}

    def start_debug(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        self._ownership.check_alignment(self._alignment)
        with self._control:
            return self._start_debug(payload, actor_user_id)

    def _start_debug(self, payload, actor_user_id):
        self._assert_turn_idle()
        self._ownership.begin_alignment(self._alignment, 'debugging')
        correlation_id = str(uuid.uuid4())
        try:
            event = self.adapter.start_debug(
                sample=str(payload.get("sample", "280-288.acq")),
                seed=int(payload.get("seed", 0)),
                fault_frame=payload.get("fault_frame"),
                correlation_id=correlation_id,
            )
        except DeviceError as exc:
            self._update_alignment()
            exc.details.setdefault("correlation_id", correlation_id)
            self._audit(actor_user_id, "device.debug.failed", None, {**exc.detail(), "correlation_id": correlation_id})
            raise
        self._audit(
            actor_user_id,
            "device.debug.start",
            None,
            {
                "session_id": self.adapter.session_id,
                "sample": payload.get("sample", "280-288.acq"),
                "seed": int(payload.get("seed", 0)),
                "correlation_id": correlation_id,
            },
        )
        data = event.to_dict()
        if event.ccds and self._angle is not None:
            data["details"] = {**event.details, "angle_deg": self._angle}
        return {
            "session_id": self.adapter.session_id,
            "event": data,
            "diagnostics": self.diagnostics(),
            "sample_records_created": 0,
            "spectrum_records_created": 0,
        }

    @device_command
    def step_debug(self, actor_user_id: int | None = None) -> dict[str, Any]:
        self._ownership.check_alignment(self._alignment)
        correlation_id = str(uuid.uuid4())
        try:
            event = self.adapter.step_debug(correlation_id=correlation_id)
        except DeviceError as exc:
            self._audit(actor_user_id, "device.debug.fault", None, {**exc.detail(), "correlation_id": correlation_id})
            raise
        if event.event_type == "fault":
            self._audit(actor_user_id, "device.debug.fault", None, {**event.details, "correlation_id": correlation_id})
        else:
            self._audit(
                actor_user_id,
                "device.debug.step",
                None,
                {"frame_index": event.frame_index, "correlation_id": correlation_id,
                 **({"communication": event.details["communication"]} if "communication" in event.details else {})},
            )
        data = event.to_dict()
        if event.ccds:
            before_arrival = (self._settled_at is not None and self.adapter.profile["transport"] == "serial"
                              and event.details.get("exposure_started_at", 0) <= self._settled_at)
            if self._turn_cancel or self._unconfirmed_motor or before_arrival:
                data = DeviceEvent("waiting", event.state, correlation_id=correlation_id,
                                   message="等待转角切换后的调试数据").to_dict()
            elif self._angle is not None:
                data["details"] = {**event.details, "angle_deg": self._angle}
        return {
            "session_id": self.adapter.session_id,
            "event": data,
            "diagnostics": self.diagnostics(),
            "sample_records_created": 0,
            "spectrum_records_created": 0,
        }

    def stop_debug(self, actor_user_id: int | None = None) -> dict[str, Any]:
        self._cancel_connection_test()
        with self._control:
            self._confirm_connection_test_stop()
            return self._stop_debug(actor_user_id)

    def _stop_debug(self, actor_user_id):
        correlation_id = str(uuid.uuid4())
        self._ownership.update(self._alignment, 'stopping')
        try:
            self._cancel_turn_and_wait(correlation_id)
            if hasattr(self.adapter, 'confirm_stop'):
                self.adapter.confirm_stop(correlation_id=correlation_id)
            event = self.adapter.stop_debug(correlation_id=correlation_id)
        except DeviceError as exc:
            self._ownership.update(self._alignment, 'stop_unconfirmed', error=exc.detail())
            raise
        if self._alignment is not None:
            self._alignment.cancel.clear()
        self._update_alignment()
        self._audit(
            actor_user_id, "device.debug.stop", None, {"state": event.state.value, "correlation_id": correlation_id}
        )
        return {
            "event": event.to_dict(),
            "diagnostics": self.diagnostics(),
            "sample_records_created": 0,
            "spectrum_records_created": 0,
        }

    def _update_alignment(self):
        self._ownership.update(self._alignment, self.adapter.state.value)

    def diagnostics(self) -> dict:
        result = self.adapter.diagnostics()
        alignment = self._alignment
        if alignment is not None and alignment.error:
            result['last_error'] = alignment.error
        return {**result, "angle_deg": self._angle, "turning": self._turn_cancel is not None}

    def _assert_turn_idle(self) -> None:
        if self._turn_cancel is not None or self._turn_stoppers:
            raise DeviceError("device_busy", "正在切换转角", status_code=409)
        if self._unconfirmed_motor is not None:
            raise DeviceError("motor_stop_unconfirmed", "请先停止设备并确认电机已停", status_code=409)

    def _cancel_turn_and_wait(self, correlation_id: str) -> None:
        if self._turn_cancel is not None:
            self._turn_cancel.set()
            self._turn_stoppers += 1
            try:
                self._turn_changed.wait_for(lambda: self._turn_cancel is None)
            finally:
                self._turn_stoppers -= 1
        if self._unconfirmed_motor is not None:
            try:
                self._unconfirmed_motor.stop()
            except DeviceError as motor_error:
                try:
                    self.adapter.stop_debug(correlation_id=correlation_id)
                except DeviceError as ccd_error:
                    motor_error.details["ccd_stop"] = ccd_error.detail()
                raise
            self._unconfirmed_motor = None

    @device_command
    def update_motor_binding(self, profile_id, binding, actor) -> None:
        self._assert_turn_idle()
        if self.adapter.state.value == "debugging":
            raise DeviceError("device_busy", "请先停止当前采集，再修改电机绑定", status_code=409)
        save_motor_binding(self.database, self.profile(profile_id), binding, actor)
        if (self.adapter.profile or {}).get("id") == profile_id:
            self._angle = self._settled_at = None

    @device_command
    def turn_state(self, method_angles: list[float]) -> dict:
        connected = self.adapter.diagnostics()["connected"]
        profile = self.adapter.profile if connected else self.current_profile()
        profile_id = profile["id"] if profile else None
        simulated = bool(profile and profile["transport"] == "simulator")
        angles = method_angles
        if not angles and profile and not simulated:
            binding = motor_binding(self.database, profile_id)
            angles = [item.method_angle_deg for item in binding.angles] if binding else []
        return {"profile_id": profile_id, "angles": angles, "simulated": simulated,
                "current_angle_deg": self._angle if connected else None, "moving": self._turn_cancel is not None}

    def switch_debug_angle(self, profile_id: int, angle: float, method_angles: list[float], actor: int) -> dict:
        self._ownership.check_alignment(self._alignment)
        with self._control:
            self._assert_turn_idle()
            if self._exit_gate is not None and self._exit_gate.is_set():
                raise DeviceError("device_exiting", "程序正在退出", status_code=409)
            if self.adapter.state.value not in {"connected", "debugging"} or self.adapter.profile["id"] != profile_id:
                raise DeviceError("device_not_connected", "请先连接当前调试设备", status_code=409)
            options = self.turn_state(method_angles)
            if angle not in options["angles"]:
                raise DeviceError("device_angle_unavailable", "该转角不在当前可选范围内", status_code=409)
            motor = None if options["simulated"] else prepare_motor_turn(
                self.database, self.adapter.profile, [angle], preflight=False)
            self._ownership.begin_alignment(self._alignment, 'turning')
            correlation_id = str(uuid.uuid4())
            cancel = self._turn_cancel = threading.Event()
            self._angle = self._settled_at = None
        try:
            if motor is None:
                receipt = self.adapter.position_angle(angle, correlation_id)
            else:
                receipt = motor.position(angle, correlation_id, cancel)
            with self._control:
                if cancel.is_set():
                    raise InterruptedError
                self._settled_at = time.monotonic()
                self._angle = angle
                self._audit(actor, "device.debug.turn", profile_id, {**receipt, "correlation_id": correlation_id})
                return {**options, "current_angle_deg": angle, "moving": False}
        except InterruptedError as exc:
            self._audit(actor, "device.debug.failed", profile_id, {"angle_deg": angle, "code": "device_turn_cancelled",
                                                                  "correlation_id": correlation_id})
            raise DeviceError("device_turn_cancelled", "转角切换已停止", status_code=409) from exc
        except DeviceError as exc:
            if exc.code == "motor_stop_unconfirmed":
                with self._control:
                    self._unconfirmed_motor = motor
                    self._ownership.update(self._alignment, 'stop_unconfirmed', error=exc.detail())
            self._audit(actor, "device.debug.failed", profile_id, {**exc.detail(), "angle_deg": angle,
                                                                  "correlation_id": correlation_id})
            raise
        finally:
            with self._turn_changed:
                if self._alignment is not None and self._alignment.state == 'turning':
                    self._update_alignment()
                self._turn_cancel = None
                self._turn_changed.notify_all()

    def _audit(self, actor_user_id: int | None, action: str, target_id: int | None, details: dict[str, Any]) -> None:
        with self.database.write() as db:
            db.execute(
                (
                    "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, "
                    "details_json, created_at) VALUES (?, ?, 'device', ?, ?, ?)"
                ),
                (
                    actor_user_id,
                    action,
                    target_id,
                    json.dumps(details, ensure_ascii=False, separators=(",", ":")),
                    utc_now(),
                ),
            )
