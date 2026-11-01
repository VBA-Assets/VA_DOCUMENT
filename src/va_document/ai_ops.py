"""AI 連携：仮名化（選択範囲を仮名化・解除・一覧）、構文ファイルのコピー、AI の回答の取り込み、
外で書き換えられた構文ファイルの取り込み。

メインの画面（app.MainWindow）の部品（mixin）。保存（on_save）は file_ops.FileMixin が持つ。
"""
from dataclasses import dataclass
from tkinter import TclError, filedialog, messagebox

from . import APP_NAME, vamd
from .dialogs import UNREGISTER, ChangedOutsideDialog, EditDialog, LoadEntriesDialog, RegisterDialog
from .pseudonym import KINDS, NotRegistrable, token_label, trim_selection
from .recover import PdfMismatch
from .session import OtherFileMissing


@dataclass
class DictionaryStep:
    """仮名化の登録・解除の1回分。Ctrl+Z・Ctrl+Y で一覧も一緒に戻すために覚える（メモリの中だけ）。
    Tk の元に戻すの記録には印を付けられないので、書き換えの前後の文章で見分ける。"""
    registered: bool    # True なら登録、False なら解除
    word: str
    kind: str
    token: str
    before: str         # 書き換える前の文章
    after: str          # 書き換えた後の文章


class AiMixin:
    """AI 連携の操作（MainWindow に混ぜて使う）。"""

    def _refresh_dictionary(self):
        self.tree.delete(*self.tree.get_children())
        for e in sorted(self.session.dictionary.entries.values(), key=lambda e: (KINDS.index(e.kind), e.token)):
            self.tree.insert("", "end", iid=e.token, values=(e.token, e.word, e.kind))

    def on_register(self):
        word = trim_selection(self._selection())
        if not word:
            messagebox.showinfo(APP_NAME, "入力欄で、仮名化する語を選んでから押してください。", parent=self)
            return
        found = self.session.dictionary.find(word)
        if found is not None:
            if messagebox.askyesno(APP_NAME, f"「{found.word}」は {found.token} として仮名化しています。仮名化を解除しますか？",
                                   parent=self):
                self._unregister(found.token)
            return
        try:
            self.session.dictionary.check(word)
        except NotRegistrable as e:
            messagebox.showerror(APP_NAME, str(e), parent=self)
            return
        # 記号の英字は自動で振らず、利用者が必ず選ぶ（2026-10-25 班長決定）
        chosen = RegisterDialog(self, word, self.session.dictionary).result
        if chosen is None:
            return
        before = self.raw_text()
        token = self.session.dictionary.register(word, *chosen)
        self._after_dictionary_change()  # エディターの同じ語を、すべて記号に置き換える
        self._note_dictionary_step(True, word, chosen[0], token, before)
        self.status.configure(text=f"「{word}」を {token} として仮名化しました。")

    def _note_dictionary_step(self, registered, word, kind, token, before):
        self._redo_steps.clear()
        if self.raw_text() != before:    # 記号の中の字を選んだときなど、書き換わる語がなければ、Ctrl+Z の記録もない
            self._undo_steps.append(DictionaryStep(registered, word, kind, token, before, self.raw_text()))

    def on_undo(self, event=None):
        """Ctrl+Z。仮名化の登録・解除まで戻ったら、一覧の語も一緒に戻す（2026-11-01 班長決定）。記号に置き換えた
        ところだけを戻すと、次に組み直すときにまた記号になって先へ戻れないので、続けてその前の操作も戻す。"""
        had_word = self.session.dictionary.spans(self.raw_text())
        self._undo_once()
        if not had_word and self.session.dictionary.spans(self.raw_text()):
            self._undo_once()
        return "break"

    def on_redo(self, event=None):
        """Ctrl+Y。on_undo の逆。"""
        had_word = self.session.dictionary.spans(self.raw_text())
        self._redo_once()
        if not had_word and self.session.dictionary.spans(self.raw_text()):
            self._redo_once()
        return "break"

    def _undo_once(self):
        before = self.raw_text()
        self.text.edit_separator()      # Tk の <<Undo>> と同じく、前後を区切る（戻した所に、次の直しが混ざらないように）
        try:
            self.text.edit_undo()
        except TclError:
            return                      # 戻す操作がない
        finally:
            self.text.edit_separator()
        step = self._undo_steps[-1] if self._undo_steps else None
        if step is None or before != step.after or self.raw_text() != step.before:
            return
        self._redo_steps.append(self._undo_steps.pop())
        self._apply_step(step, not step.registered)

    def _redo_once(self):
        before = self.raw_text()
        try:
            self.text.edit_redo()
        except TclError:
            return                      # やり直す操作がない
        step = self._redo_steps[-1] if self._redo_steps else None
        if step is None or before != step.before or self.raw_text() != step.after:
            return
        self._undo_steps.append(self._redo_steps.pop())
        self._apply_step(step, step.registered)

    def _apply_step(self, step, register):
        """Ctrl+Z・Ctrl+Y で戻した文章に合わせて、一覧の語を足す・除く。除くときは解除と同じ処理を通す（語が文章に
        残っていると、保存するときに知らせる）。"""
        if register:
            self.session.dictionary.register(step.word, step.kind, token_label(step.token))
            message = f"「{step.word}」を {step.token} として仮名化しました。"
        else:
            self.session.unregister(step.token)
            message = f"「{step.word}」（{step.token}）の仮名化を解除しました。"
        self._after_dictionary_change(tokenize=False)
        self.status.configure(text=message)

    def _after_dictionary_change(self, tokenize=True):
        """仮名化した語を登録・変更・解除した後に、一覧・エディター・確認表示・題を新しくする。tokenize なら、
        エディターに実名のまま残っている仮名化した語を記号にする（解除のときは要らない）。"""
        self._refresh_dictionary()
        if tokenize:
            self._tokenize_editor()
        self._highlight()
        self._render_preview()
        self._update_title()

    def _unregister(self, token):
        before = self.raw_text()
        e = self.session.dictionary.find(token)
        if e:
            # エディターの記号を、先に元の語に戻す（解除した語が記号のまま残らないように）
            self._replace_in_editor(token, e.word)
        e = self.session.unregister(token)
        self._after_dictionary_change(tokenize=False)
        if e:
            self._note_dictionary_step(False, e.word, e.kind, e.token, before)
            self.status.configure(text=f"「{e.word}」（{e.token}）の仮名化を解除しました。")

    def on_edit_entry(self):
        """一覧の行をダブルクリックしたとき、その語の記号と元の語を変える（2026-10-25 班長決定）。元の語を直すと
        文章の中のその記号がすべて新しい語になり、新しい語がエディターに実名のままあれば記号にする。記号を変えると、
        エディターの記号も変える（前の記号を別の語に付けるときは、画面で確かめる）。画面の［解除］で、仮名化を解除する
        （2026-10-27 班長指示。一覧の横の［解除］［変更］のボタンは置かない）。"""
        sel = self.tree.selection()
        if not sel:
            return
        e = self.session.dictionary.find(sel[0])
        if e is None:
            return
        chosen = EditDialog(self, e, self.session.dictionary).result
        if chosen is None:
            return
        if chosen == UNREGISTER:
            self._unregister(e.token)
            return
        try:
            old_word, old_token = self.session.edit(e.token, *chosen)
        except NotRegistrable as err:
            messagebox.showerror(APP_NAME, str(err), parent=self)
            return
        # 語か記号が変わると、覚えている登録・解除を戻せなくなる（Ctrl+Z で一覧は戻らない）
        self._undo_steps.clear()
        self._redo_steps.clear()
        if old_token != e.token:
            self._replace_in_editor(old_token, e.token)
        self._after_dictionary_change()  # 新しい語をエディターに打ってあれば、記号にする
        self.tree.selection_set(e.token)
        changes = []
        if old_token != e.token:
            changes.append(f"記号を {old_token} から {e.token} に")
        if old_word != e.word:
            changes.append(f"元の語を「{old_word}」から「{e.word}」に")
        self.status.configure(text=("、".join(changes) + "変えました。") if changes else "変えていません。")

    def on_load_entries(self):
        """［ファイルから読み込む］：同じ案件の書式付きファイル（PDF）か構文ファイルを選び、その文書の仮名化した語を、今の
        一覧に足す（2026-10-29 班長決定。検討_仮名化した語の読み込み.md）。対応表は、開き直すときと同じく PDF と構文ファイルを
        突き合わせてメモリの中で作り直す（クリップボード・ファイルに出さない）。食い違いが1つでもあれば何も読み込まず、
        読み込む前に一覧を見せて確かめる。選んだファイルの場所は覚えない。"""
        path = filedialog.askopenfilename(parent=self, title="仮名化する語を読み込むファイル",
                                          filetypes=[("書式付きファイル・構文ファイル", f"*.pdf *{vamd.EXTENSION}"),
                                                     ("書式付きファイル（PDF）", "*.pdf"),
                                                     ("構文ファイル", f"*{vamd.EXTENSION}")])
        if not path:
            return
        try:
            try:
                vamd_path, pdf_path = self.session.other_files(path)
            except OtherFileMissing as e:
                msg = ("この書式付きファイル（PDF）の構文ファイルが、構文ファイルのフォルダに見つかりません。構文ファイルを選びますか？"
                       if e.kind == "vamd" else
                       "この構文ファイルの書式付きファイル（PDF）が、これまでに保存したフォルダに見つかりません。PDF を選びますか？")
                if not messagebox.askyesno(APP_NAME, msg + "\n（仮名化する語は、PDF と構文ファイルの両方から作り直します）",
                                           parent=self):
                    return
                other = self.ask_other_file(e.kind)
                if other is None:
                    return
                vamd_path, pdf_path = (other, e.found) if e.kind == "vamd" else (e.found, other)
            loaded = self.session.entries_from(vamd_path, pdf_path, self.real_text())
        except vamd.NoSeparator as e:
            messagebox.showerror(APP_NAME, f"構文ファイルとして読めません。\n{e}", parent=self)
            return
        except (PdfMismatch, OSError, ValueError) as e:
            messagebox.showerror(APP_NAME, f"読み込めませんでした。\n{e}", parent=self)
            return
        plan = loaded.plan
        if plan.conflicts:
            lines = "\n".join("　" + why for _, why in plan.conflicts[:10])
            more = f"\n　ほか {len(plan.conflicts) - 10} 語" if len(plan.conflicts) > 10 else ""
            messagebox.showwarning(APP_NAME, f"この文書の仮名化する語と食い違うため、読み込みませんでした（{loaded.pdf_path.name}）：\n"
                                   f"{lines}{more}\n\n同じ案件のファイルなら、この文書の一覧（ダブルクリックで編集）を直してから、"
                                   "もう一度読み込んでください。", parent=self)
            return
        if not plan.add:
            messagebox.showinfo(APP_NAME, f"新しく読み込む語はありません（{loaded.pdf_path.name}。同じ語 {len(plan.same)} 語）。",
                                parent=self)
            return
        if not LoadEntriesDialog(self, loaded).ok:
            return
        n = self.session.merge_entries(loaded)
        self._after_dictionary_change()     # エディターの読み込んだ語を、記号に置き換える
        self.status.configure(text=f"{loaded.pdf_path.name} の文書から、仮名化する語を {n} 語読み込みました。")

    def on_copy_vamd(self):
        """構文ファイルの中身をクリップボードに写す（直していれば、先に保存する）。"""
        text = self.real_text()
        saved = ""
        if self.session.is_modified(text) or self.session.version == 0 or not self.session.vamd_path.exists():
            if not messagebox.askyesno(APP_NAME, "構文ファイルをコピーする前に、書式付きファイル（PDF）と構文ファイルを保存します。"
                                       "よろしいですか？", parent=self):
                return
            if not self.on_save():
                return
            # 保存したことも、コピーの知らせと一緒に下の欄に出す（2026-10-26 班長指摘）
            saved = f"版 {self.session.version} を保存し、"
        data = self.session.vamd_path.read_text(encoding="utf-8")
        self.clipboard_clear()
        self.clipboard_append(data)
        self.status.configure(text=f"{saved}AI に渡す構文ファイル（仮名化済み）の中身をコピーしました。AI のチャット画面に貼り付けてください。")

    def on_copy_path(self):
        """構文ファイルのフルパスをクリップボードに写す（2026-10-24 班長指示）。保存していなければ写さない。"""
        if not self.session.version:
            return
        path = str(self.session.vamd_path)
        self.clipboard_clear()
        self.clipboard_append(path)
        self.status.configure(text=f"構文ファイルのパスをコピーしました：{path}")

    def on_import(self):
        """［貼り付け］：クリップボードの AI の回答を、確認の画面なしでエディターに取り込む（2026-10-23 班長決定）。"""
        clip = self.clipboard_text() or ""        # clipboard_get は長い文章で字が化けることがある（editor_ops）
        if not vamd.has_separator(clip) and "==== VA Document" not in clip:
            messagebox.showinfo(APP_NAME, "クリップボードに AI の回答がありません。\n"
                                "AI の画面で、回答のコードブロックのコピーボタンを押してから、［貼り付け］を押してください"
                                "（回答の最初の行に「==== VA Document 文書ID …」の区切りの行が要ります）。", parent=self)
            return
        self.take_in(clip, "回答")

    def take_in(self, answer_text, origin, check_outside=True):
        """AI の回答（または外で書き換えられた構文ファイル）を、記号を実名に戻してエディターに入れ、保存する。

        ・文書ID が違う・区切りの行がないときは、入れずに知らせる。
        ・変わった段落・増えた段落は、エディターの右端に青い線を付けて示す（次に取り込むまで残る）。
        ・記号・配置の記号の問題と、消えた段落は、あるときだけ知らせる。Ctrl+Z 1回で元に戻せる。
        取り込んで保存できたら True。
        """
        text = self.real_text()
        try:
            content, r = self.session.review_answer(answer_text, text)
        except (vamd.NoSeparator, vamd.OtherDocument) as e:
            messagebox.showerror(APP_NAME, f"取り込めません。\n{e}", parent=self)
            return False
        new_text = self.session.apply_answer(content, text)
        self._replace_undoable(self.session.body(new_text))      # エディターは仮名のまま
        self.text.tag_remove("changed", "1.0", "end")
        for k in r.changed_lines:
            self.text.tag_add("changed", f"{k + 1}.0", f"{k + 1}.end+1c")
        if r.changed_lines:
            self.text.see(f"{r.changed_lines[0] + 1}.0")
        problems = []
        if r.unknown_tokens:
            problems.append("仮名化する語の一覧にない記号（記号のまま入れました）：" + "、".join(r.unknown_tokens))
        if r.lost_tokens:
            problems.append("前の文章にあって、なくなった記号：" + "、".join(r.lost_tokens))
        if r.lost_marks:
            problems.append("なくなった配置などの記号：\n" + "\n".join(f"　{m}　{ln[:40]}" for m, ln in r.lost_marks[:10]))
        if r.unknown_images:
            problems.append("この文書にない画像の番号（画像のない枠になります）："
                            + "、".join(f"[IMAGE {n}]" for n in r.unknown_images))
        if r.added_images:
            problems.append("増えた画像の行（同じ画像を2か所に置きます）：" + "、".join(f"[IMAGE {n}]" for n in r.added_images))
        if r.footnotes:
            problems.append("脚注の記号（VA Documentは脚注を組めないため、記号は字のまま PDF に出ます。"
                            "本文の括弧書きなどに直してください）：" + "、".join(r.footnotes))
        if r.removed:
            restored = [self.session.dictionary.restore(ln)[0] for ln in r.removed]
            more = f"\n　ほか {len(restored) - 10} 段落" if len(restored) > 10 else ""
            problems.append(f"消えた段落（{len(restored)}）：\n" + "\n".join(f"　{ln[:50]}" for ln in restored[:10]) + more)
        if problems:
            messagebox.showwarning(APP_NAME, f"AI の{origin}を取り込みました。次の点を確かめてください。\n\n"
                                   + "\n\n".join(problems) + "\n\n取り込む前に戻すときは、Ctrl+Z を押してください。",
                                   parent=self)
        saved = self.on_save(check_outside=check_outside, allow_unknown=True)
        notes = [f"変わった・増えた段落 {len(r.changed_lines)}（右の青い線）"]
        if r.removed:
            notes.append(f"消えた段落 {len(r.removed)}")
        if r.older:
            notes.append(f"前の版（版 {content.version}）をもとにした回答")
        if content.dropped:
            # AI の画面が混ぜた内部の目印の行は、除いて知らせる（2026-10-25 班長決定）
            notes.append(f"AI の内部の目印と思われる行 {len(content.dropped)} 行（{content.dropped[0]}）を除きました")
        head = f"AI の{origin}を取り込み、版 {self.session.version} を保存しました。" if saved else \
            f"AI の{origin}を取り込みました（まだ保存していません）。"
        self.status.configure(text=head + "　" + "、".join(notes) + "。Ctrl+Z で取り込む前に戻せます。")
        return saved

    def _import_outside(self):
        """外で書き換えられた構文ファイルの中身を、［貼り付け］と同じく取り込み、保存する。"""
        self._declined_stamp = self.session.outside_stamp()
        return self.take_in(self.session.outside_vamd_text(), "用ファイル（外で書き換えたもの）", check_outside=False)

    def _on_focus_in(self, event=None):
        """VA Documentの画面に戻ったとき、構文ファイルが外で書き換えられていれば、取り込むかを尋ねる
        （取り込まないと答えた中身については、もう一度は尋ねない。保存するときには、改めて尋ねる）。"""
        if self._focus_job is None:
            self._focus_job = self.after(300, self._check_outside)

    def _check_outside(self):
        self._focus_job = None
        if self._checking_outside or self.grab_current() is not None:
            return
        try:
            if not self.session.vamd_changed_outside() or self.session.outside_stamp() == self._declined_stamp:
                return
        except OSError:
            return
        self._checking_outside = True
        try:
            choice = ChangedOutsideDialog(self, at_save=False).result
            self._declined_stamp = self.session.outside_stamp()
            if choice == "import":
                self._import_outside()
        finally:
            self._checking_outside = False
