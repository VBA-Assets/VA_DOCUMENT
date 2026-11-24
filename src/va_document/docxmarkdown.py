"""Word の文書（.docx）を、構文ファイルの文章（マークダウン）にする（Ver420。2026-11-24 班長指示。検討_Word文書の読み込み.md）。

.docx は XML を zip にまとめたもの。標準の zipfile と xml.etree で読む（新しい部品を使わない）。段落を、PDF の取り込み
（pdfmarkdown.py）と同じ形の段落（Block）にして、同じ規則（pdfmarkdown.to_markdown）でマークダウンにする。PDF のように
字の位置から推し量らず、段落・配置・字下げ・書式・表・改ページは、文書に書かれているとおりに取る。

・見出し：見出しのスタイル・段落のアウトラインのレベルが分かる段落は、そのレベルの見出しにする。Word の自動の番号は、
  組むときに VA Document が付けるので、字にしない（2026-11-24 班長指摘「Word の番号を字として組み立てる必要はない」）。
  見出しのレベルのない段落に Word が振った番号は、番号の字を組み立てて、見出しの番号として読めるかを試す（pdfmarkdown.
  _source_mark）。番号もレベルもない段落の先頭に手で打った番号は、PDF と同じく字から読む（VA疑似アウトラインの考え方）。
・字の書式：太字・傍点・蛍光ペン。配置：中央・右。字下げ・左インデント：段落のインデント。表：結合したセルは空のセル。
  目次のフィールドは [TOC]。改ページ・セクション区切りは <<<。ヘッダー・フッターは最初のセクションのものを [HEADER]・
  [FOOTER] に、ページ番号のフィールドは、文書の設定のページ番号の位置に。行番号の設定も文書に合わせる。
・画像（2026-11-24 班長決定「画像は取り込む」）：［画像］と同じく、付加情報を除いて作り直し（images.from_image）、メモリに
  だけ持つ（保存すると PDF の中に入る。AI には渡らず、構文ファイルには [IMAGE n]{幅} の行だけ）。行内の画像は段落の中の
  位置に、浮動の画像は置いてあった段落の後ろに置く。Word で切り抜いた画像は、切り抜いた後の画像にする。

取り込まないもの（2026-11-24 班長決定。開いたときに数を知らせる。notices）：
・変更履歴は、すべて承諾した後の字だけを取る（削除した字・削除した段落記号〔次の段落とつなぐ〕・削除した表の行・移動元の
  字は取らない。挿入した字・移動先の字は取る）。
・コメント、隠し文字、作成者などの文書情報（docProps は読まない）。
・脚注・文末脚注、テキストボックス・図形の中の字（画像と組にしたキャプションも落ちる）。
・グラフ・図形・SmartArt、文書の外にリンクした画像、読めない形式の画像（EMF など）、表のセルの中の画像。

開いた docx は書き換えず、どこにも写さない。docx の名前・パスは、どこにも書かない。古い形式の .doc は読まない。
"""
import io
import posixpath
import re
import zipfile
from dataclasses import dataclass, field, replace
from xml.etree import ElementTree as ET

from PIL import Image

from . import images
from . import pdfmarkdown as pm
from .doctypes import (DOC_TYPES, PAGE_NUMBER_BOTTOM_CENTER, PAGE_NUMBER_BOTTOM_CENTER_DECORATED,
                       PAGE_NUMBER_BOTTOM_RIGHT, PAGE_NUMBER_NONE, PAGE_NUMBER_TOP_RIGHT, WEB, doc_type_for)
from .document import IMAGE_MAX
from .pseudo_outline import BULLET, NUMBER

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
V = "{urn:schemas-microsoft-com:vml}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
# Strict 形式（ISO の厳密な形）の名前空間は、通常の形に読み替える
_STRICT = {
    b"http://purl.oclc.org/ooxml/wordprocessingml/main": b"http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    b"http://purl.oclc.org/ooxml/officeDocument/relationships":
        b"http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    b"http://purl.oclc.org/ooxml/drawingml/main": b"http://schemas.openxmlformats.org/drawingml/2006/main",
    b"http://purl.oclc.org/ooxml/drawingml/wordprocessingDrawing":
        b"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}
EMU_PER_PT = 12700
MAX_PART = 200 * 1024 * 1024    # 1つの部品（XML・画像）の大きさの上限（展開した大きさ）
IMAGE_AT = "￼"             # 段落の字の中の、行内の画像の位置の目印（字には残さない）
_SYMBOL_FONTS = ("symbol", "wingdings", "webdings")


class DocxError(ValueError):
    """Word の文書として読めない。"""


def _on(el):
    """w:b・w:vanish などの切り替えの要素が「入」か（なければ None。val が false・0・off なら切）。"""
    if el is None:
        return None
    return el.get(W + "val", "true") not in ("false", "0", "off", "none")


def _int(el, attr, default=0):
    v = el.get(W + attr) if el is not None else None
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default


# ---------- スタイル ----------

@dataclass
class _PProps:
    jc: str = None
    left: int = None            # 左インデント（twip）
    left_chars: int = None      # 左インデント（字の 1/100）
    first: int = None           # 1行目（正は字下げ、負はぶら下げ。twip）
    first_chars: int = None
    right: int = None
    right_chars: int = None
    num_id: str = None
    ilvl: int = None
    outline: int = None
    page_break_before: bool = None

    def merged(self, over):
        return replace(self, **{k: v for k, v in over.__dict__.items() if v is not None})


@dataclass
class _RProps:
    bold: bool = None
    vanish: bool = None
    dots: bool = None
    highlight: bool = None
    size: float = None          # 字の大きさ（pt）

    def merged(self, over):
        return replace(self, **{k: v for k, v in over.__dict__.items() if v is not None})

    @property
    def flags(self):
        return (pm.BOLD if self.bold else 0) | (pm.DOTS if self.dots else 0) | (pm.HIGHLIGHT if self.highlight else 0)


def _read_ppr(ppr):
    p = _PProps()
    if ppr is None:
        return p
    jc = ppr.find(W + "jc")
    if jc is not None:
        p.jc = jc.get(W + "val")
    ind = ppr.find(W + "ind")
    if ind is not None:
        def get(*names):
            for n in names:
                v = ind.get(W + n)
                if v is not None:
                    try:
                        return int(v)
                    except ValueError:
                        return None
            return None
        p.left, p.left_chars = get("left", "start"), get("leftChars", "startChars")
        p.right, p.right_chars = get("right", "end"), get("rightChars", "endChars")
        first, hanging = get("firstLine"), get("hanging")
        p.first = -hanging if hanging is not None else first
        first_c, hanging_c = get("firstLineChars"), get("hangingChars")
        p.first_chars = -hanging_c if hanging_c is not None else first_c
    num = ppr.find(W + "numPr")
    if num is not None:
        nid, lv = num.find(W + "numId"), num.find(W + "ilvl")
        if nid is not None:
            p.num_id = nid.get(W + "val")
        if lv is not None:
            p.ilvl = _int(lv, "val")
    ol = ppr.find(W + "outlineLvl")
    if ol is not None:
        p.outline = _int(ol, "val", 9)
    pb = ppr.find(W + "pageBreakBefore")
    if pb is not None:
        p.page_break_before = _on(pb)
    return p


def _read_rpr(rpr):
    r = _RProps()
    if rpr is None:
        return r
    r.bold = _on(rpr.find(W + "b"))
    r.vanish = _on(rpr.find(W + "vanish"))
    em = rpr.find(W + "em")
    if em is not None:
        r.dots = em.get(W + "val") not in (None, "none")
    hl = rpr.find(W + "highlight")
    if hl is not None:
        r.highlight = hl.get(W + "val") not in (None, "none")
    sz = _int(rpr.find(W + "sz"), "val", 0)
    if sz > 0:
        r.size = sz / 2
    return r


class _Styles:
    def __init__(self, root):
        self.p, self.r, self.based = {}, {}, {}
        self.default_p = None
        self.default_ppr, self.default_rpr = _PProps(), _RProps()
        if root is None:
            return
        dd = root.find(W + "docDefaults")
        if dd is not None:
            self.default_ppr = _read_ppr(dd.find(f"{W}pPrDefault/{W}pPr"))
            self.default_rpr = _read_rpr(dd.find(f"{W}rPrDefault/{W}rPr"))
        for s in root.findall(W + "style"):
            sid = s.get(W + "styleId")
            if s.get(W + "type") == "paragraph" and s.get(W + "default") in ("1", "true"):
                self.default_p = sid
            b = s.find(W + "basedOn")
            if b is not None:
                self.based[sid] = b.get(W + "val")
            self.p[sid] = _read_ppr(s.find(W + "pPr"))
            self.r[sid] = _read_rpr(s.find(W + "rPr"))

    def _chain(self, sid):
        out, seen = [], set()
        while sid and sid not in seen and sid in self.p:
            seen.add(sid)
            out.append(sid)
            sid = self.based.get(sid)
        return reversed(out)

    def ppr(self, sid):
        p = self.default_ppr
        for s in self._chain(sid or self.default_p):
            p = p.merged(self.p[s])
        return p

    def rpr(self, sid, base=None):
        r = self.default_rpr if base is None else base
        for s in self._chain(sid):
            r = r.merged(self.r[s])
        return r


# ---------- 番号（見出しのレベルのない段落に Word が振った番号の字） ----------

_KANA = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン"
_IROHA = "イロハニホヘトチリヌルヲワカヨタレソツネナラムウヰノオクヤマケフコエテアサキユメミシヱヒモセスン"
_KANSHI = "甲乙丙丁戊己庚辛壬癸"
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_KANJI = "〇一二三四五六七八九"


def _roman(n):
    out = ""
    for v, s in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
                 (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out, n = out + s, n - v
    return out


def _kanji(n):
    if n < 10:
        return _KANJI[n]
    if n < 100:
        t, o = divmod(n, 10)
        return ("" if t == 1 else _KANJI[t]) + "十" + ("" if o == 0 else _KANJI[o])
    return str(n)


def _format_number(fmt, n):
    """Word の番号の書式 fmt で n を書いた字。表せなければ算用数字。"""
    try:
        if fmt in ("decimalFullWidth", "decimalFullWidth2"):
            return "".join(chr(ord(c) + 0xFEE0) for c in str(n))
        if fmt in ("aiueoFullWidth", "aiueo"):
            return _KANA[n - 1]
        if fmt in ("iroha", "irohaFullWidth"):
            return _IROHA[n - 1]
        if fmt in ("decimalEnclosedCircle", "decimalEnclosedCircleChinese"):
            return _CIRCLED[n - 1]
        if fmt == "upperLetter":
            return chr(ord("A") + (n - 1) % 26)
        if fmt == "lowerLetter":
            return chr(ord("a") + (n - 1) % 26)
        if fmt == "upperRoman":
            return _roman(n).upper()
        if fmt == "lowerRoman":
            return _roman(n)
        if fmt in ("japaneseCounting", "chineseCounting", "japaneseDigitalTenThousand", "chineseCountingThousand"):
            return _kanji(n)
        if fmt == "ideographTraditional":
            return _KANSHI[n - 1]
        if fmt == "decimalEnclosedParen":
            return f"({n})"
    except IndexError:
        pass
    return str(n)


@dataclass
class _Level:
    start: int = 1
    fmt: str = "decimal"
    text: str = ""
    suff: str = "tab"
    restart: int = None


class _Numbering:
    def __init__(self, root):
        self.abstract, self.nums, self.starts = {}, {}, {}
        self.counters = {}
        if root is None:
            return
        for a in root.findall(W + "abstractNum"):
            levels = {}
            for lv in a.findall(W + "lvl"):
                L = _Level()
                L.start = _int(lv.find(W + "start"), "val", 1)
                f, t, s, rs = (lv.find(W + n) for n in ("numFmt", "lvlText", "suff", "lvlRestart"))
                L.fmt = f.get(W + "val", "decimal") if f is not None else "decimal"
                L.text = t.get(W + "val", "") if t is not None else ""
                L.suff = s.get(W + "val", "tab") if s is not None else "tab"
                L.restart = _int(rs, "val") if rs is not None else None
                levels[_int(lv, "ilvl")] = L
            self.abstract[a.get(W + "abstractNumId")] = levels
        for n in root.findall(W + "num"):
            aid = n.find(W + "abstractNumId")
            if aid is None:
                continue
            nid = n.get(W + "numId")
            self.nums[nid] = aid.get(W + "val")
            self.starts[nid] = {_int(o, "ilvl"): _int(o.find(W + "startOverride"), "val", 1)
                                for o in n.findall(W + "lvlOverride") if o.find(W + "startOverride") is not None}

    def label(self, num_id, ilvl):
        """段落に Word が表示する番号の字（後ろの区切りの空白を含む）と、箇条書き（記号）か。番号がなければ ("", False)。"""
        aid = self.nums.get(num_id)
        levels = self.abstract.get(aid, {})
        L = levels.get(ilvl)
        if L is None or not 0 <= ilvl <= 8:
            return "", False
        # 番号の数え方：同じ定義（abstractNum）の番号は続けて数える。始まりの番号を指定した番号（振り直し）は別に数える
        key = num_id if self.starts.get(num_id) else aid
        cnt = self.counters.setdefault(key, [0] * 9)
        cnt[ilvl] = cnt[ilvl] + 1 if cnt[ilvl] else self.starts.get(num_id, {}).get(ilvl, L.start)
        for k in range(ilvl + 1, 9):
            lk = levels.get(k)
            if lk is None or lk.restart is None or lk.restart > ilvl:
                cnt[k] = 0
        if L.fmt == "bullet":
            return (L.text + " " if L.text else ""), True
        if L.fmt == "none":
            return "", False

        def sub(m):
            k = int(m.group(1)) - 1
            lk = levels.get(k, _Level())
            return _format_number(lk.fmt, cnt[k] or lk.start)
        text = re.sub(r"%([1-9])", sub, L.text)
        return (text + " " if text else ""), False


# ---------- 本文を読む ----------

@dataclass
class _Para:
    chars: list = field(default_factory=list)     # [(字, 書式)]。行内の画像の位置は (IMAGE_AT, 画像の番号)
    ppr: _PProps = None
    page_break_after: int = 0
    section_after: bool = False
    label: str = ""
    level: int = 0
    list_kind: str = ""
    toc: bool = False
    mark_deleted: bool = False
    mark_hidden: bool = False
    images: list = field(default_factory=list)    # [(r:id, 幅〔pt〕, 浮動か, 切り抜き)]


@dataclass
class Report:
    """取り込まなかったもの・変えたもの（開いたときに知らせる。2026-11-24 班長決定）。"""
    revisions: bool = False     # 変更履歴があったか
    deleted: int = 0            # 変更履歴で削除した字
    comments: int = 0
    hidden: int = 0             # 隠し文字の字
    footnotes: int = 0          # 脚注・文末脚注
    textboxes: int = 0          # テキストボックス・図形の中の字
    symbols: int = 0            # 記号の書体（Wingdings など）の字
    pictures: int = 0           # 取り込んだ画像
    floating: int = 0           # そのうち、浮動の画像
    unreadable: int = 0         # 読めなかった画像（EMF など）
    drawings: int = 0           # グラフ・図形・SmartArt
    linked: int = 0             # 文書の外にリンクした画像
    cell_images: int = 0        # 表のセルの中の画像
    too_many: int = 0           # 画像の数の上限（IMAGE_MAX）を超えた画像
    breaks: int = 0             # 段落の中の改行（段落を分けた）


def _xml(data):
    """XML を読む。DTD（実体の定義）を持つものは読まない（Word の文書には要らず、悪意のある文書で使われるため）。"""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise DocxError("Word の文書として読めません（思わぬ形の XML が入っています）。")
    for strict, normal in _STRICT.items():
        data = data.replace(strict, normal)
    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        raise DocxError("Word の文書として読めません（中の XML が壊れています）。") from e


class _Reader:
    def __init__(self, data):
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise DocxError("Word の文書（.docx）として読めません。パスワードで保護した文書や、古い形式の文書（.doc）は"
                            "開けません。Word で .docx の形で保存し直してから開いてください。") from e
        self.names = set(self.zip.namelist())
        main = self._main_part()
        self.base = posixpath.dirname(main)
        self.rels = self._rels(main)
        part = lambda typ: next((self._part(t) for t_, t, ext in self.rels.values()     # noqa: E731
                                 if t_ == typ and not ext), None)
        self.styles = _Styles(part("styles"))
        self.numbering = _Numbering(part("numbering"))
        comments = part("comments")
        self.rep = Report()
        self.rep.comments = len(comments.findall(W + "comment")) if comments is not None else 0
        self.doc = self._part(main)
        if self.doc is None or self.doc.find(W + "body") is None:
            raise DocxError("Word の文書として読めません（本文が見つかりません）。")
        self.items = []         # _Para または ("table", 行のリスト)
        self.section = None     # 最初のセクションの設定（sectPr）
        self.final_section = None
        self.pictures = {}      # 画像の番号 → images.Picture（メモリの中だけ）
        self._field = []        # 複合フィールドの積み上げ [命令, 結果に入ったか, 命令の名前]

    # 部品
    def _read(self, name):
        if name not in self.names:
            return None
        if self.zip.getinfo(name).file_size > MAX_PART:
            raise DocxError("Word の文書として読めません（中の部品が大きすぎます）。")
        return self.zip.read(name)

    def _part(self, name):
        data = self._read(name)
        return _xml(data) if data is not None else None

    def _main_part(self):
        root = self._part("_rels/.rels")
        if root is not None:
            for r in root.findall(PKG_REL + "Relationship"):
                if r.get("Type", "").endswith("/officeDocument"):
                    return r.get("Target", "").lstrip("/")
        return "word/document.xml"

    def _rels(self, part):
        """部品の関係 {r:id: (種類, 部品の名前, 外のファイルか)}。"""
        root = self._part(posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"))
        out = {}
        if root is None:
            return out
        for r in root.findall(PKG_REL + "Relationship"):
            target = r.get("Target", "")
            external = r.get("TargetMode") == "External"
            name = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(self.base, target))
            out[r.get("Id")] = (r.get("Type", "").rsplit("/", 1)[-1], name, external)
        return out

    # 段落の中の字
    def _runs(self, el, para, pstyle_r, deleted=False):
        for ch in el:
            tag = ch.tag
            if tag == W + "r":
                self._run(ch, para, pstyle_r, deleted)
            elif tag in (W + "ins", W + "moveTo"):
                self.rep.revisions = True
                self._runs(ch, para, pstyle_r, deleted)
            elif tag in (W + "del", W + "moveFrom"):
                self.rep.revisions = True
                self._runs(ch, para, pstyle_r, True)
            elif tag in (W + "hyperlink", W + "smartTag", W + "customXml", W + "fldSimple", W + "bdo", W + "dir"):
                self._runs(ch, para, pstyle_r, deleted)
            elif tag == W + "sdt":
                c = ch.find(W + "sdtContent")
                if c is not None:
                    self._runs(c, para, pstyle_r, deleted)
            elif tag == MC + "AlternateContent":
                c = ch.find(MC + "Fallback")
                if c is not None:
                    self._runs(c, para, pstyle_r, deleted)

    def _run(self, r, para, pstyle_r, deleted):
        rpr = r.find(W + "rPr")
        rs = rpr.find(W + "rStyle") if rpr is not None else None
        props = self.styles.rpr(rs.get(W + "val") if rs is not None else None, pstyle_r).merged(_read_rpr(rpr))
        for c in r:
            tag = c.tag
            if tag == W + "fldChar":
                kind = c.get(W + "fldCharType")
                if kind == "begin":
                    self._field.append(["", False, ""])
                elif kind == "separate" and self._field:
                    words = self._field[-1][0].split()
                    self._field[-1][1:] = [True, words[0].upper() if words else ""]
                elif kind == "end" and self._field:
                    self._field.pop()
                continue
            if tag == W + "instrText":
                if self._field:
                    self._field[-1][0] += c.text or ""
                continue
            if self._field and not self._field[-1][1]:
                continue        # フィールドの命令の部分（結果の字だけを取る）
            if tag in (W + "t", W + "delText"):
                text = c.text or ""
            elif tag in (W + "tab", W + "ptab"):
                text = "\t"
            elif tag in (W + "br", W + "cr"):
                if c.get(W + "type") == "page":
                    if not deleted:
                        para.page_break_after += 1
                    continue
                if c.get(W + "type") == "column":
                    continue
                text = "\n"
            elif tag == W + "noBreakHyphen":
                text = "-"
            elif tag == W + "sym":
                font = (c.get(W + "font") or "").lower()
                try:
                    code = int(c.get(W + "char") or "", 16)
                except ValueError:
                    code = 0
                if font.startswith(_SYMBOL_FONTS) or not code or 0xF000 <= code <= 0xF0FF:
                    if not deleted and not props.vanish:
                        self.rep.symbols += 1
                    continue
                text = chr(code)
            elif tag in (W + "footnoteReference", W + "endnoteReference"):
                if not deleted and not props.vanish:
                    self.rep.footnotes += 1
                continue
            elif tag in (W + "drawing", W + "pict", W + "object") or tag == MC + "AlternateContent":
                if not deleted and not props.vanish:
                    self._drawing(c, para)
                continue
            else:
                continue
            n = len(text.replace("\n", ""))
            if deleted:
                self.rep.deleted += n
                continue
            if props.vanish:
                self.rep.hidden += n
                continue
            para.chars += [(ch, props.flags) for ch in text]

    @staticmethod
    def _outside_textboxes(el, tag):
        """el の中の tag の要素（テキストボックスの中のものは除く）。"""
        stack = [el]
        while stack:
            x = stack.pop()
            if x.tag == tag:
                yield x
            if x.tag == W + "txbxContent":
                continue
            stack.extend(reversed(list(x)))

    def _drawing(self, el, para):
        """図（w:drawing）・古い形の図（w:pict）。テキストボックスは数え、画像は段落に覚える。"""
        if next(el.iter(W + "txbxContent"), None) is not None:
            self.rep.textboxes += 1
        found = False
        holders = list(self._outside_textboxes(el, WP + "inline")) + list(self._outside_textboxes(el, WP + "anchor"))
        for holder in holders:
            blip = next(holder.iter(A + "blip"), None)
            if blip is None:
                if next(holder.iter(W + "txbxContent"), None) is None:
                    self.rep.drawings += 1            # グラフ・図形・SmartArt など
                continue
            rid = blip.get(R + "embed")
            if not rid:
                self.rep.linked += 1
                continue
            ext = holder.find(WP + "extent")
            width = int(ext.get("cx", "0")) / EMU_PER_PT if ext is not None and ext.get("cx", "0").isdigit() else 0
            src = next(holder.iter(A + "srcRect"), None)
            crop = tuple(int(src.get(k, "0")) if src.get(k, "0").lstrip("-").isdigit() else 0
                         for k in ("l", "t", "r", "b")) if src is not None else None
            self._add_image(para, (rid, width, holder.tag == WP + "anchor", crop))
            found = True
        if not found:
            for data in self._outside_textboxes(el, V + "imagedata"):
                rid = data.get(R + "id")
                if not rid:
                    continue
                shape = next(el.iter(V + "shape"), None)
                m = re.search(r"width:([\d.]+)pt", shape.get("style", "")) if shape is not None else None
                self._add_image(para, (rid, float(m.group(1)) if m else 0, False, None))

    @staticmethod
    def _add_image(para, image):
        para.images.append(image)
        if not image[2]:
            # 行内の画像は、段落の中の位置に目印を置く（目印の所で段落を分け、画像の行を置く。画像の後ろに改行で
            # キャプションを続けた段落でも、画像とキャプションの順が変わらないように）
            para.chars.append((IMAGE_AT, len(para.images) - 1))

    def _para(self, p):
        ppr_el = p.find(W + "pPr")
        st = ppr_el.find(W + "pStyle") if ppr_el is not None else None
        sid = st.get(W + "val") if st is not None else None
        ppr = self.styles.ppr(sid).merged(_read_ppr(ppr_el))
        para = _Para(ppr=ppr)
        mark_rpr = ppr_el.find(W + "rPr") if ppr_el is not None else None
        if mark_rpr is not None:
            para.mark_deleted = mark_rpr.find(W + "del") is not None
            para.mark_hidden = bool(_on(mark_rpr.find(W + "vanish")))
            if para.mark_deleted or mark_rpr.find(W + "ins") is not None:
                self.rep.revisions = True

        def in_toc():
            return any(f[2] == "TOC" for f in self._field)
        before = in_toc()
        self._runs(p, para, self.styles.rpr(sid or self.styles.default_p))
        para.toc = before or in_toc()
        numbered = bool(ppr.num_id and ppr.num_id != "0")
        label, bullet = self.numbering.label(ppr.num_id, ppr.ilvl or 0) if numbered else ("", False)
        if ppr.outline is not None and 0 <= ppr.outline <= 8:
            para.level = ppr.outline + 1
        elif numbered and (label or bullet):
            para.list_kind = BULLET if bullet else NUMBER
            para.label = "" if bullet else label
        if ppr_el is not None and ppr_el.find(W + "sectPr") is not None:
            para.section_after = True
            if self.section is None:
                self.section = ppr_el.find(W + "sectPr")
        return para

    def _add_para(self, para):
        prev = self.items[-1] if self.items else None
        if isinstance(prev, _Para) and prev.mark_deleted:
            # 前の段落の段落記号を削除した：すべて承諾した後と同じく、つないで1つの段落にする。残る段落記号は後の段落の
            # ものなので、段落の書式（配置・インデント・スタイル）は後の段落のものを使う
            shift = len(prev.images)
            para.chars = prev.chars + [(c, f + shift) if c == IMAGE_AT else (c, f) for c, f in para.chars]
            para.images = prev.images + para.images
            para.page_break_after += prev.page_break_after
            para.section_after = para.section_after or prev.section_after
            if prev.ppr.page_break_before:
                para.ppr = replace(para.ppr, page_break_before=True)
            self.items[-1] = para
            return
        if para.mark_hidden and not any(c != IMAGE_AT and not c.isspace() for c, _ in para.chars) and not para.images:
            return              # 段落ごと隠した段落（空の行にもしない）
        self.items.append(para)

    def _cell_text(self, tc):
        texts = []
        for el in tc:
            if el.tag == W + "p":
                para = self._para(el)
                self.rep.cell_images += len(para.images)
                texts.append("".join(c for c, _ in para.chars if c != IMAGE_AT))
            elif el.tag == W + "tbl":
                texts += ["　".join(row) for row in self._table(el)]
            elif el.tag == W + "sdt":
                c = el.find(W + "sdtContent")
                if c is not None:
                    texts.append(self._cell_text(c))
        return "　".join(t.replace("\t", "　").replace("\n", "　").strip() for t in texts if t.strip())

    def _table(self, tbl):
        rows = []
        for tr in tbl.findall(W + "tr"):
            trpr = tr.find(W + "trPr")
            if trpr is not None and trpr.find(W + "del") is not None:
                self.rep.revisions = True
                continue                # 変更履歴で削除した行（すべて承諾した後と同じく、取り込まない）
            row = []
            for tc in tr.findall(W + "tc"):
                tcpr = tc.find(W + "tcPr")
                span = max(1, _int(tcpr.find(W + "gridSpan") if tcpr is not None else None, "val", 1))
                vm = tcpr.find(W + "vMerge") if tcpr is not None else None
                cont = vm is not None and vm.get(W + "val") in (None, "continue")
                text = self._cell_text(tc)
                row.append("" if cont else text)
                row += [""] * (span - 1)
            if row:
                rows.append(row)
        return rows

    def _body(self, el):
        for x in el:
            if x.tag == W + "p":
                self._add_para(self._para(x))
            elif x.tag == W + "tbl":
                rows = self._table(x)
                if rows:
                    self.items.append(("table", rows))
            elif x.tag == W + "sectPr":
                self.final_section = x
            elif x.tag in (W + "sdt", W + "customXml"):
                c = x.find(W + "sdtContent") if x.tag == W + "sdt" else x
                if c is not None:
                    self._body(c)

    def read(self):
        self._body(self.doc.find(W + "body"))
        if self.section is None:
            self.section = self.final_section
        return self

    # ヘッダー・フッター
    def header_footer(self):
        """最初のセクションのヘッダー・フッター {"header"/"footer": (段落の字と配置のリスト, ページ番号があるか, 配置)}。
        ヘッダーは、最初のページだけ別のもの（titlePg）があればそれを、なければ既定のものを使う。"""
        sect, out = self.section, {}
        if sect is None:
            return out
        title_pg = bool(_on(sect.find(W + "titlePg")))
        for kind in ("header", "footer"):
            refs = {r.get(W + "type", "default"): r.get(R + "id") for r in sect.findall(f"{W}{kind}Reference")}
            rid = refs.get("first") if kind == "header" and title_pg and refs.get("first") else refs.get("default")
            typ, name, external = self.rels.get(rid, (None, None, True))
            root = self._part(name) if typ == kind and not external else None
            if root is None:
                continue
            saved, self._field = self._field, []
            lines, jc = [], None
            for p in root.iter(W + "p"):
                para = self._para(p)
                t = "".join(c for c, _ in para.chars if c != IMAGE_AT).replace("\t", "　").replace("\n", "　").strip()
                if t:
                    lines.append((t, para.ppr.jc))
                jc = jc or para.ppr.jc
            self._field = saved
            instr = " ".join(x.text or "" for x in root.iter(W + "instrText")) + " ".join(
                x.get(W + "instr") or "" for x in root.iter(W + "fldSimple"))
            out[kind] = (lines, bool(re.search(r"\bPAGE\b", instr.upper())), jc)
        return out

    # 画像
    def picture(self, rid, crop):
        """画像を、［画像］と同じく付加情報を除いて作り直したもの。読めなければ None。"""
        typ, name, external = self.rels.get(rid, (None, None, True))
        if external or typ != "image":
            return None
        try:
            data = self._read(name)
            if data is None:
                return None
            im = Image.open(io.BytesIO(data))
            im.load()
            if crop and any(crop):
                w, h = im.size
                l, t, r, b = (max(0, min(100000, v)) for v in crop)
                box = (round(w * l / 100000), round(h * t / 100000), round(w * (1 - r / 100000)),
                       round(h * (1 - b / 100000)))
                if box[2] > box[0] and box[3] > box[1]:
                    im = im.crop(box)
            return images.from_image(im)
        except (OSError, ValueError, Image.DecompressionBombError, images.NotImage):
            return None


# ---------- Layout にする ----------

def _layout(rd):
    sect = rd.final_section if rd.final_section is not None else rd.section
    pg = sect.find(W + "pgSz") if sect is not None else None
    mar = sect.find(W + "pgMar") if sect is not None else None
    width, height = _int(pg, "w", 11906) / 20, _int(pg, "h", 16838) / 20
    left = _int(mar, "left", 1701) / 20
    right = width - _int(mar, "right", 1701) / 20
    size = rd.styles.rpr(rd.styles.default_p).size or 10.5     # 標準のスタイルの字の大きさ
    grid = sect.find(W + "docGrid") if sect is not None else None
    pitch = size
    if grid is not None and grid.get(W + "type") in ("linesAndChars", "snapToChars"):
        pitch = size + _int(grid, "charSpace", 0) / 4096
    if pitch <= 0:
        pitch = size
    line_numbers = sect is not None and sect.find(W + "lnNumType") is not None
    blocks, blank = [], 0

    def chars_of(twip, hundredths):
        if hundredths is not None:
            return hundredths / 100
        return twip / 20 / pitch if twip is not None else 0.0

    for it in rd.items:
        if isinstance(it, tuple):
            blocks.append(pm.Block(kind=pm.TABLE, cells=it[1], blank=blank))
            blank = 0
            continue
        p = it
        if p.ppr.page_break_before and blocks:
            blocks.append(pm.Block(kind=pm.PAGE_BREAK))
            blank = 0
        if p.toc:
            # 目次の項目の形（点線とページ番号）の行にして、PDF と同じく [TOC] にまとめさせる（組むときに作り直す）
            blocks.append(pm.Block(rows=[pm.Row(0, 0, left, right, size, [(c, 0) for c in "目次...... 1"])],
                                   blank=blank))
            blank = 0
        else:
            pieces, cur = [], []
            for c, f in p.chars:
                if c == "\n":
                    pieces.append(cur)
                    cur = []
                    rd.rep.breaks += 1
                elif c == IMAGE_AT:
                    pieces += [cur, f]
                    cur = []
                else:
                    cur.append(("　", f) if c == "\t" else (c, f))
            pieces.append(cur)
            # 浮動の画像は、置き場所が段落の中の位置で決まらないので、段落の後ろに置く
            pieces += [k for k, im in enumerate(p.images) if im[2]]
            if not any(isinstance(x, int) or "".join(c for c, _ in x).strip() for x in pieces):
                blank += 1
            else:
                ppr = p.ppr
                lft = chars_of(ppr.left, ppr.left_chars)
                fst = chars_of(ppr.first, ppr.first_chars)
                rgt = chars_of(ppr.right, ppr.right_chars)
                align = {"center": pm.CENTER, "right": pm.RIGHT, "end": pm.RIGHT}.get(ppr.jc, pm.LEFT)
                first = True
                for chars in pieces:
                    if isinstance(chars, int):
                        b = _image_block(rd, p, p.images[chars], left, right, pitch)
                        if b is not None:
                            b.blank, blank = blank, 0
                            blocks.append(b)
                        continue
                    if not "".join(c for c, _ in chars).strip():
                        continue
                    rows = [pm.Row(0, 0, left + (lft + fst) * pitch, right - rgt * pitch, size, chars)]
                    if lft or fst:
                        # 2行目以降の頭の位置を、字下げ・左インデントの記号で戻せるように、2行目を置く
                        rows.append(pm.Row(0, 0, left + lft * pitch, right - rgt * pitch, size, []))
                    blocks.append(pm.Block(rows=rows, blank=blank, align=align, first=fst, indent=lft,
                                           level=p.level if first else 0, list_kind=p.list_kind if first else "",
                                           label=p.label if first else ""))
                    first, blank = False, 0
        for _ in range(p.page_break_after):
            blocks.append(pm.Block(kind=pm.PAGE_BREAK))
            blank = 0
        if p.section_after:
            blocks.append(pm.Block(kind=pm.PAGE_BREAK))
            blank = 0
    while blocks and blocks[-1].kind == pm.PAGE_BREAK:
        blocks.pop()            # 文書の終わりのセクション区切り・改ページ
    return pm.Layout(blocks, (width, height), left, right, pitch, size, PAGE_NUMBER_NONE, line_numbers,
                     rd.rep.pictures > 0)


def _image_block(rd, p, image, left, right, pitch):
    """画像の行（[IMAGE n]{幅}）の段落。画像を取り込めなければ None（数えて知らせる）。"""
    rid, width_pt, floating, crop = image
    if len(rd.pictures) >= IMAGE_MAX:
        rd.rep.too_many += 1
        return None
    pic = rd.picture(rid, crop)
    if pic is None:
        rd.rep.unreadable += 1
        return None
    n = len(rd.pictures) + 1
    rd.pictures[n] = pic
    rd.rep.pictures += 1
    rd.rep.floating += floating
    # 幅は、Word で置いた幅を字数にする（1行の字数を超えない。画像の行の幅の記号は 99 字まで）
    chars = max(1, min(99, round((right - left) / pitch), round(width_pt / pitch))) if width_pt > 0 else None
    lead = {"center": ":-: ", "right": "--: ", "end": "--: "}.get(p.ppr.jc, "")
    return pm.Block(kind=pm.IMAGE, line=f"{lead}[IMAGE {n}]" + (f"{{{chars}}}" if chars else ""))


_ALIGN_LEAD = {"center": ":-: ", "right": "--: ", "end": "--: "}
_PAGE_ONLY_RE = re.compile(r"[-－−―‐ー–—\s]*[0-9０-９]+[-－−―‐ー–—\s]*")


def _areas(hf):
    """ヘッダー・フッターの行（[HEADER] ・[FOOTER] ）と、ページ番号の位置。"""
    lines, page_number = [], PAGE_NUMBER_NONE
    for kind, mark in (("header", "[HEADER] "), ("footer", "[FOOTER] ")):
        found = hf.get(kind)
        if not found:
            continue
        paras, has_page, jc = found
        for text, pjc in paras:
            if has_page and _PAGE_ONLY_RE.fullmatch(text):
                # ページ番号だけの段落は、文書の設定のページ番号の位置にする
                if kind == "header":
                    page_number = PAGE_NUMBER_TOP_RIGHT
                elif pjc in ("right", "end"):
                    page_number = PAGE_NUMBER_BOTTOM_RIGHT
                else:
                    page_number = (PAGE_NUMBER_BOTTOM_CENTER_DECORATED if re.search(r"[-－−―‐ー–—]", text)
                                   else PAGE_NUMBER_BOTTOM_CENTER)
                continue
            lines.append(mark + _ALIGN_LEAD.get(pjc, "") + text)
    return lines, page_number


# ---------- 変換する ----------

@dataclass
class DocxConverted:
    """変換の結果。"""
    text: str               # 入力欄に入れる文章（マークダウン）
    settings: object        # 文書の設定（vamd.Settings）
    headings: int           # 記号にした見出し・箇条書き・段落番号の数
    pictures: dict          # 画像の番号 → images.Picture（Session.images に入れる）
    report: Report          # 取り込まなかったもの（notices で知らせる文にする）


def convert(data, settings):
    """Word の文書（.docx のバイト列）を、マークダウンにする。settings は今の文書の設定（vamd.Settings）。
    読めなければ DocxError。"""
    rd = _Reader(data).read()
    layout = _layout(rd)
    hf = rd.header_footer()
    area_lines, page_number = _areas(hf)
    # 文書の種類：用紙・余白・1行の字数が合う種類があれば、その中から。なければ、Word の見出しのレベルがある文書は今の
    # 設定の種類（見出しのレベルから記号にするので、どの種類でも記号の数が同じになり、選べないため）、ない文書は、PDF と
    # 同じく、手で打った番号がいちばん多く当たる種類
    has_levels = any(b.level for b in layout.blocks)
    keys = (pm._geometry_types(layout) or ([settings.doc_type] if has_levels else
                                           [k for k in DOC_TYPES if k != WEB or settings.doc_type == WEB]))
    best = None
    for key in keys:
        lines, marks, exact = pm.to_markdown(layout, doc_type_for(key, settings.one_width))
        score = (marks, key == settings.doc_type, exact)
        if best is None or score > best[0]:
            best = (score, key, lines)
    (marks, _, _), key, lines = best
    # ページ番号・行番号は、Word の文書のとおりにする（ページ番号のフィールドがなければ、ページ番号なし）
    new = replace(settings, doc_type=key, page_number=page_number, line_numbers=layout.line_numbers)
    text = "\n".join(area_lines + lines).strip("\n")
    return DocxConverted(text, new.normalized(), marks, rd.pictures, rd.rep)


def notices(rep):
    """開いたときに知らせる文（取り込まなかったもの・変えたもの。2026-11-24 班長決定）。なければ空のリスト。"""
    out = []
    if rep.revisions:
        out.append("変更履歴は、すべて承諾した後の字を取りました（削除した字・行は取り込んでいません）。")
    skipped = [f"{name} {n} {unit}" for name, n, unit in (
        ("コメント", rep.comments, "個"), ("隠し文字", rep.hidden, "字"), ("脚注・文末脚注", rep.footnotes, "個"),
        ("テキストボックス・図形の中の字", rep.textboxes, "か所"), ("記号の書体（Wingdings など）の字", rep.symbols, "字"),
        ("グラフ・図形", rep.drawings, "個"), ("読めない形式の画像（EMF など）", rep.unreadable, "個"),
        ("文書の外にリンクした画像", rep.linked, "個"), ("表の中の画像", rep.cell_images, "個"),
        (f"{IMAGE_MAX} を超えた画像", rep.too_many, "個")) if n]
    if skipped:
        out.append("次のものは取り込んでいません：" + "、".join(skipped) + "。")
    if rep.pictures:
        s = f"画像 {rep.pictures} 個を取り込みました"
        if rep.floating:
            s += f"（文字列の折り返しを指定した画像 {rep.floating} 個は、置いてあった段落の後ろに置きました）"
        out.append(s + "。")
    if rep.breaks:
        out.append(f"段落の中の改行 {rep.breaks} か所は、段落を分けました。")
    return out
