"""エディターのカーソルの上の ▼ と、カーソルの行への送り（2026-10-26 班長決定）。

メインの画面（app.MainWindow）の部品（mixin。editor_ops.EditorMixin が混ぜる）。self.text（tk.Text）は MainWindow が持つ。
"""
import tkinter as tk

from . import theme

EDITOR_MARK_HEIGHT = 6      # カーソルの上の ▼ の高さ（ポイント。行の間隔の最低値と同じで、行の間に入る）
EDITOR_MARK_WATCH_MS = 300  # ▼ の置き直しの漏れを拾う間隔（ミリ秒）
EDITOR_MARK_BLINK_MS = 1000         # カーソルを動かしたとき、▼ を点滅させる時間（ミリ秒。2026-10-26 班長指示）
EDITOR_MARK_BLINK_STEP_MS = 250     # 点滅の、出す・消すの1回の時間（ミリ秒）


class EditorMarkMixin:
    """カーソルの上の ▼（MainWindow に混ぜて使う）。"""

    def _init_editor_mark(self):
        """カーソルの上に、確認表示と同じ青い ▼ を常に出す仕組みを作る（self.text を作った直後に呼ぶ）。確認表示を
        使っている間はエディターのカーソルが点滅しないので、2つの画面を行き来しても位置が分かるようにする。

        Tk の入力欄には字の上に描けないので、小さな描画欄を重ねる。重ねた印は字と一緒に動かないので、カーソルが
        動く・送る・書き換えるたびに置き直す。プログラムでカーソルだけを動かしたとき（検索・置換、AI の回答の
        取り込みなど）の漏れは、しばらくごとの見回りで拾う。

        カーソルを動かしたときは、▼ を1秒点滅させてから出したままにする。確認表示の ▼ も同時に点滅させる（字を打つ・
        消す・貼り付けるときは点滅させない。入力の間ずっと点滅してしまうため。2026-10-26 班長指示・班長決定）。
        """
        self._editor_mark = tk.Canvas(self.text, highlightthickness=0, bd=0, background=self.text.cget("background"))
        self._editor_mark_at = self._editor_mark_job = None
        self._editor_mark_index = self._editor_text_len = None     # 前に置いたときのカーソルの位置と、文章の字数
        self._blink_job, self._blink_left, self._blink_hidden = None, 0, False
        for seq in ("<Key>", "<KeyRelease>", "<Button-1>", "<B1-Motion>", "<ButtonRelease-1>", "<Configure>",
                    "<<Modified>>"):
            self.text.bind(seq, lambda e: self._schedule_editor_mark(), add="+")
        self.after(EDITOR_MARK_WATCH_MS, self._watch_editor_mark)

    def _schedule_editor_mark(self):
        """エディターの処理（字の入力・カーソルの移動・送り）が済んだ後に、▼ を置き直す。"""
        if self._editor_mark_job is None:
            self._editor_mark_job = self.after_idle(self._show_editor_mark)

    def _watch_editor_mark(self):
        self._show_editor_mark()
        self.after(EDITOR_MARK_WATCH_MS, self._watch_editor_mark)

    def _show_editor_mark(self):
        """カーソルの上（行の間）に ▼ を置く。カーソルが見えていないときは消す。位置が変わっていなければ何もしない。"""
        self._editor_mark_job = None
        mark = self._editor_mark
        # カーソルが動き、文章の字数が変わっていなければ（字を打ったのではなく、カーソルを動かした）、点滅させる
        index, length = self.text.index("insert"), self.text.count("1.0", "end", "chars")
        if self._editor_mark_index is not None and index != self._editor_mark_index and length == self._editor_text_len:
            self._start_blink()
        self._editor_mark_index, self._editor_text_len = index, length
        self._update_nav_current()         # ナビゲーションも、カーソルのある見出しを選ぶ（navigation.py）
        box = self.text.bbox("insert")
        if box is None:
            mark.place_forget()
            self._editor_mark_at = None
            return
        # 行の間（行の間隔。オプションで 6 ポイントより狭くはできない）に入る大きさ。表示の拡大に合わせる
        h = max(4, round(EDITOR_MARK_HEIGHT * self.text.winfo_fpixels("1p")))
        s = round(h / 1.6)
        at = (box[0] - s, box[1] - h, s, h)
        if at == self._editor_mark_at:
            return
        self._editor_mark_at = at
        w = 2 * s + 1
        mark.delete("all")
        mark.configure(width=w, height=h)
        mark.create_polygon(0, 0, w, 0, s, h, fill=theme.ACCENT, outline="")
        self._set_mark_visible(not self._blink_hidden)

    def _set_mark_visible(self, visible):
        """エディターと確認表示の ▼ を、出す・消す（点滅は両方そろえる）。"""
        self._blink_hidden = not visible
        at = self._editor_mark_at
        if visible and at is not None:
            self._editor_mark.place(x=at[0], y=at[1], bordermode="outside")     # bbox は枠を含めた位置
        else:
            self._editor_mark.place_forget()
        self._set_preview_caret_visible(visible)

    def _start_blink(self):
        """▼ を点滅させ始める（点滅の途中でまた動かしたら、そこから数え直す）。消す・出すを繰り返し、出して終わる。"""
        if self._blink_job is not None:
            self.after_cancel(self._blink_job)
        self._blink_left = EDITOR_MARK_BLINK_MS // EDITOR_MARK_BLINK_STEP_MS // 2 * 2     # 偶数（出して終わる）
        self._set_mark_visible(True)
        self._blink_job = self.after(EDITOR_MARK_BLINK_STEP_MS, self._blink_step) if self._blink_left > 0 else None

    def _blink_step(self):
        self._blink_left -= 1
        self._set_mark_visible(self._blink_left % 2 == 0)
        self._blink_job = self.after(EDITOR_MARK_BLINK_STEP_MS, self._blink_step) if self._blink_left > 0 else None

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
