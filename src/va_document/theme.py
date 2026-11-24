"""画面の配色と部品のスタイル（フラットデザイン。班長の UI 設計方針の「既定配色（Office風）」）。

色の定義は、ここに集める。ttk の部品は 'clam' テーマを基にして見た目を直接指定し、ttk に対応品のない
classic tk の部品（Text・Canvas・PanedWindow・Toplevel・Listbox）は、オプションデータベースで一括して指定する。
VA mints（..\\VA_MINTS\\src\\mints_prep\\ui\\theme.py）にそろえたうえで、主要な操作のボタンは、地色ではなく
枠線の色をアクセント色にして区別する（Accent.TButton）。
"""
from tkinter import font as tkfont
from tkinter import ttk

WINDOW_BG = "#f0f0f0"      # ウィンドウ・フレームの背景
FIELD_BG = "#ffffff"       # 入力欄・カード等の背景
CONTROL_BG = "#fdfdfd"     # ボタンの通常時の地色
HOVER_BG = "#e0eef9"       # ボタンのホバー時の地色（淡い青）
PRESSED_BG = "#cce4f7"     # ボタンの押下時の地色（濃い青）
TEXT = "#1a1a1a"           # 通常テキスト
NOTE = "#666666"           # 補足・注記テキスト
BORDER = "#c8c8c8"         # 枠線・区切り線
ACCENT = "#0078d4"         # アクセント（フォーカス枠線・主要ボタンの強調枠）
DISABLED_TEXT = "#a0a0a0"
# 登録した語・記号の印（入力欄で伏せ漏れを目で確かめるための、2つ目の差し色）
REGISTERED_BG = "#d9f2d9"     # 薄い緑（蛍光ペンの黄と見分ける。確認表示の仮名化した語の地も同じ色。2026-10-24）
HIGHLIGHT_BG = "#ffff00"     # 蛍光ペン（==文字==。Word の蛍光ペンの黄と同じ）
# 検索で見つかった語（すべて）と、今選んでいる1か所
FOUND_BG = PRESSED_BG
CURRENT_FOUND_BG, CURRENT_FOUND_FG = ACCENT, "#ffffff"
# AI の回答で変わった段落の、右端の線の太さ（画素。app.py の changed の印）
CHANGE_BAR_WIDTH = 4
# アイコンの塗り（Office の色付きアイコンのように、形の内側を薄い青にする。押せないときは薄い灰色。2026-10-24 班長指示）
ICON_TINT = "#9cc9f0"
ICON_TINT_DISABLED = "#e2e2e2"
# リボンの大きいボタンのアイコンの色は、アイコンの SVG（icons\<名前>_large.svg）に書く（面ごとに色を分けた絵のため。
# 2026-10-30 班長決定。icons.py）
# リボンのボタンに重ねたときの枠（淡い青の地より少し濃い青）
RIBBON_HOVER_BORDER = "#a9cdee"
# 確認表示の地（ページの白と見分ける）
PREVIEW_BG = "#e5e5e5"
SCROLL_THUMB, SCROLL_THUMB_ACTIVE, SCROLL_THUMB_PRESSED = "#c1c1c1", "#a8a8a8", "#8a8a8a"

UI_FONT_FAMILY = "Yu Gothic UI"
UI_FONT_SIZE = 9
# 入力欄の書体（全角・半角の幅がそろい、見分けやすいもの）。先にあるものを使う
EDITOR_FONT_FAMILIES = ("BIZ UDゴシック", "BIZ UDGothic", "ＭＳ ゴシック", "MS Gothic")
EDITOR_FONT_SIZE = 11
# 入力欄の行の間隔（ポイント。行の上と下に足す。折り返した行の間にも足す）。字の大きさや Word の段落の前後の間隔と
# 同じ単位にし、表示の拡大（125%・150% など）でも字と一緒に広がるようにする（2026-10-26 班長決定。それまでは画素）
EDITOR_LINE_SPACING = 6
# ナビゲーション（見出しの一覧）の字の大きさと行の間隔（ポイント。行の上と下に足す）。オプションで変えられる。書体の既定は
# エディターの既定と同じ（default_editor_family）。2026-11-24 班長指示
NAV_FONT_SIZE = UI_FONT_SIZE
NAV_LINE_SPACING = 3


# オプションで選べるエディターの書体（全角と半角の幅がそろう等幅のもの。2026-10-24 班長指示）。この PC にあるものだけ出す
EDITOR_FONT_CHOICES = ("BIZ UDゴシック", "BIZ UD明朝", "ＭＳ ゴシック", "ＭＳ 明朝")
_editor = {"family": "", "size": EDITOR_FONT_SIZE, "spacing": EDITOR_LINE_SPACING}


def set_editor_prefs(family, size, spacing):
    """オプションのエディターの書体（"" は既定）・字の大きさ・行の間隔を決める（editor_font などが使う）。"""
    _editor.update(family=family or "", size=size, spacing=spacing)


def editor_spacing(widget):
    """行の間隔（ポイント）を、Text の spacing1・spacing2・spacing3（画素）にする。"""
    px = round(_editor["spacing"] * widget.winfo_fpixels("1p"))
    return {"spacing1": px // 2, "spacing2": px, "spacing3": px - px // 2}


def editor_font_choices(root):
    families = set(tkfont.families(root))
    return [f for f in EDITOR_FONT_CHOICES if f in families]


def default_editor_family(root):
    """オプションの書体の（既定）：EDITOR_FONT_FAMILIES のうち、この PC にある最初の書体。なければ "TkFixedFont"。"""
    families = set(tkfont.families(root))
    return next((f for f in EDITOR_FONT_FAMILIES if f in families), "TkFixedFont")


def editor_font(root):
    size = _editor["size"]
    if _editor["family"] and _editor["family"] in set(tkfont.families(root)):
        return (_editor["family"], size)
    return (default_editor_family(root), size)


# ナビゲーションと「仮名化する語」の一覧のスタイル（書体・字の大きさ・行の高さをオプションで変える。apply_nav_prefs）
LIST_STYLE = "Nav.Treeview"


def apply_nav_prefs(root, family, size, spacing):
    """ナビゲーションと「仮名化する語」の一覧（LIST_STYLE。2026-11-24 班長指示で、仮名化する語の一覧も同じ字にした）に、オプションの書体（"" は（既定）。エディターの（既定）と同じ書体。2026-11-24
    班長指摘で、画面の書体から改めた）・字の大きさ・行の間隔（ポイント）を当てる。行の高さは、字の高さに行の間隔を足したもの
    （表示の拡大〔125%・150% など〕でも字と一緒に広がる）。"""
    if not family or family not in set(tkfont.families(root)):
        family = default_editor_family(root)
        if family == "TkFixedFont":
            family = tkfont.nametofont("TkFixedFont").actual("family")
    line = tkfont.Font(root=root, family=family, size=size).metrics("linespace")
    style = ttk.Style(root)
    style.configure(LIST_STYLE, font=(family, size), rowheight=line + round(spacing * root.winfo_fpixels("1p")))


def apply_theme(root):
    """テーマを適用する。部品を作る前に一度呼ぶ（Toplevel の確認画面にも及ぶ）。"""
    families = set(tkfont.families(root))
    family = UI_FONT_FAMILY if UI_FONT_FAMILY in families else ""
    if family:
        for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont"):
            tkfont.nametofont(name).configure(family=family, size=UI_FONT_SIZE)

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    root.configure(background=WINDOW_BG)
    style.configure(".", background=WINDOW_BG, foreground=TEXT, bordercolor=BORDER, focuscolor=ACCENT,
                    lightcolor=WINDOW_BG, darkcolor=WINDOW_BG)
    style.map(".", foreground=[("disabled", DISABLED_TEXT)])

    # ボタン：通常はニュートラルな地＋細い灰色の枠。ホバーで淡い青、押下で濃い青
    # ボタンの幅は中身（アイコン＋字）に合わせる（width の負の値は最小の幅。2026-10-23、アイコンを付けて段が広がったため）
    style.configure("TButton", background=CONTROL_BG, bordercolor=BORDER, lightcolor=CONTROL_BG,
                    darkcolor=CONTROL_BG, padding=(10, 3), width=-6)
    style.map("TButton",
              background=[("disabled", CONTROL_BG), ("pressed", PRESSED_BG), ("active", HOVER_BG)],
              lightcolor=[("disabled", CONTROL_BG), ("pressed", PRESSED_BG), ("active", HOVER_BG)],
              darkcolor=[("disabled", CONTROL_BG), ("pressed", PRESSED_BG), ("active", HOVER_BG)],
              bordercolor=[("disabled", BORDER), ("pressed", ACCENT), ("active", ACCENT)])
    # 主要な操作のボタン：枠線だけをアクセント色にする（地色は塗らない）
    style.configure("Accent.TButton", bordercolor=ACCENT)
    style.map("Accent.TButton", bordercolor=[("disabled", BORDER), ("!disabled", ACCENT)])
    # 配置などの小さいボタン
    style.configure("Small.TButton", padding=(8, 1), width=-4)
    # リボンのボタン（Word のリボンと同じく、ふだんは枠も地もなく、重ねたときだけ淡い青の地と枠。班長の UI 方針の
    # 「常時、細い枠線」の、このツールだけの例外。2026-10-24 班長決定）
    # 「AI 連携」の組（RibbonBox*）は、白い地を細い灰色の枠で囲み、ほかの組（Ribbon*）と分ける（AI に渡す・取り込む
    # 操作だけの組。2026-10-30 班長決定）
    for prefix, bg in (("Ribbon", WINDOW_BG), ("RibbonBox", FIELD_BG)):
        ribbon_states = dict(
            background=[("disabled", bg), ("pressed", PRESSED_BG), ("active", HOVER_BG)],
            lightcolor=[("disabled", bg), ("pressed", PRESSED_BG), ("active", HOVER_BG)],
            darkcolor=[("disabled", bg), ("pressed", PRESSED_BG), ("active", HOVER_BG)],
            bordercolor=[("disabled", bg), ("pressed", RIBBON_HOVER_BORDER), ("active", RIBBON_HOVER_BORDER)])
        for name, padding, anchor in ((f"{prefix}.TButton", (3, 1), "w"), (f"{prefix}Large.TButton", (4, 2), "center")):
            style.configure(name, background=bg, bordercolor=bg, lightcolor=bg, darkcolor=bg, padding=padding, width=0,
                            anchor=anchor, justify="center")
            style.map(name, **ribbon_states)
        style.configure(f"{prefix}.TFrame", background=bg)
        style.configure(f"{prefix}.TLabel", background=bg)
        style.configure(f"{prefix}Group.TLabel", background=bg, foreground=NOTE, padding=(0, 0, 0, 2))
    # 囲みの枠（「AI 連携」の組・印刷プレビューのページ。1画素の灰色。内側の線は地と同じ白にして、枠を1本に見せる）
    style.configure("Border.TFrame", background=FIELD_BG, borderwidth=1, relief="solid", bordercolor=BORDER,
                    lightcolor=FIELD_BG, darkcolor=FIELD_BG)

    style.configure("Note.TLabel", foreground=NOTE)
    # 白い地の欄の中に置く注記（ナビゲーションの「見出しがありません」）
    style.configure("FieldNote.TLabel", background=FIELD_BG, foreground=NOTE)
    style.configure("TEntry", fieldbackground=FIELD_BG, bordercolor=BORDER, lightcolor=FIELD_BG,
                    darkcolor=FIELD_BG, insertcolor=TEXT, padding=3)
    style.map("TEntry", bordercolor=[("focus", ACCENT)])
    style.configure("TSpinbox", fieldbackground=FIELD_BG, background=CONTROL_BG, bordercolor=BORDER,
                    lightcolor=FIELD_BG, darkcolor=FIELD_BG, arrowcolor=TEXT, insertcolor=TEXT, padding=2)
    style.map("TSpinbox", bordercolor=[("focus", ACCENT)], background=[("active", HOVER_BG)])
    style.configure("TCombobox", fieldbackground=FIELD_BG, background=CONTROL_BG, bordercolor=BORDER,
                    lightcolor=FIELD_BG, darkcolor=FIELD_BG, arrowcolor=TEXT, padding=2)
    style.map("TCombobox", bordercolor=[("focus", ACCENT), ("active", ACCENT)],
              fieldbackground=[("readonly", FIELD_BG)], background=[("active", HOVER_BG)],
              selectbackground=[("readonly", FIELD_BG)], selectforeground=[("readonly", TEXT)])
    root.option_add("*TCombobox*Listbox.background", FIELD_BG)
    root.option_add("*TCombobox*Listbox.selectBackground", PRESSED_BG)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    style.configure("TRadiobutton", background=WINDOW_BG, indicatorbackground=FIELD_BG,
                    indicatorforeground=ACCENT, bordercolor=BORDER)
    style.map("TRadiobutton", background=[("active", WINDOW_BG)],
              indicatorbackground=[("pressed", PRESSED_BG), ("active", HOVER_BG)])
    style.configure("TLabelframe", background=WINDOW_BG, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=WINDOW_BG, foreground=TEXT)
    style.configure("Treeview", background=FIELD_BG, fieldbackground=FIELD_BG, foreground=TEXT,
                    bordercolor=BORDER, lightcolor=FIELD_BG, darkcolor=FIELD_BG, rowheight=20)
    style.map("Treeview", background=[("selected", PRESSED_BG)], foreground=[("selected", TEXT)])
    style.configure("Treeview.Heading", background=WINDOW_BG, foreground=TEXT, bordercolor=BORDER,
                    lightcolor=WINDOW_BG, darkcolor=WINDOW_BG, relief="flat")
    style.map("Treeview.Heading", background=[("active", HOVER_BG)])
    style.configure("TScrollbar", troughcolor=WINDOW_BG, background=SCROLL_THUMB, bordercolor=WINDOW_BG,
                    lightcolor=SCROLL_THUMB, darkcolor=SCROLL_THUMB, arrowcolor="#606060")
    style.map("TScrollbar",
              background=[("pressed", SCROLL_THUMB_PRESSED), ("active", SCROLL_THUMB_ACTIVE)],
              lightcolor=[("pressed", SCROLL_THUMB_PRESSED), ("active", SCROLL_THUMB_ACTIVE)],
              darkcolor=[("pressed", SCROLL_THUMB_PRESSED), ("active", SCROLL_THUMB_ACTIVE)])
    style.configure("TSeparator", background=BORDER)

    # classic tk の部品
    root.option_add("*Text.background", FIELD_BG)
    root.option_add("*Text.foreground", TEXT)
    root.option_add("*Text.relief", "flat")
    root.option_add("*Text.borderWidth", 0)
    root.option_add("*Text.highlightThickness", 1)
    root.option_add("*Text.highlightBackground", BORDER)
    root.option_add("*Text.highlightColor", ACCENT)
    root.option_add("*Text.selectBackground", PRESSED_BG)
    root.option_add("*Text.selectForeground", TEXT)
    root.option_add("*Text.inactiveSelectBackground", HOVER_BG)
    root.option_add("*Text.insertBackground", TEXT)
    root.option_add("*Canvas.background", PREVIEW_BG)
    root.option_add("*Canvas.highlightThickness", 0)
    root.option_add("*Toplevel.background", WINDOW_BG)
    # Checkbutton は classic tk を使う（clam の Checkbutton はチェックの印が「✕」になり、使えないように見えるため）
    root.option_add("*Checkbutton.background", WINDOW_BG)
    root.option_add("*Checkbutton.activeBackground", WINDOW_BG)
    root.option_add("*Checkbutton.foreground", TEXT)
    root.option_add("*Checkbutton.selectColor", FIELD_BG)
    root.option_add("*Checkbutton.highlightThickness", 0)
    root.option_add("*Checkbutton.borderWidth", 0)
    root.option_add("*Panedwindow.background", WINDOW_BG)
    root.option_add("*Panedwindow.sashRelief", "flat")
