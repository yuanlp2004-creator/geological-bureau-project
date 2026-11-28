"""SpecDirect CCD transport, from uSioLink/uCcdThread (not a turn motor protocol).

Only the documented-in-source F0/pre/cycle/count/F0, cycle-change and 00
commands are transmitted. A background reader owns instrument timing; HTTP
polling never controls the physical acquisition clock.
"""
from __future__ import annotations

import hashlib
import math
import queue
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable

import serial

from .profiles import validate_profile
from .protocol import parse_acq_frame
from .values import AcquisitionState, DeviceError, DeviceEvent


def legacy_ticks(seconds: float, field: str, *, minimum: float = 0, maximum: float = 63.75) -> int:
    value = float(seconds)
    if not math.isfinite(value):
        raise DeviceError("serial_condition_invalid", f"真实设备的{field}必须为有限数值")
    ticks = round(value / .25)
    if not minimum <= value <= maximum or not 0 <= ticks <= 255 or abs(ticks * .25 - value) > 1e-8:
        raise DeviceError("serial_condition_invalid", f"真实设备的{field}须以0.25秒递增，范围{minimum}–{maximum}秒")
    return ticks


class SerialAcqAdapter:
    """One exclusive COM owner, finite captures or continuous alignment."""

    def __init__(self, *, exit_gate: threading.Event | None = None,
                 on_notice: Callable[[str, str, str, dict[str, Any]], None] | None = None) -> None:
        self.state = AcquisitionState.IDLE
        self.profile: dict[str, Any] | None = None
        self.session_id: str | None = None
        self._port: Any = None
        self._control = threading.RLock()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._frames: queue.Queue[DeviceEvent] = queue.Queue(maxsize=32)
        self._last: DeviceEvent | None = None
        self._error: DeviceError | None = None
        self._stop_error: DeviceError | None = None
        self._trace: deque[dict[str, Any]] = deque(maxlen=32)
        self._continuous = False
        self._command_sent = False
        self._end_sent = False
        self._stop_confirmed = False
        self._settings: dict[str, Any] = {}
        self.capture_phase = "idle"
        self._exit_gate = exit_gate
        self._on_notice = on_notice

    def _check_exit(self) -> None:
        if self._exit_gate is not None and self._exit_gate.is_set():
            raise DeviceError("device_exit_in_progress", "程序正在停止设备，不能开始新的真实采集", status_code=409)

    def connect(self, profile: dict[str, Any], *, correlation_id: str) -> DeviceEvent:
        with self._control:
            self._check_exit()
            if self._port is not None:
                raise DeviceError("device_busy", "请先停止并断开当前设备", status_code=409)
            normalized = validate_profile(profile)
            if normalized["transport"] != "serial" or not normalized["enabled"]:
                raise DeviceError("serial_profile_invalid", "请选择已启用的真实串口设备档案")
            if normalized["baud_rate"] not in {460800, 921600}:
                raise DeviceError("serial_baud_unsupported", "旧设备接口仅确认支持460800或921600波特率")
            # These are the six-CCD transfer dimensions verified against old
            # source and all original ACQ fixtures. Other hardware needs evidence.
            if (normalized["frame_count"], normalized["ccds_per_frame"], normalized["points_per_ccd"]) != (3, 2, 2048):
                raise DeviceError("serial_layout_unsupported", "真实接口当前支持旧设备的3组×2CCD×2048点布局")
            self.profile = normalized
            self.state = AcquisitionState.CONNECTING
            try:
                self._port = serial.Serial(
                    port=f"COM{normalized['port']}", baudrate=normalized["baud_rate"],
                    bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_TWO,
                    timeout=.05, write_timeout=.1, xonxoff=False, rtscts=False, dsrdtr=False,
                )
                self._port.reset_input_buffer()
                self._port.reset_output_buffer()
                time.sleep(.1)  # uSioLink.Open
            except (OSError, ValueError, serial.SerialException) as exc:
                self.state = AcquisitionState.ERROR
                try:
                    self._close_port()
                except (OSError, serial.SerialException) as close_error:
                    raise DeviceError("serial_stop_unconfirmed", "无法确认串口已关闭，请检查设备状态",
                                      status_code=409) from close_error
                raise DeviceError("serial_open_failed", f"无法打开COM{normalized['port']}，请检查蓝牙设备是否已配对并开机、端口是否正确或被其他程序占用",
                                  details={"port": f"COM{normalized['port']}", "reason": str(exc)}, status_code=409) from exc
            self.state = AcquisitionState.CONNECTED
            return DeviceEvent("connected", self.state, correlation_id=correlation_id,
                               message="串口已打开，仪器响应需开始采集后确认", details={"instrument_verified": False})

    def prepare_capture(self, *, pre_seconds: float, burn_seconds: float, burn_count: int,
                        dark_seconds: float, dark_count: int, countdown_seconds: float = 0,
                        correlation_id: str, continuous: bool = False, motor_turn=None) -> DeviceEvent:
        with self._control:
            self._check_exit()
            if self.state != AcquisitionState.CONNECTED or self._worker and self._worker.is_alive():
                raise DeviceError("device_not_ready", "设备未连接或正在采集", status_code=409)
            pre = legacy_ticks(pre_seconds, "预激时间", maximum=10)
            burn = legacy_ticks(burn_seconds, "燃烧周期", minimum=1, maximum=2)
            dark = legacy_ticks(dark_seconds, "暗帧周期", minimum=1, maximum=2) if dark_count else 0
            if not 1 <= burn_count <= 255 or not 0 <= dark_count <= 20 or burn_count + dark_count + 1 > 255:
                raise DeviceError("serial_count_invalid", "真实设备燃烧帧、暗帧与转换帧总数不能超过255")
            if not math.isfinite(countdown_seconds) or not 0 <= countdown_seconds <= 600:
                raise DeviceError("serial_countdown_invalid", "倒计时超出范围")
            self._continuous = continuous
            self._settings = dict(pre=pre, burn=burn, dark=dark, burns=burn_count, darks=dark_count,
                                  countdown=countdown_seconds, correlation_id=correlation_id, motor_turn=motor_turn)
            self.session_id = str(uuid.uuid4())
            self._frames = queue.Queue(maxsize=1 if continuous else 32)
            self._last = None
            self._error = self._stop_error = None
            self._command_sent = self._end_sent = self._stop_confirmed = False
            self._cancel.clear()
            self.capture_phase = "turning" if motor_turn else "countdown"
            self._trace.clear()
            return DeviceEvent("prepared", self.state, correlation_id=correlation_id,
                               message="真实采集已准备", details={"transport": "serial", "effective_pre_seconds": max(8, pre) * .25})

    def begin_capture(self) -> None:
        with self._control:
            self._check_exit()
            if self._worker and self._worker.is_alive():
                raise DeviceError("device_busy", "采集已在运行", status_code=409)
            self.state = AcquisitionState.DEBUGGING
            self._worker = threading.Thread(target=self._run, name="legacy-ccd-reader", daemon=True)
            self._worker.start()

    def start_debug(self, *, sample: str, seed: int, fault_frame: int | None, correlation_id: str) -> DeviceEvent:
        if fault_frame is not None:
            raise DeviceError("serial_simulation_invalid", "真实设备不支持模拟故障参数")
        event = self.prepare_capture(pre_seconds=0, burn_seconds=1, burn_count=1, dark_seconds=0,
                                     dark_count=0, continuous=True, correlation_id=correlation_id)
        self.begin_capture()
        return DeviceEvent("started", self.state, correlation_id=correlation_id, message="真实CCD连续调试已开始",
                           details=event.details)

    def _notice(self, kind: str, message: str, *, started: int | None = None, completed: str = '',
                suffix: str = '', severity: str = 'info', **details: Any) -> None:
        if self._on_notice is None:
            return
        tick = time.perf_counter_ns()
        text = f'{message} Freq: {tick // 1_000_000}'
        if started is not None:
            text = f'{message} Freq: {started} · {completed} Freq: {tick // 1_000_000}'
        if suffix:
            text += f' · {suffix}'
        self._on_notice(kind, text, severity, {
            'tick_ns': tick, 'start_ms': started, 'end_ms': tick // 1_000_000,
            'session_id': self.session_id, 'correlation_id': self._settings['correlation_id'],
            'port': self.profile['port'], 'phase': self.capture_phase, **details,
        })

    def _write(self, payload: bytes) -> None:
        started = time.perf_counter_ns() // 1_000_000
        count = self._port.write(payload)
        self._trace.append({"direction": "tx", "hex": payload.hex(), "bytes": count})
        if count != len(payload):
            self._notice('command_incomplete', '发送指令', started=started, completed='写入不完整',
                         suffix=f'{payload.hex(" ").upper()} · {count}/{len(payload)} 字节', severity='error',
                         command_hex=payload.hex(), bytes_written=count)
            raise DeviceError("serial_write_incomplete", "串口命令未完整发送", details={"expected": len(payload), "actual": count})
        if payload == b"\x00":
            self._end_sent = True
        self._notice('command_sent', '发送指令', started=started, completed='指令完毕',
                     suffix=payload.hex(' ').upper(), command_hex=payload.hex(), bytes_written=count)

    def _wait_until(self, deadline: float) -> bool:
        while not self._cancel.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            self._cancel.wait(remaining)
        return False

    @property
    def _transfer_seconds(self) -> float:
        return 24579 * 11 / self.profile["baud_rate"]  # 1 start + 8 data + 2 stop

    @property
    def _margin(self) -> float:
        return max(.2, self.profile["protection_time_ms"] / 1000)

    def _read_transfer(self, *, stopping: bool = False, extra_wait: float = 0) -> bytes:
        deadline = time.monotonic() + self._transfer_seconds + self._margin + extra_wait
        payload = bytearray()
        while len(payload) < 24579 and time.monotonic() < deadline:
            chunk = self._port.read(24579 - len(payload))
            payload.extend(chunk)
        self._trace.append({"direction": "rx", "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
        if len(payload) != 24579:
            raise DeviceError("serial_frame_incomplete", "CCD数据未完整接收，采集已中止",
                              details={"expected": 24579, "actual": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
        return bytes(payload)

    def _parse(self, payload: bytes) -> dict[str, Any]:
        return parse_acq_frame(payload, mirror=self.profile["mirror"], ccd_indices=self.profile["ccd_indices"])

    def _capture_frame(self, phase: str, index: int, started: float, *, extra_wait: float = 0,
                       exposure_started_at: float | None = None) -> None:
        if exposure_started_at is not None:
            exposure_started_at = min(exposure_started_at, time.monotonic())
        receive_start_ms = time.perf_counter_ns() // 1_000_000
        payload = self._read_transfer(extra_wait=extra_wait)
        receive_end_ms = time.perf_counter_ns() // 1_000_000
        parsed = self._parse(payload)
        event = DeviceEvent("frame", AcquisitionState.DEBUGGING, correlation_id=self._settings["correlation_id"],
            frame_index=index, frame_count=3, ccds=parsed["ccds"], details={
                **{key: parsed[key] for key in ("sha256", "frame_size", "byte_length", "headers", "mirror", "ccd_indices")},
                "transport": "serial", "phase": phase, "phase_index": index,
                "receive_start_ms": receive_start_ms, "receive_end_ms": receive_end_ms,
                **({"exposure_started_at": exposure_started_at} if exposure_started_at is not None else {}),
                "elapsed_ms": (time.monotonic() - started) * 1000,
                "communication": list(self._trace),
                **({"turn_position": self._settings["turn_position"]} if "turn_position" in self._settings else {}),
            })
        if not self._continuous and self._settings.get("motor_turn"):
            final_phase = "dark" if self._settings["darks"] else "burn"
            final_count = self._settings["darks"] or self._settings["burns"]
            if phase == final_phase and index + 1 == final_count:
                self._settings["final_event"] = event
                return
        if self._continuous:
            try:
                self._frames.get_nowait()  # alignment observes the newest frame
            except queue.Empty:
                pass
        try:
            self._frames.put_nowait(event)
        except queue.Full as exc:
            raise DeviceError("serial_consumer_stalled", "采集保存未及时处理，已停止设备以避免丢帧") from exc

    def _run(self) -> None:
        s = self._settings
        correlation_id = s["correlation_id"]
        motor, angle = s["motor_turn"] or (None, None)
        monitoring = threading.Event()
        monitor = None
        motor_errors = []
        try:
            if motor is not None:
                self._notice('motor_turning', f'正在定位转角 {angle:g}°')
                s["turn_position"] = motor.position(angle, correlation_id, self._cancel)
                self._notice('motor_positioned', f'转角 {angle:g}° 已到位', **s["turn_position"])
                def watch_position():
                    while not monitoring.wait(1):
                        try:
                            motor.verify_position()
                        except DeviceError as exc:
                            motor_errors.append(exc)
                            self._cancel.set()
                            return
                monitor = threading.Thread(target=watch_position, name="ccd-motor-position-monitor", daemon=True)
                monitor.start()
            self.capture_phase = "countdown"
            if not self._wait_until(time.monotonic() + s["countdown"]):
                return
            self.capture_phase = "pre_excitation"
            self._port.reset_input_buffer()
            self._port.reset_output_buffer()
            self._command_sent = True  # even a partial start requires stop
            self._write(bytes((0xF0, s["pre"], s["burn"], 0 if self._continuous else s["burns"] + s["darks"] + 1, 0xF0)))
            started = time.monotonic()
            pre_end = started + max(8, s["pre"]) * .25
            if not self._wait_until(pre_end + .5):
                return
            self._port.reset_input_buffer()  # old wsPre discards pre-excitation data
            self.capture_phase = "burn"
            if not self._continuous and s["burns"] == 1:
                self._write(bytes((s["dark"],)))
            index = 0
            while self._continuous or index < s["burns"]:
                if not self._wait_until(pre_end + (index + 1) * s["burn"] * .25 + self._margin):
                    return
                self._capture_frame("burn", index, started,
                                    exposure_started_at=pre_end + index * s["burn"] * .25 if self._continuous else None)
                index += 1
                if not self._continuous and index == s["burns"] - 1:
                    self._write(bytes((s["dark"],)))
            if s["darks"]:
                # wsTurn consumes a complete transition transfer, never a dark frame.
                transition_start = time.perf_counter_ns() // 1_000_000
                self._parse(self._read_transfer(extra_wait=s["dark"] * .25))
                self._notice('dark_transition', '状态转换', started=transition_start, completed='转换完成',
                             suffix='切换至空白采集', phase='transition')
                self.capture_phase = "dark"
                if s["darks"] == 1:
                    self._write(b"\x00")
                for index in range(s["darks"]):
                    self._capture_frame("dark", index, started, extra_wait=s["dark"] * .25)
                    if index == s["darks"] - 2:
                        self._write(b"\x00")
            self._stop_confirmed = True  # final transfer after the old end command
            if motor is not None:
                monitoring.set()
                monitor.join()
                if motor_errors:
                    raise motor_errors[0]
                if not self._cancel.is_set():
                    motor.verify_position()
                    try:
                        self._frames.put_nowait(s["final_event"])
                    except queue.Full as exc:
                        raise DeviceError("serial_consumer_stalled", "采集保存未及时处理，已停止设备以避免丢帧") from exc
            self._notice('measurement_ended', '设备测量结束')
        except InterruptedError:
            pass
        except (DeviceError, OSError, ValueError, serial.SerialException) as exc:
            self._error = exc if isinstance(exc, DeviceError) else DeviceError("serial_io_failed", f"串口通信失败：{exc}")
            label = '转角电机异常' if self._error.code.startswith('motor_') else 'CCD 通信异常'
            self._notice('communication_fault', label, suffix=self._error.message,
                         severity='error', code=self._error.code)
        finally:
            monitoring.set()
            if monitor is not None:
                monitor.join()
            if motor_errors and self._error is None:
                self._error = motor_errors[0]
                self._notice('communication_fault', '转角电机异常', suffix=self._error.message,
                             severity='error', code=self._error.code)
            if self._command_sent and not self._stop_confirmed:
                self._notice('stop_waiting', '等待中止')
                try:
                    if not self._end_sent:
                        self._write(b"\x00")
                    self._parse(self._read_transfer(stopping=True, extra_wait=max(s["burn"], s["dark"]) * .25))
                    self._stop_confirmed = True
                    self._notice('stop_confirmed', '中止成功', suffix='已收到完整结束响应')
                except (DeviceError, OSError, ValueError, serial.SerialException) as exc:
                    self._stop_error = DeviceError("serial_stop_unconfirmed", "结束指令未获完整响应，请检查仪器状态",
                                                  details={"reason": str(exc), "correlation_id": correlation_id})
                    self._notice('stop_unconfirmed', '中止未确认', suffix=self._stop_error.message,
                                 severity='error', code=self._stop_error.code)
            if motor is not None and s.get("turn_position") and (self._error or self._cancel.is_set()):
                try:
                    motor.stop()
                except DeviceError as exc:
                    self._stop_error = exc
                    self._notice('motor_stop_unconfirmed', '电机停止未确认', suffix=exc.message,
                                 severity='error', code=exc.code)
            self.state = AcquisitionState.ERROR if self._error or self._stop_error else AcquisitionState.CONNECTED

    def wait_for_capture_end(self) -> None:
        if self._worker is not None:
            self._worker.join()
        if self.capture_error:
            raise self.capture_error

    def next_capture_event(self) -> DeviceEvent | None:
        try:
            self._last = self._frames.get_nowait()
        except queue.Empty:
            if self.capture_error:
                raise self.capture_error
            return None
        return self._last

    @property
    def pending_frames(self) -> bool:
        return not self._frames.empty()

    @property
    def capture_error(self) -> DeviceError | None:
        # Unconfirmed physical stop takes precedence over the triggering fault.
        if self._stop_error and self._stop_error.code == "motor_stop_unconfirmed":
            return self._stop_error
        return self._error or self._stop_error

    @property
    def turn_position(self) -> dict[str, Any] | None:
        return self._settings.get("turn_position")

    @property
    def stop_requested(self) -> bool:
        return self._cancel.is_set()

    def request_stop(self) -> None:
        self._cancel.set()

    def confirm_stop(self, *, correlation_id: str) -> None:
        """Retain a failed shutdown until a fresh stop can be confirmed."""
        with self._control:
            error = self._stop_error or self._error
            if error is None or error.code not in {"motor_stop_unconfirmed", "serial_stop_unconfirmed"}:
                return
            if self._worker and self._worker.is_alive():
                try:
                    self.stop_debug(correlation_id=correlation_id)
                    return
                except DeviceError as exc:
                    if self._worker.is_alive():
                        raise
                    error = exc
            if error.code == "motor_stop_unconfirmed":
                motor, _ = self._settings["motor_turn"]
                motor.stop()
                if self._command_sent and not self._stop_confirmed:
                    raise DeviceError("serial_stop_unconfirmed", "未收到串口结束响应，请检查仪器状态",
                                      status_code=409)
                self._stop_error = None
                if self._error is error:
                    self._error = None
            elif not self._stop_confirmed:
                raise error
            else:
                self._stop_error = None

    def step_debug(self, *, correlation_id: str) -> DeviceEvent:
        event = self.next_capture_event()
        return event or DeviceEvent("waiting", self.state, correlation_id=correlation_id,
            ccds=self._last.ccds if self._last else [], message="等待真实CCD数据",
            details=self._last.details if self._last else {"transport": "serial"})

    def stop_debug(self, *, correlation_id: str) -> DeviceEvent:
        with self._control:
            self._cancel.set()
            if self._worker and self._worker.is_alive():
                timeout = max(self._settings["burn"], self._settings["dark"]) * .25 + 2 * (self._transfer_seconds + self._margin) + 1
                self._worker.join(timeout=timeout + (60 if self._settings.get("motor_turn") else 0))
                if self._worker.is_alive():
                    self._stop_error = DeviceError("serial_stop_unconfirmed", "串口停止超时，请检查仪器状态")
                    self._notice('stop_unconfirmed', '中止未确认', suffix=self._stop_error.message,
                                 severity='error', code=self._stop_error.code)
            if self._stop_error or self._error and self._error.code == "motor_stop_unconfirmed":
                raise self._stop_error or self._error
            if self._port is not None:
                self.state = AcquisitionState.CONNECTED
            self.session_id = None
            return DeviceEvent("stopped", self.state, correlation_id=correlation_id,
                               message="真实采集已停止", details={"stop_confirmed": self._stop_confirmed,
                               "command_sent": self._command_sent, "physical_safe_state": "unverified"})

    def _close_port(self) -> None:
        if self._port is not None:
            self._port.close()
            self._port = None

    def disconnect(self, *, correlation_id: str) -> DeviceEvent:
        if self._port is None and not (self._worker and self._worker.is_alive()):
            self.state = AcquisitionState.IDLE
            self.session_id = None
            return DeviceEvent("disconnected", self.state, correlation_id=correlation_id,
                               message="串口已关闭", details={"stop_confirmed": self._stop_confirmed,
                               "physical_safe_state": "unverified"})
        try:
            event = self.stop_debug(correlation_id=correlation_id)
        finally:
            try:
                self._close_port()
            except (OSError, serial.SerialException) as exc:
                raise DeviceError("serial_stop_unconfirmed", "无法确认串口已关闭，请检查设备状态",
                                  status_code=409) from exc
            finally:
                self.state = AcquisitionState.IDLE if self._port is None else AcquisitionState.ERROR
                self.session_id = None
        return DeviceEvent("disconnected", self.state, correlation_id=correlation_id, message="串口已关闭", details=event.details)

    def diagnostics(self) -> dict[str, Any]:
        return {"adapter": "legacy-ccd-serial", "state": self.state.value, "session_id": self.session_id,
                "connected": self._port is not None, "port": f"COM{self.profile['port']}" if self.profile else None,
                "profile_id": self.profile.get("id") if self.profile else None,
                "instrument_responded": self._last is not None,
                "last_error": (self._stop_error or self._error).detail() if self._stop_error or self._error else None,
                "contract": {"frame_count": 3, "ccds_per_frame": 2, "points_per_ccd": 2048, "frame_size": 8193, "byte_length": 24579},
                "stop_confirmed": self._stop_confirmed, "physical_safe_state": "unverified", "trace": list(self._trace)}


def monitor_capture(adapter: SerialAcqAdapter, advance: Callable[[], Any], fail: Callable[[str], Any]) -> None:
    """Persist serial captures independently of the current page/polling rate."""
    def run() -> None:
        while True:
            cancelled = adapter._cancel.wait(.03)
            if cancelled and adapter.capture_error is None:
                if adapter._settings.get("motor_turn") and adapter._worker and adapter._worker.is_alive():
                    threading.Event().wait(.03)
                    continue
                return
            try:
                result = advance()
                if result["status"] in {"completed", "between_repeats", "failed", "stopped"}:
                    return
            except Exception as exc:
                # A simultaneous explicit HTTP command may hold the task lock.
                if getattr(exc, "code", "") in {"acquisition_task_busy", "dispersion_task_busy"}:
                    continue
                try:
                    fail(str(exc))
                finally:
                    # Also stops the reader if persistence itself fails.
                    try:
                        adapter.disconnect(correlation_id="serial-save-failure")
                    except DeviceError:
                        pass
                return
    threading.Thread(target=run, name="serial-capture-save", daemon=True).start()
