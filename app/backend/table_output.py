"""Shared paginated table output, independent of business repositories."""
from __future__ import annotations
import html
import io
from pathlib import Path
from uuid import uuid4
from reportlab.lib.pagesizes import A4,A3,LETTER,landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Paragraph,PageBreak
from .printing import SystemPrinters,PrintCancelled
from .printing.paper import paper_mm


def table_excel(table: list[list], worksheet='Report') -> bytes:
    """SpreadsheetML, shared by reports and intensity tables; strings stay strings."""
    escape = lambda value: html.escape('' if value is None else str(value), quote=True)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<?mso-application progid="Excel.Sheet"?>',
             '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="'+escape(worksheet)+'"><Table>']
    for row in table:
        parts.append('<Row>'+''.join('<Cell><Data ss:Type="'+('Number' if isinstance(value,(int,float)) and not isinstance(value,bool) else 'String')+'">'+escape(value)+'</Data></Cell>' for value in row)+'</Row>')
    return ''.join([*parts,'</Table></Worksheet></Workbook>']).encode('utf-8')


def table_pdf(table: list[list], title: str, settings: dict, note='') -> bytes:
    output=io.BytesIO();paper=tuple(value*mm for value in paper_mm(settings.get('paper','A4')))
    size=landscape(paper) if settings.get('orientation')=='landscape' else paper
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    style=ParagraphStyle('table',fontName='STSong-Light',fontSize=settings.get('font_size_pt',9),leading=settings.get('font_size_pt',9)*1.4,wordWrap='CJK')
    doc=SimpleDocTemplate(output,pagesize=size,leftMargin=12*mm,rightMargin=12*mm,topMargin=12*mm,bottomMargin=12*mm,invariant=1)
    story=[];count=max(1,int(settings.get('elements_per_line',15)))
    minimum=max(12*mm,float(settings.get('font_size_pt',9))*2.5+2*mm)
    count=min(count,max(1,int((size[0]-24*mm)/minimum)-1))
    for start in range(1,len(table[0]),count):
        if story:story.append(PageBreak())
        story.extend([Paragraph(html.escape(title),style),Paragraph(html.escape(note),style)])
        rows=[[row[0],*row[start:start+count]] for row in table]
        rendered=Table([[Paragraph(html.escape(str(value if value is not None else '')),style) for value in row] for row in rows],colWidths=[(size[0]-24*mm)/len(rows[0])]*len(rows[0]),repeatRows=1)
        rendered.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),.3,'#aab8c0')]))
        story.append(rendered)
    doc.build(story)
    return output.getvalue()


def dispatch_table(content: bytes, data_dir: Path, printer_name: str) -> dict:
    backend=SystemPrinters()
    if printer_name in {"system", "geospectrum-pdf"}:printer_name=backend.default_printer()
    if printer_name not in {p['name'] for p in backend.printers()}:
        raise ValueError('选择的打印机不存在')
    identifier='intensity-'+uuid4().hex
    folder=data_dir/'print-jobs'/identifier;folder.mkdir(parents=True)
    path=folder/'intensity.pdf';path.write_bytes(content)
    try:
        backend.dispatch_pdf(path,printer_name)
        status='queued'
    except PrintCancelled:
        status='cancelled'
    return {'id':identifier,'path':str(path),'status':status,'printer':printer_name}
