"""段落の先頭に手で打った番号（疑似アウトライン）を読み、見出し・箇条書き・段落番号の記号にする。

VA疑似アウトライン（Word のアドイン）の［マークダウンに変換］（basConvertToMarkdown.ConvertToMarkdownSyntax・
ProcessCompositeHeadings）を取り込んだもの（2026-11-24 班長指示）。構文ファイルのない PDF を開いたとき
（pdfmarkdown.py）に使う。

VA疑似アウトラインとの違い：
・VA疑似アウトラインは、番号の形でレベルを決める（「第１」は #、「１」は ##、「(1)」は ### …。裁判所提出書類の番号の形）。
  ここでは、文書の種類（doctypes.DocType）の番号の書式から、組んだときにその位置に付く番号を作り、段落の先頭がそれと
  同じときだけ、そのレベルの見出しにする（契約書・技術文書の番号の形も読めるように。また、番号を記号に置き換えても、
  組み直したときに同じ番号が付くように。「第１」の次に「第３」があるような、番号が飛んだ段落は、見出しにせず字のまま
  残す。利用者の文章を変えないため）。数字の全角・半角、括弧の全角・半角、全角空白・半角空白の違いは同じとみなす。
・番号の後ろには、VA疑似アウトラインと同じく空白（または「.」）を求める。括弧で終わる番号（「(1)」）と、書式の後ろに空白の
  ない番号（契約書の「第１条」）は、空白がなくてもよい。「１件目」「2026年」のように、番号の後ろに字が続くものは番号とみない。
・複合見出し（「１(1) 当事者」「第１　１　当事者」）は、VA疑似アウトラインの ProcessCompositeHeadings と同じく、字のない
  見出しと、次のレベルの見出しの2行に分ける（左インデントの増加量が1字の文書の種類だけ。document.parse と同じ）。
・番号だけの段落（「(1)」だけ）は、見出しにしない（字のない見出しは、次の見出しと1行にまとめられてしまうため）。
・箇条書きは、文書の種類の箇条書きの記号（「・」など）で始まる段落、段落番号は、組んだときにその位置に付く番号（①など）で
  始まる段落とする。

状態（番号・最初の見出しを過ぎたか・右揃えの段落を過ぎたか）の進め方は、document.parse と同じにする。
"""
import unicodedata
from dataclasses import dataclass

from .doctypes import number_text

HEADING, COMPOSITE, BULLET, NUMBER = "heading", "composite", "bullet", "number"

# 番号を比べるときに同じとみなす字（全角の英数字・記号は半角に、全角空白は半角空白に、半角のカタカナは全角に）。
# 1字を1字にする（字の位置がずれないように。unicodedata.normalize の NFKC は「①」を「1」にするなど、字の数も
# 変えるので使わない）
_SAME = {chr(c): chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)}
_SAME.update({"　": " ", "〔": "(", "〕": ")"})
_SAME.update({ch: unicodedata.normalize("NFKC", ch) for ch in map(chr, range(0xFF66, 0xFF9E))
              if len(unicodedata.normalize("NFKC", ch)) == 1})
_CLOSE = ")]」』】"          # 括弧で終わる番号は、後ろに空白がなくてもよい
_SPACES = " 　\t"


def same_form(s):
    """番号を比べるための形（字の数は変えない）。"""
    return "".join(_SAME.get(ch, ch) for ch in s)


def _kind(ch):
    """字の種類（番号の後ろに同じ種類の字が続けば、番号の一部とみる。「第1」の後ろの「0」など）。"""
    if ch.isdigit():
        return "digit"
    if ch.isascii() and ch.isalpha():
        return "alpha"
    if "ァ" <= ch <= "ヺ" or ch == "ー":
        return "kana"
    return None


@dataclass(frozen=True)
class Mark:
    """段落の先頭の番号を読んだ結果。"""
    kind: str               # HEADING・COMPOSITE・BULLET・NUMBER
    level: int = 0          # 見出しのレベル（複合見出しは外側のレベル）
    end: int = 0            # 番号（と後ろの空白）の後ろの字の位置（段落の字の何字目から本文か）
    exact: bool = True      # 全角・半角も含めて、組んだときの番号と同じ字か
    depth: int = 1          # 1行にまとめたレベルの数（複合見出しは2以上。level から level + depth - 1 まで）


class Outliner:
    """1つの文書の段落を上から順に読み、番号を記号にするかを決める（document.parse と同じ状態を持つ）。"""

    def __init__(self, dt):
        self.dt = dt
        self.counters = [0] * 9     # レベルごとの番号
        self.current = 0            # いまのレベル
        self.seen = False           # 最初の見出し（または箇条書き・段落番号）を過ぎたか
        self.stopped = False        # 見出しの後の右揃えの段落を過ぎたか（そこから先は記号にしない）
        self.prev_number = 0        # 直前の段落が段落番号なら、その通し番号（でなければ 0）

    # ---------- 状態 ----------

    def section_break(self):
        """セクション区切り（<<<=）：番号を振り直し、初めの状態に戻す。"""
        self.counters = [0] * 9
        self.current, self.seen, self.stopped, self.prev_number = 0, False, False, 0

    @property
    def free(self):
        """いまの段落が、見出し・本文として整えない段落か（最初の見出しの前・右揃えの段落の後）。"""
        return not self.seen or self.stopped

    def accept(self, mark, align_right=False):
        """段落を1つ進める。mark は classify の結果（記号にしない段落は None）。"""
        if mark is not None and mark.kind in (HEADING, COMPOSITE):
            for level in range(mark.level, mark.level + mark.depth):
                self.counters = self._advanced(level)[1]
                self.current = level
            self.seen = True
        elif mark is not None and mark.kind == BULLET:
            self.seen = True
        elif mark is not None and mark.kind == NUMBER:
            self.seen = True
        self.prev_number = self.prev_number + 1 if mark is not None and mark.kind == NUMBER else 0
        if self.seen and align_right:
            self.stopped = True

    # ---------- 番号 ----------

    def _advanced(self, level, counters=None):
        """レベル level の見出しを1つ進めたときの (番号の字, 進めた後の番号の組)。document.parse と同じ数え方。
        その字の種類で表せない番号（ア〜ンを超えたカタカナなど）なら、番号の字は None。"""
        dt = self.dt
        counters = list(self.counters if counters is None else counters)
        counters[level - 1] = counters[level - 1] + 1 if counters[level - 1] else dt.start_at[level - 1]
        for k in range(level, 9):
            if dt.reset_on[k] and dt.reset_on[k] >= level:
                counters[k] = 0
        num = dt.number_formats[level - 1]
        try:
            for k in range(9):
                num = num.replace(f"%{k + 1}", number_text(dt.number_styles[k], counters[k]) if counters[k] else "")
        except (IndexError, ValueError):
            return None, counters
        return num, counters

    @staticmethod
    def _after(text, k, number, needs_space):
        """text の k 字目から番号 number（後ろの空白を除いた形）があれば、番号の後ろの本文の位置（空白を除いた後）。
        なければ -1。needs_space は、書式の後ろに空白があるか（あれば、番号の後ろにも空白か「.」を求める）。"""
        core = same_form(number)
        if not core or same_form(text[k:k + len(core)]) != core:
            return -1
        k += len(core)
        if k >= len(text):
            return -1                               # 番号だけの段落は見出しにしない
        ch = text[k]
        if ch in _SPACES:
            while k < len(text) and text[k] in _SPACES:
                k += 1
            return k if k < len(text) else -1
        last = core[-1]
        if _kind(ch) and (_kind(ch) == _kind(last) or (last == "." and _kind(ch) == "digit")):
            return -1                               # 「第1」の後ろの「0」、「1.」の後ろの「1」（1.1.）
        if ch in ".．" and _kind(last):
            # 「1.」「ア．」（VA疑似アウトラインと同じく、番号の後ろの「.」は区切りとみる）
            k += 1
            while k < len(text) and text[k] in _SPACES:
                k += 1
            return k if k < len(text) else -1
        if not needs_space or last in _CLOSE:
            return k
        return -1

    def _heading_at(self, text, level, k=0, counters=None):
        """text の k 字目から、レベル level の見出しの番号があれば (本文の位置, 番号の字が同じか, まとめたレベルの数)。
        番号のすぐ後ろ（「第１　」なら空白の後ろ）に次のレベルの番号が続けば、複合見出しとして、続くレベルもまとめる
        （「１(1)ア　見出し」。左インデントの増加量が1字の文書の種類だけ。document.parse と同じ）。"""
        if not self.dt.number_formats[level - 1]:
            return None
        num, after = self._advanced(level, counters)
        if num is None:
            return None
        core = num.rstrip(_SPACES)
        if not core or same_form(text[k:k + len(core)]) != same_form(core):
            return None
        exact = text[k:k + len(core)] == core
        if level < 9 and self.dt.left_add == 1:
            j = k + len(core)
            while j < len(text) and text[j] in _SPACES:
                j += 1
            inner = self._heading_at(text, level + 1, j, after)
            if inner is not None:
                return inner[0], exact and inner[1], inner[2] + 1
        end = self._after(text, k, core, needs_space=core != num)
        return (end, exact, 1) if end >= 0 else None

    def classify(self, text):
        """段落の字 text の先頭の番号を読み、Mark を返す（記号にしないなら None）。状態は変えない（accept で進める）。"""
        if self.stopped or not text:
            return None
        found = []
        for level in range(1, 10):
            hit = self._heading_at(text, level)
            if hit is not None:
                end, exact, depth = hit
                found.append(Mark(HEADING if depth == 1 else COMPOSITE, level, end, exact, depth))
        if found:
            # 同じ字が2つのレベルの番号に当たるとき（「i」はアルファベットの9番目とローマ数字の1番目）は、
            # いまのレベルの1つ下までで、いちばん深いものを選ぶ（なければ、いちばん浅いもの）
            near = [m for m in found if m.level <= self.current + 1]
            return max(near, key=lambda m: m.level) if near else min(found, key=lambda m: m.level)
        return self._list_mark(text)

    def _list_mark(self, text):
        """箇条書き・段落番号の記号で始まるか。"""
        dt = self.dt
        n = self.prev_number + 1
        try:
            num = dt.list_number.replace("%1", number_text(dt.list_number_style, n))
        except (IndexError, ValueError):
            num = ""
        core = num.rstrip(_SPACES)
        if core:
            end = self._after(text, 0, core, needs_space=core != num)
            if end >= 0:
                return Mark(NUMBER, 0, end, text.startswith(core))
        bullet = dt.list_bullet.strip()
        bullets = (bullet, "･") if bullet == "・" else (bullet,)
        for b in bullets:
            if b and text.startswith(b):
                k = len(b)
                if b.isascii() and (k >= len(text) or text[k].isdigit()):
                    continue                        # 「-」の後ろが数字なら、箇条書きとみない（「-1度」）
                while k < len(text) and text[k] in _SPACES:
                    k += 1
                if k < len(text):
                    return Mark(BULLET, 0, k, b == bullet)
        return None
