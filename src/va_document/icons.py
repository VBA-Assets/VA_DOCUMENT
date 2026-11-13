"""ボタンのアイコン（2026-10-23 班長決定）。

アイコンは Microsoft の Fluent UI System Icons（MIT ライセンス。icons\\LICENSE）の 20px・regular の SVG を、
開発のときに scripts\\make_icons.py で PNG にしたもの（icons\\png\\）を使う（Ver300、2026-11-14。それまでは起動のたびに
PyMuPDF で SVG を画像にしていたが、PyMuPDF は AGPL-3.0 なので、MIT License にするために外した。VA Case と同じ作り）。
画面の拡大率ごとの大きさ（SMALL_SIZES・LARGE_SIZES）は、その大きさで描いた PNG をそのまま使い（替える前と同じ画素）、
それ以外の大きさは、大きく描いたもの（BASE_SMALL・BASE_LARGE）を Pillow で縮める（拡大してもぼやけない）。
色は SVG の塗り（#212121）を、通常は文字の色、押せないときは薄い灰色に置き換える（PNG にするとき）。
Office の色付きアイコンのように2色にする（2026-10-24 班長指示）：同じアイコンの塗りつぶし版（<名前>_filled.svg。
20px・filled）を薄い青（theme.ICON_TINT）で下に敷き、その上に線画を濃い色で重ねる。内側のない形（矢印・字の線）は、
塗りつぶし版が線画と重なるので、線画のままに見える。塗りつぶし版がなければ線画だけで描く。
リボンの大きいボタンのアイコンは、面を色分けしたフラットなアイコン（<名前>_large.svg。32px。自作。グラデーション・影は
使わない）にする（線画を大きくするだけでは単調なため。2026-10-30 班長決定）。色は SVG に書いたまま使い、押せないときは
小さいアイコンと同じ灰色の線画を大きくして出す。_large.svg のないアイコンは、線画を大きくする。
"""
import io
import json
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parent / "icons"        # SVG（もと）と LICENSE
PNG_DIR = ICON_DIR / "png"                                  # make_icons.py で作った PNG と index.json
ICON_SIZE = 16          # 拡大率 100% のときの大きさ（画素）
# その大きさで描いておく大きさ（拡大率 100%〜300% の小さいアイコンと、リボンの大きいボタン〔ribbon.LARGE_ICON の倍〕）
SMALL_SIZES = (16, 20, 24, 28, 32, 36, 40, 48, 56, 64, 72, 80, 96)
LARGE_SIZES = (32, 40, 48, 56, 64, 72, 80, 96)
BASE_SMALL = BASE_LARGE = 128     # それ以外の大きさは、この大きさのものを縮める

# ボタンの字 → アイコンのファイル名（icons\<名前>.svg）。リボンのボタン（ribbon.py。字の改行は除いて引く）も、
# ほかの画面のボタン（decorate）も、ここで引く
BUTTON_ICONS = {
    "開く": "folder_open", "保存": "save", "印刷": "print", "閉じる": "document_dismiss",
    "選択範囲を仮名化": "person_lock", "コピー": "copy", "貼り付け": "clipboard_paste",
    "表題": "document_title", "中央": "text_align_center", "右": "text_align_right", "インデント": "text_indent_increase", "太字": "text_bold", "均等割付": "text_align_distributed", "傍点": "text_emphasis",
    "見出し": "text_header_2", "箇条書き": "text_bullet_list_ltr", "段落番号": "text_number_list_ltr",
    "改ページ": "document_page_break", "セクション区切り": "document_split_hint", "目次": "text_bullet_list_square",
    "ヘッダー": "document_header", "画像": "image",     # image は自作（Fluent の image にならった線画。2026-10-29）
    "フッター": "document_footer",     # document_footer は自作（document_header を上下に返した形。2026-11-03）
    "表": "table",      # table は自作（Fluent の table にならった線画。2026-10-31）
    "パスをコピー": "copy", "ファイルから読み込む": "folder_open", "検索": "search", "蛍光ペン": "highlight", "置換": "arrow_swap",
}


_index = None
_sheets = {}


def index():
    """index.json（種類ごとのアイコンの並びと、PNG にしたときの色）。"""
    global _index
    if _index is None:
        _index = json.loads((PNG_DIR / "index.json").read_text(encoding="utf-8"))
    return _index


def _sheet(kind, size):
    """種類（normal・disabled・large）と大きさの PNG（全部のアイコンを横に並べたもの）。"""
    key = (kind, size)
    if key not in _sheets:
        from PIL import Image
        with Image.open(PNG_DIR / f"{kind}_{size}.png") as im:
            _sheets[key] = im.convert("RGBA")
    return _sheets[key]


def icon_image(name, size, disabled=False, large=False):
    """アイコンの Pillow の画像（size 画素四方）。large なら大きいボタンの色付きのアイコン（なければ None）。"""
    kind = "large" if large else ("disabled" if disabled else "normal")
    names = index()[kind]
    if name not in names:
        return None
    i = names.index(name)
    sizes, base = (LARGE_SIZES, BASE_LARGE) if large else (SMALL_SIZES, BASE_SMALL)
    s = size if size in sizes else base
    im = _sheet(kind, s).crop((i * s, 0, (i + 1) * s, s))
    if s != size:
        from PIL import Image
        im = im.resize((size, size), Image.LANCZOS)
    return im


def icon_png(name, size, disabled=False, large=False):
    """icon_image の PNG（バイト列。Tk の PhotoImage に渡す）。なければ None。"""
    im = icon_image(name, size, disabled, large)
    if im is None:
        return None
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


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
            data = icon_png(name, size, large=True) if large and not disabled else None
            if data is None:
                data = icon_png(name, size, disabled=disabled)
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
