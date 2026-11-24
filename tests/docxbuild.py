"""試験用の Word の文書（.docx）を、XML を書いて作る（Word を使わない。試作\\make_docx_samples.py を試験の部品にしたもの）。

docx(本文の XML, ...) が .docx のバイト列を返す。本文は p()・t() などで組む。
"""
import io
import zipfile

from PIL import Image

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"')

_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>
<Default Extension="jpeg" ContentType="image/jpeg"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

_REL = '<Relationship Id="{}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{}" Target="{}"/>'

# 見出し1〜3 は番号の組 1（第%1・%2・(%3)）に結ぶ。番号の組 2 は「第%1条」、3 は「%1.」、4 は「・」（どれもレベルなし）
STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {NS}>
<w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="24"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="a"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="1"><w:name w:val="heading 1"/><w:basedOn w:val="a"/>
  <w:pPr><w:numPr><w:numId w:val="1"/></w:numPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="2"><w:name w:val="heading 2"/><w:basedOn w:val="a"/>
  <w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr><w:outlineLvl w:val="1"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="3"><w:name w:val="heading 3"/><w:basedOn w:val="a"/>
  <w:pPr><w:numPr><w:ilvl w:val="2"/><w:numId w:val="1"/></w:numPr><w:outlineLvl w:val="2"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="caption"><w:name w:val="caption"/><w:basedOn w:val="a"/><w:rPr><w:b/><w:sz w:val="20"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="hide"><w:name w:val="隠し"/><w:rPr><w:vanish/></w:rPr></w:style>
</w:styles>"""


def _lvl(i, fmt, text):
    return f'<w:lvl w:ilvl="{i}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/><w:suff w:val="space"/></w:lvl>'


NUMBERING = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering {NS}>
<w:abstractNum w:abstractNumId="0">{_lvl(0, "decimalFullWidth", "第%1")}{_lvl(1, "decimalFullWidth", "%2")}{_lvl(2, "decimal", "(%3)")}</w:abstractNum>
<w:abstractNum w:abstractNumId="1">{_lvl(0, "decimalFullWidth", "第%1条")}</w:abstractNum>
<w:abstractNum w:abstractNumId="2">{_lvl(0, "decimal", "%1.")}</w:abstractNum>
<w:abstractNum w:abstractNumId="3">{_lvl(0, "bullet", "・")}</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>
<w:num w:numId="3"><w:abstractNumId w:val="2"/></w:num><w:num w:numId="4"><w:abstractNumId w:val="3"/></w:num>
</w:numbering>"""

CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>作成者の名前</dc:creator><cp:lastModifiedBy>最後に保存した人</cp:lastModifiedBy><dc:title>文書の題</dc:title></cp:coreProperties>"""


def t(s, rpr=""):
    """字の範囲（run）。"""
    return f'<w:r>{f"<w:rPr>{rpr}</w:rPr>" if rpr else ""}<w:t xml:space="preserve">{s}</w:t></w:r>'


def p(inner, ppr=""):
    """段落。"""
    return f'<w:p>{f"<w:pPr>{ppr}</w:pPr>" if ppr else ""}{inner}</w:p>'


def ins(s):
    return f'<w:ins w:id="1" w:author="X"><w:r><w:t>{s}</w:t></w:r></w:ins>'


def dele(s):
    return f'<w:del w:id="2" w:author="X"><w:r><w:delText>{s}</w:delText></w:r></w:del>'


def page_break():
    return '<w:r><w:br w:type="page"/></w:r>'


def line_break():
    return "<w:r><w:br/></w:r>"


def pic(width_cm, anchor=False, rid="rIdImg", crop=None):
    """画像（行内か浮動）。crop は切り抜き (l, t, r, b)（1/100000 単位）。"""
    cx = int(width_cm * 360000)
    src = (f'<a:srcRect l="{crop[0]}" t="{crop[1]}" r="{crop[2]}" b="{crop[3]}"/>' if crop else "")
    graphic = ('<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
               '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:blipFill>'
               f'<a:blip r:embed="{rid}"/>{src}</pic:blipFill></pic:pic></a:graphicData></a:graphic>')
    tag = "wp:anchor" if anchor else "wp:inline"
    return f'<w:r><w:drawing><{tag}><wp:extent cx="{cx}" cy="{cx // 2}"/>{graphic}</{tag}></w:drawing></w:r>'


def textbox(text):
    return ('<w:r><w:drawing><wp:anchor><a:graphic><a:graphicData><wps:wsp><wps:txbx><w:txbxContent>'
            + p(t(text)) + '</w:txbxContent></wps:txbx></wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>')


def field(instr, result):
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve"> {instr} </w:instrText></w:r>'
            f'<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>{result}</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def sect(header=False, footer=False, margins=(1985, 1701, 1701, 1701), grid=None, line_numbers=False):
    refs = ('<w:headerReference w:type="default" r:id="rIdH"/>' if header else "") + (
        '<w:footerReference w:type="default" r:id="rIdF"/>' if footer else "")
    top, right, bottom, left = margins
    g = f'<w:docGrid w:type="linesAndChars" w:linePitch="360" w:charSpace="{grid}"/>' if grid is not None else ""
    ln = '<w:lnNumType w:countBy="1"/>' if line_numbers else ""
    return (f'<w:sectPr>{refs}<w:pgSz w:w="11906" w:h="16838"/>'
            f'<w:pgMar w:top="{top}" w:right="{right}" w:bottom="{bottom}" w:left="{left}"/>{ln}{g}</w:sectPr>')


def png(size=(200, 100), color=(200, 220, 240), text_chunk=None):
    """PNG のバイト列。text_chunk を渡すと、文字の欄（作成者など）を入れる。"""
    from PIL import PngImagePlugin
    buf = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if text_chunk:
        info.add_text("Author", text_chunk)
    Image.new("RGB", size, color).save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def docx(body, *, header=None, footer=None, comments=None, footnotes=None, images=None, styles=STYLES,
         numbering=NUMBERING, extra=None):
    """.docx のバイト列。header・footer は段落の XML、comments・footnotes は字のリスト、images は {r:id: (名前, バイト列)}。"""
    rels = [_REL.format("rIdS", "styles", "styles.xml"), _REL.format("rIdN", "numbering", "numbering.xml")]
    parts = {"word/styles.xml": styles, "word/numbering.xml": numbering}
    if header is not None:
        rels.append(_REL.format("rIdH", "header", "header1.xml"))
        parts["word/header1.xml"] = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr {NS}>{header}</w:hdr>'
    if footer is not None:
        rels.append(_REL.format("rIdF", "footer", "footer1.xml"))
        parts["word/footer1.xml"] = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}>{footer}</w:ftr>'
    if comments:
        rels.append(_REL.format("rIdC", "comments", "comments.xml"))
        parts["word/comments.xml"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:comments {NS}>'
                                      + "".join(f'<w:comment w:id="{k}" w:author="X">{p(t(s))}</w:comment>'
                                                for k, s in enumerate(comments)) + "</w:comments>")
    if footnotes:
        rels.append(_REL.format("rIdFn", "footnotes", "footnotes.xml"))
        parts["word/footnotes.xml"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:footnotes {NS}>'
                                       + "".join(f'<w:footnote w:id="{k + 1}">{p(t(s))}</w:footnote>'
                                                 for k, s in enumerate(footnotes)) + "</w:footnotes>")
    for rid, (name, data) in (images or {}).items():
        rels.append(_REL.format(rid, "image", f"media/{name}"))
        parts[f"word/media/{name}"] = data
    parts.update(extra or {})
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + "".join(rels) + "</Relationships>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/document.xml",
                   f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {NS}><w:body>{body}</w:body></w:document>')
        z.writestr("docProps/core.xml", CORE)
        for name, data in parts.items():
            z.writestr(name, data)
    return buf.getvalue()
