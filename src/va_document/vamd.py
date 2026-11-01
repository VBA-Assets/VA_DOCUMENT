"""構文ファイル（.vamd）の書き出し・読み込みと、AI の回答を取り込む前の確かめ（仕様.md の8）。

・中身は、AI への指示、区切りの行（文書ID・版・設定）、記号に置き換えた文書の3つ（UTF-8）。
・実名・文書の名前・フォルダのパスは書かない。ファイル名は「<文書ID>.vamd」とする。
・AI の回答は、区切りの行から下を1つのコードブロックで返させる。読み込むときは、区切りの行より上
  （AI への指示、AI の前置き）と、コードブロックの閉じの記号から下（AI の結び）を捨てる。
・AI の画面が回答に混ぜる内部の目印の行（「<?thinking_complete?>」だけの行）は、読み込むときに除く（Content.dropped）。
"""
import difflib
import hashlib
import os
import re
import secrets
import tempfile
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from .doctypes import DEFAULT_DOC_TYPE, DOC_TYPES, NAIYOU, PAGE_NUMBER_BOTTOM_CENTER, PAGE_NUMBER_LABELS, can_one_width
from .document import (BODY, JUSTIFY, cell_align_mark, image_mark, image_numbers, is_line_mark, move_wraps_after_marks,
                       parse, parse_separator, separator_widths, split_cells, split_lead_marks)
from .pseudonym import tokens_in

EXTENSION = ".vamd"
# 文書ID：8字。見間違えやすい字（0・O・1・I）は使わない
DOC_ID_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DOC_ID_LENGTH = 8
SEPARATOR_RE = re.compile(r"^\s*={2,}\s*VA\s*Document\s+文書ID\s+([0-9A-Z]+)\s+版\s+(\d+)(.*?)\s*={2,}\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
# AI の画面が回答のコードブロックに混ぜる、内部の目印の行（2026-10-25 の往復試験で claude.ai が「<?thinking_complete?>」を
# 混ぜた）。取り込むときに除き、除いたことを知らせる（2026-10-25 班長決定）
AI_MARKER_RE = re.compile(r"^\s*<\?[A-Za-z_][\w:.-]*\?>\s*$")
# マークダウンの脚注の記号（本文の [^1] と、行頭の [^1]: の両方）。VA Documentは脚注を組まず、字のまま PDF に出すので、
# AI の回答で増えたら知らせる（2026-10-30 班長決定。仕様.md の13）
FOOTNOTE_RE = re.compile(r"\[\^[^\[\]\s]+\]")


PROMPT = """このファイルは、ツール「VA Document」の構文ファイル（AI に渡すために、実名を記号に置き換えたもの）である。「==== VA Document」で始まる区切りの行より上は AI への指示、下は編集する文書である。

1　状況
区切りの行より下の文書は、ツール「VA Document」で作っている文書である。VA Documentは、このマークダウンを読み込み、見出しの番号・インデント・配置を自動で付けて、区切りの行に書いてある文書の種類（裁判所提出書類・公用文・契約書など）の書式の PDF に組む。
人や会社の実名を AI に渡さないため、人名・法人名・地名・番号などは、〔人名Ａ〕〔法人Ｘ〕〔人名ＹＴ〕〔地名１〕〔その他甲〕のような記号（〔 〕の中は、種別〔人名・法人・地名・番号・その他〕の後に、英字・数字・漢字などの字）に置き換えてある。同じ記号は、文書のどこでも同じ語を表す。記号の中の字は私が決めたもので、元の語とは関係がない。VA Documentは、あなたの回答を取り込むときに、記号を文字どおりに探して元の語に戻す。記号が少しでも変わると（括弧が［］や()に変わる、中の字が変わる、「同人」「同社」に言い換えられる）、その部分は元に戻らない。
行の先頭の「:=: 」は表題、「:-: 」は中央揃え、「--: 」は右揃え、「:-- 」は左揃えの記号（マークダウンの表の区切りの行と同じく、コロンのある側に寄せる。記号の後に半角空白を1つ置く）、「->2 」は段落の左インデントを全角2字にする記号（数字が字数。半角で書く）、「[HEADER] 」はその行をヘッダー（文書の最初のページと、セクション区切りの直後のページの上の余白。「別紙」などを書く）に、「[FOOTER] 」はフッター（各ページの下の余白）に出す記号（配置の記号と一緒に使うことがある）である。表のセルの先頭の「:-: 」「--: 」「:-- 」も、そのセルの配置の記号である。その行だけを書いた <<< は改ページ、<<<= はセクション区切り（改ページして見出しの番号を振り直す）、[TOC] は目次を組む位置の記号である（[TOC:2] のように、載せる見出しのレベルを書き添えることがある）。その行だけを書いた [IMAGE 1]{30} は、画像を置く位置の記号である（1 は画像の番号、30 は画像の幅の字数。行頭に「--: 」があれば画像を右に置き、続く段落を画像の左側に回り込ませる）。画像そのものは、あなたに渡していない（画像は記号に置き換えられないため）。段落の頭（行頭の記号の後ろでもよい）の全角空白は、段落の1行目を1字下げる字下げである。**語** は太字（ゴシック体）の記号、*語* は傍点（字の上の点）の記号、[語]{5} は語を5字の幅に均等に割り付ける記号、==語== は私が画面で付けた目印（蛍光ペン。PDF には出ない）である。空の行は、そのまま1行の空きになる。VA Documentは、この記号で表題・中央揃え・右揃え・改ページなどを決める。記号が消えると、配置が失われる。
区切りの行には、文書ID・版と、文書の種類などの設定が書いてある。VA Documentは、回答の最初の行にある区切りの行で、どの文書のどの版をもとにした回答かを確かめる。区切りの行がないと、回答を取り込めない。

2　任務
VA Documentに取り込ませるだけで、実名に戻った文書が正しい書式で出来上がるよう、記号・配置の記号・区切りの行を一字も変えずに残したまま、私の依頼に応える。

3　実行
必ず達成すること：
・記号（〔人名Ａ〕など）は、括弧と中の字を含めて一字も変えずに書く。言い換えない。新しい記号を作らない。記号の中身を推測しない。
・配置の記号（:=: :-: --: :-- ->2 など）と、ヘッダー・フッターの記号（[HEADER] [FOOTER]）、改ページの記号（<<< <<<=）、目次の記号（[TOC] [TOC:2] など）は、元の行にそのまま残す（記号の後の半角空白も残す）。新しく付けるのは、私が求めたときだけとする。
・画像の記号（[IMAGE 1]{30}）の行は、消さず、番号を変えず、新しく作らない。行の位置を動かすことと、幅の数字を変えることは構わない。
・段落の頭の全角空白（字下げ）は、元の行にそのまま残す。新しく段落を書くときは、前後の段落に合わせて、頭に全角空白を置くかどうかを決める。
・空行を入れない。元の文書にある空の行は、そのまま残す（空の行は、PDF で1行の空きになる）。ただし、元の文書で、同じ階層（# の数が同じ）の見出しの前に空の行を置いているときは、新しく書くその階層の見出しの前にも、空の行を1行置く（文書の先頭、<<< <<<= の直後、直前が空の行・見出しのときを除く）。
・見出しは # の数で階層を表す（# が第１、## が１、### が(1)…）。見出しに番号を書かない。# だけの行のすぐ後に見出しを書くと、2つの見出しを1行にまとめる（「第１　１　当事者」。複合見出し）。表題・日付・宛先など、最初の見出しより前の行には # を付けない。
・表は、| で列を区切るマークダウンの表で書く。2行目の - = : {字数} や、セルの先頭の配置の記号は、私が求めたときを除き、変えない。見出しの行の下を2重線にするときは、2行目のすべての列の - を = にする（|===|===|）。列の幅を求められたときは、2行目の列の後ろに、その列に入る字数を書く（|---{8}|---:{10}|）。すべての列に書くと、表の右端は列の幅の合計で決まる。
・太字は **語**、傍点は *語* で書く（太字と傍点を重ねると ***語***）。元の文書の太字・傍点の記号は残し、新しく付けるのは、私が求めたときだけとする。蛍光ペンの記号（==語==）と均等割付の記号（[語]{5}）は、私が求めたときを除き、付け外ししない。斜体・水平線・引用・リンク・脚注（[^1]）・HTML タグを使わない。1つの段落は1行に書き、段落の途中で改行しない。
・依頼が文書の書き直しである場合は、依頼した箇所以外の文字を変えない（要約・言い換えをしない）。
最終状態：回答を VA Documentに取り込むと、記号がすべて実名に戻り、配置と見出しの階層が元の文書と同じに保たれている。

4　使えるもの・制約
・記号の後に「さん」「様」などを付けるのは構わない。
・このファイルと同じフォルダにあるほかの構文ファイル（.vamd）は、別の案件の文書である。開いたり、内容を参考にしたりしない（記号は文書ごとに別の語を表す）。
・記号は文書ごとに振っている。この会話で前に扱った文書や、添付された文書の記号は、この文書の同じ記号と別の語を表すことがある。ほかの文書の記号を、この文書にそのまま書き写さない。
・記号の扱いについて確かめたいことがあれば、回答する前に質問すること。

5　成果物・報告
・文書を書き直したときは、区切りの行から文書の最後までの全体を、1つのコードブロックに入れて出力すること。コードブロックの最初の行は、区切りの行を一字も変えずに書く。この指示の部分は出力しない。コードブロックの前後の説明は短くする。
・文書の全体を出力する前に、区切りの行・記号・配置の記号が、元の文書と同じ形で残っているかを確かめること。
"""


# 前の版の既定の AI への指示（rstrip した文字列の SHA-256）。設定の指示（オプション）がこれと同じなら、ユーザーによって
# 書き換えられた指示ではなく既定の指示として扱い、今の版の指示を使う（記号を足したときに、新しい記号の説明が届くように）。
# Ver200 で名前を VA Document に改め、Ver160 までの構文ファイル（.vadm）を読まなくした（2026-10-27 班長決定）ので、
# それまでの版の指示（Ver130・Ver140・Ver142）は外した。指示を改めたら、ここに前の版の指示を足す
# （Ver220・Ver230 で足し忘れた。2026-10-28 に Ver231 で足した。Ver231 からは、開いた構文ファイルの指示は使わず、
# すべての文書に設定の指示〔なければ既定の指示〕を書く〔班長決定〕）
PREVIOUS_PROMPTS = {
    "c293b7da0341d8c303a0fa4f11a7d36d48c387dfca6c1acaceaf3a4ee6dcd2ba",   # Ver200・Ver210・Ver211
    "ebf82c3a20776b967575fa8d1d127be53ce3ad7f2ced6ad5e7f6b61210edb287",   # Ver220
    "30b5cdd9d81798eb3cf88831335ad5fedde648522fd4867dbc632689d3895a08",   # Ver230・Ver231・Ver240
    "425089d4a0e4ac7005c7e1b58b5fc7efa1f28b9d1068c192c4e2e4999130d722",   # Ver240 の次の版の作業中（命令文の「〜せよ」を改めた。配っていない）
    "96b017a0e4bf85cd49fb98852783e4b5cfd613c7aeb8598989c6be0857f81bb5",   # Ver250 の作業中（画像の記号を足した。配っていない）
    "426b6612795fb86f8a3d7e9644b51f436302cbf3f25e4fc6bc067ed640fb7431",   # Ver250 の作業中（「別の事件の文書」を「別の案件の文書」に。配っていない）
    "07968024fdfab1024ba0412d5d5ff17addad8cf274fb251832180f2079799136",   # Ver250 の作業中（書き出しをツールの働きだけを書く形に。配っていない）
    "42dc03c59fe3b3c0e097f1cc75daf78205668925ab397f6644b9405f49d8b85f",   # Ver250〜Ver261
    "76f170703112e448098019159435667c5dd44d9091d8f9cb73c01f16419c3cf4",   # Ver270（使わない記法に脚注を足した。2026-10-30 班長決定）
}
# 今の版の既定の指示の SHA-256。PROMPT を直すと試験（test_vamd）が落ちるので、そのときは、この値を PREVIOUS_PROMPTS に
# 移してから、新しい値に替える（前の版の登録を忘れないため。2026-10-28）
PROMPT_SHA256 = "bdbf333d3a3fa4a42e916d950b68d35f70bef8ba76d1190f6f151550fbe376e3"   # Ver280〜（表の列の幅の {字数} を足した。2026-11-01 班長決定）


def is_default_prompt(prompt):
    """prompt（オプションの画面・設定の指示）が、今の版か前の版の既定の指示か。"""
    text = prompt.rstrip()
    return text == PROMPT.rstrip() or hashlib.sha256(text.encode("utf-8")).hexdigest() in PREVIOUS_PROMPTS


class NoSeparator(ValueError):
    """区切りの行（文書ID・版）が見つからない。"""


class OtherDocument(ValueError):
    """開いている文書と、文書ID が違う。"""


@dataclass
class Settings:
    doc_type: str = DEFAULT_DOC_TYPE             # DOC_TYPES のキー
    page_number: str = PAGE_NUMBER_BOTTOM_CENTER  # PAGE_NUMBER_* のいずれか
    line_numbers: bool = False                   # 行番号を付けるか（2026-10-24 班長指示）
    one_width: bool = False                      # 見出し番号を全角1字の幅に縮めるか（doctypes.one_width_type。2026-10-26 班長指示）

    def allows_line_numbers(self):
        """行番号を付けられる文書の種類か（内容証明には付けない。2026-10-24 班長指示）。"""
        return self.doc_type != NAIYOU

    def allows_one_width(self):
        """見出し番号を1字の幅にできる文書の種類か（契約書1・技術文書ではできない）。"""
        return can_one_width(DOC_TYPES[self.doc_type])

    def normalized(self):
        """その文書の種類で使えない行番号・番号1字を外した設定。"""
        return replace(self, line_numbers=self.line_numbers and self.allows_line_numbers(),
                       one_width=self.one_width and self.allows_one_width())


@dataclass
class Content:
    doc_id: str
    version: int
    settings: Settings = None     # 区切りの行に設定がなければ None
    body: list = field(default_factory=list)   # 文書の行（記号入り）
    prompt: str = None            # AI への指示の部分（なければ None。AI の回答で上書きしたファイルなど）
    dropped: list = field(default_factory=list)   # 除いた AI の内部の目印の行（「<?thinking_complete?>」など）

    @property
    def body_text(self):
        return "\n".join(self.body)


def new_doc_id():
    return "".join(secrets.choice(DOC_ID_CHARS) for _ in range(DOC_ID_LENGTH))


def file_name(doc_id):
    return doc_id + EXTENSION


def default_folder():
    """構文ファイルだけを置く決まったフォルダ（ドキュメント\\VA Document\\構文ファイル。2026-10-24 に「構文ファイル」から
    改めた。設定に保存場所が書いてあれば、そちらを使う）。"""
    docs = None
    if os.name == "nt":
        # ドキュメントのフォルダは OneDrive などに移されていることがあるので、Windows に尋ねる
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:   # 5 = CSIDL_PERSONAL
            docs = Path(buf.value)
    if docs is None:
        docs = Path.home() / "Documents"
    return docs / "VA Document" / "構文ファイル"


# ---------- 区切りの行 ----------

def separator_line(doc_id, version, settings):
    dt = DOC_TYPES[settings.doc_type]
    return (f"==== VA Document 文書ID {doc_id} 版 {version} "
            f"種類 {dt.label} ページ番号 {PAGE_NUMBER_LABELS[settings.page_number]} "
            f"行番号 {'あり' if settings.line_numbers else 'なし'} "
            f"番号1字 {'あり' if settings.one_width else 'なし'} ====")


def has_separator(text):
    """文章に、構文ファイルの区切りの行があるか（行ごとに見る）。"""
    return any(SEPARATOR_RE.match(ln) for ln in text.splitlines())


def parse_separator_line(line):
    """区切りの行なら (文書ID, 版, 設定〔なければ None〕) を、そうでなければ None を返す。

    表の区切りの行（|---|）を読む document.parse_separator とは別の関数（Ver210 までは同じ名前で、こちらが
    取り込んだ document の関数を隠し、AI の回答の確かめで表の区切りの行の : を配置の記号として数えていた。Ver211 で直した）。
    """
    m = SEPARATOR_RE.match(line)
    if not m:
        return None
    words = m.group(3).split()
    pairs = dict(zip(words[0::2], words[1::2]))
    settings = None
    by_label = {d.label: d.key for d in DOC_TYPES.values()}
    if pairs.get("種類") in by_label:
        page = {v: k for k, v in PAGE_NUMBER_LABELS.items()}.get(pairs.get("ページ番号"), PAGE_NUMBER_BOTTOM_CENTER)
        # 行番号の書いていない区切りの行（2026-10-24 より前の構文ファイル）は「なし」。番号1字も、書いていなければ
        # （Ver152 までの構文ファイル）「なし」
        settings = Settings(by_label[pairs["種類"]], page, pairs.get("行番号") == "あり", pairs.get("番号1字") == "あり")
    return m.group(1), int(m.group(2)), settings


# ---------- 書き出し・読み込み ----------

def build(doc_id, version, settings, body, prompt=None):
    """構文ファイルの中身を作る。body は記号に置き換えた文書（文字列）。

    prompt は AI への指示の部分。ユーザーによってオプションで書き換えられた指示があれば、それを渡す（すべての文書に
    共通。2026-10-28 班長決定。構文ファイルの指示の部分を手で直しても、次に保存するときに書き直す）。None なら既定の指示。
    """
    lines = body.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    head = (prompt if prompt is not None else PROMPT).rstrip()
    return head + "\n\n" + separator_line(doc_id, version, settings) + "\n" + "\n".join(lines) + "\n"


def is_prompt(lines):
    """区切りの行より上が、AI への指示の部分か（AI の回答の前置きではないか）。

    VA Documentが書いた指示の書き出しか、班長の指示文の型の「1　状況」があれば、指示とみなす。
    利用者がそのどちらも消した場合は、AI の前置きとして捨て、保存するときに既定の指示を書く。
    """
    text = "\n".join(lines)
    return "ツール「VA Document」" in text or "1　状況" in text


def parse_text(text):
    """構文ファイル・AI の回答を読み、Content を返す。区切りの行がなければ NoSeparator を出す。"""
    lines = text.lstrip("﻿").splitlines()
    at = next((k for k, ln in enumerate(lines) if SEPARATOR_RE.match(ln)), None)
    if at is None:
        raise NoSeparator("区切りの行（「==== VA Document 文書ID …」の行）が見つかりません。")
    doc_id, version, settings = parse_separator_line(lines[at])
    body, dropped = [], []
    for ln in lines[at + 1:]:
        if FENCE_RE.match(ln):    # コードブロックの閉じの記号。ここから下は AI の結びの文
            break
        if AI_MARKER_RE.match(ln):
            dropped.append(ln.strip())
            continue
        body.append(ln.rstrip())
    while body and not body[-1].strip():
        body.pop()
    while body and not body[0].strip():
        body.pop(0)
    prompt = "\n".join(lines[:at]).rstrip() + "\n" if is_prompt(lines[:at]) else None
    return Content(doc_id, version, settings, body, prompt, dropped)


def read_file(path):
    with open(path, encoding="utf-8-sig") as f:
        return parse_text(f.read())


def write_file(path, text):
    """書き出す（一時ファイルに書いてから置き換える。途中で止まっても、前の版が壊れないように）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=EXTENSION, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ---------- 取り込む前の確かめ（仕様.md の8.3） ----------

@dataclass
class Review:
    older: bool = False          # 今の版より前の版をもとにした回答か
    newer: bool = False          # 今の版より後の版（ふつうは起きない）
    unknown_tokens: list = field(default_factory=list)   # 登録していない記号
    lost_tokens: list = field(default_factory=list)      # 今の文章にあって、回答で消えた記号
    lost_marks: list = field(default_factory=list)       # 消えた配置などの記号 [(記号, 今の文章の行)]
    changes: list = field(default_factory=list)          # [(種類, 今の行のリスト, 回答の行のリスト)]。種類は 変更・削除・追加
    changed_lines: list = field(default_factory=list)    # 回答で変わった・増えた行（回答の文書の何行目か。0 から）
    removed: list = field(default_factory=list)          # 回答で消えた段落（今の文章の行。変わったのではなく、なくなったもの）
    unknown_images: list = field(default_factory=list)   # 今の文書にない画像の番号（AI が作った [IMAGE n]）
    added_images: list = field(default_factory=list)     # 回答で増えた画像の行の番号（AI が行を写した）
    footnotes: list = field(default_factory=list)        # 回答で増えた脚注の記号（[^1] など。字のまま組まれる）

    @property
    def clean(self):
        return not (self.older or self.newer or self.unknown_tokens or self.lost_tokens or self.lost_marks
                    or self.unknown_images or self.added_images or self.footnotes)


def _marks(lines):
    out = []
    for ln in lines:
        s = ln.strip()
        if is_line_mark(s):
            out.append((s, ln))
            continue
        if s.startswith("|"):
            # 表のセルの配置の記号（区切りの行の : は比べない）。列の幅は、字数は比べない（直してよい）
            if parse_separator(s) is None:
                out += [(m.strip(), ln) for m in map(cell_align_mark, split_cells(s)) if m]
            else:
                out += [("{字数}", ln) for w in separator_widths(s) if w]
            continue
        lead = split_lead_marks(move_wraps_after_marks(ln))
        image = image_mark(ln)
        if image:
            out.append((f"[IMAGE {image[0]}]", ln))     # 幅の字数は比べない（直してよい）
        if lead.left:
            out.append(("->N", ln))     # 字数は比べない（直してよい）
        # ヘッダー・フッターの記号は、大文字・小文字を比べない
        for m in (lead.align, lead.area.upper()):
            if m:
                out.append((m.strip(), ln))
    return out + _indents(lines)


def _indents(lines):
    """字下げの空白が効く段落（見出し・本文として整えない段落〔最初の見出しより前・右揃えの段落の後〕、->N の段落、
    ヘッダー・フッター。左揃えのもの）のうち、行頭（記号の後ろ）に空白のある行を、記号と同じく [("字下げの空白", 行)] で
    返す（AI が消したら知らせる。2026-10-28 班長決定）。見出しの後の本文の行頭の空白は、読み込むと取り除くので数えない。
    どの段落で効くかは、組むときと同じく parse で決める（文書の種類で変わらない）。"""
    lines = list(lines)
    return [("字下げの空白", lines[p.src_line]) for p in parse(lines, DOC_TYPES[DEFAULT_DOC_TYPE])
            if p.kind == BODY and p.first_indent and p.align == JUSTIFY
            and (not p.body_level or p.left_indent is not None or p.area)]


def review(content, doc_id, version, current_body, dictionary, images=()):
    """AI の回答（content）を、今の文章（current_body：記号入りの行のリスト）と比べる。images は、データのある画像の番号。

    文書ID が違えば OtherDocument を出す（取り込む前に止める）。版の違いは止めずに知らせる
    （AI は会話の途中、最初に渡された版の番号を書き続けるため。2026-10-23 の往復試験）。
    """
    if content.doc_id != doc_id:
        raise OtherDocument(f"この回答は、別の文書（文書ID {content.doc_id}）のものです。開いている文書の文書ID は {doc_id} です。")
    r = Review(older=content.version < version, newer=content.version > version)
    new_tokens = tokens_in(content.body_text)
    old_tokens = tokens_in("\n".join(current_body))
    r.unknown_tokens = [t for t in dict.fromkeys(new_tokens) if dictionary.find(t) is None]
    r.lost_tokens = [t for t in dict.fromkeys(old_tokens) if t not in new_tokens]
    # 画像の行：消えたものは配置などの記号と同じく知らせる（lost_marks）。増えたものは、今の文書にない番号（AI が作った
    # もの）と、同じ番号の行が増えたもの（AI が行を写したもの）に分けて知らせる（2026-10-29）
    old_images, new_images = Counter(image_numbers(current_body)), Counter(image_numbers(content.body))
    for n, c in new_images.items():
        if c > old_images[n]:
            (r.added_images if old_images[n] or n in images else r.unknown_images).append(n)
    # 脚注の記号：今の文章より増えたものだけを知らせる（利用者が自分で書いた [^1] を、取り込むたびに知らせないため）
    old_notes = Counter(FOOTNOTE_RE.findall("\n".join(current_body)))
    new_notes = Counter(FOOTNOTE_RE.findall(content.body_text))
    r.footnotes = [m for m, c in new_notes.items() if c > old_notes[m]]
    new_marks = Counter(m for m, _ in _marks(content.body))
    new_lines = Counter(_marks(content.body))
    # 回答に同じ行がそのまま残っていれば、その行の記号は残ったとみなしてから、記号の数を比べる（どの行の記号が
    # 消えたかを、なるべく正しく示すため。2026-10-28）
    rest = []
    for m, ln in _marks(current_body):
        if new_lines[(m, ln)]:
            new_lines[(m, ln)] -= 1
            new_marks[m] -= 1
        else:
            rest.append((m, ln))
    seen = Counter()
    for m, ln in rest:
        seen[m] += 1
        if seen[m] > new_marks[m]:
            r.lost_marks.append((m, ln))
    # 空の行も比べる（空の行は1行の空きになるので、AI が足した・消した空行も変更として示す。2026-10-23）。
    # ただし、文書の初めと終わりの空の行は、読み込みで取り除くので比べない
    old = list(current_body)
    while old and not old[-1].strip():
        old.pop()
    while old and not old[0].strip():
        old.pop(0)
    new_index = list(range(len(content.body)))
    new = list(content.body)
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    names = {"replace": "変更", "delete": "削除", "insert": "追加"}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            r.changes.append((names[tag], old[i1:i2], new[j1:j2]))
            r.changed_lines.extend(new_index[j1:j2])
            if tag == "delete":
                r.removed.extend(ln for ln in old[i1:i2] if ln.strip())
    return r
