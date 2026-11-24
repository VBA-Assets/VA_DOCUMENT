"""左右の欄（ナビゲーション・プレビュー・エディター）の並びと幅（2026-11-24 班長指示）。

メインの画面（app.MainWindow）の部品（mixin）。self.panes（tk.PanedWindow）・self._nav_pane・self._preview_pane・
self._work_pane は MainWindow が持つ。

・欄は左から、ナビゲーション（［ナビゲーション］にチェックを入れたときだけ）、プレビュー（［プレビュー］にチェックを入れた
  ときだけ）、エディター（いつも）の順に並べる。
・ナビゲーションを出す・隠すときは、エディターの幅を変えず、プレビューの幅で加減する（プレビューを隠していれば、エディターの
  幅で加減する）。プレビューを出す・隠すときは、ナビゲーションの幅を変えず、エディターの幅で加減する。
・出すかどうかと、ナビゲーション・プレビューの幅は、この PC の設定に覚え、次に起動したときに戻す。
"""
import time
import tkinter as tk

from . import config

PREVIEW_MIN_WIDTH = 300         # プレビューの幅の最小（画素）
PREVIEW_DEFAULT_WIDTH = 620     # プレビューを初めて出すときの幅（画素）
EDITOR_MIN_WIDTH = 560          # エディターの幅の最小（画素）
SASH_RESTORE_SECONDS = 1.5      # 起動から、欄の幅を置き直す間（秒）


class PaneMixin:
    """左右の欄の並びと幅（MainWindow に混ぜて使う）。"""

    def _pane_shown(self, pane):
        return str(pane) in (str(p) for p in self.panes.panes())

    def preview_shown(self):
        """プレビューを出しているか。"""
        return self._pane_shown(self._preview_pane)

    def _first_pane_after_nav(self):
        """ナビゲーションの右に来る欄（プレビューを出していればプレビュー、隠していればエディター）。"""
        return self._preview_pane if self.preview_shown() else self._work_pane

    def _pane_widths(self):
        """出している欄の今の幅 {"nav": 画素, "preview": 画素}（出していない欄は入れない）。"""
        sash = int(self.panes.cget("sashwidth"))
        out, left, k = {}, 0, 0
        for name, pane in (("nav", self._nav_pane), ("preview", self._preview_pane)):
            if self._pane_shown(pane):
                x = self.panes.sash_coord(k)[0]
                out[name] = x - left
                left, k = x + sash, k + 1
        return out

    def _place_panes(self, nav=None, preview=None):
        """出している欄の幅を、ナビゲーション nav・プレビュー preview（画素。None なら今の幅のまま）にする。エディターは
        残りの幅。境目は右から置く（左から置くと、右の境目が狙った位置まで動かないことがあった）。"""
        widths = self._pane_widths()
        sash = int(self.panes.cget("sashwidth"))
        places, x = [], 0
        for name, width in (("nav", nav), ("preview", preview)):
            if name not in widths:
                continue
            x += widths[name] if width is None else width
            places.append((len(places), x))
            x += sash
        try:
            for k, x in reversed(places):
                if self.panes.sash_coord(k)[0] != x:
                    self.panes.sash_place(k, x, 0)
        except tk.TclError:
            pass

    def _add_preview_pane(self, width):
        self.panes.add(self._preview_pane, before=self._work_pane, minsize=PREVIEW_MIN_WIDTH, width=width,
                       stretch="always")

    def on_toggle_preview(self):
        """リボンの［プレビュー］のチェックに合わせて、プレビューを出す・隠す（2026-11-24 班長指示）。ナビゲーションの幅は
        変えず、エディターの幅で加減する。隠している間も、開く・保存・印刷などは、そのまま使える（印刷は Ctrl+P）。"""
        show = bool(self.preview_var.get())
        if show == self.preview_shown():
            return
        widths = self._pane_widths()
        if show:
            width = max(PREVIEW_MIN_WIDTH, self.cfg.preview_width or PREVIEW_DEFAULT_WIDTH)
            self._add_preview_pane(width)
            self.update_idletasks()
            self._place_panes(nav=widths.get("nav"), preview=width)
            # 隠している間は、ページを画像にしていない（preview.py）。今の文章のページを並べ、カーソルの所へ送る
            self.after_idle(self._show_preview_again)
        else:
            self.cfg.preview_width = widths["preview"]
            self.panes.forget(self._preview_pane)
            self.update_idletasks()
            self._place_panes(nav=widths.get("nav"))
        self.cfg.preview_visible = show
        config.save(self.cfg)

    def _show_preview_again(self):
        self._layout_pages()
        self._show_caret()

    def on_toggle_navigation(self):
        """リボンの［ナビゲーション］のチェックに合わせて、一番左に出す・隠す。エディターの幅は変えず、プレビューの幅で
        加減する（プレビューを隠していれば、エディターの幅で加減する）。出すかどうかと幅は、この PC の設定に覚える。"""
        show = bool(self.nav_var.get())
        if show == self.nav_shown():
            return
        widths = self._pane_widths()
        sash = int(self.panes.cget("sashwidth"))
        if show:
            width = self.nav_start_width()
            self._add_nav_pane(width)
            self.update_idletasks()
            preview = widths.get("preview")
            self._place_panes(nav=width, preview=None if preview is None
                              else max(PREVIEW_MIN_WIDTH, preview - width - sash))
        else:
            self.cfg.nav_width = widths["nav"]
            self.panes.forget(self._nav_pane)
            self.update_idletasks()
            if "preview" in widths:
                self._place_panes(preview=widths["preview"] + widths["nav"] + sash)
        self.cfg.nav_visible = show
        config.save(self.cfg)
        if show:
            self._refresh_navigation()

    # ---------- 起動したときに戻す・閉じるときに覚える ----------

    def _restore_panes(self):
        """前回の欄の幅を戻す。起動直後は大きさが何度か変わるので、起動から少しの間は、欄の大きさが変わるたびに置き直す。"""
        if not (self.nav_shown() or (self.preview_shown() and self.cfg.preview_width > 0)):
            return
        self._sash_until = time.monotonic() + SASH_RESTORE_SECONDS
        for widget in (self.panes, self._preview_pane, self._work_pane, self._nav_pane):
            widget.bind("<Configure>", self._place_sash, add="+")
        self.after_idle(self._place_sash)

    def _place_sash(self, event=None):
        if self._sash_until is None or time.monotonic() > self._sash_until:
            self._sash_until = None
            return
        nav = self.nav_start_width() if self.nav_shown() else None
        preview = max(PREVIEW_MIN_WIDTH, self.cfg.preview_width) if self.cfg.preview_width > 0 else None
        self._place_panes(nav=nav, preview=preview)

    def _remember_panes(self):
        """出している欄の幅を、設定に覚える（隠している欄は、隠したときに覚えた幅のまま）。"""
        widths = self._pane_widths()
        if "nav" in widths:
            self.cfg.nav_width = widths["nav"]
        if "preview" in widths:
            self.cfg.preview_width = widths["preview"]
