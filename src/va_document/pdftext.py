"""PDF の字を読む（構文ファイルとの突き合わせ〔recover.py〕と、構文ファイルのない PDF の取り込み〔session.open_pdf〕）。
構文ファイルのない PDF は、ふつうは pdfmarkdown.py でマークダウンにする。plain_text は、それが読み取りに失敗したとき
だけ使う（2026-11-24）。

pdfplumber（MIT。pdfminer.six）を使う。外部と通信しない。Ver300（2026-11-14 班長決定）で、PyMuPDF（AGPL-3.0）から
替えた（VA Document を MIT License にするため）。
・pdf_chars：ページごとに、PDF に描いた順の字と位置。替える前（PyMuPDF の get_texttrace）と、今の版と前の版
  （Ver200〜Ver291）で作った 496 の PDF、約 123 万字で、字の並びがすべて一致し、位置の差は 0.0001pt 以内だった
  （試作\\pdf_chars_backends.py）。全角空白も、描いたとおりに読める（pypdfium2 は全角空白を半角空白に替えるので使わない）。
・plain_text：ほかのソフトで作った PDF の文字を、段落（行をつないだもの）ごとに取り出す（試作\\plain_text_compare.py の
  plumber2。手元の 242 の PDF で、替える前と比べた）。
"""
import io
import unicodedata
from pathlib import Path

import pdfplumber

GAP = 1.0       # 行の中で、字と字の間が字の大きさのこの倍より広ければ、半角空白を補う（描いていない空白）
JOIN = 0.5      # 行と行の間が行の高さのこの倍以下なら、同じ段落としてつなぐ


def _open(path):
    # ファイルを開いたままにしない（読み終えたら閉じ、保存し直しを妨げない）
    return pdfplumber.open(io.BytesIO(Path(path).read_bytes()))


def pdf_chars(path):
    """ページごとの [(字, 字の左端, 基準線)] のリスト。位置はポイントで、基準線は用紙の上端から。PDF に描いた順。"""
    out = []
    with _open(path) as pdf:
        for page in pdf.pages:
            h = page.height
            out.append([(c["text"], c["matrix"][4], h - c["matrix"][5]) for c in page.chars])
    return out


def _kangxi(s):
    """康熙部首（U+2F00〜U+2FDF。書体の対応表によっては「一」がこの字になる）を、ふつうの漢字に戻す。"""
    return "".join(unicodedata.normalize("NFKC", ch) if 0x2F00 <= ord(ch) <= 0x2FDF else ch for ch in s)


def plain_text(path):
    """PDF の文字を、段落ごとに1行にして返す（見出し・配置は戻さない）。

    字を基準線で行にまとめ、行の中は左から並べる。字と字の間が広くあいていて、どちらも空白でなければ半角空白を補う。
    行と行の間が狭く、次の行が前の行より左に出ていなければ、同じ段落としてつなぐ。ページの外の字（はみ出した表など、
    見えない字）と、数字だけの段落（ページ番号）は除く。描いた全角空白は、そのまま残す。"""
    paras = []
    with _open(path) as pdf:
        for page in pdf.pages:
            x0, top0, x1, bottom0 = page.bbox
            rows = {}
            for c in page.chars:
                if c["x1"] < x0 or c["x0"] > x1 or c["bottom"] < top0 or c["top"] > bottom0:
                    continue
                rows.setdefault(round(c["matrix"][5] * 2) / 2, []).append(c)     # 基準線（0.5pt 刻み）
            lines = []
            for key in sorted(rows, reverse=True):          # 上から（PDF の y は下から上へ増える）
                cs = sorted(rows[key], key=lambda c: c["x0"])
                out, prev = [], None
                for c in cs:
                    if prev is not None and c["x0"] - prev["x1"] > GAP * c["size"] and not c["text"].isspace() \
                            and not prev["text"].isspace():
                        out.append(" ")
                    out.append(c["text"])
                    prev = c
                lines.append((min(c["top"] for c in cs), max(c["bottom"] for c in cs), cs[0]["x0"],
                              _kangxi("".join(out))))
            lines.sort()
            block, prev = [], None
            for top, bottom, left, text in lines:
                if prev is not None:
                    ptop, pbottom, pleft = prev
                    h = max(bottom - top, pbottom - ptop)
                    if top - pbottom > JOIN * h or left < pleft - 0.5 * h:
                        paras.append("".join(s.strip() for s in block))
                        block = []
                block.append(text)
                prev = (top, bottom, left)
            if block:
                paras.append("".join(s.strip() for s in block))
    return "\n".join(p for p in paras if p and not p.isdigit())
