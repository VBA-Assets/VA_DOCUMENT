"""行番号（VA公用文と同じ：5行ごと、ページごとに 1 から、表の中の行は数えない。2026-10-24 班長指示）。"""
import pdfcheck
from va_document import vamd
from va_document.doctypes import DOC_TYPES
from va_document.document import parse
from va_document.layout import Typesetter
from va_document.pdfwriter import LINE_NUMBER_LAST_X, pdf_bytes
from va_document.recover import rebuild_dictionary

DT = DOC_TYPES["Saiban"]


def left_numbers(data, ts):
    """本文の左の余白の字を、基準線ごとにまとめたもの。ページごとに [(字, [字の左端], 基準線, 字の大きさ)]（描いた順）。"""
    out = []
    for chars in pdfcheck.all_chars(data):
        groups = {}
        for c in chars:
            if c["x"] < ts.margin_left - 1:
                groups.setdefault(round(c["y"], 2), []).append(c)
        out.append([("".join(c["text"] for c in cs), [c["x"] for c in cs], cs[0]["y"], cs[0]["size"])
                    for cs in groups.values()])
    return out


def numbers(data, ts):
    """PDF の行番号 [(ページ, 番号, 基準線の y)]。"""
    return [(k + 1, int(text), round(y, 2)) for k, page in enumerate(left_numbers(data, ts))
            for text, _, y, _ in page if text.isdigit()]


def test_every_fifth_line_counting_blank_lines_not_table_rows():
    text = ["一行目"] + [""] * 2 + ["四行目", "五行目", "| 表 | 表 |", "|---|---|", "| 中 | 中 |", "六行目"] + [f"行{k}" for k in range(7, 12)]
    ts = Typesetter(DT)
    paras = parse(text, DT)
    lines = ts.layout(paras)
    found = numbers(pdf_bytes(ts, lines, line_numbers=True), ts)
    rows = {"".join(g.ch for g in ln.glyphs): ln.row for ln in lines}
    # 空の段落も1行と数え、表の中の行は数えない
    assert [(p, n) for p, n, _ in found] == [(1, 5), (1, 10)]
    assert found[0][2] == round(ts.baseline(rows["五行目"]), 2)
    assert found[1][2] == round(ts.baseline(rows["行10"]), 2)
    assert not numbers(pdf_bytes(ts, lines), ts)          # 付けない設定では付けない


def test_numbers_restart_on_each_page_and_align_right():
    text = [f"段落{k}" for k in range(1, 30)]
    ts = Typesetter(DT)
    lines = ts.layout(parse(text, DT))
    data = pdf_bytes(ts, lines, line_numbers=True)
    found = numbers(data, ts)
    per_page = ts.lines_page // 5
    assert [n for p, n, _ in found if p == 1] == [5 * k for k in range(1, per_page + 1)]
    assert [n for p, n, _ in found if p == 2] == [5 * k for k in range(1, (29 - ts.lines_page) // 5 + 1)]
    last = [xs[-1] for _, xs, _, _ in left_numbers(data, ts)[0]]
    assert last and all(abs(x - (ts.margin_left - LINE_NUMBER_LAST_X)) < 0.01 for x in last)    # 右をそろえる


def test_rebuild_ignores_line_numbers(tmp_path):
    """行番号は本文の左の余白にあるので、構文ファイルと PDF の突き合わせに入れない。"""
    from va_document.pdfwriter import write_pdf
    from va_document.pseudonym import Dictionary
    real = ["原告　甲野太郎"] + [f"甲野太郎の主張{k}は争う。" for k in range(12)]
    d = Dictionary()
    d.register("甲野太郎", "人名")
    ts = Typesetter(DT)
    lines = ts.layout(parse(real, DT))
    pdf = tmp_path / "a.pdf"
    write_pdf(ts, lines, str(pdf), "K7Q29XMD", 1, line_numbers=True)
    settings = vamd.Settings("Saiban", line_numbers=True)
    content = vamd.parse_text(vamd.build("K7Q29XMD", 1, settings, d.pseudonymize("\n".join(real))))
    rebuilt, r = rebuild_dictionary(content, pdf)
    assert r.exact and not r.missing
    assert rebuilt.restore(content.body_text)[0] == "\n".join(real)


# 班長が VA公用文で作った PDF（試作\出力\VA公用文_行番号.pdf。tests\data\裁判所\見本.md と同じ文書・配置、裁判所提出書類・下中央・行番号を表示）の
# 1ページ目の行番号：(番号, 各数字の左端の x, 基準線の y)。2ページ目も同じ、3ページ目は5行に満たないので番号なし（2026-10-24）
WORD_NUMBERS = [(5, [62.9], 218.78), (10, [58.68, 62.88], 346.85), (15, [58.68, 62.88], 474.79),
                (20, [58.68, 62.88], 602.83), (25, [58.68, 62.88], 730.9)]


def test_line_numbers_match_va_kouyoubun():
    """行番号の字の位置が、VA公用文の PDF と左右 0.1pt 以内で一致する（字の大きさも同じ）。上下は、Word でも行番号は
    本文の行の基準線にあり、本文の行の位置の違い（0.06〜0.18pt。字の上下の位置の比較で分かっているもの）だけずれる。"""
    from pathlib import Path
    text = (Path(__file__).resolve().parent / "data" / "裁判所" / "見本.md").read_text(encoding="utf-8").splitlines()
    ts = Typesetter(DT, keep=False)     # VA公用文の PDF と比べるので、見出しと本文を分けない処理をしない
    data = pdf_bytes(ts, ts.layout(parse(text, DT)), line_numbers=True)
    pages = left_numbers(data, ts)
    assert len(pages) == 3
    for k, page in enumerate(pages):
        found = [(int(text), xs, y, size) for text, xs, y, size in page]
        want = WORD_NUMBERS if k < 2 else []
        assert [n for n, *_ in found] == [n for n, *_ in want]
        for (n, xs, y, size), (_, wxs, wy) in zip(found, want):
            assert all(abs(a - b) < 0.1 for a, b in zip(xs, wxs)) and abs(y - wy) < 0.2 and abs(size - 8.04) < 0.01

