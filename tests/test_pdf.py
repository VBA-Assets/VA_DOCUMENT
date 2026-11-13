"""PDF の書き出しを確かめる（仕様.md の6.1・6.4・9.1・9.3）。

正解の tests/data/裁判所/VA公用文.pdf は、班長が VA公用文 Ver8D3 で見本を整え、Word で PDF に保存したもの
（裁判所提出書類、ページ番号は下中央。2026-10-23）。2026-10-28、見出しより前の2段落を1字下げた見本（見本.md は `-> `、
VA公用文に入れる 試作/見本_裁判所.md は行頭の全角空白）で、班長が作り直した（文書情報・XMP の作成者は取り除いた）。
"""
import difflib
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ByteStringObject

import pdfcheck

from va_document.doctypes import DOC_TYPES
from va_document.document import parse
from va_document.layout import Typesetter
from va_document.pdfwriter import check_embeddable, read_id, write_pdf, MS_FONTS

DATA = Path(__file__).parent / "data"


def chars(path):
    """PDF の字（字, ページ, 字の左端, 基準線）。空白は除く。"""
    return [(c["text"], pno, c["x"], c["y"]) for pno, page in enumerate(pdfcheck.all_chars(path), start=1)
            for c in page if c["text"] not in (" ", "　")]


@pytest.fixture(scope="module")
def saiban_pdf(tmp_path_factory):
    dt = DOC_TYPES["Saiban"]
    ts = Typesetter(dt, keep=False)     # VA公用文の PDF と比べるので、見出しと本文を分けない処理をしない
    lines = ts.layout(parse((DATA / "裁判所" / "見本.md").read_text(encoding="utf-8").splitlines(), dt))
    path = tmp_path_factory.mktemp("pdf") / "準備書面.pdf"
    write_pdf(ts, lines, str(path), doc_id="K7Q29XMD", version=3)
    return path


def test_same_position_as_va_kouyoubun_pdf(saiban_pdf):
    """本文の字の上下・左右の位置とページ番号が、VA公用文の PDF と一致する。"""
    w, p = chars(DATA / "裁判所" / "VA公用文.pdf"), chars(saiban_pdf)
    body_w = [c for c in w if c[3] < 780]
    body_p = [c for c in p if c[3] < 780]
    sm = difflib.SequenceMatcher(None, [c[0] for c in body_w], [c[0] for c in body_p], autojunk=False)
    pairs = [(body_w[i + k], body_p[j + k]) for i, j, n in sm.get_matching_blocks() for k in range(n)]
    assert len(pairs) == len(body_w) == len(body_p)
    assert all(a[1] == b[1] and abs(a[2] - b[2]) <= 0.5 and abs(a[3] - b[3]) <= 0.25 for a, b in pairs)
    # ページ番号（下中央）
    num_w = [c for c in w if c[3] >= 780]
    num_p = [c for c in p if c[3] >= 780]
    assert len(num_w) == len(num_p) == 3
    assert all(a[0] == b[0] and abs(a[2] - b[2]) <= 0.1 and abs(a[3] - b[3]) <= 0.1 for a, b in zip(num_w, num_p))


def test_id_and_no_metadata(saiban_pdf):
    """識別子に文書ID と版が入り、文書情報と XMP が入っていない。"""
    assert read_id(str(saiban_pdf)) == ("K7Q29XMD", 3)
    info, xmp, ids = pdfcheck.metadata(saiban_pdf)
    assert info is None and not xmp                     # 文書情報（作成ソフト・作成者・日時など）も XMP も入れない
    assert ids == [b"VAMD:K7Q29XMD:000003"] * 2
    data = saiban_pdf.read_bytes()
    assert b"ReportLab" not in data and b"pypdf" not in data


def test_id_survives_resave(saiban_pdf, tmp_path):
    """保存し直しても、識別子の文書ID と版が残る（pypdf。VA mints のメタデータの除去〔pikepdf〕も）。"""
    other = tmp_path / "保存し直し.pdf"
    PdfWriter(clone_from=PdfReader(saiban_pdf)).write(other)
    assert read_id(str(other)) == ("K7Q29XMD", 3)
    pikepdf = pytest.importorskip("pikepdf")
    mints = tmp_path / "VA_mints.pdf"
    with pikepdf.open(saiban_pdf) as pdf:          # VA mints の metadata_remover.py と同じ
        for key in list(pdf.docinfo.keys()):
            del pdf.docinfo[key]
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as meta:
            meta.clear()
        pdf.save(mints)
    assert read_id(str(mints)) == ("K7Q29XMD", 3)


def test_no_id_for_other_pdf():
    """VA Documentが作っていない PDF は、識別子なしと判別する。"""
    assert read_id(str(DATA / "裁判所" / "VA公用文.pdf")) is None


def test_no_id_for_va_documake_pdf(saiban_pdf, tmp_path):
    """Ver160 まで（VA DocuMake）の PDF の識別子（VADM:）は読まない（2026-10-27 班長決定）。"""
    old = tmp_path / "VA_DocuMake.pdf"
    writer = PdfWriter(clone_from=PdfReader(saiban_pdf))
    first = ByteStringObject(b"VADM:K7Q29XMD:000003")
    writer._ID = ArrayObject([first, first])
    writer.write(old)
    assert read_id(str(old)) is None


def test_ms_mincho_is_embeddable():
    """ＭＳ 明朝の埋め込みの許可は「編集可能」（fsType=8）。"""
    assert check_embeddable(*MS_FONTS[0]) == 8
