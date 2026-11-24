"""文書の種類ごとの書式の設定（VA公用文 cstSettings.bas の値を写したもの。仕様.md の6）。

VA公用文の版が上がって値が変わったら、ここを写し直す。値の意味は cstSettings.bas の冒頭の説明と同じ。
"""
from dataclasses import dataclass, replace

# 番号スタイル（VA公用文の値）→ 字の種類
_STYLE = {14: "fw", 0: "hw", 20: "kana", 12: "hwkana", 4: "alpha", 2: "roman", 18: "circled"}

MM = 72 / 25.4                  # 1mm のポイント数（余白などは mm で持つ）
FONT_SIZE = 12                  # 字の大きさ（ポイント。VA公用文 cstSettings.sngFont）

# 表題の配置
TITLE_CENTER, TITLE_JUSTIFY, TITLE_LEFT = "center", "justify", "left"


@dataclass(frozen=True)
class DocType:
    """1つの文書の種類の書式。"""
    key: str                        # VA公用文の文書の種類の名前（Saiban など）
    label: str                      # 画面に出す名前
    margins: tuple                  # 余白（mm）（上, 下, 左, 右）
    chars_lines: tuple              # 文字数, 行数
    number_formats: tuple           # 見出しの番号書式（%n をレベル n の番号に置き換える）
    number_styles: tuple            # 番号の字の種類
    heading_left: tuple             # 見出しの左インデント（字）
    heading_first: tuple            # 見出しの最初の行のインデント（字）
    text_left: tuple                # 本文の左インデント（字）
    text_first: tuple               # 本文の最初の行のインデント（字）
    left_add: int                   # 階層ごとに増やす左インデント（字）
    title_align: str                # 表題の配置
    title_indent: int               # 表題のインデント（字。両端揃えのとき前後に空ける字数）
    reset_on: tuple = tuple(range(9))   # リスト開始レベル（0：振り直さない）
    start_at: tuple = (1,) * 9          # 開始番号
    list_bullet: str = "・"         # 箇条書きの記号
    list_number: str = "%1　"       # 段落番号の書式
    list_number_style: str = "circled"
    list_left: int = 1              # リストの、見出しからの左インデントの増加量（字）
    list_first: int = -1            # リストの最初の行のインデント（字）
    one_width: bool = False         # 見出し番号を全角1字の幅に縮める（one_width_type。2026-10-26 班長指示）
    # 字の形（2026-11-24 のリファクタリング。VA公用文の7種類は、ＭＳ 明朝 12pt のまま）
    font_size: float = FONT_SIZE    # 字の大きさ（ポイント）
    gothic: bool = False            # 本文をゴシックで描く（太字は、ゴシックを太らせて描く。pdfwriter）
    heading_scale: tuple = (1.0,) * 9   # 見出しの字の大きさの倍率（レベルごと。行の高さに収まる大きさにする）
    heading_rules: tuple = ()       # 見出しの下に線を引くレベル
    web: bool = False               # ウェブ文書（見出しを太字にし、表題〔:=:〕を # の見出しと同じ見た目で組む。layout）


def _styles(s):
    return tuple(_STYLE[int(v)] for v in s.split(","))


def _nums(s):
    return tuple(float(v) for v in s.split(","))


_ONES = (1,) * 9
_SAIBAN_NUMBERS = ("第%1　", "%2　", "(%3) ", "%4　", "(%5) ", "%6　", "(%7) ", "%8　", "(%9) ")
_SAIBAN_STYLES = _styles("14,14,0,20,12,4,4,2,2")
_SAIBAN_HEADING_FIRST = _nums("-1,-1,-1,-1,-1,-.5,-1,-.5,-1")
_TECH_NUMBERS = tuple(".".join(f"%{k}" for k in range(1, n + 1)) + "." for n in range(1, 10))

DOC_TYPES = {d.key: d for d in (
    DocType("Saiban", "裁判所提出書類", (35, 27, 30, 17.5), (37, 26), _SAIBAN_NUMBERS, _SAIBAN_STYLES,
            _ONES, _SAIBAN_HEADING_FIRST, _ONES, _ONES, 1, TITLE_CENTER, 0),
    DocType("Naiyou", "内容証明", (30, 30, 30, 30), (19, 26),
            ("第%1　", "%2　", "（%3）", "%4　", "（%5）", "%6　", "（%7）", "%8　", "（%9）"),
            _styles("14,14,14,20,20,4,4,2,2"),
            _ONES, _nums("-1,-1,-1,-1,-1,-.5,-1.5,-.5,-1.5"), _ONES, _ONES, 1, TITLE_CENTER, 0),
    DocType("Kouyou", "公用文", (25, 20, 25, 20), (40, 40), _SAIBAN_NUMBERS, _SAIBAN_STYLES,
            _ONES, _SAIBAN_HEADING_FIRST, _ONES, _ONES, 1, TITLE_JUSTIFY, 3),
    DocType("Keiyaku1", "契約書1（法令型）", (25, 20, 25, 20), (40, 40),
            ("", "第%2条　", "%3　", "（%4）", "%5　", "", "", "", ""),
            _styles("0,14,14,14,20,0,0,0,0"),
            _nums("1,1,1,3,4,0,0,0,0"), _nums("0,-1,-1,-2,-1,0,0,0,0"), _ONES, _ONES, 0, TITLE_JUSTIFY, 3,
            reset_on=(0, 0, 2, 3, 4, 5, 6, 7, 8), start_at=(1, 1, 2, 1, 1, 1, 1, 1, 1)),
    DocType("Keiyaku2", "契約書2（実務型）", (25, 25, 25, 25), (38, 38),
            ("第%1条", "%2　", "(%3) ", "%4　", "", "", "", "", ""),
            _styles("14,14,0,20,0,0,0,0,0"),
            _nums("1,1,1,1,0,0,0,0,0"), _nums("-1,-1,-1,-1,0,0,0,0,0"),
            _nums("0,1,1,1,1,1,1,1,1"), _ONES, 1, TITLE_CENTER, 0),
    DocType("Business", "ビジネス文書", (25, 25, 25, 25), (38, 38),
            ("第%1 ", "%2　", "(%3) ", "%4　", "(%5) ", "%6　", "(%7) ", "%8　", "(%9) "),
            _styles("0,0,0,20,20,4,4,2,2"),
            _ONES, _nums("-1,-.5,-1,-1,-1.5,-.5,-1,-.5,-1"), _ONES, _ONES, 1, TITLE_CENTER, 0),
    DocType("Technical", "技術文書", (25, 25, 25, 25), (38, 38), _TECH_NUMBERS, _styles("0,0,0,0,0,0,0,0,0"),
            (0,) * 9, (0,) * 9, (0,) * 9, (0,) * 9, 0, TITLE_LEFT, 0,
            list_bullet="-", list_number="%1)", list_number_style="alpha", list_left=0, list_first=0),
    # ウェブ文書（2026-11-24 班長決定。ウェブに載せる文章の下書き）：VA公用文にはない種類。見出しの見た目は Markdown の
    # プレビュー（GitHub・VS Code など）にならう：見出しの番号・インデントはなく、見出しは太字で、大きさで段を分け、# と ## の
    # 下に線を引く。表題（:=:）は # の見出しと同じ見た目で組む（見出しとしては扱わない）。見出しのほかの記号（配置・->N・ヘッダー・改ページ・目次・画像・
    # 蛍光ペン・傍点・均等割付・表・箇条書き・段落番号）は、ビジネス文書と同じに扱う（同日 班長指示）。本文はゴシックで、
    # 字下げはなく、行の間を広めにする（行送りは字の大きさの約 1.85 倍）。字の大きさと1行の字数は、ウェブの記事の1行
    # （40字ほど）に合わせる
    DocType("Web", "ウェブ文書", (25, 25, 25, 25), (40, 36), ("",) * 9, _styles("0,0,0,0,0,0,0,0,0"),
            (0,) * 9, (0,) * 9, (0,) * 9, (0,) * 9, 0, TITLE_LEFT, 0,
            font_size=11, gothic=True, heading_scale=(1.5, 1.3, 1.15) + (1.0,) * 6, heading_rules=(1, 2),
            web=True),
)}
DEFAULT_DOC_TYPE = "Saiban"   # 既定の文書の種類（裁判所提出書類）
NAIYOU = "Naiyou"             # 内容証明（行番号・ヘッダー・フッターを付けない。naiyou.py の確かめをする）
WEB = "Web"                   # ウェブ文書（行番号を付けない。ウェブの Markdown にある記号だけを読む）


def can_one_width(dt):
    """見出し番号を1字の幅にできる文書の種類か（左インデントの増加量が1字のもの。契約書1・技術文書は「第12条」
    「1.2.3.」のような番号で1字に収まらず、複合見出しも使えないので、できないことにする）。"""
    return dt.left_add == 1


def one_width_type(dt):
    """見出し番号を全角1字の幅に縮める書式（VA疑似アウトラインの「数字を全角1文字扱いにする」と同じ形。2026-10-26
    班長指示。複合見出しで、番号の幅がそろわないと上下の字がそろわないため）。番号の後ろは全角空白にし、見出しの
    最初の行のインデントはどの段も -1 字にする（番号1字＋空白1字の後から本文が始まり、折り返した行は番号の
    1字右から始まる）。番号の字を縮めるのは行組み（layout.Typesetter.squeeze_items）で行う。"""
    if not can_one_width(dt):
        return dt
    formats = tuple(f.rstrip(" 　") + "　" if f else f for f in dt.number_formats)
    return replace(dt, number_formats=formats, heading_first=(-1,) * 9, one_width=True)


def doc_type_for(key, one_width=False):
    """文書の種類のキーと、見出し番号を1字の幅にするかから、書式を返す。"""
    dt = DOC_TYPES[key]
    return one_width_type(dt) if one_width else dt


# ページ番号の位置（VA公用文 basSetup.ConfigHeaderFooter の選択肢）
PAGE_NUMBER_NONE, PAGE_NUMBER_TOP_RIGHT = "None", "TopRight"
PAGE_NUMBER_BOTTOM_CENTER, PAGE_NUMBER_BOTTOM_CENTER_DECORATED = "BottomCenter", "BottomCenterDecorated"
PAGE_NUMBER_BOTTOM_RIGHT = "BottomRight"
# 画面と構文ファイルの区切りの行に出す名前（VA公用文のセットアップ画面の呼び方）
PAGE_NUMBER_LABELS = {PAGE_NUMBER_NONE: "なし", PAGE_NUMBER_TOP_RIGHT: "右上", PAGE_NUMBER_BOTTOM_CENTER: "中下",
                      PAGE_NUMBER_BOTTOM_CENTER_DECORATED: "中下（飾り）", PAGE_NUMBER_BOTTOM_RIGHT: "右下"}

FW_DIGITS = "０１２３４５６７８９"
KANA = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン"
HW_KANA = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝ"
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
ROMAN = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x")


def number_text(style, n):
    """番号の字の種類に応じて、n を文字列にする。"""
    if style == "fw":
        return "".join(FW_DIGITS[int(d)] for d in str(n))
    if style == "hw":
        return str(n)
    if style == "kana":
        return KANA[n - 1]
    if style == "hwkana":
        return HW_KANA[n - 1]
    if style == "alpha":
        return "abcdefghijklmnopqrstuvwxyz"[n - 1]
    if style == "roman":
        return ROMAN[n - 1]
    if style == "circled":
        return CIRCLED[n - 1]
    raise ValueError(style)
