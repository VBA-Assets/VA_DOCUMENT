"""Mac など、ＭＳ 明朝のない PC で使う同梱の書体（IPA明朝・IPAゴシック）を確かめる（仕様.md の6.1。2026-10-25）。

Mac の実機では確かめられないので、Windows で同じ文書を両方の書体で書き出し、字の位置（本文・表・ページ番号・
行番号）がＭＳ 明朝のときと同じになることを確かめる。
"""
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

import pdfcheck

from va_document.cleanup import clean
from va_document.doctypes import (DOC_TYPES, PAGE_NUMBER_BOTTOM_CENTER, PAGE_NUMBER_BOTTOM_CENTER_DECORATED,
                                  PAGE_NUMBER_BOTTOM_RIGHT, PAGE_NUMBER_TOP_RIGHT)
from va_document.document import parse
from va_document.layout import Typesetter
from va_document import pdfwriter
from va_document.pdfwriter import IPA_FONTS, MS_FONTS, check_embeddable, pdf_bytes

DATA = Path(__file__).parent / "data"

# (見本のフォルダ, 文書の種類)。VA公用文と比べている見本すべて
CASES = [
    ("裁判所", "Saiban"), ("半角と箇条書き", "Saiban"), ("公用文", "Kouyou"), ("内容証明", "Naiyou"),
    ("契約書1", "Keiyaku1"), ("契約書2", "Keiyaku2"), ("ビジネス", "Business"), ("技術", "Technical"),
    ("見出しが浅くなる", "Saiban"), ("長い文書", "Saiban"), ("整形", "Saiban"), ("目次", "Saiban"),
]

# 太字・蛍光ペン・傍点・表を含む文書
EXTRA = """\
# 第１　**請求の趣旨**

本文に**太字**と==蛍光ペン==と*傍点*がある。ABCabc123（半角）も混ぜる。

| 番号 | 名前 | 備考 |
|---|---|---|
| 1 | **甲** | 半角 ABC |
| 2 | 乙 | 全角ＡＢＣ |
"""


def chars(data):
    """PDF の字（字, ページ, 左右, 上下）と、埋め込んだ書体の名前（字の位置を比べる前に、書体が替わったことを確かめる）。"""
    pages = pdfcheck.all_chars(data)
    out = [sorted({c["font"].split("+")[-1] for page in pages for c in page})]
    for pno, page in enumerate(pages, start=1):
        for c in page:
            out.append((c["text"], pno, round(c["x"], 2), round(c["y"], 2)))
    return out


def both(text, doc_type, **kw):
    """同じ文書をＭＳ 明朝と IPA明朝で書き出し、それぞれの字を返す（先頭の書体の名前は確かめて除く）。"""
    dt = DOC_TYPES[doc_type]
    ts = Typesetter(dt)
    lines = ts.layout(parse(clean(text)[0].splitlines(), dt))
    ms, ipa = chars(pdf_bytes(ts, lines, fonts=MS_FONTS, **kw)), chars(pdf_bytes(ts, lines, fonts=IPA_FONTS, **kw))
    assert ms[0] and all(f.startswith("MS") for f in ms[0])
    assert ipa[0] and all(f.startswith("IPA") for f in ipa[0]) and len(ipa[0]) == len(ms[0])
    return ms[1:], ipa[1:]


def test_default_fonts(monkeypatch):
    """Windows ではＭＳ 明朝、Mac など（Windows 以外）では同梱の IPA明朝を使う。同梱の書体はソースにある。"""
    assert pdfwriter._default_fonts() is MS_FONTS
    monkeypatch.setattr(pdfwriter.os, "name", "posix")
    assert pdfwriter._default_fonts() is IPA_FONTS
    monkeypatch.undo()
    assert all(Path(f).is_file() for f, _ in IPA_FONTS)
    assert (Path(IPA_FONTS[0][0]).parent / "IPA_Font_License_Agreement_v1.0.txt").is_file()


def test_ipa_fonts_are_embeddable():
    """同梱の書体の埋め込みの許可は「制限なし」（fsType=0）。"""
    assert check_embeddable(*IPA_FONTS[0]) == 0
    assert check_embeddable(*IPA_FONTS[1]) == 0


@pytest.mark.parametrize("folder,doc_type", CASES, ids=[c[0] for c in CASES])
def test_same_position_as_ms_mincho(folder, doc_type):
    """見本の字の位置（本文・ページ番号・行番号）が、ＭＳ 明朝のときと同じ。"""
    ms, ipa = both((DATA / folder / "見本.md").read_text(encoding="utf-8"), doc_type, line_numbers=True)
    assert ms and ms == ipa


@pytest.mark.parametrize("page_number", [PAGE_NUMBER_BOTTOM_CENTER, PAGE_NUMBER_BOTTOM_CENTER_DECORATED,
                                         PAGE_NUMBER_BOTTOM_RIGHT, PAGE_NUMBER_TOP_RIGHT])
def test_same_position_bold_table_page_number(page_number):
    """太字（ゴシック）・表・ページ番号の形ごとに、字の位置がＭＳ 明朝のときと同じ。"""
    ms, ipa = both(EXTRA, "Saiban", page_number=page_number, highlight=True)
    assert ms and ms == ipa


def test_ipa_has_every_char_of_samples():
    """見本で使っている字が、すべて IPA明朝にある（ない字は、Mac の PDF で抜ける）。"""
    cmap = set(TTFont(IPA_FONTS[0][0]).getBestCmap())
    used = set()
    for folder, _ in CASES:
        used |= set((DATA / folder / "見本.md").read_text(encoding="utf-8"))
    missing = sorted(c for c in used if ord(c) not in cmap and not c.isspace())
    assert not missing, missing
