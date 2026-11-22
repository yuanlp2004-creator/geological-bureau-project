"""Read Windows COM metadata without opening ports or probing instruments."""
from __future__ import annotations

import re
from typing import Any

from serial.tools import list_ports

from .values import DeviceError


def available_serial_ports() -> list[dict[str, Any]]:
    try:
        result = {}
        for info in list_ports.comports():
            match = re.fullmatch(r"COM([1-9]\d*)", info.device, re.IGNORECASE)
            if not match or not 1 <= int(match[1]) <= 256:
                continue
            number = int(match[1])
            description = info.description or f"COM{number}"
            evidence = f"{info.hwid or ''} {description} {info.manufacturer or ''}".casefold()
            is_bluetooth = any(marker in evidence for marker in ('bthenum', 'bthmodem', 'bluetooth', '蓝牙'))
            # Windows BTHENUM SPP instance IDs include the remote address.
            # The all-zero instance is a local incoming port, not a device.
            address = re.search(r'&([0-9a-f]{12})_[0-9a-f]+$', str(info.hwid or ''), re.IGNORECASE) if is_bluetooth else None
            remote = address[1].upper() if address and address[1] != '000000000000' else None
            result[number] = {"device": f"COM{number}", "port": number, "description": description,
                              "is_bluetooth": is_bluetooth, 'bluetooth_address': remote,
                              'direction': ('outgoing' if remote else 'incoming' if address else None)}
        return [result[number] for number in sorted(result)]
    except (OSError, ValueError) as exc:
        raise DeviceError("serial_ports_unavailable", "无法读取系统串口，请检查 Windows 设备管理器后重试",
                          status_code=503) from exc


def bluetooth_connections() -> dict[str, Any]:
    from .bluetooth import windows_bluetooth_devices
    ports = available_serial_ports()
    return {'devices': [{**device, 'ports': [port for port in ports if port['bluetooth_address'] == device['address']]}
                        for device in windows_bluetooth_devices()]}


def validate_bluetooth_binding(address: str, port: int) -> None:
    selected = next((device for device in bluetooth_connections()['devices'] if device['address'] == address.upper()), None)
    if not selected or not any(item['port'] == port for item in selected['ports']):
        raise DeviceError('bluetooth_port_mismatch', 'Windows未将此COM口分配给所选蓝牙设备，请刷新设备或在Windows蓝牙设置中添加串口',
                          status_code=409)
