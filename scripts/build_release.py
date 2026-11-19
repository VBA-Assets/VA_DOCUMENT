"""配布用のリリース（release_VerNNN\\VA_Document_VerNNN\\ と dist\\VA_Document_VerNNN.zip）を組み立てる。

VA mints の build_release.py と同じ作り。統合版のインストーラー（..\\共通\\統合版）は、
release_VerNNN\\VA_Document_VerNNN\\ を直接参照する。

前提（このスクリプトはビルドそのものはしない。先に済ませておく）：
    1. python -m PyInstaller va_document.spec --noconfirm   （dist\\VA_Document.exe を最新のコードで作る）
    2. python scripts\\generate_manual.py                    （docs\\manual\\VA_Document_操作マニュアル_VerNNN.pdf。
       先にマニュアルのフロントマターの version を上げておく）
    3. python scripts\\make_notices.py                       （部品の版を上げたとき）

実行のしかた：
    python scripts\\build_release.py Ver100

できるもの：
    release_Ver100\\VA_Document_Ver100\\  （VA_Document.exe・LICENSE・THIRD_PARTY_NOTICES.txt・README.md・
                                          マニュアル\\・source\\）
    dist\\VA_Document_Ver100.zip          （上のフォルダを zip にしたもの）
release_*\\・dist\\ は、ビルドの生成物として git に入れない。
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# source\\ に入れないもの（git の管理下でも、公開しない内部の資料。VAプロジェクト\\CLAUDE.md の
# 「GitHub でのソースの公開」と同じ考え方）：班長の名前のある CLAUDE.md、検討メモ、試作（Word を操る試験の道具）
_EXCLUDE = [re.compile(p) for p in (r"^CLAUDE\.md$", r"^検討_.*\.md$", r"^試作/")]


def _source_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    files = [f for f in out.decode("utf-8").split("\0") if f]
    return [f for f in files if not any(p.search(f) for p in _EXCLUDE)]


def _clear_readonly(func, path, exc):
    """OneDrive はフォルダに読み取り専用の属性を付け、Windows は読み取り専用のフォルダを消せない
    （2026-10-25、作り直しで release_VerNNN が半分消えたまま止まった）。属性を外して、もう一度消す。"""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def build(version: str) -> Path:
    # 2桁目は 9 の次を A とする（Ver2A0。2026-11-13 班長決定）
    if not re.fullmatch(r"Ver[0-9A-Z]{3}", version):
        raise SystemExit("版は「Ver100」「Ver2A0」の形で指定してください。")
    exe = ROOT / "dist" / "VA_Document.exe"
    manual = ROOT / "docs" / "manual" / f"VA_Document_操作マニュアル_{version}.pdf"
    required = [exe, manual, ROOT / "LICENSE", ROOT / "THIRD_PARTY_NOTICES.txt", ROOT / "README.md"]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
    if missing:
        raise SystemExit("足りないファイルがあります：" + "、".join(missing))
    # 版のつじつま（exe の画面に出る版と、指定した版）を確かめる
    sys.path.insert(0, str(ROOT / "src"))
    from va_document import __version__
    if "Ver" + __version__.replace(".", "") != version:
        raise SystemExit(f"src\\va_document\\__init__.py の版（{__version__}）が {version} と合いません。")

    stage = ROOT / f"release_{version}" / f"VA_Document_{version}"
    if stage.exists():
        shutil.rmtree(stage, onexc=_clear_readonly)
    (stage / "マニュアル").mkdir(parents=True)
    shutil.copy2(exe, stage / exe.name)
    shutil.copy2(manual, stage / "マニュアル" / manual.name)
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.txt", "README.md"):
        shutil.copy2(ROOT / name, stage / name)
    for f in _source_files():
        dest = stage / "source" / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, dest)

    zip_path = ROOT / "dist" / f"VA_Document_{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                z.write(p, Path(stage.name) / p.relative_to(stage))
    return zip_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("使い方：python scripts\\build_release.py Ver100")
    path = build(sys.argv[1])
    print(f"作りました：{path}（{path.stat().st_size:,} バイト）")
