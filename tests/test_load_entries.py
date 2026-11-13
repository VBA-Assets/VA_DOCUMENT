"""［ファイルから読み込む］：ほかの文書の仮名化した語を、今の一覧に足す（2026-10-29 班長決定。検討_仮名化した語の読み込み.md）。
画面の操作は test_app.py。"""

import pytest

from va_document import config
from va_document.pseudonym import Dictionary, Entry
from va_document.recover import PdfMismatch
from va_document.session import OtherFileMissing, Session

FIRST = "\n".join([
    "原告　甲野太郎",
    "被告　乙山商事株式会社",
    ":=: 訴状",
    "# 請求の趣旨",
    "被告は、甲野太郎に対し、金100万円を支払え。",
])


def entries(*pairs):
    return [Entry(w, t[1:3], t) for w, t in pairs]


# ---------- 一覧と比べる（pseudonym） ----------

def test_plan_merge_adds_new_and_keeps_same():
    d = Dictionary()
    d.register("甲野太郎", "人名", "Ａ")
    plan = d.plan_merge(entries(("甲野太郎", "〔人名Ａ〕"), ("乙山商事株式会社", "〔法人Ｘ〕")))
    assert [e.word for e in plan.same] == ["甲野太郎"] and [e.word for e in plan.add] == ["乙山商事株式会社"]
    assert not plan.conflicts
    d.merge(plan.add)
    assert d.find("〔法人Ｘ〕").word == "乙山商事株式会社" and "Ｘ" in d.used["法人"]


@pytest.mark.parametrize("setup, loaded, reason", [
    # 1 同じ語に違う記号
    (lambda d: d.register("甲野太郎", "人名", "Ａ"), ("甲野太郎", "〔人名Ｋ〕"), "この文書では 〔人名Ａ〕"),
    # 2 同じ記号に違う語
    (lambda d: d.register("甲野太郎", "人名", "Ａ"), ("乙山花子", "〔人名Ａ〕"), "この文書では「甲野太郎」"),
    # 3 この文書で前に別の語に使って解除した記号
    (lambda d: (d.register("丙川次郎", "人名", "Ｂ"), d.unregister("丙川次郎")), ("乙山花子", "〔人名Ｂ〕"),
     "前に「丙川次郎」に使った"),
])
def test_plan_merge_conflicts(setup, loaded, reason):
    d = Dictionary()
    setup(d)
    plan = d.plan_merge(entries(loaded, ("丁野三郎", "〔人名Ｄ〕")))
    assert len(plan.conflicts) == 1 and reason in plan.conflicts[0][1]
    assert [e.word for e in plan.add] == ["丁野三郎"]          # 食い違いでない語も分けるが、画面では何も足さない


def test_plan_merge_unknown_token_in_text_is_conflict_and_same_word_reregister_is_not():
    d = Dictionary()
    plan = d.plan_merge(entries(("甲野太郎", "〔人名Ａ〕")), unknown_tokens=["〔人名A〕"])   # 半角の字も同じ記号
    assert plan.conflicts and "元の語が分かりません" in plan.conflicts[0][1]
    d.register("甲野太郎", "人名", "Ａ")
    d.unregister("甲野太郎")
    plan = d.plan_merge(entries(("甲野太郎", "〔人名Ａ〕")))      # 前と同じ語に付け直すのは食い違いでない
    assert not plan.conflicts and len(plan.add) == 1
    d.merge(plan.add)
    assert "〔人名Ａ〕" not in d.released


# ---------- 選んだファイルから作り直す（session） ----------

@pytest.fixture
def cfg(tmp_path):
    return config.AppConfig(vamd_folder=str(tmp_path / "構文ファイル"))


@pytest.fixture
def first(cfg, tmp_path):
    """同じ案件の前の文書（甲野太郎＝〔人名Ａ〕、乙山商事株式会社＝〔法人Ｘ〕）。"""
    s = Session(cfg)
    s.dictionary.register("甲野太郎", "人名", "Ａ")
    s.dictionary.register("乙山商事株式会社", "法人", "Ｘ")
    pdf = tmp_path / "事件" / "訴状.pdf"
    pdf.parent.mkdir()
    s.save(FIRST, pdf)
    cfg.remember_pdf_folder(pdf.parent)
    return s


def test_load_from_pdf_or_vamd_gives_same_entries(cfg, first):
    s = Session(cfg)
    text = "原告　甲野太郎\n:=: 準備書面\n乙山商事株式会社の主張は争う。\n"
    for path in (first.pdf_path, first.vamd_path):
        vamd_path, pdf_path = s.other_files(path)
        assert (vamd_path, pdf_path) == (first.vamd_path, first.pdf_path)
        loaded = s.entries_from(vamd_path, pdf_path, text)
        assert {(e.word, e.token) for e in loaded.plan.add} == {("甲野太郎", "〔人名Ａ〕"), ("乙山商事株式会社", "〔法人Ｘ〕")}
        assert loaded.occurrences == 2 and loaded.unrecovered == 0 and loaded.pdf_path.name == "訴状.pdf"
    before = (s.doc_id, s.version, s.settings, dict(s.dictionary.entries))
    assert before[3] == {}                                  # 作り直しても、今の文書は変えない
    assert s.merge_entries(loaded) == 2
    assert s.body(text).startswith("原告　〔人名Ａ〕") and (s.doc_id, s.version, s.settings) == before[:3]


def test_other_file_missing_and_wrong_files(cfg, first, tmp_path):
    s = Session(cfg)
    moved = tmp_path / "別の場所" / "訴状.pdf"
    moved.parent.mkdir()
    moved.write_bytes(first.pdf_path.read_bytes())
    first.pdf_path.unlink()
    with pytest.raises(OtherFileMissing) as e:
        s.other_files(first.vamd_path)                      # 保存したフォルダに PDF がない
    assert e.value.kind == "pdf" and e.value.found == first.vamd_path
    assert s.entries_from(first.vamd_path, moved, "").plan.add    # 利用者が選んだ PDF で作り直せる
    first.vamd_path.rename(tmp_path / "退避.vamd")
    with pytest.raises(OtherFileMissing) as e:
        s.other_files(moved)
    assert e.value.kind == "vamd"
    with pytest.raises(ValueError):
        s.other_files(_plain_pdf(tmp_path))                 # VA Document の PDF でない
    with pytest.raises(PdfMismatch):
        s.entries_from(tmp_path / "退避.vamd", _plain_pdf(tmp_path), "")
    with pytest.raises(ValueError):
        first.other_files(moved)                            # 今の文書そのもの


def _plain_pdf(tmp_path):
    import pdfcheck
    path = tmp_path / "ふつう.pdf"
    path.write_bytes(pdfcheck.make_pdf(lambda c: None))
    return path


def test_entries_not_recovered_are_not_loaded(cfg, first):
    """構文ファイルを PDF の保存の後に直していて、作り直せない記号は読み込まない（数を示す）。"""
    body = first.vamd_path.read_text(encoding="utf-8").rstrip("\n") + "\n〔人名Ｚ〕は証人である。\n"   # AI が足した記号
    first.vamd_path.write_text(body, encoding="utf-8")
    s = Session(cfg)
    loaded = s.entries_from(*s.other_files(first.pdf_path), "")
    assert {e.token for e in loaded.plan.add} == {"〔人名Ａ〕", "〔法人Ｘ〕"} and loaded.unrecovered == 1


def test_conflict_blocks_merge(cfg, first):
    s = Session(cfg)
    s.dictionary.register("甲野太郎", "人名", "Ｂ")
    loaded = s.entries_from(*s.other_files(first.pdf_path), "原告　甲野太郎")
    assert loaded.plan.conflicts
    with pytest.raises(ValueError):
        s.merge_entries(loaded)
    assert set(s.dictionary.entries) == {"甲野太郎"}
