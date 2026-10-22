from ...printing.paper import paper_mm, paper_css
import html
import csv
import io
from typing import Any
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


def _xml(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _headers(model: dict[str, Any]) -> list[str]:
    labels = {
        "report_number": "报告编号",
        "sample_name": "样品名称",
        "element": "元素",
        "wavelength_nm": "波长 (nm)",
        "calculated_value": "分析结果",
        "unit": "单位",
        "curve_snapshot_id": "曲线快照",
        "calculation_profile": "计算档案",
        "qc_status": "质控状态",
    }
    return [labels[key] for key in model["columns"]]


def _table(model: dict[str, Any]) -> list[list[Any]]:
    if model.get('table_layout') != 'legacy_matrix':
        keys = model['columns']
        return [_headers(model)] + [[row.get('display_value',row.get(key)) if key=='calculated_value' else row.get(key) for key in keys] for row in model['rows']]
    samples, elements, cells = {}, {}, {}
    for row in model['rows']:
        sample=(row.get('analysis_run_id',row.get('legacy_result_id')),row.get('sample_id',row.get('sample_index',row['sample_name'])),row['sample_name'])
        element=(row['element'],row.get('wavelength_nm'),row.get('unit',''))
        samples.setdefault(sample,row['sample_name'])
        label=str(row['element'])+(f" {row['wavelength_nm']:g} nm" if row.get('wavelength_nm') else '')+(f" ({row['unit']})" if row.get('unit') else '')
        elements.setdefault(element,label)
        value=row.get('display_value',row.get('calculated_value'))
        if (sample,element) in cells:
            raise ValueError('报告矩阵存在重复样品/元素值，请使用明细长表核对')
        cells[sample,element]=value
    table=[['样品号',*elements.values()]]+[[name,*[cells.get((sample,element),'') for element in elements]] for sample,name in samples.items()]
    return [list(row) for row in zip(*table)] if model.get('arrangement')=='exchange' else table


def _encode_table(table: list[list[Any]], fmt: str) -> tuple[bytes, str, str]:
    if fmt in {"txt", "csv"}:
        stream = io.StringIO(newline="")
        csv.writer(stream, delimiter="\t" if fmt == "txt" else ",", lineterminator="\n").writerows(table)
        return (
            ("\ufeff" + stream.getvalue()).encode("utf-8"),
            ("text/plain; charset=utf-8" if fmt == "txt" else "text/csv; charset=utf-8"),
            (".txt" if fmt == "txt" else ".csv"),
        )
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<?mso-application progid="Excel.Sheet"?>',
        (
            '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
            'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet '
            'ss:Name="Report"><Table>'
        ),
    ]
    for row in table:
        parts.append(
            "<Row>"
            + "".join(
                f'<Cell><Data ss:Type="{"Number" if isinstance(value, (int, float)) and not isinstance(value, bool) else "String"}">{_xml(value)}</Data></Cell>'
                for value in row
            )
            + "</Row>"
        )
    parts.append("</Table></Worksheet></Workbook>")
    return "".join(parts).encode("utf-8"), "application/vnd.ms-excel", ".xls"


def _page_tables(report: dict[str, Any]) -> list[list[list[Any]]]:
    table=_table(report['model'])
    printing=report.get('printing',{})
    rows=max(1,int(printing.get('samples_per_page',50)))
    cols=max(1,int(printing.get('elements_per_line',15)))
    if report['model'].get('table_layout')!='legacy_matrix':
        return [[table[0],*table[offset:offset+rows]] for offset in range(1,len(table),rows)] or [table]
    if report.get('arrangement')=='exchange':rows,cols=cols,rows
    # Exchange matrices can have hundreds of sample columns. Paginate horizontally
    # instead of squeezing cells below the font/padding width and losing output.
    paper=paper_mm(printing.get('paper','A4'))
    width=paper[1] if printing.get('orientation','portrait')=='landscape' else paper[0]
    width-=float(printing.get('margin_left_mm',12))+float(printing.get('margin_right_mm',12))
    minimum=max(12,float(printing.get('font_size_pt',9))*25.4/72*2.5+2)
    cols=min(cols,max(1,int((width-min(35,width/3))/minimum)))
    return [[[table[0][0],*table[0][column:column+cols]],
             *[[row[0],*row[column:column+cols]] for row in table[offset:offset+rows]]]
            for column in range(1,len(table[0]),cols) for offset in range(1,len(table),rows)] or [table]


def _report_time(report: dict[str, Any]) -> str:
    if report.get('printing',{}).get('time_mode','analysis')=='system':
        return '系统时间：'+str(report.get('printed_at',''))
    return '分析时间：'+(' / '.join(str(value) for value in report['model'].get('analysis_times',[]) if value) or '未记录')


def _pdf(report: dict[str, Any]) -> tuple[bytes, int]:
    from reportlab.lib.pagesizes import A3, LETTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Paragraph,PageBreak,Spacer
    output=io.BytesIO(); printing=report.get('printing',{})
    paper=tuple(value*mm for value in paper_mm(printing.get('paper','A4')))
    size=landscape(paper) if printing.get('orientation','portrait')=='landscape' else paper
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'));font='STSong-Light'
    except Exception:font='Helvetica'
    fontsize=int(printing.get('font_size_pt',9))
    margins=[float(printing.get('margin_'+side+'_mm',12))*mm for side in ('left','right','top','bottom')]
    document=SimpleDocTemplate(output,pagesize=size,leftMargin=margins[0],rightMargin=margins[1],topMargin=margins[2]+12*mm,bottomMargin=margins[3]+8*mm,invariant=1)
    body=ParagraphStyle('body',fontName=font,fontSize=fontsize,leading=fontsize*1.35,wordWrap='CJK')
    count=0
    def decorate(pdf,doc):
        nonlocal count
        count+=1;pdf.setFont(font,fontsize+3)
        pdf.drawString(margins[0],size[1]-margins[2]-5*mm,f"分析报告 {report['report_number']} v{report['version']}")
        pdf.setFont(font,fontsize)
        pdf.drawString(margins[0],size[1]-margins[2]-11*mm,_report_time(report))
        pdf.setFont(font,7)
        pdf.drawString(margins[0],margins[3],f"GeoSpectrum · 第{count}页 · SHA-256 {report['model_sha256']}")
    story=[]
    for index,rows in enumerate(_page_tables(report)):
        if index:story.append(PageBreak())
        if report['model'].get('provenance_note'):story.extend([Paragraph(_xml(report['model']['provenance_note']),body),Spacer(1,4*mm)])
        values=[[Paragraph(_xml(value),body) for value in row] for row in rows]
        width=size[0]-margins[0]-margins[1]
        first=min(35*mm,width/3);columns=[first]+[(width-first)/max(1,len(rows[0])-1)]*(len(rows[0])-1)
        table=Table(values,colWidths=columns,repeatRows=1,hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf1f3')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#dfe7eb')),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
        story.append(table)
    sources=report['model'].get('legacy_sources',[])
    if sources:
        story.extend([PageBreak(),Paragraph('旧 DAT 来源记录',body)])
        for source in sources:story.append(Paragraph(_xml(f"DAT #{source['id']} · SHA-256 {source['source_sha256']}"),body))
    runs=report['model'].get('runs',[])
    if runs:
        story.append(Spacer(1,4*mm))
        for run in runs:story.append(Paragraph(_xml(f"方法 {run.get('method_name','')} v{run.get('method_version','')} · 计算档案 {run.get('calculation_profile','')} · 运行 #{run.get('id','')}"),body))
    document.build(story,onFirstPage=decorate,onLaterPages=decorate)
    return output.getvalue(),count


def render_html(report: dict[str, Any]) -> str:
    printing=report.get('printing',{});font=int(printing.get('font_size_pt',9))
    tables=[]
    for rows in _page_tables(report):
        tables.append('<section><table><thead><tr>'+''.join('<th>'+_xml(value)+'</th>' for value in rows[0])+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+_xml(value)+'</td>' for value in row)+'</tr>' for row in rows[1:])+'</tbody></table></section>')
    sources=''.join('<li>'+_xml(f"DAT #{source['id']} · SHA-256 {source['source_sha256']}")+'</li>' for source in report['model'].get('legacy_sources',[]))
    provenance=_xml(report['model'].get('provenance_note',''))
    runs=''.join('<p>'+_xml(f"方法 {run.get('method_name','')} v{run.get('method_version','')} · {run.get('calculation_profile','')} · 运行 #{run.get('id','')}")+'</p>' for run in report['model'].get('runs',[]))
    margins=' '.join(str(printing.get('margin_'+side+'_mm',12))+'mm' for side in ('top','right','bottom','left'))
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>{_xml(report['report_number'])}</title>
<style>@page{{size:{paper_css(printing.get('paper','A4'), printing.get('orientation','portrait'))};margin:{margins}}}
body{{font-family:'Microsoft YaHei',sans-serif;color:#263d4d;font-size:{font}pt}}table{{width:100%;border-collapse:collapse;table-layout:fixed}}th,td{{border-bottom:1px solid #dfe7eb;padding:5px;overflow-wrap:anywhere}}th{{background:#eaf1f3}}thead{{display:table-header-group}}section+section{{break-before:page}}</style></head>
<body><h1>分析报告 {_xml(report['report_number'])} v{report['version']}</h1><p>{_xml(_report_time(report))}</p><small>SHA-256 {_xml(report['model_sha256'])}</small><p>{provenance}</p>{''.join(tables)}{runs}{'<h2>旧 DAT 来源</h2><ul>'+sources+'</ul>' if sources else ''}</body></html>"""
