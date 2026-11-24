"""ナビゲーション（見出しの一覧）の見出しと、見出しの範囲の操作（2026-11-24 班長指示「Word のナビゲーションと同じ機能」）。

画面から独立した関数の集まり。エディターの行のリストを受け取り、書き換えた行のリストを返す（画面は navigation.py）。
見出しの読み取りは、組むときと同じ document.parse を使う（右揃えの段落の後の # など、見出しとして組まれない行は載せない）。

・見出しの範囲：見出しの行から、次の同じか上のレベル（# の少ない）の見出しの手前まで。Word と同じく、下のレベルの見出しと
  本文を含む。ただし、セクション区切り（<<<=）と、見出しの後の右揃えの段落（「以上」など。そこから先は見出しに変換しない）の
  手前で終わる（それらは、どの見出しにも属さない。見出しを動かしても「以上」が付いてこないように）。
・見出しの前の空行：見出しの後ろの空行（次の見出しの前の空行）は、その見出しの範囲に入れて一緒に動かす。ただし、範囲の
  後ろが見出しでない見出し（その並びの最後の見出し）は、後ろの空行を残し、前の空行と一緒に動かす。見出しの前を1行あけて
  書いた文書で、見出しを入れ替えても、見出しと見出しの間の空行が崩れないようにするため。
・見出しの挿入（前・後・小見出し）と、見出しと本文の選択（section_end）も、同じ範囲の考え方による（2026-11-24 班長決定）。
"""
from dataclasses import dataclass

from .document import (BODY, BULLET, HEADING, HEADING_MARK_RE, NUMBER, RIGHT, SECTION_BREAK, move_wraps_after_marks,
                       parse, split_lead_marks)

MAX_LEVEL = 9               # 見出しのレベルの上限（######### まで）
EMPTY_LABEL = "（字のない見出し）"


@dataclass(frozen=True)
class Heading:
    """ナビゲーションに載せる見出し。行の番号は 0 から（エディターの行の番号から 1 を引いたもの）。"""
    line: int               # 見出しの行
    level: int              # レベル（# の数）
    label: str              # 一覧に出す字（番号と見出しの字。組んだときと同じ番号）
    end: int                # 範囲の終わり（この行の手前まで）
    parent: int             # 親の見出し（headings の何番目か）。なければ -1
    last: bool              # 範囲の後ろが見出しでない（セクション区切り・右揃えの段落・文書の終わり）


def _blank(line):
    """空の行か（document.parse が1行の空きとして読む行）。"""
    return not line.strip()


def headings(lines, dt):
    """行のリストの見出しを、上から順に Heading のリストにする。dt は文書の種類（DocType）。"""
    found, stops = [], []
    seen = False                    # 最初の見出し・リストを過ぎたか（document.parse と同じ）
    for p in parse(lines, dt):
        if p.kind == SECTION_BREAK:
            stops.append(p.src_line)
            seen = False
            continue
        if p.kind in (HEADING, BULLET, NUMBER):
            seen = True
        if p.kind == HEADING:
            label = (p.number + p.text).strip(" 　")
            found.append((p.src_line, p.level, label or EMPTY_LABEL))
        if seen and p.area is None and p.align == RIGHT and p.kind in (HEADING, BULLET, NUMBER, BODY):
            stops.append(p.src_line)    # 右揃えの段落（そこから先は見出しに変換しない）
    starts = {line for line, _, _ in found}
    out, stack = [], []
    for k, (line, level, label) in enumerate(found):
        end = next((other for other, lv, _ in found[k + 1:] if lv <= level), len(lines))
        end = min([end] + [s for s in stops if s > line])
        parent = -1
        while stack:
            top = out[stack[-1]]
            if top.level < level and top.end > line:
                parent = stack[-1]
                break
            stack.pop()
        stack.append(k)
        out.append(Heading(line, level, label, end, parent, end not in starts))
    return out


def heading_at(heads, line):
    """line 行目（0 から）を範囲に含む見出しのうち、いちばん下のレベルのもの（heads の何番目か）。なければ -1。"""
    for k in range(len(heads) - 1, -1, -1):
        if heads[k].line <= line < heads[k].end:
            return k
    return -1


def subtree(heads, k):
    """k 番目の見出しと、その範囲に入る見出し（heads の番号のリスト）。"""
    h = heads[k]
    return [j for j in range(k, len(heads)) if heads[j].line < h.end]


def siblings(heads, k):
    """k 番目の見出しと同じ親を持つ見出し（heads の番号のリスト。上から順）。"""
    return [j for j, h in enumerate(heads) if h.parent == heads[k].parent]


def section_end(lines, h):
    """見出し h の範囲のうち、後ろの空行を除いた終わり（この行の手前まで）。"""
    end = h.end
    while end > h.line + 1 and _blank(lines[end - 1]):
        end -= 1
    return end


def _blanks_before(lines, line):
    """line 行目のすぐ前に続く空行。"""
    start = line
    while start > 0 and _blank(lines[start - 1]):
        start -= 1
    return lines[start:line]


def _take(lines, h):
    """見出し h の範囲を取り出す。(消す行の始め, 終わり, 動かす行, 一緒に動かす空行, 空行を前に付けるか)。
    範囲の後ろが見出しなら、後ろの空行も一緒に動かす。そうでなければ（その並びの最後）、後ろの空行は残し、前の空行を
    一緒に動かす（モジュールの説明）。"""
    core_end = section_end(lines, h)
    core = lines[h.line:core_end]
    if not h.last:
        return h.line, h.end, core, lines[core_end:h.end], False
    start = h.line
    while start > 0 and _blank(lines[start - 1]):
        start -= 1
    return start, core_end, core, lines[start:h.line], True


def move(lines, heads, k, target):
    """k 番目の見出しを、その範囲ごと target 行目（0 から）の前へ動かす。target は、見出しの行（その見出しの前へ）か、
    見出しの範囲の終わり（セクション区切り・右揃えの段落・文書の終わり。その並びの最後へ）。
    (書き換えた行のリスト, 動かした見出しの行) を返す。動かせない（自分の範囲の中へ動かす）ときは None。"""
    h = heads[k]
    if h.line <= target <= h.end:
        return None
    start, stop, core, blanks, _ = _take(lines, h)
    rest = lines[:start] + lines[stop:]

    def shift(x):
        return x if x <= start else x - (stop - start)
    if target in {other.line for other in heads}:
        at = shift(target)
        return rest[:at] + core + blanks + rest[at:], at
    # その並びの最後へ：終わりの前の空行（文書の終わりの改行など）は残し、その前に、空行を前に付けて置く
    at = target
    while at > 0 and _blank(lines[at - 1]) and not start <= at - 1 < stop:
        at -= 1
    at = shift(at)
    return rest[:at] + blanks + core + rest[at:], at + len(blanks)


def move_target(heads, k, step):
    """k 番目の見出しを、前（step=-1）・後（step=1）の同じ親の見出しと入れ替えるときの target（move に渡す）。
    入れ替える見出しがなければ None。"""
    same = siblings(heads, k)
    i = same.index(k) + step
    if not 0 <= i < len(same):
        return None
    other = heads[same[i]]
    return other.line if step < 0 else other.end


def delete(lines, heads, k):
    """k 番目の見出しを、その範囲ごと消す。(書き換えた行のリスト, 消した所の行) を返す。"""
    start, stop, _, _, _ = _take(lines, heads[k])
    rest = lines[:start] + lines[stop:]
    return rest, min(start, max(0, len(rest) - 1))


# 見出しを入れる所（insert_heading）
BEFORE, AFTER, CHILD = "before", "after", "child"


def insert_heading(lines, heads, k, where):
    """k 番目の見出しの前（BEFORE）・後（AFTER。その範囲の後）・小見出し（CHILD。1つ下のレベルで、その範囲の最後の
    小見出しとして）に、字のない見出しの行を入れる（2026-11-24 班長決定。字は利用者が打つ）。
    見出しと見出しの間の空行は、まわりにならう：前・後に入れるときは、その見出しの前の空行と同じ空行で区切り、小見出しは、
    いちばん後ろの小見出しの前の空行（小見出しがなければ空行なし）で区切る。範囲の後ろの空行（次の見出しの前、「以上」の
    前など）は、入れた見出しの後ろにそのまま残す。
    (書き換えた行のリスト, 入れた見出しの行) を返す。######### より下になるときは None。"""
    h = heads[k]
    level = h.level + (1 if where == CHILD else 0)
    if level > MAX_LEVEL:
        return None
    mark = "#" * level + " "
    if where == BEFORE:
        return lines[:h.line] + [mark] + _blanks_before(lines, h.line) + lines[h.line:], h.line
    if where == AFTER:
        gap = _blanks_before(lines, h.line)
    else:
        children = [j for j in subtree(heads, k)[1:] if heads[j].parent == k]
        gap = _blanks_before(lines, heads[children[-1]].line) if children else []
    at = section_end(lines, h)
    return lines[:at] + gap + [mark] + lines[at:], at + len(gap)


def set_heading_level(line, level):
    """見出しの行の # の数を level にした行（行頭の空白・配置の記号、「**# 見出し**」の形も扱う。document.parse と同じ
    読み方）。見出しの記号がなければ、そのまま返す。"""
    rest = line.lstrip(" 　")
    head = line[:len(line) - len(rest)]
    rest = move_wraps_after_marks(rest)             # 「**# 見出し**」は「# **見出し**」として扱う（字の数は同じ）
    lead = split_lead_marks(rest)
    at = len(rest) - len(lead.rest.lstrip(" 　"))
    m = HEADING_MARK_RE.match(rest, at)
    if not m:
        return line
    return head + rest[:m.start(1)] + "#" * level + rest[m.end(1):]


def shift_level(lines, heads, k, step):
    """k 番目の見出しと、その範囲に入る見出しのレベルを step（-1 で上げる・1 で下げる）だけ変える。
    (書き換えた行のリスト, 変えた見出しの行のリスト) を返す。どれかが # より上・######### より下になるときは None
    （見出しが本文に変わらないよう、何もしない）。"""
    found = subtree(heads, k)
    if any(not 1 <= heads[j].level + step <= MAX_LEVEL for j in found):
        return None
    new = list(lines)
    for j in found:
        new[heads[j].line] = set_heading_level(new[heads[j].line], heads[j].level + step)
    return new, [heads[j].line for j in found]
