"""VA Documentの画面（tkinter・ttk。仕様.md の4）。

・画面のまとめ役。部品（mixin）を混ぜて使う：エディターの操作（editor_ops.py。カーソルの上の ▼ は editor_mark.py、表の挿入と
  表のセルは table_ops.py）、確認表示（preview.py）、
  ファイルの操作（file_ops.py：開く・保存・閉じる・印刷）、AI 連携（ai_ops.py：仮名化・コピー・取り込み）。
・エディターは常に仮名（記号）で表示し、実名は確認表示で見る（2026-10-24 班長決定）。
・確認表示は、組んだ PDF（メモリの中で作る）のページを画像にして表示する。文章を一時ファイルに書かない。
・外部と通信しない。クリップボードは、利用者がボタンを押したときだけ使う。
"""
import os
import re
import time
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont, messagebox, ttk

from . import APP_NAME, __version__, config, ime, printing, theme, tooltip, vamd
from .ai_ops import AiMixin
from .doctypes import DOC_TYPES, PAGE_NUMBER_LABELS
from .document import (BULLET_MARK, CENTER_MARK, FOOTER_MARK, HEADER_MARK, HEADING_BUTTON_MARK, NUMBER_MARK,
                       PAGE_BREAK_MARK, RIGHT_MARK, SECTION_BREAK_MARK, TITLE_MARK, TOC_MARK)
from .dialogs import OptionsDialog
from .editor_ops import EditorMixin
from .file_ops import FileMixin
from .icons import IconSet
from .ribbon import Ribbon, labeled_rows
from .preview import PREVIEW_SCROLL_STEP, PreviewMixin
from .session import Session

VERSION_LABEL = "Ver" + __version__.replace(".", "")
REFRESH_DELAY_MS = 600
SASH_RESTORE_SECONDS = 1.5   # 起動から、確認表示の幅を置き直す間（秒）
# 既定の AI への指示が新しくなったときの知らせ（書き換えられた指示を使っている人に、起動のときに一度だけ。2026-10-28 班長決定）
PROMPT_UPDATED_NOTICE = ("この版で、AI への指示の既定の文が新しくなりました。いまは、ユーザーによって書き換えられた指示を"
                         "使っているため、新しい既定の文は使われていません。オプションの［確認・修正］で、新しい既定の文と"
                         "見比べてください。［既定に戻す］を押すと、新しい既定の文に替わります。")


def _on_screen(geometry):
    """「幅x高さ+x+y」のウィンドウのタイトルの辺りが、今つながっている画面の上にあるか（外したモニターに
    出ないように）。Windows 以外では、Tk の画面の大きさの内にあるかで見る。"""
    m = re.match(r"(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)$", geometry)
    if not m:
        return False
    w, h = int(m.group(1)), int(m.group(2))
    x, y = int(m.group(3).lstrip("+")), int(m.group(4).lstrip("+"))     # 「+-1900」は左の画面
    if w < 300 or h < 200:
        return False
    px, py = x + min(w // 2, 200), y + 15
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        monitor_from_point = ctypes.windll.user32.MonitorFromPoint
        monitor_from_point.argtypes = [wintypes.POINT, wintypes.DWORD]
        monitor_from_point.restype = wintypes.HANDLE
        return bool(monitor_from_point(wintypes.POINT(px, py), 0))     # 0 = MONITOR_DEFAULTTONULL
    return 0 <= px and 0 <= py


def _icon_photos(path):
    """アイコンのファイル（.ico）から、大きさの違う画像（大きい順）を作る。作れなければ空のリスト。"""
    try:
        import io
        from PIL import Image
        photos = []
        with Image.open(path) as im:
            for size in sorted(im.info.get("sizes", []), reverse=True):
                if size[0] not in (256, 48, 32, 16):
                    continue
                im.size = size
                buf = io.BytesIO()
                im.convert("RGBA").save(buf, format="PNG")
                photos.append(tk.PhotoImage(data=buf.getvalue()))
        return photos
    except Exception:
        return []


def window_icon_path():
    """アイコン（assets/VA_Document.ico）の場所。exe（PyInstaller）では展開先に入れたもの（VA mints と同じ）。"""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    else:
        base = Path(__file__).resolve().parents[2]
    return base / "assets" / "VA_Document.ico"


class MainWindow(EditorMixin, PreviewMixin, FileMixin, AiMixin, tk.Tk):
    """メインの画面。エディターの操作（editor_ops）・確認表示（preview）・ファイルの操作（file_ops）・
    AI 連携（ai_ops）の部品を混ぜて使う。"""

    def __init__(self, cfg=None, open_path=None):
        super().__init__()
        theme.apply_theme(self)
        self.cfg = cfg or config.load()
        # オプションのエディターの書体・字の大きさ・行の間隔（2026-10-24 班長指示）
        theme.set_editor_prefs(self.cfg.editor_font_family, self.cfg.editor_font_size, self.cfg.editor_line_spacing_pt)
        self.session = Session(self.cfg)
        self._refresh_job = None
        self._preview_doc = None
        self._layout_warning = ""       # 状態の欄に出している、組んだときの知らせ（ヘッダーが本文に重なるなど）
        self._preview_page = 0
        self._page_tops = []
        self._sash_target = None        # 起動したときに戻す左右の境目の位置（_restore_window）
        self._pdf_name_text = ""        # プレビューの上の PDF の名前（入りきらないときは、省いて出す）
        self._loading = False
        self._last_printer = ""         # 前に印刷したプリンター（起動している間だけ覚える）
        self.geometry("1500x900")
        self._normal_geometry = None
        # ウィンドウ・タスクバーのアイコン（exe のアイコンは、PyInstaller の spec で別に埋め込む）。
        # 見つからない・読めないときは既定のまま（起動を妨げない）
        icon = window_icon_path()
        if icon.exists():
            try:
                if os.name == "nt":
                    self.iconbitmap(default=str(icon))
                # ウィンドウ自身にも大小のアイコンを付ける（タスクバー・Alt+Tab が、このアイコンを使う）
                self._icon_images = _icon_photos(icon)
                if self._icon_images:
                    self.iconphoto(True, *self._icon_images)      # これから作るウィンドウ（確認画面など）にも
                    self.iconphoto(False, *self._icon_images)     # このウィンドウ自身に
            except tk.TclError:
                pass
        self.minsize(900, 600)
        # ボタンのアイコン（Fluent UI System Icons。作れなくても、字のボタンのまま使える）。リボンを作る前に用意する
        try:
            self.icons = IconSet(self)
        except Exception:
            self.icons = None
        self._build()
        self._restore_window()
        # ボタンにマウスを重ねると説明を出す（アイコンだけのボタンの字を消す前に付ける）
        self._tooltips = tooltip.attach(self)
        # リボンの外のボタン（［印刷］［パスをコピー］など）にアイコンを付ける
        if self.icons is not None:
            try:
                self.icons.decorate(self)
            except Exception:
                pass
        self._load_text("")
        self._update_title()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._focus_job = None
        self._checking_outside = False
        self._declined_stamp = None
        self.bind("<FocusIn>", self._on_focus_in)
        self._find_dialog = None
        self._bind_keys()
        # エクスプローラーからファイルを落として開く（ウィンドウの中の左右の枠・確認表示・エディター。2026-10-28 班長指示）
        self.file_drop = self._init_file_drop([self.panes, self.canvas, self.text])
        if open_path:
            self.after(100, lambda: self.open_path(Path(open_path)))
        self.after(300, self.notify_prompt_update)

    def notify_prompt_update(self):
        """ユーザーによって書き換えられた AI への指示を使っていて、書き換えた後に既定の指示が新しくなったときに、
        一度だけ知らせる（2026-10-28 班長決定）。知らせたら True。"""
        if not self.session.prompt or self.cfg.ai_prompt_base == vamd.PROMPT_SHA256:
            return False
        self.cfg.ai_prompt_base = vamd.PROMPT_SHA256
        config.save(self.cfg)
        messagebox.showinfo(APP_NAME, PROMPT_UPDATED_NOTICE, parent=self)
        return True

    # ======================================================================
    # ショートカットキー（2026-10-23 班長指示：Word と同じキー）
    # ======================================================================

    # Tk のエディターがもともと持つ Emacs 風のキー（Word にない働き）。外す
    TK_EMACS_KEYS = ("<Control-Key-d>", "<Control-Key-h>", "<Control-Key-i>", "<Control-Key-k>", "<Control-Key-o>",
                     "<Control-Key-t>", "<Control-Key-space>", "<Control-Shift-Key-space>", "<Meta-Key-b>",
                     "<Meta-Key-d>", "<Meta-Key-f>", "<Meta-Key-less>", "<Meta-Key-greater>",
                     "<Meta-Key-BackSpace>", "<Meta-Key-Delete>")

    def _bind_keys(self):
        for seq in self.TK_EMACS_KEYS:
            self.text.bind_class("Text", seq, "")

        # Mac では、Ctrl に加えて Command（⌘）でも同じ働きにする（Mac のふつうのキー。2026-10-25）
        mods = ("Control", "Command") if self.tk.call("tk", "windowingsystem") == "aqua" else ("Control",)

        def key(letter, command, mac=True):
            # Caps Lock のときも効くよう、大文字・小文字の両方に付ける。このウィンドウの中だけで効く
            # （mac が偽なら Command には付けない。Command+H は Mac で「隠す」）
            for mod in (mods if mac else ("Control",)):
                for k in (letter, letter.upper()):
                    self.bind(f"<{mod}-Key-{k}>", lambda e: (command(), "break")[1])
        key("o", self.on_open)
        key("s", self.on_save)
        key("p", self.on_print)
        key("f", lambda: self.on_find(False))
        key("h", lambda: self.on_find(True), mac=False)
        key("e", lambda: self.on_align(CENTER_MARK))
        key("r", lambda: self.on_align(RIGHT_MARK))
        key("b", self.on_bold)
        # 蛍光ペンは Word と同じ Ctrl+Alt+H（Ctrl+H の置換より細かい指定なので、こちらが先に効く）
        for k in ("h", "H"):
            self.bind(f"<Control-Alt-Key-{k}>", lambda e: (self.on_highlight(), "break")[1])
        # 次のキーは、エディターのもとの働き（改行・選択を広げる）より先に受ける
        for mod in mods:
            self.text.bind(f"<{mod}-Return>", lambda e: (self.on_line_mark(PAGE_BREAK_MARK), "break")[1])
        # インデント（Ctrl+I。付ける・外す。エディターのもとの働きはタブを入れる）。2026-10-24 班長指示
        for mod in mods:
            for k in ("i", "I"):
                for widget in (self, self.text):
                    widget.bind(f"<{mod}-Key-{k}>", lambda e: (self.on_indent(), "break")[1])
        # 見出しの行を選んで Enter を押すと、同じ段の見出しの前の空行をそろえる（2026-10-28 班長決定。
        # editor_ops.on_editor_return。Ctrl+Enter〔改ページ〕は上で受けるので、ここには来ない）
        self.text.bind("<Return>", self.on_editor_return)
        # 表の中の Tab・Shift+Tab は、次・前のセルへ動く（2026-10-31 班長決定。table_ops.on_table_tab）
        self.text.bind("<Tab>", lambda e: self.on_table_tab(1))
        self.text.bind("<Shift-Tab>", lambda e: self.on_table_tab(-1))
        # Ctrl+Shift+V は、表にせず字のまま貼る（2026-10-31 班長決定）
        for mod in mods:
            for k in ("v", "V"):
                self.text.bind(f"<{mod}-Shift-Key-{k}>", lambda e: self.on_paste_plain())
        self.text.bind("<Alt-Shift-Left>", lambda e: (self.on_outline(-1), "break")[1])
        self.text.bind("<Alt-Shift-Right>", lambda e: (self.on_outline(1), "break")[1])
        for seq in ("<Control-Shift-Key-N>", "<Control-Shift-Key-n>"):
            self.bind(seq, lambda e: (self.on_plain(), "break")[1])

    # ======================================================================
    # 部品
    # ======================================================================

    def _build(self):
        """上にリボン（ウィンドウの幅いっぱい。Word や PDF のツールと同じ）、その下の左にプレビュー、右に入力欄を置く
        （2026-10-30 班長決定。それまでは、左のプレビューをウィンドウの上下いっぱいに置き、リボンは右の入力欄の上に
        置いていた。リボンが右の構文ファイルの名前の下にあり、PDF にも関わる「ファイル」の組が、構文ファイルだけの
        操作に見えたため）。左右の上には、それぞれのファイルの名前と、そのファイルの操作のボタンを置く。"""
        self._build_ribbon(self)
        self.panes = panes = tk.PanedWindow(self, orient="horizontal", sashwidth=6, bd=0)
        panes.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        # 左：プレビュー
        self._preview_pane = preview = ttk.Frame(panes)
        self._build_preview(preview)
        panes.add(preview, minsize=300, width=620, stretch="always")
        # 右：入力欄。下の部品から順に置く（入力欄が残りの高さを使う）
        self._work_pane = work = ttk.Frame(panes)
        panes.add(work, minsize=560, stretch="always")
        self._build_name_row(work)
        self.status = ttk.Label(work, style="Note.TLabel", padding=(4, 4, 0, 0))
        self.status.pack(side="bottom", fill="x")
        self._build_dictionary_list(work)
        self._build_editor(work)

    def _build_preview(self, preview):
        """プレビュー（PDF の名前・［印刷］・ページの番号、ページを並べる canvas）。ページはいつも欄の幅に合わせ、
        ページ送り・表示倍率のボタンは置かない（ページは、エディターのカーソル・ホイール・スクロールバーで送る。
        2026-10-30 班長決定）。"""
        # プレビューの上に PDF のファイル名を出し（2026-10-24 班長指示）、そのすぐ右に［印刷］を置く（右の構文ファイルの
        # 名前と［パスをコピー］と同じ形。2026-10-30 班長決定。それまではページ送りの段の右端）。行の右端にページの番号
        # （見ているページ / 全部のページ）。番号を先に置き、名前が長いときに押し出されないようにする
        self._pdf_name_row = row = ttk.Frame(preview)
        row.pack(fill="x")
        self.page_label = ttk.Label(row, style="Note.TLabel", width=9, anchor="e", padding=(0, 0, 0, 4))
        self.page_label.pack(side="right")
        self.pdf_name_label = ttk.Label(row, style="Note.TLabel", anchor="w", padding=(0, 0, 0, 4))
        self.pdf_name_label.pack(side="left")
        self._pdf_name_tip = tooltip.Tooltip(self.pdf_name_label, "")      # 省いたときだけ、名前の全体を出す
        # 実際のサイズで印刷する（2026-10-23 班長決定）
        self.print_button = ttk.Button(row, text="印刷", style="Small.TButton", command=self.on_print,
                                       state="normal" if printing.available() else "disabled")
        self.print_button.pack(side="left", padx=(8, 0), pady=(0, 4))
        row.bind("<Configure>", lambda e: self._fit_pdf_name(), add="+")
        holder = ttk.Frame(preview)
        holder.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(holder, yscrollincrement=PREVIEW_SCROLL_STEP)
        self._preview_yscroll = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_yscroll)
        self._preview_yscroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._layout_pages())
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-3 if e.delta > 0 else 3, "units"))
        # 確認表示をクリックすると、その字の位置にエディターのカーソルを動かす（2026-10-23 班長指示）
        self.canvas.bind("<Button-1>", self.on_preview_click)

    def _build_name_row(self, work):
        """エディターの最上段：構文ファイルの名前と［パスをコピー］。"""
        # 構文ファイルの名前は、エディターのすぐ上に、プレビューの上の PDF のファイル名と高さをそろえて出す（2026-10-24
        # 班長指示。どちらの行にも同じ大きさのボタンがあるので、高さは自然にそろう）。名前の右に［パスをコピー］（構文
        # ファイルのフルパスをコピーする。Claude Code に「このファイルを直して」と渡す、Claude の添付の画面の「ファイル名」
        # の欄に貼る、などに使う。2026-10-24 班長指示）
        name_row = ttk.Frame(work)
        name_row.pack(fill="x")
        self.doc_id_label = ttk.Label(name_row, style="Note.TLabel", anchor="w", padding=(4, 0, 0, 4))
        self.doc_id_label.pack(side="left")
        self.copy_path_button = ttk.Button(name_row, text="パスをコピー", style="Small.TButton", command=self.on_copy_path)
        self.copy_path_button.pack(side="left", padx=(8, 0), pady=(0, 4))

    def _build_ribbon(self, parent):
        """リボン。ボタンは Word のリボンと同じ形にする（組の名前を下に、大小のボタン、重ねたときだけ枠。2026-10-24
        班長指示）。組の順は、ファイル・レイアウト・書式・挿入・編集・表示。大きいボタンは AI 連携の［選択範囲を仮名化］
        （2026-10-24 班長指示）と、幅があるときの［開く］［保存］［見出し］（2026-10-30 班長指示）。「AI 連携」の組は、ほかの組の流れから外し、白い地を枠で囲んでウィンドウの右上に置く（AI に渡す・
        取り込む操作だけの組であることを示す。ほかの組が折り返しても、右上から動かない。2026-10-30 班長決定）。"""
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=8, pady=(8, 0))
        # 囲みを先に置く（ウィンドウが狭いときは、ほかの組の側が縮んで折り返す）
        box = ttk.Frame(top, style="Border.TFrame", padding=1)
        box.pack(side="right", anchor="n", pady=(0, 4))
        self.ai_ribbon = Ribbon(box, self.icons, boxed=True)
        self.ai_ribbon.pack()
        self.ribbon = rb = Ribbon(top, self.icons)
        # リボンの下に境界線は引かない（上にないので、下だけだと釣り合わない。2026-10-24 班長指示）
        rb.pack(side="left", fill="x", expand=True, anchor="n", pady=(0, 4))
        # ボタンのアイコンは、ボタンの字から icons.BUTTON_ICONS で引く（ribbon.py）
        # ［開く］［保存］［見出し］は、リボンが1段に入りきる幅があれば大きいボタンにする（入らなければ、折り返す前に
        # 小さくする。2026-10-30 班長指示。ribbon.py）
        g = rb.group("ファイル")
        g.small("開く", self.on_open, grow=True)
        # ［保存］は、いつも同じ見た目にする（保存していない変更があるときの青い枠は、2026-10-26 に外した。班長決定。
        # 保存していない変更は題の「＊」で示し、閉じる・開く・印刷・コピーの前に保存する〔尋ねる〕）
        self.save_button = g.small("保存", self.on_save, grow=True)
        # ［閉じる］は今の文書を閉じて新しい文書にする（VA Document は終わらない）。［オプション］は構文ファイルの
        # 保存場所とエディターの見た目（2026-10-24 班長指示）
        g.small("閉じる", self.on_close_document)
        # 過去の文書を使い回す［コピーとして開く］［名前を付けて保存］は置かない（2026-10-25 班長決定。仕様.md の9.4）
        g.small("オプション", self.on_options)
        # 文書の種類・ページ番号の選択欄と、行番号・番号1字のチェックは「レイアウト」の組、文字列に記号を付けるボタンは
        # 「書式」の組にする（2026-10-25 班長指示で1つの「書式」の組から分け、2026-10-27 班長指示で［見出し］［箇条書き］
        # ［段落番号］を「スタイル」から「書式」の左端の列に移した）。組の名前は、見出しなどを移した後の中身に合わせて、
        # 「スタイル」から Word のタブの名前の「レイアウト」に改めた（行番号・余白などのページ設定がある。挿入・表示と
        # 同じくタブの名前を使う。2026-10-27 班長決定）。選択欄の左端をそろえる。［左］は置かない。
        # 同じボタンをもう一度押すと解除する（2026-10-23・24 班長指示）
        g = rb.group("レイアウト")
        frame, (self.doc_type_box, self.page_number_box) = labeled_rows(g.body, [
            ("文書の種類", lambda m: ttk.Combobox(m, state="readonly", width=16,
                                                values=[d.label for d in DOC_TYPES.values()])),
            ("ページ番号", lambda m: ttk.Combobox(m, state="readonly", width=16,
                                                values=list(PAGE_NUMBER_LABELS.values())))])
        # 行番号は、ページ番号の選択欄の下に置くチェックで付ける（VA公用文のセットアップと同じく、ページ番号と並べる。
        # 内容証明では付けない。2026-10-24 班長指示）。［番号1字］を足したので、右ではなく選択欄の左端にそろえる
        # （2026-10-26 班長了承）
        self.line_numbers_var = tk.BooleanVar(value=False)
        self.line_numbers_check = tk.Checkbutton(frame, text="行番号", variable=self.line_numbers_var,
                                                 command=self.on_settings_changed)
        self.line_numbers_check.grid(row=2, column=1, sticky="w", pady=1)
        # 見出し番号を全角1字の幅に縮めるチェック（VA疑似アウトラインの「数字を全角1文字扱いにする」。複合見出しの
        # 上下の字をそろえるため。2026-10-26 班長指示）。行番号と同じ行の、選択欄の名前の列に置く（選択欄の下に並べると詰まる）。契約書1・技術文書では使えない
        self.one_width_var = tk.BooleanVar(value=False)
        self.one_width_check = tk.Checkbutton(frame, text="番号1字", variable=self.one_width_var,
                                              command=self.on_settings_changed)
        self.one_width_check.grid(row=2, column=0, sticky="w", pady=1)
        g.block(frame)
        self.doc_type_box.bind("<<ComboboxSelected>>", self.on_settings_changed)
        self.page_number_box.bind("<<ComboboxSelected>>", self.on_settings_changed)
        # 「書式」の組：左端の列に［見出し］［箇条書き］［段落番号］を上から順に置き（見出しは ## で付け、レベルは
        # エディターで # の数を直す。2026-10-25 班長指示。2026-10-27 に「スタイル」〔今の「レイアウト」〕から移した）、その右の列に
        # ［太字］［傍点］［均等割付］を上から順に置き（2026-10-24 班長指示）、その右に配置のボタン
        g = rb.group("書式")
        for label, mark in (("見出し", HEADING_BUTTON_MARK), ("箇条書き", BULLET_MARK), ("段落番号", NUMBER_MARK)):
            g.small(label, lambda m=mark: self.on_paragraph_kind(m), grow=label == "見出し")
        g.small("太字", self.on_bold)
        g.small("傍点", self.on_dots)
        g.small("均等割付", self.on_distribute)
        for label, mark in (("表題", TITLE_MARK), ("中央", CENTER_MARK), ("右", RIGHT_MARK)):
            g.small(label, lambda m=mark: self.on_align(m))
        # ［インデント］は配置のボタンの右の列の一番上に置く（2026-10-24 班長指示で［字下げ］の下に置いていたが、
        # 2026-10-28 班長決定で［字下げ］をなくした。字下げは行頭の全角空白で書く）
        g.small("インデント", self.on_indent)
        # ［ヘッダー］は、選んだ行の行頭に [HEADER] を付け外しする。配置のボタンと同じく行頭の記号を付け外しするので、
        # ［インデント］の下に置く（2026-10-25 班長指示）。［フッター］は［ヘッダー］の下に置き、行頭に [FOOTER] を付け外し
        # する（2026-10-25 にはボタンを置かず手で書くとしたが、2026-11-03 班長指示で足した）
        g.small("ヘッダー", lambda: self.on_area(HEADER_MARK))
        g.small("フッター", lambda: self.on_area(FOOTER_MARK))
        # 1行あけるのは、エディターの空の行で行う（Word と同じ。［空行］は置かない。2026-10-23 班長決定）
        g = rb.group("挿入")
        for label, mark in (("改ページ", PAGE_BREAK_MARK), ("セクション区切り", SECTION_BREAK_MARK),
                            ("目次", TOC_MARK)):   # 載せる見出しのレベルは手で直す（2026-10-24）
            g.small(label, lambda m=mark: self.on_line_mark(m))
        # ［表］：空の表（マークダウンの表）を入れる。表の中で押すと、列の追加などのメニューを出す。Excel・Word の表の
        # コピーは Ctrl+V で表になる（2026-10-31 班長決定）。［表］［画像］も、［開く］などと同じく、幅があれば大きい
        # ボタンにする（2026-11-03 班長指示）
        self.table_button = g.small("表", self.on_table, grow=True)
        # ［画像］：画像ファイルを選んで [IMAGE n]{幅} の行を入れる。クリップボードの画像は Ctrl+V（Win+V も）で入れる
        # （2026-10-29 班長決定）。画像の行で押すと、差し替え・幅のメニューを出す（2026-10-31 班長決定）
        self.image_button = g.small("画像", self.on_image, grow=True)
        # 見出しの前の空行は、ボタンを置かず、見出しの行を選んで Enter を押して同じ段にそろえる（2026-10-28 班長決定）
        # 検索・置換は「編集」の組にする（Word のリボンのホームのタブと同じ名前。2026-10-23 班長決定）
        g = rb.group("編集")
        g.small("検索", lambda: self.on_find(False))
        g.small("置換", lambda: self.on_find(True))
        # 蛍光ペンは「表示」の組にして、「編集」の右に置く（確認表示だけに出し、PDF・印刷には出さない。2026-10-24 班長指示）
        g = rb.group("表示")
        g.small("蛍光ペン", self.on_highlight)
        # 仮名化・コピー・貼り付けは一連の操作なので、1つの組にする（2026-10-23 班長指示）。［選択範囲を仮名化］は
        # 大きいボタン、［コピー］［貼り付け］はその右に積む小さいボタンにする（2026-10-24・25 班長指示）
        g = self.ai_ribbon.group("AI 連携")
        self.register_button = g.large("選択範囲を\n仮名化", self.on_register)
        g.small("コピー", self.on_copy_vamd)
        g.small("貼り付け", self.on_import)
        # 組の大きさが決まってから（画面に出たとき・大きさが変わったとき）高さをそろえる。［開く］などを大きくした・
        # 小さくしたときは、ほかの組の高さが変わるので、それも待ってそろえ直す
        self.ai_ribbon.bind("<Configure>", lambda e: self._align_ribbon_heights(), add="+")
        rb.bind("<Configure>", lambda e: self.after_idle(self._align_ribbon_heights), add="+")

    def _align_ribbon_heights(self):
        """「AI 連携」の囲みと、ほかの組の高さをそろえる（組の名前の下端をそろえる）。囲みの枠と余白の分（上下で
        2 画素ずつ）を差し引く。"""
        frame = 4
        main = max((g.winfo_reqheight() for g in self.ribbon.groups), default=0)
        ai = max((g.winfo_reqheight() for g in self.ai_ribbon.groups), default=0)
        height = max(main, ai + frame)
        if height != self.ribbon._min_height:
            self.ribbon.set_min_height(height)
            self.ai_ribbon.set_min_height(height - frame)

    def _build_dictionary_list(self, work):
        """仮名化した語の一覧（エディターの下。下の状態の欄の上）。"""
        bottom = ttk.Frame(work, padding=(4, 6, 0, 0))
        bottom.pack(side="bottom", fill="x")
        # 一覧の題の右に、変え方を添える（［解除］［変更］のボタンは置かず、行のダブルクリックで開く変更の画面で
        # 変える・解除する。画面を簡潔にし、仮名化の解除を手軽にしすぎないため。2026-10-27 班長指示）
        title_row = ttk.Frame(bottom)
        title_row.pack(anchor="w")
        ttk.Label(title_row, text="仮名化する語").pack(side="left")
        ttk.Label(title_row, text="（ダブルクリックで編集）", style="Note.TLabel").pack(side="left")
        # 同じ案件のほかの文書（書式付きファイル・構文ファイル）から、仮名化した語を今の一覧に足す（2026-10-29 班長決定）
        ttk.Button(title_row, text="ファイルから読み込む", style="Small.TButton", command=self.on_load_entries
                   ).pack(side="left", padx=(8, 0))
        tree_row = ttk.Frame(bottom)
        tree_row.pack(fill="x")
        self.tree = ttk.Treeview(tree_row, columns=("token", "word", "kind"), show="headings", height=4,
                                 selectmode="browse")
        for col, label, width in (("token", "記号", 120), ("word", "元の語", 300), ("kind", "種別", 80)):
            self.tree.heading(col, text=label, anchor="w")
            self.tree.column(col, width=width, anchor="w", stretch=col == "word")
        tys = ttk.Scrollbar(tree_row, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tys.set)
        self.tree.pack(side="left", fill="x", expand=True)
        tys.pack(side="left", fill="y")
        # 行をダブルクリックすると、その語の記号と元の語を変える画面を開く（2026-10-25 班長決定。登録した語の誤りの
        # 訂正と、文書をまたいでそろえる記号の付け替え。画面の下の［解除］で仮名化を解除する。2026-10-27 班長指示。
        # ［すべて解除］は、押すと構文ファイルが実名だらけになるので置かない）
        self.tree.bind("<Double-Button-1>", lambda e: self.on_edit_entry() if self.tree.identify_row(e.y) else None)

    def _build_editor(self, work):
        """エディター（入力欄）と、記号・太字・検索などの色付けの設定。"""
        # エディターは常に仮名（記号）で表示し、実名は確認表示で見る（実名・仮名の切り替えはなくした。2026-10-24 班長決定）
        editor = ttk.Frame(work, padding=(4, 0, 0, 0))
        editor.pack(fill="both", expand=True)
        self.text = tk.Text(editor, wrap="char", undo=True, font=theme.editor_font(self), padx=6, pady=6,
                            **theme.editor_spacing(self))
        self._init_editor_mark()        # カーソルの上の ▼（2026-10-26 班長決定）
        ys = ttk.Scrollbar(editor, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=lambda first, last: (ys.set(first, last), self._schedule_editor_mark()))
        ys.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("registered", background=theme.REGISTERED_BG)
        # 配置・改ページなどの記号（:=: など）は、確認表示の印と同じ青い字で示す（2026-10-23 班長指示）
        self.text.tag_configure("mark", foreground=theme.ACCENT)
        # 太字（**文字**）の字は、エディターでも太く示す（2026-10-24）
        family, size = theme.editor_font(self)
        self.text.tag_configure("bold", font=(family, size, "bold"))
        # 傍点（*文字*）の字は、エディターでは下線で示す（Tk の入力欄は字の上に点を描けないため）
        self.text.tag_configure("dots", underline=True)
        # 蛍光ペン（==文字==）の字は黄色の地で示す。仮名化した語・検索で見つけた字の地の色を優先する（下に置く）
        self.text.tag_configure("highlight", background=theme.HIGHLIGHT_BG)
        self.text.tag_lower("highlight")
        self.text.bind("<<Modified>>", self.on_text_modified, add="+")     # ▼ の置き直し（_init_editor_mark）を消さない
        # IME の入力中の文字を、エディターと同じ書体・大きさで表示する（2026-10-23 班長指摘）
        self.text.bind("<FocusIn>", lambda e: self.after_idle(self._fit_ime), add="+")
        # 貼り付け（Ctrl+V）は、仮名化した語を記号に置き換えて貼る（エディターは常に仮名。2026-10-24）
        self.text.bind("<<Paste>>", self._on_paste)
        # Ctrl+Z・Ctrl+Y は、仮名化の登録・解除も一緒に戻す（2026-11-01 班長決定）
        self.text.bind("<<Undo>>", self.on_undo)
        self.text.bind("<<Redo>>", self.on_redo)
        # エディターでカーソルを動かすと、その字のあるページを確認表示に出す（2026-10-23 班長指示）
        self._caret_job = None
        for seq in ("<KeyRelease>", "<ButtonRelease-1>"):
            self.text.bind(seq, lambda e: self._schedule_caret(), add="+")
        self.text.tag_configure("found", background=theme.FOUND_BG)
        self.text.tag_configure("found_current", background=theme.CURRENT_FOUND_BG, foreground=theme.CURRENT_FOUND_FG)
        # AI の回答で変わった段落の印（右端の青い線。Word の変更線と同じ考え方。左端では行頭のマークダウンの記号の
        # じゃまになるため、右端にする。2026-10-24 班長指示）
        self.text.tag_configure("changed", rmargin=theme.CHANGE_BAR_WIDTH, rmargincolor=theme.ACCENT)
        self.text.tag_lower("found", "sel")

    # ======================================================================
    # 入力欄
    # ======================================================================

    def _load_text(self, text):
        """入力欄の中身を入れ替える（実名の文章を渡す。エディターには、仮名化した語を記号に置き換えて入れる）。"""
        self._loading = True
        self.text.delete("1.0", "end")
        self.text.insert("1.0", self.session.dictionary.pseudonymize(text))
        self.text.edit_reset()
        self._undo_steps, self._redo_steps = [], []     # Ctrl+Z で戻せる仮名化の登録・解除（ai_ops.on_undo）
        self.text.edit_modified(False)
        self._loading = False
        self._sync_settings_boxes()
        self._refresh_dictionary()
        self._update_title()
        self.register_button.configure(state="normal")
        self.refresh()

    def raw_text(self):
        return self.text.get("1.0", "end-1c")

    def real_text(self):
        """実名の文章（エディターの記号を、仮名化した語に戻したもの。仮名化した語にない記号は、記号のまま）。"""
        return self.session.dictionary.restore(self.raw_text())[0]

    def on_text_modified(self, event=None):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if not self._loading:
            self._update_title()
            self.refresh(delay=True)

    def refresh(self, delay=False):
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
        if delay:
            self._refresh_job = self.after(REFRESH_DELAY_MS, self.refresh)
            return
        self._tokenize_editor()
        self._highlight()
        self._render_preview()

    def _fit_ime(self):
        family, size = theme.editor_font(self)
        if family != "TkFixedFont":
            ime.set_composition_font(self.text, family, size)

    # ======================================================================
    # 文書の設定・オプション・ウィンドウ
    # ======================================================================

    def on_settings_changed(self, event=None):
        labels = {d.label: d.key for d in DOC_TYPES.values()}
        pages = {v: k for k, v in PAGE_NUMBER_LABELS.items()}
        doc_type = labels[self.doc_type_box.get()]
        self.session.settings = vamd.Settings(doc_type, pages[self.page_number_box.get()], self.line_numbers_var.get(),
                                              self.one_width_var.get()).normalized()
        self._sync_settings_boxes()
        # 次に起動したときの新しい文書も、この設定で始める（2026-10-23 班長指示）
        self.cfg.remember_settings(self.session.settings)
        config.save(self.cfg)
        self._update_title()
        self.refresh()

    def _sync_settings_boxes(self):
        s = self.session.settings
        self.doc_type_box.set(self.session.doc_type.label)
        self.page_number_box.set(PAGE_NUMBER_LABELS[s.page_number])
        self.line_numbers_var.set(s.line_numbers)
        self.line_numbers_check.configure(state="normal" if s.allows_line_numbers() else "disabled")
        self.one_width_var.set(s.one_width)
        self.one_width_check.configure(state="normal" if s.allows_one_width() else "disabled")

    # ---------- ウィンドウの大きさ・位置（前回終了したときに戻す。2026-10-23 班長指示） ----------

    def _restore_window(self):
        cfg = self.cfg
        if cfg.window_geometry and _on_screen(cfg.window_geometry):
            self.geometry(cfg.window_geometry)
            self._normal_geometry = cfg.window_geometry
        if cfg.window_zoomed:
            try:
                self.state("zoomed")
            except tk.TclError:
                pass
        if cfg.preview_width > 0:
            # 左右の境目は、ウィンドウの大きさが決まってから置く。起動直後は大きさが何度か変わるので、
            # 起動から少しの間は、左右の欄の大きさが変わるたびに置き直す
            self._sash_target = cfg.preview_width
            self._sash_until = time.monotonic() + SASH_RESTORE_SECONDS
            # 左右の欄の中身の大きさが決まるときにも境目が動くので、左右それぞれの欄の大きさの変化でも置き直す
            for widget in (self.panes, self._preview_pane, self._work_pane):
                widget.bind("<Configure>", self._place_sash, add="+")
            self.after_idle(self._place_sash)
        self.bind("<Configure>", self._on_window_configure, add="+")

    def _place_sash(self, event=None):
        if self._sash_target is None or time.monotonic() > self._sash_until:
            self._sash_target = None
            return
        try:
            if self.panes.sash_coord(0)[0] != max(300, self._sash_target):
                self.panes.sash_place(0, max(300, self._sash_target), 0)
        except tk.TclError:
            pass

    def _on_window_configure(self, event=None):
        # 最大化していないときの大きさ・位置を覚えておく（最大化したまま閉じても、元の大きさに戻せるように）
        if event is not None and event.widget is self and self.state() == "normal":
            self._normal_geometry = self.geometry()

    def _remember_window(self):
        cfg = self.cfg
        try:
            zoomed = self.state() == "zoomed"
            cfg.window_zoomed = zoomed
            cfg.window_geometry = (self._normal_geometry if zoomed and self._normal_geometry else self.geometry())
            cfg.preview_width = self.panes.sash_coord(0)[0]
        except tk.TclError:
            pass
        # 文書の種類・ページ番号も覚える（次に起動したときの新しい文書は、この設定で始める。2026-10-23 班長指示）
        cfg.remember_settings(self.session.settings)

    def on_options(self):
        """オプション（構文ファイルの保存場所、エディターの書体・字の大きさ・行の間隔。2026-10-24 班長指示）。"""
        dlg = OptionsDialog(self, self.cfg, theme.editor_font_choices(self), config.FONT_SIZE_RANGE,
                            config.LINE_SPACING_RANGE, self.session.prompt or vamd.PROMPT, vamd.PROMPT)
        r = dlg.result
        if r is None:
            return
        old_folder = Path(self.cfg.vamd_folder)
        if Path(r["vamd_folder"]).resolve() != old_folder.resolve():
            # 今の文書は、これまでの場所の構文ファイルを使い続ける（新しい文書から、新しい場所に保存する）
            current = old_folder / vamd.file_name(self.session.doc_id)
            if self.session.vamd_file is None and current.exists():
                self.session.vamd_file = current
            self.cfg.vamd_folder = r["vamd_folder"]
        self.cfg.editor_font_family = r["font_family"]
        self.cfg.editor_font_size = r["font_size"]
        self.cfg.editor_line_spacing_pt = r["line_spacing"]
        if r["prompt"] is not None:
            # AI への指示：すべての文書に共通（2026-10-28 班長決定）。今の文書の保存してある構文ファイルの指示も書き直す。
            # ほかの文書は、開いて保存するときに書き直す
            custom = None if vamd.is_default_prompt(r["prompt"]) else r["prompt"]
            self.session.prompt = custom
            self.cfg.ai_prompt = custom or ""
            self.cfg.ai_prompt_base = vamd.PROMPT_SHA256 if custom else ""
            self.session.rewrite_prompt()
        config.save(self.cfg)
        self._apply_editor_prefs()
        self.status.configure(text="オプションを変えました。")

    def _apply_editor_prefs(self):
        """オプションのエディターの書体・字の大きさ・行の間隔を、エディターに当てる。"""
        theme.set_editor_prefs(self.cfg.editor_font_family, self.cfg.editor_font_size, self.cfg.editor_line_spacing_pt)
        family, size = theme.editor_font(self)
        self.text.configure(font=(family, size), **theme.editor_spacing(self))
        self.text.tag_configure("bold", font=(family, size, "bold"))
        self._fit_ime()

    def on_close(self):
        # 仮名化した語の一覧が消えることは確かめない（保存した文書は、開き直せば構文ファイルと PDF を突き合わせて
        # 作り直せる。保存していない変更は _confirm_discard で尋ねる。2026-10-27 班長指示）
        if not self._confirm_discard():
            return
        self._remember_window()
        config.save(self.cfg)
        if self._preview_doc is not None:
            self._preview_doc.close()
        self.destroy()

    def _update_title(self):
        name = self.session.pdf_path.name if self.session.pdf_path else "新しい文書"
        try:
            modified = self.session.is_modified(self.real_text())
        except Exception:
            modified = True
        self.title(f"{'＊' if modified else ''}{name} - {APP_NAME} {VERSION_LABEL}")
        # 確認表示の上に PDF、エディターの上に構文ファイルの名前と版を出す（2026-10-24 班長指示）。文書ID は
        # 構文ファイルの名前（<文書ID>.vamd）。保存するまではどちらもないので、そう書く
        s = self.session
        # 保存していない文書は、エディターが空なら「開かれていません」（起動したとき・閉じた後）、書いていれば
        # 「保存していません」（2026-10-24 班長指摘）
        none = "（開かれていません）" if not self.raw_text().strip() else "（保存していません）"
        self._pdf_name_text = (f"書式付き（PDF）ファイル：{s.pdf_path.name}" if s.pdf_path and s.version
                               else f"書式付き（PDF）ファイル：{none}")
        self._fit_pdf_name()
        # 版は画面に出さない（PDF と構文ファイルの組を確かめる内部の仕組み。古い回答の知らせなどで、必要なときだけ出す。
        # 2026-10-24 班長指示）
        self.doc_id_label.configure(text=f"構文（VAMD）ファイル：{s.vamd_path.name}"
                                    if s.version else f"構文（VAMD）ファイル：{none}")
        self.copy_path_button.configure(state="normal" if s.version else "disabled")

    def _fit_pdf_name(self):
        """PDF の名前が行に入りきらないときは、後ろを「…」で省き、マウスを重ねると全体を出す（［印刷］とページの番号を
        押し出さないように。2026-10-30）。行の幅がまだ決まっていないときは、省かない。"""
        text = self._pdf_name_text
        room = (self._pdf_name_row.winfo_width() - self.print_button.winfo_reqwidth()
                - self.page_label.winfo_reqwidth() - 16)
        shown = text
        if room > 1:
            font = tkfont.nametofont(ttk.Style(self).lookup("TLabel", "font") or "TkDefaultFont")
            if font.measure(text) > room:
                while shown and font.measure(shown + "…") > room:
                    shown = shown[:-1]
                shown += "…"
        if str(self.pdf_name_label.cget("text")) != shown:
            self.pdf_name_label.configure(text=shown)
        self._pdf_name_tip.text = text if shown != text else ""


APP_USER_MODEL_ID = "VBAAssets.VADocument.Source"


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        if not getattr(sys, "frozen", False):
            # python で起動したときも、タスクバーに VA Documentのアイコンを出す（python.exe のウィンドウとして
            # まとめられないようにする。2026-10-23 班長了承）。exe では、埋め込んだアイコンを使うので付けない
            # （インストーラーのショートカットとピン留めの扱いがずれないように）
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
            except Exception:
                pass
    path = sys.argv[1] if len(sys.argv) > 1 else None
    MainWindow(open_path=path).mainloop()


if __name__ == "__main__":
    main()
