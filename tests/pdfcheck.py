"""試験で PDF を確かめる道具（Ver300、2026-11-14。PyMuPDF〔AGPL-3.0〕を使わずに、pdfplumber〔MIT〕・pypdf〔BSD-3〕・
pdfpages〔pypdfium2〕で読み、試験用の PDF は reportlab〔BSD〕で作る）。

位置はポイントで、上下は用紙の上端から測る（替える前の PyMuPDF と同じ向き）。pdf は PDF のバイト列かファイルの場所。
"""
import io
from pathlib import Path

import pdfplumber


def _data(pdf):
    return pdf if isinstance(pdf, (bytes, bytearray)) else Path(pdf).read_bytes()


def open_pdf(pdf):
    """pdfplumber の PDF（with で使う）。"""
    return pdfplumber.open(io.BytesIO(_data(pdf)))


def page_count(pdf):
    with open_pdf(pdf) as doc:
        return len(doc.pages)


def page_size(pdf, k=0):
    with open_pdf(pdf) as doc:
        p = doc.pages[k]
        return p.width, p.height


def _char(c, h):
    return {"text": c["text"], "x": c["matrix"][4], "y": h - c["matrix"][5], "size": c["size"],
            "font": c["fontname"], "x0": c["x0"], "x1": c["x1"], "top": c["top"], "bottom": c["bottom"],
            "width": c["x1"] - c["x0"]}


def chars(pdf, k=0):
    """ページ k の字を、描いた順に [{text, x〔字の左端〕, y〔基準線〕, size, font, x0, x1, top, bottom, width}]。"""
    with open_pdf(pdf) as doc:
        p = doc.pages[k]
        return [_char(c, p.height) for c in p.chars]


def all_chars(pdf):
    """全ページの字（ページごとのリスト）。"""
    with open_pdf(pdf) as doc:
        return [[_char(c, p.height) for c in p.chars] for p in doc.pages]


def lines(pdf, k=0):
    """ページ k の字を、基準線ごとの行（左から）にした文字列のリスト（上から）。"""
    rows = {}
    for c in chars(pdf, k):
        rows.setdefault(round(c["y"] * 2) / 2, []).append(c)
    return ["".join(c["text"] for c in sorted(rows[y], key=lambda c: c["x"])) for y in sorted(rows)]


def text(pdf, k=None):
    """ページ k（None なら全ページ）の字を、行ごとに改行でつないだ文字列。"""
    ks = range(page_count(pdf)) if k is None else [k]
    return "\n".join("\n".join(lines(pdf, i)) for i in ks)


def fonts(pdf, k=0):
    """ページ k で字に使っている書体の名前の集合。"""
    return {c["font"] for c in chars(pdf, k)}


def images(pdf, k=0):
    """ページ k に置いた画像の数（同じ画像を2か所に置けば2）。"""
    with open_pdf(pdf) as doc:
        return len(doc.pages[k].images)


def drawings(pdf, k=0):
    """ページ k の線・四角・図形の数。"""
    with open_pdf(pdf) as doc:
        p = doc.pages[k]
        return len(p.lines) + len(p.rects) + len(p.curves)


def image_marks(pdf, key):
    """画像の辞書の目印（/<key>）の値のリスト（目印のある画像ごと。番号の配列は list）。"""
    from pypdf import PdfReader
    from pypdf.generic import ArrayObject
    out, seen = [], set()
    for page in PdfReader(io.BytesIO(_data(pdf))).pages:
        xo = page["/Resources"].get_object().get("/XObject")
        for ref in (xo.get_object().values() if xo else []):
            obj = ref.get_object()
            if ref.idnum in seen or "/" + key not in obj:
                continue
            seen.add(ref.idnum)
            v = obj["/" + key]
            out.append([int(x) for x in v] if isinstance(v, ArrayObject) else int(v))
    return out


def metadata(pdf):
    """(文書情報〔/Info〕の辞書か None, XMP〔/Metadata〕があるか, 識別子〔/ID〕のバイト列のリストか None)。"""
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(_data(pdf)))
    info = r.trailer.get("/Info")
    ids = r.trailer.get("/ID")
    return (dict(info.get_object()) if info is not None else None, "/Metadata" in r.trailer["/Root"],
            [_raw(x.get_object()) for x in ids] if ids else None)


def _raw(s):
    return s.original_bytes if hasattr(s, "original_bytes") else bytes(s)


def dots(pdf):
    """塗りつぶした小さな図形（傍点の黒丸）の中心 [(ページ, x, y)]。"""
    out = []
    with open_pdf(pdf) as doc:
        for k, p in enumerate(doc.pages):
            for c in p.curves + p.rects:
                color = c.get("non_stroking_color")
                if c.get("fill") and c["x1"] - c["x0"] < 3 and color in ((0,), (0, 0, 0), [0], [0, 0, 0], 0):
                    out.append((k, (c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2))
    return out


def filled(pdf, color):
    """color（0〜1 の RGB）で塗りつぶした四角・図形 [{x0, x1, top, bottom, width}]（全ページ）。"""
    out = []
    with open_pdf(pdf) as doc:
        for p in doc.pages:
            for c in p.rects + p.curves:
                fill = c.get("non_stroking_color")
                if c.get("fill") and isinstance(fill, (tuple, list)) and len(fill) == 3 and \
                        all(abs(a - b) < 0.01 for a, b in zip(fill, color)):
                    out.append({"x0": c["x0"], "x1": c["x1"], "top": c["top"], "bottom": c["bottom"],
                                "width": c["x1"] - c["x0"]})
    return out


def render(pdf, k=0, dpi=72, gray=False):
    """ページ k を画像（Pillow）にする（VA Document のプレビュー・印刷と同じ pdfpages）。"""
    from va_document.pdfpages import PdfPages
    with PdfPages(_data(pdf)) as doc:
        return doc.render(k, dpi / 72, gray=gray).image().copy()


def make_pdf(*pages, size=(595.3, 841.9)):
    """試験用の PDF（バイト列）。pages は、reportlab の canvas を受けて1ページを描く関数（y は用紙の上端から測りたい
    ときは、size[1] - y にする）。"""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=size)
    for draw in pages:
        draw(c)
        c.showPage()
    c.save()
    return buf.getvalue()
