"""MIT License で配るための確かめ（Ver300、2026-11-14 班長決定）。

・配るプログラム（src\\va_document）は PyMuPDF（AGPL-3.0）を読み込まない。読み込むと、exe に入り、全体を AGPL で配る
  ことになる（仕様.md の 11）。PyMuPDF を使ってよいのは、開発のときのスクリプト（scripts\\make_icons.py）と試作だけ。
・アイコンの PNG（scripts\\make_icons.py で作るもの）が、今の SVG・配色から作ったものであること。
"""
import json
import subprocess
import sys
from pathlib import Path

from va_document import icons, theme

ROOT = Path(__file__).resolve().parents[1]


def test_program_does_not_import_pymupdf():
    src = ROOT / "src" / "va_document"
    for path in src.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import fitz" not in text and "import pymupdf" not in text, path.name
    # 画面を含め、すべてのモジュールを読み込んでも、PyMuPDF が読み込まれない
    code = ("import pkgutil, importlib, sys, va_document\n"
            "for m in pkgutil.iter_modules(va_document.__path__):\n"
            "    importlib.import_module('va_document.' + m.name)\n"
            "print('fitz' in sys.modules or 'pymupdf' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_icon_png_is_up_to_date():
    """PNG を作ったときの色が theme.py と同じで、使うアイコンがすべて入っている（違えば
    python scripts\\make_icons.py で作り直す）。"""
    index = json.loads((icons.PNG_DIR / "index.json").read_text(encoding="utf-8"))
    assert index["colors"] == {"TEXT": theme.TEXT, "ICON_TINT": theme.ICON_TINT, "DISABLED_TEXT": theme.DISABLED_TEXT,
                               "ICON_TINT_DISABLED": theme.ICON_TINT_DISABLED}
    svgs = sorted(p.stem for p in icons.ICON_DIR.glob("*.svg") if not p.stem.endswith(("_filled", "_large")))
    assert index["normal"] == index["disabled"] == svgs
    assert index["large"] == sorted(p.stem[:-6] for p in icons.ICON_DIR.glob("*_large.svg"))
    assert set(icons.BUTTON_ICONS.values()) <= set(svgs)
    for kind, sizes in (("normal", icons.SMALL_SIZES + (icons.BASE_SMALL,)),
                        ("disabled", icons.SMALL_SIZES + (icons.BASE_SMALL,)),
                        ("large", icons.LARGE_SIZES + (icons.BASE_LARGE,))):
        for size in sizes:
            from PIL import Image
            with Image.open(icons.PNG_DIR / f"{kind}_{size}.png") as im:
                assert im.size == (size * len(index[kind]), size), (kind, size)
    # 描いておいた大きさはそのまま、ほかの大きさは縮めて、どれも指定の大きさになる
    for size in (16, 18, 24, 30, 32, 44, 128, 150):
        assert icons.icon_image("save", size).size == (size, size)
        assert icons.icon_image("save", size, large=True).size == (size, size)
    assert icons.icon_image("print", 32, large=True) is None        # 色付きのアイコンのないもの
