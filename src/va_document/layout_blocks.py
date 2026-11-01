"""行組みのうち、本文の行の格子に合わせない塊（表・画像）の組み方（layout.Typesetter に混ぜる BlockMixin）。

表（仕様.md の5.3）：Word に合わせ込まず、Word の既定に寄せた読みやすい値で組む。表の左端は本文の左インデントにそろえる
（箇条書き・段落番号・->N のすぐ後の表は、その段落の左インデントにそろえる）。
画像（[IMAGE 1]{30}。仕様.md の5.4。2026-10-29 班長決定）：行の格子の上の端から置き、右に置いた画像には続く本文を
回り込ませる（本文の行の右インデントを広げる。_wrap_extra を layout.Typesetter が行ごとに引く）。
2026-10-29 に layout.py から分けた（動きは変えない。分ける前と後で、見本の字の位置・PDF の画素が一致することを確かめた）。
座標は layout.py と同じく、ポイント単位で x は本文の左端から。
"""
from dataclasses import dataclass, field
from math import ceil

from .document import CENTER, RIGHT, TITLE
from .doctypes import FONT_SIZE, MM

# 表の値（仕様.md の5.3。Word に合わせ込まず、Word の既定に寄せた読みやすい値）
CELL_PAD_X = 1.9 * MM           # セルの左右の余白（Word の既定 1.9mm）
CELL_PAD_Y = 1.5                # セルの上下の余白（ポイント）
# 傍点のある表の行は、上をこれだけ空ける（表の行は字の上の余白が狭く、黒丸が上の罫線に重なるため）
DOT_ROW_EXTRA = 2.5
CELL_LINE_PITCH = FONT_SIZE * 1.3  # セルの中の行送り（VA公用文が表に使う「行間詰め」の1行に近い値）
# 画像（[IMAGE 1]{30}。2026-10-29 班長決定。検討_画像の挿入.md の7）
WRAP_GAP = 1                    # 回り込ませる本文と画像の間（字。句読点のぶら下げを画像に重ねないため）
WRAP_MIN = 10                   # 回り込む行の幅がこれ（字）に満たないときは回り込ませない
MISSING_RATIO = 0.75            # 画像のデータがない番号の枠の高さ（幅に対する比）
RULE_WIDTH = 0.5                # 罫線の太さ（ポイント）
DOUBLE_RULE_GAP = 2.0           # 2重線の2本の間（ポイント。1.5pt では画面で1本に見えた）


@dataclass
class TableGlyph:
    ch: str
    x: float                # 本文の左端からの位置（ポイント）
    y: float                # 基準線の、用紙の上端からの位置（ポイント）
    row: int = -1           # 表の何行目か（0 が見出しの行）
    col: int = -1           # 何列目か
    index: int = -1         # セルの何字目か
    bold: bool = False      # 太字
    highlight: bool = False  # 蛍光ペン
    dot: bool = False       # 傍点
    pseudonym: bool = False  # 仮名化した語の字


@dataclass
class TableRow:
    top: float              # 行の上の端（用紙の上端から。ポイント）
    bottom: float           # 行の下の端
    double_below: bool = False  # この行の下を2重線にするか（見出しの行）
    index: int = -1             # 表の何行目か（0 が見出しの行）


@dataclass
class TablePiece:
    """1つのページに入る表の部分（ページをまたぐ表は、ページごとに分かれる）。"""
    page: int
    col_x: list             # 列の境目の位置（本文の左端から。左端・各列の右端）
    para_index: int = -1    # 何番目の段落の表か
    rows: list = field(default_factory=list)
    glyphs: list = field(default_factory=list)


@dataclass
class ImagePiece:
    """組んだ画像（[IMAGE 1]{30}）。画像は途中で分けない。"""
    page: int
    x: float                # 左の端（本文の左端から。ポイント）
    y: float                # 上の端（用紙の上端から）
    w: float
    h: float
    number: int             # 画像の番号
    para_index: int = -1    # 何番目の段落の画像か
    missing: bool = False   # 画像のデータがない番号（確認表示では枠を線で描く）
    wrap: bool = False      # 続く本文を左側に回り込ませたか


class BlockMixin:
    """表と画像の組み方（layout.Typesetter に混ぜて使う）。self の字送り・行送り・余白・make_items・break_lines・
    place_line・longest_unbreakable・first_level・dt・tables・images・_wrap は Typesetter が持つ。"""

    # ---------- 表（仕様.md の5.3） ----------

    def table_left(self, p):
        """表の左端（本文の左端から）。箇条書き・段落番号・->N のすぐ後の表は、その段落の左インデント（2行目以降の位置）。
        それ以外は、本文の左インデント（2026-11-01 班長指摘。箇条書きの後の表の左端が「・」の位置に出ていた）。"""
        return self.indents(p.follows)[0] if p.follows else self.body_left(p)

    def body_left(self, p):
        """直前の見出しに属する本文の左インデント（本文の2行目以降の位置。本文の左端から）。"""
        if not p.body_level or self.first_level is None:
            return 0.0
        x = p.body_level - 1
        return (self.dt.text_left[x] + self.dt.left_add * (p.body_level - self.first_level)) * self.pitch

    def column_widths(self, table, width):
        """列の幅。width は本文の右端までの幅。

        {字数} のある列は、その字数が入る幅にする（2026-11-01 班長決定）。すべての列にあれば、表の右端は列の幅の合計で
        決まる。指定のない列があれば、残りの幅をその列に配り、表の幅を width にする。width を超えるときは、比で縮める。
        """
        pad = 2 * CELL_PAD_X
        floor = self.pitch + pad
        fixed = [c and c * self.pitch + pad for c in table.widths]
        free = [k for k, w in enumerate(fixed) if w is None]
        taken = sum(w for w in fixed if w is not None)
        if not free and taken <= width:
            return fixed
        if not free or (taken and taken + floor * len(free) >= width):
            total = taken + floor * len(free)
            return [(floor if w is None else w) * width / total for w in fixed]
        rows = [table.header] + table.rows
        spans = table.distribute
        limit = width - pad         # 割り付ける幅は、表の幅より広くしない
        maxw = [max(max(sum(w for _, w in self.make_items(r[k][1], spans.get((ri, k), ()), limit))
                        for ri, r in enumerate(rows)) + pad, floor) for k in free]
        minw = [max(max(self.longest_unbreakable(r[k][1], spans.get((ri, k), ()), limit)
                        for ri, r in enumerate(rows)) + pad, floor) for k in free]
        for k, w in zip(free, self._auto_widths(maxw, minw, width - taken)):
            fixed[k] = w
        return fixed

    @staticmethod
    def _auto_widths(maxw, minw, width):
        """指定のない列の幅（ブラウザの表の列の幅と同じ考え方）。表の幅を width にする。

        各列の「最小の幅」は折り返せない最も長い字の並びが収まる幅、「最大の幅」は折り返さずに収まる幅。
        全体が収まるときは、最大の幅に比べて余りを足す。収まらないときは、短い列から順に、最大の幅が
        「残りの幅を残りの列で等分した幅」以下の列に最大の幅を与え（折り返さない）、残った幅を長い列に、
        最大の幅に比べて配る（長い説明の列だけが折り返す）。長い列も最小の幅より狭くはしない。
        """
        n = len(maxw)
        if sum(maxw) <= width:
            total = sum(maxw)
            return [w + (width - total) * w / total for w in maxw]
        if sum(minw) >= width:
            # 最小の幅も収まらないときは、最小の幅に比べて縮める（語の途中で折り返す）
            total = sum(minw)
            return [w * width / total for w in minw]
        widths = [None] * n
        rest, open_cols = width, list(range(n))
        changed = True
        while changed and open_cols:
            changed = False
            share = rest / len(open_cols)
            for k in sorted(open_cols, key=lambda k: maxw[k]):
                if maxw[k] <= share:
                    widths[k] = maxw[k]
                    rest -= maxw[k]
                    open_cols.remove(k)
                    changed = True
                    break
        # 残りの長い列に、最大の幅に比べて配る（最小の幅は確保する）
        total = sum(maxw[k] for k in open_cols)
        for k in open_cols:
            widths[k] = maxw[k] * rest / total
        short = [k for k in open_cols if widths[k] < minw[k]]
        if short:
            fixed = sum(minw[k] for k in short)
            others = [k for k in open_cols if k not in short]
            total = sum(maxw[k] for k in others)
            for k in short:
                widths[k] = minw[k]
            for k in others:
                widths[k] = maxw[k] * (rest - fixed) / total
        return widths

    def column_chars(self, piece):
        """組んだ表の今の列の幅を、{字数} に書く字数にする（［表］の「列の幅を固定する」）。今折り返さない字が折り返さない
        よう切り上げ、本文の幅に収まらなければ、いちばん広い列から1字ずつ削る。"""
        pad = 2 * CELL_PAD_X
        widths = [b - a for a, b in zip(piece.col_x, piece.col_x[1:])]
        chars = [max(1, ceil((w - pad) / self.pitch - 0.01)) for w in widths]
        room = int((self.text_w - piece.col_x[0] - pad * len(chars)) / self.pitch + 0.01)
        while sum(chars) > room and max(chars) > 1:
            chars[chars.index(max(chars))] -= 1
        return chars

    def layout_cell(self, align, text, width, spans=()):
        """セルの中を組み、[(行の番号, [(字, x)])] を返す。x はセルの中の左端から。spans は均等割付の範囲。"""
        inner = width - 2 * CELL_PAD_X
        items = self.make_items(text, spans, inner)
        out = []
        if not items:
            return out
        cell_align = {"left": "justify", CENTER: CENTER, RIGHT: RIGHT}.get(align, "justify")
        for k, (start_x, chars, hang, last, trail) in enumerate(self.break_lines(items, 0, 0, 0, inner, False)):
            out.append((k, self.place_line(cell_align, start_x, chars, hang, last, trail, 0, 0, inner)))
        return out

    def table_rows(self, p):
        """表の (列の幅, [(セルごとの組んだ行, 傍点の分の空き, 行の高さ)]）。0 番目が見出しの行。"""
        t = p.table
        widths = self.column_widths(t, self.text_w - self.table_left(p))
        out = []
        for ri, cells in enumerate([t.header] + t.rows):
            laid = [self.layout_cell(a, s, widths[k], t.distribute.get((ri, k), ())) for k, (a, s) in enumerate(cells)]
            n_lines = max([len(c) for c in laid] + [1])
            extra = DOT_ROW_EXTRA if any((ri, k) in t.dots for k in range(len(cells))) else 0
            height = (n_lines * CELL_LINE_PITCH + 2 * CELL_PAD_Y + extra
                      + (DOUBLE_RULE_GAP if ri == 0 and t.double_rule else 0))
            out.append((laid, extra, height))
        return widths, out

    def table_keep_height(self, rows):
        """表の書き出しで、同じページに入れる高さ。1ページに収まる表は表全体、収まらない表は見出しの行と最初の行
        （2026-10-28 班長決定）。"""
        total = sum(h for _, _, h in rows)
        if total <= self.lines_page * self.line_pitch + 0.01:
            return total
        return sum(h for _, _, h in rows[:2])

    def layout_table(self, p, row, para_index=-1):
        """表を組んで self.tables に入れ、表の次の本文が始まる行（通しの行の番号）を返す。

        表は格子に合わせず、行の高さはセルの中の行数で決める。1ページに収まる表は途中で分けず、ページの下に
        入りきらなければ表ごと次のページへ送る。収まらない表は、ページの下に入りきらない行を次のページへ送り、
        次のページの先頭で見出しの行を繰り返す（Word の「タイトル行の繰り返し」。2026-10-28 班長決定）。
        表の次の本文は、表の下の端より後の、最初の格子の行から始める。
        """
        t = p.table
        widths, rows = self.table_rows(p)
        col_x = [self.table_left(p)]
        for w in widths:
            col_x.append(col_x[-1] + w)
        page_top = self.margin_top
        page_bottom = self.margin_top + self.lines_page * self.line_pitch
        page = row // self.lines_page + 1
        y = page_top + (row % self.lines_page) * self.line_pitch
        if self.keep and y > page_top + 0.01 and y + self.table_keep_height(rows) > page_bottom + 0.01:
            page += 1
            y = page_top
        piece = TablePiece(page, col_x, para_index=para_index)
        self.tables.append(piece)

        def put(ri, y):
            laid, extra, height = rows[ri]
            piece.rows.append(TableRow(y, y + height, ri == 0 and t.double_rule, ri))
            for k, lines in enumerate(laid):
                ci = 0
                for li, placed in lines:
                    base = (y + CELL_PAD_Y + extra + li * CELL_LINE_PITCH + (CELL_LINE_PITCH - FONT_SIZE) / 2
                            + FONT_SIZE * 220 / 256)
                    for ch, x in placed:
                        piece.glyphs.append(TableGlyph(ch, col_x[k] + CELL_PAD_X + x, base, ri, k, ci))
                        ci += 1
            return y + height

        for ri, (_, _, height) in enumerate(rows):
            if y + height > page_bottom + 0.01 and y > page_top + 0.01:
                # 次のページへ送る（ページの上から始まる行は、入りきらなくても送らない）
                page += 1
                y = page_top
                if piece.rows:
                    piece = TablePiece(page, col_x, para_index=para_index)
                    self.tables.append(piece)
                    if self.keep and ri > 0:
                        y = put(0, y)       # 見出しの行を繰り返す
                else:
                    piece.page = page
            y = put(ri, y)
        # 表の次の本文は、表の下の端より後の、最初の格子の行から
        rows_used = -(-(y - page_top - 0.01) // self.line_pitch)
        return (page - 1) * self.lines_page + int(rows_used)

    # ---------- 画像（[IMAGE 1]{30}。2026-10-29 班長決定。検討_画像の挿入.md の7） ----------

    def image_left(self, p):
        """画像を置ける範囲の左端（本文の左端から）。->N があればその字数、なければ本文の左インデント。"""
        if p.left_indent is not None:
            return min(p.left_indent, self.dt.chars_lines[0] - 1) * self.pitch
        return self.body_left(p)

    def image_size(self, p):
        """(置ける範囲の左端, 幅, 高さ, データがないか)。幅は字数×字送り（置ける幅を超えるときと、字数を省いたときは
        置ける幅）、高さは縦横の比から。1ページの本文の高さを超えるときは、比を保ったまま縮める。"""
        number, chars = p.image
        left = self.image_left(p)
        avail = self.text_w - left
        w = avail if chars is None else min(chars * self.pitch, avail)
        size = self.image_sizes.get(number)
        ratio = size[1] / size[0] if size and size[0] else MISSING_RATIO
        h = w * ratio
        max_h = self.lines_page * self.line_pitch
        if h > max_h:
            h, w = max_h, max_h / ratio
        return left, w, h, size is None

    def image_rows(self, h):
        """高さ h の画像が使う行数（画像の下の端より後の、最初の格子の行まで）。"""
        return max(1, int(-(-(h - 0.01) // self.line_pitch)))

    def layout_image(self, p, row, para_index=-1):
        """画像を組んで self.images に入れ、次の本文が始まる行（通しの行の番号）を返す。

        画像の上の端は、その行の格子の上の端。ページの下に入りきらなければ、画像ごと次のページの上へ送る（途中で
        分けない。Word の行内の画像と同じ）。右に置いた画像（--: ）は、続く本文を左側に回り込ませる：画像の行そのものは
        行を使わず、画像の横の行の右インデントを「画像の幅＋WRAP_GAP 字」だけ増やす（_wrap_extra）。回り込む行の幅が
        WRAP_MIN 字に満たないときは、回り込ませずに塊として組む。次のページへ送った回り込みの画像の前の本文は、元の幅の
        まま組み、次のページの上から回り込ませる。
        """
        left, w, h, missing = self.image_size(p)
        lines_page = self.lines_page
        start = row
        if row % lines_page and (row % lines_page) * self.line_pitch + h > lines_page * self.line_pitch + 0.01:
            start = row + lines_page - row % lines_page
        n_rows = self.image_rows(h)
        gap = WRAP_GAP * self.pitch
        wrap = p.align == RIGHT and self.text_w - w - gap - left >= WRAP_MIN * self.pitch - 0.01
        if p.align == RIGHT:
            x = self.text_w - w
        elif p.align in (CENTER, TITLE):
            x = left + (self.text_w - left - w) / 2
        else:
            x = left
        y = self.margin_top + (start % lines_page) * self.line_pitch
        self.images.append(ImagePiece(start // lines_page + 1, x, y, w, h, p.image[0], para_index, missing, wrap))
        if wrap:
            self._wrap = (start, start + n_rows, w + gap)
            return row
        return start + n_rows

    def _wrap_extra(self, row):
        """通しの行 row の右インデントに足す幅（回り込みの範囲の行なら、画像の幅＋間の空き）。"""
        if self._wrap and self._wrap[0] <= row < self._wrap[1]:
            return self._wrap[2]
        return 0.0

    def _end_wrap(self, row):
        """回り込みを終える。row が回り込みの範囲の終わりより前なら、範囲の終わり（画像の下の端より後の行）を返す。"""
        if self._wrap:
            row = max(row, self._wrap[1])
            self._wrap = None
        return row
