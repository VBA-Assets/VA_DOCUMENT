"""段落の先頭の番号の読み取り（VA疑似アウトラインの［マークダウンに変換］を取り込んだもの。pseudo_outline.py）。"""
from va_document.doctypes import DOC_TYPES, doc_type_for
from va_document.pseudo_outline import BULLET, COMPOSITE, HEADING, NUMBER, Outliner


def read(key, texts, one_width=False):
    """段落を上から読み、[(種類, レベル, 本文)] を返す（記号にしない段落は None）。"""
    o = Outliner(doc_type_for(key, one_width))
    out = []
    for t in texts:
        m = o.classify(t)
        out.append(None if m is None else (m.kind, m.level, t[m.end:]))
        o.accept(m)
    return out


def test_saiban_levels():
    """裁判所提出書類の番号の形（第１・１・(1)・ア・(ｱ)・a・(a)・i・(i)）を、組むときと同じレベルにする。"""
    got = read("Saiban", ["第１　総論", "１　当事者", "(1) 原告", "ア　経緯", "(ｱ) 出席者", "a　部長", "(a) 権限",
                          "i　議事録", "(i) 作成日"])
    assert got == [(HEADING, 1, "総論"), (HEADING, 2, "当事者"), (HEADING, 3, "原告"), (HEADING, 4, "経緯"),
                   (HEADING, 5, "出席者"), (HEADING, 6, "部長"), (HEADING, 7, "権限"), (HEADING, 8, "議事録"),
                   (HEADING, 9, "作成日")]


def test_width_of_numbers_and_spaces_does_not_matter():
    """数字・括弧・空白の全角と半角、半角のカタカナの違いは同じとみる。"""
    got = read("Saiban", ["第1 総論", "1 当事者", "（１）　原告", "（ア）経緯"])
    assert [g[1] for g in got] == [1, 2, 3, 5]


def test_numbers_must_follow_the_order():
    """組んだときに付く番号と違う番号（飛んだ番号・振り直し）は、見出しにせず字のまま残す。"""
    got = read("Saiban", ["第１　総論", "第３　飛んだ番号", "第２　次", "２　同じレベルの２つ目から"])
    assert got[1] is None and got[2] == (HEADING, 1, "次") and got[3] is None


def test_text_after_the_number_is_not_a_number():
    """「１件目」「2026年」「第10」のように、番号の後ろに字が続くものは番号とみない。番号だけの段落も見出しにしない。"""
    assert read("Saiban", ["第１回の期日", "第１０　総論"]) == [None, None]
    assert read("Saiban", ["第１　総論", "１件目は", "2026年"]) == [(HEADING, 1, "総論"), None, None]
    assert read("Saiban", ["第１"]) == [None]


def test_composite_headings():
    """複合見出し（１(1) 当事者、第１　１　当事者）は、外側のレベルにまとめた見出しとして読む。"""
    o = Outliner(DOC_TYPES["Saiban"])
    m = o.classify("第１　１　当事者")
    assert (m.kind, m.level, m.depth) == (COMPOSITE, 1, 2)
    o.accept(m)
    m = o.classify("２(1)ア　契約")
    assert (m.kind, m.level, m.depth, "２(1)ア　契約"[m.end:]) == (COMPOSITE, 2, 3, "契約")
    o.accept(m)
    assert o.current == 4 and o.classify("イ　次") is not None


def test_contract_and_technical_numbers():
    """契約書の「第１条」（後ろに空白を置かない番号）と、技術文書の「1.1.」も読む。"""
    assert read("Keiyaku2", ["第１条（目的）", "１　甲は", "(1) 会計"]) == [
        (HEADING, 1, "（目的）"), (HEADING, 2, "甲は"), (HEADING, 3, "会計")]
    assert read("Technical", ["1.概要", "1.1.範囲", "2.準備"]) == [
        (HEADING, 1, "概要"), (HEADING, 2, "範囲"), (HEADING, 1, "準備")]


def test_lists():
    """箇条書き（・）と段落番号（①②…。前の段落が段落番号でなければ①から）。"""
    got = read("Saiban", ["・項目", "①　一つ目", "②　二つ目", "③の後に続く字"])
    assert got == [(BULLET, 0, "項目"), (NUMBER, 0, "一つ目"), (NUMBER, 0, "二つ目"), None]
    assert read("Saiban", ["②　途中から"]) == [None]


def test_nothing_after_right_aligned_paragraph():
    """見出しの後に右揃えの段落（「以上」）が来たら、そこから先は記号にしない（VA公用文と同じ）。"""
    o = Outliner(DOC_TYPES["Saiban"])
    o.accept(o.classify("第１　総論"))
    o.accept(None, align_right=True)
    assert o.stopped and o.classify("第２　別紙") is None
    o.section_break()
    assert o.classify("第１　別紙").level == 1


def test_alphabet_i_and_roman_i():
    """「i」は、いまのレベルの1つ下までで、いちばん深いもの（(a) の後ならローマ数字の i）にする。"""
    got = read("Saiban", ["第１　x", "１　x", "(1) x", "ア　x", "(ｱ) x", "a　x", "(a) x", "i　ローマ"])
    assert got[-1] == (HEADING, 8, "ローマ")
