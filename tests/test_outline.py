"""ナビゲーションの見出しと、見出しの範囲の操作（outline.py。2026-11-24 班長指示）。"""
from va_document import outline
from va_document.doctypes import DOC_TYPES

SAIBAN = DOC_TYPES["Saiban"]

DOC = """:=: 準備書面

## 当事者
本文１

### 原告
原告の本文

### 被告
被告の本文

## 請求
本文２

--: 以上
"""


def heads(text):
    return outline.headings(text.split("\n"), SAIBAN)


def lines(text):
    return text.split("\n")


def test_headings_tree_and_range():
    """見出しを上から並べ、組んだときと同じ番号を付ける。範囲は次の同じか上のレベルの見出しの手前まで、ただし
    右揃えの段落（「以上」）の手前で終わる。"""
    hs = heads(DOC)
    assert [(h.level, h.label, h.parent) for h in hs] == [
        (2, "１　当事者", -1), (3, "(1) 原告", 0), (3, "(2) 被告", 0), (2, "２　請求", -1)]
    ls = lines(DOC)
    assert ls[hs[0].end] == "## 請求"                 # 下のレベルの見出しを含む
    assert ls[hs[1].end] == "### 被告"
    assert ls[hs[3].end] == "--: 以上" and hs[3].last    # 「以上」はどの見出しにも属さない
    assert not hs[0].last and hs[2].last is False
    # カーソルのある見出しは、いちばん下のレベルのもの
    assert outline.heading_at(hs, ls.index("原告の本文")) == 1
    assert outline.heading_at(hs, ls.index("本文１")) == 0
    assert outline.heading_at(hs, 0) == -1 and outline.heading_at(hs, ls.index("--: 以上")) == -1


def test_headings_skip_lines_that_are_not_headings():
    """右揃えの段落の後の #、->N の行、ヘッダーの行は、組むときと同じく見出しにしない。字のない見出しは、番号だけを出す。"""
    hs = heads("## 見出し\n->2 ## 字\n[HEADER] ## 字\n#\n## 複合\n--: 以上\n## 後ろ")
    assert [h.label for h in hs] == ["１　見出し", "第１", "１　複合"]
    assert heads("##")[0].label == "１"                    # 字のない見出しは、番号だけ


def test_section_break_ends_range():
    """セクション区切りで範囲が終わる。区切りをまたいで親子にしない。"""
    hs = heads("# 一\n本文\n<<<=\n## 二\n本文")
    assert [(h.label, h.parent, h.end) for h in hs] == [("第１　一", -1, 2), ("１　二", -1, 5)]


def test_move_keeps_blank_line_before_headings():
    """見出しを範囲ごと動かす。見出しの前を1行あけた書き方で、入れ替えても空行が崩れない。"""
    text = "前文\n\n## Ａ\n本文Ａ\n\n## Ｂ\n本文Ｂ\n\n## Ｃ\n本文Ｃ\n"
    hs = heads(text)
    # 最後の見出しを前へ（後ろの空行〔文書の終わりの改行〕は残し、前の空行と一緒に動かす）
    new, at = outline.move(lines(text), hs, 2, hs[1].line)
    assert "\n".join(new) == "前文\n\n## Ａ\n本文Ａ\n\n## Ｃ\n本文Ｃ\n\n## Ｂ\n本文Ｂ\n"
    assert new[at] == "## Ｃ"
    # 最初の見出しを最後へ
    new, at = outline.move(lines(text), hs, 0, hs[2].end)
    assert "\n".join(new) == "前文\n\n## Ｂ\n本文Ｂ\n\n## Ｃ\n本文Ｃ\n\n## Ａ\n本文Ａ\n"
    assert new[at] == "## Ａ"
    # 自分の範囲の中へは動かさない
    assert outline.move(lines(text), hs, 1, hs[1].line) is None
    assert outline.move(lines(text), hs, 1, hs[1].end) is None


def test_move_carries_lower_levels_and_stops_before_closing():
    """下のレベルの見出しと本文も一緒に動き、「以上」は動かない。"""
    hs = heads(DOC)
    new, at = outline.move(lines(DOC), hs, 3, hs[0].line)
    assert "\n".join(new) == (":=: 準備書面\n\n## 請求\n本文２\n\n## 当事者\n本文１\n\n### 原告\n原告の本文\n\n"
                              "### 被告\n被告の本文\n\n--: 以上\n")
    assert new[at] == "## 請求"
    # 同じ親の前後の見出しとの入れ替え（Alt+Shift+↑↓）
    assert outline.move_target(hs, 2, -1) == hs[1].line
    assert outline.move_target(hs, 1, -1) is None          # 親の中の最初
    assert outline.move_target(hs, 2, 1) is None           # 親の中の最後
    new, _ = outline.move(lines(DOC), hs, 1, outline.move_target(hs, 1, 1))
    assert new.index("### 被告") < new.index("### 原告") < new.index("## 請求")


def test_delete_section():
    hs = heads(DOC)
    new, at = outline.delete(lines(DOC), hs, 0)
    assert "\n".join(new) == ":=: 準備書面\n\n## 請求\n本文２\n\n--: 以上\n"
    assert new[at] == "## 請求"
    new, _ = outline.delete(lines(DOC), hs, 3)           # 最後の見出しは、前の空行と一緒に消す
    assert "\n".join(new).endswith("被告の本文\n\n--: 以上\n")


def test_shift_level_of_section():
    """レベルの上げ下げは、範囲に入る見出しにも及ぶ。# より上・######### より下になるときは何もしない。"""
    hs = heads(DOC)
    new, changed = outline.shift_level(lines(DOC), hs, 0, 1)
    assert [new[n] for n in changed] == ["### 当事者", "#### 原告", "#### 被告"]
    assert new[hs[3].line] == "## 請求"
    assert outline.shift_level(lines("# 一\n## 二"), heads("# 一\n## 二"), 0, -1) is None
    assert outline.shift_level(lines("#########  九"), heads("######### 九"), 0, 1) is None


def test_set_heading_level_keeps_marks():
    assert outline.set_heading_level(":-: ## 見出し", 3) == ":-: ### 見出し"
    assert outline.set_heading_level("**## 見出し**", 1) == "# **見出し**"
    assert outline.set_heading_level("　## 見出し", 4) == "　#### 見出し"
    assert outline.set_heading_level("##", 3) == "###"
    assert outline.set_heading_level("本文", 3) == "本文"


def test_insert_heading_before_after_and_child():
    """見出しの前・後（範囲の後）・小見出し（範囲の最後の小見出し）に、字のない見出しを入れる。空行はまわりにならい、
    「以上」の前の空行は残す（2026-11-24 班長決定）。"""
    hs = heads(DOC)
    new, at = outline.insert_heading(lines(DOC), hs, 3, outline.BEFORE)       # 「請求」の前
    assert new[at] == "## " and new[at - 1] == "" and new[at + 1] == "" and new[at + 2] == "## 請求"
    new, at = outline.insert_heading(lines(DOC), hs, 0, outline.AFTER)        # 「当事者」の範囲の後
    assert new[at - 2:at + 3] == ["被告の本文", "", "## ", "", "## 請求"]
    new, at = outline.insert_heading(lines(DOC), hs, 3, outline.AFTER)        # 最後の見出しの後（「以上」の前）
    assert new[at - 2:] == ["本文２", "", "## ", "", "--: 以上", ""]
    new, at = outline.insert_heading(lines(DOC), hs, 0, outline.CHILD)        # 小見出し：最後の小見出しの後
    assert new[at] == "### " and new[at - 2:at] == ["被告の本文", ""] and new[at + 2] == "## 請求"
    new, at = outline.insert_heading(lines(DOC), hs, 3, outline.CHILD)        # 小見出しのない見出し：空行なし
    assert new[at - 1:at + 1] == ["本文２", "### "]
    nine = "######### 九"
    assert outline.insert_heading([nine], heads(nine), 0, outline.CHILD) is None
    # 見出しと本文の範囲（後ろの空行を除く）
    assert lines(DOC)[outline.section_end(lines(DOC), hs[0]) - 1] == "被告の本文"
