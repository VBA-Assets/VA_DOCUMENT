"""ファイルの操作：開く・保存（PDF と構文ファイルを同じ版で）・閉じる・印刷。

メインの画面（app.MainWindow）の部品（mixin）。
"""
import re
from pathlib import Path
from tkinter import filedialog, messagebox

from . import APP_NAME, config, errors, naiyou, printing, vamd
from .dialogs import ChangedOutsideDialog, MissingDialog, NaiyouDialog, PrintDialog
from .doctypes import PAGE_NUMBER_LABELS, PAGE_NUMBER_NONE
from .document import image_mark
from .pdfwriter import FontNotEmbeddable
from .pseudonym import TOKEN_RE
from .recover import PdfMismatch

# ［開く］の画面のファイルの種類。最初のものが既定。開けるものをまとめて出し、Excel など開けないファイル
# （テキストとして読むと文字化けする）は出さない（2026-10-27 班長決定。「すべてのファイル」を既定にする案と比べた）。
# Word の文書（.docx）は Ver420 から（2026-11-24 班長指示。古い形式の .doc は開けない）
OPEN_FILETYPES = [
    ("開けるファイル（構文ファイル・書式付きファイル・Word の文書・テキスト・マークダウン）",
     f"*{vamd.EXTENSION} *.pdf *.docx *.txt *.md"),
    ("VA Document（構文ファイル・書式付きファイル）", f"*{vamd.EXTENSION} *.pdf"), ("Word の文書", "*.docx"),
    ("テキスト・マークダウン", "*.txt *.md"), ("すべてのファイル", "*.*")]


# エクスプローラーから落として開けるファイルの拡張子（［開く］の「開けるファイル」と同じ）
DROP_SUFFIXES = (vamd.EXTENSION, ".pdf", ".docx", ".txt", ".md")
# 落としたファイルの一覧（tkdnd の文字列。空白を含むパスは {} で囲まれる）
_DROP_PATH_RE = re.compile(r"\{([^}]*)\}|(\S+)")


def dropped_paths(data):
    """落としたファイルのパスの一覧。Tcl の splitlist はバックスラッシュを解釈して Windows のパスを壊すので、
    {} と空白だけで分ける（VA FAX の _parse_dropped_paths と同じ）。"""
    return [braced or bare for braced, bare in _DROP_PATH_RE.findall(data)]


class FileMixin:
    """ファイルの操作（MainWindow に混ぜて使う）。"""

    def _init_file_drop(self, widgets):
        """エクスプローラーからファイルを落として開けるようにする（2026-10-28 班長指示。VA FAX と同じ tkinterdnd2）。
        widgets は落とす先（ウィンドウの中の左右の枠・確認表示・エディター。ウィンドウ〔tk.Tk〕そのものは、tkinterdnd2 の
        <<Drop>> を結び付けられない）。tkinterdnd2 がない・読めないとき（ソースから使う Mac など）は、落とせないだけで、
        ほかは変わらない。落とせるようにできたら True。"""
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            TkinterDnD._require(self)
            for w in widgets:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_file_drop)
        except Exception:
            return False
        return True

    def _on_file_drop(self, event):
        # 落とす操作が終わってから開く（落としている間に確認の画面を出すと、エクスプローラーが待たされる）
        self.after(0, lambda: self.open_dropped(dropped_paths(event.data)))
        return event.action

    def open_dropped(self, paths):
        """落としたファイルを開く（［開く］と同じ。保存していない変更があれば、先に尋ねる）。開くのは1つだけで、
        2つ以上・フォルダ・開けない種類（Excel・古い形式の Word〔.doc〕など。テキストとして読むと文字化けする）は開かずに
        知らせる。"""
        if len(paths) != 1:
            messagebox.showinfo(APP_NAME, "開くファイルを1つだけ落としてください。", parent=self)
            return
        path = Path(paths[0])
        if path.is_dir() or path.suffix.lower() not in DROP_SUFFIXES:
            messagebox.showinfo(APP_NAME, f"このファイルは開けません：{path.name}\n開けるのは、構文ファイル（{vamd.EXTENSION}）・"
                                "書式付きファイル（.pdf）・Word の文書（.docx）・テキスト（.txt）・マークダウン（.md）です。",
                                parent=self)
            return
        if not self._confirm_discard():
            return
        self.open_path(path)

    def on_open(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(parent=self, title="開く", filetypes=OPEN_FILETYPES)
        if path:
            self.open_path(Path(path))

    def open_path(self, path):
        try:
            suffix = path.suffix.lower()
            if suffix == vamd.EXTENSION:
                result = self._open_vamd(path)
            elif suffix == ".pdf":
                result = self.session.open_pdf(path)
            elif suffix == ".docx":
                result = self.session.open_docx(path)
            elif suffix == ".doc":
                messagebox.showinfo(APP_NAME, "古い形式の Word の文書（.doc）は開けません。Word で開き、［名前を付けて保存］で"
                                    "「Word 文書（*.docx）」を選んで保存し直してから、開いてください。", parent=self)
                return
            else:
                result = self.session.open_text(path)
        except vamd.NoSeparator as e:
            self.errors.record(e, "開く")
            messagebox.showerror(APP_NAME, f"構文ファイルとして読めません。\n{e}", parent=self)
            return
        except (PdfMismatch, OSError, ValueError) as e:
            self.errors.record(e, "開く")
            messagebox.showerror(APP_NAME, f"開けませんでした。\n{errors.describe(e)}", parent=self)
            return
        if result is None:
            return
        if result.error is not None:
            self.errors.record(result.error, "PDF の読み取り")      # 字だけを取り出して開いた（型と場所だけを残す）
        text = result.text
        if result.unresolved:
            answers = MissingDialog(self, self.session, result).answers
            text = self.session.resolve(answers)
        self._load_text(text)
        if self.preview_shown():
            self._layout_pages(keep=False)     # 開いた文書は、1ページ目の上から表示する（隠していれば、出したときに並べる）
        for m in result.messages:
            messagebox.showinfo(APP_NAME, m, parent=self)
        self.status.configure(text=f"開きました：{path.name}")

    def _open_vamd(self, path):
        try:
            return self.session.open_vamd(path)
        except FileNotFoundError:
            pass
        choice = messagebox.askyesnocancel(
            APP_NAME, "この構文ファイルと同じ文書ID の書式付きファイル（PDF）が、これまでに保存したフォルダに見つかりません。\n"
            "PDF を選びますか？\n（［いいえ］：PDF なしで開き、記号の元の語を入力します）", parent=self)
        if choice is None:
            return None
        if choice:
            pdf = self.ask_other_file("pdf")
            if pdf is None:
                return None
            return self.session.open_vamd(path, pdf)
        return self.session.open_vamd(path, False)

    def ask_other_file(self, kind):
        """相手のファイル（kind が "pdf" なら書式付きファイル、"vamd" なら構文ファイル）が見つからないとき、選んで
        もらう（開く・［ファイルから読み込む］で共通。選んだ場所は覚えない）。選ばなければ None。"""
        title, types = (("PDF を選ぶ", [("PDF", "*.pdf")]) if kind == "pdf"
                        else ("構文ファイルを選ぶ", [("構文ファイル", f"*{vamd.EXTENSION}")]))
        path = filedialog.askopenfilename(parent=self, title=title, filetypes=types)
        return Path(path) if path else None

    def _confirm_discard(self):
        """保存していない変更があれば、保存するかを尋ねる。続けてよければ True。"""
        text = self.real_text()
        if not self.session.is_modified(text):
            return True
        answer = messagebox.askyesnocancel(APP_NAME, "保存していない変更があります。保存しますか？", parent=self)
        if answer is None:
            return False
        return self.on_save() if answer else True

    def on_close_document(self):
        """今の文書を閉じて、新しい文書にする（Word の「閉じる」。VA Document は終わらない。2026-10-24 班長指示）。
        保存していない変更があれば尋ねる。仮名化した語の一覧（実名と記号の対応）が消えることは確かめない（保存した
        文書は、開き直せば構文ファイルと PDF を突き合わせて作り直せる。2026-10-27 班長指示）。"""
        if self.is_blank():             # 白紙のまま変えていない（押せない。Ctrl+W で来たとき）
            return False
        if not self._confirm_discard():
            return False
        self.session.new()
        self._load_text("")             # 設定の欄・仮名化した語の一覧・題も、ここで新しい文書のものにする
        self._layout_pages(keep=False)
        self.status.configure(text="文書を閉じました。新しい文書です。")
        return True

    def on_save(self, check_outside=True, allow_unknown=False):
        """PDF と構文ファイルを、同じ版で保存する。保存できたら True。

        構文ファイルが外で書き換えられていれば（テキストエディターで直した、AI の回答を上書き保存した、など）、
        黙って上書きせず、取り込むか・上書きするかを尋ねる（2026-10-23 班長了承）。
        エディターは常に仮名で、見えているものがそのまま構文ファイルに書かれるので、保存の前の確認画面
        （構文ファイルに書く中身の確認）は出さない（2026-10-24 班長決定）。
        """
        text = self.real_text()
        if check_outside and self.session.vamd_changed_outside():
            choice = ChangedOutsideDialog(self, at_save=True).result
            if choice is None:
                return False
            if choice == "import":
                return self._import_outside()
        pdf = self.session.pdf_path
        if pdf is None:
            pdf = self._ask_pdf_path()
            if pdf is None:
                return False
        text = self._guard_tokens(text, allow_unknown)
        if text is None:
            return False
        if not self._check_released(text):
            return False
        if not self._check_missing_images(text):
            return False
        if self.session.settings.doc_type == naiyou.DOC_TYPE and not self._check_naiyou(text):
            return False
        try:
            self.session.save(text, pdf)
        except PermissionError as e:
            self.errors.record(e, "保存")
            messagebox.showerror(APP_NAME, f"PDF を保存できませんでした。PDF をほかのソフトで開いていれば、閉じてから"
                                 f"もう一度保存してください。\n{pdf}", parent=self)
            return False
        except (OSError, FontNotEmbeddable) as e:
            self.errors.record(e, "保存")
            messagebox.showerror(APP_NAME, f"保存できませんでした。\n{errors.describe(e)}", parent=self)
            return False
        config.save(self.cfg)
        self._update_title()
        self.status.configure(text=f"版 {self.session.version} を保存しました。書式付き（PDF）：{self.session.pdf_path.name}　"
                                   f"構文（VAMD）：{self.session.vamd_path.name}")
        return True

    def _check_released(self, text):
        """仮名化を解除した語・変える前の元の語が、構文ファイル（AI に渡すもの）に実名のまま残っていれば知らせ、
        保存するかを尋ねる（2026-10-25 班長指示）。保存してよければ True。
        残してよいと答えた語は、もう知らせない。"""
        found = self.session.released_in(text)
        if not found:
            return True
        lines = "\n".join(f"　{w}（{n} か所）" for w, n in list(found.items())[:10])
        more = f"\n　ほか {len(found) - 10} 語" if len(found) > 10 else ""
        if messagebox.askyesno(APP_NAME, "仮名化を解除した語（または、変える前の元の語）が、文章に残っています：\n"
                               f"{lines}{more}\n\nこのまま保存すると、構文ファイル（AI に渡すもの）に実名のまま書かれます。"
                               "仮名化するはずの語であれば、直してから保存してください。"
                               "仮名化するときは、語を選んで［選択範囲を仮名化］を押してください。\n\n"
                               "このまま保存しますか？", parent=self):
            self.session.accept_released(found)
            return True
        # 最初に残っている所を選んで見せる（エディターは仮名なので、残った語はエディターにもそのままある）
        word = next(iter(found))
        first = self.text.search(word, "1.0", stopindex="end")
        if first:
            self.text.tag_remove("sel", "1.0", "end")
            self.text.tag_add("sel", first, f"{first}+{len(word)}c")
            self.text.mark_set("insert", first)
            self.text.see(first)
            self.text.focus_set()
        return False

    def _check_missing_images(self, text):
        """画像のデータがない [IMAGE n]（PDF なしで開いた、別の文書から行を写した、AI が作った、など）があれば、
        エディターのカーソルをその行に動かし、保存するかを尋ねる（既定は保存をやめる。2026-10-29 班長決定）。
        このまま保存すると、その所は空けたまま（枠は描かない）。保存してよければ True。"""
        missing = self.session.missing_images(text)
        if not missing:
            return True
        names = "、".join(f"[IMAGE {n}]" for n in missing)
        for k, line in enumerate(self.raw_text().split("\n")):
            mark = image_mark(line)
            if mark and mark[0] == missing[0]:
                self.text.tag_remove("sel", "1.0", "end")
                self.text.mark_set("insert", f"{k + 1}.0")
                self.text.see(f"{k + 1}.0")
                break
        return messagebox.askyesno(APP_NAME, f"画像のない画像の記号があります：{names}\n\n"
                                   "書式付きファイル（PDF）が見つからずに開いた文書や、別の文書から写した行では、画像が"
                                   "戻りません。このまま保存すると、その所は空けたまま保存します。"
                                   "画像を入れ直すときは、その行を消して［画像］で入れてください。\n\n"
                                   "このまま保存しますか？", default=messagebox.NO, parent=self)

    def _check_naiyou(self, text):
        """内容証明なら、保存する前に VA内容証明郵便と同じ字数・行数のチェックをする（2026-10-24 班長指示）。
        ページ番号が「なし」でなければ「なし」にして知らせる（VA内容証明郵便がヘッダー・フッターを消すのと同じ）。
        超えた所があれば、エディターのカーソルをその行に動かし、保存するかを尋ねる。保存してよければ True。"""
        if self.session.settings.page_number != PAGE_NUMBER_NONE:
            self.page_number_box.set(PAGE_NUMBER_LABELS[PAGE_NUMBER_NONE])
            self.on_settings_changed()
            messagebox.showinfo(APP_NAME, "内容証明にはページ番号を付けないため、ページ番号を「なし」にしました。",
                                parent=self)
        ts, lines = self.session.typeset(text)
        problem = naiyou.check(ts, lines)
        if problem is None:
            return True
        hit = self.session.layout_map.hit(problem.page - 1, problem.x, problem.y)
        if hit is not None:
            self._move_cursor(*hit)
        return NaiyouDialog(self, problem).ok

    def _guard_tokens(self, text, allow_unknown=False):
        """保存する実名の文章に、構文ファイルの区切りの行や、仮名化した語にない記号が残っていないかを確かめる。

        区切りの行があれば保存しない（仮名の文章が紛れ込んでいる）。仮名化した語にない記号（AI が作った〔人名Ｃ〕など）
        があれば、PDF に記号のまま出ることを知らせて、保存するかを尋ねる（仮名化した語の記号は、実名に戻してある）。
        返すのは保存する文章（やめたら None）。allow_unknown なら尋ねない（AI の回答の取り込みで、すでに知らせているため）。
        """
        if vamd.has_separator(text):
            messagebox.showerror(APP_NAME, "実名の文章の中に、構文ファイルの区切りの行（==== VA Document …）があります。"
                                 "仮名の文章が紛れ込んでいるおそれがあるため、保存しません。\n\n"
                                 "AI の回答を Ctrl+V で貼り付けた場合は、Ctrl+Z で貼り付ける前に戻してから、"
                                 "「AI 連携」の［貼り付け］で取り込んでください（区切りの行を外し、文書ID と版を確かめ、"
                                 "記号を実名に戻して、変わった段落に印を付けます）。\n"
                                 "そうでない場合は、区切りの行とその上（AI への指示）を消してから保存してください。", parent=self)
            return None
        unknown = list(dict.fromkeys(m.group(0) for m in TOKEN_RE.finditer(text)))
        if not unknown or allow_unknown:
            return text
        if not messagebox.askyesno(APP_NAME, "仮名化する語の一覧にない記号があります（AI が作った記号など）：\n"
                                   + "、".join(unknown) + "\n\nこのまま保存すると、PDF には記号のまま出ます。"
                                   "元の語が分かれば、エディターで直すか、元の語を選んで仮名化してください。\n"
                                   "このまま保存しますか？", parent=self):
            return None
        return text

    def _ask_pdf_path(self):
        # 画面の題は、画面の「書式付き（PDF）ファイル」の呼び方にそろえる（2026-10-26 班長指示）
        while True:
            path = filedialog.asksaveasfilename(parent=self, title="書式付き（PDF）ファイルの保存先", defaultextension=".pdf",
                                                filetypes=[("PDF", "*.pdf")])
            if not path:
                return None
            path = Path(path)
            if path.parent.resolve() == Path(self.cfg.vamd_folder).resolve():
                messagebox.showwarning(APP_NAME, "構文ファイルのフォルダには、書式付きファイル（PDF。実名入り）を保存しないでください。"
                                       "AI がフォルダの中を読むと、実名の PDF に届いてしまいます。", parent=self)
                continue
            return path

    def on_print(self):
        """印刷の画面で選んだページを、プリンターに実際のサイズ（A4）で印刷する。保存していない変更があれば、先に保存する
        （印刷したものと、保存した書式付きファイル〔PDF〕が違わないように。2026-10-26 班長指示。それまでは保存しなくても
        印刷できた）。保存をやめたら印刷しない。白紙のまま変えていない間は、何もしない（［印刷］を押せない。Ctrl+P も
        効かせない。2026-11-24 班長指摘）。"""
        if self.is_blank():
            return
        if not printing.available():
            # Windows だけ（Mac などでは［印刷］を押せない。Ctrl+P も効かせない）。保存した PDF を、PDF のソフトで印刷する
            messagebox.showinfo(APP_NAME, "この PC では、VA Document から印刷できません。保存した PDF を開いて印刷してください。",
                                parent=self)
            return
        text = self.real_text()
        saved = ""
        if self.session.is_modified(text):
            if not self.on_save():                      # 記号・区切りの行の確かめも、保存のときに行う
                return
            text = self.real_text()
            # 保存したことは、印刷の知らせと一緒に下の欄に出す（印刷の途中の知らせで上書きされるため。2026-10-26 班長指摘）
            saved = f"版 {self.session.version} を保存し、"
        elif self._guard_tokens(text) is None:
            return
        try:
            data = self.session.preview_pdf(text)
        except Exception as e:
            self.errors.record(e, "印刷")
            messagebox.showerror(APP_NAME, f"印刷するページを組めませんでした。\n{errors.describe(e)}", parent=self)
            return
        # VA Document の「印刷」画面で選ぶ（2026-10-24 班長決定。Windows の新しい印刷画面の紛らわしい知らせを避ける）。
        # 印刷プレビューで、紙に出るものを確かめられる（2026-10-30 班長決定）
        choice = PrintDialog(self, data, printing.printers(), self._last_printer or printing.default_printer(),
                             printing.show_properties).result
        if choice is None:
            return
        name, mode, copies, page_list = choice
        self._last_printer = name
        try:
            hdc = printing.make_dc(name, mode, copies)
        except printing.PrintError as e:
            self.errors.record(e, "印刷")
            messagebox.showerror(APP_NAME, f"印刷できませんでした。\n{errors.describe(e)}", parent=self)
            return

        def progress(done, total):
            self.status.configure(text=f"印刷しています（{done} / {total} ページ）…")
            self.update_idletasks()
        self.configure(cursor="watch")
        try:
            # 印刷の文書の名前は、Word と同じく PDF のファイル名（保存していなければ「VA Document」）。
            # 2026-10-23 班長決定（文書ID にしていたが、Microsoft Print to PDF で作った PDF の題名にもなるため改めた）
            doc_name = self.session.pdf_path.stem if self.session.pdf_path else APP_NAME
            n = printing.print_pdf(data, hdc, doc_name, page_list, progress=progress)
        except (printing.PrintError, OSError) as e:
            self.errors.record(e, "印刷")
            messagebox.showerror(APP_NAME, f"印刷できませんでした。\n{errors.describe(e)}", parent=self)
            self.status.configure(text="印刷できませんでした。")
            return
        finally:
            self.configure(cursor="")
        self.status.configure(text=f"{saved}{n} ページをプリンターに送りました。")

