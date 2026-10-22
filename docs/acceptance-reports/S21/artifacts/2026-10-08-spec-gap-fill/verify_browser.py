import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

APP = Path(__file__).resolve().parents[3]
WORK = Path(__file__).parent
sys.path.insert(0, str(APP))
from tests.test_spec_gap_closure import _sample_chain
from tests.test_s09_result_migration import source_file

def seed(directory):
    directory.mkdir(parents=True)
    _, runtime, method, _, _, _, _ = _sample_chain(directory)
    runtime.methods_service().open(method['id'], 1)
    migration = runtime.result_migration_service()
    migration.commit(migration.stage(str(source_file('dat')), None)['id'], None)
    import sqlite3
    with runtime.database.read() as source, sqlite3.connect(directory / 'geospectrum.sqlite3') as target:
        source.backup(target)
    return directory

def port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]

if __name__ == '__main__':
    data = seed(WORK / ('browser-data-' + uuid.uuid4().hex[:8]))
    backend_port, frontend_port = port(), port()
    env = dict(os.environ)
    env.update(SPECTRUM_DATA_DIR=str(data), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
        VITE_API_TARGET=f'http://127.0.0.1:{backend_port}', QA_BROWSER_URL=f'http://127.0.0.1:{frontend_port}',
        PLAYWRIGHT_MODULE_PATH=r'C:\Users\Leo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright',
        QA_DESKTOP_OUTPUT=str(WORK / 'browser'), QA_DESKTOP_RESULT=str(WORK / 'browser-gap.json'))
    env.pop('QA_CDP', None)
    node = r'C:\Users\Leo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
    children = []
    with (WORK / 'gap-browser-services.log').open('w', encoding='utf-8') as log:
        try:
            children.append(subprocess.Popen([sys.executable, '-B', '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', str(backend_port), '--no-access-log'], cwd=APP, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW))
            children.append(subprocess.Popen([node, str(APP / 'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', str(frontend_port), '--strictPort'], cwd=APP / 'frontend', env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW))
            for url in (f'http://127.0.0.1:{backend_port}/health', env['QA_BROWSER_URL']):
                for _ in range(150):
                    if any(child.poll() is not None for child in children): raise RuntimeError('test service exited')
                    try:
                        urllib.request.urlopen(url, timeout=1).close()
                        break
                    except OSError: time.sleep(.1)
                else: raise RuntimeError('test service timeout')
            with (WORK / 'gap-browser.log').open('w', encoding='utf-8') as output:
                checked = subprocess.run([node, str(APP / 'tests/spec_gap_browser.mjs')], cwd=APP, env=env, stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW, timeout=240)
            if checked.returncode: raise RuntimeError((WORK / 'gap-browser.log').read_text('utf-8'))
            print((WORK / 'browser-gap.json').read_text('utf-8'))
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=15)
