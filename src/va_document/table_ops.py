"""エディターの、表の操作（表の挿入。2026-10-31 班長指示）と、表のセルの操作（セルの先頭の配置の記号、区切りの行の
列の配置。2026-10-24 班長指示）。

メインの画面（app.MainWindow）の部品（mixin。editor_ops.EditorMixin が混ぜる）。self.text（tk.Text）は MainWindow が持つ。
"""
import tkinter as tk
from bisect import bisect_left

from . import theme
from .document import (CELL_ALIGN_RE, CENTER_MARK, RIGHT_MARK, SEP_COLUMN_RE, cell_separators, is_table_line,
                       parse_separator, separator_widths, split_cells, with_column_widths)
from .undo import undoable

NEW_TABLE_SIZE = (2, 3)     # ［表］で入れる表の列数と行数（見出しの行を含む。マニュアル3.5の例と同じ形。2026-10-31 班長決定）
EMPTY_CELL_COLUMN = 2       # 空の表の行の、最初のセルの字の位置（「|  |」の2つの空白の間）
EMPTY_ROW_CELL = "  |"


def table_lines(columns, rows):
    """空の表の行（見出しの行・区切りの行・中身の行）。rows は見出しの行を含む行数。"""
    cells = "|" + EMPTY_ROW_CELL * columns
    return [cells, "|" + "---|" * columns] + [cells] * (rows - 1)


def clipboard_table(clip):
    """クリップボードの字が Excel・Word の表のコピーなら、マークダウンの表の行のリストを返す（1行目を見出しの行にする。
    セルの字は変えず、| だけを \\| にする）。そうでなければ None。2行以上で、どの行もタブの数が同じ（1つ以上）ときだけ
    表とする。Excel のセルの中の改行は、そのセルが " で囲まれて行が分かれるので、片側だけに " のあるセルがあれば
    表にしない（判定が微妙なときは、字のまま貼る側に倒す）。"""
    lines = clip.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n").split("\n")
    rows = [[c.strip() for c in line.split("\t")] for line in lines]
    columns = len(rows[0])
    if len(rows) < 2 or columns < 2 or any(len(r) != columns for r in rows):
        return None
    if any(c.startswith('"') != c.endswith('"') for r in rows for c in r):
        return None
    text = ["| " + " | ".join(c.replace("|", "\\|") for c in r) + " |" for r in rows]
    return [text[0], "|" + "---|" * columns] + text[1:]


class TableCellMixin:
    """表の挿入と、表のセルの操作（MainWindow に混ぜて使う）。"""

    _button_menu = None

    def _cursor(self):
        """カーソルの (行, 字の位置)。"""
        return tuple(int(v) for v in self.text.index("insert").split("."))

    def _line(self, n):
        return self.text.get(f"{n}.0", f"{n}.end")

    def _go(self, n, col):
        """カーソルを動かす（選んだ範囲は外す）。"""
        self.text.tag_remove("sel", "1.0", "end")
        self.text.mark_set("insert", f"{n}.{col}")
        self.text.see("insert")

    def _table_range(self, n):
        """行 n を含む表の (最初の行, 最後の行)。表でなければ None（| で始まる行が続き、2行目が区切りの行のもの。
        document.parse と同じ）。"""
        if not is_table_line(self._line(n)):
            return None
        end = int(self.text.index("end-1c").split(".")[0])
        first, last = n, n
        while first > 1 and is_table_line(self._line(first - 1)):
            first -= 1
        while last < end and is_table_line(self._line(last + 1)):
            last += 1
        return (first, last) if last > first and parse_separator(self._line(first + 1)) else None

    @staticmethod
    def _cell_index(line, col):
        """字の位置 col のあるセルの番号（0 から）。表の外側なら、いちばん近いセル。"""
        seps = cell_separators(line)
        return min(max(bisect_left(seps, col) - 1, 0), max(len(seps) - 2, 0))

    def _cell_cursor(self, n, s, e):
        """セルの字の後ろの位置（字のないセルは、空白の間）。"""
        pos, _, end, _ = self._cell_content(n, s, e)
        return end if end > pos else min(s + EMPTY_CELL_COLUMN, e)

    def on_table(self):
        """［表］：表の外では、カーソルのある行の次に空の表を入れ、カーソルを最初のセルに置く（列数・行数は尋ねない。
        Ctrl+Z 1回で戻せる）。表の中では、列を足す・見出しの下の線を変えるメニューを出す（2026-10-31 班長決定）。"""
        span = self._table_range(self._cursor()[0])
        if span:
            self._post_table_menu(span)
            return
        columns, rows = NEW_TABLE_SIZE
        first = self._insert_block(table_lines(columns, rows))
        self._go(first, EMPTY_CELL_COLUMN)
        self.text.focus_set()
        self.status.configure(text="表を入れました。1行目が見出しの行です。Tab で次のセルへ動き、Enter で行を足します。"
                                   "列は、表の中で［表］を押すと足せます。")

    def _table_menu_items(self, span):
        """表の中の［表］のメニュー [(字, 働き)]。"""
        separator = self._line(span[0] + 1)
        double = parse_separator(separator)[1]
        widths = separator_widths(separator)
        items = [("右に列を足す", self.on_table_column),
                 ("見出しの下を1重線に戻す" if double else "見出しの下を2重線にする", self.on_table_double)]
        if not all(widths):
            items.append(("列の幅を固定する", self.on_table_fix_widths))
        if any(widths):
            items.append(("列の幅を自動に戻す", self.on_table_auto_widths))
        return items

    def _post_table_menu(self, span):
        self._post_button_menu(self.table_button, self._table_menu_items(span))

    def _post_button_menu(self, button, items):
        """リボンのボタンの下にメニューを出す（［表］［画像］）。items は [(字, 働き)]。"""
        if self._button_menu is None:
            self._button_menu = tk.Menu(self, tearoff=0, background=theme.FIELD_BG, foreground=theme.TEXT,
                                        activebackground=theme.HOVER_BG, activeforeground=theme.TEXT)
        menu = self._button_menu
        menu.delete(0, "end")
        for label, command in items:
            menu.add_command(label=label, command=command)
        try:
            menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        finally:
            menu.grab_release()

    def on_table_column(self):
        """カーソルのあるセルの右に、空の列を足す（区切りの行は、今の線の種類で足す）。Ctrl+Z 1回で戻せる。"""
        n, col = self._cursor()
        span = self._table_range(n)
        if not span:
            return
        first, last = span
        k = self._cell_index(self._line(n), col)
        rule = "===|" if parse_separator(self._line(first + 1))[1] else "---|"
        with undoable(self.text):
            for m in range(first, last + 1):
                line = self._line(m)
                seps = cell_separators(line)
                cell = rule if m == first + 1 else EMPTY_ROW_CELL
                if k + 1 < len(seps):
                    self.text.insert(f"{m}.{seps[k + 1] + 1}", cell)
                else:                               # 右の | のない行・セルの足りない行は、行の後ろに足す
                    self.text.insert(f"{m}.end", ("" if line.rstrip().endswith("|") else " |") + cell)
        seps = cell_separators(self._line(n))
        self._go(n, self._cell_cursor(n, seps[k + 1], seps[k + 2]))
        self.text.focus_set()

    def on_table_double(self):
        """区切りの行の - と = を入れ替える（見出しの下の線の1重・2重。: の配置は変えない）。Ctrl+Z 1回で戻せる。"""
        span = self._table_range(self._cursor()[0])
        if not span:
            return
        n = span[0] + 1
        line = self._line(n)
        new = line.replace("=", "-") if parse_separator(line)[1] else line.replace("-", "=")
        with undoable(self.text):
            self.text.delete(f"{n}.0", f"{n}.end")
            self.text.insert(f"{n}.0", new)
        self.text.focus_set()

    def on_table_fix_widths(self):
        """区切りの行のすべての列に、今の幅の字数を {字数} で書き入れる（後は数字を直すだけで済むように。入力の画面は
        作らない。2026-11-01 班長決定）。Ctrl+Z 1回で戻せる。"""
        span = self._table_range(self._cursor()[0])
        if not span:
            return
        self.session.typeset(self.real_text())
        m = self.session.layout_map
        piece = m.table_piece(span[0] - 1)
        if piece is None:
            return
        self._set_column_widths(span[0] + 1, m.ts.column_chars(piece))
        self.status.configure(text="列の幅を固定しました。表の2行目の {字数} を直すと、列の幅が変わります。")

    def on_table_auto_widths(self):
        """区切りの行の {字数} をすべて外す。Ctrl+Z 1回で戻せる。"""
        span = self._table_range(self._cursor()[0])
        if span:
            self._set_column_widths(span[0] + 1, [])

    def _set_column_widths(self, n, chars):
        insert = self.text.index("insert")
        new = with_column_widths(self._line(n), chars)
        with undoable(self.text):
            self.text.delete(f"{n}.0", f"{n}.end")
            self.text.insert(f"{n}.0", new)
        self.text.mark_set("insert", insert)
        self.text.focus_set()

    def _add_table_row(self, after, first):
        """行 after の下に空の行を足し、カーソルをその最初のセルに置く。"""
        columns = max(len(split_cells(self._line(k))) for k in (first, first + 1))
        with undoable(self.text):
            self.text.insert(f"{after}.end", "\n|" + EMPTY_ROW_CELL * columns)
        self._go(after + 1, EMPTY_CELL_COLUMN)

    def on_table_return(self):
        """表の中の Enter：カーソルの行の下に空の行を足す（見出しの行・区切りの行では、区切りの行の下に。セルの中で
        改行はできず、ふつうの改行では行が2つに切れて表が壊れるため。2026-10-31 班長決定）。"break" を返す。表の外、
        字を選んでいるとき、表の最初の行の左の | より前（表の前に行を入れる）、最後の行の右の | より後（表の後に行を
        入れる）では None（エディターのもとの働きのまま）。"""
        n, col = self._cursor()
        span = self._table_range(n)
        if not span or self._sel_range():
            return None
        first, last = span
        seps = cell_separators(self._line(n))
        if (n == first and col <= seps[0]) or (n == last and col > seps[-1]):
            return None
        self._add_table_row(max(n, first + 1), first)
        return "break"

    def on_table_tab(self, step=1):
        """表の中の Tab・Shift+Tab：次・前のセルへ動く（区切りの行は飛ばす）。最後のセルの Tab は、表の末尾に行を足す
        （Word と同じ。2026-10-31 班長決定）。"break" を返す。表の外では None（Tab はタブの字を入れるまま）。"""
        n, col = self._cursor()
        span = self._table_range(n)
        if not span:
            return None
        first, last = span
        k = self._cell_index(self._line(n), col) + step
        while True:
            seps = cell_separators(self._line(n))
            bounds = list(zip(seps, seps[1:]))
            if 0 <= k < len(bounds):
                self._go(n, self._cell_cursor(n, *bounds[k]))
                return "break"
            n += step
            if n == first + 1:
                n += step
            if n < first:
                return "break"
            if n > last:
                self._add_table_row(last, first)
                return "break"
            k = 0 if step > 0 else len(cell_separators(self._line(n))) - 2

    def paste_table(self, clip):
        """Ctrl+V（editor_ops._on_paste から呼ぶ）：クリップボードの字が Excel・Word の表のコピーなら、カーソルのある行の
        次に表として入れる（画像の貼り付けと同じ位置）。入れたら True。"""
        lines = clipboard_table(self.session.dictionary.pseudonymize(clip))
        if lines is None:
            return False
        with undoable(self.text):
            if self._sel_range():
                self.text.delete("sel.first", "sel.last")
            first = self._insert_block(lines)
        n = first + len(lines) - 1
        self._go(n, len(self._line(n)))
        self.status.configure(text=f"表として貼りました（{len(lines) - 1} 行）。1行目が見出しの行です。Ctrl+Z で戻し、"
                                   "Ctrl+Shift+V で字のまま貼れます。")
        return True

    def _insert_block(self, lines):
        """カーソルのある行の次（カーソルの行が空ならその行。表の中なら表の後）に行を入れ、lines の最初の行の番号を
        返す。表を入れるときは、前後の表とつながって1つの表にならないよう空の行を挟み、文書の最後なら、表から出られる
        よう後ろに空の行を置く。Ctrl+Z 1回で戻せる。"""
        n = int(self.text.index("insert").split(".")[0])
        last = int(self.text.index("end-1c").split(".")[0])

        def table(k):
            return 1 <= k <= last and is_table_line(self.text.get(f"{k}.0", f"{k}.end"))
        while n < last and table(n) and table(n + 1):
            n += 1
        block = list(lines)
        empty = not self.text.get(f"{n}.0", f"{n}.end").strip()
        if is_table_line(block[-1]) and (table(n + 1) or n == last):
            block.append("")
        if is_table_line(block[0]):
            if empty and table(n - 1):
                empty = False                       # カーソルの空の行を残し、その次に入れる
            elif table(n):
                block.insert(0, "")
        with undoable(self.text):
            if empty:
                self.text.delete(f"{n}.0", f"{n}.end")
                self.text.insert(f"{n}.0", "\n".join(block))
            else:
                self.text.insert(f"{n}.end", "\n" + "\n".join(block))
        return (n if empty else n + 1) + block.index(lines[0])

    def _table_cells(self, separator=False):
        """カーソルのあるセル（字を選んでいれば、選んだ範囲にかかるセル）[(行, 左の | の位置, 右の | の位置)]。
        表の区切りの行（2行目）は除く（separator が真なら、区切りの行のセルだけ）。"""
        a, b = self._sel_range(insert=True)
        (la, ca), (lb, cb) = [tuple(int(v) for v in x.split(".")) for x in (a, b)]
        out = []
        for n in range(la, lb + 1):
            line = self.text.get(f"{n}.0", f"{n}.end")
            if not is_table_line(line) or (parse_separator(line) is None) == separator:
                continue
            seps = cell_separators(line)
            bounds = list(zip(seps, seps[1:]))
            if a == b:
                # カーソルが表の外側（最初の | の前・最後の | の後）なら、いちばん近いセル
                hit = [(s, e) for s, e in bounds if s < ca <= e] or (bounds[-1:] if bounds and ca > bounds[-1][1] else bounds[:1])
            else:
                lo, hi = (ca if n == la else 0), (cb if n == lb else len(line))
                hit = [(s, e) for s, e in bounds if s + 1 < hi and e > lo]
            out += [(n, s, e) for s, e in hit]
        return out

    def _cell_content(self, n, s, e):
        """セルの中身の位置 (配置の記号を置く位置, 字の始め, 字の終わり, 配置の記号の一致)。前後の空白は除く。"""
        line = self.text.get(f"{n}.0", f"{n}.end")
        pos = s + 1
        while pos < e and line[pos] in " 　":
            pos += 1
        end = e
        while end > pos and line[end - 1] in " 　":
            end -= 1
        m = CELL_ALIGN_RE.match(line, pos, end)
        start = pos + len(m.group(0)) if m and not m.group(1) else pos
        while start < end and line[start] in " 　":
            start += 1
        return pos, start, end, m

    def _align_cells(self, cells, mark):
        """セルの先頭の配置の記号を付け替える。すべてのセルが既にその記号なら外す。"""
        if not cells:
            return
        found = [self._cell_content(n, s, e)[3] for n, s, e in cells]
        release = all(m and m.group(2).strip() == mark.strip() for m in found)
        for n, s, e in sorted(cells, reverse=True):          # 右・下のセルから（前の位置がずれないように）
            pos, _, _, m = self._cell_content(n, s, e)
            if m:
                self.text.delete(f"{n}.{m.start(2)}", f"{n}.{m.end(2)}")
            if not release:
                self.text.insert(f"{n}.{pos}", mark)

    def _align_columns(self, columns, mark):
        """区切りの行のセルの : を付け替える（中央は :---:、右は ---:）。すべての列が既にその配置なら、
        左（---）に戻す。- と = の種類と数は変えない（2重線の設定は変わらない）。"""
        if not columns:
            return
        want = {CENTER_MARK: (True, True), RIGHT_MARK: (False, True)}[mark]

        def parts(n, s, e):
            cell = self.text.get(f"{n}.{s + 1}", f"{n}.{e}")
            lead = len(cell) - len(cell.lstrip(" 　"))
            return s + 1 + lead, SEP_COLUMN_RE.search(cell).group(1)      # 後ろの {字数} は変えない
        release = all((parts(*c)[1].startswith(":"), parts(*c)[1].endswith(":")) == want for c in columns)
        for n, s, e in sorted(columns, reverse=True):
            start, core = parts(n, s, e)
            body = core.strip(":")
            left, right = (False, False) if release else want
            new = (":" if left else "") + body + (":" if right else "")
            if new != core:
                self.text.delete(f"{n}.{start}", f"{n}.{start + len(core)}")
                self.text.insert(f"{n}.{start}", new)
