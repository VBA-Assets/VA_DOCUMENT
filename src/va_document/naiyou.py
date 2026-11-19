"""内容証明郵便の字数・行数のチェック（2026-10-24 班長指示）。

VA内容証明郵便（..\\..\\VA公用文シリーズ\\VA内容証明郵便\\basCheck.bas の CheckCharsAndLines）と同じ数え方をする。
準拠：「内容証明　ご利用の条件等」（日本郵便）。横書きの1行20字以内・1枚26行以内（VA内容証明郵便の既定）。
・1行ずつ字数を数える。全角・半角の空白と、閉じ括弧「）」「)」は数えない（括弧の対を1字とする決まりの簡易な扱い。
  VA内容証明郵便と同じ）。見出し・段落番号の番号は、組んだ字のとおりに数える（VA内容証明郵便は段落番号を「1字」と
  みなすが、番号の字を数えるほうが正確なため）。
・ページごとに、字のある行（数える字が1字以上の行）を数える。空の行は数えない。
・表は、セルの中の行ごとに字数を数え、行数は表の横の並び（同じ高さの行）1本を1行と数える。
・最初に見つかった所を返す（VA内容証明郵便と同じく、見つけた所で止める）。行数は、ページの字数を見終えてから比べる。
・画像（[IMAGE 1]{30}）があれば、字数・行数の後に知らせる。日本郵便の条件で、内容証明に図・画像を入れられるかを確かめるまでの扱い
  （2026-10-29 班長決定。検討_画像の挿入.md の13）。
VA Documentの「内容証明」は1行19字・26行の格子で組むので、超えるのは句読点のぶら下げのある行（20字。制限内）より
多い行、半角の英数字が多い行（半角も1字と数える）、表の中の行などに限られる。
"""
from collections import defaultdict
from dataclasses import dataclass

from .doctypes import NAIYOU
from .layout import FONT_SIZE

DOC_TYPE = NAIYOU        # 文書の種類「内容証明」（doctypes.DOC_TYPES のキー）
MAX_CHARS = 20
MAX_LINES = 26
NOT_COUNTED = set(" 　）)")


def count_chars(text):
    """内容証明の字数（空白と閉じ括弧を除く）。"""
    return sum(1 for ch in text if ch not in NOT_COUNTED)


@dataclass
class Problem:
    kind: str           # "chars"（1行の字数）・"lines"（1枚の行数）・"image"（画像）
    page: int           # 1 から
    count: int          # 字数・行数
    text: str           # その行の字（知らせるとき、どの行かが分かるように）
    x: float            # その行の1字目の位置（用紙の左上からのポイント。エディターのカーソルを動かすため）
    y: float

    def message(self):
        head = self.text if len(self.text) <= 24 else self.text[:24] + "…"
        if self.kind == "image":
            return (f"{self.page} ページに画像があります。内容証明に図・画像を入れられるかは、郵便局（日本郵便の"
                    "「内容証明　ご利用の条件等」）で確かめてください。")
        if self.kind == "chars":
            return (f"{self.page} ページの「{head}」の行が {self.count} 字です。"
                    f"内容証明は1行 {MAX_CHARS} 字までです（空白と閉じ括弧は数えません）。")
        return (f"{self.page} ページが {self.count} 行です。内容証明は1枚 {MAX_LINES} 行までです"
                f"（字のない行は数えません）。{MAX_LINES + 1} 行目は「{head}」の行です。")


def check(ts, lines):
    """組んだ結果（ts・lines）を確かめ、最初に見つかった Problem を返す。なければ None。"""
    pages = defaultdict(list)         # ページ → [(基準線, [行の中の字の並び（表はセルごと）], x, 位置の y)]
    for ln in lines:
        if not ln.glyphs:
            continue
        top = ts.margin_top + ln.row * ts.line_pitch
        text = "".join(g.ch for g in ln.glyphs)
        pages[ln.page].append((ts.baseline(ln.row), [text], ts.margin_left + ln.glyphs[0].x + 1,
                               top + ts.line_pitch / 2))
    for piece in ts.tables:
        rows = defaultdict(lambda: defaultdict(list))      # 基準線 → 列 → 字
        for g in piece.glyphs:
            rows[round(g.y, 2)][g.col].append(g)
        for y, cols in rows.items():
            first = min((g for gs in cols.values() for g in gs), key=lambda g: g.x)
            cells = ["".join(g.ch for g in sorted(gs, key=lambda g: g.x)) for _, gs in sorted(cols.items())]
            pages[piece.page].append((y, cells, ts.margin_left + first.x + 1, y - FONT_SIZE / 2))
    for page in sorted(pages):
        counted = 0
        for _, texts, x, y in sorted(pages[page], key=lambda t: t[0]):
            for text in texts:
                n = count_chars(text)
                if n > MAX_CHARS:
                    return Problem("chars", page, n, text, x, y)
            if any(count_chars(t) for t in texts):
                counted += 1
                if counted == MAX_LINES + 1:
                    over = Problem("lines", page, 0, " ".join(texts), x, y)
        if counted > MAX_LINES:
            over.count = counted
            return over
    # 画像は、字数・行数を確かめた後に知らせる（［このまま保存する］で、字数・行数の確かめを飛ばさないため）
    for piece in ts.images:
        return Problem("image", piece.page, 0, "", ts.margin_left + piece.x + 1, piece.y + 1)
    return None
