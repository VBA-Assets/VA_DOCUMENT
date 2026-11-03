"""ボタンのアイコン（2026-10-23 班長決定）。

アイコンは Microsoft の Fluent UI System Icons（MIT ライセンス。icons\\LICENSE）の 20px・regular の SVG を、
起動時に PyMuPDF で、画面の拡大率に合った大きさの画像にする（拡大してもぼやけない。部品を増やさない）。
色は SVG の塗り（#212121）を、通常は文字の色、押せないときは薄い灰色に置き換える。
Office の色付きアイコンのように2色にする（2026-10-24 班長指示）：同じアイコンの塗りつぶし版（<名前>_filled.svg。
20px・filled）を薄い青（theme.ICON_TINT）で下に敷き、その上に線画を濃い色で重ねる。内側のない形（矢印・字の線）は、
塗りつぶし版が線画と重なるので、線画のままに見える。塗りつぶし版がなければ線画だけで描く。
リボンの大きいボタンのアイコンは、面を色分けしたフラットなアイコン（<名前>_large.svg。32px。自作。グラデーション・影は
使わない）にする（線画を大きくするだけでは単調なため。2026-10-30 班長決定）。色は SVG に書いたまま使い、押せないときは
小さいアイコンと同じ灰色の線画を大きくして出す。_large.svg のないアイコンは、線画を大きくする。
"""
import re
from pathlib import Path

import fitz  # PyMuPDF

from . import theme

ICON_DIR = Path(__file__).resolve().parent / "icons"
ICON_SIZE = 16          # 拡大率 100% のときの大きさ（画素）
SVG_FILL = "#212121"

# ボタンの字 → アイコンのファイル名（icons\<名前>.svg）。リボンのボタン（ribbon.py。字の改行は除いて引く）も、
# ほかの画面のボタン（decorate）も、ここで引く
BUTTON_ICONS = {
    "開く": "folder_open", "保存": "save", "印刷": "print", "閉じる": "document_dismiss", "オプション": "settings",
    "選択範囲を仮名化": "person_lock", "コピー": "copy", "貼り付け": "clipboard_paste",
    "表題": "document_title", "中央": "text_align_center", "右": "text_align_right", "インデント": "text_indent_increase", "太字": "text_bold", "均等割付": "text_align_distributed", "傍点": "text_emphasis",
    "見出し": "text_header_2", "箇条書き": "text_bullet_list_ltr", "段落番号": "text_number_list_ltr",
    "改ページ": "document_page_break", "セクション区切り": "document_split_hint", "目次": "text_bullet_list_square",
    "ヘッダー": "document_header", "画像": "image",     # image は自作（Fluent の image にならった線画。2026-10-29）
    "フッター": "document_footer",     # document_footer は自作（document_header を上下に返した形。2026-11-03）
    "表": "table",      # table は自作（Fluent の table にならった線画。2026-10-31）
    "パスをコピー": "copy", "ファイルから読み込む": "folder_open", "検索": "search", "蛍光ペン": "highlight", "置換": "arrow_swap",
}


def _svg_body(svg):
    return re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)


def render_png(name, size, color, tint=None):
    """アイコンを size 画素四方の PNG（バイト列）にする。線画は color の色。tint があれば、塗りつぶし版をその色で下に敷く。"""
    svg = (ICON_DIR / f"{name}.svg").read_text(encoding="utf-8").replace(SVG_FILL, color)
    filled = ICON_DIR / f"{name}_filled.svg"
    if tint and filled.exists():
        head = re.match(r"<svg[^>]*>", svg).group(0)
        svg = head + _svg_body(filled.read_text(encoding="utf-8")).replace(SVG_FILL, tint) + _svg_body(svg) + "</svg>"
    return _svg_png(svg, size)


def render_large_png(name, size):
    """大きいボタンの色付きのアイコン（<名前>_large.svg）を size 画素四方の PNG にする。なければ None。"""
    path = ICON_DIR / f"{name}_large.svg"
    return _svg_png(path.read_text(encoding="utf-8"), size) if path.exists() else None


def _svg_png(svg, size):
    with fitz.open(stream=svg.encode("utf-8"), filetype="svg") as doc:
        page = doc[0]
        zoom = size / page.rect.width
        return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True).tobytes("png")


class IconSet:
    """アイコンの画像を作って覚えておく（Tk の画像は、参照がなくなると消えるため）。"""

    def __init__(self, root):
        import tkinter as tk
        self._tk = tk
        self.root = root
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)        # 画面の拡大率
        self.size = max(ICON_SIZE, round(ICON_SIZE * self.scale))
        self._cache = {}

    def image(self, name, disabled=False, size=None, large=False):
        """アイコンの画像。size（画素）がなければ小さいアイコンの大きさ（リボンの大きいボタンは大きくする）。large なら、
        リボンの大きいボタンの色付きのアイコン（押せないときは、小さいアイコンと同じ灰色の線画）。"""
        size = size or self.size
        key = (name, disabled, size, large)
        if key not in self._cache:
            data = render_large_png(name, size) if large and not disabled else None
            if data is None:
                color, tint = (theme.DISABLED_TEXT, theme.ICON_TINT_DISABLED) if disabled else (theme.TEXT, theme.ICON_TINT)
                data = render_png(name, size, color, tint)
            self._cache[key] = self._tk.PhotoImage(data=data)
        return self._cache[key]

    def decorate(self, widget):
        """widget の中のボタンに、字に合ったアイコンを付ける（Word のリボンと同じく、アイコン＋字）。"""
        from tkinter import ttk
        for child in widget.winfo_children():
            if isinstance(child, ttk.Button) and not child.cget("image"):    # リボンのボタンは作るときに付けた
                text = str(child.cget("text"))
                name = BUTTON_ICONS.get(text)
                if name:
                    images = (self.image(name), "disabled", self.image(name, disabled=True))
                    child.configure(image=images, compound="left")
            self.decorate(child)
