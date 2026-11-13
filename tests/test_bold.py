"""太字（**文字**。ＭＳ ゴシックで描く。2026-10-24 班長指示）。"""
import pdfcheck
from va_document.doctypes import DOC_TYPES
from va_document.document import TOC, parse, split_inline
from va_document.layout import Typesetter
from va_document.pdfwriter import pdf_bytes

DT = DOC_TYPES["Saiban"]


def test_split_bold():
    plain, bold, _, cols = split_inline("前**太字**後")
    assert plain == "前太字後" and bold == {1, 2}
    assert cols == [0, 3, 4, 7, 8]
    # 片方だけ・記号の内側が空白で始まる（終わる）ものは、太字の記号ではない
    for s in ("**片方だけ", "** 空白**", "**空白 **", "****"):
        assert split_inline(s)[0] == s and not split_inline(s)[1]


def test_parse_marks_bold_in_paragraphs_headings_and_cells():
    paras = parse(["# **重要な**見出し", "本文の**一部**を強調する。", "| 項目 | 金額 |", "|---|---|",
                   "| **休業**損害 | 1,000 |"], DT)
    head, body, table = paras
    assert head.text == "重要な見出し" and head.bold == {0, 1, 2}
    assert body.text == "本文の一部を強調する。" and body.bold == {3, 4}
    assert table.table.rows[0][0][1] == "休業損害" and table.table.bold == {(1, 0): {0, 1}}


def glyphs_of(lines):
    return [(g.ch, round(g.x, 3), ln.page, ln.row, g.bold) for ln in lines for g in ln.glyphs]


def test_bold_does_not_move_characters():
    """太字にしても、字の位置は変わらない（ＭＳ ゴシックも、字の幅はＭＳ 明朝と同じ）。"""
    ts = Typesetter(DT)
    plain = glyphs_of(ts.layout(parse(["# 見出し", "本文の一部を強調する。" * 5], DT)))
    bold = glyphs_of(ts.layout(parse(["# 見出し", "本文の**一部**を強調する。" * 5], DT)))
    assert [g[:4] for g in plain] == [g[:4] for g in bold]
    assert "".join(g[0] for g in bold if g[4]) == "一部" * 5


def test_pdf_draws_bold_in_ms_gothic():
    ts = Typesetter(DT)
    lines = ts.layout(parse(["# 見出し", "本文の**一部**を強調する。", "| 項目 | 金額 |", "|---|---|",
                             "| **休業**損害 | 1,000 |"], DT))
    chars = pdfcheck.chars(pdf_bytes(ts, lines))
    gothic = "".join(c["text"] for c in chars if "Gothic" in c["font"])
    assert gothic == "一部休業"
    assert all("Mincho" in c["font"] for c in chars if c["text"] not in "一部休業")


def test_pdf_without_bold_has_no_gothic():
    ts = Typesetter(DT)
    lines = ts.layout(parse(["# 見出し", "本文。"], DT))
    # 字に使う書体だけでなく、PDF に入れた書体にもゴシックがない
    data = pdf_bytes(ts, lines)
    assert all("Gothic" not in f for f in pdfcheck.fonts(data)) and b"Gothic" not in data


def test_toc_entries_are_not_bold():
    ts = Typesetter(DT)
    paras = parse(["[TOC]", "<<<", "# **重要な**見出し"], DT)
    assert paras[0].kind == TOC
    toc = [ln for ln in ts.layout(paras) if ln.para_index == 0]
    assert "".join(g.ch for g in toc[0].glyphs if not g.is_number) == "第１ 重要な見出し"
    assert not any(g.bold for g in toc[0].glyphs)


def test_bold_around_heading_marker():
    """「**# 見出し**」（AI が見出しの行を丸ごと太字にしたもの）も見出しとし、見出しの字を太字にする
    （VA公用文は ** を取り除いて見出しにする。2026-10-24 班長指示）。箇条書き・段落番号も同じ。"""
    paras = parse(["**# 請求原因に対する認否**", "**## 小見出し**", "**1. 番号**", "**- 箇条**",
                   "**#見出し**", "**# 片方だけ"], DT)
    kinds = [(p.kind, p.level, p.text, len(p.bold)) for p in paras]
    assert kinds[:4] == [("heading", 1, "請求原因に対する認否", 10), ("heading", 2, "小見出し", 4),
                         ("number", 0, "番号", 2), ("bullet", 0, "箇条", 2)]
    # 記号の後に空白がないもの・太字の記号が対になっていないものは、見出しにしない
    assert [p.kind for p in paras[4:]] == ["body", "body"] and paras[5].text == "**# 片方だけ"
    # 本文の字は、元の行の字の位置に対応する（確認表示とエディターの連動）
    assert paras[0].source_col(0) == 4 and paras[0].source_col(len(paras[0].text) - 1) == 13

def test_number_is_bold_when_whole_text_is_bold():
    """見出しの本文がすべて太字なら、見出しの番号も太字にする（「**# 見出し**」「# **見出し**」とも）。
    一部だけ太字なら、番号は太字にしない（2026-10-24 班長指示）。段落番号・箇条書きも同じ。"""
    ts = Typesetter(DT)
    paras = parse(["**# 請求原因に対する認否**", "## **小見出し**", "### **一部**だけ太字", "1. **番号の本文**"], DT)
    lines = ts.layout(paras)

    def number_bold(pi):
        ln = next(ln for ln in lines if ln.para_index == pi)
        return [g.bold for g in ln.glyphs if g.is_number]
    assert all(number_bold(0)) and all(number_bold(1)) and all(number_bold(3))
    assert not any(number_bold(2))

def test_bold_around_every_mark():
    """配置の記号・字下げの空白・その行だけの記号・セルの配置の記号も、太字の記号で囲んだままで記号として読む
    （「**:=: 準備書面（１）**」など。2026-10-24 班長指示。字下げは 2026-10-28 に全角空白にした）。"""
    from va_document.document import CENTER, PAGE_BREAK, RIGHT, TITLE
    paras = parse(["**:=: 準備書面（１）**", "**:-: 中央の行**", "**　字下げの段落**", "**<<<**",
                   "**[TOC:2]**", "# 見出し", "| 項目 | 金額 |", "|---|---|", "| 休業損害 | **--: 1,000** |",
                   "**--: 以上**", "**# 右揃えの後は見出しにしない**"], DT)
    title, center, indent, brk, toc, _, table, right, after = paras
    assert (title.align, title.text, len(title.bold)) == (TITLE, "準備書面（１）", 7)
    assert (center.align, center.text, len(center.bold)) == (CENTER, "中央の行", 4)
    assert (indent.first_indent, indent.text, len(indent.bold)) == (1, "字下げの段落", 6)
    assert brk.kind == PAGE_BREAK and (toc.kind, toc.level) == (TOC, 2)
    assert table.table.rows[0][1] == (RIGHT, "1,000") and table.table.bold == {(1, 1): {0, 1, 2, 3, 4}}
    assert (right.align, right.text) == (RIGHT, "以上")
    assert after.kind == "body" and after.text == "# 右揃えの後は見出しにしない"
    # 本文の1字目は、元の行の記号の後の字に対応する
    assert title.source_col(0) == len("**:=: ")