"""この PC だけの設定ファイル（仕様.md の10）。

書くのは、最後に使った文書の種類・ページ番号、構文ファイルのフォルダ、PDF を保存したフォルダの一覧
（構文ファイルから PDF を探すため。9.2）、前回終了したときのウィンドウの大きさ・位置・確認表示の幅、
オプション（エディターの書体・字の大きさ・行の間隔。2026-10-24 班長指示）だけで、文章の中身・辞書・対応表は書かない。
フォルダの名前に実名が入ることがあるので、設定ファイルは AI に渡さない（手引きに書く）。
置き場所は %APPDATA%\\VA Document\\settings.json（Windows 以外はホームの .va_document）。
"""
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .doctypes import DEFAULT_DOC_TYPE, DOC_TYPES, PAGE_NUMBER_BOTTOM_CENTER, PAGE_NUMBER_LABELS
from .theme import EDITOR_FONT_SIZE, EDITOR_LINE_SPACING, NAV_FONT_SIZE, NAV_LINE_SPACING
from .vamd import default_folder

MAX_PDF_FOLDERS = 50
FONT_SIZE_RANGE = (8, 20)       # オプションで選べるエディターの字の大きさ（ポイント）
LINE_SPACING_RANGE = (6, 15)    # 同じく行の間隔（ポイント。2026-10-26 班長決定。最低の 6 は、エディターのカーソルの上の ▼ を行の間に入れるためだった。▼ は 2026-11-27 に廃止したが、範囲は変えていない）
# ナビゲーションの行の間隔（ポイント。一覧には ▼ を置かないので、0 まで狭められる。字の大きさはエディターと同じ範囲）
NAV_LINE_SPACING_RANGE = (0, 15)


def config_path():
    # 試験のときは、環境変数 VA_DOCUMENT_CONFIG_DIR で置き場所を替える（班長の設定に書かないため。標準 02「設定ファイル」）
    override = os.environ.get("VA_DOCUMENT_CONFIG_DIR")
    if override:
        return Path(override) / "settings.json"
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "VA Document" / "settings.json"
    return Path.home() / ".va_document" / "settings.json"


@dataclass
class AppConfig:
    doc_type: str = DEFAULT_DOC_TYPE
    page_number: str = PAGE_NUMBER_BOTTOM_CENTER
    line_numbers: bool = False      # 行番号（新しい文書の既定。2026-10-24 班長指示）
    one_width: bool = False         # 見出し番号を1字の幅に縮める（新しい文書の既定。2026-10-26 班長指示）
    vamd_folder: str = ""
    pdf_folders: list = field(default_factory=list)   # 新しく使ったものが先
    # 前回終了したときのウィンドウ（2026-10-23 班長指示：起動時に元に戻す）
    window_geometry: str = ""      # 最大化していないときの「幅x高さ+x+y」
    window_zoomed: bool = False     # 最大化していたか
    preview_width: int = 0          # 確認表示の幅（画素。ナビゲーションを出していないときの、左右の境目の位置）
    # ナビゲーション（見出しの一覧）を一番左に出すか、その幅（画素。0 は既定の幅）。2026-11-24 班長指示
    preview_visible: bool = True    # プレビューを出すか（2026-11-24 班長指示）
    # 「仮名化する語」の一覧と「AI 連携」の組を出すか（2026-11-24 班長決定。仮名化する語がある文書では、これに関わらず出す）
    ai_visible: bool = True
    nav_visible: bool = False
    nav_width: int = 0
    # オプションのナビゲーションの書体（"" は画面の書体）・字の大きさ・行の間隔（ポイント）。2026-11-24 班長指示
    nav_font_family: str = ""
    nav_font_size: int = NAV_FONT_SIZE
    nav_line_spacing_pt: int = NAV_LINE_SPACING
    # オプション（2026-10-24 班長指示）。書体の "" は既定（BIZ UDゴシック、なければＭＳ ゴシック）
    editor_font_family: str = ""
    editor_font_size: int = EDITOR_FONT_SIZE
    editor_line_spacing_pt: int = EDITOR_LINE_SPACING     # Ver151 から。それまでは editor_line_spacing（画素）
    # ユーザーによって書き換えられた AI への指示（"" は既定。2026-10-24 班長指示。2026-10-28 班長決定で、すべての文書に
    # 共通にした：どの文書を保存しても、この指示〔なければ既定の指示〕を書く）
    ai_prompt: str = ""
    # ai_prompt を書き換えた（または、既定の指示が新しくなったことを知らせた）ときの既定の指示の SHA-256。
    # 起動のときに今の既定の指示と違えば、一度だけ知らせる（2026-10-28 班長決定）
    ai_prompt_base: str = ""

    def remember_settings(self, settings):
        """文書の設定（vamd.Settings）を、次の新しい文書の既定として覚える（2026-10-23 班長指示）。"""
        self.doc_type, self.page_number = settings.doc_type, settings.page_number
        self.line_numbers, self.one_width = settings.line_numbers, settings.one_width

    def __post_init__(self):
        if self.doc_type not in DOC_TYPES:
            self.doc_type = DEFAULT_DOC_TYPE
        if self.page_number not in PAGE_NUMBER_LABELS:
            self.page_number = PAGE_NUMBER_BOTTOM_CENTER
        if not isinstance(self.line_numbers, bool):
            self.line_numbers = False
        if not isinstance(self.one_width, bool):
            self.one_width = False
        if not isinstance(self.ai_visible, bool):
            self.ai_visible = True
        if not isinstance(self.preview_visible, bool):
            self.preview_visible = True
        if not isinstance(self.nav_visible, bool):
            self.nav_visible = False
        if not isinstance(self.nav_width, int) or isinstance(self.nav_width, bool) or self.nav_width < 0:
            self.nav_width = 0
        if not self.vamd_folder:
            self.vamd_folder = str(default_folder())
        if not isinstance(self.editor_font_size, int) or not FONT_SIZE_RANGE[0] <= self.editor_font_size <= FONT_SIZE_RANGE[1]:
            self.editor_font_size = EDITOR_FONT_SIZE
        if (not isinstance(self.editor_line_spacing_pt, int)
                or not LINE_SPACING_RANGE[0] <= self.editor_line_spacing_pt <= LINE_SPACING_RANGE[1]):
            self.editor_line_spacing_pt = EDITOR_LINE_SPACING
        if not isinstance(self.editor_font_family, str):
            self.editor_font_family = ""
        if not _in_range(self.nav_font_size, FONT_SIZE_RANGE):
            self.nav_font_size = NAV_FONT_SIZE
        if not _in_range(self.nav_line_spacing_pt, NAV_LINE_SPACING_RANGE):
            self.nav_line_spacing_pt = NAV_LINE_SPACING
        if not isinstance(self.nav_font_family, str):
            self.nav_font_family = ""
        if not isinstance(self.ai_prompt, str):
            self.ai_prompt = ""
        if not isinstance(self.ai_prompt_base, str):
            self.ai_prompt_base = ""

    def remember_pdf_folder(self, folder):
        folder = str(Path(folder).resolve())
        self.pdf_folders = [folder] + [f for f in self.pdf_folders if f != folder][:MAX_PDF_FOLDERS - 1]


def _in_range(value, bounds):
    """設定の値が、範囲 bounds（最小, 最大）の内の整数か（True・False は数としない）。"""
    return isinstance(value, int) and not isinstance(value, bool) and bounds[0] <= value <= bounds[1]


def load(path=None):
    path = Path(path or config_path())
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {k: data[k] for k in AppConfig.__dataclass_fields__ if k in data}
        # Ver150 までの行の間隔（画素。表示の拡大 100% のとき）は、ポイントに直して読む（8 画素 → 6 ポイント）
        old = data.get("editor_line_spacing")
        if "editor_line_spacing_pt" not in data and isinstance(old, int) and not isinstance(old, bool):
            known["editor_line_spacing_pt"] = max(LINE_SPACING_RANGE[0], min(LINE_SPACING_RANGE[1], round(old * 0.75)))
        return AppConfig(**known)
    except (OSError, ValueError, TypeError):
        return AppConfig()


def save(cfg, path=None):
    path = Path(path or config_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
