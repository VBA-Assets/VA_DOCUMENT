"""Word のリボンと同じ形のボタンの並び（2026-10-24 班長指示）。

・ボタンを組（ファイル・AI 連携・書式など）に分け、組の名前をボタンの下に小さく書く。組と組の間は縦の線で区切る。
・よく使うボタンは大きいアイコンの下に字（large）、ほかは小さいアイコンの右に字を縦に3つまで積む（small）。
・ボタンは、ふだんは枠も地もなく、マウスを重ねたときだけ淡い青の地と枠を出す（Word のリボンと同じ。班長の UI 方針の
  「ボタンには常時、細い枠線」の、このツールだけの例外。2026-10-24 班長決定）。スタイルは theme.py の Ribbon*。
・組の名前は、どの組も下端にそろえる（2026-10-24 班長指示）。
・ボタンを押しても、キーボードの焦点はエディターに残す（Word のリボンと同じ。ttk のボタンは押すと焦点を取るので、
  ボタンで書式を付けた後の Ctrl+Z〔エディターのキー〕が効かず、打った字もエディターに入らなかった。2026-10-28 班長指摘）。
・「AI 連携」の組だけは、ほかの組の流れから外し、白い地を枠で囲んでウィンドウの右上に置く（app.py。2026-10-30 班長決定）。
・幅に組が入りきらないときは、入りきらない組を次の段に送る（Word のように組を畳んで隠すことはしない）。
  もとは、大きいボタンだけの組（AI 連携）を小さいボタンを積んだ形に縮めてもいたが、2026-10-25 に［コピー］［貼り付け］を
  小さいボタンにして縮める組がなくなったので、その仕組みは除いた。
・小さいボタンのうち grow を付けたもの（［開く］［保存］［見出し］［表］［画像］）は、大きくしても組が1段に入りきる幅が
  あるときだけ、大きいボタンにする（2026-10-30 班長指示。［表］［画像］は 2026-11-03 班長指示）。狭くなったら、組を折り返す前に、まずボタンを小さくする（同日の班長指示。
  できるだけ折り返さない）。大きくすると、そのボタンの列を分け、同じ列のほかのボタンは小さいまま
  残す。大きくしたボタンの下に残ったボタンは、次の列に入りきれば、その上に積む（［閉じる］［オプション］）。入りきらなければ
  （［箇条書き］［段落番号］）、残ったボタンだけで1列にし、右の列の並びは変えない。入りきるかは、組ごとに大小の両方の幅を一度だけ測っておいて決める（大きくしたら
  入らなくなって小さく戻す、を繰り返さないため）。
"""
from tkinter import ttk

from .icons import BUTTON_ICONS

ROWS = 3                # 小さいボタンを縦に積む数
LARGE_ICON = 32         # 大きいボタンのアイコンの大きさ（拡大率 100% のとき。画素）


class RibbonGroup(ttk.Frame):
    """リボンの1つの組。ボタンは左から列ごとに置く。prefix はスタイルの名前の頭（囲んだ組は "RibbonBox"。囲みが
    区切りになるので、右の区切りの線は引かない）。"""

    def __init__(self, master, title, icons, prefix="Ribbon"):
        super().__init__(master, style=f"{prefix}.TFrame")
        self.title = title
        self.icons = icons
        self.prefix = prefix
        self.body = ttk.Frame(self, style=f"{prefix}.TFrame")
        self.body.grid(row=0, column=0, sticky="nsew", padx=2, pady=(2, 0))
        ttk.Label(self, text=title, style=f"{prefix}Group.TLabel", anchor="center").grid(row=1, column=0, sticky="sew")
        if prefix == "Ribbon":
            ttk.Separator(self, orient="vertical").grid(row=0, column=1, rowspan=2, sticky="ns", pady=(4, 4))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)      # 組の高さがそろったとき、余りはボタンの側に回し、名前を下端にそろえる
        self._items = []          # [(種類〔large・small・block〕, 部品, grow)]。置く順
        self._grown = {}          # grow のボタン → {大きいか: (スタイル, アイコンの指定)}
        self.expanded = False     # grow のボタンを大きくしているか
        self.widths = None        # {大きいか: 組の幅}。ボタンを足したら測り直す（Ribbon.reflow）

    def _images(self, text, icon, large):
        """ボタンのアイコンの指定。icon を省けば、ボタンの字（改行を除く）から BUTTON_ICONS で引く。"""
        icon = icon or BUTTON_ICONS.get(text.replace("\n", ""))
        if self.icons is None or not icon:
            return {}
        size = round(LARGE_ICON * self.icons.scale) if large else None
        images = (self.icons.image(icon, size=size, large=large), "disabled",
                  self.icons.image(icon, disabled=True, size=size))
        return {"image": images, "compound": "top" if large else "left"}

    def large(self, text, command, icon=None, **kw):
        """大きいボタン（アイコンの下に字）。1列を使う。長い字は改行で2行に分ける（説明書きは、改行を除いた字で引く。
        tooltip.py）。"""
        b = ttk.Button(self.body, text=text, command=command, style=f"{self.prefix}Large.TButton", takefocus=False,
                       **self._images(text, icon, True), **kw)
        return self._add("large", b)

    def small(self, text, command, icon=None, grow=False, **kw):
        """小さいボタン（アイコンの右に字）。今の列に縦に積み、ROWS 個で次の列へ。grow なら、幅があるときは大きい
        ボタンにする（モジュールの説明）。"""
        widget = ttk.Button(self.body, text=text, command=command, style=f"{self.prefix}.TButton", takefocus=False,
                            **self._images(text, icon, False), **kw)
        if grow:
            self._grown[widget] = {large: (f"{self.prefix}Large.TButton" if large else f"{self.prefix}.TButton",
                                           self._images(text, icon, large)) for large in (False, True)}
        return self._add("small", widget, grow)

    def block(self, widget):
        """部品（選択欄の並びなど）を、新しい列の上から置く。"""
        self._add("block", widget)

    def _add(self, kind, widget, grow=False):
        self._items.append((kind, widget, grow))
        self.widths = None
        self._place()
        return widget

    def set_expanded(self, expanded):
        """grow のボタンを大きく（expanded）するか、小さくするかを決めて置き直す。"""
        if expanded != self.expanded:
            self.expanded = expanded
            self._place()

    def _columns(self):
        """小さいボタンだけのときの列：[("small", [(部品, grow)]) か (種類, 部品)]。"""
        columns, current = [], None
        for kind, widget, grow in self._items:
            if kind == "small":
                if current is None or len(current) >= ROWS:
                    current = []
                    columns.append(("small", current))
                current.append((widget, grow))
            else:
                current = None
                columns.append((kind, widget))
        return columns

    def _place(self):
        column = 0

        def stack(widgets):
            nonlocal column
            for row, w in enumerate(widgets):
                w.grid(in_=self.body, row=row, column=column, rowspan=1, sticky="w", padx=1, pady=0)
            column += 1

        carry = []      # 大きくしたボタンの下に残った小さいボタン（次の列に入りきれば、その上に積む）
        for kind, content in self._columns():
            if kind != "small" or len(carry) + len(content) > ROWS:
                if carry:
                    stack(carry)
                carry = []
            if kind == "large":
                content.grid(in_=self.body, row=0, column=column, rowspan=ROWS, sticky="ns", padx=1, pady=0)
                column += 1
            elif kind == "block":
                content.grid(in_=self.body, row=0, column=column, rowspan=ROWS, sticky="nw", padx=(1, 6), pady=(1, 0))
                column += 1
            else:
                rest, grown = carry, False
                carry = []
                for w, grow in content:
                    big = grow and self.expanded
                    if grow:
                        style, images = self._grown[w][big]
                        w.configure(style=style, **images)
                    if not big:
                        rest.append(w)
                        continue
                    if rest:            # 大きくしたボタンの上にあった小さいボタンは、その左の列に残す
                        stack(rest)
                        rest = []
                    w.grid(in_=self.body, row=0, column=column, rowspan=ROWS, sticky="ns", padx=1, pady=0)
                    column += 1
                    grown = True
                if grown:
                    carry = rest
                elif rest:
                    stack(rest)
        if carry:
            stack(carry)


class Ribbon(ttk.Frame):
    """組を左から並べる。幅に入りきらない組は次の段に送る。boxed なら、組を白い地にする（囲みの中に置く「AI 連携」）。"""

    def __init__(self, master, icons, boxed=False):
        self.prefix = "RibbonBox" if boxed else "Ribbon"
        super().__init__(master, style=f"{self.prefix}.TFrame")
        self.icons = icons
        self.groups = []
        self._lines = []          # 段ごとの枠
        self._layout = None
        self._min_height = 0
        self._measuring = False
        self.expanded = False     # grow のボタンを大きくしているか（組のすべてで同じ）
        self.bind("<Configure>", lambda e: self.reflow(e.width))

    def group(self, title):
        g = RibbonGroup(self, title, self.icons, self.prefix)
        self.groups.append(g)
        self.reflow(self.winfo_width())
        return g

    def set_min_height(self, height):
        """段の高さを height 画素以上にする（別に置いた組と高さをそろえ、組の名前の下端をそろえるため）。"""
        self._min_height = height
        for line in self._lines:
            line.rowconfigure(0, minsize=height)

    def _measure(self):
        """組ごとに、grow のボタンを大きくしたときと小さくしたときの幅を測る（測る間の Configure では置き直さない）。"""
        self._measuring = True
        try:
            for g in self.groups:
                if g.widths is None:
                    current, widths = g.expanded, {}
                    for expanded in (True, False):
                        g.set_expanded(expanded)
                        g.update_idletasks()
                        widths[expanded] = g.winfo_reqwidth()
                    g.set_expanded(current)
                    g.widths = widths
        finally:
            self._measuring = False

    def reflow(self, width):
        """幅 width に入るように、組を段に分けて置く（同じ並びなら置き直さない。Configure が続かないように）。
        grow のボタンを大きくしても1段に入りきるなら、大きくする。幅がまだ決まっていない（width <= 1。組を作って
        いる間）ときは、測らずに小さいまま置く。"""
        if self._measuring:
            return
        if width <= 1:
            width = 10 ** 6
            expanded = False
        else:
            self._measure()
            expanded = sum(g.widths[True] for g in self.groups) <= width
        rows, used = [[]], 0
        for g in self.groups:
            w = g.widths[expanded] if g.widths else g.winfo_reqwidth()
            if rows[-1] and used + w > width:
                rows.append([])
                used = 0
            rows[-1].append(g)
            used += w
        layout = [[id(g) for g in row] for row in rows]
        if layout == self._layout and expanded == self.expanded:
            return
        self._layout = layout
        self.expanded = expanded
        for g in self.groups:
            g.set_expanded(expanded)
        # 段ごとに枠を分け、組を左から詰めて置く（1つの表に段と列で置くと、2段目の組が1段目の同じ列の幅に
        # 広げられ、組の間が空いた。2026-10-25 班長指摘）
        while len(self._lines) < len(rows):
            self._lines.append(ttk.Frame(self, style=f"{self.prefix}.TFrame"))
            self._lines[-1].rowconfigure(0, minsize=self._min_height)
        for r, line in enumerate(self._lines):
            if r < len(rows):
                line.grid(row=r, column=0, sticky="w")
            else:
                line.grid_remove()
        for r, row in enumerate(rows):
            for c, g in enumerate(row):
                g.grid(in_=self._lines[r], row=0, column=c, sticky="nsw")
                g.lift(self._lines[r])      # 組は段の枠より先に作るので、枠の上に出す


def labeled_rows(parent, rows):
    """ラベル付きの部品を縦に並べた枠（「文書の種類 [選択欄]」「ページ番号 [選択欄]」）。部品の左端をそろえる
    （2026-10-24 班長指示）。rows は [(ラベル, 部品を作る関数)]。(枠, [部品]) を返す。"""
    frame = ttk.Frame(parent, style="Ribbon.TFrame")
    widgets = []
    for r, (text, factory) in enumerate(rows):
        ttk.Label(frame, text=text, style="Ribbon.TLabel").grid(row=r, column=0, sticky="w", padx=(2, 6), pady=1)
        widget = factory(frame)
        widget.grid(row=r, column=1, sticky="w", pady=1)
        widgets.append(widget)
    return frame, widgets

