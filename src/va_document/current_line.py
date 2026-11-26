"""エディターの現在行の強調表示と、カーソルの行への送り。

メインの画面（app.MainWindow）の部品（mixin。editor_ops.EditorMixin が混ぜる）。self.text（tk.Text）は MainWindow が持つ。

カーソルのある行（エディターの1行＝段落。折り返した行も含めて）の地を、薄い灰色（theme.CURRENT_LINE_BG）にする。プレビューも、
カーソルの字のある行の地を同じ色にする（preview.py）。ナビゲーションは、カーソルのある見出しの行を同じ色にする（navigation.py）。
2026-11-27 班長指示で、カーソルの上の青い ▼ と、カーソルを動かしたときの ▼ の点滅（2026-10-26 班長決定・指示）を廃止して、
これに改めた（地の色を水色でなく灰色にしたのは、マークダウンの記号の青い字が見えにくくならないため）。
"""
from . import theme

CURRENT_LINE_TAG = "current_line"
CURRENT_LINE_WATCH_MS = 300  # 強調表示の置き直しの漏れを拾う間隔（ミリ秒）


class CurrentLineMixin:
    """エディターの現在行の強調表示（MainWindow に混ぜて使う）。"""

    def _init_current_line(self):
        """カーソルのある行の地を、いつも薄い灰色にする仕組みを作る（self.text を作った直後に呼ぶ）。プレビューを使って
        いる間はエディターのカーソルが点滅しないので、2つの画面を行き来しても、どの行にいるかが分かるようにする。

        地の色は、ほかの印（仮名化した語・蛍光ペン・検索で見つけた字・選んだ字）より下に置く（それらの色が見える）。
        カーソルが動く・書き換えるたびに置き直す。プログラムでカーソルだけを動かしたとき（検索・置換、AI の回答の
        取り込みなど）の漏れは、しばらくごとの見回りで拾う。
        """
        self.text.tag_configure(CURRENT_LINE_TAG, background=theme.CURRENT_LINE_BG)
        self._current_line_job = None
        self._current_line_at = None        # 強調している行（エディターの行の番号）
        for seq in ("<Key>", "<KeyRelease>", "<Button-1>", "<B1-Motion>", "<ButtonRelease-1>", "<<Modified>>"):
            self.text.bind(seq, lambda e: self._schedule_current_line(), add="+")
        self.after(CURRENT_LINE_WATCH_MS, self._watch_current_line)

    def _lower_current_line(self):
        """現在行の地の色を、ほかのすべての印の下に置く（印の色を付け終えてから呼ぶ。app._build_editor）。"""
        self.text.tag_lower(CURRENT_LINE_TAG)

    def _schedule_current_line(self):
        """エディターの処理（字の入力・カーソルの移動・送り）が済んだ後に、強調表示を置き直す。"""
        if self._current_line_job is None:
            self._current_line_job = self.after_idle(self._show_current_line)

    def _watch_current_line(self):
        self._show_current_line()
        self.after(CURRENT_LINE_WATCH_MS, self._watch_current_line)

    def _show_current_line(self, force=False):
        """カーソルのある行（改行まで。行の右端まで地の色が付く）を強調する。行が変わっていなければ何もしない
        （字を打って行が折り返しても、同じ行の中なら印は字と一緒に広がる）。"""
        self._current_line_job = None
        self._update_nav_current()         # ナビゲーションも、カーソルのある見出しを選ぶ（navigation.py）
        line = int(self.text.index("insert").split(".")[0])
        ranges = self.text.tag_ranges(CURRENT_LINE_TAG)
        whole = (len(ranges) == 2 and self.text.index(ranges[0]) == f"{line}.0"
                 and self.text.index(ranges[1]) == self.text.index(f"{line}.0 +1line"))
        if line == self._current_line_at and whole and not force:
            return
        self._current_line_at = line
        self.text.tag_remove(CURRENT_LINE_TAG, "1.0", "end")
        self.text.tag_add(CURRENT_LINE_TAG, f"{line}.0", f"{line}.0 +1line")

    def _scroll_to_third(self, index):
        """index の行を、見えていても、エディターの上から3分の1の高さに送る（see() だと端に出て、カーソルを探しにくい。
        いつも同じ高さに出れば探さなくてよい）。

        一度その行を一番上に送り、上から3分の1の高さとの差だけ戻す。文書の終わりの近くでは一番上まで送れず
        （文章の終わりで止まる）、決まった高さだけ戻すと行が下の端から外れるので、実際の位置との差で送る。
        """
        self.text.update_idletasks()
        self.text.yview(f"{index} display linestart")
        self.text.update_idletasks()
        info = self.text.dlineinfo(index)
        if info is not None:
            self.text.yview_scroll(info[1] - self.text.winfo_height() // 3, "pixels")
        self.text.see(index)        # 念のため（見えていれば何もしない）
