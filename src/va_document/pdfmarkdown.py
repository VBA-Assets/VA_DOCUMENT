"""構文ファイルのない PDF から、字の位置と番号を手がかりに、マークダウン（構文ファイルの文章）を作る。

2026-11-24 班長指示「VA疑似アウトラインの機能を取り込む。テキストが埋め込まれているが、構文ファイルがない PDF を開いた
場合、可能な限り、マークダウンを自動的に生成し、構文ファイルを作る」。それまでは、字を段落ごとに取り出すだけで、見出し・
配置は戻さなかった（pdftext.plain_text。読み取りに失敗したときは、今もそれを使う）。保存は、今までと同じ［保存］で行う
（PDF と構文ファイルを作る）。開いた PDF は書き換えない。

戻すもの（字の位置から読む。VA Document・VA公用文〔Word〕で作った PDF を手本にした）：
・段落：右の余白の端まで字が詰まった行の次の行は、同じ段落の続きとみる（日本語の文書は両端揃えで、段落の途中の行は
  右の端まで詰まる）。行の頭の位置が、段落の続きの行と食い違えば（1行目の字下げ・見出しのぶら下げ）、新しい段落とみる。
  ページをまたぐ段落もつなぐ。行と行の間が広くあいていれば、空の行（Word の空の段落と同じ1行の空き）を入れる。
・見出し・箇条書き・段落番号：段落の先頭の手で打った番号を、VA疑似アウトラインと同じ考え方で記号にする（pseudo_outline.py）。
  番号の書式は、文書の種類ごとに違うので、文書の種類ごとに試し、番号がいちばん多く当たる種類を選ぶ（VA Document の用紙・
  余白に合う PDF は、その種類の中から選ぶ。当たる数が同じなら、今の設定の文書の種類）。ウェブ文書は、字の大きい段落を見出しにする。
・配置：左右の余白の真ん中に置かれた行は中央（最初の見出しより前で最初のものは表題）、右の余白の端にそろえた行は右揃え。
・字下げ：見出し・本文として整えない段落（最初の見出しより前・右揃えの段落の後）は、行頭の全角空白（1行目の字下げ）と
  ->N（左インデント）で戻す。見出し・本文は、組むときに VA公用文と同じインデントが付くので、戻さない。
・表：罫線で囲まれた表（2行・2列以上）を、マークダウンの表にする。
・改ページ：ページの下が4行以上あいていれば、改ページ（<<<）。改ページの後で見出しの番号が振り直されていれば、
  セクション区切り（<<<=）。
・太字：太字の書体（名前に Bold）や、明朝の文書の中のゴシック（VA Document の太字）の字を **字** にする。
・ページ番号（ページの上下の端の数字だけの行）・行番号（左の余白の小さい数字）は、字から除き、文書の設定（ページ番号の
  位置・行番号）に戻す。
戻さないもの：画像、傍点・蛍光ペン・均等割付、表の列の幅・2重線、ヘッダー・フッター（本文の字として残す）、目次（字として残す）。

Word の文書（.docx）の取り込み（docxmarkdown.py。Ver420）も、段落をここの Block にして、同じ to_markdown でマークダウンに
する。Word の文書は、見出しのレベル・番号（Block.level・list_kind・label）、傍点・蛍光ペン（字の書式）、画像の行（IMAGE）を
持つ。
"""
import copy
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

import pdfplumber

from .doctypes import (DOC_TYPES, MM, PAGE_NUMBER_BOTTOM_CENTER, PAGE_NUMBER_BOTTOM_CENTER_DECORATED,
                       PAGE_NUMBER_BOTTOM_RIGHT, PAGE_NUMBER_NONE, PAGE_NUMBER_TOP_RIGHT, TITLE_CENTER, TITLE_JUSTIFY,
                       WEB, doc_type_for)
from .document import (AREA_MARK_RE, HEADING_MARK_RE, IMAGE_RE, LEFT_INDENT_RE, LIST_MARK_RE, is_line_mark,
                       is_table_line, split_inline_full, split_lead_marks)
from .pdftext import _kangxi
from .pseudo_outline import BULLET, COMPOSITE, HEADING, NUMBER, Mark, Outliner, same_form

# 段落の種類（Block.kind）。IMAGE は画像の行（Word の文書の取り込み。docxmarkdown.py）
TEXT, TABLE, PAGE_BREAK, IMAGE = "text", "table", "pagebreak", "image"
# 字の書式（Row.chars の (字, 書式) の書式。PDF は太字だけを読むので True/False。Word の文書は傍点・蛍光ペンも持つ）
BOLD, DOTS, HIGHLIGHT = 1, 2, 4
# 行の配置（Block.align）
LEFT, CENTER, RIGHT = "left", "center", "right"

ROW_TOLERANCE = 0.2     # 基準線の差が、字の大きさのこの倍以内の字は、同じ行とみる
FULL = 0.6              # 行の右端が、右の余白の端からこの字数以内なら、右の端まで詰まった行とみる
CENTER_TOLERANCE = 0.75  # 行の真ん中が、左右の余白の真ん中からこの字数以内なら、中央の行とみる
RIGHT_START = 0.4       # 右揃えの行は、本文の幅のこの割合より右から始まる（それより左から始まるのは、詰まった本文の行）
BLANK_GAP = 1.5         # 行の間が、行送りのこの倍より広ければ、空の行を入れる
PAGE_BREAK_ROWS = 4     # ページの下がこの行数以上あいていれば、改ページとみる
MARGIN_MATCH = 2.0  # 文書の種類の余白と、PDF の本文の左右の端の差が、このポイント以内なら同じとみる
A4 = (595.28, 841.89)
# ページ番号の行（「1」「- 1 -」「1/3」「１」「３」」）
_PAGE_NUMBER_RE = re.compile(r"[-－−―‐ー–—\s]*[0-9０-９]+」?(?:\s*/\s*[0-9０-９]+)?[-－−―‐ー–—\s]*")
# 段落の先頭の、番号らしいもの（右の端まで詰まった行の次の行でも、これで始まれば、ひとまず新しい段落とする。
# 番号として記号にしなかったら、前の段落につなぎ直す〔Block.soft〕）
_NUMBER_LIKE_RE = re.compile(r"(?:第[0-9]+[条章節款項]?|[0-9]+(?:\.[0-9]+)*\.?|[(][0-9a-zア-ン]{1,4}[)]|[ア-ン]|[a-z]{1,4}"
                             r"|[①-⑳・･])(?:[ (「]|$)|[(][0-9a-zア-ン]{1,4}[)]|第[0-9]+条")
# 目次の項目（字の後に点線とページ番号）
_TOC_ENTRY_RE = re.compile(r"[.．…‥・]{4,}\s*[0-9０-９]+$")


@dataclass
class Row:
    """PDF の1行（同じ基準線の字）。位置はポイントで、上下は用紙の上端から。"""
    page: int
    base: float             # 基準線
    left: float             # 空白でない最初の字の左端
    right: float            # 空白でない最後の字の右端
    size: float             # 字の大きさ（行の中でいちばん多いもの）
    chars: list             # [(字, 書式)]（書式は太字か〔PDF〕か、BOLD・DOTS・HIGHLIGHT の和〔Word〕。字の間の広いあきは、
                            # 全角空白・半角空白にしてある）
    pdf_chars: list = None  # PDF の字（描いた空白を含む。左から）

    @property
    def text(self):
        return "".join(ch for ch, _ in self.chars)


@dataclass
class Block:
    """段落（または表・改ページ）。"""
    kind: str = TEXT
    rows: list = field(default_factory=list)
    cells: list = None      # 表のとき、行ごとのセルの字
    blank: int = 0          # 前に入れる空の行の数
    soft: bool = False      # 前の段落の続きかもしれない（番号らしいもので始まるので分けた）
    align: str = LEFT
    first: float = 0.0      # 1行目の字下げ（左インデントからの字数）
    indent: float = 0.0     # 左インデント（本文の左端からの字数。2行目以降の頭の位置）
    # Word の文書から取り込んだ段落だけ（docxmarkdown.py）。PDF は字の位置と番号から読むので、使わない
    level: int = 0          # 見出しのレベル（Word の見出しのスタイル・アウトラインのレベル + 1）
    list_kind: str = ""     # 見出しのレベルのない段落に Word が振った番号：BULLET か NUMBER
    label: str = ""         # その番号の字（見出しの番号として読めるかを試す）
    line: str = None        # IMAGE のとき、画像の行（[IMAGE n]{幅}）

    @property
    def chars(self):
        return _join_rows(self.rows)

    @property
    def size(self):
        return max((r.size for r in self.rows), default=0)


def _alnum(ch):
    return ch.isascii() and ch.isalnum()


def _join_rows(rows):
    """段落の行をつないだ字。英数字の語が行の境目で分かれていれば（「ABC」「Cloud」）、間に半角空白を補う
    （行の境目の空白は、PDF に描かれないため）。"""
    out = []
    for r in rows:
        if out and r.chars and _alnum(out[-1][0]) and _alnum(r.chars[0][0]):
            out.append((" ", False))
        out += r.chars
    return out


@dataclass
class Layout:
    """PDF を読んだ結果（文書の種類によらないもの）。"""
    blocks: list
    page_size: tuple
    left: float             # 本文の左端
    right: float            # 本文の右端
    pitch: float            # 字の送り（全角1字の幅）
    body_size: float        # 本文の字の大きさ
    page_number: str        # ページ番号の位置（PAGE_NUMBER_*）
    line_numbers: bool      # 行番号があったか
    images: bool            # 画像があったか


@dataclass
class Converted:
    """変換の結果。"""
    text: str               # 入力欄に入れる文章（マークダウン）
    settings: object        # 文書の設定（vamd.Settings）
    headings: int           # 記号にした見出し・箇条書き・段落番号の数
    images: bool            # PDF に画像があったか（取り込んでいない）


# ---------- PDF を読む ----------

def _open(path):
    # ファイルを開いたままにしない（読み終えたら閉じ、保存し直しを妨げない）
    return pdfplumber.open(io.BytesIO(Path(path).read_bytes()))


def _is_bold(fontname, body_font):
    """太字の字か。名前に Bold などが入った書体、または本文が明朝の文書の中のゴシック（VA Document の太字）。"""
    name = fontname.lower()
    if any(w in name for w in ("bold", "black", "heavy", "w6", "w7", "w8", "w9")):
        return True
    gothic = ("gothic", "goth", "ゴシック", "sans")
    return any(w in name for w in gothic) and not any(w in body_font.lower() for w in gothic)


def _is_mincho(fontname):
    name = fontname.lower()
    return any(w in name for w in ("mincho", "明朝", "serif", "times", "century")) and "sans" not in name


def _wide(s):
    """全角の字か（PDF の字は、合字などで2字以上のこともあるので、最初の字で見る）。"""
    return bool(s) and unicodedata.east_asian_width(s[0]) in ("W", "F")


def _tables(page):
    """罫線で囲まれた表（2行・2列以上）の [(上端, 下端, 囲み, セルの字の行のリスト)]。"""
    found = []
    try:
        tables = page.find_tables()
    except Exception:
        return found
    for t in tables:
        rows = t.extract()
        if len(rows) < 2 or max((len(r) for r in rows), default=0) < 2:
            continue
        cells = [["".join((c or "").split("\n")).strip() for c in r] for r in rows]
        found.append((t.bbox[1], t.bbox[3], t.bbox, cells))
    return found


def _inside(c, bbox):
    x0, top, x1, bottom = bbox
    cx, cy = (c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2
    return x0 <= cx <= x1 and top <= cy <= bottom


def _remove_line_numbers(chars, size):
    """左の余白の行番号（本文のどの字よりも左にある数字）を除く。除いたら True も返す。行番号とみるのは、本文より小さい
    数字（VA Document・VA公用文の行番号）か、右端をそろえて3行以上に並んだ数字（Word の行番号）。"""
    body = [c for c in chars if not c["text"].isspace() and not c["text"].isdigit()]
    if not body:
        return chars, False
    left = min(c["x0"] for c in body)
    margin = [c for c in chars if c["text"].isdigit() and c["x1"] <= left - 0.5 * size]
    rows = {}
    for c in margin:
        rows.setdefault(round(c["matrix"][5]), []).append(c)
    ends = Counter(round(max(c["x1"] for c in cs)) for cs in rows.values())
    column = {e for e, n in ends.items() if n >= 3}
    drop = {id(c) for cs in rows.values() for c in cs
            if round(max(x["x1"] for x in cs)) in column or c["size"] < 0.9 * size}
    return [c for c in chars if id(c) not in drop], bool(drop)


def _row_chars(cs, pitch, body_font, full=False):
    """1行の字（左から）を、[(字, 太字か)] にする。描いた空白は除き、字と字の間の広いあきを空白にする
    （全角1字の幅のあきは全角空白、半角ほどのあきは半角空白。Word の PDF は、全角空白も半角の幅の空白の字で描くため、
    空白の字ではなく、あきの広さで決める）。あきは、その行のふつうの字の間（内容証明の格子の間、両端揃えで広げた間）
    より広い分で測る。full は、右の端まで詰まった行か（両端揃えで字の間を大きく広げることがある。詰まっていない行で
    字の間が広いのは、空白で空けたもの）。"""
    ink = [c for c in cs if not c["text"].isspace()]
    drawn = [(c["x0"] + c["x1"]) / 2 for c in cs if c["text"].isspace()]     # 描いた空白の真ん中
    # ふつうの字の間（いちばん狭い間）は、全角の字の前後と、半角の字どうし（英数字の語の中。両端揃えでも広げない）に
    # 分けて測る。両端揃えで広げた間は、どの字の間もほぼ同じだけ広がるので、いちばん狭い間がその広さになる
    pairs = list(zip(ink, ink[1:]))
    usual = {}
    for wide in (True, False):
        u = min((b["x0"] - a["x1"] for a, b in pairs if (_wide(a["text"]) or _wide(b["text"])) == wide), default=0.0)
        usual[wide] = max(0.0, u if full else min(u, 0.5 * pitch))
    out, prev = [], None
    for c in ink:
        if prev is not None:
            gap = c["x0"] - prev["x1"] - usual[_wide(prev["text"]) or _wide(c["text"])]
            if gap >= 0.75 * pitch:
                out += [("　", False)] * max(1, round(gap / pitch))
            elif gap >= 0.3 * c["size"] or (gap >= 0.15 * c["size"]
                                             and any(prev["x1"] - 1 <= x <= c["x0"] + 1 for x in drawn)):
                out.append((" ", False))        # 半角ほどのあき（描いた空白があれば、狭くても空白とみる）
        for ch in _kangxi(c["text"]):
            out.append((ch, _is_bold(c["fontname"], body_font)))
        prev = c
    return out


def _rows(page_no, chars, size, pitch, body_font, height):
    """字を基準線ごとの行にする（上から）。"""
    chars = sorted(chars, key=lambda c: height - c["matrix"][5])
    groups = []
    for c in chars:
        base = height - c["matrix"][5]
        if groups and base - groups[-1][0] <= ROW_TOLERANCE * size:
            groups[-1][1].append(c)
        else:
            groups.append((base, [c]))
    rows = []
    for base, cs in groups:
        cs.sort(key=lambda c: c["x0"])
        ink = [c for c in cs if not c["text"].isspace()]
        if not ink:
            continue
        sizes = Counter(round(c["size"], 1) for c in ink)
        rows.append(Row(page_no, base, ink[0]["x0"], ink[-1]["x1"], sizes.most_common(1)[0][0],
                        _row_chars(cs, pitch, body_font), cs))
    return rows


def _pitch(pages, size):
    """全角の字の送り（同じ行の、続いて並んだ全角の字の左端の差のうち、いちばん多いもの）。"""
    steps = Counter()
    for chars in pages:
        rows = {}
        for c in chars:
            if abs(c["size"] - size) <= 0.05 * size:        # 本文の大きさの字だけで測る
                rows.setdefault(round(c["matrix"][5]), []).append(c)
        for cs in rows.values():
            cs.sort(key=lambda c: c["x0"])
            for a, b in zip(cs, cs[1:]):
                d = b["x0"] - a["x0"]
                if _wide(a["text"]) and _wide(b["text"]) and 0.8 * size <= d <= 2.5 * size:
                    steps[round(d, 1)] += 1
    return steps.most_common(1)[0][0] if steps else size


def read_layout(path):
    """PDF を読み、段落（Block）のリストと、本文の範囲・ページ番号・行番号を返す。"""
    with _open(path) as pdf:
        pages, images, page_size = [], False, None
        for page in pdf.pages:
            x0, top0, x1, bottom0 = page.bbox
            page_size = page_size or (page.width, page.height)
            images = images or bool(page.images)
            tables = _tables(page)
            chars = [c for c in page.chars
                     if not (c["x1"] < x0 or c["x0"] > x1 or c["bottom"] < top0 or c["top"] > bottom0)
                     and not any(_inside(c, t[2]) for t in tables)]
            pages.append((page.height, chars, tables))
    ink = [c for _, chars, _ in pages for c in chars if not c["text"].isspace()]
    if not ink:
        return None
    # 本文の字の大きさ：字の2割以上を占める大きさのうち、いちばん小さいもの（見出しの多い短い文書で、見出しの大きな字を
    # 本文と取り違えないように。行番号・ページ番号の小さな字は、2割に届かない）
    sizes = Counter(round(c["size"], 1) for c in ink)
    size = min(s for s, n in sizes.items() if n >= 0.2 * len(ink)) if any(
        n >= 0.2 * len(ink) for n in sizes.values()) else sizes.most_common(1)[0][0]
    fonts = Counter(c["fontname"] for c in ink if round(c["size"], 1) == size)
    body_font = fonts.most_common(1)[0][0]
    # 明朝の字が2割以上あれば、本文は明朝（太字の多い文書で、太字のゴシックを本文と取り違えないように）
    mincho = [f for f, n in fonts.most_common() if _is_mincho(f) and n >= 0.2 * sum(fonts.values())]
    if mincho:
        body_font = mincho[0]
    line_numbers = False
    cleaned = []
    for height, chars, tables in pages:
        chars, found = _remove_line_numbers(chars, size)
        line_numbers = line_numbers or found
        cleaned.append((height, chars, tables))
    pitch = _pitch([chars for _, chars, _ in cleaned], size)
    page_rows = [(_rows(k, chars, size, pitch, body_font, height), tables)
                 for k, (height, chars, tables) in enumerate(cleaned)]
    lp = _line_pitch([rows for rows, _ in page_rows], size)
    page_number, page_rows = _take_page_numbers(page_rows, lp, page_size)
    body = [r for rows, _ in page_rows for r in rows if r.size >= 0.8 * size]
    if not body:
        body = [r for rows, _ in page_rows for r in rows]
    left = min(r.left for r in body) if body else 0
    right = _right_edge(body, left, pitch, size, (page_size or A4)[0])
    for rows, _ in page_rows:
        for r in rows:
            if _is_full(r, right, pitch):
                r.chars = _row_chars(r.pdf_chars, pitch, body_font, full=True)
    blocks = _blocks(page_rows, left, right, pitch, lp, (page_size or A4)[1])
    return Layout(blocks, page_size, left, right, pitch, size, page_number, line_numbers, images)


def _line_pitch(pages, size):
    """行送り（同じページの、続いた行の基準線の差のうち、いちばん多いもの）。"""
    steps = Counter()
    for rows in pages:
        for a, b in zip(rows, rows[1:]):
            d = b.base - a.base
            if 0.9 * size <= d <= 3 * size:
                steps[round(d)] += 1
    return float(steps.most_common(1)[0][0]) if steps else 1.5 * size


def _take_page_numbers(page_rows, lp, page_size):
    """ページの上下の端の、数字だけの行（ページ番号）を除き、ページ番号の位置（PAGE_NUMBER_*）を返す。"""
    found, out = [], []
    width = page_size[0] if page_size else A4[0]
    for rows, tables in page_rows:
        rows = list(rows)
        for at_top in (True, False):
            if not rows:
                break
            r = rows[0] if at_top else rows[-1]
            other = (rows[1] if at_top else rows[-2]) if len(rows) > 1 else None
            if (other is None or abs(r.base - other.base) >= 1.3 * lp) and _PAGE_NUMBER_RE.fullmatch(r.text):
                found.append((at_top, r))
                rows.remove(r)
        out.append((rows, tables))
    if not found:
        return PAGE_NUMBER_NONE, out
    # いちばん多い置き場所（上か下か）のページ番号で決める
    at_top = Counter(t for t, _ in found).most_common(1)[0][0]
    sample = next(r for t, r in found if t == at_top)
    if at_top:
        return PAGE_NUMBER_TOP_RIGHT, out
    centered = abs((sample.left + sample.right) / 2 - width / 2) < 0.1 * width
    if "/" in sample.text or not centered:
        return PAGE_NUMBER_BOTTOM_RIGHT, out
    if re.search(r"[-－−―‐ー–—]", sample.text):
        return PAGE_NUMBER_BOTTOM_CENTER_DECORATED, out
    return PAGE_NUMBER_BOTTOM_CENTER, out


def _right_edge(rows, left, pitch, size, width):
    """本文の右端（最後の字の右端）。用紙の幅の4分の3より右で終わる行が2つ以上あれば、その右端のうちいちばん多いもの
    （句読点のぶら下げで1字はみ出た行は除く）。なければ（短い文書）、左の余白が合う VA Document の文書の種類の右の余白、
    それもなければ、左右の余白が同じとみる。"""
    if not rows:
        return left
    far = max(r.right for r in rows)
    ends = Counter(round(r.right) for r in rows if r.right >= 0.75 * width)
    if ends and ends.most_common(1)[0][1] >= 2:
        edge, n = ends.most_common(1)[0]
        # 同じくらい多い端が2つあれば、左のもの（右のものは、ぶら下げの行）
        close = [e for e, m in ends.items() if m >= 0.5 * n and abs(e - edge) <= 1.5 * pitch]
        return float(min(close))
    rights = sorted(width - dt.margins[3] * MM - max(0.0, pitch - size) for dt in DOC_TYPES.values()
                    if abs(left - dt.margins[2] * MM) <= MARGIN_MATCH)
    # 右の端にそろえた行（右揃え）があれば、その端に合うもの。なければ、いちばん右の字が収まるもののうち、いちばん狭いもの
    fit = ([r for r in rights if abs(far - r) <= FULL * pitch]
           or [r for r in rights if far <= r + 1.2 * pitch])
    if fit:
        return fit[0]
    return max(far, width - left - max(0.0, pitch - size))


# ---------- 段落に分ける ----------

def _is_full(r, right, pitch):
    return r.right >= right - FULL * pitch


def _is_right(r, left, right, pitch):
    """右揃えの行か（右の端にそろい、本文の幅の4割より右から始まる）。"""
    return abs(r.right - right) <= FULL * pitch and r.left >= left + RIGHT_START * (right - left)


def _is_center(r, left, right, pitch):
    """中央の行か（左右の余白の真ん中に置かれ、左右にあきがある）。"""
    return (r.left >= left + 1.5 * pitch and r.right <= right - 1.5 * pitch
            and abs((r.left + r.right) / 2 - (left + right) / 2) <= CENTER_TOLERANCE * pitch)


def _continues(block, b, left, right, pitch, lp):
    """行 b が、段落 block の続きか。"""
    a = block.rows[-1]
    if a.page == b.page and b.base - a.base > BLANK_GAP * lp:
        return False
    if abs(b.size - a.size) > 0.15 * a.size:
        return False
    if not _is_full(a, right, pitch) or _is_right(a, left, right, pitch) or _is_right(b, left, right, pitch):
        return False
    if len(block.rows) > 1:
        cont = block.rows[1].left
        return abs(b.left - cont) <= 0.5 * pitch
    return abs(b.left - a.left) <= 2.5 * pitch


def _blocks(page_rows, left, right, pitch, lp, height):
    """行を段落にまとめる。表は、表の上端の位置に入れる。"""
    blocks = []
    # 本文の下端：ページの最後の行のうち、いちばん下のもの（どのページも短い文書では、用紙の高さの8割とみる）
    bottom = max([max([r.base for r in rows] + [t[1] for t in tables]) for rows, tables in page_rows
                  if rows or tables] + [0.8 * height])
    prev_row = None
    for k, (rows, tables) in enumerate(page_rows):
        items = [(r.base, r) for r in rows] + [(t[0], t) for t in tables]
        items.sort(key=lambda x: x[0])
        for _, item in items:
            if isinstance(item, tuple):
                blocks.append(Block(TABLE, cells=item[3]))
                prev_row = None
                continue
            r = item
            cur = blocks[-1] if blocks and blocks[-1].kind == TEXT else None
            if cur is not None and prev_row is not None and _continues(cur, r, left, right, pitch, lp):
                if _NUMBER_LIKE_RE.match(same_form(r.text)):
                    blocks.append(Block(TEXT, [r], soft=True))
                else:
                    cur.rows.append(r)
            else:
                blank = 0
                if prev_row is not None and prev_row.page == r.page:
                    gap = r.base - prev_row.base
                    if gap > BLANK_GAP * lp:
                        blank = max(0, round(gap / lp) - 1)
                blocks.append(Block(TEXT, [r], blank=blank))
            prev_row = r
        # ページの下が広くあいていれば、改ページ
        last = max([r.base for r in rows] + [t[1] for t in tables], default=None)
        later = any(rr or tt for rr, tt in page_rows[k + 1:])
        if last is not None and later and bottom - last >= PAGE_BREAK_ROWS * lp:
            blocks.append(Block(PAGE_BREAK))
            prev_row = None
    for b in blocks:
        if b.kind == TEXT:
            _set_align(b, left, right, pitch)
    return blocks


def _set_align(b, left, right, pitch):
    """段落の配置と、1行目の字下げ・左インデント（字数）を決める。"""
    first = b.rows[0]
    if len(b.rows) == 1 and _is_right(first, left, right, pitch):
        b.align = RIGHT
    elif all(_is_center(r, left, right, pitch) for r in b.rows):
        b.align = CENTER
    if len(b.rows) > 1:
        b.indent = max(0.0, (b.rows[1].left - left) / pitch)
        b.first = (first.left - b.rows[1].left) / pitch
    else:
        b.first = max(0.0, (first.left - left) / pitch)


# ---------- マークダウンにする ----------

def _wrap(run, flags):
    stars = ("**" if flags & BOLD else "") + ("*" if flags & DOTS else "")
    high = "==" if flags & HIGHLIGHT else ""
    return stars + high + run + high + stars


def _inline(chars):
    """[(字, 書式)] を、太字を **字**、傍点を *字*、蛍光ペンを ==字== で囲んだ文字列にする（前後の空白は囲まない。
    間の空白は、前後が同じ書式なら囲む）。囲んだ文字列を読み直して字が元に戻らなければ（字の中の * などと重なるとき）、
    その書式は付けない（利用者の字を変えない）。"""
    out, k = [], 0
    while k < len(chars):
        flags = int(chars[k][1])
        if not flags or chars[k][0].isspace():
            out.append(chars[k][0])
            k += 1
            continue
        j = k
        while j < len(chars) and (int(chars[j][1]) == flags or chars[j][0].isspace()):
            j += 1
        while j > k and chars[j - 1][0].isspace():
            j -= 1
        run = "".join(ch for ch, _ in chars[k:j])
        marked = _wrap(run, flags)
        out.append(marked if "*" not in run and split_inline_full(marked).plain == run else run)
        k = j
    line = "".join(out)
    plain = "".join(ch for ch, _ in chars)
    return line if split_inline_full(line).plain == plain else plain


def _spaces(n):
    """字数 n（0.5 刻み）の字下げの空白。"""
    n = round(n * 2) / 2
    return "　" * int(n) + (" " if n - int(n) else "")


def _misread(line):
    """字のままのつもりの行が、組むときに記号として読まれるか（見出し・箇条書き・配置の記号など）。"""
    if not line:
        return False
    lead = split_lead_marks(line)
    return bool(lead.align or lead.left or lead.area or is_line_mark(line) or is_table_line(line)
                or HEADING_MARK_RE.match(line) or LIST_MARK_RE.match(line) or IMAGE_RE.fullmatch(line.strip())
                or AREA_MARK_RE.match(line) or LEFT_INDENT_RE.match(line))


def _cell(s):
    return (s or "").replace("|", "\\|").strip()


def _table_lines(cells):
    n = max(len(r) for r in cells)
    rows = [r + [""] * (n - len(r)) for r in cells]
    out = ["| " + " | ".join(_cell(c) for c in rows[0]) + " |", "|" + "---|" * n]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows[1:]]
    return out


@dataclass
class _Item:
    """マークダウンの1段落分（つなぎ直すため、字のまま持つ）。"""
    lines: list = None          # 字のままの行（表・改ページ・空の行）
    block: Block = None
    chars: list = None
    mark: Mark = None
    lead: str = ""              # 行頭の記号
    free: bool = False          # 見出し・本文として整えない段落か
    index: int = 0              # 段落番号の通し番号
    toc: bool = False           # 目次の記号


def _is_title(b, layout, dt):
    """表題の段落か（最初の見出しより前で、文書の種類の表題の置き方に合うもの）。中央の表題は中央の行、両端揃えの表題
    （公用文・契約書1）は、左右を表題のインデントの字数ずつあけた行。左の表題（技術文書）は、見分けられない。"""
    if dt.title_align == TITLE_CENTER:
        return b.align == CENTER
    if dt.title_align == TITLE_JUSTIFY and b.align == LEFT:
        p, ind = layout.pitch, dt.title_indent
        return (all(abs(r.left - (layout.left + ind * p)) <= 0.5 * p for r in b.rows)
                and all(r.right <= layout.right - (ind - FULL) * p for r in b.rows))
    return False


def _caption(b, blocks, i, o, dt):
    """番号のない見出し（契約書1の「（目的）」。番号の書式が空のレベル）か。括弧で囲んだ1行の段落で、すぐ後の段落が
    1つ下のレベルの見出しになるものを、そのレベルの見出しとする。"""
    text = "".join(ch for ch, _ in b.chars)
    if len(b.rows) != 1 or not re.fullmatch(r"[（(〔【].*[）)〕】]", text):
        return None
    nxt = next((x for x in blocks[i + 1:] if x.kind != PAGE_BREAK), None)
    if nxt is None or nxt.kind != TEXT:
        return None
    for level in range(1, 9):
        if dt.number_formats[level - 1] or not dt.number_formats[level]:
            continue
        mark = Mark(HEADING, level, 0)
        trial = copy.deepcopy(o)
        trial.accept(mark)
        after = trial.classify("".join(ch for ch, _ in nxt.chars))
        if after is not None and after.kind in (HEADING, COMPOSITE) and after.level == level + 1:
            return mark
    return None


def _source_mark(b, text, o):
    """Word の文書から取り込んだ段落の、Word の見出しのレベル・番号による記号。(決めたか, Mark または None)。
    Word の情報のない段落（PDF のすべての段落）は (False, None)：字の先頭の番号から読む。

    ・見出しのレベルがある段落は、そのレベルの見出しにする。Word の自動の番号は、組むときに VA Document が付けるので
      字にしない（2026-11-24 班長指摘）。字の先頭に、組んだときと同じ番号を手で打っていれば、その番号は外す。
    ・見出しのレベルのない段落に Word が振った番号は、番号の字を付けて、全角・半角まで同じ見出しの番号として読めれば
      見出しに（リストの番号で振った契約書の「第１条」など）、読めなければ箇条書き・段落番号にする（「1.」で振った箇条が、
      裁判所提出書類の「１」の見出しにならないように）。
    ・右揃えの段落の後は、VA Document も見出しとして組まないので、記号にしない（document.parse と同じ）。"""
    if not b.level and not b.list_kind:
        return False, None
    if o.stopped:
        return True, None
    if b.level:
        typed = o.classify(text)
        end = typed.end if typed is not None and typed.kind == HEADING and typed.level == b.level else 0
        return True, Mark(HEADING, b.level, end)
    typed = o.classify(b.label + text) if b.label else None
    if typed is not None and typed.kind in (HEADING, COMPOSITE) and typed.exact:
        return True, Mark(typed.kind, typed.level, max(0, typed.end - len(b.label)), True, typed.depth)
    return True, Mark(b.list_kind, 0, 0)


def to_markdown(layout, dt):
    """Layout を、文書の種類 dt の記号でマークダウンにする。(行のリスト, 記号にした数, 全角・半角も同じだった数)。"""
    o = Outliner(dt)
    items, title_done = [], False
    sizes = _heading_sizes(layout) if dt.web else {}
    for i, b in enumerate(layout.blocks):
        if b.kind == PAGE_BREAK:
            items.append(_Item(lines=["<<<"]))
            o.accept(None)
            continue
        if b.kind == TABLE:
            items.append(_Item(lines=_table_lines(b.cells)))
            o.accept(None)
            continue
        for _ in range(b.blank if items else 0):
            items.append(_Item(lines=[""]))
            o.accept(None)
        if b.kind == IMAGE:
            items.append(_Item(lines=[b.line]))
            o.accept(None)
            continue
        chars = b.chars
        text = "".join(ch for ch, _ in chars)
        if _TOC_ENTRY_RE.search(text):
            # 目次の項目（見出しの字・点線・ページ番号）：続いた項目をまとめて、目次の記号 [TOC] にする（組むときに作り直す）
            if not (items and items[-1].toc):
                items.append(_Item(lines=["[TOC]"], toc=True))
            o.accept(None)
            continue
        decided, mark = _source_mark(b, text, o)
        if not decided:
            mark = o.classify(text) if not dt.web else _size_heading(b, sizes, o)
            if (mark is None and items and items[-1].lines == ["<<<"] and o.seen and not dt.web):
                # 改ページの後で、見出しの番号が振り直されていれば、セクション区切り
                fresh = Outliner(dt)
                again = fresh.classify(text)
                if again is not None and again.kind in (HEADING, COMPOSITE):
                    items[-1].lines = ["<<<="]
                    o.section_break()
                    mark = o.classify(text)
            if b.soft and mark is None and items and items[-1].block is not None:
                # 番号らしいもので始まるので分けた行が、番号ではなかった：前の段落の続きに戻す
                prev = items[-1]
                prev.chars = _join_rows(prev.block.rows + b.rows)
                prev.block = replace(prev.block, rows=prev.block.rows + b.rows)
                continue
            if mark is None and not o.stopped and not dt.web:
                mark = _caption(b, layout.blocks, i, o, dt)
        lead = ""
        if mark is None:
            if not title_done and not o.seen and _is_title(b, layout, dt):
                lead, title_done = ":=: ", True
            elif b.align == CENTER:
                lead = ":-: "
            elif b.align == RIGHT:
                lead = "--: "
        items.append(_Item(block=b, chars=chars, mark=mark, lead=lead, free=o.free, index=o.prev_number + 1))
        o.accept(mark, align_right=mark is None and b.align == RIGHT)
    lines, marks, exact = [], 0, 0
    for it in items:
        if it.lines is not None:
            lines += it.lines
            continue
        marks += it.mark is not None
        exact += it.mark is not None and it.mark.exact
        lines += _render(it)
    return lines, marks, exact


def _render(it):
    """段落を、マークダウンの行にする。"""
    m, chars = it.mark, it.chars
    if m is not None:
        rest = _inline(chars[m.end:])
        if m.kind == HEADING:
            return ["#" * m.level + " " + rest]
        if m.kind == COMPOSITE:
            # 複合見出し：字のない見出しの行を外側のレベルから並べ、最後のレベルの行に字を書く
            last = m.level + m.depth - 1
            return ["#" * level for level in range(m.level, last)] + ["#" * last + " " + rest]
        return [("- " if m.kind == BULLET else f"{it.index}. ") + rest]
    body = _inline(chars)
    b = it.block
    left, spaces = "", ""
    if it.free and not it.lead:
        # 見出し・本文として整えない段落は、字下げ（行頭の全角空白）・左インデント（->N）を記号で戻す
        if len(b.rows) > 1 and round(b.indent) >= 1:
            left, spaces = f"->{round(b.indent)} ", _spaces(max(0.0, b.first))
        else:
            spaces = _spaces(max(0.0, b.first if len(b.rows) == 1 else b.first + b.indent))
    if not left and _misread(body):
        # 字のまま組むために、左インデントの記号を付ける（->N の段落は、見出し・箇条書きなどにしない）
        left = f"->{max(0, round(b.indent))} "
    return [it.lead + left + spaces + body]


def _heading_sizes(layout):
    """ウェブ文書：本文より大きい字の大きさを、大きい順にレベル 1, 2, … にする。"""
    big = sorted({round(b.size, 1) for b in layout.blocks if b.kind == TEXT and b.size >= 1.1 * layout.body_size},
                 reverse=True)
    return {s: k + 1 for k, s in enumerate(big[:9])}


def _size_heading(b, sizes, o):
    """ウェブ文書：字の大きい段落（3行まで）を見出しにする。でなければ、箇条書き・段落番号を読む。"""
    level = sizes.get(round(b.size, 1))
    if level and len(b.rows) <= 3 and not o.stopped:
        return Mark(HEADING, level, 0)
    text = "".join(ch for ch, _ in b.chars)
    return o.classify(text)


# ---------- 文書の種類を選び、変換する ----------

def _geometry_types(layout):
    """用紙・余白・1行の字数が合う文書の種類（VA Document で作った PDF）。"""
    w, h = layout.page_size
    if abs(w - A4[0]) > 2 or abs(h - A4[1]) > 2:
        return []
    found = []
    # 本文の右端は、最後の字の右端（字の送りが字の幅より広ければ、そのぶん余白の端より左）なので、送りの余りを足す
    right = layout.right + max(0.0, layout.pitch - layout.body_size)
    for key, dt in DOC_TYPES.items():
        top, bottom, ml, mr = dt.margins
        if abs(layout.left - ml * MM) > MARGIN_MATCH or abs(right - (w - mr * MM)) > MARGIN_MATCH:
            continue
        if abs((right - layout.left) / layout.pitch - dt.chars_lines[0]) > 0.6:
            continue
        found.append(key)
    return found


def convert(path, settings):
    """PDF を読み、マークダウンにする。settings は今の文書の設定（vamd.Settings。文書の種類が決めきれないときに使う）。
    字が1つもなければ None。"""
    layout = read_layout(path)
    if layout is None:
        return None
    # 用紙・余白の合う種類がなければ（ほかのソフトで作った PDF）、すべての種類で試す。ただし、ウェブ文書は、今の設定が
    # ウェブ文書のときだけ（字の大きい表題だけで、ウェブ文書が選ばれないように）
    keys = _geometry_types(layout) or [k for k in DOC_TYPES if k != WEB or settings.doc_type == WEB]
    best = None
    for key in keys:
        lines, marks, exact = to_markdown(layout, doc_type_for(key, settings.one_width))
        score = (marks, key == settings.doc_type, exact)
        if best is None or score > best[0]:
            best = (score, key, lines)
    (marks, _, _), key, lines = best
    new = replace(settings, doc_type=key, page_number=layout.page_number, line_numbers=layout.line_numbers)
    text = "\n".join(lines).strip("\n")
    return Converted(text, new.normalized(), marks, layout.images)
