from __future__ import annotations

from typing import Any
from .serial_acq import SerialAcqAdapter
from .simulator import AcqSimulatorAdapter


def create_device_adapter(profile: dict[str, Any], *, exit_gate=None,
                          on_serial_notice=None) -> AcqSimulatorAdapter | SerialAcqAdapter:
    if profile["transport"] == "serial":
        return SerialAcqAdapter(exit_gate=exit_gate, on_notice=on_serial_notice)
    return AcqSimulatorAdapter()
