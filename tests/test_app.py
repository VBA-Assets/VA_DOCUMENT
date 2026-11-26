"""画面（仕様.md の4）。確認画面（モーダル）は差し替えて、画面の操作の流れを確かめる。"""
import json
import re
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from tkinter import messagebox  # noqa: E402

from va_document import ai_ops, app, config, diagnostics, file_ops, preview, theme, vamd  # noqa: E402
from va_document.document import (BULLET_MARK, CENTER_MARK, HEADING_BUTTON_MARK, PAGE_BREAK_MARK,  # noqa: E402
                                  RIGHT_MARK)
from va_document.pdfwriter import read_id  # noqa: E402
from va_document.current_line import CURRENT_LINE_TAG, CURRENT_LINE_WATCH_MS  # noqa: E402

TEXT = "原告　甲野太郎\n:=: 準備書面（１）\n# 認否\n甲野太郎の主張は争う。\n"
PSEUDO = TEXT.replace("甲野太郎", "〔人名Ａ〕")      # エディターは常に仮名（2026-10-24 班長決定）


@pytest.fixture(scope="module")
def main_window(tmp_path_factory):
    # Tk はモジュールで1つだけ作る（Windows の Python では、Tk を何度も作り直すと、まれに初期化に失敗する）
    try:
        w = app.MainWindow(cfg=config.AppConfig(vamd_folder="未使用"))
    except tk.TclError as e:
        pytest.skip(f"画面を表示できない環境（{e}）")
    w.withdraw()
    # 誤りの記録も、班長の %APPDATA% には書かない
    w.errors = diagnostics.ErrorLog(tmp_path_factory.mktemp("errors") / "errors.json")
    yield w
    w.destroy()


@pytest.fixture
def window(main_window, tmp_path, monkeypatch):
    # 班長の設定ファイル（%APPDATA%）には書かない
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "settings.json")
    w = main_window
    w.errors = diagnostics.ErrorLog(tmp_path / "errors.json")
    w.cfg = config.AppConfig(vamd_folder=str(tmp_path / "構文ファイル"))
    w.session = app.Session(w.cfg)
    w._load_text(TEXT)
    w.session.dictionary.register("甲野太郎", "人名")
    w._refresh_dictionary()
    w.refresh()
    return w


def test_theme(window):
    style = tk.ttk.Style(window)
    assert style.theme_use() == "clam"
    assert style.lookup("TButton", "background") == theme.CONTROL_BG
    assert style.lookup("TButton", "background", ["active"]) == theme.HOVER_BG
    assert style.lookup("TButton", "background", ["pressed"]) == theme.PRESSED_BG
    # 主要なボタンは枠線だけをアクセント色にする（地色は同じ）
    assert style.lookup("Accent.TButton", "bordercolor") == theme.ACCENT
    assert style.lookup("Accent.TButton", "background") == theme.CONTROL_BG


def test_preview_and_highlight(window):
    assert window._preview_doc is not None and len(window._preview_doc) == 1
    assert window.page_label.cget("text") == "1 / 1"
    ranges = window.text.tag_ranges("registered")
    assert [window.text.get(a, b) for a, b in zip(ranges[0::2], ranges[1::2])] == ["〔人名Ａ〕", "〔人名Ａ〕"]
    assert window.tree.get_children() == ("〔人名Ａ〕",)


def test_preview_scrolls_across_pages(window):
    """確認表示は全ページを縦に並べ、スクロールでページをまたいで送れる。"""
    window.deiconify()
    window.geometry("1200x800")
    window._load_text("\n".join(["# 見出し"] + ["本文の段落。" * 20] * 60))
    window.update()
    window._layout_pages(keep=False)
    window.update()
    n = len(window._preview_doc)
    assert n >= 3 and len(window._page_tops) == n
    assert window.page_label.cget("text") == f"1 / {n}"
    assert 0 in window._page_images and n - 1 not in window._page_images   # 見えているページだけ画像にする
    window.canvas.yview_moveto(1.0)          # スクロールバーを一番下へ
    window.update()
    window._render_visible()
    assert window.page_label.cget("text") == f"{n} / {n}" and n - 1 in window._page_images
    # ページ送りのボタンはない（2026-10-30 班長決定）。スクロールで前のページの上の端へ送ると、番号もそのページになる
    assert not hasattr(window, "on_page") and not hasattr(window, "on_zoom")
    window.canvas.yview_moveto((window._page_tops[n - 2] - preview.PAGE_GAP) / window._total_height())
    window.update()
    window._render_visible()
    assert window.page_label.cget("text") == f"{n - 1} / {n}"
    # ページはいつも欄の幅に合わせる（横のスクロールバーはない）
    assert window._page_size[0] == round(window._preview_doc.size(0)[0] * window._fit_zoom())
    assert not [c for c in _widgets(window._preview_pane, tk.ttk.Scrollbar) if str(c.cget("orient")) == "horizontal"]
    window.withdraw()


def test_editor_is_always_pseudonymized(window, monkeypatch):
    """エディターは常に仮名（記号）で、実名は確認表示で見る。仮名化した語を打つ・貼ると記号に置き換え、
    仮名化・解除でエディターの語と記号を入れ替える（2026-10-24 班長決定）。"""
    assert window.raw_text() == PSEUDO and window.real_text() == TEXT
    assert not hasattr(window, "view")
    # 仮名化した語を打つと、組み直すときに記号に置き換わる
    window.text.insert("end", "甲野太郎は認める。")
    window.refresh()
    assert window.raw_text().endswith("〔人名Ａ〕は認める。")
    # 仮名化した語を含む文章を貼ると、記号に置き換えて貼る（そのほかの文章は、ふつうの貼り付けに任せる）
    monkeypatch.setattr(window, "clipboard_text", lambda: "甲野太郎の陳述書と〔人名Ｚ〕の陳述書")
    window.text.mark_set("insert", "end")
    assert window._on_paste() == "break"
    assert window.raw_text().endswith("〔人名Ａ〕の陳述書と〔人名Ｚ〕の陳述書")
    monkeypatch.setattr(window, "clipboard_text", lambda: "ふつうの文章")
    assert window._on_paste() is None
    # 選んだ語を仮名化すると、エディターの同じ語がすべて記号になる
    window._load_text(TEXT + "乙山花子と乙山花子。\n")
    window.text.tag_add("sel", "5.0", "5.4")
    monkeypatch.setattr(ai_ops, "RegisterDialog", lambda parent, word, d: type("D", (), {"result": ("人名", "b")})())
    window.on_register()
    assert window.raw_text().endswith("〔人名Ｂ〕と〔人名Ｂ〕。\n")
    assert window.real_text().endswith("乙山花子と乙山花子。\n")
    # 解除すると、エディターの記号を元の語に戻す
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    window._unregister("〔人名Ｂ〕")
    assert window.raw_text().endswith("乙山花子と乙山花子。\n")
    # エディターの記号を選んで［選択範囲を仮名化］を押しても、解除できる
    window.text.tag_remove("sel", "1.0", "end")
    window.text.tag_add("sel", "1.3", "1.8")              # 「〔人名Ａ〕」
    window.on_register()
    assert "〔人名Ａ〕" not in window.raw_text() and window.raw_text().startswith("原告　甲野太郎")


def _register_in_editor(window, monkeypatch, start, end, letters="b"):
    window.text.tag_remove("sel", "1.0", "end")
    window.text.tag_add("sel", start, end)
    monkeypatch.setattr(ai_ops, "RegisterDialog", lambda parent, word, d: type("D", (), {"result": ("人名", letters)})())
    window.on_register()


def test_undo_register(window, tmp_path, monkeypatch):
    """Ctrl+Z 1回で、仮名化の登録ごと戻る。Ctrl+Y でもう一度登録する。解除と同じく、語が残れば保存のときに知らせる
    （2026-11-01 班長決定。それまでは登録が残り、組み直しでまた記号になって先へ戻れなかった）。"""
    window._load_text(TEXT + "乙山花子と乙山花子。\n")
    window.text.edit_separator()
    window.text.insert("end-1c", "追記。")
    window.text.edit_separator()
    typed = window.raw_text()
    _register_in_editor(window, monkeypatch, "5.0", "5.4")
    registered = window.raw_text()
    assert "〔人名Ｂ〕と〔人名Ｂ〕" in registered
    window.on_undo()
    assert window.raw_text() == typed
    assert window.session.dictionary.find("乙山花子") is None
    assert "〔人名Ｂ〕" not in window.tree.get_children()
    assert "解除しました" in window.status.cget("text")
    window.refresh()                            # 組み直しても、記号に戻らない
    assert window.raw_text() == typed
    assert window.session.released_in(window.real_text()) == {"乙山花子": 2}
    window.on_redo()
    assert window.raw_text() == registered
    assert window.session.dictionary.find("乙山花子").token == "〔人名Ｂ〕"
    assert window.session.dictionary.find("〔人名Ｂ〕").kind == "人名"
    assert "〔人名Ｂ〕" in window.tree.get_children()
    assert window.session.released_in(window.real_text()) == {}
    window.on_undo()
    window.on_undo()                            # 登録の前の直しまで戻れる
    assert "追記。" not in window.raw_text()
    window.refresh()
    assert "乙山花子と乙山花子" in window.raw_text()


def test_undo_unregister(window, monkeypatch):
    """［解除］の後の Ctrl+Z で、記号と一覧の語が一緒に戻る（元の語の分からない記号を残さない。2026-11-01 班長決定）。
    登録・解除の順に、続けて戻せる。"""
    window._load_text(TEXT + "乙山花子と乙山花子。\n")
    first = window.raw_text()
    _register_in_editor(window, monkeypatch, "5.0", "5.4")
    registered = window.raw_text()
    window._unregister("〔人名Ｂ〕")
    assert window.raw_text() == first
    window.on_undo()
    assert window.raw_text() == registered
    assert window.session.dictionary.find("〔人名Ｂ〕").word == "乙山花子"
    assert "〔人名Ｂ〕" in window.tree.get_children()
    assert window.real_text().endswith("乙山花子と乙山花子。\n")      # 記号のまま PDF に出ない
    assert window.session.released_in(window.real_text()) == {}
    assert "仮名化しました" in window.status.cget("text")
    window.on_redo()
    assert window.raw_text() == first and window.session.dictionary.find("乙山花子") is None
    assert window.session.released_in(window.real_text()) == {"乙山花子": 2}
    window.refresh()
    assert window.raw_text() == first
    window.on_undo()
    window.on_undo()                            # 解除の前へ、さらに登録の前へ
    assert window.raw_text() == first and window.session.dictionary.find("乙山花子") is None
    window.on_redo()
    window.on_redo()
    assert window.raw_text() == first and window.session.dictionary.find("乙山花子") is None
    window.on_undo()
    assert window.raw_text() == registered and window.session.dictionary.find("乙山花子") is not None


def test_undo_after_edit_entry_keeps_dictionary(window, monkeypatch):
    """［変更］の後の Ctrl+Z は、一覧を戻さない（覚えていた登録・解除を消す）。文章だけが戻る。"""
    window._load_text(TEXT + "乙山花子と乙山花子。\n")
    _register_in_editor(window, monkeypatch, "5.0", "5.4")
    window.tree.selection_set("〔人名Ｂ〕")
    monkeypatch.setattr(ai_ops, "EditDialog", lambda parent, e, d: type("D", (), {"result": ("乙山花子", "人名", "c")})())
    window.on_edit_entry()
    assert "〔人名Ｃ〕と〔人名Ｃ〕" in window.raw_text()
    assert not window._undo_steps
    window.on_undo()
    window.on_undo()
    assert window.session.dictionary.find("乙山花子").token == "〔人名Ｃ〕"


def test_undo_two_registers_and_typing_after(window, monkeypatch):
    """2語を登録し、後に打った字も含めて、新しい順に1回ずつ戻る。"""
    window._load_text(TEXT + "乙山花子と丙川次郎。\n")
    first = window.raw_text()
    _register_in_editor(window, monkeypatch, "5.0", "5.4", "b")
    second = window.raw_text()
    pos = second.index("丙川次郎")
    _register_in_editor(window, monkeypatch, f"1.0+{pos}c", f"1.0+{pos + 4}c", "c")
    third = window.raw_text()
    window.text.edit_separator()
    window.text.insert("end-1c", "あ")
    window.text.edit_separator()
    window.on_undo()
    assert window.raw_text() == third           # 打った字だけが戻り、登録は残る
    assert len(window.session.dictionary.entries) == 3
    window.on_undo()
    assert window.raw_text() == second and window.session.dictionary.find("丙川次郎") is None
    window.on_undo()
    assert window.raw_text() == first and window.session.dictionary.find("乙山花子") is None
    assert window.session.dictionary.find("甲野太郎") is not None
    window.on_redo()
    window.on_redo()
    assert window.raw_text() == third and len(window.session.dictionary.entries) == 3


def test_undo_typed_word_is_not_a_dead_end(window):
    """仮名化した語を打って記号になった後の Ctrl+Z は、打つ前まで戻る（実名に戻しただけで止まると、次に組み直すときに
    また記号になり、いつまでも先へ戻れない）。"""
    start = window.raw_text()
    window.text.edit_separator()
    window.text.insert("end-1c", "甲野太郎")
    window.text.edit_separator()
    window.refresh()
    assert window.raw_text() == start + "〔人名Ａ〕"
    window.on_undo()
    assert window.raw_text() == start
    window.refresh()
    assert window.raw_text() == start
    window.on_redo()
    assert window.raw_text() == start + "〔人名Ａ〕"


def test_undo_keys_are_bound(window):
    """<<Undo>>（Ctrl+Z）が on_undo を通る。戻す操作がなくても止まらない。"""
    window.focus_force()
    window.text.focus_force()
    window.update()
    window.text.event_generate("<<Undo>>")      # 読み込んだ直後は戻す操作がない
    window.text.event_generate("<<Redo>>")
    assert window.raw_text() == PSEUDO
    window.text.insert("end-1c", "あ")
    window.text.event_generate("<<Undo>>")
    assert window.raw_text() == PSEUDO


def test_align_and_line_marks(window):
    window.text.mark_set("insert", "4.0")
    window.on_align("--: ")
    assert window.text.get("4.0", "4.end") == "--: 〔人名Ａ〕の主張は争う。"
    window.on_align(":-: ")
    assert window.text.get("4.0", "4.end") == ":-: 〔人名Ａ〕の主張は争う。"
    window.on_align(":-: ")   # 同じボタンをもう一度押すと解除する
    assert window.text.get("4.0", "4.end") == "〔人名Ａ〕の主張は争う。"
    # 複数の行：すべてが同じ記号のときだけ解除し、そうでなければそろえる
    window.text.tag_add("sel", "2.0", "4.end")
    window.on_align("--: ")
    assert [window.text.get(f"{n}.0", f"{n}.end") for n in (2, 3, 4)] == \
        ["--: 準備書面（１）", "--: # 認否", "--: 〔人名Ａ〕の主張は争う。"]
    window.on_align("--: ")
    assert [window.text.get(f"{n}.0", f"{n}.end") for n in (2, 3, 4)] == \
        ["準備書面（１）", "# 認否", "〔人名Ａ〕の主張は争う。"]
    window.text.edit_undo()      # Ctrl+Z 1回で、3行とも戻る
    assert window.text.get("2.0", "2.end") == "--: 準備書面（１）"
    window.text.tag_remove("sel", "1.0", "end")
    window.text.edit_undo()
    window.text.mark_set("insert", "4.0")
    window.on_line_mark("<<<")
    assert window.text.get("4.0", "4.end") == "<<<"


def test_save_and_import(window, tmp_path, monkeypatch):
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    assert window.on_save()
    assert read_id(str(tmp_path / "準備書面.pdf")) == (window.session.doc_id, 1)
    assert window.session.vamd_path.exists()
    assert (tmp_path / "settings.json").exists()
    # ［貼り付け］：クリップボードの AI の回答を、確認の画面なしでエディターに取り込む
    # （班長のクリップボードを書き換えないよう、クリップボードの読み取りを差し替える）
    body = vamd.read_file(window.session.vamd_path).body_text.replace("争う。", "否認する。")
    answer = "直しました。\n```\n" + vamd.separator_line(window.session.doc_id, 1, window.session.settings) + "\n" + body + "\n```\n"
    monkeypatch.setattr(window, "clipboard_text", lambda: answer)
    window.on_import()
    assert "〔人名Ａ〕の主張は否認する。" in window.raw_text()          # エディターは仮名のまま
    assert "甲野太郎の主張は否認する。" in window.real_text()
    assert window.session.version == 2
    assert "否認する。" in window.session.vamd_path.read_text(encoding="utf-8")
    # 変わった段落（4行目）だけに、右端の青い線の印が付く
    ranges = window.text.tag_ranges("changed")
    assert [str(x) for x in ranges] == ["4.0", "5.0"]
    # Ctrl+Z（エディターの元に戻す）1回で、貼り付ける前の文章に戻る
    window.text.edit_undo()
    assert window.raw_text() == PSEUDO


def test_open_dialog_lists_all_openable_files_first(window, tmp_path, monkeypatch):
    """［開く］の画面の既定のファイルの種類は、構文ファイル・PDF・Word の文書（Ver420 から）・テキスト・マークダウンを
    まとめた「開けるファイル」（2026-10-27 班長決定）。選んだマークダウンは、そのまま開く。"""
    md = tmp_path / "見本.md"
    md.write_text("# 認否\n認める。\n", encoding="utf-8")
    seen = {}

    def ask(**kw):
        seen.update(kw)
        return str(md)
    monkeypatch.setattr(file_ops.filedialog, "askopenfilename", ask)
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: False)   # 今の文書は保存しない
    window.on_open()
    first = seen["filetypes"][0]
    assert first[0].startswith("開けるファイル")
    assert set(first[1].split()) == {"*.vamd", "*.pdf", "*.docx", "*.txt", "*.md"}
    assert ("すべてのファイル", "*.*") in seen["filetypes"]
    assert window.text.get("1.0", "end-1c").rstrip("\n") == "# 認否\n認める。"


def test_drop_file_from_explorer(window, tmp_path, monkeypatch):
    """エクスプローラーからファイルを落として開く（2026-10-28 班長指示。tkinterdnd2）。落とす先は左右の枠・確認表示・
    エディター。開くのは1つだけで、2つ以上・フォルダ・開けない種類は開かずに知らせる。保存していない変更があれば
    先に尋ねる（［開く］と同じ）。"""
    pytest.importorskip("tkinterdnd2")
    assert window.file_drop
    for w in (window.panes, window.canvas, window.text):
        assert "<<Drop>>" in w.bind()
    shown, asked = [], []
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: shown.append(a[1]))
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: asked.append(a[1]) or False)
    md = tmp_path / "落とした 文書.md"           # 空白を含む名前（tkdnd は {} で囲む）
    md.write_text("# 認否\n認める。", encoding="utf-8")
    other = tmp_path / "一覧.xlsx"
    other.write_bytes(b"PK")
    for data in (f"{{{md}}} {{{md}}}", f"{{{tmp_path}}}", str(other)):
        window.open_dropped(file_ops.dropped_paths(data))
    assert len(shown) == 3 and "1つだけ" in shown[0] and "開けません" in shown[1] and "一覧.xlsx" in shown[2]
    assert not asked and window.raw_text() == PSEUDO            # どれも、エディターは変わらない
    window.open_dropped(file_ops.dropped_paths(f"{{{md}}}"))
    assert asked                                                # 保存していない変更があるので、先に尋ねた
    assert window.raw_text().rstrip("\n") == "# 認否\n認める。"


def test_dropped_paths_keep_backslashes():
    """Windows のパス（円記号）と空白を含むパスを壊さない。"""
    assert file_ops.dropped_paths(r"{C:\Users\a b\文書.vamd} C:\x\y.pdf") == [r"C:\Users\a b\文書.vamd", r"C:\x\y.pdf"]


def test_paste_rejects_other_document_and_plain_text(window, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: shown.append(("error", a[1])))
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: shown.append(("info", a[1])))
    monkeypatch.setattr(window, "clipboard_text", lambda: "ふつうの文章")
    window.on_import()
    monkeypatch.setattr(window, "clipboard_text",
                        lambda: "==== VA Document 文書ID ZZZZZZZZ 版 1 ====\n# 認否\n認める。")
    window.on_import()
    assert [k for k, _ in shown] == ["info", "error"] and "別の文書" in shown[1][1]
    assert window.raw_text() == PSEUDO        # どちらも、エディターは変わらない


def test_paste_warns_about_removed_paragraphs_and_tokens(window, tmp_path, monkeypatch):
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    assert window.on_save()
    warned = []
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: warned.append(a[1]))
    sep = vamd.separator_line(window.session.doc_id, 1, window.session.settings)
    monkeypatch.setattr(window, "clipboard_text", lambda: sep + "\n原告　〔人名Ａ〕\n:=: 準備書面（１）\n# 認否\n")
    window.on_import()
    assert len(warned) == 1 and "消えた段落（1）" in warned[0] and "甲野太郎の主張は争う。" in warned[0]


def test_paste_drops_ai_marker_lines(window, tmp_path, monkeypatch):
    """AI の回答に混ざった内部の目印の行（<?thinking_complete?>）は、取り込むときに除き、状態の欄で知らせる。"""
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    assert window.on_save()
    body = window.raw_text().rstrip("\n")
    sep = vamd.separator_line(window.session.doc_id, 1, window.session.settings)
    monkeypatch.setattr(window, "clipboard_text", lambda: sep + "\n" + body + "\n<?thinking_complete?>\n")
    window.on_import()
    assert "<?thinking_complete?>" not in window.raw_text()
    assert "AI の内部の目印と思われる行 1 行（<?thinking_complete?>）を除きました" in window.status.cget("text")


def _change_outside(window, old, new):
    path = window.session.vamd_path
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def test_save_asks_when_vamd_changed_outside(window, tmp_path, monkeypatch):
    """構文ファイルが外で書き換えられていれば、黙って上書きしない（取り込む・上書きする・やめる）。"""
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    assert window.on_save()
    asked = []

    def fake_changed(choice):
        class D:
            def __init__(self, parent, at_save):
                asked.append(at_save)
                self.result = choice
        return D

    # やめる：保存しない
    _change_outside(window, "争う。", "否認する。")
    monkeypatch.setattr(file_ops, "ChangedOutsideDialog", fake_changed(None))
    assert not window.on_save()
    assert asked == [True] and "否認する。" in window.session.vamd_path.read_text(encoding="utf-8")

    # 取り込む：外の中身をエディターに取り込んでから保存する
    monkeypatch.setattr(file_ops, "ChangedOutsideDialog", fake_changed("import"))
    assert window.on_save()
    assert "〔人名Ａ〕の主張は否認する。" in window.raw_text()
    assert window.session.version == 2 and not window.session.vamd_changed_outside()   # やめたときは保存していない

    # 上書きする：エディターの文章で保存する
    _change_outside(window, "否認する。", "認める。")
    monkeypatch.setattr(file_ops, "ChangedOutsideDialog", fake_changed("overwrite"))
    assert window.on_save()
    assert "否認する。" in window.session.vamd_path.read_text(encoding="utf-8")
    assert not window.session.vamd_changed_outside()


def test_check_outside_while_tk_internal_part_holds_input(window, tmp_path, monkeypatch):
    """選択欄の一覧のような、Tk の中だけの部品が入力を握っている間は、外で書き換えられたかを見に行かず、誤りにもしない
    （grab_current が KeyError になっていた。2026-11-24、班長の PC の誤りの記録で見つけた）。握る部品がなくなれば見に行く。"""
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    assert window.on_save()
    _change_outside(window, "争う。", "否認する。")
    asked = []
    monkeypatch.setattr(ai_ops, "ChangedOutsideDialog",
                        lambda parent, at_save: asked.append(at_save) or type("D", (), {"result": None})())
    window.deiconify()
    window.tk.eval("toplevel .vamd_test_grab; wm geometry .vamd_test_grab 50x50")    # Python の側にない部品
    window.update()
    # 画面を出したときに予約された見回りは、ここで止めて、記録も消す（確かめるのは、この後に呼ぶ見回り）
    if window._focus_job is not None:
        window.after_cancel(window._focus_job)
        window._focus_job = None
    window._declined_stamp = None
    asked.clear()
    try:
        window.tk.eval("grab set .vamd_test_grab")
        window._check_outside()                         # 誤りにならず、見に行かない
        assert not asked
    finally:
        window.tk.eval("grab release .vamd_test_grab; destroy .vamd_test_grab")
        window.update()
    window._check_outside()
    assert asked == [False]
    window.withdraw()


def test_find_and_replace(window):
    """検索と置換（Ctrl+F・Ctrl+H）。すべて置換は Ctrl+Z 1回で戻る。"""
    # ［検索］では置換の欄とボタンを出さず、［置換］では出す。開いたまま切り替わる（2026-10-25 班長指摘）
    window.on_find(False)
    d = window._find_dialog
    replace_parts = (d.replace_label, d.replace_entry, d.buttons["置換"], d.buttons["すべて置換"])
    assert d.title() == "検索" and not any(w.grid_info() for w in replace_parts)
    assert d.buttons["次を検索"].grid_info() and d.buttons["閉じる"].grid_info()
    window.on_find(True)
    assert window._find_dialog is d and d.title() == "置換" and all(w.grid_info() for w in replace_parts)
    window.on_find(False)
    assert d.title() == "検索" and not any(w.grid_info() for w in replace_parts)
    window.on_find(True)
    d.withdraw()
    d.find_var.set("甲野太郎")              # 仮名化した語で検索すると、エディターの記号を探す
    assert d.message.cget("text") == "2 件見つかりました。"
    assert len(window.text.tag_ranges("found")) == 4
    window.text.mark_set("insert", "1.0")
    window.text.tag_remove("sel", "1.0", "end")
    assert d.find(True)
    assert window.text.get("sel.first", "sel.last") == "〔人名Ａ〕" and window.text.index("sel.first") == "1.3"
    assert d.find(True) and window.text.index("sel.first") == "4.0"
    assert d.find(True) and window.text.index("sel.first") == "1.3"     # 最後まで行ったら初めから
    assert d.find(False) and window.text.index("sel.first") == "4.0"    # 前を検索
    # 置換：選んでいる1か所だけ
    d.replace_var.set("乙山花子")
    d.replace_one()
    assert window.raw_text().count("乙山花子") == 1 and window.raw_text().count("〔人名Ａ〕") == 1
    window.text.edit_undo()
    assert window.raw_text() == PSEUDO
    # すべて置換
    d.replace_all()
    assert window.raw_text() == PSEUDO.replace("〔人名Ａ〕", "乙山花子")
    assert d.message.cget("text").startswith("2 件を置換しました")
    window.text.edit_undo()
    assert window.raw_text() == PSEUDO
    # 大文字と小文字
    window._load_text("ABC abc")
    d.find_var.set("abc")
    assert d.message.cget("text") == "2 件見つかりました。"
    d.case_var.set(True)
    d.mark_all()
    assert d.message.cget("text") == "1 件見つかりました。"
    d.close()
    assert not window.text.tag_ranges("found")


def test_save_button_is_always_plain(window, tmp_path):
    """［保存］は、保存していない変更があっても青い枠にしない（2026-10-26 班長決定）。変更は題の「＊」で示す。"""
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    window._update_title()
    # 幅があるときは大きいボタン（2026-10-30 班長指示）。どちらでも、強調の青い枠のスタイルにはしない
    plain = "RibbonLarge.TButton" if window.ribbon.expanded else "Ribbon.TButton"
    assert str(window.save_button.cget("style")) == plain and window.title().startswith("＊")
    assert window.on_save()
    assert str(window.save_button.cget("style")) == plain and not window.title().startswith("＊")


def test_ribbon_groups_and_reflow(window):
    """ボタンは Word のリボンと同じく組に分け、組の名前を下端にそろえて書く。大きいボタンは［選択範囲を仮名化］だけ。
    狭いときは、入らない組を次の段に送る（2026-10-24 班長指示）。"""
    rb = window.ribbon
    titles = [str(g.grid_slaves(row=1, column=0)[0].cget("text")) for g in rb.groups]
    assert titles == [g.title for g in rb.groups]
    assert titles == ["ファイル", "レイアウト", "書式", "挿入", "編集", "表示"]
    # 「AI 連携」は、ほかの組の流れから外し、白い地を枠で囲んで右上に置く（ほかの組が折り返しても動かない。
    # 2026-10-30 班長決定）。囲みが区切りになるので、区切りの線は引かない
    ai = window.ai_ribbon
    assert [g.title for g in ai.groups] == ["AI 連携"] and window.register_button.master is ai.groups[0].body
    box = ai.master
    assert str(box.cget("style")) == "Border.TFrame" and box.pack_info()["side"] == "right"
    assert box.master is rb.master and rb.pack_info()["side"] == "left"
    assert not [c for c in ai.groups[0].winfo_children() if isinstance(c, tk.ttk.Separator)]
    style = tk.ttk.Style(window)
    assert style.lookup("RibbonBox.TFrame", "background") == theme.FIELD_BG
    assert style.lookup("Border.TFrame", "bordercolor") == theme.BORDER
    assert str(window.register_button.cget("style")) == "RibbonBoxLarge.TButton"
    # 囲みとほかの組の高さをそろえる（組の名前の下端をそろえる）
    window._align_ribbon_heights()
    assert rb._min_height == ai._min_height + 4 >= max(g.winfo_reqheight() for g in rb.groups)
    # 文書の種類・ページ番号の選択欄は「レイアウト」の組にあり、左端がそろう（2026-10-25 に「書式」から分け、
    # 2026-10-27 に組の名前を「スタイル」から改めた）
    window.update_idletasks()
    assert window.doc_type_box.winfo_x() == window.page_number_box.winfo_x()
    w = window.doc_type_box
    while w is not None and w not in rb.groups:
        w = w.master
    assert w is _group(window, "レイアウト")
    # 「レイアウト」は選択欄とチェックだけ、文字列に記号を付けるボタンは「書式」（2026-10-25 班長指示）。［見出し］
    # ［箇条書き］［段落番号］は「書式」の左端の列、その右の列に［太字］［傍点］［均等割付］（2026-10-27 班長指示）
    found = {str(b.cget("text")): b for b in _all_buttons(window)}
    rb.reflow(1)          # 幅の決まる前と同じく、［見出し］などを小さいボタンにして置く（大きくするのは次の試験）
    assert not rb.expanded
    assert not any(b.master is _group(window, "レイアウト").body for b in found.values())
    for text in ("見出し", "箇条書き", "段落番号", "太字", "傍点", "均等割付", "表題"):
        assert found[text].master is _group(window, "書式").body, text
    cells = {t: (int(found[t].grid_info()["column"]), int(found[t].grid_info()["row"]))
             for t in ("見出し", "箇条書き", "段落番号", "太字", "傍点", "均等割付")}
    assert cells == {"見出し": (0, 0), "箇条書き": (0, 1), "段落番号": (0, 2), "太字": (1, 0), "傍点": (1, 1), "均等割付": (1, 2)}
    rb.reflow(10 ** 6)
    window.update_idletasks()
    full = sum(g.widths[False] for g in rb.groups)        # ボタンを小さくしたときの幅
    rb.reflow(full + 10)
    assert len(rb._layout) == 1 and not rb.expanded
    assert str(window.register_button.cget("compound")) == "top"
    assert str(window.register_button.cget("text")) == "選択範囲を\n仮名化"     # 大きいボタンは2行
    rb.reflow(full - 10)
    assert len(rb._layout) == 2 and len(rb._layout[1]) == 1                  # 入らない最後の組だけを次の段に
    rb.reflow(400)
    assert len(rb._layout) >= 2
    # どの段も、組を左から詰めて置く（上の段の組の幅に引きずられて間が空かない。2026-10-25 班長指摘）
    window.update_idletasks()
    by_id = {id(g): g for g in rb.groups}
    for row in rb._layout:
        groups = [by_id[i] for i in row]
        assert groups[0].winfo_x() == 0
        for a, b in zip(groups, groups[1:]):
            assert b.winfo_x() == a.winfo_x() + a.winfo_reqwidth()
    rb.reflow(full + 10)
    assert len(rb._layout) == 1


def test_ribbon_grows_open_save_heading_when_room(window):
    """［開く］［保存］［見出し］は、リボンが1段に入りきる幅があれば大きいボタンにし、狭くなったら、組を折り返す前に
    小さくする（2026-10-30 班長指示）。下に残った［閉じる］は、1つで1列にする（右の列の［オプション］は、2026-11-14 の班長指示で
    メニューバーの「ファイル」に移した）。［見出し］の下に残った［箇条書き］［段落番号］は右の列に入らないので2つで1列にし、
    ［太字］などの列は変えない。"""
    rb = window.ribbon
    found = {str(b.cget("text")): b for b in _all_buttons(rb)}
    grown = [found[t] for t in ("開く", "保存", "見出し", "表", "画像")]     # ［表］［画像］は 2026-11-03 班長指示
    rb.reflow(10 ** 6)
    large = sum(g.widths[True] for g in rb.groups)
    small = sum(g.widths[False] for g in rb.groups)
    assert large > small
    window.update_idletasks()
    assert rb.expanded and len(rb._layout) == 1
    for b in grown:
        assert str(b.cget("style")) == "RibbonLarge.TButton" and str(b.cget("compound")) == "top"
        assert int(b.grid_info()["rowspan"]) == 3
    big_images = {str(b.cget("text")): str(b.cget("image")) for b in grown}
    # 大きいアイコンは、面を色分けした自作のアイコン（<名前>_large.svg。2026-10-30 班長決定）
    from va_document import icons
    for name in ("folder_open", "save", "text_header_2", "person_lock", "table", "image"):
        assert icons.icon_png(name, 32, large=True), name
    assert str(window.register_button.cget("image")[0]) == str(
        window.icons.image("person_lock", size=round(32 * window.icons.scale), large=True))
    assert str(found["閉じる"].cget("style")) == "Ribbon.TButton"
    cells = {t: (int(found[t].grid_info()["column"]), int(found[t].grid_info()["row"]))
             for t in ("開く", "保存", "閉じる", "見出し", "箇条書き", "段落番号", "太字", "均等割付")}
    assert cells == {"開く": (0, 0), "保存": (1, 0), "閉じる": (2, 0),
                     "見出し": (0, 0), "箇条書き": (1, 0), "段落番号": (1, 1), "太字": (2, 0), "均等割付": (2, 2)}
    assert "オプション" not in found                      # リボンには置かない（メニューバーの「ファイル」。2026-11-14）
    # 大きくすると入らないが、小さければ入る幅では、小さくして1段のまま（折り返さない）
    rb.reflow(large - 10)
    assert not rb.expanded and len(rb._layout) == 1
    for b in grown:
        assert str(b.cget("style")) == "Ribbon.TButton" and str(b.cget("compound")) == "left"
        assert int(b.grid_info()["rowspan"]) == 1
        assert str(b.cget("image")) != big_images[str(b.cget("text"))]     # 小さいアイコンに戻す
    assert int(found["閉じる"].grid_info()["column"]) == 0 and int(found["閉じる"].grid_info()["row"]) == 2
    # 小さくしても入らなければ折り返す（ボタンは小さいまま）
    rb.reflow(small - 10)
    assert not rb.expanded and len(rb._layout) == 2
    rb.reflow(large + 10)
    assert rb.expanded and len(rb._layout) == 1


@pytest.mark.skipif(app.os.name != "nt", reason="IME の書体は Windows だけ")
def test_ime_composition_font_matches_editor(window):
    """IME の入力中の文字を、エディターと同じ書体で表示する（Tk のままでは System の小さい書体になる）。"""
    from va_document import ime
    family, size = theme.editor_font(window)
    assert ime.set_composition_font(window.text, family, size) >= 1
    face, height = ime.composition_font(window.text)
    assert face == family and height == -round(size * window.text.winfo_fpixels("1i") / 72)


class _Click:
    def __init__(self, x, y):
        self.x, self.y = x, y


def _canvas_point(window, line, col):
    """実名の文章の (行, 字) が、確認表示（canvas の中）のどこにあるか。"""
    page, x, top, h = window.session.layout_map.locate(line, col)
    z = window._render_zoom
    return window._page_x + (x + 1) * z - window.canvas.canvasx(0), \
        window._page_tops[page] + (top + h / 2) * z - window.canvas.canvasy(0), page


def test_editor_and_preview_are_linked(window, monkeypatch):
    """エディターのカーソル → 確認表示のページ、確認表示のクリック → エディターのカーソル。"""
    window.deiconify()
    window.geometry("1200x800")
    text = (Path(__file__).parent / "data" / "長い文書" / "見本.md").read_text(encoding="utf-8")
    window._load_text(text)
    window.update()
    window._layout_pages(keep=False)
    window.update()
    # エディターで最後の行にカーソルを置くと、確認表示は最後のページに送られ、印が付く
    last = len(text.splitlines())
    window.text.mark_set("insert", f"{last}.0")
    window._show_caret()
    window.update()
    n = len(window._preview_doc)
    assert window.page_label.cget("text") == f"{n} / {n}"
    assert window.canvas.find_withtag("caret")
    # 用紙は欄の幅いっぱいで、左右の線はない。線は灰色でページの境目だけ（編集中のページの青い線もない）。文書の上下の
    # 端に帯も線もない
    assert window._page_x == 0 and window._page_size[0] == window.canvas.winfo_width()
    canvas_items = window.canvas.find_all()
    assert not any(window.canvas.itemcget(item, "outline") for item in canvas_items
                   if window.canvas.type(item) == "rectangle")
    borders = [window.canvas.coords(item)[1] for item in canvas_items if window.canvas.type(item) == "line"]
    assert len(borders) == 2 * (n - 1) and 0 < min(borders) and max(borders) < window._total_height()
    assert window._page_tops[0] == 0 and window._total_height() == window._page_tops[-1] + window._page_size[1]
    # 確認表示の字をクリックすると、エディターのカーソルがその字へ動く
    line = last - 3
    col = len(text.splitlines()[line]) - 2     # 本文の字（行頭の「##」などの記号の上ではない）
    x, y, page = _canvas_point(window, line, col)
    window.text.yview_moveto(0)
    window.update()
    window.on_preview_click(_Click(x, y))
    assert window.text.index("insert") == f"{line + 1}.{col}"
    # 文書の終わりの近くの行も、エディターに見え（3分の1の高さまでは送れない）、その行を強調する（2026-10-26 班長指摘。
    # 一番上まで送れないのに決まった高さだけ戻していたため、行が下の端から外れていた）
    window.update()
    info = window.text.dlineinfo("insert")
    assert info is not None and info[1] + info[3] <= window.text.winfo_height()
    assert _on_current_line(window)
    # 動かした先は、エディターの上から3分の1の高さに送り（見えていた行でも）、その行を強調する
    view_h = window.text.winfo_height()
    for scroll_to in (0.0, None):       # 見えていない行へ動かすとき、見えている行へ動かすとき
        if scroll_to is not None:
            window.text.yview_moveto(scroll_to)
            window.update()
        line = len(text.splitlines()) // 2
        col = len(text.splitlines()[line]) // 2
        assert (window.text.dlineinfo(f"{line + 1}.{col}") is None) == (scroll_to is not None)
        x, y, page = _canvas_point(window, line, col)
        window.on_preview_click(_Click(x, y))
        window.update()
        info = window.text.dlineinfo("insert")
        assert info is not None and abs(info[1] - view_h // 3) <= info[3]
        assert _on_current_line(window)
    # 強調する行は、カーソルと一緒に動かす（送ったとき・カーソルを動かしたとき・字を打ったとき）
    window.text.yview_scroll(2, "units")
    assert _on_current_line(window)
    window.text.mark_set("insert", "insert +1line")
    window.text.event_generate("<KeyRelease>", keysym="Down")
    assert _on_current_line(window)
    window.text.insert("insert", "あいう")
    assert _on_current_line(window)
    window.text.delete("insert -3c", "insert")
    assert _on_current_line(window)
    # 検索などでプログラムがカーソルだけを動かしたとき（出来事が来ない）も、しばらくすると置き直す
    window.text.mark_set("insert", "insert -2line")
    end = time.monotonic() + (CURRENT_LINE_WATCH_MS + 200) / 1000
    while time.monotonic() < end:
        window.update()
    assert _on_current_line(window)
    window.withdraw()


def _on_current_line(window):
    """エディターの現在行の強調表示が、カーソルのある行（改行まで）だけに付いているか。キーの出来事は焦点のある部品に
    しか届かないので、届かなかったときは見回り（CURRENT_LINE_WATCH_MS ごと）で置き直すのを待つ。"""
    def ok():
        ranges = window.text.tag_ranges(CURRENT_LINE_TAG)
        line = int(window.text.index("insert").split(".")[0])
        return (len(ranges) == 2 and window.text.index(ranges[0]) == f"{line}.0"
                and window.text.index(ranges[1]) == window.text.index(f"{line}.0 +1line"))
    end = time.monotonic() + (CURRENT_LINE_WATCH_MS + 200) / 1000
    window.update()
    while not ok() and time.monotonic() < end:
        window.update()
    return ok()


def test_current_line_is_highlighted(window):
    """エディター・プレビューは、カーソルのある行の地を薄い灰色にする（青い ▼ と、その点滅は廃止した。2026-11-27 班長指示）。"""
    window.deiconify()
    window.geometry("1200x800")
    window._load_text("１行目の本文\n# 見出し\n==蛍光ペン==の行\n" + "４行目の長い段落。" * 12 + "\n")
    window.update()
    window._layout_pages(keep=False)
    window.update()
    text = window.text
    assert text.tag_cget(CURRENT_LINE_TAG, "background") == theme.CURRENT_LINE_BG == "#f6f6f6"     # Claude のエディターと同じ濃さ
    # ほかの印（蛍光ペン・仮名化した語・検索・選んだ字）の下に置く（それらの色が見える）
    assert text.tag_names()[0] == CURRENT_LINE_TAG
    # ▼ の描画欄は置かない
    assert not [c for c in text.winfo_children() if isinstance(c, tk.Canvas)]
    for index in ("2.1", "3.0", "1.3"):
        text.mark_set("insert", index)
        text.event_generate("<KeyRelease>", keysym="Down")
        assert _on_current_line(window)
    # 行の頭に字を打つ・改行で行を分ける・行をつなぐときも、カーソルのある行だけを強調する
    text.mark_set("insert", "2.0")
    window._show_current_line()
    for edit in (lambda: text.insert("insert", "あ"), lambda: text.insert("insert", "\n"),
                 lambda: text.delete("insert -1c")):
        edit()
        text.event_generate("<KeyRelease>", keysym="a")
        assert _on_current_line(window)
    # プレビュー：カーソルのある段落（エディターの1行）を組んだ行の全部の帯を、地を灰色にした画像で重ねる（▼ は描かない。
    # 段落全体にするのは、エディターの現在行と同じ範囲を示すため。2026-11-27 班長指示）
    window.refresh()
    window.update()
    m = window.session.layout_map
    for col in (1, 100):                # 段落の初めの行・終わりの行のどちらにカーソルがあっても同じ
        text.mark_set("insert", f"4.{col}")
        window._show_caret(scroll=False)
        window.update()
        items = window.canvas.find_withtag("caret")
        assert len(items) == 1 and window.canvas.type(items[0]) == "image"
        assert not [i for i in window.canvas.find_all() if window.canvas.type(i) == "polygon"]
        z = window._render_zoom
        [(page, top, h)] = m.paragraph_bands(3, col)
        assert h > 2.5 * m.locate(3, col)[3]                               # 3行以上に組んだ段落の全部
        assert window.canvas.coords(items[0]) == [window._page_x, window._page_tops[page] + round(top * z)]
        image = window._caret_images[0]
        assert abs(image.height() - h * z) <= 1 and image.width() == window._page_pixels[page].width
    gray = tuple(int(theme.CURRENT_LINE_BG[i:i + 2], 16) for i in (1, 3, 5))
    assert tuple(image.get(1, image.height() // 2)) == gray            # 左の余白（字のない所）は灰色
    darkest = min(sum(image.get(xx, yy)) for xx in range(0, image.width(), 2) for yy in range(0, image.height(), 2))
    assert darkest < sum(gray) // 2                                     # 字は暗いまま（灰色に埋もれない）
    # 行を変えると、帯も動く
    text.mark_set("insert", "1.0")
    window._show_caret(scroll=False)
    window.update()
    items = window.canvas.find_withtag("caret")
    page, x, top, h = window.session.layout_map.locate(0, 0)
    assert len(items) == 1 and window.canvas.coords(items[0])[1] == window._page_tops[page] + round(top * z)
    window.withdraw()


def test_linking_converts_token_lengths(window):
    """エディターは仮名なので、記号と元の語の長さの違いを換算して確認表示と連動する。"""
    window.deiconify()
    window.geometry("1200x800")
    window.update()
    window._layout_pages(keep=False)
    window.update()
    # エディターの行「〔人名Ａ〕の主張は争う。」の「主」→ 実名の行「甲野太郎の主張は争う。」の「主」
    vline = window.text.get("4.0", "4.end")
    assert vline == "〔人名Ａ〕の主張は争う。"
    assert window._token_col(vline, vline.index("主"), to_real=True) == "甲野太郎の主張は争う。".index("主")
    # 確認表示の「主」をクリックすると、エディターの「主」にカーソルが動く
    x, y, _ = _canvas_point(window, 3, "甲野太郎の主張は争う。".index("主"))
    window.on_preview_click(_Click(x, y))
    assert window.text.index("insert") == f"4.{vline.index('主')}"
    window.withdraw()


def test_save_guard_for_tokens_and_separator(window, tmp_path, monkeypatch):
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: errors.append(a[1]))
    # 区切りの行が紛れ込んでいたら、保存しない
    window.text.insert("end", "==== VA Document 文書ID ABCDEFGH 版 1 ====\n")
    assert not window.on_save()
    assert errors and not (tmp_path / "準備書面.pdf").exists()
    assert "Ctrl+Z" in errors[0] and "［貼り付け］で取り込んで" in errors[0]      # AI の回答を Ctrl+V で貼ったときの案内
    # 仮名化した語の記号は、実名に戻して保存する（PDF に記号は出ない）
    window._load_text(TEXT + "〔人名Ａ〕の陳述書による。\n")
    assert window.on_save()
    import pdfcheck
    pdf_text = pdfcheck.text(tmp_path / "準備書面.pdf")
    assert "〔" not in pdf_text and "甲野太郎の陳述書" in pdf_text
    # 仮名化した語にない記号（AI が作った記号など）は、PDF に記号のまま出ることを知らせて尋ねる
    asked = []
    window.text.insert("end", "〔人名Ｚ〕の陳述書。\n")
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(a[1]))
    assert not window.on_save()
    assert asked and "〔人名Ｚ〕" in asked[0]


@pytest.fixture
def quiet_faulthandler():
    """Microsoft Print to PDF のドライバーは、中で Windows の例外（0x80040155）を起こして中で処理する。
    pytest の faulthandler がそれを「fatal exception」と書き出して紛らわしいので、そのテストの間は止める。"""
    import faulthandler
    was = faulthandler.is_enabled()
    faulthandler.disable()
    yield
    if was:
        faulthandler.enable()


@pytest.mark.skipif(app.os.name != "nt", reason="印刷は Windows だけ")
def test_print_to_pdf_printer(window, tmp_path, monkeypatch, quiet_faulthandler):
    """［印刷］：Microsoft Print to PDF に印刷し、実際のサイズ（A4）で、字の位置がずれないことを確かめる。"""
    import pdfcheck
    from va_document import printing
    if "Microsoft Print to PDF" not in printing.printers():
        pytest.skip("Microsoft Print to PDF がない")
    out = tmp_path / "印刷.pdf"
    # VA Document の印刷画面で「Microsoft Print to PDF」・1部・すべてのページを選んだことにする
    chosen = []

    class Choose:
        def __init__(self, parent, data, names, default, show_properties):
            pages = pdfcheck.page_count(data)
            chosen.append((pages, default))
            self.result = ("Microsoft Print to PDF", None, 1, list(range(pages)))
    monkeypatch.setattr(file_ops, "PrintDialog", Choose)
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: errors.append(a[1]))
    real_print = printing.print_pdf
    names = []

    def to_file(data, dc, name, pages=None, output=None, progress=None):
        names.append(name)
        return real_print(data, dc, name, pages, output=str(out), progress=progress)
    monkeypatch.setattr(printing, "print_pdf", to_file)
    # 保存していない変更があれば、先に保存する（2026-10-26 班長指示）。保存先を選ばなければ印刷しない
    from tkinter import filedialog
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda *a, **k: "")
    window.on_print()
    assert not names and not chosen and window.session.version == 0
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda *a, **k: str(tmp_path / "準備書面（１）.pdf"))
    window.on_print()
    assert names == ["準備書面（１）"]       # 印刷の文書の名前は、Word と同じく PDF のファイル名
    assert window.session.version == 1 and (tmp_path / "準備書面（１）.pdf").exists()
    assert window.status.cget("text") == "版 1 を保存し、1 ページをプリンターに送りました。"   # 保存したことも出す
    names.clear()
    window.on_print()                        # 保存していない変更がなければ、保存しない
    assert names == ["準備書面（１）"] and window.session.version == 1
    for _ in range(50):
        if out.exists() and out.stat().st_size:
            break
        time.sleep(0.2)
    w, h = pdfcheck.page_size(out)
    assert pdfcheck.page_count(out) >= 1 and abs(w - 595.3) < 1 and abs(h - 841.9) < 1
    assert not errors and "1 ページをプリンターに送りました" in window.status.cget("text")
    assert chosen[1][1] == "Microsoft Print to PDF"            # 前に使ったプリンターを選んでおく


def _lines(window, a, b):
    return [window.text.get(f"{n}.0", f"{n}.end") for n in range(a, b + 1)]


def _focus_editor(window):
    """エディターにキーボードの焦点を移す。event_generate のキーは焦点のある部品にだけ届き、隠した画面は焦点を
    持てないので、画面を出してから移す（2026-10-27。それまでは前の試験が画面を出したままにしているのに頼っていて、
    単独で走らせると落ち、全体でも Windows が焦点を渡さなかった回に落ちた）。"""
    window.deiconify()
    window.update()
    window.text.focus_force()
    window.update()
    assert window.focus_get() is window.text, "エディターがキーボードの焦点を得られなかった（ほかの画面を操作中など）"


def test_word_shortcuts(window, monkeypatch):
    """Word と同じショートカットキー（Ctrl+E・Ctrl+R・Ctrl+Enter）と、Tk のもとのキーを外したこと。"""
    _focus_editor(window)
    window.text.mark_set("insert", "4.2")
    window.text.event_generate("<Control-Key-e>")
    assert _lines(window, 4, 4) == [":-: 〔人名Ａ〕の主張は争う。"]
    window.text.event_generate("<Control-Key-e>")          # もう一度押すと解除（Word と同じ）
    assert _lines(window, 4, 4) == ["〔人名Ａ〕の主張は争う。"]
    window.text.event_generate("<Control-Key-r>")
    assert _lines(window, 4, 4) == ["--: 〔人名Ａ〕の主張は争う。"]
    window.text.edit_undo()
    window.text.mark_set("insert", "4.0")
    window.text.event_generate("<Control-Return>")
    assert _lines(window, 4, 5) == ["<<<", "〔人名Ａ〕の主張は争う。"]
    # Tk のもとの Ctrl+O（改行を入れる）・Ctrl+K（行末まで消す）は働かない
    opened = []
    monkeypatch.setattr(window, "on_open", lambda: opened.append(True))
    window._bind_keys()
    before = window.raw_text()
    window.text.event_generate("<Control-Key-o>")
    window.text.event_generate("<Control-Key-k>")
    assert window.raw_text() == before and opened == [True]


def test_outline_level_and_plain(window):
    """Alt+Shift+←／→ で見出しのレベルを上げ下げし、Ctrl+Shift+N で標準の本文にする（Word と同じ）。"""
    window._load_text("# 第一\n## 第二\n本文\n- 項目\n--: 以上")
    _focus_editor(window)
    window.text.mark_set("insert", "2.0")
    window.text.event_generate("<Alt-Shift-Left>")
    assert _lines(window, 2, 2) == ["# 第二"]
    window.text.event_generate("<Alt-Shift-Left>")          # # から上げると本文（2026-10-25 班長指示）
    assert _lines(window, 2, 2) == ["第二"]
    window.text.event_generate("<Alt-Shift-Right>")         # 本文を下げると、直前の見出し（#）と同じレベル
    assert _lines(window, 2, 2) == ["# 第二"]
    window.text.event_generate("<Alt-Shift-Right>")
    window.text.event_generate("<Alt-Shift-Right>")
    assert _lines(window, 2, 2) == ["### 第二"]
    # 本文を上げると、直前の見出しと同じレベルの見出し
    window.text.mark_set("insert", "3.0")
    window.text.event_generate("<Alt-Shift-Left>")
    assert _lines(window, 3, 3) == ["### 本文"]
    # 9 から下げると本文
    window._load_text("######### 九")
    window.text.mark_set("insert", "1.0")
    window.text.event_generate("<Alt-Shift-Right>")
    assert _lines(window, 1, 1) == ["九"]
    # Ctrl+Shift+N：選んだ行を標準の本文に（見出し・箇条書き・配置の記号を外す）。Ctrl+Z 1回で戻る
    window._load_text("# 第一\n- 項目\n--: 以上\n1. 番号")
    window.text.tag_add("sel", "1.0", "4.end")
    window.text.event_generate("<Control-Shift-Key-N>")
    assert _lines(window, 1, 4) == ["第一", "項目", "以上", "番号"]
    window.text.edit_undo()
    assert _lines(window, 1, 4) == ["# 第一", "- 項目", "--: 以上", "1. 番号"]
    window.text.tag_remove("sel", "1.0", "end")


def test_heading_bullet_number_buttons(window):
    """［見出し］［箇条書き］［段落番号］：選んだ行の行頭に ## ・- ・1. を付け、ほかの種類の記号とは付け替える。すべて既に
    その種類なら外す（見出しはどの段でも）。空の行・配置の記号の行・表には付けない。Ctrl+Z 1回で戻る（2026-10-25 班長指示）。"""
    window._load_text("本文\n- 項目\n\n:-: 中央\n**# 第一**\n| a | b |")
    window.text.tag_add("sel", "1.0", "6.end")
    window.on_paragraph_kind("## ")
    assert _lines(window, 1, 6) == ["## 本文", "## 項目", "", ":-: 中央", "## **第一**", "| a | b |"]
    window.on_paragraph_kind("## ")                 # すべて見出しなので外す
    assert _lines(window, 1, 6) == ["本文", "項目", "", ":-: 中央", "**第一**", "| a | b |"]
    window.text.edit_undo()
    assert _lines(window, 1, 2) == ["## 本文", "## 項目"]
    window._load_text("### 三段\n  字下げした本文\n2. 番号")
    window.text.tag_add("sel", "1.0", "3.end")
    window.on_paragraph_kind("1. ")                 # 「2. 」も段落番号なので、外さずにそろえる
    assert _lines(window, 1, 3) == ["1. 三段", "1. 字下げした本文", "1. 番号"]
    window.on_paragraph_kind("- ")
    assert _lines(window, 1, 3) == ["- 三段", "- 字下げした本文", "- 番号"]
    window.on_paragraph_kind("- ")
    assert _lines(window, 1, 3) == ["三段", "字下げした本文", "番号"]
    window.text.tag_remove("sel", "1.0", "end")
    window._load_text("# 見出し")                   # 選んでいなければカーソルの行。段の違う見出しも外す
    window.text.mark_set("insert", "1.2")
    window.on_paragraph_kind("## ")
    assert _lines(window, 1, 1) == ["見出し"]
    # 字のない行（まだ打っていない行）にも付け、カーソルを行末に置く。もう一度押すと外す（2026-10-25 班長指示）
    window._load_text("前文\n\n後")
    for mark in ("## ", "- ", "1. "):
        window.text.mark_set("insert", "2.0")
        window.on_paragraph_kind(mark)
        assert _lines(window, 2, 2) == [mark] and window.text.index("insert") == f"2.{len(mark)}"
        window.on_paragraph_kind(mark)
        assert _lines(window, 2, 2) == [""]
    window.text.mark_set("insert", "2.0")             # 続けて打てば、その種類の行になる
    window.on_paragraph_kind("- ")
    window.text.insert("insert", "項目")
    assert _lines(window, 1, 3) == ["前文", "- 項目", "後"]
    # 字のある行と一緒に選んだ字のない行（1行の空き）には付けない
    window._load_text("一\n\n二")
    window.text.tag_add("sel", "1.0", "3.end")
    window.on_paragraph_kind("- ")
    assert _lines(window, 1, 3) == ["- 一", "", "- 二"]
    window.text.tag_remove("sel", "1.0", "end")
    # Alt+Shift+← も、字のない行を見出しの記号だけの行にする（直前の見出しと同じレベル）
    window._load_text("### 三\n")
    window.text.mark_set("insert", "2.0")
    window.on_outline(-1)
    assert _lines(window, 2, 2) == ["### "] and window.text.index("insert") == "2.4"
    window.on_outline(1)                             # 下げるのは、ふつうの見出しと同じ
    assert _lines(window, 2, 2) == ["#### "]
    window._load_text("### 三\n本文\n")
    window.text.mark_set("insert", "2.0")
    window.on_outline(1)                             # 本文を下げても、直前の見出しと同じレベル（2026-10-25 班長指示）
    assert _lines(window, 2, 2) == ["### 本文"]
    window.text.mark_set("insert", "3.0")
    window.on_outline(1)                             # 字のない行も同じ
    assert _lines(window, 3, 3) == ["### "]
    window._load_text("# 第一\n")
    window.text.mark_set("insert", "2.0")
    window.on_outline(-1)
    assert _lines(window, 2, 2) == ["# "]
    window.on_outline(-1)                            # # から上げると、字のない行に戻る
    assert _lines(window, 2, 2) == [""]
    # 前に見出しがなければ、上げても下げても ##（［見出し］と同じ。2026-10-25 班長指示）
    for step in (-1, 1):
        window._load_text("前文\n")
        window.text.mark_set("insert", "2.0")
        window.on_outline(step)
        assert _lines(window, 2, 2) == ["## "]
        window.text.mark_set("insert", "1.0")
        window.on_outline(step)                      # 本文の行も同じ
        assert _lines(window, 1, 1) == ["## 前文"]
    # 見出しと本文を一緒に選んだときは、見出しのレベルだけを変え、本文は変えない（2026-11-04 班長指摘）
    for step, want in ((1, ["### 一", "本文", ":-: #### 二", "本文", "#### 三", "本文"]),
                       (-1, ["# 一", "本文", ":-: ## 二", "本文", "## 三", "本文"])):
        window._load_text("## 一\n本文\n:-: ### 二\n本文\n### 三\n本文\n")
        window.text.tag_add("sel", "1.0", "6.end")
        window.on_outline(step)
        assert _lines(window, 1, 6) == want
    window._load_text("本文\n## 一\n")
    window.text.tag_add("sel", "1.0", "2.end")
    window.on_outline(-1)
    window.on_outline(-1)                            # 見出しが本文に戻っても、選んだ本文は見出しにしない
    assert _lines(window, 1, 2) == ["本文", "一"]


def test_marks_are_blue(window):
    """配置・改ページなどの記号は、青い字（確認表示の印と同じ色）で示す。記号として読まれない所は色を付けない。"""
    window._load_text(":=: 準備書面\n本文に--: と書いた\n<<<\n| :-: 科目 | 金額 |\n|---|---|\n| a | b |")
    window._highlight()
    ranges = window.text.tag_ranges("mark")
    marked = [window.text.get(a, b) for a, b in zip(ranges[0::2], ranges[1::2])]
    assert [m for m in marked if m.strip() in (":=:", ":-:", "--:", "<<<")] == [":=: ", "<<<", ":-: "]
    assert window.text.tag_cget("mark", "foreground") == theme.ACCENT


def test_markdown_marks_are_blue(window):
    """見出しの #・箇条書きの「- 」・段落番号の「1. 」・表の | と区切りの行も、同じ青い字で示す（読まれる所だけ）。"""
    window._load_text("# 見出し\n- 項目\n1. 番号\n| A | B |\n|---|---|\n| a | b |\n--: 以上\n# 見出しにしない")
    window._highlight()
    ranges = window.text.tag_ranges("mark")
    marked = [window.text.get(a, b) for a, b in zip(ranges[0::2], ranges[1::2])]
    assert marked == ["# ", "- ", "1. ", "|", "|", "|", "|---|---|", "|", "|", "|", "--: "]


def test_no_first_line_indent_button(window):
    """［字下げ］はなくした（2026-10-28 班長決定。字下げは行頭の全角空白で書く）。配置のボタンは、行頭の全角空白を
    記号の後ろに残し、もう一度押すと記号だけを外す。全角空白は記号の青い字にしない。"""
    from tkinter import ttk
    assert "字下げ" not in {str(b.cget("text")) for b in _widgets(window, ttk.Button, skip_toplevel=True)}
    window._load_text("　前文\n# 見出し")
    window.text.mark_set("insert", "1.0")
    window.on_align("--: ")
    assert _lines(window, 1, 1) == ["--: 　前文"]
    window._highlight()
    ranges = window.text.tag_ranges("mark")
    marked = [window.text.get(a, b) for a, b in zip(ranges[0::2], ranges[1::2])]
    assert "--: " in marked and not any("　" in m for m in marked)
    window.on_align("--: ")
    assert _lines(window, 1, 1) == ["　前文"]


def test_buttons_have_icons(window):
    """ボタンにアイコン（Fluent UI System Icons）を付ける。"""
    from tkinter import ttk
    from va_document import icons
    assert window.icons is not None

    def buttons(w):
        # メインの画面のボタンだけ（検索と置換などの別の画面〔Toplevel〕は見ない）
        return _widgets(w, ttk.Button, skip_toplevel=True)
    found = {str(b.cget("text")).replace("\n", ""): b for b in buttons(window)}
    for text in ("開く", "保存", "印刷", "閉じる", "選択範囲を仮名化", "コピー", "貼り付け", "表題", "中央", "右", "インデント", "太字", "均等割付",
                 "見出し", "箇条書き", "段落番号", "改ページ", "セクション区切り", "ヘッダー", "検索", "置換", "蛍光ペン", "パスをコピー"):
        assert found[text].cget("image"), text
        # リボンの大きいボタン（［選択範囲を仮名化］と、幅があるときの［開く］［保存］［見出し］）はアイコンの下に字、
        # ほかはアイコンの右に字
        large = text == "選択範囲を仮名化" or (window.ribbon.expanded and text in ("開く", "保存", "見出し"))
        assert str(found[text].cget("compound")) == ("top" if large else "left"), text
    # アイコンだけのボタンはない（ページ送り・表示倍率のボタンは、2026-10-30 になくした）
    assert not [b for b in buttons(window) if not str(b.cget("text")) and b.cget("image")]
    # 使うアイコンのファイルと、ライセンスの文書がそろっている
    for name in icons.BUTTON_ICONS.values():
        assert (icons.ICON_DIR / f"{name}.svg").exists(), name
    assert "MIT License" in (icons.ICON_DIR / "LICENSE").read_text(encoding="utf-8")
    assert icons.icon_png("save", 24)[:4] == b"\x89PNG"
    # Office の色付きアイコンのように2色（塗りつぶし版を薄い青で下に敷く。2026-10-24 班長指示）
    for name in icons.BUTTON_ICONS.values():
        assert (icons.ICON_DIR / f"{name}_filled.svg").exists(), name
    pix = icons.icon_image("save", 32)
    tint = tuple(int(theme.ICON_TINT[k:k + 2], 16) for k in (1, 3, 5))
    colors = {pix.getpixel((x, y))[:3] for x in range(pix.width) for y in range(pix.height) if pix.getpixel((x, y))[3] == 255}
    assert tint in colors and tuple(int(theme.TEXT[k:k + 2], 16) for k in (1, 3, 5)) in colors


def test_buttons_have_tooltips(window):
    """ボタンにマウスを重ねると説明が出る（ショートカットキーも書く）。"""
    from va_document import tooltip
    tips = {t.text: t for t in window._tooltips}
    assert len(window._tooltips) >= 20
    assert "Ctrl+S" in tooltip.TIPS["保存"] and tooltip.TIPS["保存"] in tips
    assert "Ctrl+B" in tooltip.TIPS["太字"] and tooltip.TIPS["太字"] in tips
    assert "Ctrl+I" in tooltip.TIPS["インデント"] and tooltip.TIPS["インデント"] in tips
    assert "Ctrl+Alt+H" in tooltip.TIPS["蛍光ペン"] and tooltip.TIPS["蛍光ペン"] in tips
    # メインの画面のボタン・チェックは、すべて説明を持つ（ボタンを足したときの付け忘れを見つける。2026-10-25、
    # ［ヘッダー］に説明がなかった）
    def labels(w):
        for c in _widgets(w, (tk.ttk.Button, tk.ttk.Radiobutton, tk.Checkbutton), skip_toplevel=True):
            yield str(c.cget("text")).replace("\n", ""), c
    missing = [text for text, c in labels(window) if text and text not in tooltip.TIPS]
    assert not missing, missing
    assert tooltip.TIPS["ヘッダー"] in tips
    # 「文書の種類」「ページ番号」は、名前のラベルと選択欄の両方に説明を付ける（2026-11-03 班長指摘）
    for name, box in (("文書の種類", window.doc_type_box), ("ページ番号", window.page_number_box)):
        owners = [t.widget for t in window._tooltips if t.text == tooltip.TIPS[name]]
        assert box in owners and any(isinstance(w, tk.ttk.Label) for w in owners), name
    window.deiconify()
    window.update()
    tip = tips[tooltip.TIPS["保存"]]
    tip.show()
    assert tip._win is not None and tip._win.winfo_exists()
    tip.hide()
    assert tip._win is None
    window.withdraw()


def test_app_icon_exists():
    """アプリのアイコン（16〜256 画素の7つの大きさ）がある。scripts/generate_icon.py で作り直せる。"""
    from PIL import Image
    path = app.window_icon_path()
    assert path.exists()
    with Image.open(path) as im:
        assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(im.info["sizes"])


def test_window_position_is_restored(tmp_path):
    """閉じたときのウィンドウの大きさ・位置・確認表示の幅を、次の起動で戻す（Tk を作り直すので、別のプロセスで試す）。"""
    import subprocess
    import sys
    src = str(Path(__file__).resolve().parents[1] / "src")
    settings = tmp_path / "settings.json"
    common = (f"import sys, json, pathlib; sys.path.insert(0, {src!r})\n"
              "from va_document import config, app\n"
              f"config.config_path = lambda: pathlib.Path({str(settings)!r})\n"
              f"cfg = config.load(); cfg.vamd_folder = {str(tmp_path)!r}\n"
              "w = app.MainWindow(cfg=cfg)\n")
    first = common + ("w.geometry('1100x720+60+70'); w.update()\n"
                      "w.panes.sash_place(0, 500, 0); w.update()\n"
                      "w.doc_type_box.set('内容証明'); w.page_number_box.set('右上'); w.on_settings_changed()\n"
                      "w.on_close()\n")
    second = common + ("w.after(2000, w.quit); w.mainloop()\n"
                       "print(w.geometry()); print(w.panes.sash_coord(0)[0]);"
                       "print(w.session.settings.doc_type, w.session.settings.page_number); w.destroy()\n")
    subprocess.run([sys.executable, "-c", first], check=True, timeout=60)
    saved = json.loads(settings.read_text(encoding="utf-8"))
    assert saved["window_geometry"] == "1100x720+60+70" and saved["window_zoomed"] is False
    assert abs(saved["preview_width"] - 500) <= 2
    out = subprocess.run([sys.executable, "-c", second], check=True, timeout=60, capture_output=True, text=True).stdout
    geometry, sash, doc_type, page_number = out.split()
    assert geometry == "1100x720+60+70" and abs(int(sash) - 500) <= 2
    # 文書の種類・ページ番号も、前回の設定で始まる
    assert (doc_type, page_number) == ("Naiyou", "TopRight")
    # ナビゲーションを出して閉じたら、次の起動でも、同じ幅のナビゲーションと同じ幅のプレビューで出す（2026-11-24）
    # 起動から幅を置き直す間（app.SASH_RESTORE_SECONDS）が過ぎてから操作する
    # （3つの欄が入るよう、ウィンドウを広げてから。ナビゲーションは、題の行が入る幅〔約 300 画素〕より狭くならない）
    third = common + ("w.after(2000, w.quit); w.mainloop(); w.geometry('1400x720+60+70'); w.update()\n"
                      "w.nav_var.set(True); w.on_toggle_navigation(); w.update()\n"
                      "w.panes.sash_place(1, 780, 0); w.panes.sash_place(0, 320, 0); w.update()\n"
                      "w.on_close()\n")
    subprocess.run([sys.executable, "-c", third], check=True, timeout=60)
    saved = json.loads(settings.read_text(encoding="utf-8"))
    assert saved["nav_visible"] is True and abs(saved["nav_width"] - 320) <= 2
    assert abs(saved["preview_width"] - (780 - 326)) <= 2
    fourth = common + ("w.after(2000, w.quit); w.mainloop()\n"
                       "print(w.nav_shown(), w.nav_check.cget('text'), w.nav_var.get());"
                       "print(w.panes.sash_coord(0)[0], w.panes.sash_coord(1)[0]); w.destroy()\n")
    out = subprocess.run([sys.executable, "-c", fourth], check=True, timeout=60, capture_output=True, text=True,
                         encoding="utf-8", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}).stdout
    shown, _, checked, nav, edge = out.split()
    assert shown == "True" and checked in ("1", "True") and abs(int(nav) - 320) <= 2 and abs(int(edge) - 780) <= 2
    # プレビューを隠して閉じたら、次の起動でも隠したまま（ナビゲーションは出したまま。2026-11-24）。題の行の高さも、
    # エディターの上の行にそろう
    fifth = common + ("w.after(2000, w.quit); w.mainloop()\n"
                      "w.preview_var.set(False); w.on_toggle_preview(); w.update(); w.on_close()\n")
    subprocess.run([sys.executable, "-c", fifth], check=True, timeout=60)
    saved = json.loads(settings.read_text(encoding="utf-8"))
    assert saved["preview_visible"] is False and abs(saved["preview_width"] - (780 - 326)) <= 2
    sixth = common + ("w.after(2000, w.quit); w.mainloop()\n"
                      "print(w.preview_shown(), w.preview_var.get(), w.nav_shown(), len(w.panes.panes()),"
                      " abs(w._nav_head.winfo_height() - w._name_row.winfo_height()) <= 1, w.panes.sash_coord(0)[0])"
                      "; w.destroy()\n")
    out = subprocess.run([sys.executable, "-c", sixth], check=True, timeout=60, capture_output=True, text=True).stdout
    preview, checked, nav, count, same_height, sash = out.split()
    assert (preview, checked, nav, count, same_height) == ("False", "False", "True", "2", "True")
    assert abs(int(sash) - 320) <= 2


def test_off_screen_geometry_is_ignored():
    """前回の位置が、今つながっていない画面（外したモニターなど）にあれば使わない。"""
    assert app._on_screen("1100x720+60+70")
    assert not app._on_screen("1100x720+-30000+70")
    assert not app._on_screen("こわれた値")
    assert not app._on_screen("10x10+60+70")


def test_toc_button_and_preview_link(window):
    """［目次］：カーソルの行の前に [TOC:3] を入れ（段数は手で直す。2026-10-24 班長指示）、青い字で示す。
    目次の行をクリックしても連動が崩れない。"""
    window._load_text("# 第一\n本文\n# 第二\n本文")
    window.text.mark_set("insert", "1.0")
    next(b for b in _all_buttons(window.ribbon) if str(b.cget("text")) == "目次").invoke()
    assert _lines(window, 1, 2) == ["[TOC:3]", "# 第一"]
    window.refresh()
    ranges = window.text.tag_ranges("mark")
    assert "[TOC:3]" in [window.text.get(a, b) for a, b in zip(ranges[0::2], ranges[1::2])]
    m = window.session.layout_map
    page, x, top, h = m.locate(0, 0)          # [TOC] の行 → 目次の1行目
    assert page == 0
    assert m.hit(page, x + 1, top + h / 2)[0] == 0


def test_bold_shortcut_and_highlight(window):
    """Ctrl+B（on_bold）で選んだ字を **…** で囲み、もう一度で外す。記号は青、中の字は太字で示す（2026-10-24）。"""
    window._load_text("# 認否\n主張は争う。\n")
    window.text.tag_add("sel", "2.0", "2.2")           # 「主張」
    window.on_bold()
    assert window.text.get("2.0", "2.end") == "**主張**は争う。"
    assert window.text.get("sel.first", "sel.last") == "主張"
    window._highlight()
    marks = window.text.tag_ranges("mark")
    texts = [window.text.get(a, b) for a, b in zip(marks[0::2], marks[1::2])]
    assert texts.count("**") == 2
    bold = window.text.tag_ranges("bold")
    assert [window.text.get(a, b) for a, b in zip(bold[0::2], bold[1::2])] == ["主張"]
    window.on_bold()                                     # 同じ選択でもう一度押すと外す
    assert window.text.get("2.0", "2.end") == "主張は争う。"
    window.text.edit_undo()                              # Ctrl+Z 1回で、外す前に戻る
    assert window.text.get("2.0", "2.end") == "**主張**は争う。"

def test_outline_and_plain_on_heading_wrapped_in_bold(window):
    """「**# 見出し**」の行も、Alt+Shift+→（on_outline）・Ctrl+Shift+N（on_plain）で見出しとして扱う。"""
    window._load_text("**# 請求原因**\n本文。\n")
    window.text.mark_set("insert", "1.3")
    window.on_outline(1)
    assert window.text.get("1.0", "1.end") == "## **請求原因**"
    window.on_plain()
    assert window.text.get("1.0", "1.end") == "**請求原因**"

def test_bold_on_heading_line_applies_to_same_level(window):
    """見出しの行で［太字］を押すと、同じ段の見出しの行をすべて太字にし、もう一度で外す（2026-10-24 班長決定）。
    見出しの一部だけを選んだときは、その字だけ。本文の行で、選ばずに押しても何もしない。"""
    window._load_text("# 請求の原因\n本文。\n## 小見出し\n**# 被告の主張**\n本文の**一部**。\n# 結論\n")

    def lines():
        return window.raw_text().split("\n")[:6]
    window.text.mark_set("insert", "1.2")
    window.on_bold()
    # 「**# 見出し**」の形は、VA Documentが書く形（# **見出し**）にそろう
    assert lines() == ["# **請求の原因**", "本文。", "## 小見出し", "# **被告の主張**", "本文の**一部**。", "# **結論**"]
    window.text.mark_set("insert", "6.3")
    window.on_bold()                                     # 太字の見出しで押すと、同じ段の太字をすべて外す
    assert lines() == ["# 請求の原因", "本文。", "## 小見出し", "# 被告の主張", "本文の**一部**。", "# 結論"]
    window.text.edit_undo()                              # Ctrl+Z 1回で、外す前に戻る
    assert lines()[0] == "# **請求の原因**" and lines()[5] == "# **結論**"
    # 見出しの字をすべて選んだときも、同じ段をそろえる
    window._load_text("# 請求の原因\n# 結論\n")
    window.text.tag_add("sel", "1.2", "1.end")
    window.on_bold()
    assert window.raw_text().split("\n")[:2] == ["# **請求の原因**", "# **結論**"]
    # 見出しの一部だけを選んだときは、その字だけ
    window._load_text("# 請求の原因\n# 結論\n")
    window.text.tag_add("sel", "1.2", "1.4")
    window.on_bold()
    assert window.raw_text().split("\n")[:2] == ["# **請求**の原因", "# 結論"]
    # 本文の行で、選ばずに押しても何もしない
    window._load_text("本文。\n")
    window.text.mark_set("insert", "1.1")
    window.on_bold()
    assert window.raw_text().startswith("本文。")

def test_bold_on_heading_sets_upper_levels_and_releases_lower_levels(window):
    """［太字］も、見出しの前の空行と同じく、見出しの行全体を選んで押せる。下の段の見出しで付けると上の段の見出しも
    太字にし、上の段の見出しで外すと下の段の見出しの太字も外す（2026-10-28 班長指示）。"""
    src = "# 第一\n本文。\n## 小一\n本文。\n### 細一\n本文。\n# 第二\n## 小二\n### 細二\n本文。"

    def lines():
        return window.raw_text().rstrip("\n").split("\n")

    def select(a, b):
        window.text.tag_remove("sel", "1.0", "end")
        window.text.tag_add("sel", a, b)
        window.text.mark_set("insert", b)
    window._load_text(src)
    select("3.0", "3.end")                               # 段2の行全体（改行を含まない）で付ける：段1・段2が太字に
    window.on_bold()
    assert lines() == ["# **第一**", "本文。", "## **小一**", "本文。", "### 細一", "本文。", "# **第二**", "## **小二**",
                       "### 細二", "本文。"]
    # 選んだ行全体を選び直し（続けて押せる）、カーソルは同じ字のところ（行末）に残る
    assert window._selection() == "## **小一**"
    assert window.text.compare("insert", "==", "3.end")
    select("9.0", "10.0")                                # 段3の行全体（行末の改行まで）で付ける：段3も太字に
    window.on_bold()
    assert lines()[4] == "### **細一**" and lines()[8] == "### **細二**"
    select("8.0", "8.end")                               # 段2で外す：段2・段3が外れ、段1は残る
    window.on_bold()
    assert lines() == ["# **第一**", "本文。", "## 小一", "本文。", "### 細一", "本文。", "# **第二**", "## 小二",
                       "### 細二", "本文。"]
    assert window.text.compare("insert", "==", "8.end")
    window.text.edit_undo()                             # Ctrl+Z 1回で、外す前に戻る
    assert lines()[2] == "## **小一**" and lines()[4] == "### **細一**"
    window.text.tag_remove("sel", "1.0", "end")
    window.text.mark_set("insert", "7.5")                # 選ばずに段1で外す：すべて外れる
    window.on_bold()
    assert window.raw_text().rstrip("\n") == src
    assert window.text.get("insert", "insert lineend") == "二"   # 「# **第|二**」のカーソルは「第」の後のまま

def test_wrap_buttons_on_whole_and_multiple_lines(window):
    """［太字］［傍点］［蛍光ペン］［均等割付］は、行の先頭から選んだ行を、行頭の記号の後ろから囲む（見出しの
    「# **見出し**」と同じ）。行末の改行まで選んでもよい。行をまたいで選ぶと、行ごとに囲み（空の行・表・改ページなどの
    記号の行は飛ばす）、すべて囲まれていれば外す。囲んだ字は選んだままにする（2026-10-28 班長指示）。"""
    def lines(k):
        return window.raw_text().split("\n")[:k]

    def select(a, b):
        window.text.tag_remove("sel", "1.0", "end")
        window.text.tag_add("sel", a, b)
        window.text.mark_set("insert", b)
    window._load_text("- 項目\n:-: 本文\n")
    select("1.0", "2.0")                                 # 行末の改行まで
    window.on_bold()
    select("2.0", "2.end")
    window.on_dots()
    assert lines(2) == ["- **項目**", ":-: *本文*"]
    assert window._selection() == "本文"
    window.on_dots()                                     # 続けて押すと外す
    assert lines(2) == ["- **項目**", ":-: 本文"]
    # 行全体を囲んだ形（「**:-: 本文**」）は、記号の後ろを囲んだ形として外す
    window._load_text("**:-: 本文**\n")
    select("1.0", "1.end")
    window.on_bold()
    assert lines(1) == [":-: 本文"]
    # 行をまたぐ選択：行ごとに囲み、空の行・表・改ページの行は飛ばす。一部の行が囲まれていれば、残りを囲む
    src = "第一の**文**。\n\n<<<\n| a | b |\n## 見出し\n最後の文。\n"
    window._load_text(src)
    select("1.3", "6.3")
    window.on_highlight()
    assert lines(6) == ["第一の==**文**。==", "", "<<<", "| a | b |", "## ==見出し==", "==最後の==文。"]
    assert window._selection().startswith("**文**。") and window._selection().endswith("最後の")
    window.on_highlight()                                # すべて囲まれていれば、すべて外す
    assert window.raw_text() == src
    select("5.0", "6.end")
    window.on_bold()
    window.on_bold()
    assert window.raw_text() == src
    window.text.edit_undo()                              # Ctrl+Z 1回で、1回分だけ戻る
    assert lines(6)[4:] == ["## **見出し**", "**最後の文。**"]
    select("5.0", "6.end")
    window.on_distribute()                               # 字数は、太字の記号を除いて数える
    assert lines(6)[4:] == ["## [**見出し**]{3}", "[**最後の文。**]{5}"]
    window.on_distribute()
    assert lines(6)[4:] == ["## **見出し**", "**最後の文。**"]


def test_align_skips_blank_lines_and_keeps_selection(window):
    """［表題］［中央］［右］は、字のある行と一緒に選んだ字のない行には付けない（字のない行だけを選んだときは付け、
    カーソルを行末に置く。［見出し］と同じ）。「**:-: 本文**」の行でも選択を残す（2026-10-28 班長指示）。"""
    window._load_text("本文一。\n\n本文二。\n\n")
    window.text.tag_add("sel", "1.0", "3.end")
    window.on_align(CENTER_MARK)
    assert window.raw_text().split("\n")[:3] == [":-: 本文一。", "", ":-: 本文二。"]
    window.text.tag_remove("sel", "1.0", "end")
    window.text.mark_set("insert", "4.0")
    window.on_align(RIGHT_MARK)
    assert window.raw_text().split("\n")[3] == "--: " and window.text.index("insert") == "4.4"
    window._load_text("**:-: 準備書面**\n")
    window.text.tag_add("sel", "1.0", "1.end")
    window.on_align(RIGHT_MARK)
    assert window.raw_text().split("\n")[0] == "--: **準備書面**"
    assert "準備書面" in window._selection()             # 選択が残り、続けて押すと外す
    window.on_align(RIGHT_MARK)
    assert window.raw_text().split("\n")[0] == "**準備書面**"


def test_bold_heading_keeps_selection(window):
    """見出しの字をすべて選んで［太字］を押すと、見出しの字を選んだままにする（続けて押すと外す。2026-10-28 班長指示）。"""
    window._load_text("# 請求の原因\n# 結論\n")
    window.text.tag_add("sel", "1.2", "1.end")
    window.on_bold()
    assert window._selection() == "**請求の原因**"
    window.on_bold()
    assert window.raw_text().split("\n")[:2] == ["# 請求の原因", "# 結論"]
    assert window._selection() == "請求の原因"


def test_line_mark_in_table_goes_before_table(window):
    """表の中で［改ページ］などを押すと、表の前に入れる（表を分けない。2026-10-28 班長指示）。"""
    window._load_text("本文。\n| a | b |\n|---|---|\n| c | d |\n")
    window.text.mark_set("insert", "4.3")
    window.on_line_mark(PAGE_BREAK_MARK)
    assert window.raw_text().split("\n")[:5] == ["本文。", "<<<", "| a | b |", "|---|---|", "| c | d |"]


def test_outline_and_paragraph_kind_on_aligned_heading(window):
    """配置の記号の付いた行（「:-: ## 見出し」「:-: 本文」）も、Alt+Shift+←／→・［見出し］［箇条書き］で見出しとして扱い、
    配置の記号を残す。Alt+Shift+←／→ は、配置の記号の付いた本文も見出しにし、上げ下げが見出しと本文の間で回る
    （2026-10-28 班長指示）。"""
    window._load_text(":-: ## 見出し\n:-: 本文\n")
    window.text.mark_set("insert", "1.6")
    window.on_outline(1)
    assert window.raw_text().split("\n")[0] == ":-: ### 見出し"
    window.on_outline(-1)
    assert window.raw_text().split("\n")[0] == ":-: ## 見出し"
    window.on_paragraph_kind(HEADING_BUTTON_MARK)        # 見出しで押すと外す
    assert window.raw_text().split("\n")[0] == ":-: 見出し"
    window._load_text("**:-: ## 見出し**\n:-: 本文\n")
    window.text.mark_set("insert", "1.6")
    window.on_paragraph_kind(BULLET_MARK)
    assert window.raw_text().split("\n")[0] == ":-: - **見出し**"
    # 「:-: 本文」：→ で見出し（前に見出しがなければ ##）、← で上げて # から本文に戻り、また ← で見出しになる
    window.text.mark_set("insert", "2.5")
    seen = []
    for step in (1, -1, -1, -1):
        window.on_outline(step)
        seen.append(window.raw_text().split("\n")[1])
    assert seen == [":-: ## 本文", ":-: # 本文", ":-: 本文", ":-: ## 本文"]
    window.on_paragraph_kind(HEADING_BUTTON_MARK)        # ［見出し］は配置の記号の付いた見出しを外すが、本文には付けない
    window.on_paragraph_kind(HEADING_BUTTON_MARK)        # （2026-10-25 班長指示）
    assert window.raw_text().split("\n")[1] == ":-: 本文"
    # ->N・[HEADER] の付いた行は、見出しにならないので変えない
    window._load_text("->2 本文\n")
    window.on_outline(1)
    assert window.raw_text().split("\n")[0] == "->2 本文"


def test_ribbon_button_keeps_focus_in_editor(window):
    """リボンのボタンを押しても、キーボードの焦点はエディターに残り、続けて Ctrl+Z で戻せる（2026-10-28 班長指摘。
    ttk のボタンは押すと焦点を取るので、ボタンで書式を付けた後の Ctrl+Z がエディターに届かなかった）。"""
    def buttons(w):
        for child in w.winfo_children():
            if isinstance(child, tk.ttk.Button) and str(child.cget("style")).startswith("Ribbon"):
                yield child
            yield from buttons(child)
    found = list(buttons(window))
    assert found and all(not b.cget("takefocus") for b in found)
    window._load_text("本文。\n")
    _focus_editor(window)
    window.text.mark_set("insert", "1.0")
    center =next(b for b in found if b.cget("text") == "中央")
    center.event_generate("<ButtonPress-1>", x=3, y=3)
    center.event_generate("<ButtonRelease-1>", x=3, y=3)
    window.update()
    assert window.raw_text().startswith(":-: 本文。")
    assert window.focus_get() is window.text
    window.text.event_generate("<Control-z>")
    window.update()
    assert window.raw_text().startswith("本文。")


def test_heading_space_by_selecting_heading(window):
    """見出しの行全体（または見出しの字すべて）を選んで Enter を押すと、同じ段の見出しの前に空行を1行ずつ入れ、
    前が空行の見出しで同じ操作をすると外す（［太字］と同じ切り替え。2026-10-28 班長決定）。ほかの見出しには、
    文書の先頭・改ページの直後・直前が空行・直前が見出しのときは入れない。Ctrl+Z 1回で戻る。"""
    src = "# 第一\n## 小\n本文。\n# 第二\n本文。\n\n# 第三\n本文。\n<<<\n# 第四\n本文。\n## 小２\n本文。"

    def lines():
        return window.raw_text().rstrip("\n").split("\n")

    def select(a, b):
        window.text.tag_remove("sel", "1.0", "end")
        window.text.tag_add("sel", a, b)
        window.text.mark_set("insert", b)
    assert window.text.bind("<Return>") and not window.text.bind("<BackSpace>")
    window._load_text(src)
    select("4.0", "4.end")                               # 行全体（改行を含まない）
    assert window.on_editor_return() == "break"
    # 「# 第二」の前だけに入る（第一は文書の先頭、第三は前が空行、第四は改ページの直後。## は段が違う）
    assert lines() == ["# 第一", "## 小", "本文。", "", "# 第二", "本文。", "", "# 第三", "本文。", "<<<", "# 第四", "本文。",
                       "## 小２", "本文。"]
    assert not window.text.tag_ranges("sel")
    select("5.2", "5.end")                               # 見出しの字すべて（前が空行の見出し）：外す
    assert window.on_editor_return() == "break"
    assert lines() == ["# 第一", "## 小", "本文。", "# 第二", "本文。", "# 第三", "本文。", "<<<", "# 第四", "本文。",
                       "## 小２", "本文。"]
    window.text.edit_undo()                              # Ctrl+Z 1回で、外す前に戻る
    assert lines()[3:8] == ["", "# 第二", "本文。", "", "# 第三"]
    # 行末の改行まで選んだときも行全体。選んだ見出しには、前が見出しでも選んだとおり入れ、同じ段のほかの見出しには
    # 規則どおり入れる
    window._load_text(src)
    select("2.0", "3.0")
    assert window.on_editor_return() == "break"
    assert lines()[:3] == ["# 第一", "", "## 小"] and lines()[-3:] == ["", "## 小２", "本文。"]
    # 選んでいないとき（見出しの行の先頭でも）・見出しの一部・本文の行・2行にまたがる選択では、エディターのもとの
    # 働きのまま（None を返す）
    window._load_text(src)
    window.text.tag_remove("sel", "1.0", "end")
    window.text.mark_set("insert", "4.0")
    assert window.on_editor_return() is None
    for a, b in (("4.2", "4.3"), ("3.0", "3.end"), ("4.0", "5.end")):
        select(a, b)
        assert window.on_editor_return() is None, (a, b)
    window.text.tag_remove("sel", "1.0", "end")
    assert window.raw_text().rstrip("\n") == src


def test_heading_space_sets_upper_levels_and_releases_lower_levels(window):
    """下の段の見出しで入れると、上の段の見出しの前にも入れ、上の段の見出しで外すと、下の段の見出しの前の空行も外す
    （VAスタイルが上の段から順に書式を変えるのと同じ。2026-10-28 班長指示）。"""
    src = "前書き。\n# 第一\n本文。\n## 小一\n本文。\n### 細一\n本文。\n# 第二\n本文。\n## 小二\n本文。\n### 細二\n本文。"

    def lines():
        return window.raw_text().rstrip("\n").split("\n")

    def select_heading(text):
        n = lines().index(text) + 1
        window.text.tag_remove("sel", "1.0", "end")
        window.text.tag_add("sel", f"{n}.0", f"{n}.end")
        window.text.mark_set("insert", f"{n}.end")
        assert window.on_editor_return() == "break"
    window._load_text(src)
    select_heading("## 小二")                             # 段2で入れる：段1・段2に入り、段3には入らない
    assert lines() == ["前書き。", "", "# 第一", "本文。", "", "## 小一", "本文。", "### 細一", "本文。", "", "# 第二", "本文。",
                       "", "## 小二", "本文。", "### 細二", "本文。"]
    select_heading("### 細一")                            # 段3で入れる：段3にも入る（段1・段2は入ったまま）
    assert lines().count("") == 6
    select_heading("## 小一")                             # 段2で外す：段2・段3が外れ、段1は残る
    assert lines() == ["前書き。", "", "# 第一", "本文。", "## 小一", "本文。", "### 細一", "本文。", "", "# 第二", "本文。",
                       "## 小二", "本文。", "### 細二", "本文。"]
    window.text.edit_undo()                              # Ctrl+Z 1回で、外す前に戻る
    assert lines().count("") == 6
    select_heading("# 第二")                              # 段1で外す：すべて外れる
    assert window.raw_text().rstrip("\n") == src


def test_heading_space_keys_reach_the_editor(window):
    """実際の Enter のキーで働く。選ばずに押した Enter・Backspace は、見出しの行の先頭でもふつうの改行・削除になる。
    Ctrl+Enter は改ページのまま。"""
    _focus_editor(window)
    window._load_text("# 第一\n本文。\n# 第二\n本文。")
    window.text.tag_add("sel", "3.0", "3.end")
    window.text.mark_set("insert", "3.end")
    window.text.event_generate("<Return>")
    assert _lines(window, 1, 5) == ["# 第一", "本文。", "", "# 第二", "本文。"]
    window.text.tag_remove("sel", "1.0", "end")
    window.text.mark_set("insert", "4.0")                # 見出しの行の先頭の Backspace：その空行だけを消す
    window.text.event_generate("<BackSpace>")
    assert _lines(window, 1, 4) == ["# 第一", "本文。", "# 第二", "本文。"]
    window._load_text("# 第一\n本文。\n# 第二\n本文。")
    window.text.mark_set("insert", "3.0")                # 見出しの行の先頭の Enter：ふつうの改行（その見出しだけ）
    window.text.event_generate("<Return>")
    assert _lines(window, 1, 5) == ["# 第一", "本文。", "", "# 第二", "本文。"]
    window.text.mark_set("insert", "4.0")
    window.text.event_generate("<Control-Return>")       # 改ページ
    assert _lines(window, 4, 4) == ["<<<"]


def test_new_heading_follows_previous_heading_of_same_level(window):
    """［見出し］・Alt+Shift+←／→ で見出しにした行には、直前の同じ段の見出しにならって、前の空行と見出し全体の太字を付ける。
    レベルを変えた見出しは、直前の同じ段の見出しになければ外す（本文から見出しにした行は付けるだけ）。Ctrl+Z 1回で、
    見出しにする前に戻る（2026-10-29 班長指示）。"""
    def lines():
        return window.raw_text().rstrip("\n").split("\n")
    window.text.tag_remove("sel", "1.0", "end")
    # 直前の ## は空行と太字の両方：［見出し］で両方が付く
    window._load_text("# 第一\n本文。\n\n## **小一**\n本文。\n次の段落。")
    window.text.mark_set("insert", "6.0")
    window.on_paragraph_kind(HEADING_BUTTON_MARK)
    assert lines()[4:] == ["本文。", "", "## **次の段落。**"]
    window.text.edit_undo()
    assert lines()[4:] == ["本文。", "次の段落。"]
    # 太字だけ・空行だけ・どちらもなし
    for prev, want in (("## **小一**", ["本文。", "## **次。**"]), ("\n## 小一", ["本文。", "", "## 次。"]),
                       ("## 小一", ["本文。", "## 次。"])):
        window._load_text(f"# 第一\n本文。\n{prev}\n本文。\n次。")
        n = len(lines())
        window.text.mark_set("insert", f"{n}.0")
        window.on_paragraph_kind(HEADING_BUTTON_MARK)
        assert lines()[-len(want):] == want, prev
    # 段の違う見出しにはならわない。Alt+Shift+→ で ### にすると、直前の ### にならう
    window._load_text("## **小一**\n本文。\n\n### 細一\n本文。\n次。")
    window.text.mark_set("insert", "6.0")
    window.on_outline(1)                                  # 本文を下げると直前の見出し（###）と同じ段
    assert lines()[4:] == ["本文。", "", "### 次。"]
    window.on_outline(-1)                                 # ## に上げると、直前の ## にならって太字。空行は、直前の ## が
                                                          # 文書の先頭で空けるかが表れないので、変えない
    assert lines()[4:] == ["本文。", "", "## **次。**"]
    window.text.edit_undo()
    assert lines()[4:] == ["本文。", "", "### 次。"]
    # 直前の同じ段の見出しが上の段の見出しの直後（空けるかが表れない）なら、その前の同じ段の見出しを見る。
    # 上の段の見出しの直後に見出しにした行には、空行を入れない（二重に空けない）
    window._load_text("# 第一\n本文。\n\n## 小一\n本文。\n# 第二\n## 小二\n本文。\n次。\n# 第三\n小三")
    window.text.mark_set("insert", "9.0")
    window.on_paragraph_kind(HEADING_BUTTON_MARK)
    assert lines()[6:10] == ["## 小二", "本文。", "", "## 次。"]
    window.text.mark_set("insert", "12.0")
    window.on_paragraph_kind(HEADING_BUTTON_MARK)
    assert lines()[10:] == ["# 第三", "## 小三"]
    # 一緒に見出しにした行にはならわず、その前の見出しにならう
    window._load_text("前文。\n\n## **小一**\n本文。\n一。\n二。")
    window.text.tag_add("sel", "5.0", "6.end")
    window.on_paragraph_kind(HEADING_BUTTON_MARK)
    window.text.tag_remove("sel", "1.0", "end")
    assert lines()[3:] == ["本文。", "", "## **一。**", "## **二。**"]
    # レベルを変えた見出しは、直前の同じ段の見出しになければ外す（2026-10-29 班長指示）。本文から見出しにした行は外さない
    window._load_text("前文。\n\n## **小一**\n本文。\n### 細一\n本文。\n次。")
    window.text.mark_set("insert", "7.0")
    window.on_outline(1)                                  # 本文 → ###（直前の ### は空行・太字なし。本文からなので外すものもない）
    assert lines()[-2:] == ["本文。", "### 次。"]
    window.on_outline(-1)                                 # ### → ##：直前の ## にならって空行と太字を付ける
    assert lines()[-3:] == ["本文。", "", "## **次。**"]
    window.on_outline(1)                                  # ## → ###：直前の ### にないので、空行と太字を外す
    assert lines()[-2:] == ["本文。", "### 次。"]
    window.text.edit_undo()                               # Ctrl+Z 1回で、レベルを変える前に戻る
    assert lines()[-3:] == ["本文。", "", "## **次。**"]
    window._load_text("## 小一\n本文。\n\n**次。**")       # 本文から見出しにした行の空行・太字は、利用者のものなので残す
    window.text.mark_set("insert", "4.0")
    window.on_paragraph_kind(HEADING_BUTTON_MARK)
    assert lines()[1:] == ["本文。", "", "## **次。**"]
    window._load_text("# **第一**\n本文。\n\n### **細一**")  # 前にも後にも同じ段の見出しがなければ、変えない
    window.text.mark_set("insert", "4.0")
    window.on_outline(-1)
    assert lines()[1:] == ["本文。", "", "## **細一**"]
    # 前に同じ段の見出しがなければ、後の同じ段の見出しに合わせる（その段の最初の見出し。2026-10-29 班長指示）
    window._load_text("# 第一\n本文。\n### 細一\n本文。\n\n## **小二**\n本文。")
    window.text.mark_set("insert", "3.0")
    window.on_outline(-1)                                 # ### → ##：後の ## にならって空行と太字を付ける
    assert lines()[:6] == ["# 第一", "本文。", "", "## **細一**", "本文。", ""]
    window._load_text("# 第一\n本文。\n\n## **小一**\n本文。\n### 細二\n本文。")
    window.text.mark_set("insert", "4.0")
    window.on_outline(1)                                  # ## → ###：後の ### にないので、空行と太字を外す
    assert lines() == ["# 第一", "本文。", "### 小一", "本文。", "### 細二", "本文。"]
    window._load_text("前文。\n小一\n本文。\n\n## **小二**")  # ［見出し］で本文を見出しにしたときも、後の ## に合わせて付ける
    window.text.mark_set("insert", "2.0")
    window.on_paragraph_kind(HEADING_BUTTON_MARK)
    assert lines()[:3] == ["前文。", "", "## **小一**"]
    # 字のない行を見出しにしたときは、空行を入れ、カーソルをその見出しの行末に置く（太字は字を打ってから）
    window._load_text("本文。\n\n## **小一**\n本文。\n")
    window.text.mark_set("insert", "5.0")
    window.on_paragraph_kind(HEADING_BUTTON_MARK)
    assert lines()[3:] == ["本文。", "", "## "] and window.text.index("insert") == "6.3"


def test_marks_wrapped_in_bold_in_editor(window):
    """「**:=: 準備書面**」の記号も青く示し、［中央］で付け替えられる。AI の回答で太字に囲まれても、
    記号が消えたとはみなさない（2026-10-24 班長指示）。"""
    window._load_text("**:=: 準備書面（１）**\n# 認否\n")
    window._highlight()
    # 「**」「:=: 」は青、「準備書面」は青でない（太字）
    assert all("mark" in window.text.tag_names(f"1.{c}") for c in range(6))
    assert "mark" not in window.text.tag_names("1.6") and "bold" in window.text.tag_names("1.6")
    window.text.mark_set("insert", "1.5")
    window.on_align(":-: ")
    assert window.text.get("1.0", "1.end") == ":-: **準備書面（１）**"
    r = vamd.review(vamd.parse_text("==== VA Document 文書ID K7Q29XMD 版 1 ====\n**:=: 準備書面**\n"),
                     "K7Q29XMD", 1, [":=: 準備書面"], window.session.dictionary)
    assert not r.lost_marks


def test_highlight_button_and_tags(window):
    """［蛍光ペン］（Ctrl+Alt+H）で選んだ字を ==…== で囲み、もう一度で外す。エディターでは黄色の地で示す。"""
    window._load_text("# 認否\n主張は争う。\n")
    window.text.tag_add("sel", "2.0", "2.2")
    window.on_highlight()
    assert window.text.get("2.0", "2.end") == "==主張==は争う。"
    window._highlight()
    assert "highlight" in window.text.tag_names("2.2") and "mark" in window.text.tag_names("2.0")
    assert "highlight" not in window.text.tag_names("2.6")
    window.on_highlight()
    assert window.text.get("2.0", "2.end") == "主張は争う。"
    assert window.bind("<Control-Alt-Key-h>")


def test_dots_button_with_bold(window):
    """［傍点］で選んだ字を *…* で囲み、もう一度で外す。太字と重ねると ***…***、外すときは * の数で見分ける。
    エディターでは下線で示す（2026-10-24 班長指示）。"""
    window._load_text("# 認否\n主張は争う。\n")
    window.text.tag_add("sel", "2.0", "2.2")
    window.on_dots()
    assert window.text.get("2.0", "2.end") == "*主張*は争う。"
    window._highlight()
    assert "dots" in window.text.tag_names("2.1") and "mark" in window.text.tag_names("2.0")
    window.on_bold()                                     # 傍点に太字を重ねる
    assert window.text.get("2.0", "2.end") == "***主張***は争う。"
    window.on_dots()                                     # 傍点だけ外す
    assert window.text.get("2.0", "2.end") == "**主張**は争う。"
    window.on_dots()                                     # 太字に傍点を重ねる
    assert window.text.get("2.0", "2.end") == "***主張***は争う。"
    window.on_bold()                                     # 太字だけ外す
    assert window.text.get("2.0", "2.end") == "*主張*は争う。"
    window.on_dots()
    assert window.text.get("2.0", "2.end") == "主張は争う。"


def test_indent_button_and_shortcuts(window):
    """［インデント］（Ctrl+I）で ->1 を付け、もう一度で外す（字数は手で直す）。字下げの全角空白と一緒に使え、
    見出しの行には付けない。Ctrl+I でタブは入らない（2026-10-24 班長指示）。"""
    window._load_text("# 認否\n主張は争う。\n次の段落。\n")
    window.text.tag_add("sel", "2.0", "3.end")
    window.on_indent()
    assert window.raw_text().split("\n")[1:3] == ["->1 主張は争う。", "->1 次の段落。"]
    window.on_indent()                                   # もう一度で外す（選択は残る）
    assert window.raw_text().split("\n")[1:3] == ["主張は争う。", "次の段落。"]
    window.text.tag_remove("sel", "1.0", "end")
    window._load_text("# 認否\n->3 主張は争う。\n次の段落。\n")
    window.text.tag_add("sel", "2.0", "3.end")           # 一部の行に記号があれば、ない行に付ける（字数は変えない）
    window.on_indent()
    assert window.raw_text().split("\n")[1:3] == ["->3 主張は争う。", "->1 次の段落。"]
    window.text.tag_remove("sel", "1.0", "end")
    window.text.insert("2.4", "　")                     # 記号の後ろに全角空白（1行目をさらに1字下げる）
    window.text.mark_set("insert", "2.6")
    window.on_align(":-: ")                            # 配置を付けても、インデントと字下げの空白は残す
    assert window.text.get("2.0", "2.end") == ":-: ->3 　主張は争う。"
    window.on_align(":-: ")
    assert window.text.get("2.0", "2.end") == "->3 　主張は争う。"
    window.text.mark_set("insert", "1.1")
    window.on_indent()                                   # 見出しの行には付けない
    assert window.text.get("1.0", "1.end") == "# 認否"
    _focus_editor(window)
    window.text.mark_set("insert", "3.2")
    window.text.event_generate("<Control-Key-i>")
    assert window.text.get("3.0", "3.end") == "次の段落。"         # Ctrl+I で外れる。タブは入らない
    window.text.event_generate("<Control-Key-i>")
    assert window.text.get("3.0", "3.end") == "->1 次の段落。"
    window._highlight()
    assert all("mark" in window.text.tag_names(f"3.{c}") for c in range(4))
    window.on_plain()                                    # 標準（Ctrl+Shift+N）で記号を外す
    assert window.text.get("3.0", "3.end") == "次の段落。"

def test_header_footer_buttons(window):
    """［ヘッダー］［フッター］：選んだ行の行頭に [HEADER] [FOOTER] を付け、もう一度で外す（もう片方とは付け替える）。
    配置の記号は残す。見出しの行には付けない。記号は青い字で示し、確認表示ではヘッダー・フッターに組む（2026-10-25
    班長指示。［フッター］は 2026-11-03 班長指示で足した）。"""
    # ［ヘッダー］は「書式」の組の［インデント］の下、［フッター］はその下（2026-10-25・2026-11-03 班長指示）
    found = {str(b.cget("text")): b for b in _all_buttons(window)}
    head, foot, indent = found["ヘッダー"], found["フッター"], found["インデント"]
    assert head.master is foot.master is indent.master is _group(window, "書式").body
    assert head.grid_info()["column"] == foot.grid_info()["column"] == indent.grid_info()["column"]
    assert int(head.grid_info()["row"]) == int(indent.grid_info()["row"]) + 1
    assert int(foot.grid_info()["row"]) == int(head.grid_info()["row"]) + 1
    window._load_text("--: 事件番号\n担当\n# 認否\n主張は争う。")
    window.text.tag_add("sel", "1.0", "2.end")
    window.on_area("[HEADER] ")
    assert _lines(window, 1, 2) == ["[HEADER] --: 事件番号", "[HEADER] 担当"]
    window.on_align(":-: ")                                 # 配置は付け替え、ヘッダーの記号は残す
    assert _lines(window, 1, 2) == ["[HEADER] :-: 事件番号", "[HEADER] :-: 担当"]
    window.text.tag_remove("sel", "1.0", "end")
    window.text.mark_set("insert", "2.0")
    foot.invoke()                                           # もう片方とは付け替える
    assert _lines(window, 2, 2) == ["[FOOTER] :-: 担当"]
    foot.invoke()                                           # もう一度で外す
    assert _lines(window, 2, 2) == [":-: 担当"]
    window.text.mark_set("insert", "3.0")
    window.on_area("[HEADER] ")                             # 見出しの行には付けない
    assert _lines(window, 3, 3) == ["# 認否"]
    window.text.edit_undo()                                 # Ctrl+Z 1回で1回分戻る
    assert _lines(window, 2, 2) == ["[FOOTER] :-: 担当"]
    window._highlight()
    ranges = window.text.tag_ranges("mark")
    assert "[HEADER] :-: " in [window.text.get(a, b) for a, b in zip(ranges[0::2], ranges[1::2])]
    window.on_plain()                                       # 標準は配置を外し、置く場所の記号は残す
    assert _lines(window, 2, 2) == ["[FOOTER] 担当"]
    window.refresh()
    lines = window.session.layout_map.lines
    assert sorted((ln.area, "".join(g.ch for g in ln.glyphs)) for ln in lines if ln.area) == [
        ("footer", "担当"), ("header", "事件番号")]


def _widgets(root, cls, skip_toplevel=False):
    """root の下の cls の部品を、すべて返す。skip_toplevel なら、別の画面（検索と置換など）の中は見ない。"""
    for c in root.winfo_children():
        if skip_toplevel and isinstance(c, tk.Toplevel):
            continue
        if isinstance(c, cls):
            yield c
        yield from _widgets(c, cls, skip_toplevel)


def _all_buttons(w):
    return _widgets(w, tk.ttk.Button)


def _group(window, title):
    """リボンの組を、名前で引く。"""
    return next(g for g in window.ribbon.groups if g.title == title)


def test_header_overflow_is_shown_in_status(window):
    window._load_text("\n".join(["[HEADER] 行"] * 6 + ["本文"]))
    window.refresh()
    assert "ヘッダー" in str(window.status.cget("text"))
    window._load_text("本文")
    window.refresh()
    assert str(window.status.cget("text")) == ""


def test_distribute_button(window):
    """［均等割付］で選んだ字を [字]{N} の形で挟み（N は選んだ字の数。手で直す）、もう一度で外す。"""
    window._load_text("原告甲野太郎\n")
    window.text.tag_add("sel", "1.0", "1.2")
    window.on_distribute()
    assert window.text.get("1.0", "1.end") == "[原告]{2}〔人名Ａ〕"
    assert window.text.get("sel.first", "sel.last") == "原告"
    window._highlight()
    assert all("mark" in window.text.tag_names(f"1.{c}") for c in (0, 3, 4, 5, 6))       # 「[」と「]{2}」
    assert "mark" not in window.text.tag_names("1.1")
    window.on_distribute()
    assert window.text.get("1.0", "1.end") == "原告〔人名Ａ〕"
    window.text.edit_undo()
    assert window.text.get("1.0", "1.end") == "[原告]{2}〔人名Ａ〕"


def test_align_and_distribute_buttons_in_table_cells(window):
    """表のセルでは、［中央］［右］がセルの先頭の配置の記号を、［均等割付］がセルの字全体を挟む記号を付け外しする。
    区切りの行では列の配置を変える（2026-10-24 班長指示）。"""
    window._load_text("| 項目 | 金額 |\n|---|---|\n| 休業損害 | :-: 1,000 |\n本文。\n")

    def lines():
        return window.raw_text().split("\n")[:4]
    window.text.mark_set("insert", "1.4")                 # 「項目」のセル
    window.on_align("--: ")
    assert lines()[0] == "| --: 項目 | 金額 |"
    window.on_align("--: ")                               # もう一度で外す
    assert lines()[0] == "| 項目 | 金額 |"
    window.text.mark_set("insert", "3.13")                # 「1,000」のセル：:-: を --: に付け替える
    window.on_align("--: ")
    assert lines()[2] == "| 休業損害 | --: 1,000 |"
    window.text.tag_add("sel", "1.2", "3.4")              # 選んだ範囲にかかるセル（区切りの行は除く）
    window.on_align(":-: ")
    assert lines()[0] == "| :-: 項目 | :-: 金額 |" and lines()[1] == "|---|---|"
    assert lines()[2] == "| :-: 休業損害 | --: 1,000 |"
    window.text.edit_undo()                               # Ctrl+Z 1回で戻る
    assert lines()[0] == "| 項目 | 金額 |"
    window.text.tag_remove("sel", "1.0", "end")
    window.text.mark_set("insert", "3.4")                 # 均等割付：セルの字全体を挟む・外す
    window.on_distribute()
    assert lines()[2] == "| [休業損害]{4} | --: 1,000 |"
    window.text.tag_remove("sel", "1.0", "end")
    window.text.mark_set("insert", "3.6")
    window.on_distribute()
    assert lines()[2] == "| 休業損害 | --: 1,000 |"
    window.text.mark_set("insert", "3.14")                # 配置の記号の後から挟む
    window.on_distribute()
    assert lines()[2] == "| 休業損害 | --: [1,000]{3} |"
    window.text.tag_remove("sel", "1.0", "end")
    window.text.mark_set("insert", "3.end")               # 最後の | の後なら、最後のセル
    window.on_align(":-: ")
    assert lines()[2] == "| 休業損害 | :-: [1,000]{3} |"
    window.text.mark_set("insert", "2.2")                 # 区切りの行では、その列の配置を変える
    window.on_align("--: ")
    assert lines()[1] == "|---:|---|"
    window.text.mark_set("insert", "4.1")                 # 表の外の行は、これまでどおり段落の配置
    window.on_align("--: ")
    assert lines()[3] == "--: 本文。"


def test_align_buttons_on_separator_row_change_column(window):
    """区切りの行のセルで［中央］［右］を押すと、その列の配置（: の付け方）を変える。もう一度で左に戻す。
    - と = の種類と数は変えない（2026-10-24 班長指示）。"""
    window._load_text("| 項目 | 金額 |\n|===|===|\n| 休業損害 | 1,000 |\n")

    def sep():
        return window.raw_text().split("\n")[1]
    window.text.mark_set("insert", "2.6")                 # 2列目
    window.on_align("--: ")
    assert sep() == "|===|===:|"
    window.on_align(":-: ")
    assert sep() == "|===|:===:|"
    window.on_align(":-: ")                             # もう一度で左に戻す
    assert sep() == "|===|===|"
    window.text.tag_add("sel", "2.0", "2.end")            # 選んだ範囲にかかる列をまとめて
    window.on_align(":-: ")
    assert sep() == "|:===:|:===:|"
    window.text.edit_undo()
    assert sep() == "|===|===|"
    from va_document.document import CENTER, parse_separator
    window.on_align(":-: ")
    assert parse_separator(sep()) == ([CENTER, CENTER], True)       # 2重線のまま


def test_naiyou_check_before_save(window, tmp_path, monkeypatch):
    """内容証明なら、保存する前に字数・行数を確かめる。ページ番号は「なし」にして知らせる。超えた所があれば
    カーソルをその行に動かして尋ね、「保存をやめて直す」なら保存しない（2026-10-24 班長指示）。"""
    shown, asked = [], []
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: shown.append(a[1]))

    class Stop:
        def __init__(self, parent, problem):
            asked.append(problem)
            self.ok = False
    monkeypatch.setattr(file_ops, "NaiyouDialog", Stop)
    window.doc_type_box.set("内容証明")
    window.page_number_box.set("中下")
    window.on_settings_changed()
    window._load_text("本文。\nABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij\n")
    window.refresh()
    window.session.pdf_path = tmp_path / "通知書.pdf"
    assert not window.on_save()
    assert window.page_number_box.get() == "なし" and "なし" in shown[0]
    assert asked and asked[0].kind == "chars"
    assert window.text.index("insert").startswith("2.")              # カーソルは超えた行に
    assert not (tmp_path / "通知書.pdf").exists()
    window._load_text("本文。\n")
    window.refresh()
    assert window.on_save() and (tmp_path / "通知書.pdf").exists()
    assert len(asked) == 1
    window.doc_type_box.set("裁判所提出書類")
    window.on_settings_changed()


def test_options_change_folder_and_editor(window, tmp_path, monkeypatch):
    """［オプション］で構文ファイルの保存場所と、エディターの書体・字の大きさ・行の間隔を変える。今の文書は、
    これまでの場所の構文ファイルを使い続ける（2026-10-24 班長指示）。"""
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    assert window.on_save()
    old = window.session.vamd_path
    shared = tmp_path / "共有"
    shared.mkdir()
    family = (app.theme.editor_font_choices(window) or [""])[0]

    class Answer:
        def __init__(self, parent, cfg, choices, size_range, spacing_range, prompt, default_prompt, nav_range):
            assert size_range == (8, 20) and spacing_range == (6, 15) and prompt == default_prompt
            assert nav_range == (0, 15)
            self.result = {"vamd_folder": str(shared), "font_family": family, "font_size": 14, "line_spacing": 9,
                           "nav_font_family": family, "nav_font_size": 12, "nav_line_spacing": 5, "prompt": None}
    monkeypatch.setattr(app, "OptionsDialog", Answer)
    window.on_options()
    assert window.cfg.vamd_folder == str(shared) and window.cfg.editor_font_size == 14
    assert str(window.doc_id_label.cget("text")) == f"エディター：{window.session.doc_id}.vamd"   # 保存した文書
    assert str(window.pdf_name_label.cget("text")) == "プレビュー：準備書面.pdf"
    assert window.session.vamd_path == old                      # 今の文書は、これまでの構文ファイル
    from tkinter import font as tkfont
    assert tkfont.Font(window, font=window.text.cget("font")).actual("size") == 14
    assert int(str(window.text.cget("spacing2"))) == round(9 * window.winfo_fpixels("1p"))     # ポイントを画素に
    saved = app.config.load(app.config.config_path())
    assert (saved.editor_font_size, saved.editor_line_spacing_pt, saved.vamd_folder) == (14, 9, str(shared))
    # ナビゲーションの書体・字の大きさ・行の間隔（2026-11-24 班長指示）。行の高さは字の高さに行の間隔を足したもの
    assert (saved.nav_font_family, saved.nav_font_size, saved.nav_line_spacing_pt) == (family, 12, 5)
    style = tk.ttk.Style(window)
    font = tkfont.Font(window, font=style.lookup("Nav.Treeview", "font"))
    assert font.actual("size") == 12 and str(window.nav_tree.cget("style")) == "Nav.Treeview"
    assert str(window.tree.cget("style")) == "Nav.Treeview"        # 「仮名化する語」の一覧も同じ字（2026-11-24 班長指示）
    assert int(style.lookup("Nav.Treeview", "rowheight")) == font.metrics("linespace") + round(5 * window.winfo_fpixels("1p"))
    # （既定）の書体は、エディターとナビゲーションで同じ（2026-11-24 班長指摘）
    app.theme.apply_nav_prefs(window, "", 9, 3)
    app.theme.set_editor_prefs("", 14, 9)
    nav_family = tkfont.Font(window, font=style.lookup("Nav.Treeview", "font")).actual("family")
    assert nav_family == tkfont.Font(window, font=app.theme.editor_font(window)).actual("family")
    # 新しい文書は、新しい場所に保存する
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    assert window.on_close_document()
    assert window.session.vamd_path.parent == shared
    window.cfg.editor_font_size, window.cfg.editor_line_spacing_pt, window.cfg.editor_font_family = 11, 6, ""
    window.cfg.nav_font_size, window.cfg.nav_line_spacing_pt, window.cfg.nav_font_family = 9, 3, ""
    window._apply_editor_prefs()


def test_close_is_disabled_while_blank(window, monkeypatch):
    """白紙のまま変えていない間は、［閉じる］（メニューとリボン）を押せない。字を書けば押せ、Ctrl+W で閉じる（標準 02
    「メニュー」。2026-11-21 班長決定）。［新規作成］は置かない。"""
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: False)   # 保存しない
    window.on_close_document()
    window.text.delete("1.0", "end")
    window.on_text_modified()
    window._update_title()
    f = window.file_menu
    labels = [f.entrycget(i, "label") for i in range(f.index("end") + 1) if f.type(i) == "command"]
    assert "新規作成" not in labels
    assert window.is_blank()
    assert f.entrycget("閉じる", "state") == "disabled" and str(window.close_button.cget("state")) == "disabled"
    assert not window.on_close_document()                          # 白紙のままなら何もしない
    # ［印刷］も押せず、Ctrl+P でも印刷の画面を開かない（2026-11-24 班長指摘）
    printing_ok = app.printing.available()
    assert str(window.print_button.cget("state")) == "disabled"
    assert window.on_print() is None
    window.text.insert("end", "字。")
    window.text.edit_modified(True)
    window.on_text_modified()
    assert f.entrycget("閉じる", "state") == "normal" and str(window.close_button.cget("state")) == "normal"
    assert str(window.print_button.cget("state")) == ("normal" if printing_ok else "disabled")
    window.text.focus_force()
    window.update()
    window.text.event_generate("<Control-Key-w>")           # エディターの中で押しても、字を消さずに閉じる
    window.update()
    assert window.raw_text() == "" and window.is_blank()
    assert f.entrycget("閉じる", "state") == "disabled"


def test_close_document_starts_new_one(window, monkeypatch):
    """［閉じる］は今の文書を閉じて新しい文書にする（VA Document は終わらない）。保存していない変更があれば尋ねる。"""
    asked = []
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: asked.append(a[1]))
    old_id = window.session.doc_id
    window.text.insert("end", "追記。")
    window.on_text_modified()
    assert not window.on_close_document()                          # キャンセルなら閉じない
    assert asked and window.session.doc_id == old_id
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: False)   # 保存しない
    # 仮名化した語の一覧が消えることは尋ねない（2026-10-27 班長指示）
    yesno = []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: yesno.append(a[1]) or False)
    assert window.session.dictionary.entries and window.on_close_document()
    assert not yesno
    assert window.session.doc_id != old_id and window.raw_text() == "" and window.winfo_exists()
    # 閉じた後（エディターが空）は「開かれていません」、書いたが保存していなければ「保存していません」
    assert str(window.doc_id_label.cget("text")) == "エディター：（開かれていません）"
    assert str(window.pdf_name_label.cget("text")) == "プレビュー：（開かれていません）"
    window.text.insert("1.0", "本文。")
    window.on_text_modified()
    assert str(window.doc_id_label.cget("text")) == "エディター：（保存していません）"
    assert str(window.pdf_name_label.cget("text")) == "プレビュー：（保存していません）"
    assert not window.tree.get_children()


def test_save_dialog_title(window, monkeypatch):
    """新しい文書を保存するときの保存先の画面の題は「書式付き（PDF）ファイルの保存先」（2026-10-26 班長指示）。"""
    from tkinter import filedialog
    titles = []
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda *a, **k: titles.append(k.get("title")) or "")
    assert not window.on_save()                                     # 保存先を選ばなければ保存しない
    assert titles == ["書式付き（PDF）ファイルの保存先"]


def test_config_rejects_out_of_range_options():
    cfg = app.config.AppConfig(editor_font_size=99, editor_line_spacing_pt=-3, editor_font_family=5)
    assert (cfg.editor_font_size, cfg.editor_line_spacing_pt, cfg.editor_font_family) == (11, 6, "")
    cfg = app.config.AppConfig(nav_font_size=True, nav_line_spacing_pt=16, nav_font_family=None)
    assert (cfg.nav_font_size, cfg.nav_line_spacing_pt, cfg.nav_font_family) == (9, 3, "")
    assert app.config.AppConfig(nav_line_spacing_pt=0).nav_line_spacing_pt == 0      # ナビゲーションは 0 まで狭められる


def test_options_dialog_has_navigation_fonts(window, monkeypatch):
    """オプションの画面に「ナビゲーション」の枠を置き、エディターと同じく書体・字の大きさ・行の間隔を変えられる
    （2026-11-24 班長指示）。範囲の外は知らせて受け付けない。"""
    from va_document import dialogs
    monkeypatch.setattr(dialogs._Dialog, "run", lambda self: None)
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: errors.append(a[1]))
    cfg = app.config.AppConfig(vamd_folder=str(Path.cwd()))
    dlg = dialogs.OptionsDialog(window, cfg, ["ＭＳ ゴシック"], (8, 20), (6, 15), vamd.PROMPT, vamd.PROMPT, (0, 15))
    try:
        frames = [str(f.cget("text")) for f in _widgets(dlg, tk.ttk.Labelframe)]
        assert frames.index("エディター") + 1 == frames.index("ナビゲーション・仮名リスト")
        assert (dlg.nav_family.get(), dlg.nav_size.get(), dlg.nav_spacing.get()) == ("（既定）", "9", "3")
        dlg.nav_spacing.set("16")
        dlg.accept()
        assert dlg.result is None and "ナビゲーション・仮名リストの" in errors[-1]
        dlg.nav_family.set("ＭＳ ゴシック")
        dlg.nav_size.set("14")
        dlg.nav_spacing.set("0")
        dlg.accept()
        assert dlg.result["nav_font_family"] == "ＭＳ ゴシック"
        assert (dlg.result["nav_font_size"], dlg.result["nav_line_spacing"]) == (14, 0)
        assert dlg.result["font_size"] == cfg.editor_font_size
    finally:
        if dlg.winfo_exists():
            dlg.destroy()


def test_config_reads_old_line_spacing_in_pixels(tmp_path):
    """Ver150 までの行の間隔（画素）は、ポイントに直して読む（2026-10-26 班長決定。単位をポイントにした）。"""
    path = tmp_path / "settings.json"
    for old, pt in ((8, 6), (12, 9), (20, 15), (0, 6)):
        path.write_text(json.dumps({"editor_line_spacing": old}), encoding="utf-8")
        assert app.config.load(path).editor_line_spacing_pt == pt
    path.write_text(json.dumps({"editor_line_spacing": 20, "editor_line_spacing_pt": 7}), encoding="utf-8")
    assert app.config.load(path).editor_line_spacing_pt == 7       # 新しい値があれば、そちらを使う
    app.config.save(app.config.load(path), path)
    assert "editor_line_spacing" not in json.loads(path.read_text(encoding="utf-8"))     # 古い値は書かない


def test_ai_prompt_in_options(window, tmp_path, monkeypatch):
    """AI への指示は、オプションで確かめ・直す。今の文書（保存してある構文ファイルの指示も書き直す）と、
    これから作る文書に使う。既定に戻すこともできる（2026-10-24 班長指示）。"""
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    assert window.on_save()
    custom = vamd.PROMPT.rstrip() + "\n・短く書け。\n"

    def answer(prompt_text):
        class Answer:
            def __init__(self, parent, cfg, choices, size_range, spacing_range, prompt, default_prompt, nav_range):
                self.result = {"vamd_folder": cfg.vamd_folder, "font_family": cfg.editor_font_family,
                               "font_size": cfg.editor_font_size, "line_spacing": cfg.editor_line_spacing_pt,
                               "nav_font_family": cfg.nav_font_family, "nav_font_size": cfg.nav_font_size,
                               "nav_line_spacing": cfg.nav_line_spacing_pt, "prompt": prompt_text}
        return Answer
    monkeypatch.setattr(app, "OptionsDialog", answer(custom))
    window.on_options()
    assert window.session.prompt == custom and window.cfg.ai_prompt == custom
    assert window.cfg.ai_prompt_base == vamd.PROMPT_SHA256           # 書き換えた時の既定の指示を控える
    saved = window.session.vamd_path.read_text(encoding="utf-8")
    assert "・短く書け。" in saved and "版 1" in saved                    # 版は変えずに指示だけ書き直す
    assert not window.session.vamd_changed_outside()
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    assert window.on_close_document()
    assert window.session.prompt == custom                                 # 新しい文書にも使う
    monkeypatch.setattr(app, "OptionsDialog", answer(vamd.PROMPT))          # 既定に戻す
    window.on_options()
    assert window.session.prompt is None and window.cfg.ai_prompt == "" and window.cfg.ai_prompt_base == ""


def test_notice_when_default_prompt_changed(window, monkeypatch):
    """ユーザーによって書き換えられた指示を使っていて、書き換えた後に既定の指示が新しくなったときだけ、起動のときに
    一度だけ知らせる（2026-10-28 班長決定）。"""
    shown = []
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: shown.append(a[1]))
    assert not window.notify_prompt_update()                    # 既定の指示を使っている
    window.cfg.ai_prompt = vamd.PROMPT.rstrip() + "\n・短く書け。\n"
    window.cfg.ai_prompt_base = vamd.PROMPT_SHA256
    window.session = app.Session(window.cfg)
    assert not window.notify_prompt_update()                    # 書き換えた時から既定の指示は変わっていない
    window.cfg.ai_prompt_base = "0" * 64                         # 書き換えた後に既定の指示が新しくなった
    assert window.notify_prompt_update() and len(shown) == 1
    assert "ユーザーによって書き換えられた指示" in shown[0] and window.cfg.ai_prompt_base == vamd.PROMPT_SHA256
    assert not window.notify_prompt_update() and len(shown) == 1    # 一度だけ


def test_prompt_dialog_reset(window):
    from va_document.dialogs import PromptDialog

    def run():
        d = [c for c in window.winfo_children() if isinstance(c, PromptDialog)][-1]
        d.text.insert("end", "\n・足した。")
        d.reset()
        assert d.text.get("1.0", "end-1c") == vamd.PROMPT.rstrip("\n")
        d.text.insert("end", "\n・足した。")
        d.accept()
    window.after(200, run)
    dlg = PromptDialog(window, vamd.PROMPT, vamd.PROMPT)
    assert dlg.result.endswith("・足した。\n")


def test_parse_pages():
    from va_document.printing import parse_pages
    assert parse_pages("1-3, 5", 6) == [0, 1, 2, 4]
    assert parse_pages("２－３，２", 4) == [1, 2]
    assert parse_pages("4-", 6) == [3, 4, 5]
    for bad in ("", "0", "7", "3-2", "a"):
        with pytest.raises(ValueError):
            parse_pages(bad, 6)


@pytest.mark.skipif(app.os.name != "nt", reason="印刷は Windows だけ")
def test_print_dialog_choices(window):
    """印刷の画面：プリンター・ページ（すべて・指定）・部数を選ぶ。右の印刷プレビューは、印刷するページを1枚ずつ、
    印刷と同じ灰色で見せる（2026-10-30 班長決定。「プレビューのページ」はなくした）。"""
    from va_document.dialogs import PrintDialog
    window._load_text("\n".join(f"# 見出し{k}\n本文。\n<<<" for k in range(6)).rstrip("<"))
    data = window.session.preview_pdf(window.real_text())
    results, seen = [], []

    def run(setup):
        def go():
            d = [c for c in window.winfo_children() if isinstance(c, PrintDialog)][-1]
            seen.append((str(d.page_note.cget("text")), str(d._prev.cget("state")), str(d._next.cget("state"))))
            setup(d)
            seen.append((str(d.page_note.cget("text")), str(d.page_view.cget("text"))))
            d.accept()
        window.after(200, go)
        return PrintDialog(window, data, ["A", "B"], "B", lambda *a: None).result
    results.append(run(lambda d: d._show_page(step=1)))
    results.append(run(lambda d: (d.which.set("range"), d.range.set("1-2, 6"), d._show_page(step=5),
                                  d.printer.set("A"), d.copies.set("3"))))
    assert results == [("B", None, 1, [0, 1, 2, 3, 4, 5]), ("A", None, 3, [0, 1, 5])]
    # 開いたときは1枚目（［＜］は押せない）。ページの選び方を変えると、印刷する最初のページに戻る。最後より先には送らない
    assert seen == [("1 ページ（1 / 6）", "disabled", "normal"), ("2 ページ（2 / 6）", ""),
                    ("1 ページ（1 / 6）", "disabled", "normal"), ("6 ページ（3 / 3）", "")]

    def check(setup):
        def go():
            d = [c for c in window.winfo_children() if isinstance(c, PrintDialog)][-1]
            setup(d)
            seen.append((str(d.page_view.cget("text")), str(d._next.cget("state")),
                         str(d.page_view.cget("image")) == str(d._blank)))
            d.cancel()
        window.after(200, go)
        return PrintDialog(window, data, ["A"], "A", lambda *a: None).result
    seen.clear()
    assert check(lambda d: d.which.set("range")) is None
    assert check(lambda d: (d.which.set("range"), d.range.set("9"))) is None
    assert [s[:2] for s in seen] == [("ページを指定してください", "disabled"), ("ページの指定を読めません", "disabled")]
    # 読めないときは白い紙（大きさを変えない）
    assert all(s[2] for s in seen)

def test_pdf_name_is_shortened(window, tmp_path):
    """プレビューの上の PDF の名前は、入りきらなければ後ろを「…」で省き、マウスを重ねると全体を出す。［印刷］と
    ページの番号は押し出さない（2026-10-30）。"""
    window.deiconify()
    window.geometry("1000x700")
    window.update()
    name = "令和８年（ワ）第１２３４５号　損害賠償請求事件　原告第３準備書面（最終）" * 2 + ".pdf"
    window.session.pdf_path = tmp_path / name
    window.session.version = 1
    window._update_title()
    window.update()
    shown = str(window.pdf_name_label.cget("text"))
    assert shown.endswith("…") and f"プレビュー：{name}".startswith(shown[:-1])
    assert window._pdf_name_tip.text == f"プレビュー：{name}"
    row = window._pdf_name_row
    assert window.print_button.winfo_x() + window.print_button.winfo_width() <= window.page_label.winfo_x()
    assert window.page_label.winfo_x() + window.page_label.winfo_width() <= row.winfo_width()
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    window._update_title()
    window.update()
    assert str(window.pdf_name_label.cget("text")) == "プレビュー：準備書面.pdf"
    assert window._pdf_name_tip.text == ""          # 省かないときは、重ねても出さない
    window.session.pdf_path, window.session.version = None, 0
    window.withdraw()

def test_line_numbers_check(window, tmp_path):
    """「レイアウト」の［行番号］のチェックで行番号を付ける。構文ファイルの区切りの行に残し、内容証明では付けない
    （VA公用文のセットアップと同じ。2026-10-24 班長指示）。"""
    from va_document.doctypes import DOC_TYPES
    assert not window.line_numbers_var.get()
    window.line_numbers_check.invoke()
    assert window.session.settings.line_numbers and window.cfg.line_numbers
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    assert window.on_save()
    assert "行番号 あり" in window.session.vamd_path.read_text(encoding="utf-8")
    window.doc_type_box.set(DOC_TYPES["Naiyou"].label)
    window.on_settings_changed()
    assert not window.session.settings.line_numbers and not window.line_numbers_var.get()
    assert str(window.line_numbers_check.cget("state")) == "disabled"
    window.doc_type_box.set(DOC_TYPES["Saiban"].label)
    window.on_settings_changed()
    assert str(window.line_numbers_check.cget("state")) == "normal" and not window.session.settings.line_numbers

def test_one_width_check(window, tmp_path):
    """「レイアウト」の［番号1字］のチェックで、見出し番号を全角1字の幅に縮める。構文ファイルの区切りの行に残し、
    契約書1・技術文書では使えない（2026-10-26 班長指示）。"""
    from va_document.doctypes import DOC_TYPES
    window.text.delete("1.0", "end")
    window.text.insert("1.0", "#\n## 当事者\n## 次")
    window.refresh()
    assert not window.one_width_var.get() and not window.session.doc_type.one_width
    window.one_width_check.invoke()
    assert window.session.settings.one_width and window.cfg.one_width and window.session.doc_type.one_width
    assert "".join(g.ch for g in window.session.layout_map.lines[0].glyphs).startswith("第１１　当事者")
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    assert window.on_save()
    assert "番号1字 あり" in window.session.vamd_path.read_text(encoding="utf-8")
    window.doc_type_box.set(DOC_TYPES["Technical"].label)
    window.on_settings_changed()
    assert not window.session.settings.one_width and not window.one_width_var.get()
    assert str(window.one_width_check.cget("state")) == "disabled"
    window.doc_type_box.set(DOC_TYPES["Saiban"].label)
    window.on_settings_changed()
    assert str(window.one_width_check.cget("state")) == "normal" and not window.session.settings.one_width


def test_copy_vamd_saves_first_and_tells(window, tmp_path, monkeypatch):
    """［コピー］は、保存していない変更があれば先に保存し、保存したことも下の欄に出す（2026-10-26 班長指摘）。"""
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    window.on_copy_vamd()
    assert window.session.version == 1
    assert window.status.cget("text").startswith("版 1 を保存し、AI に渡す構文ファイル")
    assert window.clipboard_text() == window.session.vamd_path.read_text(encoding="utf-8")
    window.on_copy_vamd()                    # 保存していない変更がなければ、保存しない
    assert window.session.version == 1 and window.status.cget("text").startswith("AI に渡す構文ファイル")


def test_copy_vamd_path(window, tmp_path):
    """［パスをコピー］で構文ファイルのフルパスをコピーする（保存するまでは押せない。2026-10-24 班長指示）。"""
    assert str(window.copy_path_button.cget("state")) == "disabled"
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    assert window.on_save()
    assert str(window.copy_path_button.cget("state")) == "normal"
    window.clipboard_clear()
    window.copy_path_button.invoke()
    assert window.clipboard_text() == str(window.session.vamd_path) and window.session.vamd_path.is_absolute()
    assert "パスをコピーしました" in str(window.status.cget("text"))


def test_no_commands_for_reusing_documents(window):
    """過去の文書を使い回す［コピーとして開く］［名前を付けて保存］（F12）と、［すべて解除］は置かない
    （2026-10-25 班長決定。仕様.md の9.4）。"""
    found = {str(b.cget("text")).replace("\n", "") for b in _all_buttons(window)}
    assert "開く" in found and not found & {"変更", "解除"}       # 一覧の横の［解除］［変更］も置かない（2026-10-27 班長指示）
    assert not found & {"コピーとして開く", "名前を付けて保存", "すべて解除"}
    assert not window.bind("<F12>")
    assert not hasattr(window, "on_save_as") and not hasattr(window, "on_open_copy") and not hasattr(window, "on_unregister_all")


def test_edit_entry_and_released_check(window, tmp_path, monkeypatch):
    """一覧の［変更］：元の語を直す（記号はそのまま）・記号を変える。解除した語の残りの確かめ（2026-10-25 班長決定）。"""
    from types import SimpleNamespace
    # 元の語を変える：記号はそのまま、文章の中の記号がすべて新しい語になる。新しい語を打ってあれば記号にする
    window.text.insert("end", "丙川次郎の陳述書。\n")
    window.tree.selection_set("〔人名Ａ〕")
    monkeypatch.setattr(ai_ops, "EditDialog", lambda parent, e, d: SimpleNamespace(result=("丙川次郎", "人名", "Ａ")))
    window.on_edit_entry()
    assert window.raw_text() == PSEUDO + "〔人名Ａ〕の陳述書。\n"
    assert window.real_text() == TEXT.replace("甲野太郎", "丙川次郎") + "丙川次郎の陳述書。\n"
    assert window.tree.item("〔人名Ａ〕", "values")[1] == "丙川次郎"
    assert "「甲野太郎」から「丙川次郎」に" in str(window.status.cget("text"))
    # 前の名前が残っていれば、保存するときに知らせ、その所を選んで見せる
    window.text.insert("end", "甲野太郎の陳述書。\n")
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    asked = []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(a[1]) or False)
    assert not window.on_save()
    assert asked and "甲野太郎（1 か所）" in asked[0] and not window.session.pdf_path.exists()
    assert window.text.get("sel.first", "sel.last") == "甲野太郎"
    # 残してよいと答えれば保存し、次からは尋ねない
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(a[1]) or True)
    assert window.on_save()
    n = len(asked)
    window.text.insert("end", "追記。\n")
    assert window.on_save() and len(asked) == n
    # 記号を変える：エディターの記号も変わる。前の記号は、ほかの語に使い直さない
    monkeypatch.setattr(ai_ops, "EditDialog", lambda parent, e, d: SimpleNamespace(result=("丙川次郎", "人名", "x")))
    window.tree.selection_set("〔人名Ａ〕")
    window.on_edit_entry()
    assert "〔人名Ａ〕" not in window.raw_text() and "〔人名Ｘ〕の陳述書。" in window.raw_text()
    assert window.tree.get_children() == ("〔人名Ｘ〕",) and "〔人名Ａ〕 から 〔人名Ｘ〕" in str(window.status.cget("text"))
    assert window.session.dictionary.next_letters("人名") == "Ｂ"


def test_register_dialog_requires_letters(window, monkeypatch):
    """仮名化の画面：記号の字は自動で入れず、利用者が必ず打つ（英字・数字・漢字など。2026-10-25 班長決定・班長指示）。
    今ほかの語に使っている記号・空・使えない字なら、理由を知らせて画面を閉じない。解除した記号を別の語に付けるときは
    確かめる。この文書で使っている記号・解除した記号を示す。"""
    from va_document.dialogs import EditDialog, RegisterDialog
    d = window.session.dictionary                     # 甲野太郎＝〔人名Ａ〕
    d.register("丙川次郎", "人名", "B")
    d.unregister("丙川次郎")
    errors, asked, answers, seen = [], [], iter([False, True]), {}
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: errors.append(a[1]))
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(a[1]) or next(answers))

    def run():
        dlg = [c for c in window.winfo_children() if isinstance(c, RegisterDialog)][-1]
        assert dlg.letters.get() == ""
        seen["used"] = str(dlg.used_label.cget("text"))
        dlg.ok()                                       # 空のまま
        dlg.letters.set("a")
        dlg.ok()                                       # 今使っている記号
        dlg.letters.set("Ｘ Ｙ")
        dlg.ok()                                       # 空白は使えない
        dlg.letters.set("b")
        dlg.ok()                                       # 解除した記号：確かめて［いいえ］
        seen["after_no"] = dlg.winfo_exists()
        dlg.letters.set("相手方1")
        seen["preview"] = str(dlg.preview.cget("text"))
        dlg.letters.set("b")
        dlg.ok()                                       # 解除した記号：確かめて［はい］
    window.after(200, run)
    assert RegisterDialog(window, "丁野四郎", d).result == ("人名", "b")
    assert "〔人名Ａ〕（甲野太郎）" in seen["used"] and "〔人名Ｂ〕（丙川次郎）" in seen["used"]
    assert seen["preview"] == "記号：〔人名相手方１〕" and seen["after_no"]
    assert len(errors) == 3 and "入れて" in errors[0] and "使っています" in errors[1] and "数字だけ" in errors[2]
    assert len(asked) == 2 and "「丙川次郎」に使った記号" in asked[0]

    def run_edit():
        dlg = [c for c in window.winfo_children() if isinstance(c, EditDialog)][-1]
        assert dlg.letters.get() == "Ａ" and dlg.word.get() == "甲野太郎"
        assert "〔人名Ａ〕" not in str(dlg.used_label.cget("text"))      # 自分の記号は「使えない」に出さない
        dlg.word.set("甲野太朗")
        dlg.ok()
    window.after(200, run_edit)
    assert EditDialog(window, d.find("〔人名Ａ〕"), d).result == ("甲野太朗", "人名", "Ａ")
    assert len(asked) == 2                              # 自分の記号のままなら確かめない
    d.register("山田太郎", "人名", "yt")

    def run_edit2():
        dlg = [c for c in window.winfo_children() if isinstance(c, EditDialog)][-1]
        seen["edit"] = dlg.letters.get()
        dlg.cancel()
    window.after(200, run_edit2)
    assert EditDialog(window, d.find("〔人名ＹＴ〕"), d).result is None
    assert seen["edit"] == "ＹＴ"                       # 2字以上の記号も、その字を入れて開く


def test_edit_dialog_unregisters(window, monkeypatch):
    """一覧の横に［解除］［変更］のボタンを置かず、題の右に「（ダブルクリックで編集）」と書く。行のダブルクリックで開く
    変更の画面の［解除］で、確かめてから仮名化を解除する（2026-10-27 班長指示）。"""
    from tkinter import ttk
    from va_document.dialogs import UNREGISTER, EditDialog

    assert "（ダブルクリックで編集）" in {str(c.cget("text")) for c in _widgets(window, ttk.Label)}
    d = window.session.dictionary                     # 甲野太郎＝〔人名Ａ〕
    answers, asked = iter([False, True]), []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(a[1]) or next(answers))
    seen = {}

    def run():
        dlg = [c for c in window.winfo_children() if isinstance(c, EditDialog)][-1]
        dlg.unregister()                               # ［いいえ］：画面に戻る
        seen["after_no"] = dlg.winfo_exists()
        dlg.unregister()                               # ［はい］
    window.after(200, run)
    assert EditDialog(window, d.find("〔人名Ａ〕"), d).result == UNREGISTER
    assert seen["after_no"] and len(asked) == 2 and "「甲野太郎」（〔人名Ａ〕）の仮名化を解除しますか" in asked[0]
    # 一覧の行から開いて解除すると、エディターの記号が元の語に戻り、一覧から消える
    from types import SimpleNamespace
    monkeypatch.setattr(ai_ops, "EditDialog", lambda parent, e, dic: SimpleNamespace(result=UNREGISTER))
    window.tree.selection_set("〔人名Ａ〕")
    window.on_edit_entry()
    assert "〔人名Ａ〕" not in window.raw_text() and window.raw_text() == window.real_text() == TEXT
    assert window.tree.get_children() == () and "仮名化を解除しました" in str(window.status.cget("text"))


# ---------- 画像（[IMAGE 1]{30}。2026-10-29 班長決定） ----------

def _picture(size=(400, 300)):
    import io
    from PIL import Image
    from va_document import images
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 90, 160)).save(buf, "PNG")
    return images.from_bytes(buf.getvalue())


def test_image_button_inserts_line_and_undo(window, tmp_path, monkeypatch):
    """［画像］で画像ファイルを選ぶと、カーソルの行の次に [IMAGE n]{幅} の行が入り、確認表示に画像が出る。
    Ctrl+Z 1回で戻る。画像として読めないファイルは知らせる。"""
    from tkinter import ttk
    from va_document import image_ops
    assert "画像" in {str(b.cget("text")) for b in _widgets(window, ttk.Button)}
    good = tmp_path / "現場.png"
    good.write_bytes(__import__("base64").b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAAEElEQVR4nGP4z8DAwMDAAAAN+gH/4oXbOAAAAABJRU5ErkJggg=="))
    bad = tmp_path / "メモ.txt"
    bad.write_text("画像ではない", encoding="utf-8")
    errors = []
    monkeypatch.setattr(image_ops.filedialog, "askopenfilenames", lambda **k: (str(good), str(bad)))
    monkeypatch.setattr(image_ops.messagebox, "showerror", lambda *a, **k: errors.append(a[1]))
    window.text.mark_set("insert", "2.0")
    window.on_image()
    lines = window.raw_text().split("\n")
    assert lines[2] == "[IMAGE 1]{1}" and len(errors) == 1 and "読めない" in errors[0]
    assert window.session.images[1].size == (2, 1)
    assert [p.number for p in window.session.layout_map.ts.images] == [1]
    assert str(good) not in json.dumps(window.cfg.__dict__, ensure_ascii=False, default=str)   # 場所を覚えない
    window.text.edit_undo()
    assert "[IMAGE" not in window.raw_text()


def _text_lines(window):
    return window.raw_text().split("\n")


def test_insert_table(window):
    """［表］：入力画面なしで、カーソルの行の次に2列3行の空の表が入り、カーソルが最初のセルに来る。字を打てば確認表示に
    出る。Ctrl+Z 1回で戻る。"""
    from tkinter import ttk
    from va_document.document import TABLE
    assert "表" in {str(b.cget("text")) for b in _widgets(window, ttk.Button)}
    window.text.mark_set("insert", "4.3")
    window.on_table()
    assert _text_lines(window)[3:8] == [PSEUDO.split("\n")[3], "|  |  |", "|---|---|", "|  |  |", "|  |  |"]
    assert window.text.index("insert") == "5.2"
    window.text.insert("insert", "項目")
    window.refresh()
    assert any(p.kind == TABLE for p in window.session.layout_map.paras)
    import pdfcheck
    assert "項目" in pdfcheck.text(window.session.preview_pdf(window.real_text(), highlight=True))
    window.text.edit_undo()
    window.text.edit_undo()
    assert window.raw_text() == PSEUDO


@pytest.mark.parametrize("text, cursor, expected", [
    ("本文\n\n本文", "2.0", ["本文", "H", "S", "H", "H", "本文"]),                         # 空の行はその行に入れる
    ("本文\n", "2.0", ["本文", "H", "S", "H", "H", ""]),                                  # 文書の最後は、後ろに空の行
    ("| a |\n|---|\n| b |\n本文", "1.0", ["| a |", "|---|", "| b |", "", "H", "S", "H", "H", "本文"]),  # 表の中なら表の後
    ("| a |\n|---|\n\n本文", "3.0", ["| a |", "|---|", "", "H", "S", "H", "H", "本文"]),  # 前が表の空の行は残す
    ("本文\n\n| a |\n|---|", "2.0", ["本文", "H", "S", "H", "H", "", "| a |", "|---|"]),  # 後が表の空の行も残す
    ("本文\n| a |\n|---|", "1.0", ["本文", "H", "S", "H", "H", "", "| a |", "|---|"]),    # 表の直前の行
    ("| a |\n|---|\n\n| b |\n|---|", "3.0",
     ["| a |", "|---|", "", "H", "S", "H", "H", "", "| b |", "|---|"]),                   # 表の間
])
def test_insert_table_keeps_tables_apart(window, text, cursor, expected):
    """表が隣の表とつながらないよう、間に空の行を置く（| の行が続くと1つの表になるため）。"""
    from va_document.document import TABLE, parse
    from va_document.table_ops import table_lines
    window._load_text(text)
    window.text.mark_set("insert", cursor)
    first = window._insert_block(table_lines(2, 3))
    assert _text_lines(window) == [{"H": "|  |  |", "S": "|---|---|"}.get(x, x) for x in expected]
    assert window._line(first) == "|  |  |" and window._line(first + 1) == "|---|---|"
    tables = sum(p.kind == TABLE for p in parse(_text_lines(window), window.session.doc_type))
    assert tables == 1 + text.count("|---|")


def _in_table(window, cursor="4.3"):
    window._load_text("本文\n| 項目 | 金額 |\n|---|---:|\n| 休業 | 100 |\n| 通院 | 200 |\n本文\n")
    window.text.mark_set("insert", cursor)


def test_table_column_widths_menu(window):
    """［表］のメニュー：「列の幅を固定する」で今の字数を書き入れ、「列の幅を自動に戻す」で外す。どちらも Ctrl+Z 1回で
    戻り、カーソルは動かない。すべての列を固定したら「固定する」は出さず、指定がなければ「自動に戻す」は出さない
    （2026-11-01 班長決定）。"""
    labels = lambda: [x[0] for x in window._table_menu_items((2, 5))]
    window._load_text("前\n| 項目 | 金額 |\n|---|---:|\n| 休業損害 | 1,000 |\n| 慰謝料 | 500 |\n")
    window.text.mark_set("insert", "4.3")
    assert "列の幅を固定する" in labels() and "列の幅を自動に戻す" not in labels()
    window.on_table_fix_widths()
    line = window._line(3)
    assert re.fullmatch(r"\|---\{\d+\}\|---:\{\d+\}\|", line)
    assert window.text.index("insert") == "4.3"
    assert "列の幅を固定する" not in labels() and "列の幅を自動に戻す" in labels()
    assert "表の2行目" in window.status.cget("text")
    window.refresh()
    assert window.session.layout_map.table_piece(1) is not None
    window.on_undo()
    assert window._line(3) == "|---|---:|"
    window.on_redo()
    window.on_table_auto_widths()
    assert window._line(3) == "|---|---:|"
    window.on_undo()
    assert window._line(3) == line
    # 一部の列だけに字数があれば、どちらも出す。固定すると、書いてある列の字数は変わらない
    window.text.mark_set("insert", "4.3")
    window._set_column_widths(3, [8])
    assert window._line(3) == "|---{8}|---:|"
    assert "列の幅を固定する" in labels() and "列の幅を自動に戻す" in labels()
    window.on_table_fix_widths()
    assert window._line(3).startswith("|---{8}|---:{")
    # 区切りの行に空白があっても、字数だけを書き換える
    window.text.delete("3.0", "3.end")
    window.text.insert("3.0", "| --- | :---: |")
    window._set_column_widths(3, [6, 7])
    assert window._line(3) == "| ---{6} | :---:{7} |"


def test_table_widths_with_other_table_operations(window):
    """{字数} のある表で、列の配置・2重線・列の追加が字数を壊さない。表として読め、保存する文書にも残る。"""
    window._load_text("| 項目 | 金額 |\n|---{8}|---{10}|\n| 休業損害 | 1,000 |\n")
    window.text.mark_set("insert", "2.10")
    window.on_align("--: ")
    assert window._line(2) == "|---{8}|---:{10}|"
    window.on_align(":-: ")
    assert window._line(2) == "|---{8}|:---:{10}|"
    window.on_align(":-: ")
    assert window._line(2) == "|---{8}|---{10}|"
    window.on_table_double()
    assert window._line(2) == "|==={8}|==={10}|"
    window.on_table_double()
    assert window._line(2) == "|---{8}|---{10}|"
    window.text.mark_set("insert", "3.3")
    window.on_table_column()
    assert window._line(2) == "|---{8}|---|---{10}|"
    window.refresh()
    assert window.session.layout_map.table_piece(0) is not None
    assert "|---{8}|---|---{10}|" in window.session.body(window.real_text())


def test_table_menu_only_in_table(window, monkeypatch):
    """表の中の［表］は表を入れず、メニューを出す。2重線の項目の字は、今の線で変わる。"""
    posted = []
    monkeypatch.setattr(window, "_post_table_menu", lambda span: posted.append(span))
    _in_table(window)
    before = window.raw_text()
    window.on_table()
    assert posted == [(2, 5)] and window.raw_text() == before
    assert [x[0] for x in window._table_menu_items((2, 5))] == ["右に列を足す", "見出しの下を2重線にする", "列の幅を固定する"]
    window.on_table_double()
    assert window._line(3) == "|===|===:|"
    assert [x[0] for x in window._table_menu_items((2, 5))][1] == "見出しの下を1重線に戻す"
    window.on_table_double()
    assert window._line(3) == "|---|---:|"
    window.text.edit_undo()
    assert window._line(3) == "|===|===:|"


def test_table_add_column(window):
    """カーソルのセルの右に列を足す。Ctrl+Z 1回で戻る。2重線の表には = で足す。"""
    from va_document.document import parse_table
    _in_table(window, "4.3")
    window.on_table_column()
    assert window._line(2) == "| 項目 |  | 金額 |" and window._line(3) == "|---|---|---:|"
    assert window._line(4) == "| 休業 |  | 100 |" and window._line(5) == "| 通院 |  | 200 |"
    assert window._cursor() == (4, 7)
    assert len(parse_table([window._line(k) for k in range(2, 6)]).header) == 3
    window.text.edit_undo()
    assert window._line(2) == "| 項目 | 金額 |"
    window.on_table_double()
    window.text.mark_set("insert", "4.10")      # 最後の列
    window.on_table_column()
    assert window._line(3) == "|===|===:|===|" and window._line(4) == "| 休業 | 100 |  |"


@pytest.mark.parametrize("cursor, row, added", [
    ("2.3", 4, True), ("3.1", 4, True), ("4.3", 5, True), ("5.3", 6, True),   # 見出し・区切りの行では区切りの行の下に
    ("4.0", 5, True), ("4.100", 5, True),                                     # 表の途中の行は、行の外側でも足す
    ("2.0", None, False), ("5.100", None, False),                             # 表の前・後に行を入れるのは、ふつうの改行
    ("1.1", None, False), ("6.1", None, False),                               # 表の外
])
def test_table_enter_adds_row(window, cursor, row, added):
    _in_table(window, cursor)
    before = window.raw_text()
    if added:
        assert window.on_editor_return() == "break"
        assert window._line(row) == "|  |  |" and window._cursor() == (row, 2)
        assert window._table_range(row) == (2, 6)
        window.text.edit_undo()
        assert window.raw_text() == before
    else:
        assert window.on_editor_return() is None and window.raw_text() == before


def test_table_enter_with_selection_is_ordinary(window):
    _in_table(window)
    window.text.tag_add("sel", "4.2", "4.4")
    assert window.on_editor_return() is None


def test_table_tab_moves_between_cells(window):
    """Tab で次のセル、Shift+Tab で前のセルへ。区切りの行は飛ばす。最後のセルの Tab は行を足す。表の外はタブのまま。"""
    _in_table(window, "2.3")
    seen = []
    for _ in range(4):
        assert window.on_table_tab() == "break"
        seen.append(window.text.get("insert linestart", "insert"))
    assert seen == ["| 項目 | 金額", "| 休業", "| 休業 | 100", "| 通院"]
    window.text.mark_set("insert", "5.9")
    assert window.on_table_tab() == "break"
    assert window._line(6) == "|  |  |" and window._cursor() == (6, 2)
    assert window._table_range(6) == (2, 6)
    assert window.on_table_tab(-1) == "break" and window.text.get("insert linestart", "insert") == "| 通院 | 200"
    window.text.mark_set("insert", "2.3")
    assert window.on_table_tab(-1) == "break" and window._cursor() == (2, 3)        # 最初のセルより前には動かない
    window.text.mark_set("insert", "1.1")
    assert window.on_table_tab() is None


def test_table_keys_reach_the_editor(window, monkeypatch):
    """実際の Enter・Tab・Shift+Tab・Ctrl+Shift+V のキーで働く。表の外の Tab はタブの字を入れる。"""
    _focus_editor(window)
    _in_table(window, "4.3")
    window.text.event_generate("<Return>")
    assert window._line(5) == "|  |  |" and window._cursor() == (5, 2)
    window.text.event_generate("<Tab>")
    assert window._cursor() == (5, 5)
    window.text.event_generate("<Shift-Tab>")
    assert window._cursor() == (5, 2)
    window.text.mark_set("insert", "1.2")
    window.text.event_generate("<Tab>")
    assert window._line(1) == "本文\t"
    monkeypatch.setattr(window, "clipboard_text", lambda: "字\t字\n字\t字")
    window.text.event_generate("<Control-Shift-Key-V>")
    assert window._line(1) == "本文\t字\t字" and window._line(2) == "字\t字"


def test_table_tab_moves_to_blank_cell(window):
    """字のないセルは、空白の間にカーソルを置く（打つと「| 字 |」になる）。"""
    window._load_text("")
    window.on_table()
    window.on_table_tab()
    assert window._cursor() == (1, 5)
    window.text.insert("insert", "金額")
    assert window._line(1) == "|  | 金額 |"


def test_paste_excel_table(window, monkeypatch):
    """Ctrl+V：表のコピーは、カーソルの行の次に表として貼る（仮名化した語は記号に）。Ctrl+Z 1回で戻る。
    Ctrl+Shift+V は字のまま貼る。"""
    monkeypatch.setattr(window, "clipboard_text", lambda: "氏名\t金額\r\n甲野太郎\t1,080,000\r\nA|B\t\r\n")
    window.text.mark_set("insert", "4.2")
    assert window._on_paste() == "break"
    assert _text_lines(window)[3:8] == [PSEUDO.split("\n")[3], "| 氏名 | 金額 |", "|---|---|",
                                   "| 〔人名Ａ〕 | 1,080,000 |", "| A\\|B |  |"]
    window.text.edit_undo()
    assert window.raw_text() == PSEUDO
    window.text.mark_set("insert", "4.2")
    assert window.on_paste_plain() == "break"
    assert "氏名\t金額" in window.raw_text() and "〔人名Ａ〕\t1,080,000" in window.raw_text() and "|---|" not in window.raw_text()
    window.text.edit_undo()
    assert window.raw_text() == PSEUDO


def test_editor_context_menu(window, monkeypatch):
    """右クリックのメニュー：［コピー］［貼り付け］［選択範囲を仮名化…］。範囲の外で押すと選択を外してカーソルを動かし、
    中で押すと選択はそのまま。選んでいなければ［コピー］［選択範囲を仮名化…］は押せない。［貼り付け］は Ctrl+V と同じく、
    仮名化した語を記号にして貼る。［選択範囲を仮名化…］はリボンの［選択範囲を仮名化］と同じ働き。"""
    from types import SimpleNamespace
    menu = window.editor_menu
    assert [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) == "command"] == [
        "コピー", "貼り付け", "選択範囲を仮名化…"]
    assert window.text.bind("<Button-3>")
    posted = []
    monkeypatch.setattr(menu, "tk_popup", lambda x, y: posted.append((x, y)))
    # 隠したウィンドウでは @x,y の位置が決まらないので、押した所の位置を差し替える
    at = {"index": "4.1"}
    real_index = window.text.index
    monkeypatch.setattr(window.text, "index", lambda i: at["index"] if str(i).startswith("@") else real_index(i))
    click = SimpleNamespace(x=1, y=1, x_root=100, y_root=200)

    # 選んだ範囲の中で押す：選択はそのまま、［コピー］を押せる
    window.text.tag_add("sel", "4.0", "4.3")
    assert window.on_editor_menu(click) == "break"
    assert posted == [(100, 200)]
    assert window._sel_range() == ("4.0", "4.3")
    assert menu.entrycget(0, "state") == "normal"
    assert menu.entrycget("選択範囲を仮名化…", "state") == "normal"
    sent = []
    real_generate = window.text.event_generate
    monkeypatch.setattr(window.text, "event_generate", lambda seq: sent.append(seq))   # 班長のクリップボードに書かない
    menu.invoke(0)
    assert sent == ["<<Copy>>"]
    monkeypatch.setattr(window.text, "event_generate", real_generate)

    # 範囲の外で押す：選択を外して、カーソルを押した所へ動かす。［コピー］は押せない
    at["index"] = "2.1"
    window.on_editor_menu(click)
    assert window._sel_range() is None
    assert window.text.index("insert") == "2.1"
    assert menu.entrycget(0, "state") == "disabled"
    assert menu.entrycget("選択範囲を仮名化…", "state") == "disabled"

    # ［貼り付け］は Ctrl+V と同じ働き（仮名化した語を記号に置き換える）
    monkeypatch.setattr(window, "clipboard_text", lambda: "甲野太郎")
    menu.invoke(1)
    assert window._line(2) == ":〔人名Ａ〕=: 準備書面（１）"
    window.text.edit_undo()
    assert window.raw_text() == PSEUDO

    # ［選択範囲を仮名化…］は、リボンの［選択範囲を仮名化］と同じく、記号の英字を選ぶ画面を開いて仮名化する。
    # Ctrl+Z 1回で、一覧の語ごと戻る
    monkeypatch.setattr(ai_ops, "RegisterDialog", lambda parent, word, d: type("D", (), {"result": ("人名", "b")})())
    window.text.tag_add("sel", "4.6", "4.8")        # 「主張」
    at["index"] = "4.7"
    window.on_editor_menu(click)
    menu.invoke("選択範囲を仮名化…")
    assert window._line(4) == "〔人名Ａ〕の〔人名Ｂ〕は争う。"
    assert window.session.dictionary.find("主張") is not None
    window.on_undo()
    assert window.raw_text() == PSEUDO
    assert window.session.dictionary.find("主張") is None


def _image_line(window, width=12, lead=":-: "):
    n = window.session.add_picture(_picture(), window.raw_text())
    window.text.insert("end", f"{lead}[IMAGE {n}]{{{width}}}\n")
    line = int(window.text.index("end-1c").split(".")[0]) - 1
    window.text.mark_set("insert", f"{line}.2")
    return n, line


def test_image_button_on_image_line_opens_menu(window, monkeypatch):
    """画像の行の［画像］は、ファイルを選ばずメニューを出す。データのない画像には「元の大きさ」を出さない。"""
    from va_document import image_ops
    posted = []
    monkeypatch.setattr(window, "_post_image_menu", posted.append)
    monkeypatch.setattr(image_ops.filedialog, "askopenfilenames", lambda **k: pytest.fail("ファイルを選ばない"))
    n, _ = _image_line(window)
    window.on_image()
    assert posted == [n]
    assert [x[0] for x in window._image_menu_items(n)] == ["別の画像に差し替える", "元の大きさにする", "本文の幅いっぱいにする"]
    assert [x[0] for x in window._image_menu_items(99)] == ["別の画像に差し替える", "本文の幅いっぱいにする"]


def test_image_replace_keeps_width_and_align(window, tmp_path, monkeypatch):
    """差し替え：幅と配置はそのままで番号が替わり、Ctrl+Z 1回で元の画像に戻る。読めないファイル・やめたときは替わらない。"""
    from va_document import image_ops
    n, line = _image_line(window)
    good, bad = tmp_path / "新.png", tmp_path / "メモ.txt"
    good.write_bytes(__import__("base64").b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAAEElEQVR4nGP4z8DAwMDAAAAN+gH/4oXbOAAAAABJRU5ErkJggg=="))
    bad.write_text("画像ではない", encoding="utf-8")
    errors = []
    monkeypatch.setattr(image_ops.messagebox, "showerror", lambda *a, **k: errors.append(a[1]))
    before = window.raw_text()
    for path in ("", str(bad)):
        monkeypatch.setattr(image_ops.filedialog, "askopenfilename", lambda **k: path)
        window.on_image_replace()
        assert window.raw_text() == before
    assert len(errors) == 1 and "読めない" in errors[0]
    monkeypatch.setattr(image_ops.filedialog, "askopenfilename", lambda **k: str(good))
    window.on_image_replace()
    assert window._line(line) == f":-: [IMAGE {n + 1}]{{12}}"
    assert window.session.images[n + 1].size == (2, 1) and window.session.images[n].size == (400, 300)
    assert [p.number for p in window.session.layout_map.ts.images] == [n + 1]
    window.text.edit_undo()
    assert window.raw_text() == before
    assert str(good) not in json.dumps(window.cfg.__dict__, ensure_ascii=False, default=str)   # 場所を覚えない


def test_image_replace_fills_missing_image(window, tmp_path, monkeypatch):
    """データのない画像の行も差し替えられ、番号の知らせが消える。"""
    from va_document import image_ops
    window.text.insert("end", "--: [IMAGE 7]{9}\n")
    window.text.mark_set("insert", "5.0")
    path = tmp_path / "新.png"
    path.write_bytes(__import__("base64").b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAAEElEQVR4nGP4z8DAwMDAAAAN+gH/4oXbOAAAAABJRU5ErkJggg=="))
    monkeypatch.setattr(image_ops.filedialog, "askopenfilename", lambda **k: str(path))
    window.on_image_replace()
    assert window._line(5) == "--: [IMAGE 8]{9}" and window.session.missing_images(window.raw_text()) == []


def test_image_width_items(window):
    """幅のメニュー：元の大きさは入れたときの字数、いっぱいは1行の字数。組むときは置ける幅に収まる。Ctrl+Z 1回で戻る。"""
    n, line = _image_line(window, width=12, lead="")
    chars = window.session.doc_type.chars_lines[0]
    natural = window._natural_width(window.session.images[n])
    window.on_image_full_width()
    assert window._line(line) == f"[IMAGE {n}]{{{chars}}}"
    piece = window.session.layout_map.ts.images[0]
    assert piece.x + piece.w <= window.session.layout_map.ts.text_w + window.session.layout_map.ts.margin_left + 0.01
    window.on_image_natural_width()
    assert window._line(line) == f"[IMAGE {n}]{{{natural}}}"
    window.text.edit_undo()
    assert window._line(line) == f"[IMAGE {n}]{{{chars}}}"
    window.text.edit_undo()
    assert window._line(line) == f"[IMAGE {n}]{{12}}"


def test_image_width_without_braces_and_lowercase(window):
    """幅を省いた行・小文字の記号も書き換えられる。"""
    window.text.insert("end", "[image 3]\n")
    window.text.mark_set("insert", "5.0")
    window.on_image_full_width()
    assert window._line(5) == f"[IMAGE 3]{{{window.session.doc_type.chars_lines[0]}}}"


def test_paste_word_formats(window, monkeypatch):
    """Ctrl+V：Word の書式を記号にして貼る。行の途中では配置の記号を付けない。Ctrl+Z 1回で戻る。Ctrl+Shift+V は字だけ。"""
    from va_document import html_paste
    from test_html_paste import cf_html
    data = cf_html("<p align=center style='text-align:center'><b>甲野太郎</b>の主張</p><p>次の行</p>")
    monkeypatch.setattr(html_paste, "read_html", lambda: data)
    monkeypatch.setattr(window, "clipboard_text", lambda: "甲野太郎の主張\n次の行")
    window.text.mark_set("insert", "end-1c")
    assert window._on_paste() == "break"
    assert _text_lines(window)[4:6] == [":-: **〔人名Ａ〕**の主張", "次の行"]
    window.text.edit_undo()
    assert window.raw_text() == PSEUDO
    window.text.mark_set("insert", "4.1")
    assert window._on_paste() == "break"
    assert window._line(4).endswith("**〔人名Ａ〕**の主張") and ":-:" not in window._line(4)
    window.text.edit_undo()
    window.text.mark_set("insert", "end-1c")
    window.on_paste_plain()
    assert _text_lines(window)[4:6] == ["〔人名Ａ〕の主張", "次の行"]


def test_paste_browser_formats(window, monkeypatch):
    """Ctrl+V：ブラウザーの書式も記号にして貼る。Ctrl+Shift+V は字だけ。"""
    from va_document import html_paste
    from test_html_paste import browser_html
    data = browser_html('<p style="font-weight: 400"><strong>甲野太郎</strong>の主張</p><p style="text-align: right">次の行</p>')
    monkeypatch.setattr(html_paste, "read_html", lambda: data)
    monkeypatch.setattr(window, "clipboard_text", lambda: "甲野太郎の主張\n\n次の行")
    window.text.mark_set("insert", "end-1c")
    assert window._on_paste() == "break"
    assert _text_lines(window)[4:7] == ["**〔人名Ａ〕**の主張", "", "--: 次の行"]
    window.text.edit_undo()
    assert window.raw_text() == PSEUDO
    window.text.mark_set("insert", "end-1c")
    window.on_paste_plain()
    assert _text_lines(window)[4:7] == ["〔人名Ａ〕の主張", "", "次の行"]


def test_paste_word_table_is_placed_like_table(window, monkeypatch):
    from va_document import html_paste
    from test_html_paste import cf_html
    data = cf_html("<table><tr><td><p><b>項目</b></p></td><td><p>金額</p></td></tr>"
                   "<tr><td><p>休業</p></td><td><p align=right>100</p></td></tr></table>")
    monkeypatch.setattr(html_paste, "read_html", lambda: data)
    monkeypatch.setattr(window, "clipboard_text", lambda: "項目\t金額\n休業\t100\n")
    window.text.mark_set("insert", "4.1")
    assert window._on_paste() == "break"
    assert _text_lines(window)[4:7] == ["| **項目** | 金額 |", "|---|---|", "| 休業 | --: 100 |"]


def test_paste_plain_replaces_selection_in_one_undo(window, monkeypatch):
    monkeypatch.setattr(window, "clipboard_text", lambda: "字\t字")
    window.text.tag_add("sel", "4.0", "4.3")
    window.text.mark_set("insert", "4.3")
    window.on_paste_plain()
    assert window._line(4).startswith("字\t字")
    window.text.edit_undo()
    assert window.raw_text() == PSEUDO


@pytest.mark.parametrize("clip, is_table", [
    ("a\tb\nc\td\n", True),
    ("a\tb\tc", False),                     # 1行だけ
    ("a\nb\n", False),                      # タブがない
    ("a\tb\nc\n", False),                   # タブの数がそろわない
    ("a\tb\n\nc\td\n", False),              # 空の行がある
    ('A\t"x\ny"\tC\n', False),              # セルの中の改行（Excel は " で囲む）
    ('"甲"\tb\nc\td\n', True),              # 字としての " は、両端にあれば残す
])
def test_clipboard_table(clip, is_table):
    from va_document.table_ops import clipboard_table
    assert (clipboard_table(clip) is not None) == is_table


def test_empty_table_goes_through_save(window, tmp_path):
    """空のセルのある表でも、組む・保存するが通る。"""
    window.text.mark_set("insert", "end")
    window.on_table()
    window.refresh()
    window.update()
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    assert window.on_save() and window.session.version == 1


def test_paste_image_from_clipboard(window, monkeypatch):
    """Ctrl+V：クリップボードに字がなく画像だけがあれば画像を入れる（Win+V で選んだ画像も、ここを通る）。字があれば
    （Excel・Word からのコピーは字と画像の両方）、今までどおり字を貼る。"""
    from va_document import image_ops
    calls = []
    monkeypatch.setattr(window, "clipboard_text", lambda: None)
    monkeypatch.setattr(image_ops.images, "from_clipboard", lambda: calls.append(1) or [_picture(), _picture()])
    window.text.mark_set("insert", "end")
    assert window._on_paste() == "break"
    assert window.raw_text().rstrip("\n").split("\n")[-2:] == ["[IMAGE 1]{25}", "[IMAGE 2]{25}"]
    window.text.edit_undo()                                   # 2つとも Ctrl+Z 1回で戻る
    assert "[IMAGE" not in window.raw_text()
    monkeypatch.setattr(window, "clipboard_text", lambda: "ふつうの文章")
    assert window._on_paste() is None and len(calls) == 1
    monkeypatch.setattr(window, "clipboard_text", lambda: None)
    monkeypatch.setattr(image_ops.images, "from_clipboard", lambda: [])
    assert window._on_paste() is None


def test_save_asks_when_image_data_is_missing(window, tmp_path, monkeypatch):
    """画像のデータがない [IMAGE n] があれば、カーソルをその行に動かし、保存するかを尋ねる（既定は保存しない）。"""
    window.text.insert("end", "[IMAGE 5]{10}\n")
    window.session.pdf_path = tmp_path / "準備書面.pdf"
    asked = []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append((a[1], k.get("default"))) or False)
    assert not window.on_save() and window.session.version == 0
    assert "[IMAGE 5]" in asked[0][0] and asked[0][1] == messagebox.NO
    assert window.text.index("insert").startswith("5.")
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    assert window.on_save() and window.session.version == 1


def test_image_preview_links_to_editor(window):
    """確認表示の画像を押すと、エディターの画像の行へ。エディターの画像の行は、確認表示の画像の位置。"""
    n = window.session.add_picture(_picture(), window.raw_text())
    window.text.insert("end", f":-: [IMAGE {n}]{{20}}\n")
    window.refresh()
    m = window.session.layout_map
    piece = m.ts.images[0]
    line = len(window.raw_text().split("\n")) - 2
    assert m.hit(piece.page - 1, m.ts.margin_left + piece.x + piece.w / 2, piece.y + piece.h / 2) == (line, 4)
    assert m.locate(line, 4) == (piece.page - 1, m.ts.margin_left + piece.x, piece.y, piece.h)
    assert window._preview_doc.has_images(0)
    # ［右］で右に置き、もう一度押すと標準に戻す（配置のボタンは画像の行にも効く）
    window.text.mark_set("insert", f"{line + 1}.0")
    window.on_align(RIGHT_MARK)
    assert window.text.get(f"{line + 1}.0", f"{line + 1}.end") == f"--: [IMAGE {n}]{{20}}"
    window.refresh()
    im = window.session.layout_map.ts.images[0]
    assert im.wrap and window._preview_doc.has_images(0)          # 回り込ませる画像は、後に本文がなくても描く


# ---------- ［ファイルから読み込む］（2026-10-29 班長決定） ----------

def _first_document(window, tmp_path):
    """同じ案件の前の文書（甲野太郎＝〔人名Ａ〕、乙山商事株式会社＝〔法人Ｘ〕）を保存する。"""
    s = app.Session(window.cfg)
    s.dictionary.register("甲野太郎", "人名", "Ａ")
    s.dictionary.register("乙山商事株式会社", "法人", "Ｘ")
    pdf = tmp_path / "事件" / "訴状.pdf"
    pdf.parent.mkdir()
    s.save("原告　甲野太郎\n被告　乙山商事株式会社\n", pdf)
    return pdf


def test_load_entries_from_file(window, tmp_path, monkeypatch):
    """「仮名化した語（ダブルクリックで編集）」の右の［ファイルから読み込む］で、同じ案件の文書の仮名化した語を、確認の画面で
    確かめてから今の一覧に足す。エディターの読み込んだ語は記号になり、PDF の字は変わらない。選んだ場所は覚えない。"""
    from tkinter import ttk
    from va_document.dialogs import LoadEntriesDialog
    note = next(c for c in _widgets(window, ttk.Label) if str(c.cget("text")) == "（ダブルクリックで編集）")
    button = next(c for c in _widgets(window, ttk.Button) if str(c.cget("text")) == "ファイルから読み込む")
    assert button.master == note.master and button.winfo_x() >= note.winfo_x()
    pdf = _first_document(window, tmp_path)
    folders = list(window.cfg.pdf_folders)
    monkeypatch.setattr(ai_ops.filedialog, "askopenfilename", lambda **k: str(pdf))
    window.text.insert("end", "乙山商事株式会社の主張は争う。\n")
    window.refresh()
    real = window.real_text()
    # ［やめる］なら何も変わらない
    monkeypatch.setattr(ai_ops, "LoadEntriesDialog", lambda parent, loaded: type("D", (), {"ok": False})())
    window.on_load_entries()
    assert set(window.session.dictionary.entries) == {"甲野太郎"} and "乙山商事株式会社の" in window.raw_text()
    # ［読み込む］（本物の確認の画面で押す）
    monkeypatch.setattr(ai_ops, "LoadEntriesDialog", LoadEntriesDialog)
    seen = {}

    def press():
        dlg = [c for c in window.winfo_children() if isinstance(c, LoadEntriesDialog)][-1]
        seen["text"] = " ".join(str(c.cget("text")) for c in _widgets(dlg, ttk.Label))
        dlg.accept()
    window.after(200, press)
    window.on_load_entries()
    assert "訴状.pdf" in seen["text"] and "1 語読み込みます" in seen["text"] and "同じ語・同じ記号" in seen["text"]
    assert window.session.dictionary.find("〔法人Ｘ〕").word == "乙山商事株式会社"
    assert "〔法人Ｘ〕の主張は争う。" in window.raw_text() and window.real_text() == real    # PDF の字は変わらない
    assert window.tree.exists("〔法人Ｘ〕") and "1 語読み込みました" in str(window.status.cget("text"))
    assert window.cfg.pdf_folders == folders


def test_load_entries_conflict_loads_nothing(window, tmp_path, monkeypatch):
    """この文書の一覧と食い違う語があれば、何も読み込まずに知らせる。"""
    pdf = _first_document(window, tmp_path)
    window.session.dictionary.register("乙山商事株式会社", "法人", "Ｂ")
    shown = []
    monkeypatch.setattr(ai_ops.filedialog, "askopenfilename", lambda **k: str(pdf))
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: shown.append(a[1]))
    monkeypatch.setattr(ai_ops, "LoadEntriesDialog", lambda *a: pytest.fail("確認の画面を出さない"))
    window.on_load_entries()
    assert shown and "食い違う" in shown[0] and "〔法人Ｂ〕" in shown[0]
    assert set(window.session.dictionary.entries) == {"甲野太郎", "乙山商事株式会社"}


def test_load_entries_asks_for_missing_pdf(window, tmp_path, monkeypatch):
    """構文ファイルを選び、PDF が保存したフォルダに見つからないときは、PDF を選ぶかを尋ね、選んだ PDF で読み込む
    （相手のファイルを選んでもらう画面は、開くときと共通の ask_other_file）。"""
    pdf = _first_document(window, tmp_path)
    moved = tmp_path / "別の場所" / "訴状.pdf"
    moved.parent.mkdir()
    pdf.rename(moved)
    vamd_path = next(Path(window.cfg.vamd_folder).glob("*.vamd"))
    asked, picked = [], []

    def pick(**k):                  # ai_ops と file_ops は同じ tkinter.filedialog を使うので、画面の題で分ける
        picked.append(k["title"])
        return str(moved) if k["title"] == "PDF を選ぶ" else str(vamd_path)
    monkeypatch.setattr(file_ops.filedialog, "askopenfilename", pick)
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(a[1]) or True)
    monkeypatch.setattr(ai_ops, "LoadEntriesDialog", lambda parent, loaded: type("D", (), {"ok": True})())
    window.on_load_entries()
    assert asked and "PDF を選びますか" in asked[0] and picked == ["仮名化する語を読み込むファイル", "PDF を選ぶ"]
    assert window.session.dictionary.find("〔法人Ｘ〕").word == "乙山商事株式会社"


# ---------- ヘルプ・診断情報（2026-11-10 班長決定） ----------

def test_help_menu(window, monkeypatch):
    """メニューバーは「ファイル」と「ヘルプ」。「ファイル」に［開く…］［保存］［閉じる］と、一番下に［オプション…］
    （［オプション］はリボンには置かない。［印刷］は置かない。2026-11-14 班長指示）、「ヘルプ」に［診断情報をコピー］と
    ［VA Document について］がある。"""
    def commands(menu):
        return [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) == "command"]
    assert [window.menu_bar.entrycget(i, "label") for i in range(window.menu_bar.index("end") + 1)
            if window.menu_bar.type(i) == "cascade"] == ["ファイル", "ヘルプ"]
    f = window.file_menu
    assert [f.type(i) if f.type(i) == "separator" else f.entrycget(i, "label") for i in range(f.index("end") + 1)] == \
        ["開く…", "保存", "閉じる", "separator", "オプション…"]
    assert [f.entrycget(i, "accelerator") for i in range(3)] == ["Ctrl+O", "Ctrl+S", "Ctrl+W"]
    # どの項目も、リボンのボタンと同じ操作を呼ぶ
    called = []
    for name in ("on_open", "on_save", "on_print", "on_options", "on_close_document"):
        monkeypatch.setattr(window, name, lambda n=name: called.append(n))
    for i in range(f.index("end") + 1):
        if f.type(i) == "command":
            f.invoke(i)
    assert called == ["on_open", "on_save", "on_close_document", "on_options"]
    assert commands(window.help_menu) == ["診断情報をコピー", "VA Document について"]
    assert window.menu_bar.entrycget(window.menu_bar.index("end"), "label") == "ヘルプ"
    # メニューバーは、ウィンドウを表示してから付ける（_build_menu。前の大きさ・位置に戻すのは test_window_position_is_restored）
    window.update_idletasks()
    assert str(window.cget("menu")) == str(window.menu_bar)
    # 「について」は VA Case・VA FAX と同じ形（名前と版・1行の説明・空の行・作った者・ライセンス。2026-11-14 班長指示）
    assert window.about_text().split("\n") == [f"VA Document  {app.VERSION_LABEL}", window.ABOUT_LINE, "",
                                               "VBAアセット（vba-assets.net）", "MIT License"]


def test_diagnostic_text_has_no_contents(window, tmp_path, monkeypatch):
    """診断情報に、文章・仮名化した語と記号・ファイルの名前・フォルダの場所・例外のメッセージの本文が入らない。"""
    pdf = _first_document(window, tmp_path)                 # 「訴状.pdf」として保存した文書（仮名化した語あり）
    secret = tmp_path / "甲野太郎の事件"
    secret.mkdir()
    window.cfg.vamd_folder = str(secret)
    window.cfg.pdf_folders = [str(secret), str(pdf.parent)]
    try:
        raise OSError(13, "アクセスが拒否されました", str(secret / "準備書面.pdf"))
    except OSError as e:
        window.errors.record(e, "保存")
    text = window.diagnostic_text()
    assert app.VERSION_LABEL in text and "PermissionError" in text and "処理：保存" in text
    assert "構文ファイルの保存場所：変えた場所・設定あり（フォルダがある）" in text
    assert "PDF を保存したフォルダ（覚えている数）：2" in text
    assert "仮名化した語：1 語（人名 1）" in text and "保存：まだ" in text
    assert f"エディター：{len(PSEUDO)} 字" in text
    for word in ("甲野", "乙山", "〔人名", "〔法人", "訴状", "準備書面", "認否", "アクセスが拒否", str(tmp_path), "AppData"):
        assert word not in text, word
    shown = []
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: shown.append(a[1]))
    window.on_copy_diagnostics()
    assert window.clipboard_get() == text
    assert shown and "診断情報をコピーしました" in shown[0]
    window.clipboard_clear()


def test_errors_are_recorded(window, tmp_path, monkeypatch):
    """開けなかったファイル・画面の処理の予期しない誤りを、型と場所だけで覚える。"""
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: None)
    window.open_path(tmp_path / "甲野太郎" / "ない.txt")
    last = window.errors.records[-1]
    assert last["stage"] == "開く" and last["type"] == "FileNotFoundError"
    assert "甲野" not in json.dumps(window.errors.records, ensure_ascii=False)
    monkeypatch.setattr("sys.stderr", open(tmp_path / "stderr.txt", "w", encoding="utf-8"))   # Tk の既定の出力
    try:
        raise KeyError("甲野太郎")
    except KeyError as e:
        window.report_callback_exception(type(e), e, e.__traceback__)
    assert window.errors.records[-1]["stage"] == "画面の処理" and window.errors.records[-1]["type"] == "KeyError"
    assert "甲野" not in window.diagnostic_text()


# ----------------------------------------------------------------------
# ナビゲーション（見出しの一覧。2026-11-24 班長指示。navigation.py・outline.py）
# ----------------------------------------------------------------------

# 行：1 表題、3 当事者、6 原告、9 被告、12 請求、15 以上
NAV_TEXT = (":=: 準備書面\n\n## 当事者\n本文１\n\n### 原告\n原告の本文\n\n### 被告\n被告の本文\n\n## 請求\n本文２\n\n"
            "--: 以上\n")


def _show_navigation(window, show):
    window.nav_var.set(show)
    window.on_toggle_navigation()
    window.update()


@pytest.fixture
def nav_window(window):
    """ナビゲーションを出した画面（終わったら隠す。ほかの試験に残さない）。"""
    window.deiconify()
    window.geometry("1500x800")
    window._load_text(NAV_TEXT)
    window.update()
    _show_navigation(window, True)
    yield window
    _show_navigation(window, False)
    window.withdraw()


def _nav_labels(window, parent=""):
    tree = window.nav_tree
    return [(tree.item(i, "text"), _nav_labels(window, i)) for i in tree.get_children(parent)]


def _nav_image(window, item):
    image = window.nav_tree.item(item, "image")
    if isinstance(image, (list, tuple)):
        return str(image[0]) if image else ""
    return str(image or "")


def _nav_click(window, item, release=True):
    x, y, _, h = window.nav_tree.bbox(item)
    window.nav_tree.event_generate("<ButtonPress-1>", x=x + 40, y=y + h // 2)
    if release:
        window.nav_tree.event_generate("<ButtonRelease-1>", x=x + 40, y=y + h // 2)
    window.update()


def test_navigation_toggle_and_tree(window):
    """リボンの「表示」の［ナビゲーション］にチェックを入れたときだけ、一番左に見出しの一覧を出す（エディターの幅は
    変えない）。見出しはレベルに合わせて木の形に並べ、組んだときと同じ番号を付ける。出すかどうかは設定に覚える。"""
    window.deiconify()
    window.geometry("1500x800")
    window._load_text(NAV_TEXT)
    window.update()
    assert not window.nav_shown() and window.nav_check.master is _group(window, "表示").body
    # 左の列に上から［AI 連携］［プレビュー］［ナビゲーション］、右の列に［蛍光ペン］（2026-11-24 班長指示）
    marker = next(b for b in _all_buttons(window) if str(b.cget("text")) == "蛍光ペン")
    place = lambda w: (int(w.grid_info()["column"]), int(w.grid_info()["row"]))
    assert [place(c) for c in (window.ai_check, window.preview_check, window.nav_check)] == [(0, 0), (0, 1), (0, 2)]
    assert place(marker) == (1, 0)
    editor = window._work_pane.winfo_width()
    _show_navigation(window, True)
    try:
        assert [str(p) for p in window.panes.panes()] == [str(window._nav_pane), str(window._preview_pane),
                                                          str(window._work_pane)]
        assert abs(window._work_pane.winfo_width() - editor) <= 2
        assert window.cfg.nav_visible and config.load().nav_visible
        assert _nav_labels(window) == [("１　当事者", [("(1) 原告", []), ("(2) 被告", [])]), ("２　請求", [])]
        assert window.nav_tree.winfo_rooty() == window.canvas.winfo_rooty()        # 一覧とプレビューの上端をそろえる
        scroll = [c for c in _widgets(window._nav_pane, tk.ttk.Scrollbar) if str(c.cget("orient")) == "vertical"]
        assert scroll and str(window.nav_tree.cget("yscrollcommand"))
        # 見出しを書き足すと、一覧も変わる。見出しがなければ、その旨を出す
        window.text.insert("3.0", "## 前置き\n")
        window.refresh()
        assert [label for label, _ in _nav_labels(window)] == ["１　前置き", "２　当事者", "３　請求"]
        assert not window._nav_empty.winfo_ismapped()
        window._load_text("本文だけ")
        window.update()
        assert _nav_labels(window) == [] and window._nav_empty.winfo_ismapped()
        # 起動し直したときも、覚えた幅で出す
        assert "ナビゲーション はい" in window.diagnostic_text()
    finally:
        _show_navigation(window, False)
    assert not window.nav_shown() and not config.load().nav_visible
    assert abs(window._work_pane.winfo_width() - editor) <= 2
    window.withdraw()


def _show_preview(window, show):
    window.preview_var.set(show)
    window.on_toggle_preview()
    window.update()


def test_web_document_buttons_and_navigation(window):
    """文書の種類を「ウェブ文書」にしても、記号のボタン・キーは、ビジネス文書と同じに使える（2026-11-24 班長指示）。
    行番号・番号1字は付けない。表題（:=:）は H1 の見た目で組むが、見出しではないので、ナビゲーションには載らない。"""
    from va_document.doctypes import DOC_TYPES, WEB
    window._load_text(":=: 記事の題\n本文")
    window.doc_type_box.set(DOC_TYPES[WEB].label)
    window.on_settings_changed()
    try:
        assert window.session.doc_type.web
        buttons = [b for b in _all_buttons(window.ribbon)]
        assert buttons and all(str(b.cget("state")) == "normal" for b in buttons)
        assert str(window.line_numbers_check.cget("state")) == "disabled"
        assert str(window.one_width_check.cget("state")) == "disabled"
        window.text.mark_set("insert", "2.0")
        window.on_align(RIGHT_MARK)                           # Ctrl+R の右揃え
        assert window.raw_text() == ":=: 記事の題\n--: 本文"
        window.refresh()
        from va_document import outline
        heads = outline.headings(window.raw_text().split("\n"), window.session.doc_type)
        assert heads == []
    finally:
        window.doc_type_box.set(DOC_TYPES["Saiban"].label)
        window.on_settings_changed()


def test_ai_area_toggle(window, monkeypatch):
    """リボンの「表示」の［AI 連携］のチェックを外すと、「仮名化する語」の一覧・「AI 連携」の組・右クリックの
    ［選択範囲を仮名化…］を隠す（2026-11-24 班長決定）。仮名化する語がある文書では、自動で出し、チェックを外せない。
    自動で出したのはその文書の間だけで、新しい文書になったら、利用者が選んでいた形に戻す（設定は書き換えない）。"""
    window.deiconify()
    window.update()
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: False)   # 閉じるときは保存しない
    menu_labels = lambda: [window.editor_menu.entrycget(i, "label") for i in range(window.editor_menu.index("end") + 1)
                           if window.editor_menu.type(i) == "command"]
    # 仮名化する語のある文書（試験の初めの文書）は、出したまま外せない
    assert window.ai_shown() and window.ai_var.get() and str(window.ai_check.cget("state")) == "disabled"
    try:
        assert window.on_close_document()
        assert window.ai_shown() and str(window.ai_check.cget("state")) == "normal"   # 既定は出す
        window.ai_var.set(False)
        window.on_toggle_ai()
        window.update()
        assert not window.ai_shown() and not window._ai_box.winfo_ismapped()
        assert not window._dictionary_frame.winfo_ismapped() and "選択範囲を仮名化…" not in menu_labels()
        assert not window.cfg.ai_visible and not config.load().ai_visible
        assert window.ribbon._min_height == max(g.winfo_reqheight() for g in window.ribbon.groups)
        assert "AI 連携 いいえ" in window.diagnostic_text()
        # 仮名化する語ができる（そういう文書を開く）と、自動で出し、外せなくする。設定は書き換えない
        window._load_text("乙山花子の主張。")
        window.session.dictionary.register("乙山花子", "人名")
        window._refresh_dictionary()
        window.update()
        assert window.ai_shown() and window._ai_box.winfo_ismapped() and window._dictionary_frame.winfo_ismapped()
        assert window.ai_var.get() and str(window.ai_check.cget("state")) == "disabled"
        assert "選択範囲を仮名化…" in menu_labels() and not window.cfg.ai_visible
        # 一覧の位置は、エディターの下（状態の欄の上）のまま
        assert window._dictionary_frame.winfo_y() > window._editor_frame.winfo_y()
        assert window.status.winfo_y() > window._dictionary_frame.winfo_y()
        # 語をすべて解除すると外せるが、その文書の間は出したまま
        window._unregister(next(iter(window.session.dictionary.entries)))
        assert window.ai_shown() and str(window.ai_check.cget("state")) == "normal"
        # 新しい文書になったら、選んでいた形（隠す）に戻る
        assert window.on_close_document()
        window.update()
        assert not window.ai_shown() and not window.ai_var.get()
    finally:
        window.ai_var.set(True)
        window.on_toggle_ai()
        window.withdraw()
    assert window.ai_shown() and window.cfg.ai_visible


def test_preview_toggle(window, tmp_path, monkeypatch):
    """リボンの「表示」の［プレビュー］にチェックを入れたときだけ、プレビューを出す（2026-11-24 班長指示）。隠すと、
    エディターがその分広がり、出すと、覚えた幅で戻る（ナビゲーションの幅は変えない）。隠している間も、組み直し・保存・
    印刷は働く（ページを画像にするのは、出したときだけ）。3つの欄が入りきる幅で試す（入りきらなければ、エディターの最小の
    幅を守って、プレビューを狭める）。"""
    window.deiconify()
    window.geometry("1700x800")
    window._load_text(NAV_TEXT)
    window.update()
    sash = int(window.panes.cget("sashwidth"))
    assert window.preview_shown() and window.preview_var.get()
    editor, preview = window._work_pane.winfo_width(), window._pane_widths()["preview"]
    laid = []
    monkeypatch.setattr(window, "_layout_pages", lambda keep=True: laid.append(keep))
    _show_preview(window, False)
    try:
        assert [str(p) for p in window.panes.panes()] == [str(window._work_pane)]
        assert abs(window._work_pane.winfo_width() - (editor + preview + sash)) <= 2
        assert not window.cfg.preview_visible and not config.load().preview_visible
        assert abs(window.cfg.preview_width - preview) <= 2
        # 隠している間も組み直す（ページを画像にはしない）。保存と印刷もできる
        window.text.insert("end", "追記。\n")
        window.refresh()
        assert not laid and window.session.layout_map is not None
        window.session.pdf_path = tmp_path / "準備書面.pdf"
        assert window.on_save() and window.session.pdf_path.exists()
        printed = []
        monkeypatch.setattr(file_ops.printing, "available", lambda: True)
        monkeypatch.setattr(file_ops, "PrintDialog", lambda *a, **k: printed.append(a[1]) or type("D", (), {"result": None})())
        window.event_generate("<Control-Key-p>")
        window.update()
        window.on_print()
        assert printed and printed[-1][:4] == b"%PDF"
        assert "プレビュー いいえ" in window.diagnostic_text()
        # プレビューを隠したまま、ナビゲーションを出す・隠す（エディターの幅で加減する）
        _show_navigation(window, True)
        assert [str(p) for p in window.panes.panes()] == [str(window._nav_pane), str(window._work_pane)]
        nav = window._pane_widths()["nav"]
        # プレビューを出すと、覚えた幅で、ナビゲーションの右に戻る（ナビゲーションの幅は変えない）。ページも並べ直す
        _show_preview(window, True)
        assert [str(p) for p in window.panes.panes()] == [str(window._nav_pane), str(window._preview_pane),
                                                          str(window._work_pane)]
        widths = window._pane_widths()
        assert abs(widths["nav"] - nav) <= 2 and abs(widths["preview"] - preview) <= 2
        assert laid and window.cfg.preview_visible
        _show_navigation(window, False)
        assert [str(p) for p in window.panes.panes()] == [str(window._preview_pane), str(window._work_pane)]
    finally:
        _show_navigation(window, False)
        _show_preview(window, True)
        window.withdraw()


def test_navigation_follows_cursor_and_click_moves_cursor(nav_window):
    """エディターでカーソルを動かすと、カーソルのある見出しを選ぶ（行の地が薄い灰色になる。畳んだ見出しの中なら、畳んだ見出し）。
    ▼ は付けない（2026-11-24 班長指示）。見出しをクリックすると、エディターのカーソルをその見出しへ動かす。"""
    w, tree = nav_window, nav_window.nav_tree
    w.text.mark_set("insert", "7.2")                    # 原告の本文
    w._show_current_line()
    assert w._nav_current == "h1" and tree.selection() == ("h1",)
    assert all(not _nav_image(w, i) for i in w._nav_items())          # ▼ などの画像は付けない
    # カーソルのある見出しの地は、エディターの現在行と同じ薄い灰色。仮名リストの選んだ行も同じ（2026-11-27 班長指示）
    style = tk.ttk.Style(w)
    for t in (tree, w.tree):
        assert style.lookup(str(t.cget("style")), "background", ["selected"]) == theme.CURRENT_LINE_BG
    # 仮名リストの題と列の見出し（同日 班長指示。それまでは「仮名化する語」「記号」）
    assert [w.tree.heading(c, "text") for c in ("token", "word", "kind")] == ["仮名", "元の語", "種別"]
    # 見出し行は、地の色を付けず（白）、下に細い線を1本引く（選んだ行の灰色と見分ける。同日 班長指示）
    assert style.layout("Nav.Treeview.Heading")[0][0] == theme.HEADING_ELEMENT
    image = theme._heading_images[w.tk]
    # 画像は見出しより大きくする（1画素の画像だと敷き詰めて描くのに時間がかかり、行を選ぶたびに 0.5 秒ほど待たされた。
    # 同日 班長指摘）
    assert (image.width(), image.height()) == theme.HEADING_TILE
    assert image.width() >= w.tree.winfo_width() // 2 and image.height() >= 2 * w.tree.bbox(w.tree.get_children()[0])[3]
    assert "#%02x%02x%02x" % tuple(image.get(0, 0)) == theme.FIELD_BG
    assert "#%02x%02x%02x" % tuple(image.get(0, image.height() - 1)) == theme.BORDER
    labels = [str(c.cget("text")) for c in w.tree.master.master.winfo_children()[0].winfo_children()
              if isinstance(c, tk.ttk.Label)]
    assert labels[0] == "仮名リスト"
    for index in ("1.0", "15.0"):                       # 最初の見出しの前・「以上」は、どの見出しにも属さない
        w.text.mark_set("insert", index)
        w._show_current_line()
        assert w._nav_current is None and not tree.selection()
    tree.item("h0", open=False)
    w.text.mark_set("insert", "10.0")                   # 被告の本文（畳んだ「当事者」の中）
    w._update_nav_current(force=True)
    assert w._nav_current == "h0"
    tree.item("h0", open=True)
    _nav_click(w, "h3")
    assert w.text.index("insert") == "12.0" and w._nav_current == "h3"
    # 選んでいる見出しをもう一度クリックしても、見出しの行へ動かす
    w.text.mark_set("insert", "13.1")
    _nav_click(w, "h3")
    assert w.text.index("insert") == "12.0"
    assert w.raw_text() == NAV_TEXT                     # クリックでは文章を変えない


def test_navigation_expand_and_collapse_all(nav_window):
    """題の右の［展開］［折りたたむ］（2026-11-24 班長指示。名前は［展開］［折りたたむ］だけ。同日 班長指示）。一覧の見た目だけを変え、
    文章は変えない。畳んだ見出しの中のカーソルは、外側の見出しを選ぶ。欄は、題の行が入りきる幅より狭くならない。"""
    w, tree = nav_window, nav_window.nav_tree
    assert [str(c.cget("text")) for c in w._nav_head.winfo_children()[1:]] == ["展開", "折りたたむ"]
    assert all(b.cget("image") for b in (w.nav_expand_button, w.nav_collapse_button))         # アイコン付き
    assert w._nav_pane.winfo_width() >= sum(c.winfo_reqwidth() for c in w._nav_head.winfo_children())
    w.text.mark_set("insert", "7.2")                    # 原告の本文
    w._show_current_line()

    def states():
        return str(w.nav_expand_button.cget("state")), str(w.nav_collapse_button.cget("state"))
    # 押しても何も変わらないボタンは、押せない（灰色。2026-11-24 班長指摘）
    assert states() == ("disabled", "normal")                   # すべて開いている
    w.nav_collapse_button.invoke()
    assert not tree.item("h0", "open") and tree.selection() == ("h0",) and w.raw_text() == NAV_TEXT
    assert states() == ("normal", "disabled")                   # すべて畳んでいる
    w.nav_expand_button.invoke()
    assert tree.item("h0", "open") and tree.selection() == ("h1",)
    assert states() == ("disabled", "normal")
    # 見出しの左の三角で1つだけ畳んだ・開いたときも合わせる
    tree.item("h0", open=False)
    tree.event_generate("<<TreeviewClose>>")
    w.update()
    assert states() == ("normal", "disabled")
    tree.item("h0", open=True)
    tree.event_generate("<<TreeviewOpen>>")
    w.update()
    assert states() == ("disabled", "normal")
    # 下のレベルの見出しがなければ、押せない
    w._load_text("## 一\n## 二")
    w.update()
    assert str(w.nav_expand_button.cget("state")) == "disabled" == str(w.nav_collapse_button.cget("state"))


def test_navigation_drag_and_drop_moves_section(nav_window):
    """見出しをドラッグ アンド ドロップすると、属する見出し・本文と一緒に動く（「以上」は動かない）。Ctrl+Z 1回で戻る。"""
    w, tree = nav_window, nav_window.nav_tree
    _, top, _, _ = tree.bbox("h0")
    _nav_click(w, "h3", release=False)
    x = tree.bbox("h3")[0] + 40
    tree.event_generate("<B1-Motion>", x=x, y=top + 2)
    w.update()
    assert w._nav_drop_line.winfo_ismapped()
    tree.event_generate("<ButtonRelease-1>", x=x, y=top + 2)
    w.update()
    assert w.raw_text() == (":=: 準備書面\n\n## 請求\n本文２\n\n## 当事者\n本文１\n\n### 原告\n原告の本文\n\n"
                            "### 被告\n被告の本文\n\n--: 以上\n")
    assert w.text.index("insert") == "3.0" and [label for label, _ in _nav_labels(w)] == ["１　請求", "２　当事者"]
    assert not w._nav_drop_line.winfo_ismapped() and w.title().startswith("＊")
    w.nav_tree.event_generate("<<Undo>>")
    assert w.raw_text() == NAV_TEXT
    # 自分の範囲の中（自分の子の前）には置けない
    w.update()
    assert w._nav_drop_target(0, tree.bbox("h1")[1] + 2) is None
    # 一覧の下の空いた所に放すと、最後の見出しの後（「以上」の前）へ
    target, _ = w._nav_drop_target(1, tree.winfo_height() - 5)
    assert target == 14


def test_navigation_insert_and_select(nav_window):
    """右クリックのメニューの［前に見出しを挿入］［後に見出しを挿入］［小見出しを挿入］［見出しと本文を選択］（2026-11-24
    班長決定）。挿入は、字のない見出しを入れてエディターのカーソルをそこに置き（続けて打てる）、Ctrl+Z 1回で戻る。"""
    w, tree = nav_window, nav_window.nav_tree
    labels = [w.nav_menu.entrycget(i, "label") for i in range(w.nav_menu.index("end") + 1) if w.nav_menu.type(i) == "command"]
    assert labels == ["レベルを上げる", "レベルを下げる", "前に見出しを挿入", "後に見出しを挿入", "小見出しを挿入",
                      "見出しと本文を選択", "削除"]
    _nav_click(w, "h3")                                  # 請求
    w.nav_menu.invoke("前に見出しを挿入")
    lines = w.raw_text().split("\n")
    assert lines[11:14] == ["## ", "", "## 請求"] and w.text.index("insert") == "12.3"
    assert w.focus_get() is w.text
    w.text.insert("insert", "前置き")                       # 続けて打てる
    w.refresh()
    assert [label for label, _ in _nav_labels(w)] == ["１　当事者", "２　前置き", "３　請求"]
    w.text.edit_undo()                                   # 打った字を戻す
    w.nav_tree.event_generate("<<Undo>>")                # 挿入を Ctrl+Z 1回で戻す
    assert w.raw_text() == NAV_TEXT
    _nav_click(w, "h0")                                  # 当事者：小見出しは、最後の小見出しの後
    w.nav_menu.invoke("小見出しを挿入")
    lines = w.raw_text().split("\n")
    assert lines[9:13] == ["被告の本文", "", "### ", ""] and w.text.index("insert") == "12.4"
    w.nav_tree.event_generate("<<Undo>>")
    _nav_click(w, "h0")
    w.nav_menu.invoke("後に見出しを挿入")                    # 範囲の後（「請求」の前）
    assert w.raw_text().split("\n")[11:14] == ["## ", "", "## 請求"]
    w.nav_tree.event_generate("<<Undo>>")
    assert w.raw_text() == NAV_TEXT
    # 見出しと本文を選ぶ（属する見出し・本文。後ろの空行は含めない）
    _nav_click(w, "h0")
    w.nav_menu.invoke("見出しと本文を選択")
    assert w.text.get("sel.first", "sel.last") == "\n".join(NAV_TEXT.split("\n")[2:10])
    assert w.focus_get() is w.text and w.raw_text() == NAV_TEXT
    w.text.tag_remove("sel", "1.0", "end")


def test_navigation_keys_and_menu(nav_window, monkeypatch):
    """右クリックのメニュー（レベルを上げる・下げる・削除）と、Alt+Shift+←→・Alt+Shift+↑↓・Delete。どれも属する
    見出し・本文に及び、Ctrl+Z 1回で戻る。"""
    w, tree = nav_window, nav_window.nav_tree
    w.nav_tree.focus_force()
    w.update()
    if w.focus_get() is not tree:
        pytest.skip("一覧がキーボードの焦点を得られなかった（ほかの画面を操作中など）")
    _nav_click(w, "h0")
    tree.event_generate("<Alt-Shift-Right>")             # レベルを下げる（属する見出しも）
    lines = w.raw_text().split("\n")
    assert (lines[2], lines[5], lines[8], lines[11]) == ("### 当事者", "#### 原告", "#### 被告", "## 請求")
    assert w.focus_get() is tree and tree.selection() == ("h0",)
    tree.event_generate("<Alt-Shift-Left>")
    assert w.raw_text() == NAV_TEXT
    tree.event_generate("<Alt-Shift-Left>")              # # より上にはしない（見出しが本文に変わらない）
    tree.event_generate("<Alt-Shift-Left>")
    assert w.raw_text().split("\n")[2] == "# 当事者" and "できません" in str(w.status.cget("text"))
    tree.event_generate("<<Undo>>")
    assert w.raw_text() == NAV_TEXT
    # Alt+Shift+↓：同じ親の次の見出しと入れ替える
    _nav_click(w, "h1")
    tree.event_generate("<Alt-Shift-Down>")
    lines = w.raw_text().split("\n")
    assert lines.index("### 被告") < lines.index("### 原告") < lines.index("## 請求")
    assert tree.item(tree.selection()[0], "text") == "(2) 原告"
    tree.event_generate("<Alt-Shift-Up>")
    assert w.raw_text() == NAV_TEXT
    # Delete：属する見出し・本文ごと消す
    _nav_click(w, "h0")
    tree.event_generate("<Delete>")
    assert w.raw_text() == ":=: 準備書面\n\n## 請求\n本文２\n\n--: 以上\n"
    assert "Ctrl+Z" in str(w.status.cget("text"))
    tree.event_generate("<<Undo>>")
    assert w.raw_text() == NAV_TEXT
    # 右クリックのメニュー：上げられない見出しでは［レベルを上げる］を押せない
    shown = []
    monkeypatch.setattr(w.nav_menu, "tk_popup", lambda x, y: shown.append(
        {label: str(w.nav_menu.entrycget(label, "state")) for label in ("レベルを上げる", "レベルを下げる", "削除")}))
    w._load_text("# 一\n## 二\n本文")
    w.update()
    x, y, _, h = tree.bbox("h0")
    tree.event_generate("<Button-3>", x=x + 40, y=y + h // 2)
    assert shown[-1] == {"レベルを上げる": "disabled", "レベルを下げる": "normal", "削除": "normal"}
    assert w.text.index("insert") == "1.0"
    w.nav_menu.invoke("レベルを下げる")
    assert w.raw_text() == "## 一\n### 二\n本文"


def test_open_docx(window, monkeypatch, tmp_path):
    """Word の文書（.docx）を開くと、見出し・配置・画像を戻したマークダウンがエディターに入り、画像はプレビューに出て、
    取り込まなかったものを知らせる（Ver420。2026-11-24 班長指示）。古い形式の .doc は開かずに知らせる。"""
    from docxbuild import docx, p, pic, png, sect, t
    shown = []
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: shown.append(a[1]))
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: False)
    src = tmp_path / "書面.docx"
    src.write_bytes(docx(p(t("準備書面"), '<w:jc w:val="center"/>') + p(t("当事者"), '<w:pStyle w:val="1"/>')
                         + p(pic(5)) + sect(), comments=["メモ"], images={"rIdImg": ("image1.png", png())}))
    window.open_path(src)
    assert window.raw_text().rstrip("\n").splitlines() == [":=: 準備書面", "# 当事者", "[IMAGE 1]{12}"]
    # 見出しのレベルがあり、用紙が VA Document の種類に合わない文書は、今の設定の文書の種類（この試験の設定は裁判所提出書類）
    assert window.session.images[1].size == (200, 100) and window.doc_type_box.get() == "裁判所提出書類"
    assert len(shown) == 1 and "Word の文書から" in shown[0] and "コメント 1 個" in shown[0] and "画像 1 個" in shown[0]
    old = tmp_path / "古い.doc"
    old.write_bytes(b"\xd0\xcf\x11\xe0")
    window.open_path(old)
    assert "古い形式" in shown[-1] and window.raw_text().startswith(":=: 準備書面")
    assert ("Word の文書", "*.docx") in file_ops.OPEN_FILETYPES and ".docx" in file_ops.DROP_SUFFIXES


def test_open_pdf_without_vamd_makes_markdown(window, monkeypatch):
    """構文ファイルのない PDF（VA公用文〔Word〕で作ったもの）を開くと、見出し・配置を戻したマークダウンがエディターに入り、
    文書の種類・ページ番号の欄も PDF に合わせる（2026-11-24 班長指示「VA疑似アウトラインの機能を取り込む」）。"""
    shown = []
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: shown.append(a[1]))
    window.session = app.Session(config.AppConfig(vamd_folder=window.cfg.vamd_folder, doc_type="Business"))
    window.open_path(Path(__file__).parent / "data" / "裁判所" / "VA公用文.pdf")
    lines = window.raw_text().splitlines()
    assert lines[3] == ":=: 準備書面（１）" and "# 請求原因に対する認否" in lines
    assert window.doc_type_box.get() == "裁判所提出書類" and window.page_number_box.get() == "中下"
    assert len(shown) == 1 and "裁判所提出書類" in shown[0]
