"""ボタンのアイコンを、SVG（src\\va_document\\icons\\*.svg）から PNG にする（開発のときに使う。Ver300、2026-11-14）。

VA Document は、起動のたびに PyMuPDF で SVG を画像にしていたが、PyMuPDF は AGPL-3.0 なので、Ver300 で配るものから
外した（VA Document を MIT License にするため。2026-11-14 班長決定）。VA Case の scripts\\make_icons.py と同じく、開発の
ときに一度 PNG にして src\\va_document\\icons\\png\\ に入れ、起動したときは Pillow で読む（icons.py）。このスクリプトだけが
PyMuPDF を使う（開発の PC にあるもの。requirements.txt には入れない）。

・色は今と同じ2色（塗りつぶし版〔<名前>_filled.svg〕を薄い青で下に敷き、線画を濃い色で重ねる。押せないときは灰色）。
  大きいボタンの色付きのアイコン（<名前>_large.svg）は、SVG に書いた色のまま。
・画面の拡大率ごとの大きさ（SMALL_SIZES・LARGE_SIZES）は、その大きさで描く（縮めると線がぼやけるため。替える前と同じ
  画素になる）。それ以外の大きさは、いちばん大きいもの（BASE）を起動したときに縮める。
・大きさごとに、全部のアイコンを横に並べた1枚の PNG にする（<種類>_<大きさ>.png。種類は normal・disabled・large）。
  並びと、描いたときの色は index.json に書く（色が theme.py と違えば、試験が知らせる。test_icons.py）。

使い方：python scripts\\make_icons.py      （theme.py の色・SVG を変えたら、作り直してコミットする）
"""
import json
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF（開発のときだけ）
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from va_document import theme  # noqa: E402
from va_document.icons import BASE_LARGE, BASE_SMALL, ICON_DIR, LARGE_SIZES, PNG_DIR, SMALL_SIZES  # noqa: E402

SVG_FILL = "#212121"


def _body(svg):
    return re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)


def _png(svg, size):
    with fitz.open(stream=svg.encode("utf-8"), filetype="svg") as doc:
        page = doc[0]
        zoom = size / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True)
        return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)


def small_svg(name, color, tint):
    """線画を color、塗りつぶし版を tint にした SVG（替える前の icons.render_png と同じ）。"""
    svg = (ICON_DIR / f"{name}.svg").read_text(encoding="utf-8").replace(SVG_FILL, color)
    filled = ICON_DIR / f"{name}_filled.svg"
    if filled.exists():
        head = re.match(r"<svg[^>]*>", svg).group(0)
        svg = head + _body(filled.read_text(encoding="utf-8")).replace(SVG_FILL, tint) + _body(svg) + "</svg>"
    return svg


def names():
    return sorted(p.stem for p in ICON_DIR.glob("*.svg") if not p.stem.endswith(("_filled", "_large")))


def main():
    PNG_DIR.mkdir(exist_ok=True)
    for old in PNG_DIR.glob("*.png"):
        old.unlink()
    small = names()
    large = [n for n in small if (ICON_DIR / f"{n}_large.svg").exists()]
    kinds = {"normal": (small, lambda n: small_svg(n, theme.TEXT, theme.ICON_TINT), SMALL_SIZES + (BASE_SMALL,)),
             "disabled": (small, lambda n: small_svg(n, theme.DISABLED_TEXT, theme.ICON_TINT_DISABLED),
                          SMALL_SIZES + (BASE_SMALL,)),
             "large": (large, lambda n: (ICON_DIR / f"{n}_large.svg").read_text(encoding="utf-8"),
                       LARGE_SIZES + (BASE_LARGE,))}
    total = 0
    for kind, (ns, make, sizes) in kinds.items():
        for size in sizes:
            sheet = Image.new("RGBA", (size * len(ns), size), (0, 0, 0, 0))
            for i, n in enumerate(ns):
                sheet.paste(_png(make(n), size), (i * size, 0))
            sheet.save(PNG_DIR / f"{kind}_{size}.png", optimize=True)
            total += 1
    index = {"normal": small, "disabled": small, "large": large,
             "colors": {"TEXT": theme.TEXT, "ICON_TINT": theme.ICON_TINT, "DISABLED_TEXT": theme.DISABLED_TEXT,
                        "ICON_TINT_DISABLED": theme.ICON_TINT_DISABLED}}
    (PNG_DIR / "index.json").write_bytes(json.dumps(index, ensure_ascii=False, indent=1).encode("utf-8") + b"\n")
    size = sum(p.stat().st_size for p in PNG_DIR.iterdir())
    print(f"{total} 枚の PNG（アイコン {len(small)} 個、大きいボタンの色付き {len(large)} 個）と index.json。{size:,} バイト")


if __name__ == "__main__":
    main()
