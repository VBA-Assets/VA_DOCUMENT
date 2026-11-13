"""ヘッダー・フッター（[HEADER] [FOOTER]。2026-10-25 班長指示）。"""
import pytest

import pdfcheck

from va_document import config, vamd
from va_document.cleanup import clean_lines
from va_document.doctypes import (DOC_TYPES, PAGE_NUMBER_BOTTOM_CENTER, PAGE_NUMBER_NONE, PAGE_NUMBER_TOP_RIGHT)
from va_document.document import (CENTER, FOOTER, HEADER, HEADING, RIGHT, move_wraps_after_marks, parse,
                                  split_lead_marks)
from va_document.layout import (FONT_SIZE, FOOTER_BASELINE_OFFSET, FOOTER_DISTANCE, HEADER_DISTANCE, HF_ABOVE,
                                HF_BELOW, HF_EDGE_MIN, HF_LINE_PITCH, PAGE_H, Typesetter)
from va_document.pdfwriter import pdf_bytes
from va_document.session import Session
from va_document.textmap import LayoutMap

SAIBAN, KOUYOU = DOC_TYPES["Saiban"], DOC_TYPES["Kouyou"]
BODY = ["# 請求原因", "本文です。" * 120, "## 細目", "本文です。" * 120]
HEADER_TOP = HEADER_DISTANCE + FONT_SIZE * 220 / 256        # 右上のページ番号の基準線
FOOTER_BOTTOM = PAGE_H - FOOTER_DISTANCE - FOOTER_BASELINE_OFFSET   # 下中央のページ番号の基準線


def layout(lines, dt=SAIBAN, page_number=PAGE_NUMBER_BOTTOM_CENTER):
    ts = Typesetter(dt, page_number)
    paras = parse(lines, dt)
    return ts, paras, ts.layout(paras)


def area_lines(lines, area=None):
    return [ln for ln in lines if ln.area and (area is None or ln.area == area)]


def text_of(ln):
    return "".join(g.ch for g in ln.glyphs)


def test_marks_are_read_with_other_marks():
    ps = parse(["[HEADER] 事件番号", "[footer] :-: 事務所", "--: [Header] 右", "[FOOTER] ->2 　字下げ",
                "**[HEADER] 太字**", "[HEADER]", "[HEADER]本文", "本文"], SAIBAN)
    assert [(p.area, p.align, p.text) for p in ps] == [
        (HEADER, "justify", "事件番号"), (FOOTER, CENTER, "事務所"), (HEADER, RIGHT, "右"),
        (FOOTER, "justify", "字下げ"), (HEADER, "justify", "太字"), (HEADER, "justify", ""),
        (None, "justify", "[HEADER]本文"), (None, "justify", "本文")]      # 後ろに空白のないものは記号ではない
    assert (ps[3].left_indent, ps[3].first_indent) == (2, 1)
    assert ps[4].bold == frozenset({0, 1})
    lead = split_lead_marks("--: [header] ->2 本文")
    assert (lead.align, lead.area, lead.left, lead.rest) == ("--: ", "[header] ", "->2 ", "本文")
    assert move_wraps_after_marks("**[HEADER] --: 本文**") == "[HEADER] --: **本文**"


def test_header_lines_do_not_change_conversion_state():
    """ヘッダー・フッターの行は、見出しの変換を止めない（右揃えの段落と違う）。見出しにもならない。"""
    ps = parse(["# 第一", "--: [FOOTER] 以上", "[HEADER] 　字下げ", "## 第二", "[HEADER] # 見出しではない"], SAIBAN)
    assert [p.kind for p in ps if not p.area] == [HEADING, HEADING]
    assert ps[4].area == HEADER and ps[4].text == "# 見出しではない"


def test_body_is_not_moved_by_header_and_footer():
    """本文の字の位置・改行・改ページは、ヘッダー・フッターがあってもなくても同じ。"""
    def body(lines):
        return [(ln.page, ln.row, [(g.ch, round(g.x, 3)) for g in ln.glyphs]) for ln in lines if not ln.area]
    _, _, plain = layout(BODY)
    _, _, marked = layout(["[HEADER] --: 令和７年（ワ）第１２３号"] + BODY[:2] + ["[FOOTER] :-: 事務所"] + BODY[2:])
    assert body(plain) == body(marked)
    assert max(ln.page for ln in plain) >= 2


def test_header_on_first_page_of_section_and_footer_on_every_page():
    """ヘッダーは、文書の最初のページとセクション区切りの直後のページだけ（「別紙」「付紙」など）。フッターは
    セクションの全ページ（2026-10-25 班長指示）。"""
    ts, _, lines = layout(["[FOOTER] 本紙の下"] + BODY + ["[HEADER] 本紙", "<<<=", "[HEADER] --: 別紙", "[FOOTER] 別紙の下"]
                          + BODY)
    pages = max(ln.page for ln in lines)
    second = min(ln.page for ln in lines if not ln.area and "".join(g.ch for g in ln.glyphs).endswith("請求原因")
                 and ln.page > 1)
    assert second > 2 and pages > second           # どちらのセクションも2ページ以上
    head = {ln.page: text_of(ln) for ln in area_lines(lines, HEADER)}
    assert head == {1: "本紙", second: "別紙"}      # セクションの途中に書いても、最初のページに出る
    foot = {ln.page: text_of(ln) for ln in area_lines(lines, FOOTER)}
    assert foot == {p: ("本紙の下" if p < second else "別紙の下") for p in range(1, pages + 1)}
    assert all(ln.row == -1 for ln in area_lines(lines))
    assert not ts.warnings


def test_positions_next_to_page_number():
    # 下中央：ヘッダーはページ番号の位置（右上）から書き出し、フッターはページ番号の直上に積む
    ts, _, lines = layout(["[HEADER] 一", "[HEADER] 二", "[FOOTER] 三", "本文"])
    ys = [ln.y for ln in area_lines(lines)]
    assert ys == pytest.approx([HEADER_TOP, HEADER_TOP + HF_LINE_PITCH, FOOTER_BOTTOM - HF_LINE_PITCH])
    assert ts.page_number_baseline(1, PAGE_NUMBER_BOTTOM_CENTER) == pytest.approx(FOOTER_BOTTOM)
    # 右上：ヘッダーはページ番号の直下、フッターはページ番号の位置（下）で終える
    ts, _, lines = layout(["[HEADER] 一", "[FOOTER] 二", "[FOOTER] 三", "本文"], page_number=PAGE_NUMBER_TOP_RIGHT)
    ys = [ln.y for ln in area_lines(lines)]
    assert ys == pytest.approx([HEADER_TOP + HF_LINE_PITCH, FOOTER_BOTTOM - HF_LINE_PITCH, FOOTER_BOTTOM])
    # ページ番号なし：ページ番号の位置から
    _, _, lines = layout(["[HEADER] 一", "[FOOTER] 二", "本文"], page_number=PAGE_NUMBER_NONE)
    assert [ln.y for ln in area_lines(lines)] == pytest.approx([HEADER_TOP, FOOTER_BOTTOM])


def test_alignment_in_header():
    ts, _, lines = layout(["[HEADER] --: 右の字", "[FOOTER] :-: 中央", "本文"])
    right, center = area_lines(lines)
    last = right.glyphs[-1]
    assert last.x + ts.advance(last.ch) == pytest.approx(ts.text_w)
    width = sum(ts.advance(g.ch) for g in center.glyphs)
    assert center.glyphs[0].x == pytest.approx((ts.text_w - width) / 2)


def test_long_header_wraps():
    ts, _, lines = layout(["[HEADER] " + "長いヘッダー" * 10, "本文"])
    head = area_lines(lines, HEADER)
    assert len(head) == 2 and head[1].y - head[0].y == pytest.approx(HF_LINE_PITCH)
    assert "".join(text_of(ln) for ln in head) == "長いヘッダー" * 10


def test_overflow_moves_header_and_page_number_toward_edge():
    """公用文（上の余白 25mm）で右上のページ番号の下にヘッダーを置くと本文にかかるので、ページ番号ごと上へずらす。
    本文は動かさない。端から HF_EDGE_MIN まででも入らなければ知らせる（2026-10-25 班長決定）。"""
    ts, _, lines = layout(["[HEADER] 一", "本文"], KOUYOU, PAGE_NUMBER_TOP_RIGHT)
    (head,) = area_lines(lines)
    pn = ts.page_number_baseline(1, PAGE_NUMBER_TOP_RIGHT)
    assert head.y + HF_BELOW == pytest.approx(ts.margin_top)            # 本文の範囲のすぐ上まで
    assert head.y - pn == pytest.approx(HF_LINE_PITCH) and pn < HEADER_TOP
    assert not ts.warnings
    ts, _, lines = layout(["[HEADER] 行"] * 4 + ["本文"], KOUYOU, PAGE_NUMBER_TOP_RIGHT)
    pn = ts.page_number_baseline(1, PAGE_NUMBER_TOP_RIGHT)
    assert pn - HF_ABOVE == pytest.approx(HF_EDGE_MIN)
    assert ts.warnings and "ヘッダー" in ts.warnings[0] and "1 ページ" in ts.warnings[0]
    # フッター：公用文（下の余白 20mm）で下中央のページ番号の上に置くと、ページ番号ごと下へずらす
    ts, _, lines = layout(["[FOOTER] 一", "本文"], KOUYOU)
    (foot,) = area_lines(lines)
    assert foot.y - HF_ABOVE == pytest.approx(ts.margin_top + ts.lines_page * ts.line_pitch)
    assert ts.page_number_baseline(1, PAGE_NUMBER_BOTTOM_CENTER) - foot.y == pytest.approx(HF_LINE_PITCH)
    assert not ts.warnings


def test_naiyou_has_no_header():
    ts, _, lines = layout(["[HEADER] 一", "本文"], DOC_TYPES["Naiyou"], PAGE_NUMBER_NONE)
    assert not area_lines(lines) and ts.warnings


def test_pdf_draws_header_and_moved_page_number():
    ts, _, lines = layout(["[HEADER] --: **事件番号**", "[FOOTER] 事務所", "本文"], KOUYOU, PAGE_NUMBER_TOP_RIGHT)
    chars = [(c["text"], c["y"]) for c in pdfcheck.chars(pdf_bytes(ts, lines, page_number=PAGE_NUMBER_TOP_RIGHT))]
    ys = {}
    for ch, y in chars:
        ys.setdefault(ch, y)
    assert ys["事"] == pytest.approx(area_lines(lines, HEADER)[0].y, abs=0.01)
    assert ys["所"] == pytest.approx(area_lines(lines, FOOTER)[0].y, abs=0.01)
    # ページ番号（最後のページは「１」」）は、ページの最後に、ずらした位置に描く
    assert "".join(ch for ch, _ in chars[-2:]) == "１」"
    assert chars[-1][1] == pytest.approx(ts.page_number_baseline(1, PAGE_NUMBER_TOP_RIGHT), abs=0.01)
    assert chars[-1][1] < HEADER_TOP


def test_line_numbers_do_not_count_header():
    from va_document.pdfwriter import LINE_NUMBER_STEP
    ts, _, lines = layout(["[HEADER] 一"] + ["本文"] * 5)
    text = pdfcheck.text(pdf_bytes(ts, lines, line_numbers=True), 0)
    assert str(LINE_NUMBER_STEP) in text and "10" not in text


def test_preview_link_on_header():
    text = "[HEADER] --: 事件番号\n" + "\n".join(BODY)
    cleaned, origins, _ = clean_lines(text)
    ts = Typesetter(SAIBAN)
    paras = parse(cleaned, SAIBAN)
    lines = ts.layout(paras)
    m = LayoutMap(ts, lines, paras, cleaned, origins)
    page, x, top, height = m.locate(0, 14)              # 「事件番号」の「件」
    head = area_lines(lines, HEADER)[0]
    assert page == 0 and top == pytest.approx(head.y - HF_ABOVE) and height == pytest.approx(HF_LINE_PITCH)
    assert m.hit(0, x + 1, head.y - 4) == (0, 14)        # ヘッダーの字をクリックすると、その字へ
    assert not [ln for ln in area_lines(lines) if ln.page == 2]     # 2ページ目にはヘッダーがない


@pytest.fixture
def session(tmp_path):
    s = Session(config.AppConfig(vamd_folder=str(tmp_path / "構文ファイル")))
    s.dictionary.register("甲野太郎", "人名")
    s.dictionary.register("乙山花子", "人名")
    return s


@pytest.mark.parametrize("page_number", [PAGE_NUMBER_BOTTOM_CENTER, PAGE_NUMBER_TOP_RIGHT])
def test_reopen_recovers_words_only_in_header(session, tmp_path, page_number):
    """ヘッダー・フッターにだけある実名も、構文ファイルと PDF の突き合わせで求まる（複数ページ・セクション）。"""
    session.settings.page_number = page_number
    real = "\n".join(["[HEADER] --: 原告　甲野太郎"] + BODY + ["[FOOTER] :-: 担当　乙山花子", "<<<=",
                      "[HEADER] --: 原告　甲野太郎", "別紙", "<<<=", "[HEADER] 別紙２", "本文"])
    pdf = tmp_path / "準備書面.pdf"
    session.save(real, pdf)
    assert "甲野" not in session.vamd_path.read_text(encoding="utf-8")
    s2 = Session(session.cfg)
    r = s2.open_vamd(session.vamd_path, pdf)
    assert r.text == real and not r.unresolved and not r.messages and r.recovery.exact


def test_review_reports_lost_header_mark():
    c = vamd.Content("ABCDEFGH", 1, body=["本文", "原告"])
    r = vamd.review(c, "ABCDEFGH", 1, ["本文", "[header] 原告"], _NoDictionary())
    assert r.lost_marks == [("[HEADER]", "[header] 原告")]
    c = vamd.Content("ABCDEFGH", 1, body=["本文", "[HEADER] 原告"])
    assert not vamd.review(c, "ABCDEFGH", 1, ["本文", "[header] 原告"], _NoDictionary()).lost_marks


def test_default_prompt_mentions_header_and_old_prompt_is_default():
    assert "[HEADER]" in vamd.PROMPT and vamd.is_default_prompt(vamd.PROMPT + "\n")
    assert not vamd.is_default_prompt("独自の指示")
    assert all(len(h) == 64 for h in vamd.PREVIOUS_PROMPTS)


class _NoDictionary:
    def find(self, token):
        return None
