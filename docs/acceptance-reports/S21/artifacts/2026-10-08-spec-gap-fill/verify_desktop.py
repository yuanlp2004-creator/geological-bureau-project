import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import urllib.request
import uuid
from verify_browser import seed, APP, WORK, port

EXE = Path(os.environ['QA_DESKTOP_EXE'])
data = seed(WORK / ('desktop-data-' + uuid.uuid4().hex[:8]))
debug_port = port()
env = dict(os.environ)
env.update(SPECTRUM_DATA_DIR=str(data), WEBVIEW2_USER_DATA_FOLDER=str(data / 'webview'),
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={debug_port}', QA_CDP=f'http://127.0.0.1:{debug_port}',
    PLAYWRIGHT_MODULE_PATH=r'C:\Users\Leo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright',
    QA_DESKTOP_OUTPUT=str(WORK / 'desktop'), QA_DESKTOP_RESULT=str(WORK / 'desktop-gap.json'))
node = r'C:\Users\Leo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
user32 = ctypes.WinDLL('user32', use_last_error=True)
CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [CALLBACK, wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
startup = subprocess.STARTUPINFO()
startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow = 0
process = subprocess.Popen([str(EXE)], cwd=EXE.parent, env=env, startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW)
stopped = threading.Event()
windows = set()
@CALLBACK
def find_window(hwnd, _):
    owner = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    if owner.value == process.pid:
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        if title.value.startswith('GeoSpectrum'):
            windows.add(hwnd)
            user32.ShowWindow(hwnd, 0)
    return True
def hide_owned():
    while not stopped.wait(.05): user32.EnumWindows(find_window, 0)
hider = threading.Thread(target=hide_owned, daemon=True)
hider.start()
result = {'status': 'failed', 'exe': str(EXE), 'pid': process.pid, 'isolated_identifier': 'cn.geospectrum.desktop.specgapqa'}
try:
    for _ in range(300):
        if process.poll() is not None: raise RuntimeError('isolated desktop exited early')
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{debug_port}/json/version', timeout=1).close()
            break
        except OSError: time.sleep(.1)
    else: raise RuntimeError('WebView debug endpoint unavailable')
    with (WORK / 'desktop-gap.log').open('w', encoding='utf-8') as log:
        checked = subprocess.run([node, str(APP / 'tests/spec_gap_browser.mjs')], cwd=APP, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW, timeout=240)
    if checked.returncode: raise RuntimeError((WORK / 'desktop-gap.log').read_text('utf-8'))
    result['status'] = 'passed'
finally:
    stopped.set()
    hider.join(timeout=2)
    user32.EnumWindows(find_window, 0)
    for hwnd in windows: user32.PostMessageW(hwnd, 0x0010, 0, 0)
    try: process.wait(timeout=25)
    except subprocess.TimeoutExpired:
        result['forced_stop'] = True
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)
        process.wait(timeout=10)
    result['returncode'] = process.returncode
    result['closed_normally'] = process.returncode == 0 and not result.get('forced_stop')
    command = "$p='" + str(EXE.parent).replace("'", "''") + "'; Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -like ($p+'\\*')} | Select-Object -ExpandProperty ProcessId"
    remaining = subprocess.run(['powershell', '-NoProfile', '-Command', command], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    result['remaining_owned_pids'] = [int(value) for value in remaining.stdout.split() if value.isdigit()]
    (WORK / 'desktop-process.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    if not result['closed_normally'] or result['remaining_owned_pids']: raise RuntimeError('desktop failed to exit cleanly')
