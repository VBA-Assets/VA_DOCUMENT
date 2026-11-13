"""印刷の色（2026-10-30 班長決定）：字だけのページは灰色、画像のあるページはカラーで送る。カラーのページは、上から
BAND_ROWS 行ずつに分けて送り、帯の間がすかないこと。Microsoft Print to PDF に印刷して確かめる（Windows だけ）。"""
import time

import pytest
from PIL import Image

import pdfcheck
from va_document import printing
from va_document.pdfpages import PdfPages

H = 841.9


def color_pdf():
    """1ページ目は字だけ、2ページ目は字と、帯の切れ目をまたぐ高さのカラーの画像（用紙の上から 100〜700pt）。"""
    from reportlab.lib.utils import ImageReader
    red = ImageReader(Image.new("RGB", (40, 200), (220, 40, 40)))

    def page(k, image=False):
        def draw(c):
            c.setFont("Helvetica", 12)
            c.drawString(72, H - 72, f"page {k}")
            if image:
                c.drawImage(red, 100, H - 700, width=200, height=600)
        return draw
    return pdfcheck.make_pdf(page(1), page(2, image=True), size=(595.3, H))


def test_page_is_color():
    with PdfPages(color_pdf()) as doc:
        assert not printing.page_is_color(doc, 0)
        assert printing.page_is_color(doc, 1)


@pytest.fixture
def quiet_faulthandler():
    """Microsoft Print to PDF のドライバーは、中で Windows の例外を起こして中で処理する（test_app.py と同じ）。"""
    import faulthandler
    was = faulthandler.is_enabled()
    faulthandler.disable()
    yield
    if was:
        faulthandler.enable()


@pytest.mark.skipif(not printing.available(), reason="印刷は Windows だけ")
def test_color_page_is_printed_in_color_without_gaps(tmp_path, quiet_faulthandler):
    if "Microsoft Print to PDF" not in printing.printers():
        pytest.skip("Microsoft Print to PDF がない")
    out = tmp_path / "印刷.pdf"
    hdc = printing.make_dc("Microsoft Print to PDF")
    assert printing.print_pdf(color_pdf(), hdc, "色の試験", output=str(out)) == 2
    for _ in range(50):
        if out.exists() and out.stat().st_size:
            break
        time.sleep(0.2)
    time.sleep(0.5)
    assert pdfcheck.page_count(out) == 2
    gray = pdfcheck.render(out, 0, dpi=72).convert("RGB")
    assert all(len(set(gray.getpixel((x, y)))) == 1 for x in range(0, gray.width, 7) for y in range(0, gray.height, 7))
    # 2ページ目の画像は赤いまま。画像の上から下まで（帯の切れ目をまたいで）、白い行がない
    pix = pdfcheck.render(out, 1, dpi=150).convert("RGB")
    z = 150 / 72
    x = round(200 * z)
    reds = [pix.getpixel((x, y)) for y in range(round(105 * z), round(695 * z))]
    assert all(r > 150 and g < 120 and b < 120 for r, g, b in reds), [c for c in reds if c[0] <= 150 or c[1] >= 120][:3]
    # 送った解像度（600 dpi）でも、帯の切れ目（BAND_ROWS 行ごと）の前後に、白い行がない
    z = 600 / 72
    fine = pdfcheck.render(out, 1, dpi=600).convert("RGB")
    cut_rows = [r for r in range(printing.BAND_ROWS, round(700 * z), printing.BAND_ROWS) if r > round(100 * z)]
    assert cut_rows
    for r in cut_rows:
        for y in range(max(0, r - 3), min(fine.height, r + 3)):
            cr, cg, cb = fine.getpixel((round(200 * z), y))
            assert cr > 150 and cg < 120, (r, y, (cr, cg, cb))
