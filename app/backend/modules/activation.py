"""Offline, installation-scoped authorization for starting new operations."""
from __future__ import annotations

import base64
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

MAX_LICENSE_BYTES = 4096
SIGNATURE_CONTEXT = b"GeoSpectrum activation v1\0"


class ActivationClaims(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    product: Literal["GeoSpectrum"] = "GeoSpectrum"
    installation_id: UUID
    expires_at: AwareDatetime


class SignedActivation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: str = Field(min_length=1, max_length=2048)
    signature: str = Field(min_length=88, max_length=88)


class ActivationStatus(BaseModel):
    state: Literal["unmanaged", "pending", "active", "expired", "invalid", "configuration_error"]
    installation_id: UUID | None = None
    expires_at: AwareDatetime | None = None


class ActivationError(ValueError):
    pass


def _read_bounded(path: Path) -> bytes:
    with path.open("rb") as stream:
        result = stream.read(MAX_LICENSE_BYTES + 1)
    if len(result) > MAX_LICENSE_BYTES:
        raise ActivationError("授权文件过大")
    return result


def _replace_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file = tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False)
    temporary = Path(file.name)
    try:
        with file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ActivationService:
    def __init__(self, data_dir: Path, public_key: str):
        self._identity = data_dir / "activation-installation.id"
        self._license = data_dir / "activation.json"
        self.managed = bool(public_key) or self._identity.exists() or self._license.exists()
        self._public_key: Ed25519PublicKey | None = None
        if public_key:
            try:
                self._public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
            except ValueError:
                pass
        self._lock = RLock()

    def _installation_id(self, *, create: bool = False) -> UUID | None:
        try:
            return UUID(_read_bounded(self._identity).decode("ascii"))
        except FileNotFoundError:
            if create and not self._license.exists():
                identifier = uuid4()
                _replace_bytes(self._identity, str(identifier).encode("ascii"))
                return identifier
            return None

    def _verified_claims(self, raw: bytes, installation_id: UUID) -> ActivationClaims:
        if len(raw) > MAX_LICENSE_BYTES:
            raise ActivationError("授权文件过大")
        if self._public_key is None:
            raise ActivationError("当前部署未配置有效的激活验签公钥")
        try:
            signed = SignedActivation.model_validate_json(raw)
            payload = base64.b64decode(signed.payload, validate=True)
            signature = base64.b64decode(signed.signature, validate=True)
            self._public_key.verify(signature, SIGNATURE_CONTEXT + payload)
            claims = ActivationClaims.model_validate_json(payload)
            if not {"version", "product"} <= claims.model_fields_set:
                raise ValueError("missing format fields")
            expires_at = claims.expires_at.astimezone(timezone.utc)
        except (InvalidSignature, ValueError, OverflowError) as exc:
            raise ActivationError("授权文件格式或签名无效") from exc
        if claims.installation_id != installation_id:
            raise ActivationError("授权文件与当前安装标识不匹配")
        return claims.model_copy(update={"expires_at": expires_at})

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def status(self, *, initialize: bool = False) -> ActivationStatus:
        if not self.managed:
            return ActivationStatus(state="unmanaged")
        if self._public_key is None:
            return ActivationStatus(state="configuration_error")
        with self._lock:
            installation_id = None
            try:
                installation_id = self._installation_id(create=initialize)
                raw = _read_bounded(self._license)
            except FileNotFoundError:
                return ActivationStatus(state="pending", installation_id=installation_id)
            except (OSError, ValueError):
                return ActivationStatus(state="invalid")
            if installation_id is None:
                return ActivationStatus(state="invalid")
            try:
                claims = self._verified_claims(raw, installation_id)
            except ActivationError:
                return ActivationStatus(state="invalid", installation_id=installation_id)
            state = "active" if self._now() < claims.expires_at else "expired"
            return ActivationStatus(state=state, installation_id=installation_id, expires_at=claims.expires_at)

    def install(self, raw: bytes) -> tuple[ActivationStatus, bool]:
        if self._public_key is None:
            raise ActivationError("当前部署未配置有效的激活验签公钥")
        with self._lock:
            installation_id = self._installation_id()
            if installation_id is None:
                raise ActivationError("安装标识不可用，请刷新软件激活状态")
            claims = self._verified_claims(raw, installation_id)
            if claims.expires_at <= self._now():
                raise ActivationError("授权文件已过期")
            current = self.status()
            if current.expires_at and claims.expires_at < current.expires_at:
                raise ActivationError("续期文件的到期时间早于当前授权")
            if current.expires_at == claims.expires_at:
                return current, False
            _replace_bytes(self._license, raw)
            return self.status(), True


def encode_signed_activation(claims: ActivationClaims, sign) -> str:
    payload = claims.model_dump_json().encode("utf-8")
    return json.dumps({
        "payload": base64.b64encode(payload).decode("ascii"),
        "signature": base64.b64encode(sign(SIGNATURE_CONTEXT + payload)).decode("ascii"),
    })
