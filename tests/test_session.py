"""文書の作業（保存・開く・構文ファイルの直し・取り込み）。仕様.md の3・7・8・9。"""
from pathlib import Path

import pytest

from va_document import config, vamd
from va_document.pdfwriter import read_id
from va_document.session import Session

REAL = "\n".join([
    "令和８年（ワ）第１２３４号　損害賠償請求事件",
    "原告　甲野太郎",
    "被告　乙山商事株式会社",
    ":=: 準備書面（１）",
    "--: 令和８年９月１７日",
    "# 請求原因に対する認否",
    "## 請求原因第１項について",
    "甲野太郎と乙山商事株式会社との間で売買契約が締結された事実はない。",
    "## 請求原因第２項について",
    "争う。",
    "--: 以上",
])


@pytest.fixture
def session(tmp_path):
    cfg = config.AppConfig(vamd_folder=str(tmp_path / "構文ファイル"))
    s = Session(cfg)
    s.dictionary.register("甲野太郎", "人名")
    s.dictionary.register("乙山商事株式会社", "法人")
    return s


def saved(session, tmp_path, text=REAL):
    pdf = tmp_path / "事件" / "準備書面.pdf"
    pdf.parent.mkdir(exist_ok=True)
    session.save(text, pdf)
    return pdf


def test_save_writes_pdf_and_vamd_with_same_version(session, tmp_path):
    pdf = saved(session, tmp_path)
    assert read_id(str(pdf)) == (session.doc_id, 1)
    c = vamd.read_file(session.vamd_path)
    assert (c.doc_id, c.version) == (session.doc_id, 1)
    assert session.vamd_path.name == f"{session.doc_id}.vamd"
    # 構文ファイルに実名・PDF の名前・フォルダのパスがない
    raw = session.vamd_path.read_text(encoding="utf-8")
    for s in ("甲野", "乙山", "準備書面.pdf", str(tmp_path)):
        assert s not in raw
    assert not session.is_modified(REAL)
    saved(session, tmp_path)
    assert read_id(str(pdf))[1] == vamd.read_file(session.vamd_path).version == 2


def test_reopen_rebuilds_dictionary(session, tmp_path):
    pdf = saved(session, tmp_path)
    s2 = Session(session.cfg)
    r = s2.open_vamd(session.vamd_path)       # PDF は、保存したフォルダから探す
    assert r.text == REAL and not r.unresolved and not r.messages
    assert s2.pdf_path == pdf and s2.version == 1
    assert not s2.is_modified(REAL)
    # PDF から開いても同じ
    s3 = Session(session.cfg)
    assert s3.open_pdf(pdf).text == REAL


def test_vamd_edited_in_text_editor(session, tmp_path):
    """構文ファイルをテキストエディターで直した（指示の書き足し・本文の直し・記号の書き足し）。"""
    saved(session, tmp_path)
    raw = session.vamd_path.read_text(encoding="utf-8")
    raw = raw.replace("5　成果物・報告", "・敬語は使わない。\n\n5　成果物・報告")
    raw = raw.replace("争う。", "争う。〔人名Ｂ〕の陳述書は信用できない。")
    session.vamd_path.write_text(raw, encoding="utf-8")
    s2 = Session(session.cfg)
    r = s2.open_vamd(session.vamd_path)
    assert r.messages                       # PDF の後に直されたことを知らせる
    assert r.unresolved == ["〔人名Ｂ〕"]    # 書き足した記号は、元の語を尋ねる
    text = s2.resolve({"〔人名Ｂ〕": "丙川次郎"})
    assert "争う。丙川次郎の陳述書は信用できない。" in text and "甲野太郎" in text
    assert s2.is_modified(text)
    # 次に保存すると、手で書き足した指示は残らず、設定の指示（ここでは既定の指示）を書く（AI への指示はすべての
    # 文書に共通。2026-10-28 班長決定。それまでは書き足した指示を残した）
    s2.save(text)
    assert "・敬語は使わない。" not in s2.vamd_path.read_text(encoding="utf-8")
    assert s2.vamd_path.read_text(encoding="utf-8").startswith(vamd.PROMPT.rstrip())
    assert "丙川" not in s2.vamd_path.read_text(encoding="utf-8")


def test_vamd_changed_outside(session, tmp_path):
    """構文ファイルが外で書き換えられたことを見分ける。"""
    assert not session.vamd_changed_outside()          # まだ保存していない
    saved(session, tmp_path)
    assert not session.vamd_changed_outside()          # 自分で書いた直後
    raw = session.vamd_path.read_text(encoding="utf-8")
    session.vamd_path.write_text(raw.replace("争う。", "否認する。"), encoding="utf-8")
    assert session.vamd_changed_outside()
    assert "否認する。" in session.outside_vamd_text()
    saved(session, tmp_path)                            # 上書きすると、また自分で書いたものになる
    assert not session.vamd_changed_outside()
    s2 = Session(session.cfg)
    s2.open_vamd(session.vamd_path)
    assert not s2.vamd_changed_outside()               # 開いた直後


def test_open_without_pdf_asks_every_token(session, tmp_path):
    saved(session, tmp_path)
    s2 = Session(config.AppConfig(vamd_folder=session.cfg.vamd_folder))   # PDF のフォルダを知らない
    with pytest.raises(FileNotFoundError):
        s2.open_vamd(session.vamd_path)
    r = s2.open_vamd(session.vamd_path, pdf_path=False)
    assert r.unresolved == ["〔人名Ａ〕", "〔法人Ａ〕"]
    # 新しく登録する語は、構文ファイルにある記号の続き
    assert s2.dictionary.register("丙川次郎", "人名") == "〔人名Ｂ〕"


def test_import_answer(session, tmp_path):
    saved(session, tmp_path)
    answer = vamd.parse_text(session.vamd_text(REAL)).body
    answer = [ln.replace("争う。", "否認する。") for ln in answer]
    sep = vamd.separator_line(session.doc_id, 1, session.settings)
    content, r = session.review_answer("```\n" + sep + "\n" + "\n".join(answer) + "\n```\n", REAL)
    assert r.clean and [k for k, _, _ in r.changes] == ["変更"]
    text = session.apply_answer(content, REAL)
    assert "否認する。" in text and "甲野太郎" in text


def test_open_foreign_pdf_as_plain_text(session, tmp_path):
    import pdfcheck

    def draw(c):
        c.setFont("Helvetica", 12)
        c.drawString(72, 770, "Plain text")
    p = tmp_path / "他.pdf"
    p.write_bytes(pdfcheck.make_pdf(draw))
    r = Session(session.cfg).open_pdf(p)
    assert "Plaintext" in r.text.replace(" ", "") and r.messages


def test_config_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    cfg = config.AppConfig(doc_type="Naiyou", vamd_folder=str(tmp_path))
    cfg.remember_pdf_folder(tmp_path / "a")
    cfg.remember_pdf_folder(tmp_path / "b")
    cfg.remember_pdf_folder(tmp_path / "a")
    config.save(cfg, path)
    back = config.load(path)
    assert back.doc_type == "Naiyou" and [Path(f).name for f in back.pdf_folders] == ["a", "b"]
    assert config.load(tmp_path / "ない.json").doc_type == "Saiban"


def test_registering_a_word_after_save_counts_as_modified(session, tmp_path):
    """保存した後に語を仮名化・解除すると、文章が同じでも保存していない変更とみなす
    （［コピー］が保存し直さずに、前の構文ファイル〔仮名化する前の実名入り〕を写さないように）。"""
    text = REAL + "\n丙川次郎の陳述書による。"
    saved(session, tmp_path, text)
    assert not session.is_modified(text)
    session.dictionary.register("丙川次郎", "人名")
    assert session.is_modified(text)
    saved(session, tmp_path, text)
    assert not session.is_modified(text) and "丙川" not in session.vamd_path.read_text(encoding="utf-8")
    session.dictionary.unregister("丙川次郎")
    assert session.is_modified(text)


def test_open_pdf_without_text_layer(tmp_path):
    """字の層のない PDF（OCR していないスキャン）は、今の文書を消さずに知らせる（2026-10-24）。"""
    import pytest
    from PIL import Image
    from reportlab.lib.utils import ImageReader

    import pdfcheck
    from va_document.pdfwriter import DEFAULT_FONTS, register_font
    from va_document.session import NoTextInPdf
    scan = ImageReader(Image.new("L", (100, 100), 255))

    def page(c, ocr=False):
        c.drawImage(scan, 0, 0, width=595.3, height=841.9)
        if ocr:     # スキャンの上に、透明な字（OCR の字の層。描画モード 3）を置く
            t = c.beginText(72, 741.9)
            t.setFont(register_font(*DEFAULT_FONTS[0]), 12)
            t.setTextRenderMode(3)
            t.textOut("透明な字の層")
            c.drawText(t)
    pdf = tmp_path / "スキャン.pdf"
    pdf.write_bytes(pdfcheck.make_pdf(page))
    s = Session(config.AppConfig(vamd_folder=str(tmp_path / "v")))
    s.typeset("# 認否\n本文。")
    doc_id = s.doc_id
    with pytest.raises(NoTextInPdf, match="OCR"):
        s.open_pdf(pdf)
    assert s.doc_id == doc_id                       # 今の文書のまま
    # OCR の字の層（透明な字）があれば、取り出せる
    (tmp_path / "OCR済み.pdf").write_bytes(pdfcheck.make_pdf(lambda c: page(c, ocr=True)))
    assert pdfcheck.render(tmp_path / "OCR済み.pdf", gray=True).getextrema() == (255, 255)    # 透明な字は見えない
    assert s.open_pdf(tmp_path / "OCR済み.pdf").text == "透明な字の層"



def test_released_words_are_reported(session):
    """解除した語・変える前の元の語が、構文ファイルに実名のまま残るかを確かめる（2026-10-25 班長指示）。"""
    assert session.rename("〔人名Ａ〕", "丙川次郎") == "甲野太郎"
    text = REAL.replace("甲野太郎", "丙川次郎", 1)        # 1か所だけ、前の名前が残った
    assert session.released_in(text) == {"甲野太郎": 1}
    assert session.released_in(REAL.replace("甲野太郎", "丙川次郎")) == {}
    assert {session.unregister(t).token for t in ("〔人名Ａ〕", "〔法人Ａ〕")} == {"〔人名Ａ〕", "〔法人Ａ〕"}
    assert not session.dictionary.entries
    found = session.released_in(REAL)
    assert found == {"甲野太郎": 2, "乙山商事株式会社": 2}
    session.accept_released(["甲野太郎"])                 # 残してよいと答えた語は、もう知らせない
    assert session.released_in(REAL) == {"乙山商事株式会社": 2}
    # 仮名化し直した語は、構文ファイルに残らないので知らせない
    session.dictionary.register("乙山商事株式会社", "法人")
    assert session.released_in(REAL) == {}
    session.new()
    assert session.released == {}


def test_renamed_or_moved_pdf_still_opens(session, tmp_path):
    """保存した PDF の名前を変えても（エクスプローラーで）、PDF からも構文ファイルからも開ける。別のフォルダに移した
    PDF は、PDF から開ける（構文ファイルから開くときは、移した先が保存したことのあるフォルダでなければ見つからない）。
    文書と PDF は、ファイルの名前ではなく文書ID で結ぶため（マニュアルの3.15）。"""
    pdf = saved(session, tmp_path)
    renamed = pdf.with_name("準備書面（１）提出版.pdf")
    pdf.rename(renamed)
    assert Session(session.cfg).open_pdf(renamed).text == REAL
    s = Session(session.cfg)
    assert s.open_vamd(session.vamd_path).text == REAL and s.pdf_path == renamed
    moved = tmp_path / "別のフォルダ" / renamed.name
    moved.parent.mkdir()
    renamed.rename(moved)
    assert Session(session.cfg).open_pdf(moved).text == REAL
    with pytest.raises(FileNotFoundError):
        Session(session.cfg).open_vamd(session.vamd_path)
