"""複合見出し（字のない見出しの行のすぐ後の見出しを1行にまとめる。VA疑似アウトラインと同じ。2026-10-24 班長指示）。"""
from va_document import config
from va_document.doctypes import DOC_TYPES, doc_type_for
from va_document.document import HEADING, parse
from va_document.layout import Typesetter
from va_document.session import Session

DT = DOC_TYPES["Saiban"]
LONG = "当事者は、長い見出しを折り返すと、２行目はまとめた段の数だけ右から始まる。"
SRC = ["[TOC]", "#", "## " + LONG, "本文。", "## 請求の原因", "#", "##", "### 三段まとめ", "本文。"]


def lines_by_para(src, dt=DT):
    ts = Typesetter(dt)
    paras = parse(src, dt)
    out = {}
    for ln in ts.layout(paras):
        out.setdefault(ln.para_index, []).append(ln)
    return ts, paras, out


def test_composite_heading_is_one_line():
    ts, paras, by = lines_by_para(SRC)
    assert [p.composite for p in paras] == [False, True, False, False, False, True, True, False, False]
    assert 1 not in by and 5 not in by and 6 not in by                  # 字のない見出しは行にしない
    first, second = by[2]
    assert "".join(g.ch for g in first.glyphs).startswith("第１　１　当事者")
    assert first.glyphs[0].x == 0 and round(second.glyphs[0].x / ts.pitch, 3) == 2   # 第１の段の折り返し（1字）＋1字
    assert all(g.is_number for g in first.glyphs[:5]) and not first.glyphs[5].is_number     # 「第１　１　」が番号
    assert "".join(g.ch for g in by[7][0].glyphs).startswith("第２　１(1) 三段まとめ")
    # 番号は、まとめた後も続く（「２　請求の原因」は第１の段の中の２番目）
    assert "".join(g.ch for g in by[4][0].glyphs) == "２　請求の原因"


def test_outer_number_space_removed():
    """外側の番号の後の全角空白を1つ取り除いてつなぐ（「１(1) 見出し」。VA疑似アウトラインと同じ。2026-10-26 班長指摘）。
    「第」で始まる番号は空白を残し（2026-10-26 班長決定）、半角空白（「(3) 」）も残す。［番号1字］を付けない文書では、
    複合見出しでも番号を縮めない（2026-10-26 班長指示）。"""
    src = ["##", "### 見出し", "### 見出し", "", "###", "#### 見出し", "#### 見出し"]
    ts, paras, by = lines_by_para(src)
    assert "".join(g.ch for g in by[1][0].glyphs) == "１(1) 見出し"
    assert [round(g.x / ts.pitch, 3) for g in by[1][0].glyphs] == [0, 1, 1.5, 2, 2.5, 3, 4, 5]
    assert "".join(g.ch for g in by[2][0].glyphs) == "(2) 見出し"
    assert "".join(g.ch for g in by[5][0].glyphs) == "(3) ア　見出し"
    ts, paras, by = lines_by_para(["#", "##", "###", "#### 見出し", "####", "##### 見出し"])
    assert "".join(g.ch for g in by[3][0].glyphs) == "第１　１(1) ア　見出し"
    assert "".join(g.ch for g in by[5][0].glyphs) == "イ(ｱ) 見出し"
    assert all(g.scale == 1 for k in by for ln in by[k] for g in ln.glyphs)        # どの字も縮めない


def test_one_width_composite_squeezed():
    """［番号1字］の文書の複合見出しは、段ごとの番号を全角1字の幅に縮めてつなぐ（「(3)ア　見出し」）。括弧の番号は、
    括弧をそれぞれ 1/4 字、中の字に残りの 1/2 字を分ける（2026-10-26 班長決定・班長指示）。"""
    dt = doc_type_for("Saiban", True)
    ts, paras, by = lines_by_para(["#", "##", "###", "#### 見出し", "####", "##### 見出し"], dt)
    line = by[3][0]
    assert "".join(g.ch for g in line.glyphs) == "第１１(1)ア　見出し"
    xs = [round(g.x / ts.pitch, 3) for g in line.glyphs]
    assert xs[2:9] == [1, 2, 2.25, 2.75, 3, 4, 5]                         # 第１・１・(1)・ア が1字ずつ
    assert [g.scale for g in line.glyphs[3:6]] == [0.5, 1.0, 0.5]       # 括弧は半角の半分、数字は半角のまま
    assert "".join(g.ch for g in by[5][0].glyphs) == "イ(ｱ)　見出し"
    ts, paras, by = lines_by_para(["###", "####", "##### 見出し"], dt)
    line = by[2][0]
    assert "".join(g.ch for g in line.glyphs) == "(1)ア(ｱ)　見出し"
    x0 = line.glyphs[0].x
    assert [round((g.x - x0) / ts.pitch, 3) for g in line.glyphs] == [0, 0.25, 0.75, 1, 2, 2.25, 2.75, 3, 4, 5, 6]


def test_squeezed_number_in_pdf(tmp_path):
    """縮めた括弧の番号は、PDF でも横の倍率を掛けて描き、字は並びのまま残る（突き合わせで読める）。"""
    import pdfcheck
    from va_document.pdfwriter import write_pdf
    ts, paras, by = lines_by_para(["###", "#### 見出し"], doc_type_for("Saiban", True))
    lines = [ln for k in sorted(by) for ln in by[k]]
    out = tmp_path / "a.pdf"
    write_pdf(ts, lines, str(out))
    assert "(1)ア　見出し" in pdfcheck.text(out, 0)
    widths = [round(c["width"], 3) for c in pdfcheck.chars(out)]
    assert widths[:4] == [3, 6, 3, 12]                                  # 縮めるのは括弧だけ（後の字に倍率を残さない）


def test_composite_heading_in_toc():
    """目次には、外側の段の1項目として載せる（字のない見出しは載せない）。"""
    ts, paras, by = lines_by_para(SRC)
    toc = ["".join(g.ch for g in ln.glyphs if not g.is_number) for ln in by[0]]
    assert toc[0].startswith("第１　１ 当事者")
    assert any(t.startswith("２ 請求の原因") for t in toc) and any(t.startswith("第２　１(1) 三段まとめ") for t in toc)
    assert by[0][0].glyphs[0].x == 0                                    # 第１の段の位置
    _, paras1, by1 = lines_by_para(["[TOC:1]", "#", "## まとめた見出し", "## 載せない"])
    assert ["".join(g.ch for g in ln.glyphs if not g.is_number) for ln in by1[0]] == ["第１　１ まとめた見出し"]


def test_not_merged_when_left_add_is_not_one():
    """左インデントの増加量が1字でない文書の種類（契約書1・技術文書）では、まとめない（VA疑似アウトラインと同じ）。"""
    for key in ("Keiyaku1", "Technical"):
        paras = parse(["#", "## 見出し"], DOC_TYPES[key])
        assert not paras[0].composite and paras[0].kind == HEADING


def test_editor_position_round_trip():
    text = "#\n## 当事者\n本文。"
    s = Session(config.AppConfig(vamd_folder="未使用"))
    s.typeset(text)
    m = s.layout_map
    for ch in "当者":
        col = text.splitlines()[1].index(ch)
        page, x, top, h = m.locate(1, col)
        assert m.hit(page, x + 1, top + h / 2) == (1, col)


def test_one_width_numbers_align():
    """見出し番号を1字の幅に縮める文書（2026-10-26 班長指示）では、まとめない見出しの番号も、複合見出しの番号も、
    すべて全角1字の幅に収め（「第１」「１１」「(11)」も）、後ろを全角空白にする。複合見出しの見出しの字は、すぐ下の
    同じレベルの見出しの字とそろう。見出しの最初の行のインデントは、どのレベルも -1 字。"""
    for key in ("Saiban", "Naiyou", "Kouyou", "Business", "Keiyaku2"):
        dt = doc_type_for(key, True)
        deepest = min(6, sum(1 for f in dt.number_formats if f))     # 契約書2 の番号はレベル4まで
        src = ["# 見出し"]
        for a in range(1, deepest):
            src += ["#" * a, "#" * (a + 1) + " 見出し", "#" * (a + 1) + " 次"]
        ts, paras, by = lines_by_para(src, dt)
        lines = [ln for k in sorted(by) for ln in by[k]]
        text_x = []
        for ln in lines:
            k = next(i for i, g in enumerate(ln.glyphs) if not g.is_number)
            text_x.append(round(ln.glyphs[k].x / ts.pitch, 3))
            assert ln.glyphs[k - 1].ch == "　"                         # 番号の後ろは全角空白
            # 番号の字は、1つの段の番号ごとに1字の幅に収まる（括弧・字は縮め、1字より狭い字は中ほどに置く）
            assert all(g.scale <= 1 for g in ln.glyphs[:k])
        assert text_x[0] == 2                                           # 第１（1字）＋空白
        for a in range(deepest - 1):
            assert text_x[1 + 2 * a] == text_x[2 + 2 * a], (key, a)     # 複合見出しと、すぐ下の見出しの字がそろう


def test_one_width_wide_numbers():
    """「第１」「１１」「(11)」も1字の幅に収める。"""
    dt = doc_type_for("Saiban", True)
    src = ["# 一"] + ["## 二"] * 11 + ["### 三"] * 11
    ts, paras, by = lines_by_para(src, dt)
    first = by[0][0].glyphs
    assert [g.ch for g in first[:3]] == ["第", "１", "　"] and [round(g.scale, 3) for g in first[:2]] == [0.5, 0.5]
    eleven = by[11][0].glyphs
    assert [g.ch for g in eleven[:3]] == ["１", "１", "　"] and round(eleven[2].x - eleven[0].x, 3) == round(ts.pitch, 3)
    paren = by[22][0].glyphs
    assert "".join(g.ch for g in paren[:5]) == "(11)　" and round(paren[4].x - paren[0].x, 3) == round(ts.pitch, 3)


def test_one_width_not_for_keiyaku1_and_technical():
    """契約書1・技術文書（左インデントの増加量が1字でないもの）では、番号1字にしない（番号が1字に収まらず、複合見出しも使えない）。"""
    for key in ("Keiyaku1", "Technical"):
        assert doc_type_for(key, True) == DOC_TYPES[key]
