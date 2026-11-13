"""目次（[TOC]）を、VA公用文で整えた文書に Word の「自動作成の目次 1」を入れたものと比べる（2026-10-24）。

正解は、試作\\Make-VaKouyoubunPdf.ps1 -Toc で、別の Word から読み取った（tests\\data\\目次）。
Word の目次には題の行（「内容」）と、目次の後の空の行2つが入るので、見本にも同じ行を入れて比べる
（VA Documentの目次は題を付けない。2026-10-24 班長決定）。
・項目の文字列・ページ番号・行・ページは、すべて一致すること。
・字の左右の位置は 1pt 以内（1字目は Word の読み取りが崩れることがあるので、2字目から比べる）。
  ただし、折り返した見出しは、Word と組み方を変えたので（2026-10-24 班長決定）、Word とは比べず、
  1行目も両端揃えにせず格子どおり並び、2行目以降は1字ぶら下げであること（Word の目次は1行目が両端揃えで、ぶら下げなし）。
・点線の点とページ番号の位置は、班長が VA公用文で作った目次入りの PDF（VA公用文_目次.pdf。作成者の名前は消した）と比べる。
"""
import collections
import json
import re
from pathlib import Path

import pdfcheck
from va_document import vamd
from va_document.cleanup import clean
from va_document.doctypes import DOC_TYPES
from va_document.document import TOC, parse
from va_document.layout import TOC_TAB_FROM_RIGHT, Typesetter
from va_document.pdfwriter import pdf_bytes

DATA = Path(__file__).parent / "data" / "目次"


def test_toc_matches_va_kouyoubun():
    dt = DOC_TYPES["Saiban"]
    ts = Typesetter(dt, keep=False)     # VA公用文と比べるので、見出しと本文を分けない処理をしない
    paras = parse(clean((DATA / "見本.md").read_text(encoding="utf-8"))[0].splitlines(), dt)
    lines = ts.layout(paras)
    toc_pi = next(k for k, p in enumerate(paras) if p.kind == TOC)
    entries, cur = [], []
    for ln in (ln for ln in lines if ln.para_index == toc_pi):
        cur.append(ln)
        if any(g.is_number and g.ch.isdigit() for g in ln.glyphs):
            entries.append(cur)
            cur = []
    info = json.loads((DATA / "VA公用文_段落.json").read_text(encoding="utf-8-sig"))
    chars = json.loads((DATA / "VA公用文_字の位置.json").read_text(encoding="utf-8-sig"))
    by = collections.defaultdict(list)
    for c in chars:
        by[c["para"]].append(c)
    word = [k for k, p in enumerate(info["paragraphs"], 1) if p["style"].startswith("目次 ")]
    assert len(word) == len(entries) == 85
    assert max(ln.page for ln in lines) == info["pages"] == 18
    left = info["page"]["left"]
    worst, wrapped = 0.0, 0
    for k, ent in zip(word, entries):
        wtext, wpage = info["paragraphs"][k - 1]["text"].split("\t")
        glyphs = [(ln, g) for ln in ent for g in ln.glyphs if not g.is_number]
        assert "".join(g.ch for _, g in glyphs) == wtext
        assert "".join(g.ch for ln in ent for g in ln.glyphs if g.is_number and g.ch.isdigit()) == wpage
        wc = [c for c in by[k] if c["c"] not in (None, "\t")][:len(wtext)]
        texts = [[g for g in ln.glyphs if not g.is_number] for ln in ent]
        if wrapped_entry(texts):
            # 折り返した見出し：どの行も字の送りどおり（両端揃えなし）、2行目以降は1行目の書き出しより1字右から
            wrapped += 1
            for t in texts:
                for a, b in zip(t, t[1:]):
                    assert abs(b.x - a.x - ts.advance(a.ch)) < 0.01
            for t in texts[1:]:
                assert not t or abs(t[0].x - texts[0][0].x - ts.pitch) < 0.01
        for j in range(1, min(len(glyphs), len(wc))):
            ln, g = glyphs[j]
            if not wrapped_entry(texts):
                worst = max(worst, abs(left + g.x - wc[j]["xs"]))
            top = ts.margin_top + ln.row * ts.line_pitch
            assert wc[j]["page"] == ln.page and top - 1 <= wc[j]["ys"] <= top + ts.line_pitch + 1
    assert worst <= 1.0, worst
    assert wrapped >= 3


def wrapped_entry(texts):
    return len([t for t in texts if t]) > 1


def test_toc_lists_headings_up_to_level_3_with_page_numbers():
    dt = DOC_TYPES["Saiban"]
    ts = Typesetter(dt)
    paras = parse(["[TOC]", "<<<", "# 第一", "## 小", "### 細", "#### 載せない", "<<<", "# 第二"], dt)
    lines = ts.layout(paras)
    toc = [ln for ln in lines if ln.para_index == 0]
    texts = ["".join(g.ch for g in ln.glyphs if not g.is_number) for ln in toc]
    nums = ["".join(g.ch for g in ln.glyphs if g.is_number and g.ch.isdigit()) for ln in toc]
    assert texts == ["第１ 第一", "１ 小", "(1) 細", "第２ 第二"]
    assert nums == ["2", "2", "2", "3"]
    # 点線は見出しの後からページ番号の手前まで。ページ番号は本文の右端（から TOC_TAB_FROM_RIGHT 左）にそろう
    dots = [g for g in toc[0].glyphs if g.ch == "."]
    assert dots and dots[0].x > toc[0].glyphs[4].x
    digit = [g for g in toc[0].glyphs if g.ch.isdigit()][-1]
    assert abs(digit.x + ts.advance(digit.ch) - (ts.text_w - TOC_TAB_FROM_RIGHT)) < 0.01


def test_toc_wrapped_line_hangs_one_char():
    """目次の折り返した行は、本文の見出しと同じく1字ぶら下げ（1行目の書き出しより1字右から）。"""
    dt = DOC_TYPES["Saiban"]
    ts = Typesetter(dt)
    long = "長い見出し" * 12
    paras = parse(["[TOC]", "# 第一", "### " + long], dt)
    lines = ts.layout(paras)
    toc = [ln for ln in lines if ln.para_index == 0]
    first, second = toc[1], toc[2]          # (1) の段の項目の1行目と2行目
    assert first.glyphs[0].ch == "(" and abs(first.glyphs[0].x - 2 * ts.pitch) < 0.01
    assert abs(second.glyphs[0].x - 3 * ts.pitch) < 0.01


def pdf_rows(pdf):
    """PDF のページごとの行 {基準線の位置: [(字, 左端)]}。"""
    out = []
    for page in pdfcheck.all_chars(pdf):
        rows = collections.defaultdict(list)
        for c in page:
            if c["text"].strip():
                rows[round(c["y"])].append((c["text"], c["x"]))
        out.append({y: sorted(v, key=lambda c: c[1]) for y, v in rows.items()})
    return out


def test_toc_leader_matches_va_kouyoubun_pdf():
    """目次の点線は、Word と同じく「.」を用紙の左端から決まった間隔で、見出しの最後の字より右のますから
    ページ番号の手前のますまで並べる。班長が VA公用文で作った PDF と、点・ページ番号の位置が 0.25pt 以内で合うこと。
    折り返した見出しの2行目は、1字ぶら下げにしたので（Word はぶら下げなし）、点の数が違ってよい。"""
    dt = DOC_TYPES["Saiban"]
    ts = Typesetter(dt, keep=False)     # 同上
    lines = ts.layout(parse(clean((DATA / "見本.md").read_text(encoding="utf-8"))[0].splitlines(), dt))
    ro, rw = pdf_rows(pdf_bytes(ts, lines)), pdf_rows(DATA / "VA公用文_目次.pdf")
    assert len(ro) == len(rw) == 18
    compared, worst = 0, 0.0
    for po, pw in zip(ro, rw):
        for y, sw in pw.items():
            if not re.search(r"\.\d+$", "".join(c for c, _ in sw)):
                continue                                    # 目次の項目の最後の行（点線＋ページ番号）だけ
            so = po[y]
            if abs(so[0][1] - sw[0][1]) > ts.pitch / 2:
                assert abs(so[0][1] - sw[0][1] - ts.pitch) < 1      # 1字ぶら下げの行
                continue
            assert "".join(c for c, _ in so) == "".join(c for c, _ in sw)
            for (c, xo), (_, xw) in zip(so, sw):
                if c == "." or xw > 500:
                    worst = max(worst, abs(xo - xw))
            compared += 1
    assert compared >= 75
    assert worst <= 0.25, worst

def test_toc_levels_can_be_given_in_the_mark():
    """[TOC:2] のように段を書き添えると、その段までを載せる（2026-10-24 班長指示。全角のコロン・数字も読む）。"""
    dt = DOC_TYPES["Saiban"]
    ts = Typesetter(dt)
    body = ["<<<", "# 第一", "## 小", "### 細", "#### 四段", "##### 五段"]

    def toc_texts(mark):
        paras = parse([mark] + body, dt)
        assert paras[0].kind == TOC
        return ["".join(g.ch for g in ln.glyphs if not g.is_number) for ln in ts.layout(paras) if ln.para_index == 0]
    assert toc_texts("[TOC]") == ["第１ 第一", "１ 小", "(1) 細"]
    assert toc_texts("[TOC:1]") == ["第１ 第一"]
    assert toc_texts("[TOC：２]") == ["第１ 第一", "１ 小"]
    assert toc_texts("[TOC:4]") == ["第１ 第一", "１ 小", "(1) 細", "ア 四段"]
    # 段が 1〜9 でなければ記号ではない（そのまま本文になる）
    assert parse(["[TOC:0]"], dt)[0].kind != TOC
    assert vamd.is_line_mark(" [TOC:2] ") and not vamd.is_line_mark("[TOC:10]")