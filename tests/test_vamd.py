"""構文ファイル（仕様.md の8）と、PDF との突き合わせによる対応表の作り直し（仕様.md の7）。"""
from pathlib import Path

import pytest

from va_document import vamd
from va_document.doctypes import DOC_TYPES, PAGE_NUMBER_TOP_RIGHT, doc_type_for
from va_document.document import parse
from va_document.layout import Typesetter
from va_document.pdfwriter import write_pdf
from va_document.pseudonym import Dictionary
from va_document.recover import PdfMismatch, rebuild_dictionary, recover

DATA = Path(__file__).parent / "data"
TRIAL = DATA / "AI往復試験"


# ---------- 書き出し・読み込み ----------

def test_doc_id():
    ids = {vamd.new_doc_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(len(i) == 8 and not set(i) & set("0O1I") for i in ids)
    assert vamd.file_name("K7Q29XMD") == "K7Q29XMD.vamd"


def test_build_and_read_back(tmp_path):
    settings = vamd.Settings("Keiyaku1", PAGE_NUMBER_TOP_RIGHT)
    text = vamd.build("K7Q29XMD", 3, settings, ":=: 契約書\n# 目的\n〔人名Ａ〕は、\n\n")
    sep = "==== VA Document 文書ID K7Q29XMD 版 3 種類 契約書1（法令型） ページ番号 右上 行番号 なし 番号1字 なし ===="
    assert sep in text.splitlines()
    path = tmp_path / "K7Q29XMD.vamd"
    vamd.write_file(path, text)
    c = vamd.read_file(path)
    assert (c.doc_id, c.version, c.settings) == ("K7Q29XMD", 3, settings)
    assert c.body == [":=: 契約書", "# 目的", "〔人名Ａ〕は、"]
    assert c.prompt is not None
    assert list(tmp_path.iterdir()) == [path]   # 一時ファイルが残らない
    # 行番号（2026-10-24）。行番号の書いていない区切りの行（それより前の構文ファイル）は「なし」
    on = vamd.Settings("Saiban", PAGE_NUMBER_TOP_RIGHT, True)
    assert vamd.parse_separator_line(vamd.separator_line("K7Q29XMD", 1, on))[2] == on
    assert not vamd.parse_separator_line(sep.replace(" 行番号 なし", ""))[2].line_numbers
    # 見出し番号を1字の幅にするか（2026-10-26）。書いていない区切りの行（Ver152 までの構文ファイル）は「なし」
    one = vamd.Settings("Saiban", PAGE_NUMBER_TOP_RIGHT, False, True)
    assert vamd.parse_separator_line(vamd.separator_line("K7Q29XMD", 1, one))[2] == one
    assert not vamd.parse_separator_line(sep.replace(" 番号1字 なし", ""))[2].one_width


def test_old_separator_without_settings():
    """往復試験の構文ファイル（設定のない区切りの行）も読める。"""
    c = vamd.read_file(TRIAL / "K7Q29XMD.vamd")
    assert (c.doc_id, c.version, c.settings) == ("K7Q29XMD", 1, None)
    assert c.body[0].startswith("令和８年（ワ）第〔番号Ａ〕号")
    assert c.body[-1] == "--: 以上"


@pytest.mark.parametrize("n", [1, 2, 3])
def test_trial_answers(n):
    c = vamd.read_file(TRIAL / f"回答_{n}.txt")
    assert (c.doc_id, c.version) == ("K7Q29XMD", 1)
    assert c.prompt is None
    assert c.body[-1] == "--: 以上"


def test_va_documake_separator_is_not_read():
    """Ver160 まで（VA DocuMake）の区切りの行は読まない（2026-10-27 班長決定）。"""
    with pytest.raises(vamd.NoSeparator):
        vamd.parse_text("==== VA DocuMake 文書ID K7Q29XMD 版 1 ====\n# 認否\n認める。\n")
    assert vamd.file_name("K7Q29XMD").endswith(".vamd")


def test_answer_with_preface_and_code_block():
    answer = ("ご依頼のとおり直しました。\n\n```markdown\n"
              "==== VA Document 文書ID K7Q29XMD 版 2 種類 裁判所提出書類 ページ番号 中下 ====\n"
              "# 認否\n認める。\n```\n\n記号はすべて元のまま残しています。\n")
    c = vamd.parse_text(answer)
    assert c.version == 2 and c.settings.doc_type == "Saiban"
    assert c.body == ["# 認否", "認める。"]


def test_no_separator():
    with pytest.raises(vamd.NoSeparator):
        vamd.parse_text("# 認否\n認める。\n")


# ---------- 取り込む前の確かめ ----------

def make_dictionary():
    d = Dictionary()
    d.register("甲野太郎", "人名")
    d.register("乙山商事株式会社", "法人")
    return d


CURRENT = [":=: 準備書面", "--: 令和８年９月１７日", "# 認否", "〔人名Ａ〕の主張は争う。", "<<<", "〔法人Ａ〕は認める。"]


def answer(body, version=3, doc_id="K7Q29XMD"):
    return vamd.parse_text(f"==== VA Document 文書ID {doc_id} 版 {version} ====\n" + "\n".join(body))


def test_review_same_text_is_clean():
    r = vamd.review(answer(CURRENT), "K7Q29XMD", 3, CURRENT, make_dictionary())
    assert r.clean and not r.changes


def test_review_reports_footnotes_added_by_ai():
    """AI が書いた脚注の記号（本文の [^1] と行頭の [^1]:）は、字のまま組まれるので知らせる。今の文章にもあるもの
    （利用者が書いたもの）は、増えたときだけ知らせる（2026-10-30 班長決定）。"""
    body = CURRENT[:3] + ["〔人名Ａ〕の主張は争う[^1]。"] + CURRENT[4:] + ["[^1]: 最判平成元年１月１日"]
    r = vamd.review(answer(body), "K7Q29XMD", 3, CURRENT, make_dictionary())
    assert r.footnotes == ["[^1]"] and not r.clean
    current = CURRENT[:3] + ["〔人名Ａ〕の主張は争う[^注]。"] + CURRENT[4:]
    assert vamd.review(answer(current), "K7Q29XMD", 3, current, make_dictionary()).clean
    r = vamd.review(answer(current + ["[^注]: 出典", "〔法人Ａ〕[^b]"]), "K7Q29XMD", 3, current, make_dictionary())
    assert r.footnotes == ["[^注]", "[^b]"]
    # 均等割付の記号と、空白を含むものは脚注としない
    r = vamd.review(answer(CURRENT + ["[原告]{5}", "[^ 1]"]), "K7Q29XMD", 3, CURRENT, make_dictionary())
    assert r.footnotes == []


def test_prompt_forbids_footnotes():
    assert "脚注（[^1]）" in vamd.PROMPT


def test_review_other_document_stops():
    with pytest.raises(vamd.OtherDocument):
        vamd.review(answer(CURRENT, doc_id="ZZZZZZZZ"), "K7Q29XMD", 3, CURRENT, make_dictionary())


def test_review_reports_tokens_marks_changes_and_old_version():
    body = ["準備書面", "--: 令和８年９月１７日", "# 認否", "〔人名A〕の主張は争う。〔人名Ｃ〕も同じ。", "<<<", "追加した段落。"]
    r = vamd.review(answer(body, version=1), "K7Q29XMD", 3, CURRENT, make_dictionary())
    assert r.older
    assert r.unknown_tokens == ["〔人名Ｃ〕"]
    assert r.lost_tokens == ["〔法人Ａ〕"]          # 〔人名A〕（半角）は消えたことにしない
    assert r.lost_marks == [(":=:", ":=: 準備書面")]
    changed_old = [ln for _, old, _ in r.changes for ln in old]
    changed_new = [ln for _, _, new in r.changes for ln in new]
    assert ":=: 準備書面" in changed_old and "〔法人Ａ〕は認める。" in changed_old
    assert "追加した段落。" in changed_new
    assert "# 認否" not in changed_old    # 変わっていない行は出さない
    # 変わった・増えた行は、回答の文書の何行目か（エディターで印を付けるため）
    assert [body[k] for k in r.changed_lines] == ["準備書面", "〔人名A〕の主張は争う。〔人名Ｃ〕も同じ。", "追加した段落。"]


# ---------- 突き合わせによる対応表の作り直し ----------

WORDS = [("甲野太郎", "人名"), ("乙山商事株式会社", "法人"), ("丙川　次郎", "人名"), ("丁田三郎", "人名"),
         ("戊村四郎", "人名"), ("原告", "その他")]


def save_pair(tmp_path, real_lines, doc_type="Saiban", page_number=None, words=WORDS, version=5, one_width=False):
    """実名の文章から、同じ版の PDF と構文ファイルを作る（VA Documentの［保存］と同じ）。"""
    dt = doc_type_for(doc_type, one_width)
    d = Dictionary()
    for w, k in words:
        d.register(w, k)
    ts = Typesetter(dt)
    lines = ts.layout(parse(real_lines, dt))
    pdf = tmp_path / "実名.pdf"
    kw = {"page_number": page_number} if page_number else {}
    write_pdf(ts, lines, str(pdf), doc_id="K7Q29XMD", version=version, **kw)
    settings = vamd.Settings(doc_type, page_number or vamd.Settings().page_number, one_width=one_width)
    text = vamd.build("K7Q29XMD", version, settings, d.pseudonymize("\n".join(real_lines)))
    return d, pdf, vamd.parse_text(text)


@pytest.mark.parametrize("sample", ["裁判所", "長い文書"])
def test_rebuild_same_version(tmp_path, sample):
    real = (DATA / sample / "見本.md").read_text(encoding="utf-8").splitlines()
    original, pdf, content = save_pair(tmp_path, real)
    d, r = rebuild_dictionary(content, pdf)
    expected = {e.token: e.word for e in original.entries.values() if e.token in content.body_text}
    assert r.found == expected and not r.missing and not r.conflicts
    assert r.exact
    # 作り直した辞書で戻すと、元の実名の文章になる
    assert d.restore(content.body_text)[0] == "\n".join(real)
    # 次に登録する語は、続きの英字（人名は甲野・丙川・丁田・戊村の4つ）
    assert d.register("己野五郎", "人名") == "〔人名Ｅ〕"


def test_rebuild_with_table_and_top_right_page_number(tmp_path):
    real = [":=: 損害の一覧", "# 損害", "甲野太郎の損害は、次の表のとおりである。",
            "| 項目 | --: 金額 |", "|===|---:|", "| 甲野太郎の休業損害 | 1,080,000 |", "| 乙山商事株式会社の負担分 | 500,000 |",
            "表のとおり、甲野太郎の損害は乙山商事株式会社が負う。", "<<<", "--: 以上"]
    original, pdf, content = save_pair(tmp_path, real, page_number=PAGE_NUMBER_TOP_RIGHT)
    d, r = rebuild_dictionary(content, pdf)
    assert r.exact
    assert d.restore(content.body_text)[0] == "\n".join(real)


def test_rebuild_after_ai_changed_text(tmp_path):
    """版ずれ（AI の回答で上書きした後、PDF を保存していない）：変わっていない部分から求め、残りは尋ねる。"""
    real = (DATA / "裁判所" / "見本.md").read_text(encoding="utf-8").splitlines()
    original, pdf, content = save_pair(tmp_path, real)
    body = list(content.body)
    body.insert(10, "なお、〔人名Ａ〕の主張は失当である。")
    body[-3] = "（この段落は AI が書き直した。）"
    content.body = body
    d, r = rebuild_dictionary(content, pdf)
    assert not r.exact
    expected = {e.token: e.word for e in original.entries.values()}
    assert all(expected[t] == w for t, w in r.found.items() if t not in r.conflicts)
    assert r.found["〔人名Ａ〕"] == "甲野太郎"


def test_rebuild_rejects_other_pdf(tmp_path):
    real = ["# 認否", "甲野太郎の主張は争う。"]
    _, pdf, content = save_pair(tmp_path, real)
    content.doc_id = "ZZZZZZZZ"
    with pytest.raises(PdfMismatch):
        rebuild_dictionary(content, pdf)


def test_recover_reports_missing_when_word_cannot_be_found(tmp_path):
    real = ["# 認否", "甲野太郎の主張は争う。"]
    _, pdf, content = save_pair(tmp_path, real)
    r = recover(content.body + ["〔人名Ｚ〕の陳述書"], pdf, DOC_TYPES["Saiban"])
    assert r.found["〔人名Ａ〕"] == "甲野太郎"
    assert not r.exact


def test_review_reports_blank_lines_added_by_ai():
    """空の行は1行の空きになるので、AI が足した空行も変わった行として示す（文書の初めと終わりの空行は除く）。"""
    body = list(CURRENT)
    body.insert(3, "")
    r = vamd.review(answer(body), "K7Q29XMD", 3, CURRENT + [""], make_dictionary())
    assert r.changed_lines == [3] and not r.removed


def test_prompt_allows_table_changes_on_request():
    """AI への指示：表の2行目・セルの配置の記号は「私が求めたときを除き」変えない。2重線はすべての列を = にする。"""
    assert "セルの先頭の配置の記号は、私が求めたときを除き、変えない" in vamd.PROMPT
    assert "2行目のすべての列の - を = にする" in vamd.PROMPT


@pytest.mark.parametrize("mark", ["[TOC]", "[TOC:1]"])
def test_rebuild_with_toc(tmp_path, mark):
    """目次（見出しが2回、PDF に出る）があっても、突き合わせで記号の元の語が求まる。"""
    real = [":=: 準備書面", mark, "<<<", "# 甲野太郎の主張について", "甲野太郎は、乙山商事株式会社と契約した。",
            "## 乙山商事株式会社の反論", "反論する。"]
    original, pdf, content = save_pair(tmp_path, real)
    d, r = rebuild_dictionary(content, pdf)
    assert r.exact and not r.missing
    assert d.restore(content.body_text)[0] == "\n".join(real)


def test_rebuild_with_bold(tmp_path):
    """太字（**文字**）の記号は PDF に出ないが、突き合わせで記号の元の語が求まる（太字の中の記号も）。"""
    real = ["# 認否", "**甲野太郎**の主張は争う。", "| 当事者 | 主張 |", "|---|---|", "| **乙山商事株式会社** | 争う |"]
    original, pdf, content = save_pair(tmp_path, real)
    d, r = rebuild_dictionary(content, pdf)
    assert r.exact and not r.missing
    assert d.restore(content.body_text)[0] == "\n".join(real)


def test_prompt_allows_bold_on_request():
    assert "太字は **語**、傍点は *語* で書く" in vamd.PROMPT and "・太字・斜体" not in vamd.PROMPT


def test_rebuild_with_highlight(tmp_path):
    """蛍光ペン（==文字==）は保存する PDF に出ないが、突き合わせで記号の元の語が求まる。"""
    real = ["# 認否", "==甲野太郎の主張==は争う。", "| 当事者 | 主張 |", "|---|---|", "| ==乙山商事株式会社== | 争う |"]
    original, pdf, content = save_pair(tmp_path, real)
    d, r = rebuild_dictionary(content, pdf)
    assert r.exact and not r.missing
    assert d.restore(content.body_text)[0] == "\n".join(real)


def test_prompt_explains_highlight():
    assert "==語== は私が画面で付けた目印（蛍光ペン。PDF には出ない）" in vamd.PROMPT
    assert "蛍光ペンの記号（==語==）と均等割付の記号（[語]{5}）は、私が求めたときを除き、付け外ししない" in vamd.PROMPT


def test_review_ignores_table_separator_colons():
    """表の区切りの行の : は、配置の記号として比べない（AI が :-- を :--- に直しても知らせない。Ver210 までは、
    区切りの行を読む関数の名前が重なり、比べていた）。セルの先頭の配置の記号は比べる。"""
    current = ["| 項目 | 金額 |", "|:--|--:|", "| :-: 休業損害 | 1,080,000 |"]
    r = vamd.review(answer(["| 項目 | 金額 |", "|:---|---:|", "| :-: 休業損害 | 1,080,000 |"]), "K7Q29XMD", 3, current,
                    make_dictionary())
    assert not r.lost_marks
    r = vamd.review(answer(["| 項目 | 金額 |", "|:--|--:|", "| 休業損害 | 1,080,000 |"]), "K7Q29XMD", 3, current,
                    make_dictionary())
    assert [m for m, _ in r.lost_marks] == [":-:"]


def test_review_notices_lost_column_widths():
    """AI が列の幅の {字数} を消したら知らせる。字数を変えたのは知らせない（直してよい。画像の幅と同じ）。"""
    current = ["| 項目 | 金額 |", "|---{8}|---:{10}|", "| 休業損害 | 1,080,000 |"]
    r = vamd.review(answer(["| 項目 | 金額 |", "|---{9}|---:{12}|", "| 休業損害 | 1,080,000 |"]), "K7Q29XMD", 3, current,
                    make_dictionary())
    assert not r.lost_marks
    r = vamd.review(answer(["| 項目 | 金額 |", "|---|---:{10}|", "| 休業損害 | 1,080,000 |"]), "K7Q29XMD", 3, current,
                    make_dictionary())
    assert r.lost_marks == [("{字数}", current[1])]


def test_review_reports_lost_indent_but_not_changed_count():
    """AI の回答で ->N が消えたら知らせる。字数を変えただけなら知らせない。"""
    current = ["# 認否", "->2 主張は争う。"]
    r = vamd.review(answer(["# 認否", "->3 主張は争う。"]), "K7Q29XMD", 3, current, make_dictionary())
    assert not r.lost_marks
    r = vamd.review(answer(["# 認否", "主張は争う。"]), "K7Q29XMD", 3, current, make_dictionary())
    assert [m for m, _ in r.lost_marks] == ["->N"]
    assert "「->2 」は段落の左インデントを全角2字にする記号" in vamd.PROMPT


def test_review_reports_lost_first_line_indent():
    """字下げの全角空白が AI の回答で消えたら知らせる（字下げが効く段落だけ。見出しの後の本文は、読み込むと空白を
    取り除くので比べない。2026-10-28 班長決定）。"""
    current = ["　前書き。", "# 認否", "　本文。", "--: 以上", "　後書き。", "->2 　インデント。"]
    r = vamd.review(answer(current), "K7Q29XMD", 3, current, make_dictionary())
    assert not r.lost_marks
    r = vamd.review(answer(["前書き。", "# 認否", "本文。", "--: 以上", "　後書き。", "->2 インデント。"]),
                    "K7Q29XMD", 3, current, make_dictionary())
    assert r.lost_marks == [("字下げの空白", "　前書き。"), ("字下げの空白", "->2 　インデント。")]
    assert "全角空白は、段落の1行目を1字下げる字下げである" in vamd.PROMPT and "「-> 」" not in vamd.PROMPT


def test_rebuild_with_distribute(tmp_path):
    """均等割付の記号は PDF に出ないが、突き合わせで記号の元の語が求まる（割り付けた中の記号も）。"""
    real = ["[原告]{5}甲野太郎", "--: [被告]{6}乙山商事株式会社", "# 認否", "[甲野太郎]{8}の主張は争う。"]
    original, pdf, content = save_pair(tmp_path, real)
    d, r = rebuild_dictionary(content, pdf)
    assert r.exact and not r.missing
    assert d.restore(content.body_text)[0] == "\n".join(real)


@pytest.mark.parametrize("real", [
    # 割り付けた記号と、続く記号が隣り合う（PDF の字の並びは「原告甲野太郎」で、切れ目が字の並びに残らない）
    ["[原告]{5}甲野太郎"],
    # 行の終わりの記号と、次の行の割り付けた記号も隣り合う
    ["[原告]{5}甲野太郎", "[乙山商事株式会社]{10}被告", "# 認否"],
    # 割り付けた記号の前に記号がある（範囲の終わりから始めを求める）
    ["甲野太郎[原告]{5}"],
    # 表のセルの中
    ["| 当事者 | 主張 |", "|---|---|", "| [原告]{5}甲野太郎 | 否認 |"],
])
def test_rebuild_with_distribute_next_to_token(tmp_path, real):
    """均等割付の範囲の境目は、PDF の字の位置（1字目の左端から字数の幅）で求まる（2026-10-25 に見つかった不具合）。"""
    original, pdf, content = save_pair(tmp_path, real)
    d, r = rebuild_dictionary(content, pdf)
    assert r.exact and not r.missing and not r.conflicts
    assert d.restore(content.body_text)[0] == "\n".join(real)


def test_rebuild_with_distribute_not_spread(tmp_path):
    """字数より字が多く、割り付けずに字の幅のまま並んだときは、境目を字の位置から決めない（誤った語を採らない）。"""
    original, pdf, content = save_pair(tmp_path, ["[原告]{1}甲野太郎"])
    d, r = rebuild_dictionary(content, pdf)
    assert not r.exact and set(r.missing) == {"〔その他Ａ〕", "〔人名Ａ〕"} and not r.found


def test_rebuild_with_dots(tmp_path):
    """傍点の黒丸は図形で描くので PDF の字に入らず、突き合わせで記号の元の語が求まる（傍点の中の記号も）。"""
    real = ["原告　甲野太郎", "# 認否", "*甲野太郎*の主張は***争う***。", "| 当事者 | 主張 |", "|---|---|", "| *乙山商事株式会社* | 否認 |"]
    original, pdf, content = save_pair(tmp_path, real)
    d, r = rebuild_dictionary(content, pdf)
    assert r.exact and not r.missing
    assert d.restore(content.body_text)[0] == "\n".join(real)

def test_rebuild_with_composite_heading(tmp_path):
    """複合見出し（番号が続けて並ぶ）と目次があっても、突き合わせで記号の元の語が求まる。"""
    real = ["[TOC]", "<<<", "#", "## 甲野太郎の主張", "本文。", "#", "## 乙山商事株式会社の反論", "反論する。"]
    original, pdf, content = save_pair(tmp_path, real)
    d, r = rebuild_dictionary(content, pdf)
    assert r.exact and not r.missing
    assert d.restore(content.body_text)[0] == "\n".join(real)


def test_rebuild_with_one_width_numbers(tmp_path):
    """見出し番号を1字の幅に縮めた文書（2026-10-26）でも、突き合わせで記号の元の語が求まる。番号1字は区切りの行から
    読むので、構文ファイルの設定のとおりに組み直して突き合わせる。"""
    real = ["[TOC]", "#", "## 甲野太郎の主張", "### 乙山商事株式会社の反論", "本文。", "##", "### 甲野太郎", "####",
            "##### 乙山商事株式会社"]
    original, pdf, content = save_pair(tmp_path, real, one_width=True)
    assert content.settings.one_width
    d, r = rebuild_dictionary(content, pdf)
    assert r.exact and not r.missing
    assert d.restore(content.body_text)[0] == "\n".join(real)


def test_ai_marker_lines_are_dropped():
    """AI の画面が回答に混ぜた内部の目印の行（2026-10-25 の往復試験で claude.ai が混ぜた「<?thinking_complete?>」）は、
    読み込むときに除き、除いた行を返す（2026-10-25 班長決定）。本文の中の <?…?> や、字のある行は除かない。"""
    c = answer(["--: 以上", "<?thinking_complete?>", "  <?x-y.z?>  ", "<<<=", "本文に<?thinking_complete?>と書いた",
                "<?thinking_complete?> 字のある行"])
    assert c.body == ["--: 以上", "<<<=", "本文に<?thinking_complete?>と書いた", "<?thinking_complete?> 字のある行"]
    assert c.dropped == ["<?thinking_complete?>", "<?x-y.z?>"]
    r = vamd.review(c, "K7Q29XMD", 3, ["--: 以上", "<<<=", "本文に<?thinking_complete?>と書いた",
                                       "<?thinking_complete?> 字のある行"], make_dictionary())
    assert not r.changes and not r.changed_lines


def test_prompt_says_tokens_are_per_document():
    """AI への指示に、記号は文書ごとに振ることと、ほかの文書の記号を書き写さないことを書く（2026-10-25 班長決定）。"""
    assert "記号は文書ごとに振っている" in vamd.PROMPT
    assert "ほかの文書の記号を、この文書にそのまま書き写さない" in vamd.PROMPT


def test_prompt_hash_is_recorded():
    """今の版の既定の指示の SHA-256 を PROMPT_SHA256 に控える。指示を直すとこの試験が落ちるので、前の値を
    PREVIOUS_PROMPTS に移してから新しい値に替える（前の版の登録を忘れないため。Ver220・Ver230 で忘れた。2026-10-28）。"""
    import hashlib
    assert hashlib.sha256(vamd.PROMPT.rstrip().encode("utf-8")).hexdigest() == vamd.PROMPT_SHA256
    assert vamd.PROMPT_SHA256 not in vamd.PREVIOUS_PROMPTS


@pytest.mark.parametrize("version", ["Ver211", "Ver220"])
def test_old_default_prompt_is_replaced_on_open(version, tmp_path):
    """前の版が書いた構文ファイル（その版の既定の指示。tests/data/前の版の指示 は、配った各版のソースで作った）を開くと、
    保存するときは今の版の指示を書く（2026-10-28 Ver231）。前の版の既定の指示は見分けられる（少しでも直したものは別）。"""
    from va_document import config
    from va_document.session import Session
    src = DATA / "前の版の指示" / f"{version}.vamd"
    old = vamd.read_file(src).prompt
    assert "「-> 」" in old and vamd.is_default_prompt(old)
    assert not vamd.is_default_prompt(old.replace("表題", "題", 1))
    path = tmp_path / src.name
    path.write_bytes(src.read_bytes())
    s = Session(config.AppConfig(vamd_folder=str(tmp_path)))
    s.open_vamd(path, False)
    assert s.prompt is None
    assert s.vamd_text("前書き。").startswith(vamd.PROMPT.rstrip())


def test_prompt_is_common_to_all_documents(tmp_path):
    """AI への指示はすべての文書に共通：開いた構文ファイルの指示（手で直したものも）は使わず、設定の指示（ユーザーに
    よって書き換えられた指示。なければ既定の指示）を書く（2026-10-28 班長決定）。"""
    from va_document import config
    from va_document.session import Session
    path = tmp_path / "K7Q29XMD.vamd"
    path.write_text(vamd.build("K7Q29XMD", 2, vamd.Settings("Saiban"), "本文。", "手で直した指示"), encoding="utf-8")
    s = Session(config.AppConfig(vamd_folder=str(tmp_path)))
    s.open_vamd(path, False)
    assert s.prompt is None and s.vamd_text("本文。").startswith(vamd.PROMPT.rstrip())
    custom = vamd.PROMPT.rstrip() + "\n・短く書け。"
    s = Session(config.AppConfig(vamd_folder=str(tmp_path), ai_prompt=custom))
    s.open_vamd(path, False)
    assert s.prompt == custom and s.vamd_text("本文。").startswith(custom)
    s = Session(config.AppConfig(vamd_folder=str(tmp_path), ai_prompt=vamd.read_file(
        DATA / "前の版の指示" / "Ver220.vamd").prompt))
    assert s.prompt is None                                   # 前の版の既定の指示が設定に残っていても、今の既定の指示
