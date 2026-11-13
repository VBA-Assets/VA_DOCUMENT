"""蛍光ペン（==文字==。確認表示だけで黄色に塗り、保存する PDF と印刷には出さない。2026-10-24 班長指示）。"""
import pdfcheck
from va_document import config
from va_document.doctypes import DOC_TYPES
from va_document.document import RIGHT, TITLE, parse, split_inline
from va_document.layout import Typesetter
from va_document.pdfwriter import pdf_bytes
from va_document.session import Session

DT = DOC_TYPES["Saiban"]
TEXT = ["# 認否", "被告の==主張==は**争う**。", "**==重ねた語==**と==**重ねた語**==。", "a == b のような式は、そのまま。",
        "==# 見出しを囲む==", "==:=: 表題を囲む==", "| 項目 | 金額 |", "|---|---|", "| ==休業損害== | ==--: 1,000== |"]


def test_split_inline():
    plain, bold, mark, cols = split_inline("被告の==主張==は**争う**。")
    assert plain == "被告の主張は争う。" and mark == {3, 4} and bold == {6, 7}
    assert cols[3] == 5 and cols[6] == 12
    plain, bold, mark, _ = split_inline("**==重ねた語==**")
    assert plain == "重ねた語" and bold == mark == {0, 1, 2, 3}
    for s in ("a == b のような式", "== 空白==", "==片方だけ"):
        assert split_inline(s)[0] == s


def test_parse_reads_highlight_with_marks():
    paras = parse(TEXT, DT)
    body, both, formula, heading, title, table = paras[1:]
    assert body.text == "被告の主張は争う。" and body.highlight == {3, 4} and body.bold == {6, 7}
    assert both.text == "重ねた語と重ねた語。" and both.highlight == both.bold == {0, 1, 2, 3, 5, 6, 7, 8}
    assert formula.text == "a == b のような式は、そのまま。" and not formula.highlight
    assert (heading.kind, heading.text, len(heading.highlight)) == ("heading", "見出しを囲む", 6)
    assert (title.align, title.text) == (TITLE, "表題を囲む")
    assert table.table.rows[0][1] == (RIGHT, "1,000")
    assert table.table.highlight == {(1, 0): {0, 1, 2, 3}, (1, 1): {0, 1, 2, 3, 4}}


def yellow_rects(data):
    return pdfcheck.filled(data, (1, 1, 0))


def test_yellow_only_in_preview():
    """黄色は確認表示だけ。保存する PDF・印刷（preview_pdf の既定）には塗らない。字の位置は変わらない。"""
    ts = Typesetter(DT)
    lines = ts.layout(parse(TEXT, DT))
    rects = yellow_rects(pdf_bytes(ts, lines, highlight=True))
    # 段落の「主張」「重ねた語」×2（字の間も1つにつなげる）、見出し（番号も）、表題、セル2つ
    assert len(rects) == 7
    assert not yellow_rects(pdf_bytes(ts, lines))
    s = Session(config.AppConfig(vamd_folder="未使用"))
    assert yellow_rects(s.preview_pdf("\n".join(TEXT), highlight=True))
    assert not yellow_rects(s.preview_pdf("\n".join(TEXT)))
    plain = [(g.ch, round(g.x, 3)) for ln in ts.layout(parse([split_inline(t)[0] for t in TEXT[:4]], DT))
             for g in ln.glyphs]
    marked = [(g.ch, round(g.x, 3)) for ln in ts.layout(parse(TEXT[:4], DT)) for g in ln.glyphs]
    assert plain == marked


def test_triple_equals_is_not_highlight():
    """表の区切りの行（|===|===|）の「==|==」や、= が3つ以上続く所は蛍光ペンの記号とみなさない（2026-10-24、
    エディターで区切りの行の真ん中の | が黄色になった）。"""
    from va_document.document import inline_mark_spans
    for s in ("|===|===|", "|:===|===:|", "a===b===c", "==== VA Document 文書ID K7Q29XMD 版 1 ===="):
        assert inline_mark_spans(s) == ([], [], [], []) and split_inline(s)[0] == s
    assert split_inline("**==重ねた語==**")[2] == {0, 1, 2, 3}
    assert split_inline("| ==休業損害== |")[2] == {2, 3, 4, 5}


def test_pseudonyms_are_tinted_in_preview_only():
    """確認表示では、仮名化した語の字の地に薄い緑を付ける（本文・表のセル。保存する PDF・印刷には付けない。
    2026-10-24 班長指示）。"""
    s = Session(config.AppConfig(vamd_folder="未使用"))
    s.dictionary.register("甲野太郎", "人名")
    text = "# 認否\n甲野太郎の主張は争う。\n| 当事者 | 主張 |\n|---|---|\n| 甲野太郎 | 争う |"

    def tinted(data):
        return pdfcheck.filled(data, (0xd9 / 255, 0xf2 / 255, 0xd9 / 255))
    rects = tinted(s.preview_pdf(text, highlight=True))
    assert len(rects) == 2                                        # 本文の「甲野太郎」と、セルの「甲野太郎」
    assert all(abs(r["width"] - 4 * 12) < 13 for r in rects)     # 4字ぶん（字の間隔の分の揺れは許す）
    assert not tinted(s.preview_pdf(text))

