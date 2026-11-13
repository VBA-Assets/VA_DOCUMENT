"""画像（[IMAGE 1]{30}。2026-10-29 班長決定。検討_画像の挿入.md）：取り込み・記号・組み方・PDF への出し入れ・保存と開き直し・
AI の回答の確かめ。画面の操作（［画像］・Ctrl+V）は test_app.py。"""
import io

import pytest
from PIL import Image, PngImagePlugin

import pdfcheck

from va_document import config, images, naiyou, vamd
from va_document.doctypes import DEFAULT_DOC_TYPE, DOC_TYPES, NAIYOU
from va_document.document import IMAGE, image_mark, image_numbers, parse
from va_document.layout import Typesetter
from va_document.layout_blocks import WRAP_GAP, WRAP_MIN
from va_document.pdfwriter import IMAGE_KEY, pdf_bytes, read_images
from va_document.recover import pdf_body_text
from va_document.session import Session

DT = DOC_TYPES[DEFAULT_DOC_TYPE]
BODY = "現場の状況は、次の写真のとおりである。" * 3


def png(size=(800, 600), color=(30, 90, 160), mode="RGB", **save):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG", **save)
    return buf.getvalue()


def picture(size=(800, 600), color=(30, 90, 160)):
    return images.from_bytes(png(size, color))


def typeset(text, sizes=None):
    ts = Typesetter(DT)
    ts.image_sizes = sizes if sizes is not None else {n: (800, 600) for n in range(1, 10)}
    paras = parse(text, DT)
    return ts, ts.layout(paras), paras


# ---------- 取り込み（付加情報の除去） ----------

def test_exif_and_gps_are_removed_and_orientation_applied():
    im = Image.new("RGB", (400, 300), (200, 180, 160))
    exif = Image.Exif()
    exif[0x013B] = "Kono Taro"               # 作成者
    exif[0x0110] = "Phone 15"                # 機種
    exif[0x0112] = 6                         # 向き（90 度回す）
    exif[0x8825] = {1: "N", 2: (35.0, 41.0, 22.0), 3: "E", 4: (139.0, 41.0, 30.0)}   # GPS
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif)
    pic = images.from_bytes(buf.getvalue())
    out = Image.open(io.BytesIO(pic.data))
    assert out.format == "JPEG" and pic.size == (300, 400)       # 向きを画素に反映した
    assert not dict(out.getexif()) and b"Kono" not in pic.data and b"Phone" not in pic.data


def test_png_text_chunks_and_transparency_are_removed():
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Kono Taro")
    info.add_text("Comment", r"C:\Users\someone\client\photo.png")
    pic = images.from_bytes(png((200, 100), (255, 0, 0, 0), mode="RGBA", pnginfo=info))
    out = Image.open(io.BytesIO(pic.data))
    assert out.format == "PNG" and out.mode == "RGB" and not out.text
    assert out.getpixel((10, 10)) == (255, 255, 255)             # 透過は白地に重ねた
    assert b"Kono" not in pic.data and b"client" not in pic.data


def test_large_image_is_shrunk_and_large_png_may_become_jpeg():
    pic = picture((5000, 1000))
    assert max(pic.size) == images.MAX_SIDE and pic.size == (2500, 500)
    # 写真のように PNG では大きくなる画像は、JPEG と比べて小さいほうにする
    noise = Image.effect_noise((2000, 1500), 80).convert("RGB")
    buf = io.BytesIO()
    noise.save(buf, "PNG")
    assert len(buf.getvalue()) > images.PNG_LIMIT
    assert Image.open(io.BytesIO(images.from_bytes(buf.getvalue()).data)).format == "JPEG"


def test_not_image():
    with pytest.raises(images.NotImage):
        images.from_bytes(b"not an image")


def test_natural_chars():
    pitch = Typesetter(DT).pitch
    assert images.natural_chars(picture((96, 10)), pitch) == 6        # 72pt ÷ 字送り 12.45pt を切り上げ
    assert images.natural_chars(picture((1, 1)), pitch) == 1


# ---------- 記号 ----------

@pytest.mark.parametrize("line, expected", [
    ("[IMAGE 1]{30}", (1, 30)),
    ("[image 12]", (12, None)),
    (":-: [IMAGE 3]{20}", (3, 20)),
    ("--: [IMAGE 3]{15}  ", (3, 15)),
    ("->2 [IMAGE 4]{10}", (4, 10)),
    ("　[IMAGE 5]{10}", (5, 10)),
    ("写真は[IMAGE 1]{30}のとおり", None),        # 同じ行に字があるものは画像にしない（均等割付の字）
    ("[HEADER] [IMAGE 1]{30}", None),           # ヘッダー・フッターの画像は扱わない
    ("[IMAGE 0]{30}", None),
    ("[IMAGE 1000]", None),
    ("[IMAGE 1]{0}", None),
    ("[ＩＭＡＧＥ 1]{30}", None),                 # 半角だけを記号とする
    ("| [IMAGE 1]{3} |", None),
])
def test_image_mark(line, expected):
    assert image_mark(line) == expected


def test_parse_image_keeps_heading_state():
    paras = parse(["# 状況", "--: [IMAGE 2]{12}", "本文", "## 次"], DT)
    p = paras[1]
    assert p.kind == IMAGE and p.image == (2, 12) and p.align == "right" and p.body_level == 1 and p.src_line == 1
    assert paras[2].body_level == 1 and paras[3].number            # 右揃えでも、後の変換は止めない
    assert image_numbers(["[IMAGE 2]", "x", ":-: [IMAGE 2]{3}", "[IMAGE 5]"]) == [2, 2, 5]


# ---------- 組み方 ----------

def test_block_image_uses_whole_rows_and_next_text_on_grid():
    ts, lines, _ = typeset(["本文の一行目。", "[IMAGE 1]{20}", "次の本文。"])
    im = ts.images[0]
    assert im.page == 1 and im.y == pytest.approx(ts.margin_top + ts.line_pitch)
    assert im.w == pytest.approx(20 * ts.pitch) and im.h == pytest.approx(im.w * 0.75)
    rows = -(-(im.h - 0.01) // ts.line_pitch)
    assert lines[1].row == 1 + rows and not im.missing and not im.wrap


def test_image_alignment_and_width_limits():
    ts, _, _ = typeset([":-: [IMAGE 1]{20}", "--: [IMAGE 2]{40}", "[IMAGE 3]", "[IMAGE 4]{99}"])
    a, b, c, d = ts.images
    assert a.x == pytest.approx((ts.text_w - a.w) / 2)
    assert b.x == pytest.approx(ts.text_w - b.w) and not b.wrap          # 回り込む幅が足りない
    assert c.w == pytest.approx(ts.text_w) and d.w == pytest.approx(ts.text_w)


def test_image_that_does_not_fit_goes_to_next_page_and_tall_image_shrinks():
    text = ["本文。"] * (DT.chars_lines[1] - 2) + ["[IMAGE 1]{20}", "後の本文。"]
    ts, lines, _ = typeset(text)
    assert ts.images[0].page == 2 and ts.images[0].y == pytest.approx(ts.margin_top)
    assert lines[-1].page == 2
    ts, _, _ = typeset(["[IMAGE 1]"], {1: (100, 1000)})
    im = ts.images[0]
    assert im.h == pytest.approx(ts.lines_page * ts.line_pitch) and im.w == pytest.approx(im.h / 10)


def test_missing_image_is_a_frame_without_text():
    ts, lines, paras = typeset(["[IMAGE 7]{20}", "本文。"], {})
    assert ts.images[0].missing and ts.images[0].h == pytest.approx(ts.images[0].w * 0.75)
    data = pdf_bytes(ts, lines, highlight=True)
    assert pdfcheck.lines(data, 0) == ["本文。", "1"]                     # 本文とページ番号だけ
    assert not pdfcheck.images(data, 0) and pdfcheck.drawings(data, 0)  # 枠は線で描き、字は描かない


def test_right_image_wraps_following_text():
    ts, lines, _ = typeset(["--: [IMAGE 1]{12}", BODY * 3, "後の本文。"])
    im = ts.images[0]
    assert im.wrap and im.y == pytest.approx(ts.margin_top)
    zone = -(-(im.h - 0.01) // ts.line_pitch)
    limit = ts.text_w - im.w - WRAP_GAP * ts.pitch
    body = [ln for ln in lines if ln.para_index == 1][:-1]     # 段落の最後の行（短い）は除く
    assert len(body) > zone
    for ln in body:
        right = max(g.x + ts.advance(g.ch) for g in ln.glyphs)
        if ln.row < zone:
            assert right <= limit + ts.pitch + 0.01       # ぶら下げの句読点は、間の1字に入る
        else:
            assert right > limit                          # 画像の下は元の幅
    assert lines[0].row == 0                              # 画像の行は行を使わない


def test_wrap_needs_minimum_width():
    ts, lines, _ = typeset(["--: [IMAGE 1]{" + str(DT.chars_lines[0] - WRAP_MIN - WRAP_GAP + 1) + "}", "本文。"])
    assert not ts.images[0].wrap and lines[0].row > 0


def test_wrap_ends_at_table_and_page_break():
    ts, lines, paras = typeset(["--: [IMAGE 1]{12}", "短い本文。", "| 甲 | 乙 |", "|---|---|", "| 1 | 2 |"])
    im, table = ts.images[0], ts.tables[0]
    assert table.rows[0].top >= im.y + im.h - 0.01            # 表は画像の下から
    ts, lines, paras = typeset(["--: [IMAGE 1]{12}", "短い本文。", "<<<", "次のページ。"])
    assert lines[-1].page == 2 and lines[-1].row == 0


def test_wrap_image_moved_to_next_page_wraps_there():
    text = ["本文。"] * (DT.chars_lines[1] - 2) + ["--: [IMAGE 1]{12}", BODY * 2]
    ts, lines, _ = typeset(text)
    im = ts.images[0]
    assert im.page == 2 and im.wrap
    first = [ln for ln in lines if ln.para_index == len(text) - 1]
    assert first[0].page == 1                                  # 前のページの残りは、元の幅のまま組む
    full = max(g.x for g in first[0].glyphs)
    on_next = [ln for ln in first if ln.page == 2 and ln.row == 0]
    assert on_next and max(g.x for g in on_next[0].glyphs) < full - im.w + 0.01


def test_lines_without_images_are_unchanged():
    """画像のない文書の組み方は変わらない（VA公用文との一致の試験は test_layout_vs_va_kouyoubun）。"""
    a, la, _ = typeset([BODY, "# 見出し", BODY])
    b, lb, _ = typeset([BODY, "# 見出し", BODY], {})
    assert [(ln.page, ln.row, [(g.ch, g.x) for g in ln.glyphs]) for ln in la] == \
           [(ln.page, ln.row, [(g.ch, g.x) for g in ln.glyphs]) for ln in lb]


# ---------- PDF ----------

def test_pdf_images_round_trip_with_numbers(tmp_path):
    blue, red = picture(), picture((300, 200), (200, 30, 30))
    ts, lines, _ = typeset(["[IMAGE 1]{20}", "本文。", "[IMAGE 2]{10}", "[IMAGE 1]{5}", "[IMAGE 3]{10}"],
                           {1: blue.size, 2: red.size, 3: blue.size})
    data = pdf_bytes(ts, lines, doc_id="K7Q29XMD", version=1, images={1: blue, 2: red, 3: blue})
    path = tmp_path / "a.pdf"
    path.write_bytes(data)
    got = read_images(str(path))
    assert set(got) == {1, 2, 3}
    assert got[2].size == red.size and got[1].size == blue.size
    for n, pic in ((1, blue), (2, red), (3, blue)):
        assert Image.open(io.BytesIO(got[n].data)).convert("RGB").tobytes() == \
               Image.open(io.BytesIO(pic.data)).convert("RGB").tobytes()
    assert pdfcheck.images(path) == 4                            # 画像1 は2か所に置いた
    info, xmp, _ = pdfcheck.metadata(path)
    assert not info and not xmp                                  # 文書情報（作成者など）と XMP は入れない
    # 同じ中身の 1・3 は1つにまとまり、番号は配列
    assert sorted(map(str, pdfcheck.image_marks(path, IMAGE_KEY))) == ["2", "[1, 3]"]
    # 画像は字を持たないので、構文ファイルとの突き合わせの字は変わらない
    assert pdf_body_text(str(path), ts)[0] == "本文。"


# ---------- 保存と開き直し ----------

@pytest.fixture
def session(tmp_path):
    return Session(config.AppConfig(vamd_folder=str(tmp_path / "構文ファイル")))


def test_save_and_reopen_restores_images_by_number(session, tmp_path):
    blue, red = picture(), picture((300, 200), (200, 30, 30))
    text = "# 状況\n甲野太郎の写真\n"
    session.dictionary.register("甲野太郎", "人名")
    n1 = session.add_picture(blue, text)
    n2 = session.add_picture(red, text)
    text += f"[IMAGE {n1}]{{20}}\n--: [IMAGE {n2}]{{10}}\n本文。\n"
    pdf = tmp_path / "準備書面.pdf"
    session.save(text, pdf)
    raw = session.vamd_path.read_bytes()
    assert b"[IMAGE 1]{20}" in raw and b"IHDR" not in raw and b"JFIF" not in raw    # 画像は構文ファイルに書かない
    # AI の回答で、画像の行の順が入れ替わったとする（番号で結ぶので、取り違えない）
    body = session.vamd_path.read_text(encoding="utf-8")
    body = body.replace("[IMAGE 1]{20}\n--: [IMAGE 2]{10}", "--: [IMAGE 2]{10}\n[IMAGE 1]{20}")
    session.vamd_path.write_text(body, encoding="utf-8")
    other = Session(session.cfg)
    result = other.open_vamd(session.vamd_path, pdf)
    assert set(other.images) == {1, 2} and other.images[2].size == red.size and other.images[1].size == blue.size
    assert not other.missing_images(result.text)
    assert other.add_picture(blue, result.text) == 3                     # 番号は続きから


def test_unused_pdf_images_are_reported_and_kept(session, tmp_path):
    n = session.add_picture(picture(), "")
    pdf = tmp_path / "a.pdf"
    session.save(f"[IMAGE {n}]{{10}}\n本文。\n", pdf)
    body = session.vamd_path.read_text(encoding="utf-8").replace("[IMAGE 1]{10}\n", "")
    session.vamd_path.write_text(body, encoding="utf-8")
    other = Session(session.cfg)
    result = other.open_vamd(session.vamd_path, pdf)
    assert 1 in other.images and any("画像 1" in m for m in result.messages)


def test_open_without_pdf_has_missing_images(session, tmp_path):
    n = session.add_picture(picture(), "")
    session.save(f"[IMAGE {n}]{{10}}\n本文。\n", tmp_path / "a.pdf")
    other = Session(session.cfg)
    result = other.open_vamd(session.vamd_path, False)
    assert other.images == {} and other.missing_images(result.text) == [1]


def test_numbers_are_not_reused(session):
    assert session.add_picture(picture(), "") == 1
    assert session.add_picture(picture(), "") == 2
    del session.images[2]                                   # 行を消しても番号は使い回さない
    assert session.add_picture(picture(), "") == 3
    assert session.add_picture(picture(), "[IMAGE 9]") == 10   # 文章にある、データのない番号も避ける


# ---------- AI の回答の確かめ ----------

def _review(current, answer, images_known=(1,)):
    content = vamd.parse_text(vamd.build("K7Q29XMD", 1, vamd.Settings(DEFAULT_DOC_TYPE), answer))
    return vamd.review(content, "K7Q29XMD", 1, current.splitlines(), _NoDictionary(), images_known)


class _NoDictionary:
    def find(self, token):
        return None


def test_review_reports_lost_unknown_and_added_images():
    current = "本文。\n[IMAGE 1]{20}\n後の本文。"
    assert _review(current, "本文を直した。\n[IMAGE 1]{25}\n後の本文。").clean     # 幅を変えるのはよい
    assert _review(current, "後の本文。\n[IMAGE 1]{20}\n本文。").clean          # 動かすのはよい
    r = _review(current, "本文。\n後の本文。")
    assert ("[IMAGE 1]", "[IMAGE 1]{20}") in r.lost_marks
    r = _review(current, "本文。\n[IMAGE 1]{20}\n[IMAGE 4]{20}\n後の本文。")
    assert r.unknown_images == [4] and not r.clean
    r = _review(current, "本文。\n[IMAGE 1]{20}\n後の本文。\n[IMAGE 1]{20}")
    assert r.added_images == [1] and not r.clean


def test_prompt_explains_image_mark():
    assert "[IMAGE 1]{30}" in vamd.PROMPT and "画像そのものは、あなたに渡していない" in vamd.PROMPT


# ---------- 内容証明 ----------

def test_naiyou_reports_image_after_chars_and_lines():
    dt = DOC_TYPES[NAIYOU]
    ts = Typesetter(dt)
    ts.image_sizes = {1: (800, 600)}
    lines = ts.layout(parse(["本文。", "[IMAGE 1]{10}"], dt))
    problem = naiyou.check(ts, lines)
    assert problem.kind == "image" and "画像" in problem.message()
