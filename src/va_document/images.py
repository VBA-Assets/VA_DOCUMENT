"""画像の取り込み（2026-10-29 班長決定。検討_画像の挿入.md の6）。

・画像は仮名化できない（スキャンした書類・画面の写しに実名が写っていることがある）ので、AI に渡さず、構文ファイルにも
  書かない。編集中はメモリ（Session.images）にだけ持ち、保存すると PDF の中に入る（pdfwriter.py）。
・取り込むときに Pillow で作り直し、その結果だけを持つ（PDF に入るのも、確認表示に出るのも、この画像）：
  EXIF の向きを画素に反映してから EXIF を捨てる。透過は白地に重ねてなくす（PDF からの取り出しで透過の層が別に
  なるのを避ける）。色は RGB か灰色にする。長い辺が MAX_SIDE 画素を超えるものは縮める。JPEG は JPEG（画質 95）、
  それ以外は PNG にし、EXIF・ICC・文字の欄（作成者・コメント・ソフト名・パスなど）を一切渡さずに保存し直す。
  PNG が PNG_LIMIT バイトを超えるときは JPEG と比べて小さいほうにする（写真をコピーしたものなど）。
・ファイルの名前・パスはどこにも残さない。一時ファイルも作らない。
"""
import io
import math
from dataclasses import dataclass

from PIL import Image, ImageGrab, ImageOps

MAX_SIDE = 2500             # 長い辺の画素数の上限（A4 の幅を 300dpi で印刷するのに足りる大きさ）
JPEG_QUALITY = 95
PNG_LIMIT = 1_500_000       # これを超える PNG は、JPEG と比べて小さいほうにする
SCREEN_DPI = 96             # 入れるときの幅（画像の大きさを、この解像度で置いた幅）
# ファイルを選ぶ画面に出す形式（Pillow が読めるもの）
FILE_TYPES = (("画像", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff"), ("すべてのファイル", "*.*"))


class NotImage(ValueError):
    """画像として読めない。"""


@dataclass(frozen=True)
class Picture:
    """付加情報を除いた画像。"""
    data: bytes             # JPEG か PNG
    width: int              # 画素
    height: int

    @property
    def size(self):
        return self.width, self.height


def _encode(im, as_jpeg):
    buf = io.BytesIO()
    if as_jpeg:
        im.save(buf, "JPEG", quality=JPEG_QUALITY)     # exif・icc_profile を渡さない
    else:
        im.save(buf, "PNG", optimize=True)              # pnginfo を渡さない
    return buf.getvalue()


def from_image(im, jpeg=None):
    """Pillow の画像を作り直して Picture にする。jpeg が None なら、元の形式（JPEG かどうか）で決める。"""
    try:
        if jpeg is None:
            jpeg = im.format in ("JPEG", "MPO")
        im = ImageOps.exif_transpose(im)
        im.load()
    except Exception as e:      # 壊れたファイルなど
        raise NotImage("画像として読めないファイルです。") from e
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        im = bg
    elif im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    if max(im.size) > MAX_SIDE:
        im = im.copy()
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    data = _encode(im, jpeg)
    if not jpeg and len(data) > PNG_LIMIT:
        other = _encode(im, True)
        if len(other) < len(data):
            data = other
    return Picture(data, im.width, im.height)


def from_bytes(data):
    try:
        im = Image.open(io.BytesIO(data))
    except Exception as e:
        raise NotImage("画像として読めないファイルです。") from e
    return from_image(im)


def from_file(path):
    """画像ファイルを読む（ファイルの名前・パスは残さない）。"""
    with open(path, "rb") as f:
        return from_bytes(f.read())


def from_clipboard():
    """クリップボードの画像を読む（利用者が Ctrl+V を押したときだけ呼ぶ）。画像があれば [Picture]、画像ファイルを
    コピーしたもの（エクスプローラーでコピーしたファイル）なら、そのうちの画像ファイルの [Picture]、なければ []。
    Windows ではメモリの中で読み（PNG か DIB。クリップボードの履歴〔Win+V〕から選んだものも、Windows が置き直して
    から Ctrl+V を送るので同じ道を通る）、Mac では osascript の出力から読む。どちらも一時ファイルを作らない。"""
    try:
        got = ImageGrab.grabclipboard()
    except Exception:
        return []
    if got is None:
        return []
    if isinstance(got, list):
        out = []
        for path in got:
            try:
                out.append(from_file(path))
            except (OSError, NotImage):
                continue        # 画像でないファイルは入れない
        return out
    return [from_image(got, jpeg=False)]


def natural_chars(picture, pitch):
    """画像を SCREEN_DPI で置いたときの幅を、字数に切り上げたもの（入れるときの幅）。"""
    return max(1, math.ceil(picture.width * 72 / SCREEN_DPI / pitch - 1e-6))


def open_image(picture):
    """Picture を Pillow の画像として開く（確認表示の試験などに使う）。"""
    return Image.open(io.BytesIO(picture.data))
