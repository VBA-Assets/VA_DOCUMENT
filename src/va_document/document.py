"""マークダウンを段落に分け、見出し・段落番号に番号を付ける（仕様.md の5）。

対応する書き方（VA公用文の ai-prompt.md と同じ形に、配置などの記号を足したもの）
・見出し：行頭の `#`〜`#########`＋半角空白。階層は `#` の数。
・複合見出し：字のない見出しの行（`#` だけ、または `# ` だけ）のすぐ後に見出しが続くと、2つを1行にまとめる
  （「１(1) 当事者」。VA疑似アウトラインの複合見出しと同じ。2026-10-24 班長指示）。番号を続けて並べ（外側の番号の後の
  全角空白を除く。「第」の番号は空白を残す。［番号1字］の文書では、番号を全角1字の幅に縮め、後ろの空白を
  除く。2026-10-26）、1行目は外側の見出しの位置から書き出し、折り返した行は、まとめた段の数だけ外側の見出しより
  右から始める。目次には、外側の段の1項目として載せる。左インデントの増加量（left_add）が1字でない文書の種類では、まとめない（VA疑似アウトラインと同じ）。
・箇条書き：`- `。段落番号：`1. `（連番。① ② … にする）。
  記号の後に半角空白があるときだけ見出し・箇条書き・段落番号とする（2026-10-23 班長決定。VA公用文は空白が
  なくても記号とみなすが、「-1度」「2026.10.23」で始まる段落の字が消えるので、安全側にした）。
・記号の形（2026-10-25 班長決定）：もとは `{右}` `{字下}` のような波かっこの語の記号だったが、マークダウンの表の
  区切りの行（`:---:` `---:`）にならい、記号で表す形に改めた。Ver120 までの古い形は読まない（2026-10-25 班長決定）。行頭の記号は、見出しの `# ` と同じく、
  後ろに半角空白があるときだけ記号とする（行末なら空白はなくてよい）。
・配置の記号：行頭の `:=: `（表題）、`:-: `（中央）、`--: `（右）、`:-- `（左）。コロンのある側に寄せる（表の区切りの行と
  同じ）。`=` は表の2重線と同じく「強い」意味で、表題に使う。
・字下げ：行頭（行頭の記号の後ろでもよい）の空白を、1行目の字下げ（Word の「最初の行のみ1字下げ」。全角1つで1字、
  半角1つで半字）として読む（VA公用文 ReplaceSpaceWithIndent と同じ。PDF には空白の字ではなく段落の字下げとして組む）。
  効くのは、見出し・本文として整えない段落（最初の見出しより前、右揃えの段落の後、->N の段落、ヘッダー・フッター）だけ。
  2026-10-28 班長決定で、それまでの `-> `（2026-10-23〜。見出しの後に使うと、その段落から先の変換を止めた）をなくした
  （一般のマークダウンでも字下げに見えるようにするため。前の版の `-> ` は読み替えず、字として残す）。
・`->2 `：行頭（配置の記号の後）に書くと、その段落の左インデントを全角2字にする（数字は 0〜99）。マークダウンの記号と
  同じく、矢印・数字とも半角だけを記号とする（2026-10-28 班長決定。それまでの `+2 `〔2026-10-24 班長指示。全角の＋・
  数字も受け付け、「+81 3-1234-5678」のような電話番号を除いていた〕は読まない）。見出しの段に合わせた自動のインデントは
  付けず、見出し・箇条書き・段落番号の変換もしない（VA公用文の「行間詰め」と同じく、インデントの自動調節の対象外。
  2026-10-24 班長指示）。記号の後ろに全角空白を書くと（`->2 　本文`）、1行目をさらに1字下げる。
・`[HEADER] ` `[FOOTER] `：行頭に書くと、その段落を本文から外し、ヘッダー（上の余白。ページ番号の直下）・フッター（下の
  余白。ページ番号の直上）に組む（2026-10-25 班長指示。記号の形は班長決定。[TOC] と同じく角かっこの英語。小文字でもよい）。
  配置の記号・->N と一緒に使える（順は問わない。ボタンで付けるときは `[HEADER] --: 文字` の順）。ヘッダーは、その
  行を書いたセクションの最初のページ（文書の最初のページ、セクション区切りの直後のページ）だけ、フッターはセクションの
  全ページに出す（「別紙」「付紙」などをヘッダーに書く使い方のため。2026-10-25 班長指示）。本文の行を使わず、見出し・番号・インデントの変換をせず、「最初の見出しを
  過ぎたか」「右揃えの段落を過ぎたか」も変えない。組み方は layout.py。
・`<<<`：その行だけを書いた行で、ページを改める（見出しの番号は続く。AsciiDoc の改ページの記号と同じ）。
・`[TOC]`：その行だけを書いた行に、見出しの3段目までの目次を組む（layout.py。2026-10-24 班長指示。Python-Markdown・
  Typora などの目次の記号と同じ。小文字でもよい）。`[TOC:2]` のように段（1〜9）を書き添えると、その段までを載せる
  （2026-10-24 班長指示。コロン・数字は全角でもよい）。
・`<<<=`：セクション区切り。VA公用文のセクション区切りと同じ。ページを改め、見出しの番号を振り直し、
  「最初の見出しを過ぎたか」「右揃えの段落を過ぎたか」「最初の階層」を初めに戻す（2026-10-23 班長決定）。
・太字：`**文字**`（同じ行の中で対になったもの。記号の直後・直前が空白のものは除く）。記号を除いた字を太字の範囲とし、
  ＭＳ ゴシックで描く（VA公用文シリーズの VAスタイルの「太字」と同じ。字の幅が変わらない。2026-10-24 班長指示）。
  表のセルの中でも使える。目次の項目には太字を付けない。「**# 見出し**」「**:=: 準備書面**」のように行全体を囲んだものは、
  行頭の記号（配置の記号・見出し・箇条書き・段落番号）や字下げの空白の後に記号を移して読む（「# **見出し**」。その行だけの記号
  「**<<<**」なども記号とする。2026-10-24 班長指示）。`__` `_` の強調は、整形（cleanup.py）で取り除く（`*` は傍点の記号）。
・傍点：`*文字*`（マークダウンの「強調」。日本語の組版では強調を傍点で表す。2026-10-24 班長決定）。記号を除いた字の上の
  中央に黒丸を付ける（VAスタイルの傍点の既定「黒丸」〔Word の EmphasisMark＝OverSolidCircle〕と同じ形）。黒丸は行の間に
  置き、字の位置・改行・改ページは変えない。太字と重ねると `***文字***`（太字の記号を先に読み、残った * を傍点とする）。
  記号の内側が空白で始まる（終わる）もの、* の外側に英数字が続くもの（「2*3*4」など）は記号とみなさない。表のセルでも
  使える。見出し・段落番号の番号には付けない。目次の項目には付けない。VA公用文は *文字* の * を取り除く（字は残る）。
・均等割付：`[原告]{5}`（同じ行の中で、角かっこで挟んだ字。波かっこに字数〔全角。0〜99。全角の数字でもよい〕を書く。
  2026-10-24 班長指示。Pandoc の [字]{属性} と同じ形。2026-10-25 班長決定）。挟まれた字を、
  1字目を左端、最後の字を字数の右端に置いて、字の間を均等に空ける（Word の均等割り付けと同じ）。表のセルでも使える。
・画像：`[IMAGE 1]{30}`（その行だけ。行頭の配置の記号の後ろでもよい）。1 は画像の番号（1〜999）、30 は幅の字数（1〜99。
  均等割付と同じ読み方で「画像1 を30字の幅に」。省くと置ける幅いっぱい）。画像のデータは構文ファイルに書かず、PDF の中に
  だけ持つ（2026-10-29 班長決定。検討_画像の挿入.md）。`:-: ` は中央、`--: ` は右に置いて続く本文を左側に回り込ませる。記号の
  ないものは表と同じく本文の左インデントにそろえる。大文字・小文字は問わない。同じ行に字があるもの、ヘッダー・フッターの
  行のものは画像とせず、字として読む（均等割付の字になる）。見出しの番号・「最初の見出しを過ぎたか」「右揃えの段落を
  過ぎたか」は変えない。組み方は layout.py。
・空の行：Word（VA公用文）の空の段落と同じく、1行分あける（2026-10-23 班長決定。もとは空の行を段落の区切りとして
  読み飛ばし、1行あけるには `{空行}` を書いていたが、VA公用文との互換のため改めた）。
・中身のない配置の行（`--:` だけの行など）も、Word と同じく1行分あける。右揃えなら、そこから先は変換しない。
・行頭の空白は取り除き、段落の書き出しのインデント（全角1つで1字、半角1つで半字）にする（VA公用文
  clsPreFormatter.ReplaceSpaceWithIndent と同じ）。効くのは、見出し・本文として整えない段落（最初の見出しより前、
  右揃えの段落の後）だけ。見出し・本文・リストは、VA公用文と同じくインデントを付け直す。
・最初の見出し（または箇条書き・段落番号）より前の行は、見出しの番号やインデントを付けない（VA公用文の
  blnSkipUntil）。最初の見出しを過ぎた後に右揃えの段落（「以上」など）が来たら、次のセクション区切りまで、
  見出し・箇条書きの記号を変換せず、インデントも付け直さない（VA公用文の blnStopAfter。2026-10-23 班長決定）。

記号の読み取り方（正規表現・記号の一覧）は、このモジュールにまとめる。エディターの色付け・ボタン（editor_ops.py）、
AI の回答の確かめ（vamd.py）、確認表示との連動（textmap.py）も、ここの定義を使う（2026-10-24 のリファクタリング。
組む側とエディターの側で記号の扱いが食い違わないように）。
"""
import bisect
import re
from dataclasses import dataclass, field
from typing import NamedTuple

from .doctypes import number_text

# 段落の種類
HEADING, BODY, BULLET, NUMBER = "heading", "body", "bullet", "number"
PAGE_BREAK, SECTION_BREAK, BLANK, TABLE = "pagebreak", "section", "blank", "table"
TOC = "toc"                 # 目次（[TOC] だけの行）
IMAGE = "image"             # 画像（[IMAGE 1]{30} の行）
# 配置
JUSTIFY, CENTER, RIGHT, TITLE = "justify", "center", "right", "title"

# 行頭の記号は、後ろの半角の空白までを記号とする（行末なら空白はなくてよい。lead_mark_len）
ALIGN_MARKS = {":=: ": TITLE, ":-: ": CENTER, "--: ": RIGHT, ":-- ": JUSTIFY}    # 行頭の配置の記号
TITLE_MARK, CENTER_MARK, RIGHT_MARK = ":=: ", ":-: ", "--: "
# ->2（左インデントの字数）。マークダウンの記号と同じく、半角の矢印・数字だけを記号とする（後ろに半角空白。行末なら
# 空白はなくてよい。2026-10-28 班長決定）
LEFT_INDENT_RE = re.compile(r"->([0-9]{1,2})(?: |$)")
LEFT_INDENT_MARK = "->1 "   # ［インデント］で付ける記号
# ヘッダー・フッター（Para.area）。行頭の [HEADER] [FOOTER]（小文字でもよい。後ろに半角空白。行末なら空白はなくてよい）
HEADER, FOOTER = "header", "footer"
HEADER_MARK, FOOTER_MARK = "[HEADER] ", "[FOOTER] "
AREA_MARK_RE = re.compile(r"\[(header|footer)\](?: |$)", re.I)
PAGE_BREAK_MARK, SECTION_BREAK_MARK = "<<<", "<<<="
_LINE_MARKS = {PAGE_BREAK_MARK: PAGE_BREAK, SECTION_BREAK_MARK: SECTION_BREAK}
TOC_LEVELS = 3              # 目次に載せる見出しの段の既定（Word の「自動作成の目次 1」と同じ）
_TOC_RE = re.compile(r"\[(?i:toc)(?:[:：]([1-9１-９]))?\]")
TOC_MARK = "[TOC:3]"        # ［目次］で入れる記号
# 見出しの記号。字のない見出し（「#」だけの行。複合見出しの外側の段）も含む
# 画像（[IMAGE 1]{30}。2026-10-29 班長決定）。group(1) が番号、group(2) が幅の字数（省いたら None）。半角だけを記号とする
IMAGE_RE = re.compile(r"\[(?i:image) ([1-9][0-9]{0,2})\](?:\{([1-9][0-9]?)\})?")
IMAGE_MAX = 999
HEADING_MARK_RE = re.compile(r"(#{1,9})(?: |[ 　]*$)")
_NUMBERED_RE = re.compile(r"(\d+)\. ")
LIST_MARK_RE = re.compile(r"- |\d+\. ")       # 箇条書き・段落番号の記号
# ［見出し］［箇条書き］［段落番号］で付ける記号（見出しのレベルは、エディターで # の数を直す。2026-10-25 班長指示）
HEADING_BUTTON_MARK, BULLET_MARK, NUMBER_MARK = "## ", "- ", "1. "
_BOLD_RE = re.compile(r"\*\*(?! )([^*\n]+?)(?<! )\*\*")
# 蛍光ペン。= が3つ以上続く所（表の区切りの行 |===|===| の「==|==」など）は記号とみなさない（2026-10-24）
_HIGHLIGHT_RE = re.compile(r"(?<!=)==(?![ =])([^=\n]+?)(?<! )==(?!=)")
# 傍点（*文字*）。太字の記号を伏せた文字列で読む（_wrap_spans）。外側に英数字が続くもの（2*3*4）は記号とみなさない
_DOT_RE = re.compile(r"(?<![*0-9A-Za-z])\*(?![ *])([^*\n]+?)(?<![ *])\*(?![*0-9A-Za-z])")
# 字を囲む記号（太字・蛍光ペン・傍点）。長いものから並べる（「***」の先頭は ** とみなす）
_WRAPS = {"**": _BOLD_RE, "==": _HIGHLIGHT_RE, "*": _DOT_RE}
WRAP_MARKS = tuple(_WRAPS)
# 均等割付（[原告]{5}）。角かっこで挟んだ字を、波かっこの字数の幅に割り付ける（Pandoc の [字]{属性} と同じ形）
DISTRIBUTE_OPEN = "["
DISTRIBUTE_CLOSE_RE = re.compile(r"\]\{([0-9０-９]{1,2})\}")
DISTRIBUTE_RE = re.compile(r"\[([^\[\]\n]+?)" + DISTRIBUTE_CLOSE_RE.pattern)     # group(1) が字、group(2) が字数


def lead_mark_len(s, mark, k=0):
    """s の k 字目に行頭の記号 mark（後ろの半角の空白を含む）があれば、その字数（行末なら空白はなくてよい）。
    なければ 0。"""
    if s.startswith(mark, k):
        return len(mark)
    return len(mark) - 1 if s[k:] == mark[:-1] else 0


class Inline(NamedTuple):
    """字を囲む記号を除いた結果。位置は、記号を除いた文字列の何字目か。"""
    plain: str              # 記号を除いた文字列
    bold: frozenset         # 太字の字の位置
    highlight: frozenset    # 蛍光ペンの字の位置
    dots: frozenset         # 傍点の字の位置
    distribute: tuple       # 均等割付 ((始め, 終わり, 字数), ...)
    cols: list              # 各字の元の文字列での位置（＋末尾）


def leading_wrap(s):
    """s の先頭の、字を囲む記号（** == *）。なければ None（「***」の先頭は ** とみなす）。"""
    return next((w for w in WRAP_MARKS if s.startswith(w)), None)


def _wrap_spans(s):
    """字を囲む記号（太字・蛍光ペン・傍点）の [(記号, 始め, 中の字の始め, 中の字の終わり, 終わり)]。
    太字を先に読み、太字の記号を伏せてから傍点（*）を読む（「***語***」は太字と傍点。傍点の中の字から太字の記号を除く）。"""
    out = [(w, m.start(), m.start(1), m.end(1), m.end()) for w in ("**", "==") for m in _WRAPS[w].finditer(s)]
    masked = list(s)
    for w, a, _, _, e in out:
        if w == "**":
            masked[a:a + 2] = "\0\0"
            masked[e - 2:e] = "\0\0"
    masked = "".join(masked)
    for m in _DOT_RE.finditer(masked):
        a, b = m.start(1), m.end(1)
        while a < b and masked[a] == "\0":
            a += 1
        while b > a and masked[b - 1] == "\0":
            b -= 1
        out.append(("*", m.start(), a, b, m.end()))
    return out


def split_inline(s):
    """字を囲む記号（**文字** の太字、==文字== の蛍光ペン、*文字* の傍点、[文字]{N} の均等割付）を除く。
    (記号を除いた文字列, 太字の字の位置の集合, 蛍光ペンの字の位置の集合, 各字の s での位置のリスト＋末尾) を返す。
    重ねてよい（**==文字==**）。傍点・均等割付も要るときは split_inline_full を使う。"""
    r = split_inline_full(s)
    return r.plain, r.bold, r.highlight, r.cols


def split_inline_full(s):
    """字を囲む記号を除き、Inline（太字・蛍光ペン・傍点の字の位置、均等割付の範囲を含む）を返す。"""
    marker, inside = set(), {w: set() for w in _WRAPS}
    for w, a, ia, ib, e in _wrap_spans(s):
        marker.update(range(a, a + len(w)))
        marker.update(range(e - len(w), e))
        inside[w].update(range(ia, ib))
    spans = []
    for m in DISTRIBUTE_RE.finditer(s):
        marker.update(range(m.start(), m.start(1)))
        marker.update(range(m.end(1), m.end()))
        spans.append((m.start(1), m.end(1), int(m.group(2))))      # int は全角の数字も読む
    plain, cols, index_of = [], [], {}
    found = {w: set() for w in _WRAPS}
    for k, ch in enumerate(s):
        if k in marker:
            continue
        index_of[k] = len(plain)
        for w in _WRAPS:
            if k in inside[w]:
                found[w].add(len(plain))
        plain.append(ch)
        cols.append(k)
    cols.append(len(s))
    distribute = tuple((index_of[a], index_of[b - 1] + 1, n) for a, b, n in spans
                       if a in index_of and b - 1 in index_of)
    return Inline("".join(plain), frozenset(found["**"]), frozenset(found["=="]), frozenset(found["*"]), distribute, cols)


def remove_bold(s):
    """太字の記号（**）だけを除く（蛍光ペンの記号は残す）。"""
    return _BOLD_RE.sub(lambda m: m.group(1), s)


def move_wraps_after_marks(line, lists=True):
    """「**:=: 準備書面**」「**# 見出し**」「==# 見出し==」のように、行（セル）全体を囲む太字・蛍光ペンの記号が、
    行頭の記号（配置の記号・見出し・箇条書き・段落番号）や字下げの空白の前にあるときは、記号・空白の後に移す
    （「:=: **準備書面**」「# **見出し**」「　**本文**」）。AI は行を丸ごと太字にすることがあり、VA公用文は ** を取り除いて記号として読むので、同じく記号と
    する（2026-10-24 班長指示）。字の数は変わらない。lists が偽なら（右揃えの段落の後など）、見出し・箇条書き・
    段落番号の記号は移さない。->N・[HEADER] の後の見出しなどの記号も移さない（その段落は見出しにしないため）。
    「**==…==**」のように重ねたものは、内側から移す。"""
    wrap = leading_wrap(line)
    if wrap is None:
        return line
    rest = move_wraps_after_marks(line[len(wrap):], lists)
    lead = split_lead_marks(rest)
    k = len(rest) - len(lead.rest.lstrip(" 　"))       # 記号の後ろの字下げの空白の後に移す
    if lead.left or lead.area:
        lists = False
    if lists:
        m = HEADING_MARK_RE.match(rest, k) or LIST_MARK_RE.match(rest, k)
        if m:
            k = m.end()
    if k == 0:
        return line
    moved = rest[:k] + wrap + rest[k:]
    return moved if _WRAPS[wrap].match(moved, k) else line


def inline_mark_spans(s):
    """行の中の、字を囲む記号の位置 [(始め, 終わり)]と、太字・蛍光ペン・傍点の字の範囲（エディターの色付けに使う）。"""
    marks, inner = [], {w: [] for w in _WRAPS}
    for w, a, ia, ib, e in _wrap_spans(s):
        marks += [(a, a + len(w)), (e - len(w), e)]
        inner[w].append((ia, ib))
    for m in DISTRIBUTE_RE.finditer(s):
        marks += [(m.start(), m.start(1)), (m.end(1), m.end())]
    return marks, inner["**"], inner["=="], inner["*"]


def has_inline_marks(s):
    """字を囲む記号（太字・蛍光ペン・傍点・均等割付）がありそうか（ない行を早く飛ばすため）。"""
    return "*" in s or "==" in s or "]{" in s


def _outer_number(number, one_width=False):
    """複合見出しで、次の段の番号の前に付ける外側の番号。後ろの全角空白を1つ取り除く（「１　」→「１」。VA疑似アウトラインの
    ProcessCompositeHeadings と同じ。2026-10-26 班長指摘）。半角空白（「(3) 」）は残す。「第」で始まる番号は、「第１１」と
    読めないよう空白を残す（「第１　１　当事者」。2026-10-26 班長決定）。見出し番号を1字の幅に縮める文書では、どの番号も
    （「第１」も）1字に縮めて、後ろの空白を取り除く（上下の字をそろえるため。2026-10-26 班長指示）。"""
    if one_width:
        return number.rstrip(" 　")
    if number.startswith("第") or not number.endswith("　"):
        return number
    return number[:-1]


def _composite_parts(paras, pi):
    """見出しの番号を、外側の段から順に並べたもの（複合見出しでなければ、その見出しの番号だけ）と、外側の見出し。"""
    p = paras[pi]
    parts, outer = [p.number], p
    j = pi - 1
    while j >= 0 and paras[j].composite:
        parts.insert(0, _outer_number(paras[j].number, p.one_width))
        outer = paras[j]
        j -= 1
    return parts, outer


def heading_label(paras, pi):
    """見出しの (段, 番号, まとめた段の数, 外側の見出し)。複合見出し（字のない見出しの行のすぐ後の見出し）は、前の字の
    ない見出しの番号を前に付け（_outer_number）、段は外側（いちばん前）の見出しの段にする。"""
    parts, outer = _composite_parts(paras, pi)
    return outer.level, "".join(parts), len(parts) - 1, outer


def squeezed_numbers(paras, pi):
    """見出しの番号（heading_label の番号）のうち、全角1字の幅に縮めて描く番号の (始め, 終わり)。縮めるのは、見出し番号を
    1字の幅に縮める文書（Para.one_width。［番号1字］。2026-10-26 班長指示）の見出しだけで、まとめない見出しも複合見出しも、
    段ごとの番号を縮める。［番号1字］を付けない文書では、複合見出しでも縮めない（VA公用文と同じ幅。Ver152 は複合見出しの
    括弧の番号だけを縮めたが、上下でそろわないので取りやめた。2026-10-26 班長指示）。"""
    if not paras[pi].one_width:
        return []
    parts, _ = _composite_parts(paras, pi)
    spans, end = [], 0
    for part in parts:
        core = part.rstrip(" 　")
        if core:
            spans.append((end, end + len(core)))
        end += len(part)
    return spans


def line_mark(s):
    """その行だけを書く記号（<<< <<<= [TOC] [TOC:2]）なら (段落の種類, 目次の段)、
    そうでなければ (None, 0)。s は前後の空白を除いた行。"""
    wrap = leading_wrap(s)
    while wrap and len(s) > 2 * len(wrap) and s.endswith(wrap):
        # 太字・蛍光ペン・傍点の記号で囲んだもの（**<<<**）も記号とする（2026-10-24 班長指示）
        s = s[len(wrap):-len(wrap)]
        wrap = leading_wrap(s)
    if s in _LINE_MARKS:
        return _LINE_MARKS[s], 0
    m = _TOC_RE.fullmatch(s)
    if m:
        return TOC, int(m.group(1)) if m.group(1) else TOC_LEVELS     # int は全角の数字も読む
    return None, 0


def is_line_mark(line):
    """その行だけを書く記号（<<< <<<= [TOC] [TOC:2] など）の行か。"""
    return line_mark(line.strip())[0] is not None


@dataclass
class Para:
    """1つの段落。"""
    text: str
    kind: str = BODY
    level: int = 0          # 見出しの階層（1〜9）。見出しでなければ 0
    body_level: int = 0     # 本文・リストが属する見出しの階層（0：見出し・本文として整えない段落）
    number: str = ""        # 見出し・段落番号の番号（例：「第１　」「①　」「・」）
    number_index: int = 0   # 段落番号の通し番号（1 から）
    align: str = JUSTIFY
    first_indent: float = 0.0  # 行頭の空白から変換した、書き出しのインデント（字）
    left_indent: int = None    # ->N の左インデント（字）。None なら自動（見出しの段に合わせる）
    table: object = None       # 表のとき Table
    follows: object = None     # 表の左端をそろえる直前の段落（箇条書き・段落番号・->N。Para）。なければ None
    # 元の行（parse に渡した行の番号）と、本文の1字目がその行の何字目か（確認表示とエディターの連動に使う）。
    # 表は src_line〜src_end の行
    src_line: int = -1
    src_col: int = 0
    src_end: int = -1
    bold: frozenset = frozenset()   # 太字の字の位置（本文の何字目か。番号は含まない）
    highlight: frozenset = frozenset()  # 蛍光ペンの字の位置（確認表示だけで黄色に塗る）
    dots: frozenset = frozenset()   # 傍点の字の位置（本文の何字目か。番号には付けない）
    distribute: tuple = ()          # 均等割付 ((始め, 終わり, 字数), ...)（本文の何字目か。番号は含まない）
    src_cols: list = None           # 本文の各字が元の行の何字目か（＋末尾）。太字の記号を除いたので、src_col からの通しではない
    composite: bool = False         # 字のない見出しで、次の見出しと1行にまとめるもの（複合見出しの外側の段）
    area: str = None                # ヘッダー・フッターの段落なら HEADER・FOOTER（本文の行を使わない）
    one_width: bool = False         # 見出し番号を全角1字の幅に縮める文書の見出しか（doctypes.one_width_type）
    image: tuple = None             # 画像の段落なら (番号, 幅の字数〔省いたら None〕)

    def text_index(self, col):
        """元の行の col 字目 → 本文の何字目か。"""
        if self.src_cols is None:
            return max(0, col - self.src_col)
        return min(bisect.bisect_left(self.src_cols, col), len(self.text))

    def source_col(self, k):
        """本文の k 字目 → 元の行の何字目か。"""
        if self.src_cols is None:
            return self.src_col + max(0, k)
        return self.src_cols[max(0, min(k, len(self.src_cols) - 1))]


@dataclass
class Table:
    """マークダウンの表（仕様.md の5.3）。"""
    header: list            # 見出しの行のセル [(配置, 文字列)]
    rows: list              # それ以外の行 [[(配置, 文字列), ...], ...]
    double_rule: bool       # 見出しの行の下を2重線にするか（区切りの行が = のとき）
    bold: dict = field(default_factory=dict)    # (表の何行目〔0 が見出しの行〕, 何列目) → 太字の字の位置の集合
    highlight: dict = field(default_factory=dict)   # 同じく、蛍光ペンの字の位置の集合
    dots: dict = field(default_factory=dict)        # 同じく、傍点の字の位置の集合
    distribute: dict = field(default_factory=dict)  # 同じく、均等割付の範囲 ((始め, 終わり, 字数), ...)
    widths: list = field(default_factory=list)      # 列ごとの幅の字数（区切りの行の {字数}。指定のない列は None）


# 表の区切りの行（|---|:===:| など。列の後ろの {8} は、列の幅の字数。2026-11-01 班長決定）
_TABLE_SEP_CELL_RE = re.compile(r"^\s*(:?)([-=])\2*(:?)(?:\{([1-9１-９][0-9０-９]?)\})?\s*$")
SEP_COLUMN_RE = re.compile(r"(:?[-=]+:?)(?:\{[^{}]*\})?")     # 区切りの行の1列分。group(1) が線と配置の : の部分
_LEFT = "left"
CELL_ALIGNS = {":-- ": _LEFT, ":-: ": CENTER, "--: ": RIGHT}     # セルの先頭の配置の記号（行頭の記号と同じ形）
# セルの先頭の配置の記号（太字・蛍光ペンの記号の内側にあってもよい）。group(1) が前の囲む記号、group(2) が配置の記号
# （後ろの半角の空白を含む。セルの終わりなら空白はなくてよい）
CELL_ALIGN_RE = re.compile("((?:" + "|".join(map(re.escape, WRAP_MARKS)) + ")*)((?:"
                           + "|".join(re.escape(m.strip()) for m in CELL_ALIGNS) + ")(?: |$))")


def cell_separators(line):
    """表の行の、区切りの「|」の位置（「\\|」は区切りではない）。"""
    return [k for k, ch in enumerate(line) if ch == "|" and not (k and line[k - 1] == "\\")]


def split_cells(line):
    """表の行をセルの文字列のリストにする（前後の | を除く。\\| は | として扱う）。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, cur, i = [], "", 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur += "|"
            i += 2
            continue
        if s[i] == "|":
            cells.append(cur.strip())
            cur = ""
        else:
            cur += s[i]
        i += 1
    cells.append(cur.strip())
    return cells


def is_table_line(line):
    """表の行（| で始まる行）か。"""
    return line.lstrip().startswith("|")


def parse_separator(line):
    """表の区切りの行なら、(列ごとの配置のリスト, 2重線か) を返す。そうでなければ None。"""
    if "|" not in line:
        return None
    cells = split_cells(line)
    aligns, kinds = [], set()
    for c in cells:
        m = _TABLE_SEP_CELL_RE.match(c)
        if not m:
            return None
        left, kind, right, _ = m.groups()
        kinds.add(kind)
        aligns.append(CENTER if left and right else RIGHT if right else _LEFT)
    # 1つの列でも = を使っていれば2重線にする（AI が一部の列だけ = にした場合も、利用者の意図を活かす）
    return aligns, "=" in kinds


def separator_widths(line):
    """表の区切りの行の、列ごとの幅の字数のリスト（指定のない列は None）。"""
    found = [_TABLE_SEP_CELL_RE.match(c).group(4) for c in split_cells(line)]
    return [int(c) if c else None for c in found]


def with_column_widths(line, chars):
    """表の区切りの行の {字数} を、chars（列ごとの字数。足りない列・None は指定なし）に書き換えた行を返す。"""
    rest = iter(chars)

    def put(m):
        n = next(rest, None)
        return m.group(1) + (f"{{{n}}}" if n else "")
    return SEP_COLUMN_RE.sub(put, line)


def _cell(text, default_align):
    """セルの文字列から、先頭の配置の記号を読み取る。記号がなければ列の配置にする。
    「**--: 金額**」のように太字の記号で囲んだものも、配置の記号として読む（2026-10-24 班長指示）。"""
    text = move_wraps_after_marks(text, lists=False)
    for mark, align in CELL_ALIGNS.items():
        if lead_mark_len(text, mark):
            return align, text[lead_mark_len(text, mark):].strip()
    return default_align, text


def cell_align_mark(text):
    """セルの文字列の先頭の配置の記号（後ろの空白を含む形）。なければ ""。"""
    text = move_wraps_after_marks(text.strip(), lists=False)
    return next((mark for mark in CELL_ALIGNS if lead_mark_len(text, mark)), "")


def parse_table(lines):
    """表の行（見出しの行・区切りの行・それ以外の行）から Table を作る。表でなければ None。"""
    if len(lines) < 2:
        return None
    sep = parse_separator(lines[1])
    if sep is None:
        return None
    aligns, double = sep
    head = split_cells(lines[0])
    n = max(len(head), len(aligns))
    aligns = aligns + [_LEFT] * (n - len(aligns))
    widths = separator_widths(lines[1])
    def row(cells):
        cells = cells + [""] * (n - len(cells))
        return [_cell(c, aligns[k]) for k, c in enumerate(cells[:n])]
    table = Table(row(head), [row(split_cells(l)) for l in lines[2:]], double,
                  widths=widths + [None] * (n - len(widths)))
    # セルの太字・蛍光ペンの記号を除き、字の位置を覚える
    for r, cells in enumerate([table.header] + table.rows):
        for c, (align, text) in enumerate(cells):
            found = split_inline_full(text)
            cells[c] = (align, found.plain)
            for name in ("bold", "highlight", "dots", "distribute"):
                if getattr(found, name):
                    getattr(table, name)[(r, c)] = getattr(found, name)
    return table


def left_indent_of(mark):
    """->N の記号（split_lead_marks が返す形）から字数を返す。"""
    return int(mark.strip()[2:])


class LeadMarks(NamedTuple):
    """行頭の記号を読んだ結果（split_lead_marks）。記号がなければ ""。"""
    align: str      # 配置の記号
    left: str       # ->N の記号
    rest: str       # 記号の後ろ（字下げの空白を含む）
    area: str = ""  # [HEADER] [FOOTER] の記号（書いたとおりの大文字・小文字）

    def join(self):
        """記号と記号の後ろをつないだ行。記号は、ボタンで付けるときの順（ヘッダー・配置・インデント）に並べる。"""
        return self.area + self.align + self.left + self.rest


def area_of(mark):
    """[HEADER] [FOOTER] の記号（split_lead_marks が返す形）から HEADER・FOOTER を返す（記号がなければ None）。"""
    return (HEADER if mark.strip()[1:-1].lower() == HEADER else FOOTER) if mark else None


def split_lead_marks(line):
    """行頭の記号を読み、LeadMarks を返す。配置の記号は ->N より先、[HEADER] [FOOTER] はどの位置でもよい
    （エディターの付け外しと、AI の回答の確かめに使う）。記号は、後ろの半角の空白を付けた形で返す
    （行末で空白のないものも）。記号の後ろの字下げの空白は rest に残す。"""
    rest, align, left, area = line, "", "", ""
    while True:
        m_area = AREA_MARK_RE.match(rest)
        m_left = LEFT_INDENT_RE.match(rest)
        mark = "" if align or left else next((m for m in ALIGN_MARKS if lead_mark_len(rest, m)), "")
        if m_area and not area:
            area, rest = m_area.group(0).rstrip() + " ", rest[m_area.end():]
        elif mark:
            align, rest = mark, rest[lead_mark_len(rest, mark):]
        elif m_left and not left:
            left, rest = m_left.group(0).rstrip() + " ", rest[m_left.end():]
        else:
            return LeadMarks(align, left, rest, area)


def image_mark(line):
    """画像の行（[IMAGE 1]{30}。行頭の配置の記号・->N の後ろでもよい）なら (番号, 幅の字数〔省いたら None〕)、
    そうでなければ None。ヘッダー・フッターの行は画像としない（parse と同じ）。"""
    lead = split_lead_marks(split_leading_space(line)[0])
    if lead.area:
        return None
    m = IMAGE_RE.fullmatch(split_leading_space(lead.rest)[0].rstrip())
    return (int(m.group(1)), int(m.group(2)) if m.group(2) else None) if m else None


def image_numbers(lines):
    """文章（行のリスト）の画像の番号を、出てくる順に（同じ番号も重ねて）返す。"""
    return [n[0] for n in map(image_mark, lines) if n]


def split_leading_space(line):
    """行頭の空白を取り除き、(残りの文字列, インデントの字数) を返す。"""
    n = 0.0
    i = 0
    while i < len(line) and line[i] in "　 ":
        n += 1 if line[i] == "　" else 0.5
        i += 1
    return line[i:], n


def table_follows(paras):
    """これから置く表の左端をそろえる直前の段落。箇条書き・段落番号・->N の段落なら、それを返す（空の行は飛ばす）。"""
    for p in reversed(paras):
        if p.kind == BLANK or p.area:
            continue
        return p if p.kind in (BULLET, NUMBER) or p.left_indent is not None else None
    return None


def parse(lines, dt):
    """マークダウンの行のリストを段落のリストにする。dt は文書の種類（DocType）。"""
    paras = []
    counters = [0] * 9
    current = 0
    seen = False            # 最初の見出しまたはリストを過ぎたか（VA公用文の blnAfterHeading）
    stopped = False         # 見出しの後の右揃えの段落を過ぎたか（VA公用文の blnAfterAlignRight）
    lines = [raw.rstrip("\r\n") for raw in lines]
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        src = i - 1
        if not line.strip():
            paras.append(Para("", kind=BLANK, src_line=src))
            continue
        # 表：| で始まる行が続き、2行目が区切りの行のもの
        if is_table_line(line):
            j = i
            while j < len(lines) and is_table_line(lines[j]):
                j += 1
            table = parse_table(lines[i - 1:j])
            if table is not None:
                paras.append(Para("", kind=TABLE, table=table, body_level=current if seen and not stopped else 0,
                                  follows=table_follows(paras), src_line=src, src_end=j - 1))
                i = j
                continue
        kind, toc_levels = line_mark(line.strip())
        if kind:
            # 目次の段落の level は、載せる見出しの段
            paras.append(Para("", kind=kind, level=toc_levels, src_line=src))
            if kind == SECTION_BREAK:
                counters = [0] * 9
                current, seen, stopped = 0, False, False
            continue
        line, indent = split_leading_space(line)
        line = move_wraps_after_marks(line, lists=not stopped)  # 「**:=: 準備書面**」「**# 見出し**」
        lead = split_lead_marks(line)
        align, line = ALIGN_MARKS[lead.align] if lead.align else JUSTIFY, lead.rest
        left_indent = left_indent_of(lead.left) if lead.left else None
        area = area_of(lead.area)
        line, more = split_leading_space(line)      # 記号・太字の記号の後ろの空白も字下げ（`->2 　本文`。2026-10-28）
        indent += more
        m_image = None if area else IMAGE_RE.fullmatch(line.rstrip())
        if m_image:
            # 画像：見出しの番号・「最初の見出しを過ぎたか」「右揃えの段落を過ぎたか」は変えない
            paras.append(Para("", kind=IMAGE, image=(int(m_image.group(1)), int(m_image.group(2) or 0) or None),
                              align=align, left_indent=left_indent, body_level=current if seen and not stopped else 0,
                              src_line=src, src_col=len(lines[src]) - len(line)))
            continue
        if not stopped and left_indent is None and area is None:      # ->N の段落は、見出しなどに変換しない
            m_head = HEADING_MARK_RE.match(line)
            m_num = _NUMBERED_RE.match(line)
        else:
            m_head = m_num = None
        if area:
            # ヘッダー・フッター：見出し・本文として整えない段落と同じく組み、本文の行は使わない
            p = Para(line, area=area, first_indent=indent, left_indent=left_indent)
        elif m_head:
            level = len(m_head.group(1))
            line = line[m_head.end():]
            seen = True
            # 番号を進める（振り直した後の最初は開始番号から）
            counters[level - 1] = counters[level - 1] + 1 if counters[level - 1] else dt.start_at[level - 1]
            # 下の階層のうち、この階層以上で振り直すもの（リスト開始レベルがこの階層以上）を振り直す
            for k in range(level, 9):
                if dt.reset_on[k] and dt.reset_on[k] >= level:
                    counters[k] = 0
            num = dt.number_formats[level - 1]
            for k in range(9):
                num = num.replace(f"%{k + 1}", number_text(dt.number_styles[k], counters[k]) if counters[k] else "")
            p = Para(line, kind=HEADING, level=level, number=num, one_width=dt.one_width)
            current = level
        elif not stopped and left_indent is None and line.startswith("- "):
            seen = True
            p = Para(line[2:], kind=BULLET, body_level=current, number=dt.list_bullet)
        elif m_num:
            seen = True
            # 前の段落が段落番号でなければ、番号を1から振り直す
            prev = paras[-1] if paras else None
            n = prev.number_index + 1 if prev is not None and prev.kind == NUMBER else 1
            p = Para(line[m_num.end():], kind=NUMBER, body_level=current, number_index=n,
                     number=dt.list_number.replace("%1", number_text(dt.list_number_style, n)))
        else:
            p = Para(line, body_level=current if seen and not stopped else 0, first_indent=indent,
                     left_indent=left_indent)
        p.align = align
        p.src_line, p.src_col = src, len(lines[src]) - len(p.text)
        if has_inline_marks(p.text):
            found = split_inline_full(p.text)
            p.text, p.bold, p.highlight, p.dots, p.distribute = (found.plain, found.bold, found.highlight, found.dots,
                                                                 found.distribute)
            p.src_cols = [p.src_col + c for c in found.cols]
        paras.append(p)
        if seen and align == RIGHT and area is None:
            stopped = True
    # 複合見出し：字のない見出しのすぐ後が見出しなら、1行にまとめる（左インデントの増加量が1字の文書の種類だけ）
    if dt.left_add == 1:
        for k in range(len(paras) - 1):
            p = paras[k]
            if p.kind == HEADING and not p.text.strip() and paras[k + 1].kind == HEADING:
                p.composite = True
    return paras
