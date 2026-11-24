"""文書の種類「ウェブ文書」（2026-11-24 班長決定）：見出しを Markdown のプレビュー（GitHub・VS Code など）にならった
見た目で組み、表題（:=:）を # の見出し（H1）として読む。見出しのほかの記号は、ビジネス文書と同じに扱う（同日 班長指示）。"""
import io

from pypdf import PdfReader

from va_document import vamd
from va_document.doctypes import DOC_TYPES, WEB
from va_document.document import (BODY, BULLET, CENTER, HEADING, IMAGE, NUMBER, PAGE_BREAK, RIGHT, TABLE, TOC,
                                  parse)
from va_document.layout import Typesetter
from va_document.pdfwriter import pdf_bytes

DT = DOC_TYPES[WEB]
BUSINESS = DOC_TYPES["Business"]

TEXT = """:=: 記事の題

本文の段落です。**太字**と*傍点*が使えます。

## 見出し

- 箇条書き
1. 番号

| 項目 | 内容 |
|---{8}|===:|
| --: 名前 | 見本 |

:-: 中央
->2 字下げ
[HEADER] ヘッダー
<<<
[TOC]
[IMAGE 1]{30}
==蛍光ペン== [原告]{5}
"""


def _parsed(dt):
    return [p for p in parse(TEXT.split("\n"), dt) if p.kind != "blank"]


def test_web_title_looks_like_h1_and_headings_have_no_numbers():
    """表題（:=:）は、見出しとしては扱わず（ビジネス文書と同じ）、# の見出し（H1）と同じ見た目で組む（2026-11-24 班長指示）。
    見出しの番号は付けない。"""
    ps = _parsed(DT)
    assert (ps[0].kind, ps[0].align, ps[0].text) == (BODY, "title", "記事の題")
    assert ps[2].kind == HEADING and ps[2].level == 2 and ps[2].number == ""
    ts = Typesetter(DT)
    lines = ts.layout(parse(["# 見出し", ":=: 表題"], DT))
    h1, title = lines
    assert (title.size, title.rule) == (h1.size, h1.rule) == (1.5, True)
    assert all(g.bold for g in title.glyphs) and title.glyphs[0].x == h1.glyphs[0].x == 0    # H1 と同じく左から


def test_web_marks_are_the_same_as_business_document():
    """見出しのほかの記号（太字・傍点・箇条書き・段落番号・表・配置・->N・ヘッダー・改ページ・目次・画像・蛍光ペン・
    均等割付）は、ビジネス文書と同じに読む。"""
    web, business = _parsed(DT), _parsed(BUSINESS)
    assert [p.kind for p in web[1:]] == [p.kind for p in business[1:]] == [
        BODY, HEADING, BULLET, NUMBER, TABLE, BODY, BODY, BODY, PAGE_BREAK, TOC, IMAGE, BODY]
    for w, b in zip(web[1:], business[1:]):
        if w.kind == HEADING:
            continue
        assert (w.text, w.align, w.left_indent, w.area, w.bold, w.dots, w.highlight, w.distribute, w.image) == (
            b.text, b.align, b.left_indent, b.area, b.bold, b.dots, b.highlight, b.distribute, b.image)
        assert w.number == b.number                       # 箇条書き・段落番号の記号もビジネス文書と同じ（・ ①）
    assert web[6].align == CENTER and web[7].left_indent == 2 and web[8].area == "header"
    table = web[5].table
    assert table.double_rule and table.widths == [8, None] and table.rows[0][0] == (RIGHT, "名前")


def test_web_layout_and_pdf():
    """本文はゴシックの 11pt で字下げなし。見出しは大きく太く、# と ## の下に線を引く。"""
    paras = parse(TEXT.split("\n"), DT)
    ts = Typesetter(DT)
    lines = ts.layout(paras)
    assert ts.font_size == 11 and DT.gothic and DT.label == "ウェブ文書"
    by_para = {}
    for ln in lines:
        by_para.setdefault(ln.para_index, []).append(ln)
    title, body = by_para[0][0], by_para[2][0]
    assert title.size == 1.5 and title.rule and all(g.bold for g in title.glyphs)
    assert body.size == 1.0 and not body.rule and body.glyphs[0].x == 0          # 1行目の字下げなし
    assert any(g.dot for g in body.glyphs)                                      # 傍点はビジネス文書と同じ黒丸
    data = pdf_bytes(ts, lines)
    fonts = {str(f["/BaseFont"]) for page in PdfReader(io.BytesIO(data)).pages
             for f in page["/Resources"]["/Font"].values()}
    # 本文も太字も、埋め込むのはゴシック1つ（太字は太らせて描く。明朝は使わない。Helvetica は reportlab の既定の名前で、
    # VA公用文の文書の PDF にも入る）
    assert len([f for f in fonts if f != "/Helvetica"]) == 1
    assert not any("Mincho" in f or "ipam" in f.lower() for f in fonts)


def test_web_settings():
    """ウェブ文書には、行番号・番号1字を付けない。構文ファイルの区切りの行には「種類 ウェブ文書」と書き、読み戻せる。"""
    s = vamd.Settings(WEB)
    assert not s.allows_line_numbers() and not s.allows_one_width()
    line = vamd.separator_line(vamd.new_doc_id(), 3, s)
    assert "種類 ウェブ文書" in line
    assert vamd.parse_separator_line(line)[2].doc_type == WEB


def test_web_right_aligned_line_after_title_is_the_same_as_business():
    """右揃えの段落の後の決まり（そこから先の # は見出しにしない）は、ビジネス文書と同じ。表題は見出しではないので、表題の
    直後の右揃えの日付の後の見出しは、見出しのまま（2026-11-24 班長指示）。"""
    lines = [":=: 記事の題", "--: 2026年11月24日", "", "## 見出し", "本文", "--: 以上", "## 後ろの見出し"]
    web = [(p.kind, p.text) for p in parse(lines, DT) if p.kind != "blank"]
    business = [(p.kind, p.text) for p in parse(lines, BUSINESS) if p.kind != "blank"]
    assert web == business
    assert web[2] == (HEADING, "見出し") and web[-1] == (BODY, "## 後ろの見出し")
