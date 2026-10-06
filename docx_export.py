"""把单词清单导出成 Word（.docx）：一列英文、一列中文。

只依赖标准库（zipfile + 手写 OOXML），这样部署环境不用新增依赖。
"""

import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PAGE_WIDTH = 9360      # A4 正文可用宽度（twips）
COL_EN = 3600
COL_ZH = PAGE_WIDTH - COL_EN

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

PACKAGE_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:styles xmlns:w="{W}">'
    "<w:docDefaults><w:rPrDefault><w:rPr>"
    '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="SimSun" w:cs="Calibri"/>'
    '<w:sz w:val="22"/>'
    "</w:rPr></w:rPrDefault><w:pPrDefault/></w:docDefaults>"
    f'<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/></w:style>'
    "</w:styles>"
)

BORDER = (
    '<w:tblBorders>'
    '<w:top w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
    '<w:left w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
    '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
    '<w:right w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
    '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
    '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
    "</w:tblBorders>"
)


def _run(text, size=None, bold=False, color=None):
    props = ""
    if bold:
        props += "<w:b/>"
    if size:
        props += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    if color:
        props += f'<w:color w:val="{color}"/>'
    props = f"<w:rPr>{props}</w:rPr>" if props else ""
    # 保留空格，避免连续空格在 Word 里被折叠
    return f'<w:r>{props}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _cell(width, paragraphs, shading=None):
    props = f'<w:tcW w:w="{width}" w:type="dxa"/>'
    if shading:
        props += f'<w:shd w:val="clear" w:color="auto" w:fill="{shading}"/>'
    body = "".join(f'<w:p><w:pPr><w:spacing w:after="40"/></w:pPr>{runs}</w:p>' for runs in paragraphs)
    return f"<w:tc><w:tcPr>{props}</w:tcPr>{body}</w:tc>"


def build_vocab_docx(rows, phonetic=True, title="雅思单词记录本"):
    """rows: [{'word':..., 'phonetic':..., 'zh':...}]，返回 .docx 文件字节。"""
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    header = (
        _cell(COL_EN, [_run("英文", bold=True, size=20)], shading="F2F2F2"),
        _cell(COL_ZH, [_run("中文", bold=True, size=20)], shading="F2F2F2"),
    )
    body_rows = []
    for row in rows:
        word = str(row.get("word") or "").strip()
        zh = str(row.get("zh") or "").strip() or "暂无释义"
        english = [_run(word, size=22)]
        ph = str(row.get("phonetic") or "").strip()
        if phonetic and ph:
            english.append(_run(ph, size=18, color="808080"))
        body_rows.append(
            f'<w:tr><w:trPr><w:cantSplit/></w:trPr>'
            f"{_cell(COL_EN, english)}{_cell(COL_ZH, [_run(zh, size=22)])}</w:tr>"
        )
    if not body_rows:
        body_rows.append(
            f'<w:tr>{_cell(PAGE_WIDTH, [_run("没有可导出的单词", size=22, color="808080")])}</w:tr>'
        )
    table = (
        '<w:tbl><w:tblPr>'
        f'<w:tblW w:w="{PAGE_WIDTH}" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/>'
        f"{BORDER}"
        "</w:tblPr>"
        f'<w:tblGrid><w:gridCol w:w="{COL_EN}"/><w:gridCol w:w="{COL_ZH}"/></w:tblGrid>'
        f'<w:tr><w:trPr><w:tblHeader/></w:trPr>{"".join(header)}</w:tr>'
        f'{"".join(body_rows)}'
        "</w:tbl>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>'
        f'<w:p><w:pPr><w:spacing w:after="120"/></w:pPr>{_run(title, size=32, bold=True)}</w:p>'
        f'<w:p><w:pPr><w:spacing w:after="200"/></w:pPr>'
        f'{_run(f"共 {len(rows)} 个单词 · 导出于 {stamp}", size=18, color="808080")}</w:p>'
        f"{table}"
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
        "</w:body></w:document>"
    )
    return _zip({"[Content_Types].xml": CONTENT_TYPES,
                 "_rels/.rels": PACKAGE_RELS,
                 "word/document.xml": document,
                 "word/_rels/document.xml.rels": DOCUMENT_RELS,
                 "word/styles.xml": STYLES})


def _zip(parts):
    from io import BytesIO
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content.encode("utf-8"))
    return buffer.getvalue()
