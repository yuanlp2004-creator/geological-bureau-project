"""Use the commissioned local RtuMotor service without opening the CCD COM on it."""
from __future__ import annotations

import json
import math
import re
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...db import Database, utc_now
from .ports import validate_bluetooth_binding
from .values import DeviceError


class MotorPositionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    reference_source: str = Field(min_length=1, max_length=240)
    reference_file: str = Field(min_length=1, max_length=255)
    observed_file: str = Field(min_length=1, max_length=255)
    reference_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    observed_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    ccd_index: int = Field(ge=0, le=255)
    reference_angle_deg: float = Field(ge=0, le=360)
    reference_peak: int = Field(ge=0)
    observed_peak: int = Field(ge=0)
    target_angle_deg: float = Field(ge=0, le=360)


class MotorAngle(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    method_angle_deg: float = Field(ge=0, le=360)
    motor_angle_deg: float
    evidence: MotorPositionEvidence | None = None

    @model_validator(mode="after")
    def matches_target(self):
        if self.evidence and self.evidence.target_angle_deg != self.method_angle_deg:
            raise ValueError("定位依据的目标角与方法转角不一致")
        return self


class MotorBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    bluetooth_address: str = Field(pattern=r"^[0-9A-Fa-f]{12}$")
    motor_port: int = Field(ge=1, le=256)
    api_port: int = Field(default=8790, ge=1, le=65535)
    calibration_id: str = Field(min_length=1, max_length=200)
    angles: list[MotorAngle] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_angles(self):
        if len({point.method_angle_deg for point in self.angles}) != len(self.angles):
            raise ValueError("同一方法转角只能绑定一个已标定的电机坐标")
        return self


def motor_binding(database: Database, profile_id: int) -> MotorBinding | None:
    with database.read() as db:
        row = db.execute("SELECT value FROM app_metadata WHERE key=?", (f"devices.motor_binding.{profile_id}",)).fetchone()
    return MotorBinding.model_validate_json(row["value"]) if row else None


def requires_motor(database: Database, profile, *, multiple: bool) -> bool:
    return profile["transport"] == "serial" and (multiple or motor_binding(database, profile["id"]) is not None)


def save_motor_binding(database: Database, profile: dict, binding: MotorBinding | None, actor: int) -> None:
    if binding is not None:
        _validate_ports(profile, binding)
        if any(angle.evidence and angle.evidence.ccd_index not in profile["ccd_indices"] for angle in binding.angles):
            raise DeviceError("motor_evidence_ccd_mismatch", "定位依据的 CCD 不在当前设备档案中", status_code=409)
    key = f"devices.motor_binding.{profile['id']}"
    now = utc_now()
    with database.write() as db:
        if binding is None:
            db.execute("DELETE FROM app_metadata WHERE key=?", (key,))
        else:
            db.execute("INSERT INTO app_metadata(key,value,updated_at) VALUES(?,?,?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                       (key, binding.model_dump_json(), now))
        db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) "
                   "VALUES (?,'device.profile.update','device_profile',?,?,?)",
                   (actor, profile['id'], json.dumps({"motor_binding": binding.model_dump() if binding else None}), now))


def _validate_ports(profile, binding: MotorBinding) -> None:
    if profile["transport"] != "serial" or profile["port"] == binding.motor_port:
        raise DeviceError("motor_port_conflict", "CCD采集与蓝牙电机须使用两个不同的真实COM口", status_code=409)
    validate_bluetooth_binding(binding.bluetooth_address, binding.motor_port)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class MotorTurn:
    def __init__(self, binding: MotorBinding, key: str, targets: dict[float, float]):
        self.binding = binding
        self.targets = targets
        self._key = key
        self._base = f"http://127.0.0.1:{binding.api_port}/api/v1/motors"
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self._commissioned_profile = None
        self.target_mms: str | None = None

    def _request(self, path, *, post=False, payload=None, timeout=4):
        body = json.dumps(payload, allow_nan=False).encode() if payload is not None else None
        request = Request(self._base + path, data=body, method="POST" if post else "GET",
                          headers={"Authorization": "Bearer " + self._key, "Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=timeout) as response:
                value = json.load(response)
                if not isinstance(value, dict):
                    raise ValueError("expected a JSON object")
                return value
        except HTTPError as exc:
            with exc:
                try:
                    detail = json.load(exc).get("detail")
                except (ValueError, AttributeError, OSError):
                    detail = None
            code = detail.get("code") if isinstance(detail, dict) else None
            raise DeviceError("motor_service_rejected", "本机电机服务拒绝了请求",
                              details={"motor_code": code, "http_status": exc.code}, status_code=409) from exc
        except (ValueError, OSError) as exc:
            raise DeviceError("motor_service_unavailable", "无法确认本机电机服务的响应", status_code=409) from exc

    def _reference(self, status):
        profile = status.get("profile") or {}
        if (profile.get("transport") != "serial" or status.get("simulated") is not False
                or profile.get("port") != f"COM{self.binding.motor_port}" or profile.get("motion_verified") is not True
                or profile.get("calibration_id") != self.binding.calibration_id
                or status.get("reference_valid") is not True
                or self._commissioned_profile is not None and profile != self._commissioned_profile):
            raise DeviceError("motor_reference_unverified", "电机服务的COM口或现场标定未通过核对", status_code=409)
        return profile

    def preflight(self):
        status = self._request("/status")
        profile = self._reference(status)
        if status.get("worker_active") is not False or status.get("state") not in {"idle", "stopped"}:
            raise DeviceError("motor_not_ready", "蓝牙电机未处于可定位状态", status_code=409)
        bounds = (profile.get("min_angle_deg"), profile.get("max_angle_deg"))
        if (not all(type(value) in (int, float) and math.isfinite(value) for value in bounds)
                or bounds[0] >= bounds[1] or any(not bounds[0] <= target <= bounds[1] for target in self.targets.values())):
            raise DeviceError("motor_target_outside_limits", "本次摄谱的电机坐标超出现场标定范围", status_code=409)
        self._commissioned_profile = profile

    def verify_position(self):
        status = self._request("/refresh", post=True)
        self._reference(status)
        snapshot = status.get("snapshot") or {}
        if (status.get("state") != "idle" or status.get("worker_active") is not False
                or snapshot.get("position") != self.target_mms or snapshot.get("position_set") != self.target_mms
                or snapshot.get("velocity") != 0 or snapshot.get("error_code") != 0):
            raise DeviceError("motor_position_lost", "无法确认电机仍停在摄谱位置", status_code=409)

    def stop(self):
        try:
            result = self._request("/stop", post=True, timeout=35)
        except DeviceError as exc:
            raise DeviceError("motor_stop_unconfirmed", "未能确认电机停止，请检查仪器", details=exc.detail(), status_code=409) from exc
        if result.get("stop_confirmed") is not True:
            raise DeviceError("motor_stop_unconfirmed", "未能确认电机停止，请检查仪器", status_code=409)

    def position(self, angle, correlation_id, cancel):
        self.preflight()
        if cancel.is_set():
            raise InterruptedError
        target = self.targets[angle]
        try:
            start = self._request("/move", post=True, payload={"angle_deg": target, "correlation_id": correlation_id},
                                  timeout=20)
            operation = start.get("operation") or {}
            identifier = operation.get("id", "")
            if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}", identifier):
                raise DeviceError("motor_operation_invalid", "电机服务没有返回可核对的定位任务", status_code=409)
            if operation.get("correlation_id") != correlation_id or operation.get("requested_angle_deg") != target:
                raise DeviceError("motor_operation_invalid", "电机定位任务与本次摄谱不一致", status_code=409)
            timeout = self._commissioned_profile.get("move_timeout_s")
            if type(timeout) not in (int, float) or not 0 < timeout <= 300:
                raise DeviceError("motor_reference_unverified", "电机服务缺少有效的定位超时配置", status_code=409)
            deadline = time.monotonic() + timeout + 2
            while not cancel.wait(.08):
                if time.monotonic() >= deadline:
                    raise DeviceError("motor_position_timeout", "等待电机到位超时", status_code=409)
                state = self._request("/operations/" + identifier)
                operation = state.get("operation") or {}
                if operation.get("status") in {"failed", "stopped"}:
                    raise DeviceError("motor_position_failed", "电机定位失败或已停止", status_code=409)
                if operation.get("status") == "completed" and state.get("worker_active") is False:
                    position = operation.get("target_mms")
                    if (operation.get("id") != identifier or operation.get("correlation_id") != correlation_id
                            or not isinstance(position, str) or not re.fullmatch(r"-?\d+", position)):
                        raise DeviceError("motor_operation_invalid", "电机反馈与本次任务不一致", status_code=409)
                    self.target_mms = position
                    self.verify_position()
                    if cancel.is_set():
                        break
                    return {"angle_deg": angle, "motor_angle_deg": target, "calibration_id": self.binding.calibration_id,
                            "motor_port": f"COM{self.binding.motor_port}", "operation_id": identifier, "target_mms": position}
            raise InterruptedError
        except (InterruptedError, DeviceError):
            self.stop()
            raise


def prepare_motor_turn(database: Database, profile, angles, *, preflight=True) -> MotorTurn:
    binding = motor_binding(database, profile["id"])
    if binding is None:
        raise DeviceError("hardware_protocol_unavailable", "请先在设备连接绑定已完成现场标定的蓝牙电机", status_code=409)
    _validate_ports(profile, binding)
    mapping = {point.method_angle_deg: point.motor_angle_deg for point in binding.angles}
    missing = [angle for angle in angles if angle not in mapping]
    if missing:
        raise DeviceError("motor_angle_not_calibrated", "本次方法存在未标定的电机转角", details={"angles": missing}, status_code=409)
    try:
        key = (database.path.parent / "motor-api.key").read_text(encoding="utf-8").strip()
        if len(key) < 32 or not key.isascii() or any(char.isspace() for char in key):
            raise ValueError("invalid local key")
    except (ValueError, OSError) as exc:
        raise DeviceError("motor_service_key_unavailable", "缺少本机电机服务凭据，请核对现场启动配置", status_code=409) from exc
    motor = MotorTurn(binding, key, {angle: mapping[angle] for angle in angles})
    if preflight:
        motor.preflight()
    return motor
