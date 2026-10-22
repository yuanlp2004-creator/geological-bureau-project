"""Real PDF rasterization with a fake GDI device: never submit to Windows."""
import ctypes
from contextlib import contextmanager

import pytest
from reportlab.pdfgen.canvas import Canvas

from backend.printing import PrintCancelled, SystemPrinters
from backend.printing import windows


@pytest.mark.parametrize('failure', [None, 'draw', 'cancel', 'cancel-save'])
def test_gdi_submission_cleanup_and_cancel(tmp_path, monkeypatch, failure):
    path = tmp_path/'document.pdf'
    pdf = Canvas(str(path))
    pdf.drawString(30, 30, 'print pipeline')
    pdf.showPage()
    pdf.save()
    calls = []
    class Device:
        def GetSafeHdc(self): return 1
        def GetDeviceCaps(self, index):
            return {88:600, 90:600, 110:4961, 111:7016, 112:0, 113:0}[index]
        def StartPage(self): calls.append('start-page')
        def EndPage(self): calls.append('end-page')
        def EndDoc(self): calls.append('end-doc')
        def AbortDoc(self): calls.append('abort-doc')
    @contextmanager
    def device(*args):
        try: yield Device(), None, {'pDriverName':'Microsoft Print To PDF' if failure == 'cancel-save' else 'test'}
        finally: calls.append('delete-dc')
    monkeypatch.setattr(windows, 'printer_dc', device)
    if failure == 'cancel-save':
        import win32ui
        class SaveDialog:
            def SetOFNTitle(self, title): assert 'Microsoft Print to PDF' in title
            def DoModal(self): return 2
        monkeypatch.setattr(win32ui, 'CreateFileDialog', lambda *args: SaveDialog())
    class Start:
        def __call__(self, *args):
            calls.append('start-doc')
            if failure == 'cancel':
                ctypes.set_last_error(1223)
                return -1
            return 7
    class Gdi:
        StartDocW = Start()
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *args,**kwargs:Gdi())
    from PIL import ImageWin
    class Dib:
        def __init__(self, image): assert image.width > 100
        def draw(self, *args):
            calls.append('draw')
            if failure == 'draw': raise RuntimeError('driver drawing failed')
    monkeypatch.setattr(ImageWin, 'Dib', Dib)
    if failure:
        with pytest.raises(PrintCancelled if failure in {'cancel', 'cancel-save'} else RuntimeError):
            windows.print_pdf(path, 'test', {'paper':'A4'})
        assert 'end-doc' not in calls
        assert ('abort-doc' in calls) == (failure == 'draw')
        assert ('start-doc' in calls) == (failure != 'cancel-save')
    else:
        result = windows.print_pdf(path, 'test', {'paper':'A4'})
        assert result['spool_job_id'] == 7 and result['status'] == 'queued'
        assert calls[:-1] == ['start-doc','start-page','draw','end-page','end-doc']
    assert calls[-1] == 'delete-dc'


def test_missing_windows_printer_has_no_virtual_fallback(monkeypatch):
    monkeypatch.setattr(SystemPrinters, '_system_printers', staticmethod(lambda: []))
    assert SystemPrinters().printers() == []
    assert SystemPrinters().default_printer() == 'system'
