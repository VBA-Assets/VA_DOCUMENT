"""構文ファイル（記号入り）と PDF（実名入り）を突き合わせて、対応表を作り直す（仕様.md の7）。

・PDF から、本文の範囲（上下の余白の内側）の字を、描いた順に取り出して1本の文字列にする
  （ページ番号は余白にあるので入らない。行の切れ目はつなぐ）。VA Documentは字を文書の順に描く（pdfwriter）。
・構文ファイルの文書を、PDF と同じ並び（見出しの番号＋本文、表はセルの順。配置の記号は除く）の
  1本の文字列にし、記号（〔人名Ａ〕など）は1字の目印（私用領域の字）に置き換える。
・2つを difflib で突き合わせ、目印の字に対応する PDF の字の並びを、その記号の元の語とする。同じ記号が
  何度も出てくるときは、いちばん多く対応した語を採り、食い違いがあれば知らせる。
・均等割付の範囲の境目は PDF の字の並びに残らないので、字の位置（1字目の左端から字数の幅）で求め、両方の
  文字列の同じ位置に区切りを入れてから突き合わせる（範囲の中の記号と外の記号が隣り合うと、切れ目が定まらないため。
  2026-10-25）。
・ヘッダー・フッター（[HEADER] [FOOTER]。2026-10-25）の字は、上下の余白の字をページごとに描いた順に取り出し（ページの
  最後に描くページ番号は除く）、本文の後ろに、ヘッダー（セクションの最初のページにだけある）をページの順に、続けて
  フッター（セクションの全ページにある。続くページで同じものは1つにまとめる）を続ける。構文ファイルの側も、セクション
  ごとのヘッダー、まとめたフッターの順に続ける。
・求めた語で目印を置き換えた文字列が PDF の文字列と一致すれば、すべての記号が確かに求まっている（exact）。
試作（試作\\recover_map.py）で、同じ版なら短い文書・14ページの文書とも、すべての記号の元の語が求まった。
"""
import difflib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .doctypes import DEFAULT_DOC_TYPE, NAIYOU, PAGE_NUMBER_BOTTOM_CENTER, PAGE_NUMBER_NONE, doc_type_for
from .document import FOOTER, HEADER, SECTION_BREAK, TABLE, TOC, parse
from .document import heading_label
from .layout import toc_entries
from .layout import Typesetter
from .pdftext import pdf_chars
from .pdfwriter import page_number_text, read_id
from .pseudonym import TOKEN_RE, Dictionary, normalize_token

_MARK_BASE = 0xE000
_TOC_FILL = "\uF8FF"     # 目次の点線とページ番号の位置（PDF にだけある。一致の確かめでは「点の並び＋数字」とみなす）
_SEP = "\x1f"           # 均等割付の範囲の境目（突き合わせのときだけ、両方の文字列の同じ位置に入れる）
_AREA_SEP = chr(0xF8FE)  # ヘッダー・フッターの字の、ページ（セクション）ごとの切れ目（両方の文字列に入れる）
_SPACE_RE = re.compile(r"\s+")


class PdfMismatch(ValueError):
    """PDF が、構文ファイルと同じ文書のものではない。"""


@dataclass
class Recovery:
    found: dict = field(default_factory=dict)       # 記号 → 元の語
    conflicts: dict = field(default_factory=dict)   # 記号 → {語: 回数}（違う語が対応した記号）
    missing: list = field(default_factory=list)     # 元の語が求まらなかった記号
    exact: bool = False                             # 求めた語で戻すと、PDF の文章と一字残らず一致したか


def pdf_body_text(path, ts, pages=None):
    """PDF の本文の範囲の字を、描いた順に1本の文字列にする（空白も残す。名前の中の空白を戻すため）。
    (文字列, [(ページ, 字の左端, 基準線)]) を返す（位置は均等割付の範囲を求めるのに使う）。pages は pdftext.pdf_chars の
    結果（読んであれば渡す。同じ PDF を2度読まないため）。"""
    top = ts.margin_top
    bottom = ts.margin_top + ts.lines_page * ts.line_pitch
    out, where = [], []
    for pi, chars in enumerate(pdf_chars(path) if pages is None else pages):
        for ch, x, y in chars:      # 字の左端と基準線（用紙の上端から）
            # 本文の左端より左（行番号）は除く
            if top < y <= bottom + 1 and x >= ts.margin_left - 1:
                out.append(ch)
                where.append((pi, x, y))
    return "".join(out), where


def pdf_area_text(path, ts, page_number=PAGE_NUMBER_BOTTOM_CENTER, pages=None):
    """PDF のヘッダー・フッター（上下の余白）の字を1本の文字列にする。ページ番号（ページの最後に描く。pdfwriter）は
    除く。ヘッダーの字のあるページのヘッダーをページの順に並べ、続けてフッターを並べる（フッターは、字のないページを
    飛ばし、前のページと同じものは1つにまとめる。セクションの全ページに出るため）。ページごとの初めに _AREA_SEP を
    入れる。(文字列, 位置) を返す。pages は pdf_body_text と同じ。"""
    top = ts.margin_top
    bottom = ts.margin_top + ts.lines_page * ts.line_pitch
    heads, feet, prev = [], [], None
    pages = pdf_chars(path) if pages is None else pages
    for pi, page in enumerate(pages):
        chars = [(ch, (pi, x, y)) for ch, x, y in page]
        if page_number != PAGE_NUMBER_NONE:
            s = page_number_text(page_number, pi + 1, len(pages))
            if "".join(c for c, _ in chars[-len(s):]) == s:
                chars = chars[:-len(s)]
        head = [c for c in chars if c[1][2] <= top]
        foot = [c for c in chars if c[1][2] > bottom + 1]
        if "".join(c for c, _ in head).strip():
            heads.append(head)
        text = "".join(c for c, _ in foot)
        if text.strip() and text != prev:
            feet.append(foot)
            prev = text
    out, where = [], []
    for chars in heads + feet:
        out.append(_AREA_SEP + "".join(c for c, _ in chars))
        where += [(-1, 0.0, 0.0)] + [w for _, w in chars]
    return "".join(out), where


def vamd_body_text(lines, dt):
    """構文ファイルの文書を、PDF と同じ並びの文字列にする。

    (文字列, {目印: 記号}, 均等割付の範囲 [(始め, 終わり, 字数)]〔文字列の何字目か〕) を返す。"""
    marks = {}

    def sub(m):
        tok = normalize_token(m.group(0))
        if tok not in marks:
            marks[tok] = chr(_MARK_BASE + len(marks))
        return marks[tok]
    paras = parse([TOKEN_RE.sub(sub, ln) for ln in lines], dt)
    parts, spans, pos = [], [], 0

    def add(text, distribute=(), shift=0):
        nonlocal pos
        spans.extend((pos + shift + a, pos + shift + b, n) for a, b, n in distribute)
        parts.append(text)
        pos += len(text)
    sections = [{HEADER: [], FOOTER: []}]
    for p in paras:
        if p.area:
            sections[-1][p.area].append(p)      # 本文の後ろに続ける（下）
        elif p.kind == SECTION_BREAK:
            sections.append({HEADER: [], FOOTER: []})
        elif p.kind == TABLE:
            for ri, row in enumerate([p.table.header] + p.table.rows):
                for k, (_, text) in enumerate(row):
                    add(text, p.table.distribute.get((ri, k), ()))
        elif p.kind == TOC:
            # 目次の行（番号＋半角の空白＋見出し。点線とページ番号は PDF にだけあり、突き合わせでは飛ばされる）
            for hi, h in toc_entries(paras, p.level):
                number = heading_label(paras, hi)[1]
                add(number.rstrip(" 　") + (" " if number.strip() else "") + h.text + _TOC_FILL)
        else:
            add(p.number + p.text, p.distribute, len(p.number))
    # ヘッダー・フッター（pdf_area_text と同じ並び）：セクションごとのヘッダー、続けてフッター。字のないものは飛ばし、
    # フッターは前のセクションと同じものを1つにまとめる。内容証明では組まない
    groups, prev = [], None
    if dt.key != NAIYOU:
        groups = [s[HEADER] for s in sections if "".join(p.text for p in s[HEADER]).strip()]
        for s in sections:
            text = "".join(p.text for p in s[FOOTER])
            if text.strip() and text != prev:
                groups.append(s[FOOTER])
                prev = text
    for group in groups:
        add(_AREA_SEP)
        for p in group:
            add(p.text, p.distribute)
    return "".join(parts), {v: k for k, v in marks.items()}, spans


def _boundary(ops, b):
    """v の b 字目の前の境目に当たる p の位置（突き合わせで定まらない区間の中なら None）。"""
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal" and i1 <= b <= i2:
            return j1 + b - i1
        if tag != "equal" and b == i1:
            return j1
        if tag != "equal" and b == i2:
            return j2
    return None


def _distribute_extent(p, where, ts, n, start=None, end=None):
    """均等割付の範囲の、p での始め（end から）か終わり（start から）を、字の位置から求める。

    割り付けた範囲は、1字目の左端から最後の字の右端までが n 字の幅になる（layout）。字の幅の合計が n 字の幅より
    狭い（字の間が空いている）ときだけ当てはめる。字の幅のまま並んだとき（字数より字が多いなど）は、普通の字と
    見分けられないので None。"""
    wide = n * ts.pitch
    if start is not None and start < len(p):
        page, x0, y0 = where[start]
        natural = 0.0
        for e in range(start, len(p)):
            pg, x, y = where[e]
            if pg != page or abs(y - y0) > 0.5:
                break
            natural += ts.advance(p[e])
            right = x + ts.advance(p[e])
            if abs(right - (x0 + wide)) < 0.1:
                return e + 1 if natural < wide - 0.1 else None
            if right > x0 + wide:
                break
    if end is not None and 0 < end <= len(p):
        page, x1, y0 = where[end - 1]
        left = x1 + ts.advance(p[end - 1]) - wide
        natural = 0.0
        for s in range(end - 1, -1, -1):
            pg, x, y = where[s]
            if pg != page or abs(y - y0) > 0.5:
                break
            natural += ts.advance(p[s])
            if abs(x - left) < 0.1:
                return s if natural < wide - 0.1 else None
            if x < left:
                break
    return None


def _separate_distribute(v, p, where, spans, mark_to_token, ts):
    """均等割付の範囲の境目に、v・p の同じ位置へ区切りの字を入れる。

    割り付けた字の間の空きは PDF の字の並びに残らないので、範囲の中の記号と外の字（記号）が隣り合うと
    （「[〔その他Ａ〕]{5}〔人名Ａ〕」→「原告甲野太郎」）、どこで切れるかが突き合わせでは定まらない。範囲の片方の
    端が突き合わせで定まれば、もう片方の端は字の位置から求まる。区切りを入れて突き合わせ直すと、新しく端が
    定まる範囲があるので、繰り返す。(区切りを入れた v, p) を返す。"""
    spans = [s for s in spans if any(c in mark_to_token for c in v[s[0]:s[1]])]
    cuts = {}       # v の何字目の前 → p の何字目の前
    done = set()
    while True:
        vs, ps = _with_cuts(v, sorted(cuts)), _with_cuts(p, sorted(cuts.values()))
        ops = difflib.SequenceMatcher(None, vs, ps, autojunk=False).get_opcodes()
        v_pos = _cut_positions(len(v), sorted(cuts))
        p_orig = _orig_positions(ps)
        added = False
        for a, b, n in spans:
            if (a, b) in done:
                continue
            # 範囲の始め（区切りの後ろ）と終わり（区切りの前）が突き合わせで定まるか
            ja, jb = _boundary(ops, v_pos[a]), _boundary(ops, v_pos[b - 1] + 1)
            ja = None if ja is None else p_orig[ja]
            jb = None if jb is None else p_orig[jb]
            if ja is not None and jb is None:
                jb = _distribute_extent(p, where, ts, n, start=ja)
            elif jb is not None and ja is None:
                ja = _distribute_extent(p, where, ts, n, end=jb)
            if ja is None or jb is None or ja >= jb:
                continue
            new = dict(cuts)
            if new.setdefault(a, ja) != ja or new.setdefault(b, jb) != jb:
                continue
            keys = sorted(new)
            if [new[k] for k in keys] != sorted(new[k] for k in keys):
                continue    # 前後が入れ替わる区切りは採らない
            cuts = new
            done.add((a, b))
            added = True
        if not added:
            return vs, ps


def _with_cuts(s, at):
    """s の at（昇順）の各位置の前に区切りの字を入れる。"""
    out, k = [], 0
    for i in at:
        out.append(s[k:i])
        out.append(_SEP)
        k = i
    out.append(s[k:])
    return "".join(out)


def _cut_positions(n, at):
    """区切りを入れる前の何字目が、入れた後の何字目になるか（n 字分）。"""
    pos, shift, at = [], 0, list(at)
    for i in range(n + 1):
        while at and at[0] == i:
            shift += 1
            at.pop(0)
        pos.append(i + shift)
    return pos


def _orig_positions(s):
    """区切りを入れた文字列の各位置（境目）が、区切りを入れる前の何字目の前に当たるか。"""
    out, k = [], 0
    for c in s:
        out.append(k)
        if c != _SEP:
            k += 1
    out.append(k)
    return out


def recover(vamd_lines, pdf_path, dt, page_number=PAGE_NUMBER_BOTTOM_CENTER):
    """突き合わせて Recovery を返す。page_number は PDF のページ番号の位置（ヘッダー・フッターの字から除くため）。"""
    ts = Typesetter(dt)
    v_plain, mark_to_token, spans = vamd_body_text(vamd_lines, dt)
    pages = pdf_chars(pdf_path)
    p_plain, where = pdf_body_text(pdf_path, ts, pages)
    area_text, area_where = pdf_area_text(pdf_path, ts, page_number, pages)
    p_plain, where = p_plain + area_text, where + area_where
    v, p = _separate_distribute(v_plain, p_plain, where, spans, mark_to_token, ts)
    sm = difflib.SequenceMatcher(None, v, p, autojunk=False)
    votes = defaultdict(Counter)
    pending = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        seg_v, seg_p = v[i1:i2], p[j1:j2]
        if len(seg_v) == 1 and seg_v in mark_to_token and tag == "replace" and _SEP not in seg_p:
            # 目印だけの区間なら、その区間の PDF の字が元の語
            votes[mark_to_token[seg_v]][seg_p] += 1
        elif any(c in mark_to_token for c in seg_v) and seg_p:
            pending.append((seg_v, seg_p))
    # 目印と文字が混ざった区間・目印が隣り合う区間（版ずれ、「〔その他Ａ〕〔人名Ａ〕」など）は、
    # 求まった記号を語に戻してみて、求まらない目印が1つだけ残り、その前後の字が PDF の区間の前後と
    # 合うときに当てはめる。新しく求まった記号があれば、繰り返す
    progress = True
    while pending and progress:
        progress = False
        rest = []
        for seg_v, seg_p in pending:
            unknown = [k for k, c in enumerate(seg_v) if c in mark_to_token and not votes[mark_to_token[c]]]
            if len(unknown) != 1:
                if unknown:
                    rest.append((seg_v, seg_p))
                continue
            k = unknown[0]

            def expand(s):
                return "".join(votes[mark_to_token[c]].most_common(1)[0][0] if c in mark_to_token else c for c in s)
            before, after = expand(seg_v[:k]), expand(seg_v[k + 1:])
            if seg_p.startswith(before) and seg_p.endswith(after) and len(seg_p) > len(before) + len(after):
                votes[mark_to_token[seg_v[k]]][seg_p[len(before):len(seg_p) - len(after)]] += 1
                progress = True
        pending = rest
    # 予備：まだ求まらない記号は、記号の前後の字（3〜8字ずつ）が PDF で「前の字＋何か＋後の字」に
    # なっている箇所を探す（版ずれで、記号の近くが書き換わった場合のため）
    for k, ch in enumerate(v_plain):
        tok = mark_to_token.get(ch)
        if tok is None or votes[tok]:
            continue
        before = re.split(f"[{chr(_MARK_BASE)}-{chr(_MARK_BASE + 0x0FFF)}]", v_plain[max(0, k - 8):k])[-1]
        after = re.split(f"[{chr(_MARK_BASE)}-{chr(_MARK_BASE + 0x0FFF)}]", v_plain[k + 1:k + 9])[0]
        if len(before) < 3 or len(after) < 3:
            continue
        for m in re.finditer(re.escape(before) + "(.{1,40}?)" + re.escape(after), p_plain):
            votes[tok][m.group(1)] += 1
    r = Recovery()
    for tok in mark_to_token.values():
        if votes[tok]:
            r.found[tok] = votes[tok].most_common(1)[0][0]
            if len(votes[tok]) > 1:
                r.conflicts[tok] = dict(votes[tok])
        else:
            r.missing.append(tok)
    restored = "".join(r.found.get(mark_to_token.get(c), c) if c in mark_to_token else c for c in v_plain)
    # 比べるときは空白を除く（行末の半角空白は行の外に出し、PDF に描かないことがある）
    pattern = "".join(r"\.*\d+" if piece == _TOC_FILL else re.escape(piece)
                      for piece in re.split(f"({_TOC_FILL})", _SPACE_RE.sub("", restored)) if piece)
    r.exact = (not r.missing and not r.conflicts
               and re.fullmatch(pattern, _SPACE_RE.sub("", p_plain), flags=re.S) is not None)
    return r


def rebuild_dictionary(content, pdf_path, doc_type=None):
    """構文ファイル（vamd.Content）と PDF から、辞書を作り直す。(Dictionary, Recovery) を返す。

    PDF の識別子の文書ID が違えば PdfMismatch を出す。版が違っても突き合わせる（求まらない記号・
    違う語が対応した記号は Recovery に入るので、利用者に尋ねる。違う語が対応した記号は辞書に入れない）。
    構文ファイルに出てくる記号の英字は、元の語が求まらなくても使ったものとして覚え、新しい語に
    同じ記号を振らない。文書の種類は、doc_type（DOC_TYPES のキー）がなければ区切りの行の設定による。
    """
    pdf_id = read_id(pdf_path)
    if pdf_id is None or pdf_id[0] != content.doc_id:
        raise PdfMismatch("この PDF は、構文ファイルと同じ文書のものではありません。")
    if doc_type is None:
        doc_type = content.settings.doc_type if content.settings else DEFAULT_DOC_TYPE
    page_number = content.settings.page_number if content.settings else PAGE_NUMBER_BOTTOM_CENTER
    one_width = content.settings.one_width if content.settings else False
    r = recover(content.body, pdf_path, doc_type_for(doc_type, one_width), page_number)
    d = Dictionary()
    for m in TOKEN_RE.finditer(content.body_text):
        d.note_used(m.group(0))
    for tok, word in r.found.items():
        if tok not in r.conflicts:
            d.add_known(word, tok)
    return d, r
