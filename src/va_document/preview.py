"""確認表示：組んだ PDF の全ページを縦に並べて表示し、エディターと連動させる（仕様.md の4）。ページはいつも欄の幅に
合わせる（拡大・縮小とページ送りのボタンは置かない。ページは、エディターのカーソル・ホイール・スクロールバーで送る。
2026-10-30 班長決定）。

メインの画面（app.MainWindow）の部品（mixin）。self.canvas・self.session などは MainWindow が持つ。
"""
import tkinter as tk

from . import theme
from .layout import FONT_SIZE
from .pdfpages import PdfPages
from .pdfwriter import FontNotEmbeddable
from .pseudonym import TOKEN_RE


PAGE_GAP = 12               # 確認表示のページの間（画素）
CARET_SIZE, CARET_MIN_SIZE = 5, 4   # 確認表示の印（▼）の幅の半分（ポイント×表示倍率。小さくしすぎない画素）
PREVIEW_SCROLL_STEP = 20    # ホイール1目盛り＝3単位で送る画素


class PreviewMixin:
    """確認表示（MainWindow に混ぜて使う）。"""

    def _render_preview(self):
        text = self.real_text()
        try:
            data = self.session.preview_pdf(text, highlight=True)     # 蛍光ペンは確認表示だけで塗る
        except FontNotEmbeddable as e:
            self.errors.record(e, "プレビュー")
            self.status.configure(text=str(e))
            return
        except Exception as e:      # 組めない文章でも、入力は続けられるようにする
            self.errors.record(e, "プレビュー")      # 続けて同じ誤りなら、1件にまとめる（diagnostics.ErrorLog）
            self.status.configure(text=f"プレビューを作れませんでした：{e}")
            return
        if self._preview_doc is not None:
            self._preview_doc.close()
        self._preview_doc = PdfPages(data)
        self._layout_pages()
        self._show_layout_warning()

    def _show_layout_warning(self):
        """組んだときの知らせ（ヘッダー・フッターが余白に入りきらないなど）を状態の欄に出す。知らせることが
        なくなったら、出していた知らせだけを消す（ほかの知らせは消さない）。"""
        m = self.session.layout_map
        warning = " ".join(m.ts.warnings) if m is not None else ""
        if warning:
            self.status.configure(text=warning)
        elif self._layout_warning and str(self.status.cget("text")) == self._layout_warning:
            self.status.configure(text="")
        self._layout_warning = warning

    def _fit_zoom(self):
        """ページを欄の幅いっぱいに合わせる倍率。"""
        return max(self.canvas.winfo_width(), 100) / self._preview_doc.size(0)[0]

    def _layout_pages(self, keep=True):
        """全ページを縦に並べる（スクロールバー・ホイールでページをまたいで送れる）。

        画像にするのは、見えているページだけとする（長い文書でも、組み直すたびに重くならない）。
        組み直したときは、表示していた位置（全体の何割か）を保つ。
        """
        doc = self._preview_doc
        if doc is None or not len(doc):
            return
        fraction = self.canvas.yview()[0] if keep else 0.0
        zoom = self._fit_zoom()
        width = max(self.canvas.winfo_width(), 100)
        page_w, page_h = doc.size(0)
        self._page_size = (round(page_w * zoom), round(page_h * zoom))
        pw, ph = self._page_size
        self._page_x = 0
        self._page_tops = [k * (ph + PAGE_GAP) for k in range(len(doc))]
        self._page_images = {}
        self._render_zoom = zoom
        self.canvas.delete("all")
        # 用紙は欄の幅いっぱいなので、左右の線は引かず、ページとページの境目だけを線で示す（最初のページの上と
        # 最後のページの下にも引かない。2026-10-31 班長指示）
        for k, top in enumerate(self._page_tops):
            self.canvas.create_rectangle(0, top, pw, top + ph, outline="", fill="white")
            if k:
                self.canvas.create_line(0, top - 1, pw, top - 1, fill=theme.BORDER)
                self.canvas.create_line(0, top - PAGE_GAP, pw, top - PAGE_GAP, fill=theme.BORDER)
        self.canvas.configure(scrollregion=(0, 0, max(pw, width), self._total_height()))
        self.canvas.yview_moveto(fraction)
        self._render_visible()
        self._show_caret(scroll=False)

    def _schedule_caret(self):
        if self._caret_job is not None:
            self.after_cancel(self._caret_job)
        self._caret_job = self.after(120, self._show_caret)

    def _cursor_real(self):
        """エディターのカーソルの位置を、実名の文章の (行, 字) にする（エディターは仮名なので、記号と元の語の長さの
        違いを直す）。"""
        line, col = (int(v) for v in self.text.index("insert").split("."))
        line -= 1
        return line, self._token_col(self.text.get(f"{line + 1}.0", f"{line + 1}.end"), col, to_real=True)

    def _token_col(self, line, col, to_real):
        """仮名の行の字の位置 ↔ 実名の行の字の位置（記号の長さと元の語の長さが違うため）。

        line は仮名の行。to_real なら col は仮名の行の位置で、実名の行の位置を返す。そうでなければ逆。
        記号の中の位置は、元の語の初め（実名 → 仮名では記号の初め）にする。
        """
        v = r = 0           # 仮名の行と実名の行で、見終えたところ
        for m in TOKEN_RE.finditer(line):
            e = self.session.dictionary.find(m.group(0))
            word_len = len(e.word) if e else len(m.group(0))
            seg = m.start() - v         # 記号の前の、仮名・実名で同じ部分
            if to_real:
                if col <= m.start():
                    return r + (col - v)
                if col < m.end():
                    return r + seg
            else:
                if col <= r + seg:
                    return v + (col - r)
                if col < r + seg + word_len:
                    return m.start()
            r += seg + word_len
            v = m.end()
        return r + (col - v) if to_real else v + (col - r)

    def _show_caret(self, scroll=True):
        """カーソルの字の位置に、確認表示で印を付ける。scroll なら、見えていないときにそのページへ送る。"""
        self._caret_job = None
        self.canvas.delete("caret")
        m = self.session.layout_map
        pos = self._cursor_real()
        if m is None or pos is None or not self._page_tops:
            return
        found = m.locate(*pos)
        if found is None:
            return
        page, x, top, h = found
        if page >= len(self._page_tops):
            return
        z = self._render_zoom
        cx =self._page_x + x * z
        cy = self._page_tops[page] + top * z
        # 印は、入力カーソルと同じ位置（字と字の間）の上の ▼（縦棒だと、確認表示に入力できるように見えるため。
        # 2026-10-23 班長決定）
        char_top = cy + (h - FONT_SIZE) / 2 * z
        s = max(CARET_MIN_SIZE, CARET_SIZE * z)
        # エディターの ▼ が点滅の途中（消えているところ）なら、確認表示の ▼ も消した形で描く（そろえて点滅させる）
        self.canvas.create_polygon(cx - s, char_top - s * 1.6, cx + s, char_top - s * 1.6, cx, char_top - 1,
                                   fill=theme.ACCENT, outline="", tags="caret",
                                   state="hidden" if self._blink_hidden else "normal")
        if scroll:
            view_top, view_h = self.canvas.canvasy(0), self.canvas.winfo_height()
            if cy < view_top or cy + h * z > view_top + view_h:
                self.canvas.yview_moveto(max(0.0, (cy - view_h / 3) / self._total_height()))
                self._render_visible()

    def _set_preview_caret_visible(self, visible):
        """確認表示の ▼ を、出す・消す（エディターの ▼ と一緒に点滅させる。2026-10-26 班長指示）。"""
        self.canvas.itemconfigure("caret", state="normal" if visible else "hidden")

    def on_preview_click(self, event):
        """確認表示でクリックした字の位置に、エディターのカーソルを動かす。"""
        m = self.session.layout_map
        if m is None or not self._page_tops:
            return
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        ph = self._page_size[1]
        page = next((k for k, top in enumerate(self._page_tops) if top <= cy < top + ph), None)
        if page is None:
            return
        z = self._render_zoom
        hit = m.hit(page, (cx - self._page_x) / z, (cy - self._page_tops[page]) / z)
        if hit is None:
            return
        self._move_cursor(*hit, scroll=False)

    def _move_cursor(self, line, col, scroll=True):
        """エディターのカーソルを、実名の文章の (行, 字) に動かし、確認表示に印を付ける（エディターは仮名なので、
        記号の側の位置に直す）。"""
        col = self._token_col(self.text.get(f"{line + 1}.0", f"{line + 1}.end"), col, to_real=False)
        index = f"{line + 1}.{col}"
        self.text.tag_remove("sel", "1.0", "end")
        self.text.mark_set("insert", index)
        self._scroll_to_third(index)
        self.text.focus_set()
        self._schedule_editor_mark()
        self._show_caret(scroll=scroll)

    def _on_yscroll(self, first, last):
        self._preview_yscroll.set(first, last)
        self.after_idle(self._render_visible)

    def _render_visible(self):
        doc = self._preview_doc
        if doc is None or not self._page_tops or len(self._page_tops) != len(doc):
            return
        top = self.canvas.canvasy(0)
        bottom = self.canvas.canvasy(self.canvas.winfo_height())
        ph = self._page_size[1]
        for k, y in enumerate(self._page_tops):
            if y + ph < top - ph or y > bottom + ph or k in self._page_images:
                continue
            self._page_images[k] = tk.PhotoImage(data=doc.render(k, self._render_zoom).png())
            self.canvas.create_image(self._page_x, y, image=self._page_images[k], anchor="nw")
            self.canvas.tag_raise("caret")
        # 表示中のページ：確認表示の真ん中にあるページ（一番上・一番下まで送ったときは、最初・最後のページ）
        if self.canvas.yview()[0] <= 0:
            self._preview_page = 0
        elif self.canvas.yview()[1] >= 1:
            self._preview_page = len(doc) - 1
        else:
            self._preview_page = self._page_at(top + self.canvas.winfo_height() / 2)
        self.page_label.configure(text=f"{self._preview_page + 1} / {len(doc)}")

    def _total_height(self):
        """確認表示の全ページを並べた高さ（画素）。"""
        return self._page_tops[-1] + self._page_size[1]

    def _page_at(self, y):
        """canvas の高さ y にあるページ（0 から）。"""
        k = 0
        for i, t in enumerate(self._page_tops):
            if t - PAGE_GAP <= y:
                k = i
        return k
