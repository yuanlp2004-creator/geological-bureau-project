"""Windows DEVMODE, Unicode driver capabilities and GDI document lifecycle."""
from __future__ import annotations

import ctypes
from contextlib import contextmanager
from pathlib import Path

from . import PrintCancelled
from .paper import paper_code, paper_id


def printer_papers(name: str) -> list[dict]:
    with _printer(name) as (handle, info):
        capability = ctypes.WinDLL('winspool.drv').DeviceCapabilitiesW
        capability.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ushort, ctypes.c_void_p, ctypes.c_void_p]
        capability.restype = ctypes.c_int
        count = capability(name, info['pPortName'], 2, None, None)
        if count <= 0:
            raise RuntimeError('打印机驱动未提供纸张列表')
        ids = (ctypes.c_ushort * count)()
        sizes = (ctypes.c_long * (count * 2))()
        names = ctypes.create_unicode_buffer(count * 64)
        for kind, buffer in ((2, ids), (3, sizes), (16, names)):
            if capability(name, info['pPortName'], kind, buffer, None) != count:
                raise RuntimeError('读取打印机纸张列表失败，请刷新后重试')
        return [{'code': paper_code(ids[i], sizes[2*i], sizes[2*i+1]),
                 'display_name': names[i*64:(i+1)*64].split('\0')[0].strip(),
                 'paper_id': ids[i], 'width_mm': sizes[2*i]/10, 'height_mm': sizes[2*i+1]/10}
                for i in range(count) if sizes[2*i] > 0 and sizes[2*i+1] > 0]


@contextmanager
def _printer(name):
    import win32print
    handle = win32print.OpenPrinter(name)
    try:
        yield handle, win32print.GetPrinter(handle, 2)
    finally:
        win32print.ClosePrinter(handle)


@contextmanager
def printer_dc(name: str, settings: dict):
    import win32con
    import win32gui
    import win32print
    import win32ui
    selected = settings.get('paper', 'A4')
    if selected not in {p['code'] for p in printer_papers(name)}:
        raise ValueError('所选纸张不受当前打印机支持，请重新选择纸张')
    with _printer(name) as (handle, info):
        mode = info['pDevMode']
        mode.PaperSize = paper_id(selected)
        mode.Orientation = 2 if settings.get('orientation') == 'landscape' else 1
        mode.Copies = settings.get('copies', 1)
        mode.Duplex = {'none': 1, 'long_edge': 2, 'short_edge': 3}[settings.get('duplex', 'none')]
        mode.Color = 2 if settings.get('color') else 1
        mode.Fields |= (win32con.DM_PAPERSIZE | win32con.DM_ORIENTATION | win32con.DM_COPIES |
                        win32con.DM_DUPLEX | win32con.DM_COLOR)
        if win32print.DocumentProperties(0, handle, name, mode, mode, 10) != 1:
            raise RuntimeError('打印机驱动拒绝页面设置')
        if mode.PaperSize != paper_id(selected) or mode.Orientation != (2 if settings.get('orientation') == 'landscape' else 1):
            raise ValueError('打印机驱动不接受所选纸张或方向')
        dc = win32ui.CreateDCFromHandle(win32gui.CreateDC('WINSPOOL', name, mode))
        try:
            yield dc, mode, info
        finally:
            dc.DeleteDC()


def printer_connection(name: str, settings: dict) -> dict:
    import win32con
    with printer_dc(name, settings) as (dc, mode, info):
        return {'connected': True, 'printer_name': name, 'driver': info['pDriverName'],
                'paper_id': mode.PaperSize, 'orientation': mode.Orientation,
                'dpi': [dc.GetDeviceCaps(win32con.LOGPIXELSX), dc.GetDeviceCaps(win32con.LOGPIXELSY)],
                'printable_pixels': [dc.GetDeviceCaps(win32con.HORZRES), dc.GetDeviceCaps(win32con.VERTRES)],
                'submitted': False}


def print_pdf(path: Path, name: str, settings: dict) -> dict:
    import pypdfium2 as pdfium
    from PIL import ImageWin

    with pdfium.PdfDocument(str(path)) as document:
        if not len(document):
            raise ValueError('打印文档没有页面')
        if not settings:
            first = document[0]
            try:
                width, height = first.get_size()
            finally:
                first.close()
            match = next((p for p in printer_papers(name) if abs(p['width_mm']-min(width,height)*25.4/72)<1 and
                          abs(p['height_mm']-max(width,height)*25.4/72)<1), None)
            if not match:
                raise ValueError('打印机没有与文档尺寸一致的纸张')
            settings = {'paper': match['code'], 'orientation': 'landscape' if width>height else 'portrait'}
        with printer_dc(name, settings) as (dc, mode, info):
            output_path = None
            if info['pDriverName'].lower() == 'microsoft print to pdf':
                # Choose the path explicitly: the driver's own PORTPROMPT dialog can
                # stay hidden when called by a background desktop sidecar.
                import win32con
                import win32ui
                dialog = win32ui.CreateFileDialog(False, 'pdf', path.stem+'.pdf',
                    win32con.OFN_OVERWRITEPROMPT | win32con.OFN_PATHMUSTEXIST | win32con.OFN_NOCHANGEDIR,
                    'PDF 文件 (*.pdf)|*.pdf||')
                dialog.SetOFNTitle('将打印输出另存为 — Microsoft Print to PDF')
                if dialog.DoModal() != 1:
                    raise PrintCancelled('已取消 Windows 打印')
                output_path = dialog.GetPathName()
            class DocInfo(ctypes.Structure):
                _fields_ = [('cbSize', ctypes.c_int), ('lpszDocName', ctypes.c_wchar_p),
                            ('lpszOutput', ctypes.c_wchar_p), ('lpszDatatype', ctypes.c_wchar_p),
                            ('fwType', ctypes.c_ulong)]
            gdi = ctypes.WinDLL('gdi32', use_last_error=True)
            gdi.StartDocW.argtypes = [ctypes.c_void_p, ctypes.POINTER(DocInfo)]
            gdi.StartDocW.restype = ctypes.c_int
            detail = DocInfo(ctypes.sizeof(DocInfo), 'GeoSpectrum - '+path.stem, output_path, None, 0)
            ctypes.set_last_error(0)
            job = gdi.StartDocW(dc.GetSafeHdc(), ctypes.byref(detail))
            if job <= 0:
                error = ctypes.get_last_error()
                if error == 1223:
                    raise PrintCancelled('已取消 Windows 打印')
                raise ctypes.WinError(error)
            try:
                dpi_x, dpi_y = dc.GetDeviceCaps(88), dc.GetDeviceCaps(90)
                physical_w, physical_h = dc.GetDeviceCaps(110), dc.GetDeviceCaps(111)
                offset_x, offset_y = dc.GetDeviceCaps(112), dc.GetDeviceCaps(113)
                for page in document:
                    try:
                        bitmap = page.render(scale=min(200, dpi_x, dpi_y)/72)
                        try:
                            image = bitmap.to_pil().convert('RGB')
                            try:
                                dc.StartPage()
                                ImageWin.Dib(image).draw(dc.GetSafeHdc(), (-offset_x, -offset_y,
                                    physical_w-offset_x, physical_h-offset_y))
                                dc.EndPage()
                            finally:
                                image.close()
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
                dc.EndDoc()
            except BaseException:
                dc.AbortDoc()
                raise
            return {'status': 'queued', 'spool_job_id': job, 'printer_name': name}
