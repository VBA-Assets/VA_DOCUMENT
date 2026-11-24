"""ナビゲーション ウィンドウ（見出しの一覧。2026-11-24 班長指示「Word のナビゲーションと同じ機能」）。

メインの画面（app.MainWindow）の部品（mixin）。self.text（tk.Text）・self.panes などは MainWindow が持つ。

・リボンの「表示」の［ナビゲーション］にチェックを入れたときだけ、ウィンドウの一番左に出す（表示するか・幅は、この PC の
  設定に覚える）。
・エディターの見出しを、レベルに合わせて木の形で並べる（番号は組んだときと同じ。エディターと同じく、仮名化した語は記号の
  まま）。見出しの読み取りと、範囲の決め方は outline.py。
・見出しをクリックする（↑↓で選ぶ）と、エディターのカーソルをその見出しへ動かす。エディターでカーソルを動かすと、カーソルの
  ある見出しを選ぶ（行の地が青くなる。畳んだ見出しの中なら、畳んだ見出しを選ぶ）。はじめはエディター・プレビューと同じ ▼ も
  付けたが、行の地の色で分かるので外した（2026-11-24 班長指示）。
・見出しをドラッグ アンド ドロップすると、その見出しに属する見出し・本文と一緒に動かす（レベルは変えない）。
・右クリックのメニュー（レベルを上げる・レベルを下げる・前に／後に／小見出しを挿入・見出しと本文を選択・削除。挿入と選択は
  2026-11-24 班長決定）と、キー（Alt+Shift+←→ でレベル、Alt+Shift+↑↓ で同じ親の
  前後の見出しと入れ替え、Delete で削除）。どれも、その見出しに属する見出し・本文に及び、Ctrl+Z 1回で戻せる。
・プレビュー（書式付きファイル）は、書き換えたエディターの文章で組み直す（ほかの書き換えと同じ）。
"""
import tkinter as tk
from tkinter import ttk

from . import outline, theme
from .undo import undoable

NAV_MIN_WIDTH = 150         # ナビゲーションの幅の最小（画素。題の行〔題と［展開］［折りたたむ］〕が入る幅より狭くはしない）
NAV_DEFAULT_WIDTH = 240     # 初めて出すときの幅（画素。同じく、題の行が入る幅より狭くはしない）
DRAG_START = 5              # この画素より動かしたら、ドラッグとみなす（クリックと見分ける）
DRAG_SCROLL_EDGE = 12       # ドラッグ中に、一覧の上下の端からこの画素の内に来たら、一覧を送る


class NavigationMixin:
    """ナビゲーション ウィンドウ（MainWindow に混ぜて使う）。"""

    # ------------------------------------------------------------------
    # 部品
    # ------------------------------------------------------------------

    def _build_navigation(self, parent):
        """ナビゲーションの欄（上に題、下に見出しの一覧とスクロールバー）を作る。panes には足さない（on_toggle_navigation）。"""
        self._nav_pane = pane = ttk.Frame(parent)
        self._nav_heads = []                # outline.Heading のリスト（一覧の項目 "h<番号>" と同じ順）
        self._nav_signature = None          # 一覧を作ったときの見出しの並び（変わったときだけ作り直す）
        self._nav_current = None            # カーソルのある見出しとして選んでいる項目
        self._nav_drag = None               # ドラッグの状態
        # 題の行。高さは、プレビュー・エディターの上のファイルの名前の行にそろえる（app._build）
        self._nav_head = head = ttk.Frame(pane, height=1)
        head.pack(fill="x")
        head.pack_propagate(False)
        ttk.Label(head, text="ナビゲーション", style="Note.TLabel", anchor="w", padding=(0, 0, 0, 4)).pack(
            side="left", fill="y")
        # 一覧の全体に効く操作は、題の右に置く（プレビューの［印刷］、エディターの［パスをコピー］と同じ形。名前は
        # ［展開］［折りたたむ］だけとする。2026-11-24 班長指示）。一覧の見た目だけを変え、文章は変えない
        self.nav_expand_button = ttk.Button(head, text="展開", style="Small.TButton",
                                            command=self.on_nav_expand_all)
        self.nav_collapse_button = ttk.Button(head, text="折りたたむ", style="Small.TButton",
                                              command=self.on_nav_collapse_all)
        for button in (self.nav_expand_button, self.nav_collapse_button):
            button.pack(side="left", padx=(8, 0), pady=(0, 4))
        if self.icons is not None:      # 欄の幅を、アイコンを付けたボタンの幅で決めるため、ここで付ける
            try:
                self.icons.decorate(head)
            except Exception:
                pass
        body = ttk.Frame(pane)
        body.pack(fill="both", expand=True)
        # 書体・字の大きさ・行の高さは、オプションで変えられる（Nav.Treeview。theme.apply_nav_prefs）
        self.nav_tree = tree = ttk.Treeview(body, show="tree", selectmode="browse", style=theme.LIST_STYLE)
        ys = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        self._nav_empty = ttk.Label(tree, text="見出しがありません。", style="FieldNote.TLabel")
        self._nav_drop_line = tk.Frame(pane, height=2, background=theme.ACCENT)   # ドラッグで置く位置の線
        tree.bind("<<TreeviewSelect>>", self._on_nav_select)
        for seq in ("<<TreeviewOpen>>", "<<TreeviewClose>>"):     # 開く・畳むのは、この知らせの後
            tree.bind(seq, lambda e: self.after_idle(self._after_nav_open_close))
        tree.bind("<ButtonPress-1>", self._on_nav_press, add="+")
        tree.bind("<B1-Motion>", self._on_nav_motion)
        tree.bind("<ButtonRelease-1>", self._on_nav_release, add="+")
        tree.bind("<Alt-Shift-Left>", lambda e: self.on_nav_level(-1))
        tree.bind("<Alt-Shift-Right>", lambda e: self.on_nav_level(1))
        tree.bind("<Alt-Shift-Up>", lambda e: self.on_nav_move(-1))
        tree.bind("<Alt-Shift-Down>", lambda e: self.on_nav_move(1))
        tree.bind("<Delete>", lambda e: self.on_nav_delete())
        # 削除などの後の Ctrl+Z・Ctrl+Y は、一覧を選んだままでも、エディターの書き換えを戻す
        tree.bind("<<Undo>>", lambda e: self._nav_undo(self.on_undo))
        tree.bind("<<Redo>>", lambda e: self._nav_undo(self.on_redo))
        self._init_nav_menu()
        return pane

    def _init_nav_menu(self):
        """見出しの右クリックのメニュー（2026-11-24 班長指示）。Mac では右クリックが Button-2 になり、Control+クリックでも開く。"""
        self.nav_menu = menu = tk.Menu(self.nav_tree, tearoff=0, background=theme.FIELD_BG, foreground=theme.TEXT,
                                       activebackground=theme.HOVER_BG, activeforeground=theme.TEXT)
        menu.add_command(label="レベルを上げる", accelerator="Alt+Shift+←", command=lambda: self.on_nav_level(-1))
        menu.add_command(label="レベルを下げる", accelerator="Alt+Shift+→", command=lambda: self.on_nav_level(1))
        # 見出しの挿入と、見出しと本文の選択（Word のナビゲーション ウィンドウにならう。2026-11-24 班長決定）
        menu.add_separator()
        menu.add_command(label="前に見出しを挿入", command=lambda: self.on_nav_insert(outline.BEFORE))
        menu.add_command(label="後に見出しを挿入", command=lambda: self.on_nav_insert(outline.AFTER))
        menu.add_command(label="小見出しを挿入", command=lambda: self.on_nav_insert(outline.CHILD))
        menu.add_separator()
        menu.add_command(label="見出しと本文を選択", command=self.on_nav_select_section)
        menu.add_separator()
        menu.add_command(label="削除", accelerator="Delete", command=self.on_nav_delete)
        mac = self.tk.call("tk", "windowingsystem") == "aqua"
        for seq in (("<Button-2>", "<Control-Button-1>") if mac else ("<Button-3>",)):
            self.nav_tree.bind(seq, self._on_nav_menu)

    # ------------------------------------------------------------------
    # 出す・隠す（出す・隠す操作と幅は panes.py）
    # ------------------------------------------------------------------

    def nav_shown(self):
        """ナビゲーションを出しているか。"""
        return str(self._nav_pane) in (str(p) for p in self.panes.panes())

    def nav_min_width(self):
        """ナビゲーションの幅の最小：題の行（題と、題の右のボタン）が入りきる幅（NAV_MIN_WIDTH より狭くはしない）。"""
        head = self._nav_head.winfo_children()
        need = sum(w.winfo_reqwidth() for w in head) + 8 * (len(head) - 1) + 4
        return max(NAV_MIN_WIDTH, need)

    def nav_start_width(self):
        """ナビゲーションを出すときの幅（覚えた幅。なければ既定の幅。どちらも最小より狭くはしない）。"""
        return max(self.nav_min_width(), self.cfg.nav_width or NAV_DEFAULT_WIDTH)

    def _add_nav_pane(self, width):
        self.panes.add(self._nav_pane, before=self._first_pane_after_nav(), minsize=self.nav_min_width(), width=width,
                       stretch="never")

    # ------------------------------------------------------------------
    # 一覧と、カーソルのある見出し
    # ------------------------------------------------------------------

    def _refresh_navigation(self):
        """エディターの文章から見出しを読み直し、並びが変わったときだけ一覧を作り直す（畳んだ見出しと、送った位置は残す）。
        出していないときは何もしない（出すときに作る）。"""
        if "nav_tree" not in self.__dict__ or not self.nav_shown():
            self._nav_signature = None
            return
        self._nav_heads = heads = outline.headings(self.raw_text().split("\n"), self.session.doc_type)
        signature = tuple((h.level, h.label, h.parent) for h in heads)
        if signature != self._nav_signature:
            self._rebuild_nav_tree(heads)
            self._nav_signature = signature
        self._update_nav_current(force=True)

    def _rebuild_nav_tree(self, heads):
        tree = self.nav_tree
        closed = {tree.item(i, "text") for i in self._nav_items() if tree.get_children(i) and not tree.item(i, "open")}
        top = tree.yview()[0]
        tree.delete(*tree.get_children())
        self._nav_current = None
        for k, h in enumerate(heads):
            tree.insert("" if h.parent < 0 else f"h{h.parent}", "end", iid=f"h{k}", text=h.label, open=True)
        for i in self._nav_items():
            if tree.get_children(i) and tree.item(i, "text") in closed:
                tree.item(i, open=False)
        tree.yview_moveto(top)
        self._update_nav_buttons()
        if heads:
            self._nav_empty.place_forget()
        else:
            self._nav_empty.place(x=8, y=6)

    def _nav_items(self, parent=""):
        """一覧の項目（上から順。畳んだ見出しの中も）。"""
        out = []
        for i in self.nav_tree.get_children(parent):
            out.append(i)
            out += self._nav_items(i)
        return out

    def _update_nav_current(self, force=False):
        """エディターのカーソルのある見出しを選ぶ（エディターの ▼ を置き直すたびに呼ぶ。editor_mark.py）。畳んだ見出しの
        中なら、畳んだ見出しを選ぶ。見出しの外（最初の見出しの前、「以上」など）なら、どれも選ばない。"""
        if "nav_tree" not in self.__dict__ or "text" not in self.__dict__ or not self.nav_shown():
            return
        tree = self.nav_tree
        line = int(self.text.index("insert").split(".")[0]) - 1
        k = outline.heading_at(self._nav_heads, line)
        item = self._nav_visible_item(f"h{k}") if k >= 0 and tree.exists(f"h{k}") else None
        old = self._nav_current
        if item == old and not force:
            return
        self._nav_current = item
        if item is None:
            tree.selection_remove(*tree.selection())
            return
        if tree.selection() != (item,):
            tree.selection_set(item)
        tree.focus(item)
        if item != old:
            tree.see(item)          # 書き換えのたびには送らない（利用者が一覧を送って見ている所を動かさない）

    def on_nav_expand_all(self):
        """［展開］：畳んだ見出しをすべて開く（一覧の見た目だけ。文章は変えない）。"""
        self._nav_open_all(True)

    def on_nav_collapse_all(self):
        """［折りたたむ］：下のレベルの見出しを持つ見出しをすべて畳む（いちばん上のレベルの見出しだけが見える）。
        カーソルのある見出しが畳んだ見出しの中に入れば、その外側の見出しを選ぶ。"""
        self._nav_open_all(False)

    def _after_nav_open_close(self):
        """見出しの左の三角で開いた・畳んだ後：ボタンの押せる・押せないと、カーソルのある見出しを合わせる。"""
        self._update_nav_buttons()
        self._update_nav_current(force=True)

    def _update_nav_buttons(self):
        """［展開］は畳んだ見出しがあるときだけ、［折りたたむ］は開いた見出し（下のレベルの見出しを持つもの）があるときだけ
        押せるようにする（押しても何も変わらないときは灰色にする。2026-11-24 班長指摘）。"""
        tree = self.nav_tree
        parents = [i for i in self._nav_items() if tree.get_children(i)]
        opened = [bool(tree.item(i, "open")) for i in parents]
        self.nav_expand_button.configure(state="normal" if not all(opened) else "disabled")
        self.nav_collapse_button.configure(state="normal" if any(opened) else "disabled")

    def _nav_open_all(self, open_):
        tree = self.nav_tree
        for item in self._nav_items():
            if tree.get_children(item):
                tree.item(item, open=open_)
        self._update_nav_buttons()
        self._update_nav_current(force=True)
        if self._nav_current is not None:
            tree.see(self._nav_current)

    def _nav_visible_item(self, item):
        """item が畳んだ見出しの中にあれば、見えている（いちばん外側の畳んだ）見出し。"""
        tree = self.nav_tree
        found, parent = item, tree.parent(item)
        while parent:
            if not tree.item(parent, "open"):
                found = parent
            parent = tree.parent(parent)
        return found

    # ------------------------------------------------------------------
    # クリック・選ぶ
    # ------------------------------------------------------------------

    def _on_nav_select(self, event=None):
        """↑↓などで選んだ見出しへ、エディターのカーソルを動かす（カーソルのある見出しとして選んだときは動かさない）。"""
        selected = self.nav_tree.selection()
        if selected and selected[0] != self._nav_current:
            self._nav_go(selected[0])

    def _nav_go(self, item):
        """エディターのカーソルを、見出しの行の先頭へ動かす（エディターの上から3分の1の高さに出す）。キーボードの焦点は
        一覧に残す（続けて ↑↓ や Delete を押せるように）。"""
        k = self._nav_index(item)
        if k is None:
            return
        index = f"{self._nav_heads[k].line + 1}.0"
        self.text.tag_remove("sel", "1.0", "end")
        self.text.mark_set("insert", index)
        self._scroll_to_third(index)
        self._schedule_editor_mark()
        self._show_caret()

    def _nav_index(self, item):
        """一覧の項目の見出しの番号（outline.headings の何番目か）。"""
        try:
            k = int(str(item)[1:])
        except ValueError:
            return None
        return k if 0 <= k < len(self._nav_heads) else None

    def _nav_selected(self):
        """選んでいる見出しの番号。エディターの書き換えを、まだ一覧に入れていなければ、先に入れる（古い行の番号で書き換え
        ないように）。選んでいなければ None。"""
        if self._refresh_job is not None:
            self.refresh()
        selected = self.nav_tree.selection()
        return self._nav_index(selected[0]) if selected else None

    # ------------------------------------------------------------------
    # ドラッグ アンド ドロップ
    # ------------------------------------------------------------------

    def _on_nav_press(self, event):
        tree = self.nav_tree
        item = tree.identify_row(event.y)
        element = str(tree.identify_element(event.x, event.y))
        # 開く・畳む印（三角）を押したときは、ドラッグしない
        self._nav_drag = ({"item": item, "y": event.y, "active": False, "target": None}
                          if item and "indicator" not in element else None)

    def _on_nav_motion(self, event):
        drag = self._nav_drag
        if drag is None:
            return None
        if not drag["active"]:
            if abs(event.y - drag["y"]) < DRAG_START:
                return "break"
            drag["active"] = True
            self.nav_tree.configure(cursor="hand2")
        tree = self.nav_tree
        if event.y < DRAG_SCROLL_EDGE:
            tree.yview_scroll(-1, "units")
        elif event.y > tree.winfo_height() - DRAG_SCROLL_EDGE:
            tree.yview_scroll(1, "units")
        drag["target"] = target = self._nav_drop_target(self._nav_index(drag["item"]), event.y)
        if target is None:
            self._nav_drop_line.place_forget()
        else:
            self._nav_drop_line.place(in_=tree, x=0, y=max(0, target[1] - 1), relwidth=1)
            self._nav_drop_line.lift()
        return "break"

    def _on_nav_release(self, event):
        drag, self._nav_drag = self._nav_drag, None
        self._nav_drop_line.place_forget()
        self.nav_tree.configure(cursor="")
        if drag is None:
            return None
        if drag["active"]:
            k = self._nav_index(drag["item"])
            if k is not None and drag["target"] is not None:
                self._nav_apply(outline.move(self.raw_text().split("\n"), self._nav_heads, k, drag["target"][0]))
            return "break"
        # クリック：選んでいた見出しでも、その見出しの行へ動かす（Word と同じ）
        if self.nav_tree.identify_row(event.y) == drag["item"]:
            self._nav_go(drag["item"])
        return None

    def _nav_drop_target(self, k, y):
        """ドラッグした見出し（k 番目）を、高さ y で放したときの (target〔outline.move に渡す行〕, 線を引く高さ)。
        見出しの上の半分なら、その見出しの前。下の半分なら、その見出しの後（開いた見出しなら、最初の子の前。畳んだ見出し・
        子のない見出しなら、その範囲の後）。一覧の下の空いた所なら、最後の見出しの後。動かせない所（自分の範囲の中）は None。"""
        tree = self.nav_tree
        if k is None or not self._nav_heads:
            return None
        item = tree.identify_row(y)
        if item:
            x, top, w, h = tree.bbox(item)
            head = self._nav_heads[self._nav_index(item)]
            children = tree.get_children(item)
            if y < top + h / 2:
                target, line_y = head.line, top
            else:
                child = children[0] if children and tree.item(item, "open") else None
                target = self._nav_heads[self._nav_index(child)].line if child else head.end
                line_y = top + h
        else:
            visible = [i for i in self._nav_items() if tree.bbox(i)]
            if not visible or y < tree.bbox(visible[0])[1]:
                return None
            last = self._nav_heads[-1]
            while last.parent >= 0:             # 最後の見出しの、いちばん外側の見出しの範囲の後
                last = self._nav_heads[last.parent]
            x, top, w, h = tree.bbox(visible[-1])
            target, line_y = last.end, top + h
        mine = self._nav_heads[k]
        if mine.line <= target <= mine.end:
            return None
        return target, line_y

    # ------------------------------------------------------------------
    # メニュー・キーの操作
    # ------------------------------------------------------------------

    def _on_nav_menu(self, event):
        """右クリックした見出しを選び（エディターのカーソルも動かす）、メニューを出す。上げられない・下げられないときは、
        その項目を押せなくする。"""
        tree = self.nav_tree
        item = tree.identify_row(event.y)
        if not item:
            return "break"
        tree.focus_set()
        tree.selection_set(item)
        tree.focus(item)
        self._nav_go(item)
        k = self._nav_index(item)
        lines = self.raw_text().split("\n")
        for label, step in (("レベルを上げる", -1), ("レベルを下げる", 1)):
            ok = outline.shift_level(lines, self._nav_heads, k, step) is not None
            self.nav_menu.entryconfigure(label, state="normal" if ok else "disabled")
        ok = outline.insert_heading(lines, self._nav_heads, k, outline.CHILD) is not None     # レベル 9 の下は作れない
        self.nav_menu.entryconfigure("小見出しを挿入", state="normal" if ok else "disabled")
        try:
            self.nav_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.nav_menu.grab_release()
        return "break"

    def on_nav_level(self, step):
        """選んだ見出しと、その範囲の見出しのレベルを上げる（step=-1）・下げる（step=1）。エディターの Alt+Shift+←→ と同じく、
        レベルを変えた見出しには、同じレベルの見出しにならって前の空行と太字を付ける（editor_ops._follow_same_level）。"""
        k = self._nav_selected()
        if k is None:
            return "break"
        heads = self._nav_heads
        found = outline.shift_level(self.raw_text().split("\n"), heads, k, step)
        if found is None:
            self.status.configure(text="これより上のレベルにはできません。" if step < 0
                                  else "これより下のレベルにはできません（見出しのレベルは 9 までです）。")
            return "break"
        new, changed = found
        before = set(self._heading_lines())
        with undoable(self.text):
            self._set_lines(new)
            # 前の空行を入れ外ししても、カーソル（見出しの行の先頭）は同じ見出しに付いて動く
            self.text.mark_set("insert", f"{heads[k].line + 1}.0")
            self._follow_same_level([n + 1 for n in changed], before)
        self._after_nav_edit()
        return "break"

    def on_nav_move(self, step):
        """選んだ見出しを、その範囲ごと、同じ親の前（step=-1）・後（step=1）の見出しと入れ替える。"""
        k = self._nav_selected()
        if k is None:
            return "break"
        target = outline.move_target(self._nav_heads, k, step)
        if target is not None:
            self._nav_apply(outline.move(self.raw_text().split("\n"), self._nav_heads, k, target))
        return "break"

    def on_nav_insert(self, where):
        """選んだ見出しの前・後（属する見出し・本文の後）・小見出しとして、字のない見出しを入れ、エディターのカーソルを
        そこに置く（続けて字を打てるよう、キーボードの焦点もエディターに移す）。前の空行は、まわりの見出しにならう
        （outline.insert_heading。入れた後に、［見出し］のボタンと同じく、同じレベルの見出しにならって前の空行を足す。
        字のない見出しには太字を付けない）。Ctrl+Z 1回で戻せる。"""
        k = self._nav_selected()
        if k is None:
            return "break"
        found = outline.insert_heading(self.raw_text().split("\n"), self._nav_heads, k, where)
        if found is None:
            return "break"
        new, line = found
        before = set(self._heading_lines())
        with undoable(self.text):
            self._set_lines(new)
            self.text.mark_set("insert", f"{line + 1}.0")
            self._follow_same_level([line + 1], before)
        self.text.mark_set("insert", "insert lineend")
        self._after_nav_edit()
        self.text.focus_set()
        return "break"

    def on_nav_select_section(self):
        """選んだ見出しと、属する見出し・本文を、エディターで選ぶ（後ろの空行は含めない）。続けてコピーや書式のボタンを
        使えるよう、キーボードの焦点をエディターに移す。"""
        k = self._nav_selected()
        if k is None:
            return "break"
        h = self._nav_heads[k]
        end = outline.section_end(self.raw_text().split("\n"), h)
        first, last = f"{h.line + 1}.0", f"{end}.end"
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", first, last)
        self.text.mark_set("insert", last)
        self._scroll_to_third(first)
        self._schedule_editor_mark()
        self._show_caret()
        self.text.focus_set()
        return "break"

    def on_nav_delete(self):
        """選んだ見出しを、その範囲（属する見出し・本文）ごと消す。Ctrl+Z で戻せる。"""
        k = self._nav_selected()
        if k is None:
            return "break"
        self._nav_apply(outline.delete(self.raw_text().split("\n"), self._nav_heads, k))
        self.status.configure(text="見出しを、属する見出し・本文と一緒に削除しました。Ctrl+Z で戻せます。")
        return "break"

    def _nav_apply(self, result):
        """outline.move・delete の結果 (行のリスト, カーソルを置く行) をエディターに入れる（Ctrl+Z 1回で戻せる）。"""
        if result is None:
            return
        new, line = result
        with undoable(self.text):
            self._set_lines(new)
        self.text.mark_set("insert", f"{line + 1}.0")
        self._after_nav_edit()

    def _set_lines(self, new):
        """エディターの文章を、行のリスト new にする。変わった所だけを書き換える（ほかの字の色付けなどを保つ）。"""
        old, text = self.raw_text(), "\n".join(new)
        if old == text:
            return
        head = 0
        limit = min(len(old), len(text))
        while head < limit and old[head] == text[head]:
            head += 1
        tail = 0
        while tail < limit - head and old[-1 - tail] == text[-1 - tail]:
            tail += 1
        self.text.delete(f"1.0+{head}c", f"1.0+{len(old) - tail}c")
        self.text.insert(f"1.0+{head}c", text[head:len(text) - tail])

    def _after_nav_edit(self):
        """一覧で書き換えた後：カーソルの行を見せ、題（＊）・一覧・プレビューを直し、キーボードの焦点を一覧に残す。"""
        self.text.tag_remove("sel", "1.0", "end")
        self._scroll_to_third("insert")
        self._update_title()
        self.refresh()
        self._schedule_editor_mark()
        self.nav_tree.focus_set()

    def _nav_undo(self, command):
        """一覧を選んだまま押した Ctrl+Z・Ctrl+Y で、エディターの書き換えを戻す・やり直す。"""
        command()
        self._update_title()
        self.refresh()
        return "break"
