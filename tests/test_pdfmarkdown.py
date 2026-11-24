"""構文ファイルのない PDF から、マークダウンを作る（pdfmarkdown.py。2026-11-24 班長指示「VA疑似アウトラインの機能を
取り込む」）。

確かめ方：見本を組んで PDF にし、その PDF からマークダウンを作って組み直すと、すべての字が同じページ・行・位置に来る
こと（見出しの番号・配置・字下げ・表・改ページが戻っていること）。VA公用文（Word）で作った PDF からは、見本と同じ
マークダウンが戻ること。
"""
from pathlib import Path

import pytest

import pdfcheck
from va_document import config, pdfmarkdown, vamd
from va_document.cleanup import clean
from va_document.doctypes import doc_type_for
from va_document.document import parse
from va_document.layout import Typesetter
from va_document.pdfwriter import pdf_bytes
from va_document.session import Session

DATA = Path(__file__).parent / "data"

# (見本のフォルダ, 文書の種類)
SAMPLES = [
    ("裁判所", "Saiban"), ("半角と箇条書き", "Saiban"), ("公用文", "Kouyou"), ("内容証明", "Naiyou"),
    ("契約書1", "Keiyaku1"), ("契約書2", "Keiyaku2"), ("ビジネス", "Business"), ("技術", "Technical"),
    ("見出しが浅くなる", "Saiban"), ("長い文書", "Saiban"), ("整形", "Saiban"), ("目次", "Saiban"),
]


def glyphs(md, settings):
    """マークダウンを組んだ字の [(ページ, 行, 左端, 字)]（空白を除く）と、組んだ結果。"""
    dt = doc_type_for(settings.doc_type, settings.one_width)
    ts = Typesetter(dt, settings.page_number)
    lines = ts.layout(parse(clean(md)[0].splitlines(), dt))
    return [(ln.page, ln.row, round(ts.margin_left + g.x, 1), g.ch) for ln in lines for g in ln.glyphs
            if not g.ch.isspace()], ts, lines


def round_trip(md, tmp_path, settings, default=None):
    """md を組んで PDF にし、PDF からマークダウンを作る。(元の字, 戻した字, 変換の結果)。"""
    before, ts, lines = glyphs(md, settings)
    pdf = tmp_path / "見本.pdf"
    pdf.write_bytes(pdf_bytes(ts, lines, "TESTDOC1", 1, settings.page_number, line_numbers=settings.line_numbers))
    result = pdfmarkdown.convert(pdf, default or vamd.Settings())
    after, _, _ = glyphs(result.text, result.settings)
    return before, after, result


@pytest.mark.parametrize("folder,key", SAMPLES, ids=[s[0] for s in SAMPLES])
def test_samples_come_back(folder, key, tmp_path):
    """どの文書の種類の見本も、PDF から戻したマークダウンで組み直すと、すべての字が元と同じ位置に来る。文書の種類・
    行番号・ページ番号も戻る（今の設定がほかの種類〔ビジネス文書〕でも、用紙と余白から選ぶ）。"""
    settings = vamd.Settings(key, line_numbers=True).normalized()
    before, after, r = round_trip((DATA / folder / "見本.md").read_text(encoding="utf-8"), tmp_path, settings,
                                  default=vamd.Settings("Business"))
    assert r.settings == settings
    assert after == before


@pytest.mark.parametrize("page_number", ["TopRight", "BottomCenterDecorated", "BottomRight", "None"])
def test_page_number_position(page_number, tmp_path):
    settings = vamd.Settings("Saiban", page_number)
    before, after, r = round_trip((DATA / "裁判所" / "見本.md").read_text(encoding="utf-8"), tmp_path, settings)
    assert r.settings.page_number == page_number and after == before


CASES = {
    "複合見出し": "# 総論\n#\n## 当事者\n原告は会社である。\n##\n### 契約\n#\n##\n### 三重\n本文。",
    "表": ":=: 表の見本\n# 請求の内容\n次のとおり請求する。\n| 品名 | 数量 | 金額 |\n|---|--:|--:|\n"
          "| りんご | 3 | 300円 |\n| みかん | 10 | 1,000円 |\n以上の金額を支払え。",
    "太字": "# 総論\n本文に**太字**を含む。\n**全体が太字の段落。**\n# **見出しの太字**\n本文。",
    "空の行": "表題の前\n\n:=: 準備書面\n\n# 総論\n本文。\n\n## 小見出し\n本文。\n\n\n二つ空ける。",
    "改ページ": "# 総論\n本文。\n<<<\n# 次のページ\n本文。\n<<<=\n# 新しいセクション\n本文。",
    "字下げ": ("　一字下げの段落で、長い文になるので折り返して二行目に続いていく段落の例である。そのうえで、さらに長く書く。\n"
             "->3 左に三字のインデントのある段落で、長い文になるので折り返して二行目に続いていく段落の例である。\n"
             "->2 　左に二字のインデントと字下げのある段落で、長い文になるので折り返して二行目に続いていく段落である。\n"
             "# 総論\n本文。\n--: 以上\n->2 以上の後の段落で、折り返すように長く書いた文である。字下げがなく、左に二字の段落である。"),
    "箇条書き": "# 総論\n- 箇条書きの一つ目\n- 箇条書きの二つ目\n1. 段落番号の一つ目\n2. 段落番号の二つ目\n\n1. 空けた後の段落番号",
    "記号に読める字": "# 総論\n本文。\n->0 # これは見出しではない\n->0 - これも箇条書きではない",
}


@pytest.mark.parametrize("name", list(CASES))
def test_marks_come_back(name, tmp_path):
    """複合見出し・表・太字・空の行・改ページとセクション区切り・字下げと ->N・箇条書きと段落番号も戻る。記号に読める
    字（「# 」で始まる本文など）は、->0 を付けて字のまま組まれるようにする。"""
    before, after, r = round_trip(CASES[name], tmp_path, vamd.Settings("Saiban"))
    assert after == before


def test_web_headings_by_size(tmp_path):
    """ウェブ文書は、字の大きさで見出しのレベルを決める。"""
    md = ":=: お知らせ\n# 見出し\n本文。\n## 小見出し\n- 箇条\n1. 番号"
    before, after, r = round_trip(md, tmp_path, vamd.Settings("Web"))
    assert r.settings.doc_type == "Web" and after == before
    assert "## 小見出し" in r.text


def test_skipped_number_is_left_as_text(tmp_path):
    """組んだときに付く番号と違う番号（第１の次の第３）は、見出しにせず字のまま残す（番号が変わらないように）。"""
    _, _, r = round_trip("# 総論\n本文。\n->0 第３　飛んだ番号\n本文。", tmp_path, vamd.Settings("Saiban"))
    assert "第３　飛んだ番号" in r.text and "# 飛んだ番号" not in r.text


def test_pdf_made_by_word():
    """VA公用文（Word）で作った PDF（Word の PDF は、全角空白を半角の幅の空白の字で描き、行末に空白の字を置く）から、
    見本と同じマークダウンが戻る。今の設定がほかの種類でも、用紙と余白から裁判所提出書類を選ぶ。"""
    r = pdfmarkdown.convert(DATA / "裁判所" / "VA公用文.pdf", vamd.Settings("Business"))
    assert r.text == (DATA / "裁判所" / "見本.md").read_text(encoding="utf-8").strip()
    assert r.settings == vamd.Settings("Saiban", "BottomCenter")


def test_pdf_made_by_word_with_toc():
    """目次の項目（字・点線・ページ番号）は、目次の記号 [TOC] にまとめる（18 ページの PDF）。この PDF の最後の「以上」は、
    右揃えでなく本文の位置にあるので、右揃えにしない。"""
    r = pdfmarkdown.convert(DATA / "目次" / "VA公用文_目次.pdf", vamd.Settings())
    expected = (DATA / "目次" / "見本.md").read_text(encoding="utf-8").strip()
    assert r.text == expected.replace("--: 以上", "以上")


def test_session_opens_pdf_without_vamd(tmp_path):
    """構文ファイルのない PDF を開くと、マークダウンを作り、文書の設定を PDF に合わせ、そのことを知らせる。"""
    s = Session(config.AppConfig(vamd_folder=str(tmp_path / "構文ファイル"), doc_type="Business"))
    r = s.open_pdf(DATA / "裁判所" / "VA公用文.pdf")
    assert r.text.startswith("令和８年") and "# 請求原因に対する認否" in r.text
    assert s.settings.doc_type == "Saiban" and r.error is None
    assert "裁判所提出書類" in r.messages[0] and s.pdf_path is None      # 保存するときに保存先を尋ねる


def test_session_falls_back_to_plain_text(tmp_path, monkeypatch):
    """見出し・配置の読み取りに失敗したら、前の版と同じく字だけを取り出し、誤りを返す（画面で誤りの記録に残す）。"""
    import va_document.session as session_module

    def broken(path, settings):
        raise RuntimeError("読み取りの失敗")
    monkeypatch.setattr(session_module, "pdf_to_markdown", broken)

    def draw(c):
        c.setFont("Helvetica", 12)
        c.drawString(72, 770, "Plain text")
    p = tmp_path / "他.pdf"
    p.write_bytes(pdfcheck.make_pdf(draw))
    r = Session(config.AppConfig(vamd_folder=str(tmp_path))).open_pdf(p)
    assert "Plain" in r.text and isinstance(r.error, RuntimeError) and "文字だけ" in r.messages[0]


def test_line_numbers_of_the_same_size(tmp_path):
    """本文と同じ大きさの行番号（Word の行番号。左の余白に、右端をそろえて並ぶ数字）も除き、行番号の設定にする。"""
    from va_document.pdfwriter import DEFAULT_FONTS, register_font
    font = register_font(*DEFAULT_FONTS[0])

    def draw(c):
        c.setFont(font, 10.5)
        for k, s in enumerate(["本文の一行目です。", "二行目です。", "三行目です。", "四行目です。"]):
            y = 770 - 18 * k
            c.drawRightString(70, y, str(k + 1))
            c.drawString(85, y, s)
    p = tmp_path / "行番号.pdf"
    p.write_bytes(pdfcheck.make_pdf(draw))
    r = pdfmarkdown.convert(p, vamd.Settings())
    assert r.text.splitlines() == ["本文の一行目です。", "二行目です。", "三行目です。", "四行目です。"]
    assert r.settings.line_numbers


def test_foreign_pdf_keeps_drawn_space(tmp_path):
    """ほかのソフトの PDF の、描いた半角空白（狭いもの）を残す。"""
    def draw(c):
        c.setFont("Helvetica", 12)
        c.drawString(72, 770, "Plain text")
    p = tmp_path / "他.pdf"
    p.write_bytes(pdfcheck.make_pdf(draw))
    assert pdfmarkdown.convert(p, vamd.Settings()).text == "Plain text"
