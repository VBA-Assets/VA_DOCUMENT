"""PDF のページを画像にする（プレビュー・印刷・印刷の画面の見本）。

pypdfium2（PDFium。Apache-2.0・BSD-3。VA FAX・VA Case と同じ部品）を使う。外部と通信しない。
Ver300（2026-11-14 班長決定）で、PyMuPDF（AGPL-3.0）から替えた（VA Document を MIT License にするため）。替える前に、
同じ PDF を両方で画像にして比べ、600 dpi の印刷で字の位置が 99.99% 一致し、プレビューも目で見て見分けがつかないことを
確かめた（試作\\render_compare.py）。
"""
import io

import pypdfium2 as pdfium
import pypdfium2.raw as raw


class Pixels:
    """ページを画像にしたもの。data は上の行から並べた画素（1行は stride バイト。4 の倍数）。n は1画素のバイト数
    （灰色は 1、カラーは 3）。bgr なら、カラーの画素は青・緑・赤の順（Windows の画像と同じ）。"""

    def __init__(self, data, width, height, stride, n, bgr=False):
        self.data, self.width, self.height, self.stride, self.n, self.bgr = data, width, height, stride, n, bgr

    def image(self):
        """Pillow の画像（灰色は L、カラーは RGB）。"""
        from PIL import Image
        if self.n == 1:
            return Image.frombuffer("L", (self.width, self.height), self.data, "raw", "L", self.stride, 1)
        return Image.frombuffer("RGB", (self.width, self.height), self.data, "raw", "BGR" if self.bgr else "RGB",
                                self.stride, 1)

    def png(self):
        """PNG のバイト列（Tk の PhotoImage に渡す。画面に出すだけなので、圧縮は軽くする）。"""
        buf = io.BytesIO()
        self.image().save(buf, "PNG", compress_level=1)
        return buf.getvalue()


class PdfPages:
    """PDF（バイト列）のページ。使い終わったら close する（with でも使える）。"""

    def __init__(self, data):
        self._doc = pdfium.PdfDocument(data)
        self._pages = {}
        self.closed = False

    def __len__(self):
        return len(self._doc)

    def _page(self, k):
        if k not in self._pages:
            self._pages[k] = self._doc[k]
        return self._pages[k]

    def size(self, k=0):
        """ページの幅と高さ（ポイント）。"""
        return self._page(k).get_size()

    def has_images(self, k):
        """ページに画像があるか（印刷をカラーにするかの判定。printing.page_is_color）。"""
        page = self._page(k)
        return next(iter(page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=4)), None) is not None

    def render(self, k, zoom, gray=False, top=None, bottom=None, bgr=False):
        """ページ k を zoom 倍（1 ポイントが zoom 画素）の画像にする。gray なら灰色。top・bottom（ポイント。ページの上から）を
        与えれば、その間の帯だけを画像にする。白地に描く（透明にしない）。"""
        page = self._page(k)
        w, h = page.get_size()
        crop = (0, 0, 0, 0)
        if top is not None or bottom is not None:
            crop = (0, h - (h if bottom is None else bottom), 0, 0 if top is None else top)    # 左・下・右・上から切る量
        bm = page.render(scale=zoom, crop=crop, grayscale=gray, rev_byteorder=not (gray or bgr),
                         fill_color=(255, 255, 255, 255))
        try:
            n = 1 if gray else 3
            data = bytes(bm.buffer)
            return Pixels(data, bm.width, bm.height, bm.stride, n, bgr=bgr and not gray)
        finally:
            bm.close()

    def close(self):
        if self.closed:
            return
        for p in self._pages.values():
            p.close()
        self._pages.clear()
        self._doc.close()
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
