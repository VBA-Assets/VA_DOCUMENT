"""印刷（Windows だけ。2026-10-23 班長決定：ツールの中で印刷する）。

VA Document の「印刷」画面（dialogs.PrintDialog）でプリンター・部数・ページを選んでもらい（2026-10-24 班長決定。
Windows 11 の新しい印刷画面は、プレビューの欄に「このアプリは印刷プレビューをサポートしていません」と出て紛らわしいため、
Windows の PrintDlgW をやめた。プリンターの細かい設定は［プロパティ］で、プリンターのドライバーの画面を開く）、組んだページ
（確認表示と同じもの）をプリンターの解像度（最大 PRINT_MAX_DPI）の画像にして、実際のサイズで送る。
・字だけのページは灰色、画像のあるページはカラーにする（page_is_color。2026-10-30 班長決定。それまではすべて灰色で、写真も
  白黒で刷られた）。カラーのページは、灰色の3倍の大きさになるので、上から BAND_ROWS 行ずつに分けて送る（1ページを丸ごと
  画像にすると、600 dpi で約 100 MB になるため）。印刷の画面の印刷プレビューも、同じ規則で色を決める。
・用紙は A4 にする（プリンターの既定が Letter などでも、字が切れないように）。
・印刷できない用紙の縁の分（PHYSICALOFFSET）を差し引き、用紙の左上にページの左上を合わせる。
・印刷の文書の名前（待ち行列に出る名前。Microsoft Print to PDF では PDF の題名になる）は、呼ぶ側が決める（画面では PDF のファイル名）。
外の部品（pywin32）は使わず、ctypes で Windows の関数を呼ぶ。ページを画像にするのは pdfpages（pypdfium2。Ver300 で
PyMuPDF から替えた）。
"""
import ctypes
import os

from .pdfpages import PdfPages

PRINT_MAX_DPI = 600
BAND_ROWS = 1024        # カラーのページを分けて送るときの、1回の行の数（600 dpi で約 15 MB）

if os.name == "nt":
    from ctypes import wintypes

    _gdi32 = ctypes.windll.gdi32
    _winspool = ctypes.WinDLL("winspool.drv")

    class PRINTER_INFO_4(ctypes.Structure):
        _fields_ = [("pPrinterName", wintypes.LPWSTR), ("pServerName", wintypes.LPWSTR),
                    ("Attributes", wintypes.DWORD)]

    class DOCINFOW(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_int), ("lpszDocName", wintypes.LPCWSTR), ("lpszOutput", wintypes.LPCWSTR),
                    ("lpszDatatype", wintypes.LPCWSTR), ("fwType", wintypes.DWORD)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    class BITMAPINFO_GRAY(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 256)]

    class BITMAPINFO_RGB(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 1)]

    _winspool.EnumPrintersW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p,
                                        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    _winspool.EnumPrintersW.restype = wintypes.BOOL
    _winspool.GetDefaultPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    _winspool.GetDefaultPrinterW.restype = wintypes.BOOL
    _winspool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    _winspool.OpenPrinterW.restype = wintypes.BOOL
    _winspool.ClosePrinter.argtypes = [wintypes.HANDLE]
    _winspool.DocumentPropertiesW.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.LPWSTR, ctypes.c_void_p,
                                              ctypes.c_void_p, wintypes.DWORD]
    _winspool.DocumentPropertiesW.restype = wintypes.LONG
    _gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
    _gdi32.CreateDCW.restype = wintypes.HDC
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    _gdi32.StartDocW.argtypes = [wintypes.HDC, ctypes.POINTER(DOCINFOW)]
    _gdi32.StartPage.argtypes = [wintypes.HDC]
    _gdi32.EndPage.argtypes = [wintypes.HDC]
    _gdi32.EndDoc.argtypes = [wintypes.HDC]
    _gdi32.AbortDoc.argtypes = [wintypes.HDC]
    _gdi32.ResetDCW.argtypes = [wintypes.HDC, ctypes.c_void_p]
    _gdi32.ResetDCW.restype = wintypes.HDC
    _gdi32.StretchDIBits.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                     ctypes.c_void_p, wintypes.UINT, wintypes.DWORD]
    PRINTER_ENUM_LOCAL, PRINTER_ENUM_CONNECTIONS = 0x2, 0x4
    DM_OUT_BUFFER, DM_IN_PROMPT, DM_IN_BUFFER, IDOK = 2, 4, 8, 1
    LOGPIXELSX, LOGPIXELSY, PHYSICALOFFSETX, PHYSICALOFFSETY = 88, 90, 112, 113
    DM_PAPERSIZE, DM_COPIES, DM_COLLATE, DMPAPER_A4 = 0x2, 0x100, 0x8000, 9
    # DEVMODEW の dmFields・dmPaperSize・dmCopies・dmCollate の位置（バイト）
    DEVMODE_FIELDS_OFFSET, DEVMODE_PAPERSIZE_OFFSET, DEVMODE_COPIES_OFFSET, DEVMODE_COLLATE_OFFSET = 72, 78, 86, 100
    SRCCOPY, DIB_RGB_COLORS = 0x00CC0020, 0


class PrintError(Exception):
    """印刷できなかった（プリンターが応えない、など）。"""


def available():
    return os.name == "nt"


def printers():
    """この PC で使えるプリンターの名前（手元のものと、共有のプリンターへの接続）。"""
    flags = PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    needed, count = wintypes.DWORD(), wintypes.DWORD()
    _winspool.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(count))
    if not needed.value:
        return []
    buf = ctypes.create_string_buffer(needed.value)
    if not _winspool.EnumPrintersW(flags, None, 4, buf, needed, ctypes.byref(needed), ctypes.byref(count)):
        return []
    infos = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_4))
    return [infos[k].pPrinterName for k in range(count.value)]


def default_printer():
    """Windows の既定のプリンターの名前（なければ ""）。"""
    size = wintypes.DWORD(0)
    _winspool.GetDefaultPrinterW(None, ctypes.byref(size))
    if not size.value:
        return ""
    buf = ctypes.create_unicode_buffer(size.value)
    return buf.value if _winspool.GetDefaultPrinterW(buf, ctypes.byref(size)) else ""


def _document_properties(hwnd, name, devmode_in, mode):
    """DocumentPropertiesW を呼び、(戻り値, 出てきた DEVMODE) を返す。"""
    handle = wintypes.HANDLE()
    if not _winspool.OpenPrinterW(name, ctypes.byref(handle), None):
        raise PrintError(f"プリンター「{name}」を使えません。")
    try:
        size = _winspool.DocumentPropertiesW(hwnd, handle, name, None, None, 0)
        if size <= 0:
            raise PrintError(f"プリンター「{name}」の設定を読めませんでした。")
        out = ctypes.create_string_buffer(size)
        ret = _winspool.DocumentPropertiesW(hwnd, handle, name, out, devmode_in, mode)
        return ret, out
    finally:
        _winspool.ClosePrinter(handle)


def devmode(name):
    """プリンターの今の設定（DEVMODE のバイト列）。"""
    ret, out = _document_properties(None, name, None, DM_OUT_BUFFER)
    if ret < 0:
        raise PrintError(f"プリンター「{name}」の設定を読めませんでした。")
    return out


def show_properties(hwnd, name, current=None):
    """プリンターのドライバーの設定画面（プロパティ）を出す。OK なら直した DEVMODE、やめたら None を返す。"""
    current = current if current is not None else devmode(name)
    ret, out = _document_properties(hwnd, name, current, DM_IN_BUFFER | DM_OUT_BUFFER | DM_IN_PROMPT)
    return out if ret == IDOK else None


def make_dc(name, mode=None, copies=1):
    """印刷の DC を作る。用紙は A4 にし（プリンターの既定が Letter などでも、字が切れないように）、部数を入れる。"""
    buf = mode if mode is not None else devmode(name)
    base = ctypes.addressof(buf)
    fields = ctypes.c_uint32.from_address(base + DEVMODE_FIELDS_OFFSET)
    ctypes.c_int16.from_address(base + DEVMODE_PAPERSIZE_OFFSET).value = DMPAPER_A4
    ctypes.c_int16.from_address(base + DEVMODE_COPIES_OFFSET).value = max(1, int(copies))
    ctypes.c_int16.from_address(base + DEVMODE_COLLATE_OFFSET).value = 1     # 部単位で印刷する
    fields.value |= DM_PAPERSIZE | DM_COPIES | DM_COLLATE
    hdc = _gdi32.CreateDCW("WINSPOOL", name, None, buf)
    if not hdc:
        raise PrintError(f"プリンター「{name}」を使えません。")
    return hdc


def parse_pages(spec, total):
    """「1-3, 5」のようなページの指定を、0 から数えたページのリストにする（順に並べ、重ねない）。
    全角の数字・区切りも読む。読めない・範囲の外なら ValueError。"""
    spec = spec.translate(str.maketrans("０１２３４５６７８９－ー～〜、，　", "0123456789----,, "))
    chosen = set()
    for part in (s.strip() for s in spec.split(",")):
        if not part:
            continue
        a, dash, b = part.partition("-")
        first = int(a)
        last = int(b) if b.strip() else (total if dash else first)      # 「4-」は最後のページまで
        if not (1 <= first <= last <= total):
            raise ValueError(part)
        chosen.update(range(first - 1, last))
    if not chosen:
        raise ValueError(spec)
    return sorted(chosen)


def page_is_color(doc, k):
    """ページ k（doc は pdfpages.PdfPages）をカラーで印刷するか：画像のあるページはカラー、字だけのページは灰色
    （2026-10-30 班長決定）。蛍光ペンと仮名化する語の色は、印刷する PDF にはもともと入らない（preview_pdf の既定）。"""
    return doc.has_images(k)


def _stretch(hdc, pix, bmi, x, y, dest_w, dest_h):
    """画像（pdfpages.Pixels。1行は 4 の倍数のバイト数で、DIB と同じ並び）を、プリンターの (x, y) に dest_w × dest_h で描く。"""
    data, row = pix.data, pix.width * pix.n
    stride = (row + 3) & ~3                             # DIB の1行のバイト数（4 の倍数）
    if pix.stride != stride:                            # pdfium の画像の行の幅が違えば、詰め直す
        pad = b"\xff" * (stride - row)
        data = b"".join(data[r * pix.stride:r * pix.stride + row] + pad for r in range(pix.height))
    bmi.bmiHeader.biWidth = pix.width
    bmi.bmiHeader.biHeight = -pix.height                # 上から下へ並ぶ画像
    buf = ctypes.create_string_buffer(data, len(data))
    _gdi32.StretchDIBits(hdc, x, y, dest_w, dest_h, 0, 0, pix.width, pix.height,
                         buf, ctypes.byref(bmi), DIB_RGB_COLORS, SRCCOPY)


def _draw_color_page(hdc, doc, k, render_dpi, dpi_x, dpi_y, off_x, off_y):
    """カラーのページを、上から BAND_ROWS 行ずつ画像にしてプリンターに描く（1ページを丸ごと画像にしないため）。
    帯の位置は、帯の画像の位置（画素）から毎回計算する（丸めの差で、帯の間がすいたり重なったりしないように）。"""
    zoom = render_dpi / 72
    sx, sy = dpi_x / render_dpi, dpi_y / render_dpi
    bmi = BITMAPINFO_RGB()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biPlanes, bmi.bmiHeader.biBitCount = 1, 24
    rows = round(doc.size(k)[1] * zoom)
    for r0 in range(0, rows, BAND_ROWS):
        r1 = min(r0 + BAND_ROWS, rows)
        # 青・緑・赤の順（Windows の画像と同じ）で、1行は 4 の倍数のバイト数（pdfium の画像のまま渡せる）
        pix = doc.render(k, zoom, top=r0 / zoom, bottom=r1 / zoom, bgr=True)
        y0 = round(r0 * sy)
        dest_w, dest_h = round(pix.width * sx), round((r0 + pix.height) * sy) - y0
        _stretch(hdc, pix, bmi, -off_x, y0 - off_y, dest_w, dest_h)


def print_pdf(pdf_bytes, hdc, doc_name, pages=None, output=None, progress=None):
    """PDF（バイト列）の pages（0 から。None なら全部）を、hdc のプリンターに実際のサイズで印刷する。

    output はファイルに印刷するときの出力先（試験用）。progress(済んだ数, 全部の数) を呼ぶ。印刷したページ数を返す。
    hdc は、この関数の中で消す。
    """
    try:
        dpi_x = _gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
        dpi_y = _gdi32.GetDeviceCaps(hdc, LOGPIXELSY)
        off_x = _gdi32.GetDeviceCaps(hdc, PHYSICALOFFSETX)
        off_y = _gdi32.GetDeviceCaps(hdc, PHYSICALOFFSETY)
        if dpi_x <= 0 or dpi_y <= 0:
            raise PrintError("プリンターの解像度を読めませんでした。")
        render_dpi = min(PRINT_MAX_DPI, max(dpi_x, dpi_y))
        di = DOCINFOW()
        di.cbSize = ctypes.sizeof(DOCINFOW)
        di.lpszDocName = doc_name
        di.lpszOutput = output
        if _gdi32.StartDocW(hdc, ctypes.byref(di)) <= 0:
            raise PrintError("印刷を始められませんでした。")
        bmi = BITMAPINFO_GRAY()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biPlanes, bmi.bmiHeader.biBitCount = 1, 8
        for k in range(256):
            bmi.bmiColors[k] = k | (k << 8) | (k << 16)
        done = 0
        with PdfPages(pdf_bytes) as doc:
            chosen = list(range(len(doc))) if pages is None else pages
            try:
                for k in chosen:
                    if page_is_color(doc, k):
                        if _gdi32.StartPage(hdc) <= 0:
                            raise PrintError("ページを始められませんでした。")
                        _draw_color_page(hdc, doc, k, render_dpi, dpi_x, dpi_y, off_x, off_y)
                        if _gdi32.EndPage(hdc) <= 0:
                            raise PrintError("ページを送れませんでした。")
                        done += 1
                        if progress:
                            progress(done, len(chosen))
                        continue
                    pix = doc.render(k, render_dpi / 72, gray=True)
                    page_w, page_h = doc.size(k)
                    dest_w = round(page_w / 72 * dpi_x)
                    dest_h = round(page_h / 72 * dpi_y)
                    if _gdi32.StartPage(hdc) <= 0:
                        raise PrintError("ページを始められませんでした。")
                    _stretch(hdc, pix, bmi, -off_x, -off_y, dest_w, dest_h)
                    if _gdi32.EndPage(hdc) <= 0:
                        raise PrintError("ページを送れませんでした。")
                    done += 1
                    if progress:
                        progress(done, len(chosen))
            except Exception:
                _gdi32.AbortDoc(hdc)
                raise
        _gdi32.EndDoc(hdc)
        return done
    finally:
        _gdi32.DeleteDC(hdc)
