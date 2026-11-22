"""Read Classic Bluetooth device state from Windows, without inquiry or pairing."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
from typing import Any

from .values import DeviceError


class SystemTime(ctypes.Structure):
    _fields_ = [(name, wintypes.WORD) for name in
                ('year', 'month', 'weekday', 'day', 'hour', 'minute', 'second', 'milliseconds')]


class BluetoothDeviceInfo(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('address', ctypes.c_ulonglong),
                ('device_class', wintypes.ULONG), ('connected', wintypes.BOOL),
                ('remembered', wintypes.BOOL), ('authenticated', wintypes.BOOL),
                ('last_seen', SystemTime), ('last_used', SystemTime), ('name', wintypes.WCHAR * 248)]


class BluetoothSearchParams(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('authenticated', wintypes.BOOL),
                ('remembered', wintypes.BOOL), ('unknown', wintypes.BOOL), ('connected', wintypes.BOOL),
                ('inquiry', wintypes.BOOL), ('timeout', ctypes.c_ubyte), ('radio', wintypes.HANDLE)]


def windows_bluetooth_devices() -> list[dict[str, Any]]:
    if sys.platform != 'win32':
        raise DeviceError('bluetooth_windows_required', '蓝牙设备列表需要 Windows 系统', status_code=409)
    try:
        api = ctypes.WinDLL('bthprops.cpl', use_last_error=True)
        api.BluetoothFindFirstDevice.argtypes = [ctypes.POINTER(BluetoothSearchParams), ctypes.POINTER(BluetoothDeviceInfo)]
        api.BluetoothFindFirstDevice.restype = wintypes.HANDLE
        api.BluetoothFindNextDevice.argtypes = [wintypes.HANDLE, ctypes.POINTER(BluetoothDeviceInfo)]
        api.BluetoothFindNextDevice.restype = wintypes.BOOL
        api.BluetoothFindDeviceClose.argtypes = [wintypes.HANDLE]
        api.BluetoothFindDeviceClose.restype = wintypes.BOOL
        params = BluetoothSearchParams()
        params.size = ctypes.sizeof(params)
        params.authenticated = params.remembered = params.connected = True
        # Never scan the radio, pair, connect, or change Windows configuration.
        params.inquiry = False
        info = BluetoothDeviceInfo()
        info.size = ctypes.sizeof(info)
        handle = api.BluetoothFindFirstDevice(ctypes.byref(params), ctypes.byref(info))
        if not handle:
            error = ctypes.get_last_error()
            if error in (0, 259, 1168):
                return []
            raise OSError(error, 'BluetoothFindFirstDevice')
        devices = {}
        try:
            while True:
                address = f'{info.address:012X}'
                if info.connected or info.authenticated or info.remembered:
                    devices[address] = {'address': address, 'name': info.name or '未命名蓝牙设备',
                                        'connected': bool(info.connected), 'paired': bool(info.authenticated)}
                info = BluetoothDeviceInfo()
                info.size = ctypes.sizeof(info)
                if not api.BluetoothFindNextDevice(handle, ctypes.byref(info)):
                    error = ctypes.get_last_error()
                    if error not in (0, 259):
                        raise OSError(error, 'BluetoothFindNextDevice')
                    break
        finally:
            api.BluetoothFindDeviceClose(handle)
        return sorted(devices.values(), key=lambda item: (not item['connected'], item['name'].casefold(), item['address']))
    except OSError as exc:
        raise DeviceError('bluetooth_devices_unavailable', '无法读取 Windows 蓝牙设备，请检查蓝牙开关和适配器后重试',
                          status_code=503) from exc
