"""表（仕様.md の5.3）。

表は Word に合わせ込まない（比べる正解がない）ので、決まりごと（読み取り、左端・右端、列の幅、
折り返し、改ページ、表の後の本文の位置）を確かめる。
"""
import fitz
import pytest

from va_document.doctypes import DOC_TYPES
from va_document.document import BODY, parse, parse_table, with_column_widths
from va_document.layout import Typesetter
from va_document.layout_blocks import CELL_PAD_X
from va_document.pdfwriter import write_pdf

SAIBAN = DOC_TYPES["Saiban"]


def test_parse_alignment_and_double_rule():
    t = parse_table(["| :-: 科目 | 摘要 | :-- 金額 |", "|===|:---:|---:|", "| 参加費 | 500円 | 48,000 |"])
    # 見出しの行：記号のあるセルは記号の配置、ないセルは列の配置
    assert t.header == [("center", "科目"), ("center", "摘要"), ("left", "金額")]
    # それ以外の行：列の配置（区切りの行の :）
    assert t.rows == [[("left", "参加費"), ("center", "500円"), ("right", "48,000")]]
    assert t.double_rule


def test_parse_single_rule_and_escaped_bar():
    t = parse_table(["| A | B |", "| --- | --- |", r"| a \| b | c |"])
    assert not t.double_rule
    assert t.rows == [[("left", "a | b"), ("left", "c")]]


def test_not_a_table_without_separator():
    ps = parse(["| これは表ではない |", "本文"], SAIBAN)
    assert [p.kind for p in ps] == [BODY, BODY]
    assert ps[0].text == "| これは表ではない |"


def layout(lines):
    ts = Typesetter(SAIBAN)
    out = ts.layout(parse(lines, SAIBAN))
    return ts, out


def test_left_edge_is_body_indent_and_right_edge_is_text_right():
    ts, _ = layout(["# 一", "## 二", "| A | B |", "|---|---|", "| a | b |"])
    piece = ts.tables[0]
    # ## の下の本文の左インデントは2字（本文の2行目以降の位置）
    assert abs(piece.col_x[0] - 2 * ts.pitch) < 0.01
    assert abs(piece.col_x[-1] - ts.text_w) < 0.01


@pytest.mark.parametrize("before", [["- " + "本文" * 40], ["1. " + "本文" * 40], ["- 本文", ""], ["->3 " + "本文" * 40]])
def test_left_edge_follows_list_and_left_indent(before):
    # 箇条書き・段落番号・->N のすぐ後の表は、その段落の2行目以降の字の位置にそろう（空の行は飛ばす）
    ts, lines = layout(["# 一", *before, "| A | B |", "|---|---|", "| a | b |"])
    piece = ts.tables[0]
    para = [ln for ln in lines if ln.glyphs and ln.glyphs[0].ch != "第"]
    left = ts.indents(parse(["# 一", *before], SAIBAN)[1])[0]
    assert abs(piece.col_x[0] - left) < 0.01
    assert left > ts.pitch                  # 本文の左インデント（1字）とは別の位置
    if len(para) > 1:
        assert abs(piece.col_x[0] - para[-1].glyphs[0].x) < 0.01
    assert abs(piece.col_x[-1] - ts.text_w) < 0.01


def test_left_edge_is_body_indent_after_list_and_body():
    # 箇条書きの後でも、間に本文か見出しがあれば本文の左インデント
    ts, _ = layout(["# 一", "- 箇条書き", "本文", "| A | B |", "|---|---|", "| a | b |"])
    assert abs(ts.tables[0].col_x[0] - ts.pitch) < 0.01
    ts, _ = layout(["# 一", "- 箇条書き", "# 二", "| A | B |", "|---|---|", "| a | b |"])
    assert abs(ts.tables[0].col_x[0] - ts.pitch) < 0.01


def test_image_after_list_stays_at_body_indent():
    ts, _ = layout(["# 一", "- 箇条書き", "[IMAGE 1]{10}"])
    assert abs(ts.images[0].x - ts.pitch) < 0.01


def test_table_before_first_heading_starts_at_left_margin():
    ts, _ = layout(["| A | B |", "|---|---|", "| a | b |"])
    assert ts.tables[0].col_x[0] == 0


def test_short_columns_do_not_wrap():
    ts, _ = layout(["| 項目 | 内容 | 金額 |", "|---|---|---:|",
                    "| 休業損害 | " + "長い説明の文章。" * 10 + " | 1,080,000 |"])
    piece = ts.tables[0]
    widths = [b - a for a, b in zip(piece.col_x, piece.col_x[1:])]
    # 短い列は「折り返さずに収まる幅」がある（休業損害は4字、1,080,000 は半角9字＝4.5字）
    assert widths[0] >= 4 * ts.pitch + 2 * CELL_PAD_X - 0.01
    assert widths[2] >= 4.5 * ts.pitch + 2 * CELL_PAD_X - 0.01
    # 長い説明の列だけが折り返し、その行は高くなる
    assert piece.rows[1].bottom - piece.rows[1].top > piece.rows[0].bottom - piece.rows[0].top


def col_widths(piece):
    return [b - a for a, b in zip(piece.col_x, piece.col_x[1:])]


def test_parse_column_widths():
    """区切りの行の {字数}（2026-11-01 班長決定）。配置・2重線と一緒に書け、全角の数字も読む。"""
    t = parse_table(["| A | B | C |", "|:---:{8}|===|---:{１０}|", "| a | b | c |"])
    assert t.widths == [8, None, 10]
    assert t.double_rule and t.rows == [[("center", "a"), ("left", "b"), ("right", "c")]]
    assert parse_table(["| A | B |", "|---|---{3}|---{4}|"]).widths == [None, 3, 4]    # 列が多い
    assert parse_table(["| A | B |", "|---|"]).widths == [None, None]                  # 列が足りない
    assert parse_table(["| A |", "|---{0}|"]) is None                                  # 0字は記号ではない


def test_all_columns_fixed_right_edge_follows_widths():
    """すべての列を指定すると、左端は本文のインデントのまま、右端は列の幅の合計で決まる。"""
    ts, _ = layout(["# 一", "## 二", "| A | B |", "|---{8}|---{6}|", "| a | b |"])
    piece = ts.tables[0]
    assert abs(piece.col_x[0] - 2 * ts.pitch) < 0.01
    assert col_widths(piece) == [8 * ts.pitch + 2 * CELL_PAD_X, 6 * ts.pitch + 2 * CELL_PAD_X]
    assert piece.col_x[-1] < ts.text_w


def test_fixed_width_holds_its_characters_on_one_line():
    ts, _ = layout(["| A | B |", "|---{8}|---{5}|", "| " + "あ" * 8 + " | い |"])
    assert len({g.y for g in ts.tables[0].glyphs if g.ch == "あ"}) == 1
    ts, _ = layout(["| A | B |", "|---{4}|---{5}|", "| " + "あ" * 8 + " | い |"])
    assert len({g.y for g in ts.tables[0].glyphs if g.ch == "あ"}) == 2     # 指定を優先して折り返す


def test_some_columns_fixed_others_reach_text_right():
    """一部の列だけの指定なら、残りの列が本文の右端までを埋める。"""
    ts, _ = layout(["| A | B | C |", "|---{6}|---|---|", "| 短い | " + "長い説明。" * 20 + " | 金額 |"])
    piece = ts.tables[0]
    assert col_widths(piece)[0] == 6 * ts.pitch + 2 * CELL_PAD_X
    assert abs(piece.col_x[-1] - ts.text_w) < 0.01
    assert col_widths(piece)[2] < col_widths(piece)[1]


def test_widths_over_text_width_shrink_by_ratio():
    """本文の幅を超える指定は、比で縮め、右端を本文の右端で止める。指定のない列があっても同じ。"""
    ts, _ = layout(["| A | B |", "|---{60}|---{30}|", "| a | b |"])
    w = col_widths(ts.tables[0])
    assert abs(ts.tables[0].col_x[-1] - ts.text_w) < 0.01
    assert w[0] / w[1] == pytest.approx((60 * ts.pitch + 2 * CELL_PAD_X) / (30 * ts.pitch + 2 * CELL_PAD_X))
    ts, _ = layout(["| A | B |", "|---{90}|---|", "| a | b |"])
    assert abs(ts.tables[0].col_x[-1] - ts.text_w) < 0.01
    assert all(w > 0 for w in col_widths(ts.tables[0]))


def test_no_widths_keeps_automatic_layout():
    """{字数} のない表は、列の幅も右端も今までと同じ。外すと、元の組み方に戻る。"""
    base = ["| 項目 | 内容 |", "|---|---|", "| 休業損害 | " + "長い説明。" * 20 + " |"]
    ts, _ = layout(base)
    ts2, _ = layout([base[0], "|---{6}|---{9}|", base[2]])
    ts3, _ = layout([base[0], with_column_widths("|---{6}|---{9}|", []), base[2]])
    assert ts.tables[0].col_x[-1] == pytest.approx(ts.text_w)
    assert ts2.tables[0].col_x != ts.tables[0].col_x
    assert ts3.tables[0].col_x == ts.tables[0].col_x


def test_column_chars_rounds_up_and_fits_text():
    """今の幅の字数は切り上げ（半角の混ざる列も折り返さない）、合計は本文に収める。固定しても字が折り返さない。"""
    lines = ["| 項目 | 内容 | 金額 |", "|---|---|---:|", "| 休業損害 | " + "長い説明の文章。" * 10 + " | 1,080,000 |"]
    ts, _ = layout(lines)
    chars = ts.column_chars(ts.tables[0])
    assert chars[0] == 4 and chars[2] == 5
    fixed = with_column_widths(lines[1], chars)
    assert fixed == f"|---{{4}}|---{{{chars[1]}}}|---:{{5}}|"
    ts2, _ = layout([lines[0], fixed, lines[2]])
    piece = ts2.tables[0]
    assert piece.col_x[-1] <= ts2.text_w + 0.01
    assert ts2.text_w - piece.col_x[-1] < ts2.pitch * len(chars)
    assert len({g.y for g in piece.glyphs if g.col == 0 and g.row == 1}) == 1
    assert len({g.y for g in piece.glyphs if g.col == 2 and g.row == 1}) == 1


def test_column_chars_of_fixed_columns_are_kept():
    ts, _ = layout(["| A | B |", "|---{8}|---{6}|", "| a | b |"])
    assert ts.column_chars(ts.tables[0]) == [8, 6]


def test_no_hanging_punctuation_in_cells():
    ts, _ = layout(["| A |", "|---|", "| " + "あ" * 40 + "、い |"])
    piece = ts.tables[0]
    right = piece.col_x[-1] - CELL_PAD_X
    assert all(g.x + ts.pitch <= right + 0.01 for g in piece.glyphs)


def test_body_after_table_starts_on_next_grid_row():
    ts, lines = layout(["前", "| A |", "|---|", "| a |", "後"])
    piece = ts.tables[0]
    after = [ln for ln in lines if ln.glyphs[0].ch == "後"][0]
    top_of_after = ts.margin_top + after.row * ts.line_pitch
    assert top_of_after >= piece.rows[-1].bottom - 0.01
    assert top_of_after - piece.rows[-1].bottom < ts.line_pitch


def test_long_table_breaks_between_rows():
    rows = ["| 日付 | 内容 |", "|---|---|"] + [f"| {k}日 | 経過 |" for k in range(1, 60)]
    ts, _ = layout(rows)
    pages = sorted({p.page for p in ts.tables})
    assert pages[0] == 1 and len(pages) >= 2
    bottom = ts.margin_top + ts.lines_page * ts.line_pitch
    assert all(r.bottom <= bottom + 0.01 for p in ts.tables for r in p.rows)
    # 2ページ目以降は、先頭で見出しの行を繰り返す（2026-10-28 班長決定）
    assert all(p.rows[0].index == 0 for p in ts.tables)
    assert sum(len(p.rows) for p in ts.tables) == 60 + len(pages) - 1
    assert [r.index for p in ts.tables for r in p.rows if r.index] == list(range(1, 60))


def test_table_in_pdf(tmp_path):
    ts, lines = layout(["| 科目 | 金額 |", "|===|---:|", "| 参加費 | 48,000 |"])
    path = tmp_path / "表.pdf"
    write_pdf(ts, lines, str(path))
    with fitz.open(path) as doc:
        text = doc[0].get_text()
        drawings = doc[0].get_drawings()
    assert "参加費" in text and "48,000" in text
    # 罫線：横の線（見出しの行の上・2重線の2本・最後の行の下）と縦の線（列の境目3本）
    assert len(drawings) >= 1


def test_double_rule_if_any_column_has_equals():
    """2行目のどれか1列にでも = があれば2重線（|===|---| も |===|===| も同じ）。"""
    assert parse_table(["| A | B |", "|===|---|", "| a | b |"]).double_rule
    assert parse_table(["| A | B |", "|===|===|", "| a | b |"]).double_rule
    assert not parse_table(["| A | B |", "|---|---|", "| a | b |"]).double_rule
