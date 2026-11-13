"""傍点（*文字*。字の上に黒丸を付ける。2026-10-24 班長指示）。"""
import pdfcheck
from va_document.doctypes import DOC_TYPES
from va_document.document import (PAGE_BREAK, TITLE, line_mark, move_wraps_after_marks, parse, split_inline,
                                  split_inline_full)
from va_document.layout import DOT_RADIUS, DOT_RISE, Typesetter
from va_document.pdfwriter import pdf_bytes

DT = DOC_TYPES["Saiban"]
TEXT = ["# 認否", "被告の*主張*は**争う**。", "***重ねた語***と*二つ* *目*。", "2*3*4 や * 項目 * は、そのまま。",
        "| 項目 | 金額 |", "|---|---|", "| *休業損害* | --: 1,000 |"]


def test_split_inline_reads_dots():
    r = split_inline_full("被告の*主張*は**争う**。")
    assert r.plain == "被告の主張は争う。" and r.dots == {3, 4} and r.bold == {6, 7}
    r = split_inline_full("***重ねた語***")              # 太字の記号を先に読み、残った * を傍点とする
    assert r.plain == "重ねた語" and r.bold == r.dots == {0, 1, 2, 3}
    for s in ("2*3*4", "* 項目 *", "*片方だけ", "a*b*c"):
        assert split_inline_full(s).plain == s and not split_inline_full(s).dots
    assert split_inline("前*傍点*後")[0] == "前傍点後"


def test_dots_with_lead_marks():
    """行全体を * で囲んでも、行頭の記号（配置・見出し・その行だけの記号）として読む（太字と同じ）。"""
    assert move_wraps_after_marks("*:=: 準備書面*") == ":=: *準備書面*"
    assert move_wraps_after_marks("*# 見出し*") == "# *見出し*"
    assert line_mark("*<<<*") == (PAGE_BREAK, 0)
    p = parse(["*:=: 準備書面*"], DT)[0]
    assert (p.align, p.text, p.dots) == (TITLE, "準備書面", {0, 1, 2, 3})


def dots_in(data):
    """PDF の黒丸（傍点）の中心 [(ページ, x, y)]。"""
    return pdfcheck.dots(data)


def test_dots_drawn_above_characters_without_moving_text():
    """傍点は保存する PDF にも描く。字の上の中央に黒丸を置き、字の位置・改行は変えない。PDF の字には入れない。"""
    ts = Typesetter(DT)
    paras = parse(TEXT, DT)
    lines = ts.layout(paras)
    data = pdf_bytes(ts, lines)
    dots = dots_in(data)
    # 本文の「主張」2字、「重ねた語」4字、「二つ」「目」3字（空白には付けない）、表のセルの「休業損害」4字
    assert len(dots) == 2 + 4 + 3 + 4
    glyphs = {(g.ch, round(ts.margin_left + g.x + ts.advance(g.ch) / 2, 2)): ln for ln in lines for g in ln.glyphs if g.dot}
    for ch, x in glyphs:
        assert any(abs(x - dx) < 0.01 for _, dx, _ in dots), ch
    first = next(ln for ln in lines if any(g.dot for g in ln.glyphs))
    _, _, y = dots[0]
    assert abs(y - (ts.baseline(first.row) - DOT_RISE)) < 0.05     # 基準線から DOT_RISE 上（上から測る）
    text = pdfcheck.text(data, 0)
    assert "・" not in text and "被告の主張は争う。" in text.replace("\n", "")
    plain = [(g.ch, round(g.x, 3), ln.row) for ln in ts.layout(parse([split_inline_full(t).plain for t in TEXT[:4]], DT))
             for g in ln.glyphs]
    marked = [(g.ch, round(g.x, 3), ln.row) for ln in ts.layout(parse(TEXT[:4], DT)) for g in ln.glyphs]
    assert plain == marked


def test_dots_not_on_heading_numbers():
    ts = Typesetter(DT)
    lines = ts.layout(parse(["# *認否*"], DT))
    assert [g.ch for g in lines[0].glyphs if g.dot] == ["認", "否"]


def test_dots_in_table_rows_do_not_touch_rules():
    """表の行は字の上の余白が狭いので、傍点のある行だけ上を空け、黒丸が上の罫線に重ならないようにする。"""
    ts = Typesetter(DT)
    ts.layout(parse(["| 項目 | 金額 |", "|---|---|", "| *休業損害* | 1,000 |", "| 逸失利益 | 2,000 |"], DT))
    rows = ts.tables[0].rows
    heights = [round(r.bottom - r.top, 2) for r in rows]
    assert heights[1] > heights[0] == heights[2]
    for g in ts.tables[0].glyphs:
        if g.dot:
            assert g.y - DOT_RISE - DOT_RADIUS > rows[g.row].top + 0.5

