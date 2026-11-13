"""確認の画面（種別の選択・記号と元の語の変更・外で書き換えられた・記号の元の語・内容証明・オプション・AI への指示・
印刷）。"""
import tkinter as tk
from tkinter import messagebox, ttk

from . import APP_NAME, theme
from .pseudonym import KINDS, NotRegistrable, letters_to_number, make_token, token_label, to_wide


class _Dialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.configure(background=theme.WINDOW_BG)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda e: self.cancel())

    def run(self):
        self.update_idletasks()
        parent = self.master
        x = parent.winfo_rootx() + max((parent.winfo_width() - self.winfo_reqwidth()) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - self.winfo_reqheight()) // 3, 0)
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        self.wait_window()

    def cancel(self):
        self.destroy()

    def buttons(self, ok_text, ok_command, cancel_text="やめる"):
        bar = ttk.Frame(self, padding=(12, 8, 12, 12))
        bar.pack(side="bottom", fill="x")
        ttk.Button(bar, text=cancel_text, command=self.cancel).pack(side="right")
        ok = ttk.Button(bar, text=ok_text, style="Accent.TButton", command=ok_command)
        ok.pack(side="right", padx=(0, 8))
        return bar


class _TokenFields:
    """種別と記号の字の欄（仮名化・一覧の変更の画面で使う）。記号の字は自動で入れず、利用者が必ず打つ（2026-10-25 班長決定。
    「自分の側はＡから、相手の側はＸから」・番号・漢字など、文書をまたいで同じ人に同じ記号を付けられる
    ように。英字・数字・漢字などを使え、字数の制限はない。はじめは英字を選ぶボタンだったが、同じ日に打ち込む欄に戻した）。"""

    def token_fields(self, body, dictionary, kind, letters, keep=None):
        self.dictionary, self.keep = dictionary, keep
        self.kind = tk.StringVar(value=kind)
        self.letters = tk.StringVar(value=letters)
        row = ttk.Frame(body)
        row.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Label(row, text="種別").pack(side="left", padx=(0, 8))
        for k in KINDS:
            ttk.Radiobutton(row, text=k, value=k, variable=self.kind).pack(side="left", padx=(0, 6))
        row = ttk.Frame(body)
        row.pack(anchor="w", fill="x", pady=(8, 0))
        ttk.Label(row, text="記号の字").pack(side="left", padx=(0, 8))
        self.letters_box = ttk.Entry(row, textvariable=self.letters, width=16)
        self.letters_box.pack(side="left")
        self.preview = ttk.Label(row, text="")
        self.preview.pack(side="left", padx=(12, 0))
        ttk.Label(body, text="英字・数字・漢字などを使えます（例：Ａ、１、甲）。", style="Note.TLabel"
                  ).pack(anchor="w", pady=(4, 0))
        self.used_label = ttk.Label(body, text="", style="Note.TLabel", wraplength=420, justify="left")
        self.used_label.pack(anchor="w", pady=(6, 0))
        self.kind.trace_add("write", lambda *a: self._show())
        self.letters.trace_add("write", lambda *a: self._show())
        self._show()

    def _show(self):
        kind, letters = self.kind.get(), self.letters.get().strip(" 　")
        self.preview.configure(text=f"記号：〔{kind}{to_wide(letters) or '？'}〕")
        mine = self.keep.token if self.keep is not None else None
        current = {e.token: e.word for e in self.dictionary.entries.values()}
        in_use, released = [], []
        # 英字の記号を Ａ・Ｂ…ＡＡ の順に先に、ほかの字の記号を後に並べる
        for label in sorted(self.dictionary.used[kind], key=lambda x: (letters_to_number(x) == 0, letters_to_number(x), x)):
            token = make_token(kind, label)
            if token == mine:
                continue
            if token in current:
                in_use.append(f"{token}（{current[token]}）")
            else:
                before = self.dictionary.released.get(token)
                released.append(f"{token}（{before}）" if before else token)
        # 記号ごとに改行する（Tk の折り返しは、記号の途中や括弧の中でも切れるため）
        lines = []
        if in_use:
            lines += ["この文書で使っている記号（使えません）："] + ["　" + x for x in in_use]
        if released:
            lines += ["解除した記号（別の語に付けるときは確かめます）："] + ["　" + x for x in released]
        self.used_label.configure(text="\n".join(lines) if lines else "この文書で、この種別の記号はまだ使っていません。")

    def target_word(self):
        """記号を付ける語（解除した記号を別の語に付けるかを確かめるため）。"""
        raise NotImplementedError

    def checked_token(self):
        """選んだ種別・記号の字で記号を作れるかを確かめ、(種別, 記号の字) を返す。作れなければ理由を知らせて None
        （画面は閉じない）。解除した記号を別の語に付けるときは、付けるかを尋ねる（2026-10-25 班長決定）。"""
        try:
            token = self.dictionary.check_token(self.kind.get(), self.letters.get(), keep=self.keep)
        except NotRegistrable as e:
            messagebox.showerror(APP_NAME, str(e), parent=self)
            self.letters_box.focus_set()
            return None
        if self.keep is None or token != self.keep.token:
            warning = self.dictionary.reuse_warning(token, self.target_word())
            if warning and not messagebox.askyesno(APP_NAME, warning, parent=self):
                self.letters_box.focus_set()
                return None
        return self.kind.get(), self.letters.get()


class RegisterDialog(_Dialog, _TokenFields):
    """仮名化する語の種別と記号の字を決める。result は (種別, 記号の字)。"""

    def __init__(self, parent, word, dictionary):
        super().__init__(parent, "仮名化")
        self.result = None
        self.word = word
        body = ttk.Frame(self, padding=(16, 14, 16, 4))
        body.pack(fill="both")
        ttk.Label(body, text=f"「{word}」を仮名化します。種別を選び、記号の字を入れてください。").pack(anchor="w")
        self.token_fields(body, dictionary, KINDS[0], "")
        self.buttons("仮名化する", self.ok)
        self.bind("<Return>", lambda e: self.ok())
        self.letters_box.focus_set()
        self.run()

    def target_word(self):
        return self.word

    def ok(self):
        self.result = self.checked_token()
        if self.result is not None:
            self.destroy()


# 変更の画面で［解除］を押したときの result
UNREGISTER = "unregister"


class EditDialog(_Dialog, _TokenFields):
    """仮名化した語の記号と元の語を変える（2026-10-25 班長決定）。result は (元の語, 種別, 記号の字)。
    画面の下の［解除］で仮名化を解除する（確かめてから。result は UNREGISTER。2026-10-27 班長指示で、一覧の横の
    ［解除］［変更］のボタンをやめ、この画面に移した）。"""

    def __init__(self, parent, entry, dictionary):
        super().__init__(parent, "記号・元の語の変更")
        self.result = None
        self.entry = entry
        body = ttk.Frame(self, padding=(16, 14, 16, 4))
        body.pack(fill="both")
        ttk.Label(body, text=f"{entry.token}（{entry.word}）の、元の語と記号を変えます。",
                  wraplength=420, justify="left").pack(anchor="w", pady=(0, 8))
        row = ttk.Frame(body)
        row.pack(anchor="w", fill="x")
        ttk.Label(row, text="元の語").pack(side="left", padx=(0, 8))
        self.word = tk.StringVar(value=entry.word)
        box = ttk.Entry(row, textvariable=self.word, width=36)
        box.pack(side="left", fill="x", expand=True)
        self.token_fields(body, dictionary, entry.kind, token_label(entry.token) or "", keep=entry)
        # 文ごとに改行する（Tk の折り返しは行頭の禁則を守らず、「AI」の後の空白でも切れるため）
        ttk.Label(body, text="元の語を直すと、文章の中のこの記号は、すべて新しい語になります（誤字の訂正など）。\n"
                  "記号を変えると、エディターの記号も変わります（前の書面と記号をそろえるときなど）。\n"
                  "AI の前の回答にある前の記号は、取り込むときに「仮名化する語の一覧にない記号」として知らせます。",
                  style="Note.TLabel", justify="left").pack(anchor="w", pady=(8, 0))
        bar = self.buttons("変える", self.ok)
        # ［解除］は、［変える］［やめる］から離して左端に置く
        ttk.Button(bar, text="解除", command=self.unregister).pack(side="left")
        self.bind("<Return>", lambda e: self.ok())
        box.select_range(0, "end")
        box.focus_set()
        self.run()

    def target_word(self):
        return self.word.get()

    def ok(self):
        token = self.checked_token()
        if token is not None:
            self.result = (self.word.get(), *token)
            self.destroy()

    def unregister(self):
        """仮名化を解除する（エディターの記号は元の語に戻る）。［いいえ］なら画面に戻る。"""
        e = self.entry
        if messagebox.askyesno(APP_NAME, f"「{e.word}」（{e.token}）の仮名化を解除しますか？\n"
                               "エディターの記号は、元の語に戻ります。", parent=self):
            self.result = UNREGISTER
            self.destroy()


class ChangedOutsideDialog(_Dialog):
    """構文ファイルが外で書き換えられたことを知らせ、どうするかを尋ねる。result は "import"・"overwrite"・None。"""

    def __init__(self, parent, at_save):
        super().__init__(parent, "構文ファイルが書き換えられています")
        self.result = None
        body = ttk.Frame(self, padding=(16, 14, 16, 4))
        body.pack(fill="both")
        msg = ("構文ファイル（VAMD）が、VA Documentの外で書き換えられています"
               "（テキストエディターで直した、AI の回答を上書き保存した、など）。\n")
        if at_save:
            msg += ("このまま保存すると、外で書き換えた中身は消えます。\n"
                    "［取り込む］：外で書き換えた中身をエディターに取り込んでから保存します（変わった段落は右の青い線で示します）。\n"
                    "［上書きする］：外で書き換えた中身を捨てて、エディターの文章で保存します。")
        else:
            msg += "外で書き換えた中身を、エディターに取り込みますか？（変わった段落は右の青い線で示し、Ctrl+Z で元に戻せます）"
        ttk.Label(body, text=msg, justify="left").pack(anchor="w")
        bar = ttk.Frame(self, padding=(12, 10, 12, 12))
        bar.pack(side="bottom", fill="x")
        ttk.Button(bar, text="やめる" if at_save else "取り込まない", command=self.cancel).pack(side="right")
        if at_save:
            ttk.Button(bar, text="上書きする", command=lambda: self.choose("overwrite")).pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="取り込む", style="Accent.TButton",
                   command=lambda: self.choose("import")).pack(side="right", padx=(0, 8))
        self.run()

    def choose(self, value):
        self.result = value
        self.destroy()


class MissingDialog(_Dialog):
    """元の語が求まらなかった記号の、元の語を利用者に尋ねる（仕様.md の7）。"""

    def __init__(self, parent, session, result):
        super().__init__(parent, "記号の元の語")
        self.answers = {}
        r = result.recovery
        head = ttk.Frame(self, padding=(12, 12, 12, 4))
        head.pack(fill="x")
        ttk.Label(head, text="次の記号の元の語が、PDF から求まりませんでした。分かるものは入力してください。\n"
                             "空のままにした記号は、記号のまま入力欄に入ります（後から［選択範囲を仮名化］で仮名化できます）。",
                  justify="left").pack(anchor="w")
        grid = ttk.Frame(self, padding=(12, 4))
        grid.pack(fill="both", expand=True)
        self.entries = {}
        for n, tok in enumerate(result.unresolved):
            ttk.Label(grid, text=tok).grid(row=n, column=0, sticky="w", padx=(0, 8), pady=2)
            e = ttk.Entry(grid, width=40)
            e.grid(row=n, column=1, sticky="we", pady=2)
            if tok in r.conflicts:
                best = max(r.conflicts[tok].items(), key=lambda kv: kv[1])[0]
                e.insert(0, best)
                ttk.Label(grid, style="Note.TLabel",
                          text="候補：" + "、".join(r.conflicts[tok])).grid(row=n, column=2, sticky="w", padx=(8, 0))
            self.entries[tok] = e
        self.buttons("決める", self.accept, "空のまま開く")
        self.run()

    def accept(self):
        self.answers = {tok: e.get() for tok, e in self.entries.items()}
        self.destroy()


class NaiyouDialog(_Dialog):
    """内容証明の字数・行数を超えた所を知らせ、保存するかを尋ねる（2026-10-24 班長指示）。ok が真なら保存する。"""

    def __init__(self, parent, problem):
        super().__init__(parent, "内容証明の字数・行数")
        self.ok = False
        body = ttk.Frame(self, padding=(16, 14, 16, 4))
        body.pack(fill="both")
        ttk.Label(body, text=problem.message() + "\n\nエディターのカーソルを、その行に動かしました。"
                             "このまま保存すると、内容証明として出せないことがあります。",
                  justify="left", wraplength=520).pack(anchor="w")
        bar = ttk.Frame(self, padding=(12, 10, 12, 12))
        bar.pack(side="bottom", fill="x")
        ttk.Button(bar, text="このまま保存する", command=self.accept).pack(side="right")
        stop = ttk.Button(bar, text="保存をやめて直す", style="Accent.TButton", command=self.cancel)
        stop.pack(side="right", padx=(0, 8))
        stop.focus_set()
        self.bind("<Return>", lambda e: self.cancel())
        self.run()

    def accept(self):
        self.ok = True
        self.destroy()


class LoadEntriesDialog(_Dialog):
    """［ファイルから読み込む］：読み込む仮名化した語を見せ、読み込むかを確かめる（2026-10-29 班長決定）。選んだファイルの
    名前（どの案件の文書かを見分ける手がかり）・足す語の一覧・今の一覧と同じ語の数・今の文章で記号に置き換わる所の数・作り直せなかった
    記号の数を出す。ok が真なら読み込む。"""

    def __init__(self, parent, loaded):
        super().__init__(parent, "仮名化する語を読み込む")
        self.ok = False
        body = ttk.Frame(self, padding=(16, 14, 16, 4))
        body.pack(fill="both", expand=True)
        plan = loaded.plan
        ttk.Label(body, text=f"次のファイルの文書から、仮名化する語を {len(plan.add)} 語読み込みます。\n"
                             f"　{loaded.pdf_path.name}\n"
                             "この文書と同じ案件のファイルかを、確かめてください。",
                  justify="left", wraplength=520).pack(anchor="w")
        row = ttk.Frame(body)
        row.pack(fill="both", expand=True, pady=(10, 0))
        tree = ttk.Treeview(row, columns=("token", "word", "kind"), show="headings", height=min(max(len(plan.add), 3), 12),
                            selectmode="none")
        for col, label, width in (("token", "記号", 120), ("word", "元の語", 300), ("kind", "種別", 80)):
            tree.heading(col, text=label, anchor="w")
            tree.column(col, width=width, anchor="w", stretch=col == "word")
        for e in sorted(plan.add, key=lambda e: (KINDS.index(e.kind), e.token)):
            tree.insert("", "end", values=(e.token, e.word, e.kind))
        bar = ttk.Scrollbar(row, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="left", fill="y")
        notes = []
        if plan.same:
            notes.append(f"この文書の一覧に同じ語・同じ記号であるもの {len(plan.same)} 語は、そのままにします。")
        notes.append(f"今の文章で記号に置き換わる所：{loaded.occurrences} か所（PDF の字は変わりません）。")
        if loaded.unrecovered:
            notes.append(f"元の語を作り直せなかった記号 {loaded.unrecovered} 個は、読み込みません。")
        ttk.Label(body, text="\n".join(notes), style="Note.TLabel", justify="left", wraplength=520
                  ).pack(anchor="w", pady=(8, 0))
        self.buttons("読み込む", self.accept)
        self.run()

    def accept(self):
        self.ok = True
        self.destroy()


class OptionsDialog(_Dialog):
    """オプション（構文ファイルの保存場所、エディターの書体・字の大きさ・行の間隔。2026-10-24 班長指示）。
    result は {"vamd_folder", "font_family", "font_size", "line_spacing", "prompt"}（prompt は直した AI への指示。
    直していなければ None。やめたら result が None）。"""

    def __init__(self, parent, cfg, font_choices, size_range, spacing_range, prompt, default_prompt):
        super().__init__(parent, "オプション")
        self.result = None
        self.size_range, self.spacing_range = size_range, spacing_range
        self.prompt, self.default_prompt, self.new_prompt = prompt, default_prompt, None
        body = ttk.Frame(self, padding=(16, 14, 16, 4))
        body.pack(fill="both", expand=True)
        box = ttk.Labelframe(body, text="構文ファイル（.vamd）の保存場所", padding=(10, 6))
        box.pack(fill="x")
        self.folder = tk.StringVar(value=cfg.vamd_folder)
        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.folder, width=60).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="参照", command=self.browse).pack(side="left", padx=(6, 0))
        # 注意書きは文ごとに改行する（Tk の折り返しは語の途中で切れるため）
        ttk.Label(box, style="Note.TLabel", justify="left",
                  text="共有フォルダも選べます（ほかの人と文書を共有するとき）。\n"
                       "このフォルダには構文ファイル（仮名化済み）だけを置き、書式付きファイル（PDF）や案件の資料（実名入り）は"
                       "置かないでください。\n"
                       "ほかの人が構文ファイルを開いて実名に戻すには、同じ文書の書式付きファイル（PDF）も必要です。").pack(anchor="w", pady=(6, 0))
        box = ttk.Labelframe(body, text="エディター", padding=(10, 6))
        box.pack(fill="x", pady=(10, 0))
        self.family = tk.StringVar(value=cfg.editor_font_family or "（既定）")
        self.size = tk.StringVar(value=str(cfg.editor_font_size))
        self.spacing = tk.StringVar(value=str(cfg.editor_line_spacing_pt))
        ttk.Label(box, text="書体").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Combobox(box, textvariable=self.family, state="readonly", width=20,
                     values=["（既定）"] + list(font_choices)).grid(row=0, column=1, sticky="w", pady=2)
        for r, (label, var, rng, unit) in enumerate((("字の大きさ", self.size, size_range, "ポイント"),
                                                     ("行の間隔", self.spacing, spacing_range,
                                                      "ポイント（行の上と下に足す間隔）")), start=1):
            ttk.Label(box, text=label).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=2)
            cell = ttk.Frame(box)
            cell.grid(row=r, column=1, sticky="w", pady=2)
            ttk.Spinbox(cell, textvariable=var, from_=rng[0], to=rng[1], width=5).pack(side="left")
            ttk.Label(cell, text=unit, style="Note.TLabel").pack(side="left", padx=(6, 0))
        ttk.Label(box, style="Note.TLabel", justify="left",
                  text="書体は、全角と半角の幅がそろうものから選べます。\n"
                       "書体・字の大きさ・行の間隔は、エディターの見た目だけで、PDF には関係しません。").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        box = ttk.Labelframe(body, text="AI への指示（構文ファイルの上の部分）", padding=(10, 6))
        box.pack(fill="x", pady=(10, 0))
        row = ttk.Frame(box)
        row.pack(fill="x")
        self.prompt_note = ttk.Label(row, style="Note.TLabel")
        self.prompt_note.pack(side="left")
        ttk.Button(row, text="確認・修正", command=self.edit_prompt).pack(side="right")
        self._show_prompt_state()
        self.buttons("OK", self.accept, "キャンセル")
        self.run()

    def _show_prompt_state(self):
        current = self.new_prompt if self.new_prompt is not None else self.prompt
        same = current.rstrip() == self.default_prompt.rstrip()
        self.prompt_note.configure(text="既定の指示を使っています。" if same else "ユーザーによって書き換えられた指示を使っています。")

    def edit_prompt(self):
        current = self.new_prompt if self.new_prompt is not None else self.prompt
        dlg = PromptDialog(self, current, self.default_prompt)
        if dlg.result is not None:
            self.new_prompt = dlg.result
            self._show_prompt_state()

    def browse(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory(parent=self, title="構文ファイルの保存場所", initialdir=self.folder.get(),
                                         mustexist=True)
        if folder:
            self.folder.set(folder)

    def accept(self):
        from pathlib import Path
        folder = self.folder.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showerror("オプション", "構文ファイルの保存場所のフォルダが見つかりません。", parent=self)
            return
        try:
            size, spacing = int(self.size.get()), int(self.spacing.get())
        except ValueError:
            messagebox.showerror("オプション", "字の大きさと行の間隔は、数字で入れてください。", parent=self)
            return
        if not (self.size_range[0] <= size <= self.size_range[1] and self.spacing_range[0] <= spacing <= self.spacing_range[1]):
            messagebox.showerror("オプション", f"字の大きさは {self.size_range[0]}〜{self.size_range[1]}、行の間隔は "
                                 f"{self.spacing_range[0]}〜{self.spacing_range[1]} の数字にしてください。", parent=self)
            return
        family = self.family.get()
        self.result = {"vamd_folder": folder, "font_family": "" if family == "（既定）" else family,
                       "font_size": size, "line_spacing": spacing, "prompt": self.new_prompt}
        self.destroy()


class PromptDialog(_Dialog):
    """AI への指示（構文ファイルの区切りの行より上の部分）を確かめ、直す（2026-10-24 班長指示）。
    result は直した指示（やめたら None）。"""

    def __init__(self, parent, prompt, default_prompt):
        super().__init__(parent, "AI への指示")
        self.result = None
        self.default_prompt = default_prompt
        head = ttk.Frame(self, padding=(12, 12, 12, 4))
        head.pack(fill="x")
        ttk.Label(head, justify="left",
                  text="構文ファイルの上に付ける、AI への指示です。今の文書と、これから作る文書に使います。\n"
                       "記号（〔人名Ａ〕など）や区切りの行を残すよう求める部分は、消さないでください。").pack(anchor="w")
        frame = ttk.Frame(self, padding=(12, 0))
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(frame, wrap="char", height=24, width=90, font=theme.editor_font(parent), padx=6, pady=6,
                            undo=True)
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.insert("1.0", prompt.rstrip("\n"))
        bar = self.buttons("OK", self.accept, "キャンセル")
        ttk.Button(bar, text="既定に戻す", command=self.reset).pack(side="left")
        self.run()

    def reset(self):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", self.default_prompt.rstrip("\n"))

    def accept(self):
        self.result = self.text.get("1.0", "end-1c").rstrip() + "\n"
        self.destroy()


class PrintDialog(_Dialog):
    """VA Document の「印刷」画面（プリンター・部数・ページ。2026-10-24 班長決定。Windows 11 の新しい印刷画面は、
    プレビューの欄に「このアプリは印刷プレビューをサポートしていません」と出て紛らわしいため）。
    右に印刷プレビューを置く（印刷するページを1枚ずつ、紙に出るものと同じ色〔字だけのページは灰色、画像のあるページは
    カラー。printing.page_is_color〕の1ページ全体で見せる。蛍光ペンと仮名化する語の色は、PDF・印刷と同じく付かない。
    2026-10-30 班長決定）。pdf_data は印刷する PDF（バイト列）。
    result は (プリンターの名前, DEVMODE〔プロパティで直さなければ None〕, 部数, ページ〔0 から〕のリスト)。やめたら None。"""

    PREVIEW_HEIGHT = 380    # 印刷プレビューのページの高さ（画素。画面の拡大率 100% のとき）

    def __init__(self, parent, pdf_data, printer_names, chosen, show_properties):
        from .pdfpages import PdfPages
        super().__init__(parent, "印刷")
        self.result = None
        self.doc = PdfPages(pdf_data)
        self.pages, self.show_properties = len(self.doc), show_properties
        pages = self.pages
        self.modes = {}             # プリンター → プロパティで直した設定
        self._build_preview()
        body = ttk.Frame(self, padding=(16, 14, 16, 4))
        body.pack(fill="both")
        box = ttk.Labelframe(body, text="プリンター", padding=(10, 6))
        box.pack(fill="x")
        self.printer = tk.StringVar(value=chosen if chosen in printer_names else
                                    (printer_names[0] if printer_names else ""))
        ttk.Combobox(box, textvariable=self.printer, values=printer_names, state="readonly", width=40).pack(
            side="left")
        ttk.Button(box, text="プロパティ", command=self.properties).pack(side="left", padx=(8, 0))
        box = ttk.Labelframe(body, text="印刷するページ", padding=(10, 6))
        box.pack(fill="x", pady=(10, 0))
        self.which = tk.StringVar(value="all")
        # 「プレビューのページ」は置かない（プレビューにページ送りがなく、見ているページを選ぶ場面がないため。1ページだけ
        # 刷るときは、番号を指定して印刷プレビューで確かめる。2026-10-30 班長決定）
        ttk.Radiobutton(box, text=f"すべて（{pages} ページ）", value="all", variable=self.which).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=1)
        ttk.Radiobutton(box, text="ページを指定", value="range", variable=self.which).grid(
            row=1, column=0, sticky="w", pady=1)
        self.range = tk.StringVar()
        entry = ttk.Entry(box, textvariable=self.range, width=20)
        entry.grid(row=1, column=1, sticky="w", padx=(6, 0))
        entry.bind("<FocusIn>", lambda e: self.which.set("range"))
        ttk.Label(box, text="例：1-3, 5", style="Note.TLabel").grid(row=1, column=2, sticky="w", padx=(6, 0))
        # ページの選び方を変えたら、印刷プレビューを、印刷する最初のページにする
        self.which.trace_add("write", lambda *a: self._show_page(reset=True))
        self.range.trace_add("write", lambda *a: self._show_page(reset=True))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text="部数").pack(side="left")
        self.copies = tk.StringVar(value="1")
        ttk.Spinbox(row, textvariable=self.copies, from_=1, to=99, width=5).pack(side="left", padx=(8, 0))
        ttk.Label(body, style="Note.TLabel", justify="left",
                  text="印刷プレビューのとおりに、A4 の実際の大きさで印刷します。\n"
                       "用紙のトレイ・両面などは、［プロパティ］で決めてください。").pack(anchor="w", pady=(10, 0))
        self.buttons("印刷", self.accept, "キャンセル")
        self.bind("<Return>", lambda e: self.accept())
        self._show_page(reset=True)
        self.run()

    def _build_preview(self):
        """右の印刷プレビュー（ページの絵と、印刷するページを送る［＜］［＞］）。左の欄より先に置く（ボタンの段は左の欄の下）。"""
        side = ttk.Frame(self, padding=(0, 14, 16, 12))
        side.pack(side="right", fill="y")
        ttk.Label(side, text="印刷プレビュー", style="Note.TLabel").pack(anchor="w")
        scale = max(1.0, self.winfo_fpixels("1i") / 96)
        page_w, page_h = self.doc.size(0)
        self._zoom = self.PREVIEW_HEIGHT * scale / page_h
        w, h = round(page_w * self._zoom), round(page_h * self._zoom)
        # 読めない指定のときに出す白い紙（絵の大きさを変えず、画面が伸び縮みしないように）
        self._blank = tk.PhotoImage(width=w, height=h)
        self._blank.put(theme.FIELD_BG, to=(0, 0, w, h))
        holder = ttk.Frame(side, style="Border.TFrame", padding=1)
        holder.pack(pady=(4, 6))
        self.page_view = tk.Label(holder, image=self._blank, compound="center", borderwidth=0,
                                  background=theme.FIELD_BG, foreground=theme.NOTE)
        self.page_view.pack()
        nav = ttk.Frame(side)
        nav.pack()
        self._prev = ttk.Button(nav, text="＜", style="Small.TButton", command=lambda: self._show_page(step=-1))
        self._prev.pack(side="left")
        self.page_note = ttk.Label(nav, width=18, anchor="center")
        self.page_note.pack(side="left")
        self._next = ttk.Button(nav, text="＞", style="Small.TButton", command=lambda: self._show_page(step=1))
        self._next.pack(side="left")
        self._shown = 0             # 印刷するページのうち、見せている順番（0 から）

    def _chosen_pages(self):
        """印刷するページ（0 から）のリスト。指定が読めなければ ValueError。"""
        from .printing import parse_pages
        if self.which.get() == "all":
            return list(range(self.pages))
        return parse_pages(self.range.get(), self.pages)

    def _show_page(self, step=0, reset=False):
        """印刷するページのうち、今の順番から step だけ送ったページを、印刷と同じ色で見せる。"""
        from .printing import page_is_color
        try:
            pages = self._chosen_pages()
        except ValueError:
            message = "ページを指定してください" if not self.range.get().strip() else "ページの指定を読めません"
            self.page_view.configure(image=self._blank, text=message)
            self.page_note.configure(text="")
            self._prev.configure(state="disabled")
            self._next.configure(state="disabled")
            return
        self._shown = 0 if reset else max(0, min(len(pages) - 1, self._shown + step))
        k = pages[self._shown]
        pix = self.doc.render(k, self._zoom, gray=not page_is_color(self.doc, k))
        self._page_image = tk.PhotoImage(data=pix.png())
        self.page_view.configure(image=self._page_image, text="")
        self.page_note.configure(text=f"{k + 1} ページ（{self._shown + 1} / {len(pages)}）")
        self._prev.configure(state="normal" if self._shown > 0 else "disabled")
        self._next.configure(state="normal" if self._shown < len(pages) - 1 else "disabled")

    def destroy(self):
        self.doc.close()
        super().destroy()

    def properties(self):
        name = self.printer.get()
        if not name:
            return
        try:
            mode = self.show_properties(int(self.wm_frame(), 16), name, self.modes.get(name))
        except Exception as e:
            messagebox.showerror("印刷", f"プリンターの設定の画面を開けませんでした。\n{e}", parent=self)
            return
        if mode is not None:
            self.modes[name] = mode

    def accept(self):
        name = self.printer.get()
        if not name:
            messagebox.showerror("印刷", "プリンターを選んでください。", parent=self)
            return
        try:
            copies = int(self.copies.get())
            if not 1 <= copies <= 99:
                raise ValueError
        except ValueError:
            messagebox.showerror("印刷", "部数は 1〜99 の数字にしてください。", parent=self)
            return
        try:
            pages = self._chosen_pages()
        except ValueError:
            messagebox.showerror("印刷", f"ページの指定を読めません（1〜{self.pages} の数字を、「1-3, 5」のように"
                                 "書いてください）。", parent=self)
            return
        self.result = (name, self.modes.get(name), copies, pages)
        self.destroy()

