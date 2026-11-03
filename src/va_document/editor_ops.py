"""エディター（入力欄）の操作：配置・改ページなどの記号、見出しのレベル、標準、記号の色付け、貼り付け、検索
（カーソルの上の ▼ と行への送りは editor_mark.py、表のセルの配置は table_ops.py、画像の挿入は image_ops.py）。

メインの画面（app.MainWindow）の部品（mixin）。self.text（tk.Text）・self.session などは MainWindow が持つ。
"""
import difflib
import math
import re
import tkinter as tk

from . import html_paste, vamd
from .document import (ALIGN_MARKS, BLANK, BULLET, BULLET_MARK, CELL_ALIGN_RE, CENTER_MARK, DISTRIBUTE_CLOSE_RE, DISTRIBUTE_OPEN,
                       HEADING, HEADING_BUTTON_MARK, HEADING_MARK_RE,
                       LEFT_INDENT_MARK, LIST_MARK_RE, NUMBER, NUMBER_MARK, PAGE_BREAK, RIGHT_MARK, SECTION_BREAK,
                       TABLE, TOC, area_of,
                       cell_separators, image_mark, has_inline_marks, inline_mark_spans, is_line_mark, is_table_line, lead_mark_len,
                       leading_wrap,
                       move_wraps_after_marks, parse, remove_bold, split_inline, split_lead_marks)
from .editor_mark import EditorMarkMixin
from .find_dialog import FindDialog
from .image_ops import ImageMixin
from .layout import is_half
from .pseudonym import TOKEN_RE
from .table_ops import TableCellMixin
from .undo import undoable


class EditorMixin(EditorMarkMixin, TableCellMixin, ImageMixin):
    """エディターの操作（MainWindow に混ぜて使う）。カーソルの上の ▼ は editor_mark.py、表のセルの操作は table_ops.py、
    画像の操作は image_ops.py。"""

    def _highlight(self):
        self.text.tag_remove("registered", "1.0", "end")
        self.text.tag_remove("mark", "1.0", "end")
        self.text.tag_remove("bold", "1.0", "end")
        self.text.tag_remove("highlight", "1.0", "end")
        self.text.tag_remove("dots", "1.0", "end")
        raw = self.raw_text()
        wrap_marks, bold_text, highlight_text, dot_text = self._inline_spans(raw)
        for a, b in _mark_spans(raw) + self._markdown_spans(raw) + wrap_marks:
            self.text.tag_add("mark", f"1.0+{a}c", f"1.0+{b}c")
        for a, b in bold_text:
            self.text.tag_add("bold", f"1.0+{a}c", f"1.0+{b}c")
        for a, b in highlight_text:
            self.text.tag_add("highlight", f"1.0+{a}c", f"1.0+{b}c")
        for a, b in dot_text:
            self.text.tag_add("dots", f"1.0+{a}c", f"1.0+{b}c")
        for m in TOKEN_RE.finditer(raw):           # 仮名化した語の記号（エディターは常に仮名）
            self.text.tag_add("registered", f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    def _tokenize_editor(self):
        """エディターの中の、仮名化した語（打った・貼った実名）を記号に置き換える（エディターは常に仮名。
        2026-10-24 班長決定）。置き換えを Ctrl+Z で戻すときは、その前の操作も一緒に戻す（ai_ops.on_undo）。"""
        if self._loading:
            return
        spans = self.session.dictionary.spans(self.raw_text())
        if not spans:
            return
        insert = self.text.index("insert")
        with undoable(self.text):
            for a, b, entry in reversed(spans):
                self.text.delete(f"1.0+{a}c", f"1.0+{b}c")
                self.text.insert(f"1.0+{a}c", entry.token)
        self.text.mark_set("insert", insert)
        self.text.edit_modified(False)
        self._update_title()

    def _replace_in_editor(self, old, new):
        """エディターの old をすべて new に置き換える（仮名化の解除で、記号を元の語に戻すとき）。Ctrl+Z 1回で戻る。"""
        raw = self.raw_text()
        starts = [m.start() for m in re.finditer(re.escape(old), raw)]
        if not starts:
            return
        with undoable(self.text):
            for a in reversed(starts):
                self.text.delete(f"1.0+{a}c", f"1.0+{a + len(old)}c")
                self.text.insert(f"1.0+{a}c", new)
        self.text.edit_modified(False)

    def _markdown_spans(self, raw):
        """マークダウンの記号（見出しの #、箇条書きの「- 」、段落番号の「1. 」、表の | と区切りの行）の位置。

        読み取り（document.parse）で、見出しなどとして読まれる行だけに付ける（右揃えの段落の後など、変換しない
        所の # には付けない）。
        """
        lines = raw.split("\n")
        pos = [0]
        for line in lines:
            pos.append(pos[-1] + len(line) + 1)
        out = []
        for p in parse(lines, self.session.doc_type):
            if p.src_line < 0:
                continue
            n = p.src_line
            if p.kind in (HEADING, BULLET, NUMBER) and p.src_col > 0:
                # 記号の終わりは本文の1字目の前（「**# 見出し**」では、前の ** と # の両方）
                out.append((pos[n], pos[n] + (p.source_col(0) if p.text else p.src_col)))
            elif p.kind == TABLE:
                for k in range(n, p.src_end + 1):
                    if k == n + 1:
                        out.append((pos[k], pos[k] + len(lines[k])))     # 区切りの行
                        continue
                    out += [(pos[k] + c, pos[k] + c + 1) for c in cell_separators(lines[k])]
        return out

    def _inline_spans(self, raw):
        """字を囲む記号（** == * [字]{N}）の位置と、太字・蛍光ペン・傍点の字の範囲。"""
        out, pos = ([], [], [], []), 0
        for line in raw.split("\n"):
            if has_inline_marks(line):
                for found, spans in zip(out, inline_mark_spans(line)):
                    found += [(pos + x, pos + y) for x, y in spans]
            pos += len(line) + 1
        return out

    def on_bold(self):
        """選んだ文字列を太字にする（**文字** で囲む。Word の Ctrl+B。2026-10-24 班長指示）。
        既に囲まれていれば、記号を外す。行をまたぐ選択と、空白だけの選択には付けない。

        見出しの行で押したとき（選んでいない、見出しの行全体を選んだ、または見出しの字をすべて選んだとき）は、
        同じ段と上の段の見出しの行をすべて太字にする。その見出しが既に太字なら、同じ段と下の段の見出しの太字を
        すべて外す（同じ段の見出しの太字をそろえるため。組むときは書いたとおりにする。2026-10-24 班長決定。
        選び方と段の連動は、見出しの前の空行と同じ。2026-10-28 班長指示）。
        """
        target = self._heading_for_bold()
        if target:
            self._bold_headings(*target)
            return
        self._toggle_wrap("**")

    def on_highlight(self):
        """選んだ文字列に蛍光ペンを付ける（==文字== で囲む。Word の Ctrl+Alt+H。2026-10-24 班長指示）。
        既に囲まれていれば、記号を外す。蛍光ペンは確認表示だけで黄色に塗り、保存する PDF と印刷には出さない。"""
        self._toggle_wrap("==")

    def on_dots(self):
        """選んだ文字列に傍点を付ける（*文字* で囲む。2026-10-24 班長指示）。既に付いていれば外す。"""
        self._toggle_wrap("*")

    def on_distribute(self):
        """選んだ字を均等割付にする（[文字]{N} の形で挟む。N は選んだ字の数〔半角は半字〕を切り上げた字数で、
        目次と同じくエディターで手で直す。2026-10-24 班長指示）。既に挟まれていれば外す。空白だけの選択には
        付けない。行をまたいで選んだときと、行の先頭から選んだときは、行ごとに挟む（_wrap_selection）。
        Ctrl+Z 1回で戻せる。"""
        sel = selected = self._sel_range()
        if not sel:
            # 表のセルにカーソルがあれば、そのセルの字全体を挟む・外す（配置の記号の後から。2026-10-24 班長指示）
            cells = self._table_cells()
            if not cells:
                return
            n, s, e = cells[0]
            _, start, end, _ = self._cell_content(n, s, e)
            if start >= end:
                return
            sel = f"{n}.{start}", f"{n}.{end}"

        def bounds(line, s, e):
            """選んだ字を挟む「[」の位置と「]{N}」の範囲 (「[」, 「]」, 終わり)。記号は選んだ字の外側にも内側にもあってよい
            （行をまたいで選ぶと、行の先頭の側は記号が内側に入る）。なければ None。"""
            o = s - 1 if line[:s].endswith(DISTRIBUTE_OPEN) else s if line.startswith(DISTRIBUTE_OPEN, s) else None
            m = DISTRIBUTE_CLOSE_RE.match(line, e) or _CLOSE_AT_END_RE.search(line, 0, e)
            if o is None or not m or m.start() <= o or any(c in line[o + 1:m.start()] for c in "[]"):
                return None
            return o, m.start(), m.end()

        def apply(line, s, e, release):
            found = bounds(line, s, e)
            if found:
                if not release:
                    return line, s, e
                o, c, end = found
                return line[:o] + line[o + 1:c] + line[end:], o, c - 1
            # 字数は、記号（太字など）を除いた字で数える
            closing = f"]{{{math.ceil(sum(0.5 if is_half(c) else 1 for c in split_inline(line[s:e])[0]))}}}"
            k = len(DISTRIBUTE_OPEN)
            return line[:s] + DISTRIBUTE_OPEN + line[s:e] + closing + line[e:], s + k, e + k
        self._wrap_selection(sel, lambda line, s, e: bounds(line, s, e) is not None, apply, select=bool(selected))

    def _toggle_wrap(self, wrap):
        """選んだ文字列を wrap（** == *）で囲む。既に囲まれていれば外す。空白だけの選択には付けない。行をまたいで
        選んだときと、行の先頭から選んだときは、行ごとに囲む（_wrap_selection）。Ctrl+Z 1回で戻せる。太字と傍点は
        * の数で見分ける（「***語***」は太字と傍点。* が2つ以上なら太字、奇数なら傍点）。"""
        sel = self._sel_range()
        if not sel:
            return
        n = len(wrap)

        def run(s, from_end=False):
            """s の端から続く、記号の字（* か =）の数。"""
            s = s[::-1] if from_end else s
            return len(s) - len(s.lstrip(wrap[0]))

        def wrapped(left, right):
            return left % 2 == 1 and right % 2 == 1 if wrap == "*" else left >= n and right >= n

        def runs(line, s, e):
            """選んだ字の左右の境目に続く記号の字の数 (左の外, 左の内, 右の内, 右の外)。記号は選んだ字の外側にも内側にも
            あってよい（行をまたいで選ぶと、行の先頭の側は記号が内側に入る）。選んだ字が記号だけなら None。"""
            inner = run(line[s:e])
            if inner == e - s:
                return None
            return run(line[:s], True), inner, run(line[s:e], True), run(line[e:])

        def is_on(line, s, e):
            r = runs(line, s, e)
            return r is not None and wrapped(r[0] + r[1], r[2] + r[3])

        def apply(line, s, e, release):
            if not release:
                if is_on(line, s, e):
                    return line, s, e
                return line[:s] + wrap + line[s:e] + wrap + line[e:], s + n, e + n
            # 境目に続く記号の字はみな同じ字なので、どこから n 字除いても同じになる（右、左の順に、外側の端から除く）
            lo, li, ri, _ = runs(line, s, e)
            line = line[:e - ri] + line[e - ri + n:]
            line = line[:s - lo] + line[s - lo + n:]
            return line, s + li - n, e - ri - n
        self._wrap_selection(sel, is_on, apply)

    def _wrap_selection(self, sel, is_on, apply, select=True):
        """字を囲む記号（太字・蛍光ペン・傍点・均等割付）の付け外しの共通の流れ。sel（先頭, 末尾）の字を、行ごとに
        is_on(行, 始め, 終わり) で確かめ、すべて既に囲まれていれば外し、そうでなければ囲む（apply(行, 始め, 終わり, 外すか)
        が、書き換えた行と、囲んだ字の始め・終わりを返す）。Ctrl+Z 1回で戻せる。select が真なら、囲んだ字を選んだままに
        する（続けて押せる。選ばずに表のセルで押したときは、選ばない）。

        選択の前後の空白は囲まない（「** 文字**」は記号にならない）。行の先頭から選んだ行は、行頭の記号（ヘッダー・配置・
        ->N・字下げの空白・見出し・箇条書き・段落番号）の後ろから囲む（見出しの「# **見出し**」と同じ）。行末の改行まで
        選んだときは、その行まで。行をまたいで選んだとき（行の先頭から選んだときも）は、空の行と、表・改ページなどの
        記号の行を飛ばす（2026-10-28 班長指示）。"""
        (la, ca), (lb, cb) = [tuple(int(v) for v in x.split(".")) for x in sel]
        if lb > la and cb == 0:
            lb -= 1
            cb = len(self.text.get(f"{lb}.0", f"{lb}.end"))
        found = []
        for k in range(la, lb + 1):
            line = self.text.get(f"{k}.0", f"{k}.end")
            s, e = (ca if k == la else 0), (cb if k == lb else len(line))
            if s == 0 or la != lb:
                if not line.strip(" 　") or _structural_line(line):
                    continue
            if s == 0:
                if e == len(line):
                    line = move_wraps_after_marks(line)     # 「**:-: 本文**」は「:-: **本文**」として扱う（字の数は同じ）
                s = _lead_len(line)
            while s < e and line[s] in " 　":
                s += 1
            while e > s and line[e - 1] in " 　":
                e -= 1
            if s < e:
                found.append((k, line, s, e))
        if not found:
            return
        release = all(is_on(line, s, e) for _, line, s, e in found)
        spans = []
        with undoable(self.text):
            for k, line, s, e in found:
                new, s, e = apply(line, s, e, release)
                self._replace_line(k, new)
                spans.append((k, s, e))
        self.text.tag_remove("sel", "1.0", "end")
        if select:
            a, b = f"{spans[0][0]}.{spans[0][1]}", f"{spans[-1][0]}.{spans[-1][2]}"
            self.text.tag_add("sel", a, b)
            self.text.mark_set("insert", b)

    def _replace_line(self, n, new):
        """n 行目を new に書き換える。変わった字だけを書き換え、カーソル・選択を同じ字のところに残す（行の選択が残り、
        続けて押せるように）。"""
        line = self.text.get(f"{n}.0", f"{n}.end")
        for tag, i1, i2, j1, j2 in reversed(difflib.SequenceMatcher(None, line, new, autojunk=False).get_opcodes()):
            if tag != "equal":
                self.text.delete(f"{n}.{i1}", f"{n}.{i2}")
                self.text.insert(f"{n}.{i1}", new[j1:j2])

    def _heading_lines(self):
        """見出しとして読まれる行 {エディターの行の番号（1 から）: 見出しの階層}。"""
        return {p.src_line + 1: p.level for p in parse(self.raw_text().split("\n"), self.session.doc_type)
                if p.kind == HEADING}

    def _heading_for_bold(self):
        """［太字］で同じ段の見出しをそろえるときの (行の番号, 見出しの階層)。そうでなければ None。"""
        n = self._selected_heading_line()          # 見出しの行全体か、見出しの字すべて（見出しの前の空行と同じ）
        if n is not None and _split_heading(self.text.get(f"{n}.0", f"{n}.end")) is not None:
            return n, self._heading_lines()[n]
        a, b = self._sel_range(insert=True)
        n = int(a.split(".")[0])
        if int(b.split(".")[0]) != n:
            return None
        level = self._heading_lines().get(n)
        parts = _split_heading(self.text.get(f"{n}.0", f"{n}.end"))
        if not level or parts is None:
            return None
        if a != b:
            # 見出しの一部だけを選んだときは、その字だけを太字にする
            if split_inline(self.text.get(a, b))[0].strip(" 　") != split_inline(parts[1])[0].strip(" 　"):
                return None
        return n, level

    def _bold_headings(self, n, level):
        """同じ段（level）と上の段（# の少ない段）の見出しの行を、すべて太字にする（n 行目の見出しが太字なら、
        同じ段と下の段の見出しの太字を、すべて外す。見出しの前の空行と同じ。2026-10-28 班長指示）。Ctrl+Z 1回で戻せる。"""
        release = _whole_bold(_split_heading(self.text.get(f"{n}.0", f"{n}.end"))[1])
        sel = self._sel_range()
        with undoable(self.text):
            for k, lv in self._heading_lines().items():
                line = self.text.get(f"{k}.0", f"{k}.end")
                parts = _split_heading(line) if ((lv >= level) if release else (lv <= level)) else None
                if parts is None:
                    continue
                new = _bold_heading_line(*parts, release)
                if new is None:
                    continue
                self._replace_line(k, new)      # カーソルは同じ字のところに残す（見出しの前の空行と同じ）
        if sel:
            # 選んだ範囲（行全体か、見出しの字すべて）を選び直す（ほかのボタンと同じく、続けて押せるように）
            self.text.tag_remove("sel", "1.0", "end")
            if sel[0] == f"{n}.0":
                self.text.tag_add("sel", f"{n}.0", f"{n + 1}.0" if sel[1] == f"{n + 1}.0" else f"{n}.end")
            else:
                line = self.text.get(f"{n}.0", f"{n}.end")
                prefix, body = _split_heading(line)
                start = len(prefix) + len(body) - len(body.lstrip(" 　"))
                self.text.tag_add("sel", f"{n}.{start}", f"{n}.{len(line.rstrip(' 　'))}")
        self.text.see("insert")

    # ---------- 見出しの前の空行（2026-10-28 班長決定） ----------
    # VAスタイルの「段落前に1行空ける」に当たる。［太字］で同じ段の見出しをそろえるのと同じく、見出しの行全体（または
    # 見出しの字すべて）を選んで Enter を押すと、その段と上の段の見出しの前に空行を1行ずつ入れ、前が空行の見出しで
    # 同じ操作をすると、その段と下の段の見出しの前の空行を1行ずつ外す（VAスタイルが上の段から順に書式を変えるのと
    # 同じく、空ける段は上から続く。ボタンは置かない。選ばずに押した Enter・Backspace は、ふつうの改行・削除のまま。
    # 1か所だけ空ける・詰めるときに使う）。マークダウンの空行として書き、Ctrl+Z 1回で戻せる。
    # はじめは見出しの行の先頭の Enter・Backspace で行ったが、ふつうの改行と見分けにくいので改めた（2026-10-28 班長指示）

    def on_editor_return(self, event=None):
        """エディターの Enter。見出しの行全体（または見出しの字すべて）を選んで押したら、見出しの前の空行を入れる
        （その段と上の段）・外す（その段と下の段）。"break" を返す。表の中は、行を足す（table_ops）。そうでなければ None
        （エディターのもとの働きのまま）。"""
        line = self._selected_heading_line()
        if line is None:
            return self.on_table_return()
        self._heading_space(line)
        return "break"

    def _selected_heading_line(self):
        """見出しの行全体（行末の改行を含んでも含まなくてもよい）か、見出しの字すべて（# の後。［太字］と同じ）を
        選んでいれば、その行の番号。そうでなければ None。"""
        sel = self._sel_range()
        if not sel:
            return None
        a, b = sel
        n = int(a.split(".")[0])
        if n not in self._heading_lines():
            return None
        if a == f"{n}.0" and self.text.compare(b, ">=", f"{n}.end") and self.text.compare(b, "<=", f"{n + 1}.0"):
            return n                    # 行全体
        if int(b.split(".")[0]) != n:
            return None
        parts = _split_heading(self.text.get(f"{n}.0", f"{n}.end"))
        if parts is None or not split_inline(parts[1])[0].strip(" 　"):
            return None
        if split_inline(self.text.get(a, b))[0].strip(" 　") == split_inline(parts[1])[0].strip(" 　"):
            return n                    # 見出しの字すべて
        return None

    def _heading_space(self, line):
        """line 行目の見出しの前の空行をそろえる。その見出しのすぐ上の行が空行なら、その段と下の段（# の多い段）の
        見出しの前の空行を外し、そうでなければ、その段と上の段の見出しの前に入れる（2026-10-28 班長指示）。入れるときは、
        二重に空けないよう、ほかの見出しのうち、文書の先頭・改ページとセクション区切りの直後・直前が空行（中身のない
        配置の行も）・直前が見出しのものには入れない（選んだ見出しには、選んだとおり入れる）。ページの先頭に来た空行は、
        組むときに詰める（layout）。"""
        paras = [p for p in parse(self.raw_text().split("\n"), self.session.doc_type) if not p.area]
        heads = {p.src_line + 1: k for k, p in enumerate(paras) if p.kind == HEADING}

        def before(k):
            return paras[k - 1] if k else None
        mine = before(heads[line])
        release = mine is not None and mine.kind == BLANK and mine.src_line + 2 == line
        level = paras[heads[line]].level
        targets = []        # 空行を入れる見出しの行・外す空行の行（エディターの行の番号）
        for n, k in heads.items():
            p, b = paras[k], before(k)
            if (p.level < level) if release else (p.level > level):
                continue
            if n == line:
                targets.append(n - 1 if release else n)
            elif b is None:
                continue
            elif release:
                if b.kind == BLANK:
                    targets.append(b.src_line + 1)
            elif _needs_space(b):
                targets.append(n)
        with undoable(self.text):
            for n in sorted(targets, reverse=True):
                if release:
                    self.text.delete(f"{n}.0", f"{n + 1}.0")
                else:
                    self.text.insert(f"{n}.0", "\n")
        self.text.tag_remove("sel", "1.0", "end")
        self.text.see("insert")

    def _follow_same_level(self, lines, headings=()):
        """［見出し］・Alt+Shift+←／→ で見出しにした（レベルを変えた）行 lines（エディターの行の番号）に、直前の同じ段の
        見出しの「前の空行」と「見出し全体の太字」をならって付ける（2026-10-29 班長指示）。もとから見出しだった行
        （headings。レベルを変えた行）は、直前の同じ段の見出しになければ外す（前のレベルでならって付いたものが残らない
        ように。2026-10-29 班長指示）。本文から見出しにした行は、付けるだけで外さない（利用者が付けた空行・太字を
        消さないため）。前に同じ段の見出しがなければ、後の同じ段の見出しに合わせる（その段の最初の見出しで付け外しできる
        ように。2026-10-29 班長指示）。どちらにもなければ、何もしない。同じ段の見出しは、lines のほかの行を除いて探す（一緒に
        見出しにした行にならわないため）。前の空行は、文書の先頭・改ページとセクション区切りの直後・直前が見出しの見出しには、
        空けるかどうかが表れないので、その次に近い同じ段の見出しを見る。入れるときも、見出しの前の空行と同じく、二重に空けない
        よう、それらの見出しには入れない。太字は、字のない見出し（まだ打っていない行）には付けない。"""
        paras = [p for p in parse(self.raw_text().split("\n"), self.session.doc_type) if not p.area]
        heads = {p.src_line + 1: k for k, p in enumerate(paras) if p.kind == HEADING}
        jobs = []                   # (行, 空行, 太字)。それぞれ True は付ける、False は外す、None は変えない
        for n in sorted(set(lines) & set(heads)):
            k = heads[n]
            space = bold = None
            others = [m for m in heads if m not in lines]
            # 前の同じ段の見出しを近い順に見て、決まらなければ後の見出しを近い順に見る（その段の最初の見出しのため）
            for m in sorted((m for m in others if m < n), reverse=True) + sorted(m for m in others if m > n):
                p = paras[heads[m]]
                if p.level != paras[k].level:
                    continue
                b = paras[heads[m] - 1] if heads[m] else None
                if space is None and b is not None:
                    space = True if b.kind == BLANK else False if _needs_space(b) else None
                parts = _split_heading(self.text.get(f"{m}.0", f"{m}.end"))
                if bold is None and parts and split_inline(parts[1])[0].strip(" 　"):
                    bold = _whole_bold(parts[1])
                if space is not None and bold is not None:
                    break
            b = paras[k - 1] if k else None
            if space:
                space = True if _needs_space(b) else None
            elif space is False:
                # 外すのは、すぐ上の行の空行1行だけ
                space = False if n in headings and b is not None and b.kind == BLANK and b.src_line + 2 == n else None
            if bold is False and n not in headings:
                bold = None
            jobs.append((n, space, bold))
        if all(space is None and bold is None for _, space, bold in jobs):
            return
        with undoable(self.text):
            for n, space, bold in reversed(jobs):      # 下の行から（空行を入れ外ししても、上の行の番号は変わらない）
                parts = _split_heading(self.text.get(f"{n}.0", f"{n}.end"))
                if bold is not None and parts and _whole_bold(parts[1]) != bold:
                    new = _bold_heading_line(*parts, not bold)
                    if new is not None:
                        self._replace_line(n, new)
                if space:
                    self.text.insert(f"{n}.0", "\n")
                elif space is False:
                    self.text.delete(f"{n - 1}.0", f"{n}.0")

    def _sel_range(self, insert=False):
        """選んだ範囲の (先頭, 末尾) の位置。選んでいなければ、insert が真ならカーソルの位置を2つ、偽なら None。"""
        try:
            return self.text.index("sel.first"), self.text.index("sel.last")
        except tk.TclError:
            if insert:
                index = self.text.index("insert")
                return index, index
            return None

    def _selection(self):
        try:
            return self.text.get("sel.first", "sel.last")
        except tk.TclError:
            return ""

    def _line_range(self):
        try:
            first = int(self.text.index("sel.first").split(".")[0])
            last_index = self.text.index("sel.last")
            last = int(last_index.split(".")[0])
            if last_index.endswith(".0") and last > first:
                last -= 1
        except tk.TclError:
            first = last = int(self.text.index("insert").split(".")[0])
        return first, last

    def on_align(self, mark):
        """選んだ行（なければカーソルの行）に配置の記号を付ける。ほかの配置の記号は付け替える
        （->N は残す）。

        対象の行がすべて既にその記号なら、記号を外して標準（左）に戻す（同じボタンをもう一度押すと解除）。
        表の行では、［中央］［右］は、カーソルのあるセル（選んでいれば、選んだ範囲にかかるセル）の先頭の配置の記号を
        付け外しする。区切りの行（2行目）のセルでは、その列の配置（:--- の : の付け方）を変える（2026-10-24 班長指示）。
        """
        cells = self._table_cells() if mark in (CENTER_MARK, RIGHT_MARK) else []
        # 区切りの行の列の配置は、カーソル（選んだ範囲）が区切りの行の中だけにあるときに変える
        columns = self._table_cells(separator=True) if mark in (CENTER_MARK, RIGHT_MARK) and not cells else []
        first, last = self._line_range()
        # 字のない行は、選んだ行がすべて字のない行のときだけ記号を付け、カーソルを行末に置く（［見出し］などと同じ。
        # 字のある行と一緒に選んだ字のない行〔1行の空き〕には付けない。2026-10-28 班長指示）
        blank = not cells and not columns and self._blank_range()
        rows = []
        for n in range(first, last + 1):
            line = self.text.get(f"{n}.0", f"{n}.end")
            if _structural_line(line) or (not blank and not line.strip(" 　\t")):
                continue
            rows.append((n, line, move_wraps_after_marks(line)))
        if not rows and not cells and not columns:
            return

        def has(norm):
            lead = split_lead_marks(norm)
            return lead.align == mark
        release = all(has(norm) for _, _, norm in rows)
        with undoable(self.text):          # 何行あっても、Ctrl+Z 1回で戻せる
            self._align_cells(cells, mark)
            self._align_columns(columns, mark)
            for n, line, norm in rows:
                # 「**:=: 準備書面**」は「:=: **準備書面**」として扱う。配置の記号は付け替え、
                # ->N・[HEADER] は残す（記号の順は、ヘッダー・配置・インデント）
                # 変わった字だけを書き換える（行の選択が残るように）
                self._replace_line(n, split_lead_marks(norm)._replace(align="" if release else mark).join())
        if blank and rows:
            self._caret_to_line_end()

    def on_indent(self):
        """選んだ行（なければカーソルの行）に ->1 を付ける。対象の行がすべて既に ->N なら外す（ほかの
        ボタンと同じく、もう一度押すと解除。字数は、目次と同じくエディターで手で直す。2026-10-24 班長指示）。
        既に ->N のある行の字数は変えない。見出し・箇条書き・段落番号の行には付けない（付けると見出しなどで
        なくなるため）。Ctrl+Z 1回で戻せる。"""
        def target(line):
            if not line.strip() or _structural_line(line):
                return None
            parts = split_lead_marks(move_wraps_after_marks(line))
            if not parts.left and (HEADING_MARK_RE.match(parts.rest) or LIST_MARK_RE.match(parts.rest)):
                return None
            return parts
        self._toggle_lines(target, lambda p: p.left,
                           lambda p, release: p._replace(left="" if release else p.left or LEFT_INDENT_MARK).join())

    def on_area(self, mark):
        """選んだ行（なければカーソルの行）を、ヘッダー・フッターの行にする（行頭に [HEADER] [FOOTER] を付ける。
        2026-10-25 班長指示）。もう片方の記号は付け替える。対象の行がすべて既にその記号なら外す（ほかのボタンと同じ）。
        配置の記号・->N は残す。表・改ページなどの記号の行・区切りの行と、見出し・箇条書き・段落番号の行には
        付けない（付けると見出しなどでなくなるため。［インデント］と同じ）。Ctrl+Z 1回で戻せる。"""
        def target(line):
            if _structural_line(line):
                return None
            parts = split_lead_marks(move_wraps_after_marks(line))
            if not (parts.area or parts.left) and (
                    HEADING_MARK_RE.match(parts.rest) or LIST_MARK_RE.match(parts.rest)):
                return None
            return parts
        self._toggle_lines(target, lambda p: area_of(p.area) == area_of(mark),
                           lambda p, release: p._replace(area="" if release else mark).join())

    def _toggle_lines(self, target, has, build):
        """行頭の記号を付け外しするボタン（［インデント］［ヘッダー］［見出し］［箇条書き］［段落番号］）の共通の流れ。
        選んだ行（なければカーソルの行）のうち、target(行) が None でない行を対象とする。対象の行がすべて
        has(target の結果) なら外し、そうでなければ付ける（行は build(target の結果, 外すか) に書き換える）。
        対象の行がなければ何もしない。Ctrl+Z 1回で戻せる。書き換えた行の番号を返す（外したときは空）。"""
        first, last = self._line_range()
        found = [target(self.text.get(f"{n}.0", f"{n}.end")) for n in range(first, last + 1)]
        found = [p for p in found if p is not None]
        if not found:
            return []
        release = all(has(p) for p in found)

        def change(line, n):
            parts = target(line)
            return None if parts is None else build(parts, release)
        changed = self._edit_lines(change)
        return [] if release else changed

    def _edit_lines(self, change):
        """選んだ行（なければカーソルの行）を change(行, 番号) で書き換える（None は変えない）。Ctrl+Z 1回で戻せる。
        書き換えた行の番号を返す。"""
        first, last = self._line_range()
        changed = []
        with undoable(self.text):
            for n in range(first, last + 1):
                line = self.text.get(f"{n}.0", f"{n}.end")
                new = change(line, n)
                if new is not None and new != line:
                    self._replace_line(n, new)      # 変わった所だけ（行の選択が残り、続けて押せるように）
                    changed.append(n)
        return changed

    def _heading_level_before(self, n):
        """n 行目より前の、いちばん近い見出しの階層（なければ 0）。"""
        for k in range(n - 1, 0, -1):
            m = HEADING_MARK_RE.match(move_wraps_after_marks(self.text.get(f"{k}.0", f"{k}.end")))
            if m:
                return len(m.group(1))
        return 0

    def _level_for_plain(self, n):
        """n 行目の本文（字のない行）を Alt+Shift+←／→ で見出しにするときのレベル。←・→ とも、直前の見出しと同じ。
        直前に見出しがなければ、［見出し］と同じ ##（2026-10-25 班長指示）。"""
        return self._heading_level_before(n) or len(HEADING_BUTTON_MARK.strip())

    def on_outline(self, step):
        """見出しのレベルを上げ下げする（Word の Alt+Shift+←／→）。step は -1（上げる）・+1（下げる）。

        見出しは # の数を1つ減らす・増やす。# から上げると本文、9 から下げると本文になる（# から上げるのは
        2026-10-25 班長指示。それまでは # より上げなかった）。本文の行は、上げても下げても、直前の見出しと同じ
        レベルの見出しになる（上げるのは Word と同じ。下げるのは 2026-10-25 班長指示。それまでは下げなかった）。
        直前に見出しがなければ、［見出し］と同じ ## にする（公用文では第１のレベルを基本的に使わないため。
        2026-10-25 班長指示）。
        字のない行も、見出しの記号だけの行にする（選んだ行がすべて字のない行のとき。2026-10-25 班長指示）。
        配置の記号の付いた行（「:-: ## 見出し」「:-: 本文」）は、配置の記号を残してレベルを変える・見出しにする（上げ下げが
        見出しと本文の間で回るように。2026-10-28 班長指示）。
        見出しにした（レベルを変えた）行には、直前の同じ段の見出しにならって、前の空行と太字を付ける（レベルを変えた見出しは、
        直前の同じ段の見出しになければ外す。2026-10-29 班長指示）。
        見出しと本文を一緒に選んだときは、見出しのレベルだけを変え、本文の行は変えない（Word のアウトラインと同じ。
        本文が見出しに変わってしまっていた。2026-11-04 班長指摘）。本文を見出しにするのは、選んだ行に見出しがないときだけ。
        """
        blank = self._blank_range()
        first, last = self._line_range()
        with_heading = any(self._outline_heading(self.text.get(f"{n}.0", f"{n}.end")) for n in range(first, last + 1))

        def change(line, n):
            if blank:
                return "#" * self._level_for_plain(n) + " "
            prefix, line = _split_align(line) or ("", line)
            if _special_line(line):
                return None
            line = move_wraps_after_marks(line)     # 「**# 見出し**」は「# **見出し**」として扱う
            m = HEADING_MARK_RE.match(line)
            if m:
                level = len(m.group(1)) + step
                if level < 1 or level > 9:
                    return prefix + line[m.end():]
                return prefix + "#" * level + " " + line[m.end():]
            if line.strip() and not with_heading:
                level = self._level_for_plain(n)
                return prefix + "#" * level + " " + _strip_list(line.lstrip(" 　"))
            return None
        headings = set(self._heading_lines())
        with undoable(self.text):          # ならって付ける・外すのも含めて、Ctrl+Z 1回で戻せる
            self._follow_same_level(self._edit_lines(change), headings)
        if blank:
            self._caret_to_line_end()

    @staticmethod
    def _outline_heading(line):
        """on_outline がレベルを変える見出しの行か（配置の記号の付いた見出し、「**# 見出し**」も含む）。"""
        _, line = _split_align(line) or ("", line)
        return not _special_line(line) and bool(HEADING_MARK_RE.match(move_wraps_after_marks(line)))

    def _blank_range(self):
        """選んだ行（なければカーソルの行）が、すべて字のない行か（空白だけの行も含む）。"""
        first, last = self._line_range()
        return all(not self.text.get(f"{n}.0", f"{n}.end").strip(" 　\t") for n in range(first, last + 1))

    def _caret_to_line_end(self):
        """字のない行に記号を付けた後、続けて字を打てるよう、カーソルを最後の行の行末に置く（選択は外す）。"""
        _, last = self._line_range()
        self.text.tag_remove("sel", "1.0", "end")
        self.text.mark_set("insert", f"{last}.end")

    def on_paragraph_kind(self, mark):
        """選んだ行（なければカーソルの行）を、見出し（## ）・箇条書き（- ）・段落番号（1. ）にする（2026-10-25 班長指示）。
        ほかの見出し・箇条書き・段落番号の記号は付け替える。対象の行がすべて既にその種類なら、記号を外して本文に
        戻す（見出しは、どのレベルでも見出しとみなす。レベルは、エディターで # の数を直す）。表・改ページなどの記号の行・
        区切りの行と、配置・->N・[HEADER] の記号のある行には付けない。ただし、配置の記号の付いた見出し（「:-: ## 見出し」）は、
        配置の記号を残して変える（2026-10-28 班長指示）。
        字のない行は、選んだ行がすべて字のない行のときだけ記号を付け、カーソルを行末に置く（まだ打っていない行を
        見出しなどにしてから書くため。2026-10-25 班長指示）。字のある行と一緒に選んだ字のない行（1行の空き）には
        付けない。見出しにした行には、直前の同じ段（##）の見出しにならって、前の空行と太字を付ける（ほかのレベルの見出しから
変えた行は、直前の同じ段の見出しになければ外す。2026-10-29 班長指示）。
        Ctrl+Z 1回で戻せる。"""
        blank = self._blank_range()

        def target(line):
            if blank:
                return "", "", ""
            split = _split_align(line)
            prefix, line = split if split and HEADING_MARK_RE.match(split[1]) else ("", line)
            if _special_line(line):
                return None
            body = move_wraps_after_marks(line).lstrip(" 　")   # 「**# 見出し**」は「# **見出し**」として扱う
            kind, end = _paragraph_kind(body)
            return kind, body[end:], prefix
        headings = set(self._heading_lines())
        with undoable(self.text):          # ならって付ける・外すのも含めて、Ctrl+Z 1回で戻せる
            changed = self._toggle_lines(target, lambda p: p[0] == mark,
                                         lambda p, release: p[2] + ("" if release else mark) + p[1])
            if mark == HEADING_BUTTON_MARK:
                self._follow_same_level(changed, headings)
        if blank:
            self._caret_to_line_end()

    def on_plain(self):
        """標準の本文（左寄せ）にする（Word の Ctrl+Shift->N）。見出し・箇条書き・段落番号・配置の記号を外す。"""
        def change(line, n):
            if _structural_line(line):
                return None
            # 「**:-: # 見出し**」は「:-: # **見出し**」として扱う。配置・->N の記号を外す（ヘッダー・フッターの
            # 記号は、置く場所の記号なので残す。Word の「標準」でも、ヘッダーの段落はヘッダーのまま）
            lead = split_lead_marks(move_wraps_after_marks(line))
            if lead.area:
                return lead.area + lead.rest
            line = lead.rest
            m = HEADING_MARK_RE.match(line)
            if m:
                line = line[m.end():]
            return _strip_list(line)
        self._edit_lines(change)

    def on_line_mark(self, mark):
        """カーソルの行の前に、改ページなどの記号だけの行を入れる。カーソルが表の中にあれば、表の前に入れる（表を
        分けないため。行頭の記号のボタンも、表の行では何もしない。2026-10-28 班長指示）。"""
        n = int(self.text.index("insert").split(".")[0])

        def table(k):
            return is_table_line(self.text.get(f"{k}.0", f"{k}.end"))
        while n > 1 and table(n) and table(n - 1):
            n -= 1
        self.text.insert(f"{n}.0", mark + "\n")

    def on_find(self, replace):
        """検索と置換の画面を開く（開いていれば前に出す）。選んでいる文字があれば、検索する文字列に入れる。"""
        selected = self._selection()
        if self._find_dialog is None or not self._find_dialog.winfo_exists():
            self._find_dialog = FindDialog(self)
        self._find_dialog.show(selected if "\n" not in selected else "", replace)

    def _replace_undoable(self, text):
        """エディターの文章を、Ctrl+Z（元に戻す）で戻せる形で置き換える（AI の回答の貼り付けで使う。
        2026-10-23 班長決定。［貼り付けを元に戻す］のボタンの代わり）。text は仮名の文章。"""
        with undoable(self.text):
            self.text.delete("1.0", "end")
            self.text.insert("1.0", text)
        self.text.edit_modified(False)
        self._update_title()
        self.refresh()

    def clipboard_text(self):
        """クリップボードの字（なければ None）。clipboard_get ではなく selection_get で読む：Tk の clipboard_get は、
        VA Document 自身がクリップボードに置いた約 4000 バイトを超える文章を読み戻すと、その区切りで日本語の字が化ける
        （Tk 8.6.15。2026-10-29 に確かめた。ほかのアプリから写した文章は化けない）。"""
        try:
            return self.selection_get(selection="CLIPBOARD")
        except tk.TclError:
            return None

    def _on_paste(self, event=None):
        """貼り付け（Ctrl+V）は、仮名化した語を記号に置き換えて貼る（エディターは常に仮名。2026-10-24）。
        クリップボードに字がなく画像だけがあれば、画像を入れる（Win+V で選んだ画像も、Windows が置き直してから Ctrl+V を
        送るので、ここを通る。字と画像の両方があれば〔Excel・Word からのコピー〕、今までどおり字を貼る。2026-10-29 班長決定）。
        字が Excel・Word の表のコピーなら、表として貼る（table_ops）。Word・ブラウザーの書式（太字・傍点・蛍光ペン・配置）は、
        記号にして残す（html_paste。2026-10-31 班長決定）。"""
        clip = self.clipboard_text()
        if not clip:
            return "break" if self.paste_pictures() else None
        if self.paste_html(clip) or self.paste_table(clip):
            return "break"
        if not self.session.dictionary.spans(clip):
            return None
        self._paste_text(clip)
        return "break"

    def paste_html(self, clip):
        """Word・ブラウザーからコピーした書式付きの字を、書式を記号にして貼る。貼ったら True。字はプレーンな字（clip）のまま変えず、
        書式を読めないときは False（呼ぶ側が、これまでどおりに貼る）。行の途中に貼るときは、1行目に配置の記号を付けない。"""
        data = html_paste.read_html()
        if not data:
            return False
        blank = not self._sel_range() and not self.text.get("insert linestart", "insert lineend").strip()
        lines = html_paste.convert(data, clip, self.session.dictionary, first_align=blank)
        if lines is None:
            return False
        with undoable(self.text):
            if self._sel_range():
                self.text.delete("sel.first", "sel.last")
            if any(is_table_line(line) for line in lines):
                first = self._insert_block(lines)
                self.text.mark_set("insert", f"{first + len(lines) - 1}.end")
            else:
                self.text.insert("insert", "\n".join(lines))
        self.text.see("insert")
        self.status.configure(text="書式を記号にして貼りました。Ctrl+Z で戻し、Ctrl+Shift+V で字のまま貼れます。")
        return True

    def on_paste_plain(self):
        """Ctrl+Shift+V：表にせず、字のまま貼る（仮名化した語は Ctrl+V と同じく記号に置き換える。2026-10-31 班長決定）。"""
        clip = self.clipboard_text()
        if clip:
            self._paste_text(clip)
        return "break"

    def _paste_text(self, clip):
        """クリップボードの字を、仮名化した語を記号に置き換えて貼る。"""
        spans = self.session.dictionary.spans(clip)
        with undoable(self.text):
            try:
                self.text.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            self.text.insert("insert", self.session.dictionary.pseudonymize(clip))
        self.text.see("insert")
        if spans:
            self.status.configure(text=f"貼り付けた文章の仮名化する語 {len(spans)} か所を、記号に置き換えました。")


# 表の行の、セルの先頭の配置の記号（| の後。太字・蛍光ペンの記号の内側にあってもよい）。group(2) が配置の記号
_CELL_MARK_RE = re.compile(r"(?<!\\)\|[ 　]*" + CELL_ALIGN_RE.pattern)


def _mark_spans(text):
    """配置・改ページなどの記号の位置 [(始め, 終わり)]（文章の初めからの字数）。記号として読まれる所だけ
    （行頭の配置の記号、その行だけの改ページなどの記号、表のセルの先頭の配置の記号）。"""
    out, pos = [], 0
    for line in text.split("\n"):
        stripped = line.strip()
        if is_line_mark(stripped):
            start = pos + line.index(stripped)
            out.append((start, start + len(stripped)))
        elif image_mark(line):
            # 画像の行（[IMAGE 1]{30}。行頭の配置の記号も含めて、行の字の全体）
            start = pos + len(line) - len(line.lstrip(" 　"))
            out.append((start, pos + len(line.rstrip())))
        elif is_table_line(line):
            for m in _CELL_MARK_RE.finditer(line):
                out.append((pos + m.start(2), pos + m.end(2)))
        else:
            body = line.lstrip(" 　")
            # 「**:=: 準備書面**」の記号は、前の ** の後にある
            off = 0
            if move_wraps_after_marks(body) != body:
                while leading_wrap(body[off:]):
                    off += len(leading_wrap(body[off:]))
            # 行頭の配置・->N の記号（後ろの字下げの空白は含めない）
            lead = len(body) - off - len(split_lead_marks(body[off:]).rest)
            if lead:
                start = pos + len(line) - len(body) + off
                out.append((start, start + lead))
        pos += len(line) + 1
    return out


def _structural_line(line):
    """行頭の記号のボタンで変えない行（表の行・改ページなどの記号の行・構文ファイルの区切りの行）。"""
    return is_table_line(line) or is_line_mark(line) or bool(vamd.SEPARATOR_RE.match(line))


def _special_line(line):
    """見出しのレベルを変えない行（表・改ページなどの記号の行・配置の記号の行・区切りの行・空の行）。"""
    lead = split_lead_marks(move_wraps_after_marks(line))
    return (not line.strip() or _structural_line(line) or bool(image_mark(line))
            or bool(lead.align or lead.left or lead.area))


# 選んだ字の末尾で終わる「]{N}」（均等割付の閉じ。on_distribute）
_CLOSE_AT_END_RE = re.compile(DISTRIBUTE_CLOSE_RE.pattern + r"\Z")


def _lead_len(line):
    """行頭の記号（ヘッダー・配置・->N・字下げの空白・見出し・箇条書き・段落番号）の字数。字を囲む記号は、この後ろに
    付ける（->N・[HEADER] の後の見出しなどの記号は、見出しなどにならないので字として囲む。move_wraps_after_marks と同じ）。"""
    lead = split_lead_marks(line)
    rest = lead.rest
    k = len(rest) - len(rest.lstrip(" 　"))
    if not (lead.left or lead.area):
        m = HEADING_MARK_RE.match(rest, k) or LIST_MARK_RE.match(rest, k)
        if m:
            k = m.end()
    return len(line) - len(rest) + k


def _split_align(line):
    """配置の記号だけが付いた行（「:-: ## 見出し」「:-: 本文」。配置の記号の付いた見出しは、組むときも見出しとして読む）を
    (配置の記号まで, その後ろ) に分ける（「**:-: ## 見出し**」の形も扱う）。->N・[HEADER] もある行と、配置の記号のない行は
    None。"""
    line = move_wraps_after_marks(line)
    lead = split_lead_marks(line)
    if not lead.align or lead.left or lead.area:
        return None
    return line[:len(line) - len(lead.rest)], lead.rest


def _split_heading(line):
    """見出しの行を (記号まで, 見出しの字) に分ける（行頭の空白・配置の記号、「**# 見出し**」の形も扱う）。
    見出しの記号がなければ None。"""
    rest = line.lstrip(" 　")
    prefix = line[:len(line) - len(rest)]
    rest = move_wraps_after_marks(rest)
    for mark in ALIGN_MARKS:
        if lead_mark_len(rest, mark):
            n = lead_mark_len(rest, mark)
            prefix, rest = prefix + rest[:n], rest[n:]
            break
    m = HEADING_MARK_RE.match(rest)
    return (prefix + rest[:m.end()], rest[m.end():]) if m else None


def _whole_bold(body):
    """見出しの字が、すべて太字か。"""
    plain, bold, _, _ = split_inline(body)
    return bool(plain.strip()) and all(k in bold for k, ch in enumerate(plain) if not ch.isspace())


def _bold_heading_line(prefix, body, release):
    """見出しの行（_split_heading で分けた記号まで・見出しの字）の字全体を太字にした行（release が真なら、太字を外した行）。
    蛍光ペンの記号は残す。字のない見出しは None。"""
    plain = remove_bold(body)
    core = plain.strip(" 　")
    if not core:
        return None
    if release:
        return prefix + plain
    lead = plain[:len(plain) - len(plain.lstrip(" 　"))]
    return prefix + lead + "**" + core + "**" + plain[len(lead) + len(core):]


def _needs_space(before):
    """前の段落が before の見出しの前に、空行を入れるか（見出しの前の空行で、二重に空けないため。文書の先頭〔before が
    None〕・空行・中身のない配置の行・見出し・改ページ・セクション区切りの後には入れない）。"""
    return before is not None and before.kind not in (BLANK, HEADING, PAGE_BREAK, SECTION_BREAK) and (
        before.kind in (TABLE, TOC) or bool(before.number or before.text))


def _paragraph_kind(body):
    """行頭の見出し・箇条書き・段落番号の記号 (［見出し］などで付ける記号, 記号の字数)。なければ ("", 0)。"""
    m = HEADING_MARK_RE.match(body)
    if m:
        return HEADING_BUTTON_MARK, m.end()
    m = LIST_MARK_RE.match(body)
    if m:
        return (BULLET_MARK if m.group(0) == BULLET_MARK else NUMBER_MARK), m.end()
    return "", 0


def _strip_list(line):
    """行頭の箇条書き（「- 」）・段落番号（「1. 」）を外す。"""
    m = LIST_MARK_RE.match(line)
    return line[m.end():] if m else line
