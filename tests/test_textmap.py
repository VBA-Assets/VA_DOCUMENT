"""確認表示とエディターの連動（textmap.py）。エディター → 確認表示 → エディターで、同じ位置に戻ることを確かめる。"""
from pathlib import Path

import pytest

from va_document import config
from va_document.session import Session

DATA = Path(__file__).parent / "data"


def session_for(text, doc_type="Saiban"):
    s = Session(config.AppConfig(vamd_folder="未使用", doc_type=doc_type))
    s.typeset(text)
    return s.layout_map


def round_trip(m, line, col):
    page, x, top, h = m.locate(line, col)
    return m.hit(page, x + 1, top + h / 2)


@pytest.mark.parametrize("sample", ["裁判所", "長い文書", "契約書1", "技術"])
def test_every_character_round_trips(sample):
    text = (DATA / sample / "見本.md").read_text(encoding="utf-8")
    m = session_for(text, {"契約書1": "Keiyaku1", "技術": "Technical"}.get(sample, "Saiban"))
    lines = text.splitlines()
    checked = wrong = 0
    for n, p in ((p.src_line, p) for p in m.paras if p.text and p.kind != "table"):
        orig_line = m.origins[n][0]
        for k in range(len(p.text)):
            if p.text[k] == " ":
                continue          # 行末の半角空白は行の外に出すので、字として組まれないことがある
            col = m.origins[n][1][p.source_col(k)]
            checked += 1
            if round_trip(m, orig_line, col) != (orig_line, col):
                wrong += 1
    assert checked > 300 and wrong == 0, (checked, wrong)
    assert len(lines) >= len(m.paras) - 1


def test_page_of_cursor():
    text = (DATA / "長い文書" / "見本.md").read_text(encoding="utf-8")
    m = session_for(text)
    pages = [m.locate(n, 0)[0] for n in range(len(text.splitlines()))]
    assert pages[0] == 0 and pages[-1] == max(pages) >= 10 and pages == sorted(pages)


def test_cleanup_keeps_positions():
    """整形で消える行（コードブロックの記号・フロントマター）と字（強調記号・太字の記号）があっても、元の位置に戻る。"""
    text = "---\ntitle: 試し\n---\n```\n# 第一の見出し\n**強く**言う*本文*。\n```"
    m = session_for(text)
    # 「言」は、元の行（5行目）の「**強く**」の後
    line, col = 5, text.splitlines()[5].index("言")
    assert round_trip(m, line, col) == (line, col)
    # 整形で消えた行（コードブロックの記号）は、次に残った行へ
    assert m.locate(3, 0)[:1] == m.locate(4, 0)[:1]


def test_table_cells():
    text = "# 損害\n| 項目 | --: 金額 |\n|---|---:|\n| 休業損害 | 1,080,000 |\n本文"
    m = session_for(text)
    line3 = text.splitlines()[3]
    page, x, top, h = m.locate(3, line3.index("1,080"))
    assert m.hit(page, x + 1, top + h / 2)[0] == 3
    # 見出しの行のセル（配置の記号の後）をクリックすると、その字へ
    line1 = text.splitlines()[1]
    page, x, top, h = m.locate(1, line1.index("金"))
    ln, col = m.hit(page, x + 1, top + h / 2)
    assert ln == 1 and line1[col] in "項金"


def test_blank_line_locates_to_its_row():
    m = session_for("# 認否\n\n認める。")
    p0, _, top0, h = m.locate(0, 0)
    p1, _, top1, _ = m.locate(1, 0)
    p2, _, top2, _ = m.locate(2, 0)
    assert p0 == p1 == p2 == 0 and top1 == top0 + h and top2 == top1 + h


def test_bold_marks_keep_positions():
    """太字の記号（**）は組まないが、その後の字も、表のセルの中の字も、元の位置に戻る（2026-10-24）。"""
    text = "# 第一の見出し\n前の字**太字の語**後の字。\n| 項目 | 金額 |\n|---|---|\n| **休業**損害 | 1,080,000 |"
    m = session_for(text)
    line = text.splitlines()[1]
    for ch in "前太語後。":
        col = line.index(ch)
        assert round_trip(m, 1, col) == (1, col), ch
    # 表のセルの「損」をクリックすると、元の行の「損」（「**休業**」の後）へ
    cell = text.splitlines()[4]
    piece = m.ts.tables[0]
    g = next(g for g in piece.glyphs if g.ch == "損")
    row = next(r for r in piece.rows if r.index == g.row)
    assert m.hit(piece.page - 1, m.ts.margin_left + g.x + 1, (row.top + row.bottom) / 2) == (4, cell.index("損"))

def test_heading_wrapped_in_bold_round_trips():
    text = "**# 請求原因に対する認否**\n本文。"
    m = session_for(text)
    line = text.splitlines()[0]
    for ch in "請否":
        assert round_trip(m, 0, line.index(ch)) == (0, line.index(ch))

def test_marks_wrapped_in_bold_round_trip():
    text = "**:=: 準備書面（１）**\n# 認否\n| 項目 | 金額 |\n|---|---|\n| 休業損害 | **--: 1,000** |"
    m = session_for(text)
    line = text.splitlines()[0]
    for ch in "準）":
        assert round_trip(m, 0, line.index(ch)) == (0, line.index(ch))
    cell = text.splitlines()[4]
    piece = m.ts.tables[0]
    g = next(g for g in piece.glyphs if g.ch == "0")
    row = next(r for r in piece.rows if r.index == g.row)
    assert m.hit(piece.page - 1, m.ts.margin_left + g.x + 1, (row.top + row.bottom) / 2) == (4, cell.index("0"))


def test_highlight_marks_keep_positions():
    text = "# 認否\n被告の==主張==は**争う**。\n==# 見出しを囲む=="
    m = session_for(text)
    line = text.splitlines()[1]
    for ch in "被主張は争。":
        assert round_trip(m, 1, line.index(ch)) == (1, line.index(ch)), ch
    line = text.splitlines()[2]
    assert round_trip(m, 2, line.index("見")) == (2, line.index("見"))


def test_indent_marks_round_trip():
    text = "# 認否\n->3 　インデントの段落。"
    m = session_for(text)
    line = text.splitlines()[1]
    for ch in "イ段。":
        assert round_trip(m, 1, line.rindex(ch)) == (1, line.rindex(ch))


def test_distribute_marks_round_trip():
    text = "[原告]{5}甲野太郎"
    m = session_for(text)
    for ch in "原告甲郎":
        assert round_trip(m, 0, text.index(ch)) == (0, text.index(ch)), ch


def test_paragraph_bands():
    """プレビューの現在行の強調表示は、エディターの1行＝段落を組んだ行の全部（ページをまたげば、ページごと。2026-11-27
    班長指示）。段落のどの字にカーソルがあっても同じ範囲。"""
    long_para = "被告は、原告の主張をすべて争う。" * 12
    for filler in range(20, 40):
        text = "\n".join(["本文の行。"] * filler + [long_para, "最後の行。"]) + "\n"
        m = session_for(text)
        bands = m.paragraph_bands(filler, 0)
        if len(bands) == 2:
            break
    else:
        pytest.fail("段落がページをまたぐ見本を作れなかった")
    lines = [ln for ln in m.lines if m.paras[ln.para_index].src_line == m._cleaned_line(filler) and ln.glyphs]
    assert len(lines) >= 3
    (p0, top0, h0), (p1, top1, h1) = bands
    assert p1 == p0 + 1
    first, last = [ln for ln in lines if ln.page - 1 == p0], [ln for ln in lines if ln.page - 1 == p1]
    assert (top0, top0 + h0) == (m.ts.line_box(first[0])[0], sum(m.ts.line_box(first[-1])))
    assert (top1, top1 + h1) == (m.ts.line_box(last[0])[0], sum(m.ts.line_box(last[-1])))
    assert m.paragraph_bands(filler, len(long_para) - 1) == bands
    # 1行の段落は、locate の行と同じ
    page, x, top, h = m.locate(0, 0)
    assert m.paragraph_bands(0, 0) == [(page, top, pytest.approx(h))]
