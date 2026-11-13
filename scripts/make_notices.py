"""VA Document が使っている部品のライセンスの表示（THIRD_PARTY_NOTICES.txt）を作る。

exe に入る部品（Python・Tcl/Tk・ReportLab・pypdf・pdfplumber・pdfminer.six・pypdfium2〔PDFium〕・fontTools・Pillow・
tkinterdnd2・tkdnd・PyInstaller のブートローダーと、それらが使う部品）と、
ボタンのアイコン（Fluent UI System Icons）のライセンスの全文を、いま入っている部品のファイルから集める。
部品の版を上げたら、作り直してコミットする。

実行のしかた：
    python scripts\\make_notices.py
"""

from __future__ import annotations

import importlib.metadata as metadata
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "THIRD_PARTY_NOTICES.txt"
PY_HOME = Path(sys.base_prefix)
# tkdnd の使用許諾は、tkdnd.tcl の先頭に書いてある（tkinterdnd2 に別のファイルがない）
TKDND_TCL = Path(metadata.distribution("tkinterdnd2").locate_file("tkinterdnd2/tkdnd/win-x64/tkdnd.tcl"))

# (表示する名前, 配布の名前〔版を読む。None は Python〕, 用途, ライセンス, 全文のファイル)
COMPONENTS = [
    ("Python", None, "プログラムの言語（exe に入る）", "PSF License Version 2", [PY_HOME / "LICENSE.txt"]),
    ("Tcl/Tk", None, "画面", "Tcl/Tk License（BSD 形式）", [PY_HOME / "tcl" / "tk8.6" / "license.terms"]),
    ("ReportLab", "reportlab", "PDF の作成（字・罫線を描く）", "BSD License", ["licenses/LICENSE"]),
    ("pypdf", "pypdf", "PDF の仕上げ（画像・識別子・文書情報）と、識別子・画像の読み出し", "BSD License（3条項）",
     ["licenses/LICENSE"]),
    ("pdfplumber", "pdfplumber", "PDF の字の読み取り（開き直したときの対応表の作り直し、ほかのソフトで作った PDF の取り込み）",
     "MIT License", ["licenses/LICENSE.txt"]),
    ("pdfminer.six", "pdfminer.six", "PDF の字の読み取り（pdfplumber が使う）", "MIT License", ["licenses/LICENSE"]),
    ("charset-normalizer", "charset-normalizer", "文字コードの判定（pdfminer.six が使う）", "MIT License", ["licenses/LICENSE"]),
    ("cryptography", "cryptography", "暗号化された PDF を読む（pdfminer.six が使う）",
     "Apache License 2.0 または BSD License（3条項）。どちらかを選べる", ["licenses/LICENSE", "licenses/LICENSE.APACHE",
                                                                 "licenses/LICENSE.BSD"]),
    ("cffi", "cffi", "cryptography が使う", "MIT License", ["licenses/LICENSE"]),
    ("pycparser", "pycparser", "cffi が使う", "BSD License（3条項）", ["licenses/LICENSE"]),
    ("pypdfium2", "pypdfium2", "プレビュー・印刷（PDF のページを画像にする）。Google の PDFium と、PDFium が使う部品を含む",
     "Apache License 2.0・BSD License（3条項）。PDFium と、PDFium が使う部品のライセンスも写す",
     ["licenses/LICENSES/Apache-2.0.txt", "licenses/LICENSES/BSD-3-Clause.txt"] + [
         f"licenses/data/windows_x64/BUILD_LICENSES/{n}" for n in (
             "pdfium.txt", "pdfium-binaries.txt", "abseil.txt", "agg23.txt", "fast_float.txt", "freetype.txt", "icu.txt",
             "lcms.txt", "libjpeg_turbo.ijg", "libjpeg_turbo.md", "libopenjpeg.txt", "libpng.txt", "libtiff.txt",
             "llvm-libc.txt", "simdutf.txt", "zlib.txt")]),
    ("fontTools", "fonttools", "書体の埋め込みの許可の確かめ", "MIT License",
     ["licenses/LICENSE", "licenses/LICENSE.external"]),
    ("Pillow", "pillow", "アイコンの画像", "MIT-CMU License", ["licenses/LICENSE"]),
    ("tkinterdnd2", "tkinterdnd2", "エクスプローラーからのドラッグアンドドロップ", "MIT License", ["licenses/LICENSE"]),
    ("tkdnd 2.10.1", None, "エクスプローラーからのドラッグアンドドロップ（tkinterdnd2 に入っている Tk の拡張）",
     "BSD 形式（Tcl/Tk と同じ条項）", [TKDND_TCL]),
    ("PyInstaller", "pyinstaller", "実行ファイルの作成（ブートローダーが exe に入る）",
     "GNU General Public License 第2版以降（ブートローダーの例外条項付き）", ["licenses/COPYING.txt"]),
    ("Fluent UI System Icons", None, "ボタンのアイコン（［傍点］のアイコンを除く）", "MIT License",
     [ROOT / "src" / "va_document" / "icons" / "LICENSE"]),
    ("IPAフォント（IPA明朝・IPAゴシック）Ver.003.03", None,
     "Mac など、ＭＳ 明朝のない PC で PDF に埋め込む書体（ソースの assets/fonts に同梱。exe には入らない）",
     "IPAフォントライセンス v1.0", [ROOT / "assets" / "fonts" / "IPA_Font_License_Agreement_v1.0.txt"]),
]


def _license_files(dist: str | None, files: list) -> list[tuple[str, str]]:
    out = []
    for f in files:
        if isinstance(f, Path):
            path = f
        else:
            path = Path(metadata.distribution(dist).locate_file(f"{dist}-{metadata.version(dist)}.dist-info/{f}"))
            if not path.exists():
                matches = [p for p in metadata.distribution(dist).files or [] if str(p).replace("\\", "/").endswith(f)]
                path = Path(metadata.distribution(dist).locate_file(matches[0])) if matches else path
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if path.suffix == ".tcl":
            # Tcl のファイル（tkdnd.tcl）は、先頭のコメント（著作権と使用許諾）だけを写す
            head = []
            for line in text.splitlines():
                if not line.startswith("#"):
                    break
                head.append(line[2:] if line.startswith("# ") else line[1:])
            text = "\n".join(head).strip("\n") + "\n"
        out.append((path.name, text))
    return out


def build() -> Path:
    parts = [
        "VA Document が使っている部品のライセンスの表示",
        "",
        "VA Document そのものは、MIT License で公開しています（LICENSE）。",
        "VA Document の実行ファイル（VA_Document.exe）には、次の部品が入っています（IPAフォントは、ソースにだけ入っています）。",
        "ＭＳ 明朝・ＭＳ ゴシックは入っていません（Windows に入っているものを、埋め込みの許可の範囲で PDF に埋め込みます）。",
        "",
    ]
    for name, dist, use, lic, files in COMPONENTS:
        version = sys.version.split()[0] if name == "Python" else (metadata.version(dist) if dist else "")
        parts += ["=" * 78, f"{name} {version}".rstrip(), f"用途：{use}", f"ライセンス：{lic}"]
        parts.append("=" * 78)
        for fname, text in _license_files(dist, files):
            parts += [f"--- {fname} ---", text.rstrip(), ""]
        parts.append("")
    OUTPUT.write_text("\n".join(parts) + "\n", encoding="utf-8", newline="\n")
    return OUTPUT


if __name__ == "__main__":
    print(f"作りました：{build()}")
