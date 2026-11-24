"""1つの文書の作業（組む・保存・開く・構文ファイル・AI の回答の取り込み）。画面からは独立させる。

・エディターは記号で表示し、実名の文章（記号を元の語に戻したもの）は、画面から受け取って組むだけで、ファイルには
  しない（仕様.md の9.1）。
  手元に残すのは、PDF（実名）と構文ファイル（記号）の2つで、いつも同じ版で保存する。
・辞書・対応表はメモリの中だけに持つ（Dictionary）。開き直したときは、構文ファイルと PDF を突き合わせて作り直す。
・構文ファイルは、AI に渡す前も後も、テキストエディターや画面で自由に直してよい（2026-10-23 班長指示）。
  直した構文ファイルを開くと、変わっていない部分から対応表を作り直し、求まらない記号は利用者に尋ねる。
  指示の部分を書き換えていれば、保存するときもその指示を残す。
"""
import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import vamd
from .cleanup import clean_lines
from .doctypes import doc_type_for
from .document import IMAGE_MAX, image_numbers, parse
from .layout import Typesetter
from .docxmarkdown import DocxError
from .docxmarkdown import convert as docx_to_markdown
from .docxmarkdown import notices as docx_notices
from .pdfmarkdown import convert as pdf_to_markdown
from .pdftext import plain_text as pdf_plain_text
from .pdfwriter import pdf_bytes, read_id, read_images, write_pdf
from .pseudonym import Dictionary, NotRegistrable, tokens_in, trim_selection
from .recover import Recovery, rebuild_dictionary
from .textmap import LayoutMap


@dataclass
class OpenResult:
    text: str                                   # 入力欄に入れる文章（求まらない記号は記号のまま）
    recovery: Recovery = None                   # 構文ファイルから開いたときの突き合わせの結果
    messages: list = field(default_factory=list)  # 利用者に知らせること
    error: Exception = None                     # PDF の見出し・配置を読み取れなかったときの誤り（誤りの記録に残す）

    @property
    def unresolved(self):
        """利用者に元の語を尋ねる記号（求まらない記号と、違う語が対応した記号）。"""
        if self.recovery is None:
            return []
        return list(self.recovery.missing) + [t for t in self.recovery.conflicts if t not in self.recovery.missing]


@dataclass
class LoadedEntries:
    """ほかの文書から作り直した仮名化した語（［ファイルから読み込む］。2026-10-29 班長決定）。"""
    pdf_path: Path              # 突き合わせた書式付きファイル（確認の画面に名前を出す。案件を見分ける手がかり）
    plan: object                # pseudonym.MergePlan
    occurrences: int = 0        # 今の文章で、足す語が記号に置き換わる所の数
    unrecovered: int = 0        # 作り直せなかった記号の数（構文ファイルを PDF の後に直していた、など。読み込まない）


class OtherFileMissing(FileNotFoundError):
    """読み込む文書の相手のファイル（PDF なら構文ファイル、構文ファイルなら PDF）が見つからない。kind は見つからない
    ほう（"vamd"・"pdf"）、found はもう一方のパス。"""

    def __init__(self, kind, found):
        super().__init__(kind)
        self.kind, self.found = kind, found


class Session:
    def __init__(self, cfg):
        self.cfg = cfg
        self.new()

    def _default_settings(self):
        """新しい文書の設定（この PC の設定の、文書の種類・ページ番号・行番号・番号1字）。"""
        return vamd.Settings(self.cfg.doc_type, self.cfg.page_number, self.cfg.line_numbers,
                             self.cfg.one_width).normalized()

    def new(self):
        self.doc_id = vamd.new_doc_id()
        self.version = 0
        self.settings = self._default_settings()
        self.dictionary = Dictionary()
        # AI への指示：すべての文書に共通（ユーザーによってオプションで書き換えられた指示。None なら既定の指示。
        # 2026-10-28 班長決定。開いた構文ファイルの指示は使わない）
        prompt = self.cfg.ai_prompt
        self.prompt = None if not prompt or vamd.is_default_prompt(prompt) else prompt
        self.pdf_path = None
        self.vamd_file = None          # 開いた構文ファイル（None なら決まったフォルダの <文書ID>.vamd）
        self.saved_text = None
        self.saved_body = None          # 保存した構文ファイルの文書（記号入り）
        self.saved_settings = None
        self._opened_body = None
        self.layout_map = None          # 最後に組んだ結果とエディターの位置の対応
        self._vamd_stamp = None        # 最後に書いた・読んだ構文ファイルの中身の指紋（外での書き換えを見分ける）
        # 仮名化を解除した語・変える前の元の語（メモリの中だけ）。保存するとき、構文ファイルに実名のまま残って
        # いれば知らせる（2026-10-25 班長指示）
        self.released = {}
        # 画像（[IMAGE 1]{30}。番号 → 付加情報を除いた画像。メモリの中だけ。保存すると PDF に入る。2026-10-29 班長決定）。
        # 行を消しても、Ctrl+Z で戻せるように、閉じるまで残す（PDF に入れるのは、文章にある番号だけ）
        self.images = {}
        self._last_image = 0            # 振ったことのある画像の番号の最大（消した画像の番号を使い回さない）

    # ---------- 状態 ----------

    @property
    def vamd_path(self):
        if self.vamd_file is not None:
            return self.vamd_file
        return Path(self.cfg.vamd_folder) / vamd.file_name(self.doc_id)

    @property
    def doc_type(self):
        return doc_type_for(self.settings.doc_type, self.settings.one_width)

    def is_modified(self, text):
        """保存した後に、文章・設定・構文ファイルの中身を変えたか（文末の改行・行末の空白の違いは、
        変えたことにしない。構文ファイル〔記号〕の表示から戻すと、文末の改行がなくなるため）。

        語を仮名化・解除すると、文章が同じでも構文ファイルの中身（記号）が変わるので、変えたことにする
        （保存し直さないまま［コピー］で前の構文ファイルを写し、仮名化する前の実名を AI に渡さないように）。
        """
        if self.saved_text is None:
            return bool(text.strip())
        return (_normalized(text) != _normalized(self.saved_text) or self.settings != self.saved_settings
                or (self.saved_body is not None and _normalized(self.body(text)) != _normalized(self.saved_body)))

    # ---------- 組む ----------

    def typeset(self, text):
        """組む。組んだ結果とエディターの位置の対応（確認表示との連動に使う）を self.layout_map に残す。"""
        cleaned, origins, _ = clean_lines(text)
        ts = Typesetter(self.doc_type, self.settings.page_number)
        ts.image_sizes = {n: p.size for n, p in self.images.items()}
        paras = parse(cleaned, self.doc_type)
        lines = ts.layout(paras)
        self.layout_map = LayoutMap(ts, lines, paras, cleaned, origins)
        return ts, lines

    def preview_pdf(self, text, highlight=False):
        """確認表示・印刷の PDF（メモリの中だけ。識別子は入れない）。highlight が真なら、確認表示だけの色を付ける
        （蛍光ペンの黄と、仮名化した語の地の色。2026-10-24 班長指示）。"""
        ts, lines = self.typeset(text)
        if highlight and self.dictionary.entries:
            self._mark_pseudonyms(ts, lines, text)
        return pdf_bytes(ts, lines, page_number=self.settings.page_number, highlight=highlight,
                         line_numbers=self.settings.line_numbers, images=self.images)

    def _mark_pseudonyms(self, ts, lines, text):
        """組んだ字のうち、仮名化した語の字に印を付ける（確認表示で、どこが仮名化されているかを示すため）。"""
        marked = set()
        for n, line in enumerate(text.split("\n")):
            for a, b, _ in self.dictionary.spans(line):
                marked.update((n, c) for c in range(a, b))
        if not marked:
            return
        m = self.layout_map
        for ln in lines:
            for g in ln.glyphs:
                if m.glyph_source(ln, g) in marked:
                    g.pseudonym = True
        for piece in ts.tables:
            for g in piece.glyphs:
                if m.cell_glyph_source(piece, g) in marked:
                    g.pseudonym = True

    # ---------- 構文ファイル ----------

    def body(self, text):
        """記号に置き換えた文書。"""
        return self.dictionary.pseudonymize(text)

    def vamd_text(self, text, version=None):
        return vamd.build(self.doc_id, self.version if version is None else version, self.settings,
                           self.body(text), self.prompt)

    def rewrite_prompt(self):
        """AI への指示を直したとき、保存してある構文ファイルの指示の部分だけを書き直す（版と文書は変えない。
        PDF と同じ版の文書のまま）。"""
        if self.version and self.saved_text is not None and self.vamd_path.exists():
            vamd.write_file(self.vamd_path, self.vamd_text(self.saved_text, self.version))
            self._vamd_stamp = _stamp(self.vamd_path)

    # ---------- 保存（仕様.md の9.1） ----------

    def save(self, text, pdf_path=None):
        """PDF と構文ファイルを、同じ文書ID・同じ（1つ上げた）版で保存する。"""
        pdf_path = Path(pdf_path or self.pdf_path)
        version = self.version + 1
        ts, lines = self.typeset(text)
        write_pdf(ts, lines, str(pdf_path), self.doc_id, version, self.settings.page_number,
                  line_numbers=self.settings.line_numbers, images=self.images)
        vamd.write_file(self.vamd_path, self.vamd_text(text, version))
        self._vamd_stamp = _stamp(self.vamd_path)
        self.version = version
        self.pdf_path = pdf_path
        self.saved_text = text
        self.saved_body = self.body(text)
        self.saved_settings = replace(self.settings)
        self.cfg.remember_pdf_folder(pdf_path.parent)
        self.cfg.remember_settings(self.settings)

    # ---------- 画像（[IMAGE 1]{30}。2026-10-29 班長決定） ----------

    def add_picture(self, picture, text):
        """画像を加え、振った番号を返す（その文書で使ったことのある番号の最大＋1。文章にある、データのない番号も避ける）。
        番号が IMAGE_MAX を超えるときは ValueError。"""
        n = max([self._last_image, *self.images, *image_numbers(text.split("\n"))], default=0) + 1
        if n > IMAGE_MAX:
            raise ValueError(f"画像の番号が {IMAGE_MAX} を超えるため、これ以上入れられません。")
        self.images[n] = picture
        self._last_image = n
        return n

    def missing_images(self, text):
        """文章にあって、画像のデータがない番号（PDF なしで開いた、別の文書から行を写した、など）。出てくる順。"""
        return [n for n in dict.fromkeys(image_numbers(text.split("\n"))) if n not in self.images]

    # ---------- ほかの文書からの読み込み（［ファイルから読み込む］。2026-10-29 班長決定） ----------

    def other_files(self, path):
        """読み込む文書の (構文ファイル, PDF) を返す。選んだのが PDF なら、識別子の文書ID で構文ファイルのフォルダから
        構文ファイルを、構文ファイルなら、PDF を保存したことのあるフォルダから PDF を探す（開くときと同じ find_vamd・
        find_pdf）。相手が
        見つからなければ OtherFileMissing。VA Document の PDF でなければ ValueError。今の文書そのものなら ValueError。"""
        path = Path(path)
        if path.suffix.lower() == ".pdf":
            pid = read_id(str(path))
            if pid is None:
                raise ValueError("VA Document で作った書式付きファイル（PDF）ではありません。")
            self._check_other(pid[0])
            found = self.find_vamd(pid[0])
            if found is None:
                raise OtherFileMissing("vamd", path)
            return found, path
        content = vamd.read_file(path)
        self._check_other(content.doc_id)
        pdf = self.find_pdf(content.doc_id)
        if pdf is None:
            raise OtherFileMissing("pdf", path)
        return path, pdf

    def _check_other(self, doc_id):
        if doc_id == self.doc_id:
            raise ValueError("選んだファイルは、今開いている文書のものです。")

    def entries_from(self, vamd_path, pdf_path, text):
        """読み込む文書の構文ファイルと PDF を突き合わせて仮名化した語を作り直し（開き直すときと同じ。対応表はメモリの
        中だけ）、今の一覧と比べた LoadedEntries を返す。text は今の文章（実名）。今の文書は変えない。
        作り直せなかった記号・違う語が対応した記号は読み込まない。PDF が別の文書のものなら PdfMismatch。"""
        content = vamd.read_file(vamd_path)
        self._check_other(content.doc_id)
        d, r = rebuild_dictionary(content, str(pdf_path))
        body = self.body(text)
        known = {e.token for e in self.dictionary.entries.values()}
        unknown = [t for t in dict.fromkeys(tokens_in(body)) if t not in known]
        plan = self.dictionary.plan_merge(list(d.entries.values()), unknown)
        added = Dictionary()
        for e in plan.add:
            added.add_known(e.word, e.token)
        return LoadedEntries(Path(pdf_path), plan, len(added.spans(body)),
                             len(set(r.missing) | set(r.conflicts)))

    def merge_entries(self, loaded):
        """LoadedEntries の足す語を、今の一覧に足す（食い違いがあれば何も足さない。呼ぶ側で確かめてから呼ぶ）。"""
        if loaded.plan.conflicts:
            raise ValueError("食い違いがあるため、読み込めません。")
        self.dictionary.merge(loaded.plan.add)
        return len(loaded.plan.add)

    # ---------- 仮名化の解除・元の語の変更 ----------

    def unregister(self, word_or_token):
        """仮名化を解除する（解除した語は、保存するときの確かめのために覚えておく）。"""
        e = self.dictionary.unregister(word_or_token)
        if e:
            self.released[e.word] = None
        return e

    def rename(self, word_or_token, new_word):
        """仮名化した語の元の語を変え、前の語を返す（前の語は、保存するときの確かめのために覚えておく）。"""
        e = self.dictionary.find(word_or_token)
        old = self.dictionary.rename(word_or_token, new_word)
        if e.word != old:
            self.released[old] = None
            self.released.pop(e.word, None)      # 前に解除した語を、改めて元の語にした
        return old

    def edit(self, token, word, kind, letters):
        """仮名化した語の元の語と記号を変え、(前の語, 前の記号) を返す（一覧の変更。2026-10-25 班長決定）。どちらかが
        変えられなければ、どちらも変えずに NotRegistrable を出す。"""
        e = self.dictionary.find(token)
        if e is None:
            raise KeyError(token)
        self.dictionary.check_token(kind, letters, keep=e)
        word = trim_selection(word)
        if word != e.word:
            if word in self.dictionary.entries:
                raise NotRegistrable(f"「{word}」は、すでに {self.dictionary.entries[word].token} として仮名化しています。")
            self.dictionary.check(word)
        old_word = self.rename(token, word)
        old_token = self.dictionary.change_token(word, kind, letters)
        return old_word, old_token

    def released_in(self, text):
        """仮名化を解除した語・変える前の元の語のうち、構文ファイル（記号に置き換えた文書）に実名のまま残るもの
        {語: 数}。"""
        body = self.body(text)
        return {w: body.count(w) for w in self.released if w in body}

    def accept_released(self, words):
        """利用者が残してよいと答えた語を、もう知らせない。"""
        for w in words:
            self.released.pop(w, None)

    # ---------- 外での書き換え ----------

    def vamd_changed_outside(self):
        """構文ファイルが、最後に書いた・読んだときから、VA Documentの外で書き換えられたか
        （テキストエディターで直した、AI の回答を上書き保存した、など。2026-10-23 班長了承）。"""
        path = self.vamd_path
        if not path.exists():
            return False
        return _stamp(path) != self._vamd_stamp

    def outside_vamd_text(self):
        """外で書き換えられた構文ファイルの中身。"""
        return self.vamd_path.read_bytes().decode("utf-8-sig", errors="replace")

    def outside_stamp(self):
        return _stamp(self.vamd_path) if self.vamd_path.exists() else None

    # ---------- AI の回答の取り込み（仕様.md の8.3） ----------

    def review_answer(self, answer_text, current_text):
        """AI の回答を読み、今の文章と比べる。(Content, Review) を返す（文書ID 違い・区切りの行なしは例外）。"""
        content = vamd.parse_text(answer_text)
        r = vamd.review(content, self.doc_id, self.version, self.body(current_text).splitlines(), self.dictionary,
                        self.images)
        return content, r

    def apply_answer(self, content, current_text):
        """回答を取り込んだ実名の文章を返す（取り込む前の文章には、画面のエディターの Ctrl+Z で戻る）。"""
        for tok in tokens_in(content.body_text):
            self.dictionary.note_used(tok)
        return self.dictionary.restore(content.body_text)[0]

    # ---------- 開く（仕様.md の9.2） ----------

    def find_vamd(self, doc_id):
        """構文ファイルのフォルダから、文書ID の構文ファイル（<文書ID>.vamd）を探す（なければ None）。PDF から開くとき・
        PDF から仮名化した語を読み込むときに使う（find_pdf と対）。"""
        candidate = Path(self.cfg.vamd_folder) / vamd.file_name(doc_id)
        return candidate if candidate.exists() else None

    def find_pdf(self, doc_id):
        """これまでに PDF を保存したフォルダから、文書ID の合う PDF を探す（版がいちばん新しいもの）。"""
        best = None
        for folder in self.cfg.pdf_folders:
            try:
                candidates = list(Path(folder).glob("*.pdf"))
            except OSError:
                continue
            for p in candidates:
                try:
                    pid = read_id(str(p))
                except Exception:
                    continue
                if pid and pid[0] == doc_id and (best is None or pid[1] > best[1]):
                    best = (p, pid[1])
        return best[0] if best else None

    def open_vamd(self, path, pdf_path=None):
        """構文ファイルを開く。pdf_path が None なら探し、False なら PDF なしで開く（記号は利用者に尋ねる）。

        PDF が見つからないときは FileNotFoundError を出す（画面で利用者に PDF を選んでもらう）。
        """
        content = vamd.read_file(path)
        if pdf_path is None:
            pdf_path = self.find_pdf(content.doc_id)
            if pdf_path is None:
                raise FileNotFoundError(content.doc_id)
        messages = []
        if pdf_path:
            d, r = rebuild_dictionary(content, str(pdf_path))
            pdf_version = read_id(str(pdf_path))[1]
        else:
            d, r = Dictionary(), Recovery(missing=list(dict.fromkeys(tokens_in(content.body_text))))
            for tok in r.missing:
                d.note_used(tok)
            pdf_version = 0
        if pdf_path and pdf_version != content.version:
            messages.append(f"構文ファイル（版 {content.version}）と書式付きファイル（PDF。版 {pdf_version}）の版が違います。"
                            "変わっていない部分から、記号の元の語を求めました。")
        elif pdf_path and not r.exact:
            messages.append("構文ファイルが、書式付きファイル（PDF）を保存した後に直されています。変わっていない部分から、記号の元の語を求めました。")
        self.new()
        if pdf_path:
            # 画像は、PDF の番号の目印で、構文ファイルの画像の行と結び直す（行の順が変わっていても取り違えない）
            self.images = read_images(str(pdf_path))
            self._last_image = max(self.images, default=0)
            unused = [n for n in sorted(self.images) if n not in image_numbers(content.body)]
            if unused:
                messages.append("書式付きファイル（PDF）にある画像 " + "・".join(map(str, unused)) + " が、構文ファイルに"
                                "ありません（次に保存すると、PDF から消えます。残すときは、[IMAGE 番号] の行を書き戻して"
                                "ください）。")
        self.doc_id = content.doc_id
        self.version = max(content.version, pdf_version)
        if content.settings is not None:
            self.settings = content.settings
        self.dictionary = d
        self.pdf_path = Path(pdf_path) if pdf_path else None
        self.vamd_file = Path(path)
        self._vamd_stamp = _stamp(path)
        self._opened_body = content.body_text
        text = d.restore(content.body_text)[0]
        if pdf_path and r.exact and pdf_version == content.version:
            self.saved_text = text
            self.saved_body = self.body(text)
            self.saved_settings = replace(self.settings)
        return OpenResult(text, r, messages)

    def resolve(self, answers):
        """利用者が答えた記号の元の語（{記号: 語}。空の語は記号のまま）を辞書に入れ、開いた文書の文章を返す。"""
        for tok, word in answers.items():
            word = word.strip()
            if word:
                self.dictionary.add_known(word, tok)
        return self.dictionary.restore(self._opened_body or "")[0]

    def open_pdf(self, path):
        """PDF を開く。VA Documentの PDF で構文ファイルが見つかれば、それを開く。

        構文ファイルが見つからない PDF・ほかのソフトで作った PDF は、字の位置と番号から、見出し・配置・表などを戻した
        マークダウンにする（pdfmarkdown.py。VA疑似アウトラインの機能を取り込んだもの。2026-11-24 班長指示）。文書の種類・
        ページ番号・行番号の設定も、PDF に合わせる。新しい文書として開き、保存すると PDF と構文ファイルを作る（開いた
        PDF は書き換えない）。読み取りに失敗したときは、前の版と同じく、字だけを取り出す（失敗は OpenResult.error）。
        """
        pid = read_id(str(path))
        found = self.find_vamd(pid[0]) if pid else None
        if found is not None:
            return self.open_vamd(found, path)
        error = converted = None
        try:
            converted = pdf_to_markdown(path, self._default_settings())
            text = converted.text if converted is not None else ""
        except Exception as e:      # 読み取れない形の PDF でも、字だけは取り出せるように
            error = e
            text = pdf_plain_text(path)
        if not text.strip():
            # 字の層のない PDF（OCR していないスキャンなど）は、今の文書を消さずに知らせる（2026-10-24）
            raise NoTextInPdf("この PDF には、取り出せる字がありません（スキャンした画像だけで、OCR の字が入っていません）。\n"
                              "スキャンのソフトで OCR（ScanSnap なら「検索可能な PDF にする」）をしてから、もう一度開いてください。")
        self.new()
        msg = "この PDF の構文ファイルが見つかりません。" if pid else "VA Document で作った PDF ではありません。"
        if converted is None:
            return OpenResult(text, None, [msg + "文字だけを取り出しました（見出し・配置は戻していません）。"], error)
        self.settings = converted.settings
        msg += (f"字の位置と番号から、見出し・配置・表などを戻しました（文書の種類：{self.doc_type.label}）。\n"
                "元の PDF と見比べて、確かめてください。保存すると、PDF の保存先を尋ね、PDF と構文ファイルを作ります"
                "（開いた PDF は書き換えません）。")
        if converted.images:
            msg += "\nこの PDF の画像は取り込んでいません。要る画像は、［画像］で入れてください。"
        return OpenResult(text, None, [msg])

    def open_docx(self, path):
        """Word の文書（.docx）を開く（Ver420。2026-11-24 班長指示。docxmarkdown.py）。

        PDF を開くのと同じく、新しい文書として開く（文書の使い回しの機能は作らない。2026-11-24 班長決定）。段落・見出し・
        配置・表・改ページ・画像などを戻したマークダウンにし、文書の種類・ページ番号・行番号の設定も Word の文書に合わせる。
        画像は、付加情報を除いて作り直し、メモリにだけ持つ（保存すると PDF に入る）。取り込まなかったもの（変更履歴の
        削除した字・コメント・隠し文字・脚注・テキストボックスの字など）は、知らせる。開いた docx は書き換えない。"""
        try:
            converted = docx_to_markdown(Path(path).read_bytes(), self._default_settings())
        except (DocxError, OSError):
            raise
        except Exception as e:      # 思わぬ形の文書：今の文書を消さずに知らせる（誤りの記録には型と場所を残す）
            raise DocxError("この Word の文書は、読み取れない形です。Word で開き、［名前を付けて保存］で保存し直してから、"
                            "もう一度開いてください。") from e
        if not converted.text.strip():
            raise NoTextInDocx("この Word の文書には、取り込める字がありません。")
        self.new()
        self.settings = converted.settings
        self.images = dict(converted.pictures)
        self._last_image = max(self.images, default=0)
        msg = (f"Word の文書から、見出し・配置・表などを戻しました（文書の種類：{self.doc_type.label}）。\n"
               "元の Word の文書と見比べて、確かめてください。保存すると、PDF の保存先を尋ね、PDF と構文ファイルを作ります"
               "（開いた Word の文書は書き換えません）。")
        notes = docx_notices(converted.report)
        if notes:
            msg += "\n\n" + "\n".join(notes)
        return OpenResult(converted.text, None, [msg])

    def open_text(self, path):
        """テキスト・マークダウンを開く（素材の取り込み用。新しい文書になる）。"""
        raw = Path(path).read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp932", errors="replace")
        self.new()
        return OpenResult(text.replace("\r\n", "\n"))


class NoTextInPdf(ValueError):
    """PDF に字の層がない（OCR していないスキャンなど）。"""


class NoTextInDocx(ValueError):
    """Word の文書に、取り込める字がない。"""


def _stamp(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _normalized(text):
    return "\n".join(ln.rstrip() for ln in text.strip("\n").splitlines())
