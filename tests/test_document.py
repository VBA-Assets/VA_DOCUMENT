"""マークダウンの読み取り（仕様.md の5）。"""
from va_document.doctypes import DOC_TYPES
from va_document.document import (BLANK, BODY, BULLET, CENTER, HEADING, NUMBER, PAGE_BREAK, RIGHT,
                                      SECTION_BREAK, TITLE, TOC, parse)
from va_document.layout import Typesetter

SAIBAN = DOC_TYPES["Saiban"]


def kinds(text):
    return [(p.kind, p.number, p.text) for p in parse(text.splitlines(), SAIBAN)]


def test_marks_need_space():
    """記号の後に半角空白がないものは、見出し・箇条書き・段落番号にしない（字が消えないように）。"""
    ps = parse(["# 見出し", "#見出し", "- 項目", "-1度", "1. 項目", "2026.10.23に"], SAIBAN)
    assert [p.kind for p in ps] == [HEADING, BODY, BULLET, BODY, NUMBER, BODY]
    assert [p.text for p in ps] == ["見出し", "#見出し", "項目", "-1度", "項目", "2026.10.23に"]


def test_keiyaku2_article_space_unless_bracket():
    """契約書2の「第１条」は、見出しが括弧で始まれば詰め（「第１条（目的）」。VA公用文と同じ）、そうでなければ全角空白を
    足す（2026-11-03 班長決定）。太字の記号の中の括弧も括弧と見る。字のない見出し（複合見出しの外側）には足さない。
    契約書1の「第１条　」は変えない。"""
    ps = parse(["# 見出し", "# （目的）", "# **（委託料）**", "# **見出し**", "# 〔管轄〕", "#", "## 項"], DOC_TYPES["Keiyaku2"])
    assert [p.number for p in ps] == ["第１条　", "第２条", "第３条", "第４条　", "第５条", "第６条", "１　"]
    ps = parse(["## （目的）", "### 項"], DOC_TYPES["Keiyaku1"])
    assert [p.number for p in ps] == ["第１条　", "２　"]


def test_align_marks():
    ps = parse([":=: 準備書面", "--: 以上", ":-: 記", ":-- 本文"], SAIBAN)
    assert [p.align for p in ps] == [TITLE, RIGHT, CENTER, "justify"]
    assert [p.text for p in ps] == ["準備書面", "以上", "記", "本文"]


def test_line_marks():
    # 空の行は、Word の空の段落と同じく1行の空き（2026-10-23 班長決定）
    ps = parse(["前", "", "<<<", "<<<=", "後"], SAIBAN)
    assert [p.kind for p in ps] == [BODY, BLANK, PAGE_BREAK, SECTION_BREAK, BODY]


def test_symbol_marks_need_space_or_line_end():
    """記号で表す行頭の記号（2026-10-25 班長決定）も、後ろに半角空白があるときだけ記号とする（行末なら空白は
    なくてよい）。電話番号の「+81 3-…」、箇条書きに似た「+ 」、前の版の「＋２ 」「-> 」、行の途中の記号は、字のまま残す。"""
    ps = parse([":=:準備書面", "--:", "->前文", "->2本文", "+81 3-1234-5678", "+ 項目", "＋２ 全角", "->2 1. 番号にしない",
                "<<<<", "<<< 改ページ", "[toc]", "[TOC：２]", "[目次]"], SAIBAN)
    assert [(p.align, p.text) for p in ps[:1]] == [("justify", ":=:準備書面")]
    assert (ps[1].align, ps[1].text) == (RIGHT, "")                 # 中身のない右揃えの行
    assert [p.text for p in ps[2:7]] == ["->前文", "->2本文", "+81 3-1234-5678", "+ 項目", "＋２ 全角"]
    assert [p.left_indent for p in ps[2:8]] == [None, None, None, None, None, 2]
    assert ps[7].text == "1. 番号にしない" and ps[7].kind == BODY
    assert [p.kind for p in ps[8:]] == [BODY, BODY, TOC, TOC, BODY]
    assert [p.level for p in ps[10:12]] == [3, 2]


def test_leading_space_becomes_indent_before_first_heading():
    ps = parse(["　　前文", "  半角", "# 見出し", "　本文"], SAIBAN)
    assert (ps[0].text, ps[0].first_indent) == ("前文", 2)
    assert (ps[1].text, ps[1].first_indent) == ("半角", 1)
    # 見出しの後の本文は、VA公用文と同じくインデントを付け直す（行頭の空白は取り除く）
    assert ps[3].text == "本文" and ps[3].body_level == 1


def test_stop_after_right_aligned():
    """見出しの後に右揃えの段落が来たら、次のセクション区切りまで変換しない（VA公用文と同じ）。"""
    ps = parse(["# 主張", "本文", "--: 以上", "# 別紙の見出し", "- 項目", "<<<=", "# 新しい見出し"],
               SAIBAN)
    assert [(p.kind, p.text, p.body_level) for p in ps[3:5]] == [(BODY, "# 別紙の見出し", 0), (BODY, "- 項目", 0)]
    # セクション区切りの後は、変換を再開し、番号を第１から振り直す
    assert (ps[6].kind, ps[6].number) == (HEADING, "第１　")


def test_page_break_keeps_numbering():
    ps = parse(["# 一", "<<<", "# 二"], SAIBAN)
    assert [p.number for p in ps if p.kind == HEADING] == ["第１　", "第２　"]


def test_layout_page_and_section_breaks_and_blank():
    ts = Typesetter(SAIBAN)
    lines = ts.layout(parse(["一", "", "二", "<<<", "三", "<<<", "<<<=", "四"],
                            SAIBAN))
    assert [(ln.page, ln.row, "".join(g.ch for g in ln.glyphs)) for ln in lines] == [
        (1, 0, "一"), (1, 2, "二"), (2, 0, "三"), (3, 0, "四")]


def test_leading_space_indent_in_layout():
    ts = Typesetter(SAIBAN)
    lines = ts.layout(parse(["　前文", "# 見出し"], SAIBAN))
    assert lines[0].glyphs[0].x == ts.pitch


def test_empty_aligned_line_takes_a_row_and_stops_conversion():
    """--: だけの行は、Word の空の右揃えの段落と同じく1行使い、そこから先は変換しない（VA公用文と同じ）。"""
    ts = Typesetter(SAIBAN)
    ps = parse(["# 認否", "認める。", "--: ", "別紙", "# 見出しにしない"], SAIBAN)
    assert [(p.kind, p.text, p.body_level) for p in ps[3:]] == [(BODY, "別紙", 0), (BODY, "# 見出しにしない", 0)]
    lines = ts.layout(ps)
    assert [(ln.row, "".join(g.ch for g in ln.glyphs)) for ln in lines] == [
        (0, "第１　認否"), (1, "認める。"), (3, "別紙"), (4, "# 見出しにしない")]


def test_full_width_space_indents_first_line():
    """字下げは行頭の全角空白で書く（2026-10-28 班長決定。それまでの -> はなくした）。最初の見出しより前、右揃えの
    段落の後、->N の段落では1行目だけを1字下げ、見出しの後の本文では取り除いてインデントを付け直す。"""
    ts = Typesetter(SAIBAN)
    long = "前文" * 40
    ps = parse(["　" + long, "# 見出し", "　本文", "--: 以上", "　別紙", "->2 　別紙の段落", "<<<=", "　後の前文"],
               SAIBAN)
    assert (ps[0].text, ps[0].first_indent) == (long, 1)
    lines = ts.layout(ps)
    first, second = lines[0], lines[1]
    assert first.glyphs[0].x == ts.pitch and second.glyphs[0].x == 0
    assert (ps[2].text, ps[2].body_level) == ("本文", 1)
    assert (ps[4].kind, ps[4].text, ps[4].body_level, ps[4].first_indent) == (BODY, "別紙", 0, 1)
    assert (ps[5].text, ps[5].left_indent, ps[5].first_indent) == ("別紙の段落", 2, 1)
    assert (ps[7].text, ps[7].body_level, ps[7].first_indent) == ("後の前文", 0, 1)
    row = [ln for ln in ts.layout(ps) if "".join(g.ch for g in ln.glyphs) == "別紙"][0]
    assert row.glyphs[0].x == ts.pitch


def test_old_first_line_mark_is_text():
    """前の版の -> は読み替えず、字として残す。見出しの後に書いても、変換は止めない（2026-10-28 班長指示）。"""
    ps = parse(["-> 前文", "# 見出し", "-> 本文", "# 二"], SAIBAN)
    assert (ps[0].text, ps[0].first_indent) == ("-> 前文", 0)
    assert (ps[2].kind, ps[2].text, ps[2].body_level) == (BODY, "-> 本文", 1)
    assert (ps[3].kind, ps[3].number) == (HEADING, "第２　")
