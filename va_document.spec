# -*- mode: python ; coding: utf-8 -*-
# VA Document の実行ファイル（dist\VA_Document.exe）を作る（VA mints の mints_prep.spec と同じ作り）。
# 作り方：pyinstaller va_document.spec --noconfirm

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


a = Analysis(
    ['main.py'],
    pathex=['src'],
    # エクスプローラーからのドラッグアンドドロップ（tkinterdnd2 の tkdnd。Tcl のファイルと DLL。VA FAX の motfax.spec と同じ）
    binaries=collect_dynamic_libs('tkinterdnd2'),
    # ・ボタンのアイコン（scripts\make_icons.py で SVG から作った PNG と、Fluent UI System Icons の LICENSE）。icons.py は
    #   va_document\icons\png から読む。SVG（もと）は入れない（Ver300。起動のたびに SVG を画像にするのをやめた）
    # ・ウィンドウ（タイトルバー・タスクバー）のアイコン。exe そのもののアイコンは EXE(icon=...) で埋め込むが、
    #   Tk のウィンドウには、実行時にファイルとして読ませる必要があるため、展開先（sys._MEIPASS）に入れる
    # ・同梱の IPA書体（assets/fonts。Mac などで使う）は入れない（Windows ではＭＳ 明朝を使う。pdfwriter.DEFAULT_FONTS）
    # ・PDF の部品（Ver300 で PyMuPDF から替えた）：pypdfium2 の PDFium（DLL）・pdfminer.six の文字の対応表（cmap）は、
    #   PyInstaller の部品の設定（pyinstaller-hooks-contrib の hook-pypdfium2・hook-pdfminer）が入れる
    datas=[('src/va_document/icons/png', 'va_document/icons/png'),
           ('src/va_document/icons/LICENSE', 'va_document/icons'), ('assets/VA_Document.ico', 'assets')]
          + collect_data_files('tkinterdnd2'),
    hiddenimports=['tkinterdnd2'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 使わない大きな部品を入れない（試験の部品・ほかの GUI）。PyMuPDF（AGPL-3.0）は、開発の PC に入っていても、
    # exe に入れない（Ver300 から MIT License で配るため。src は読み込まない：tests\test_license.py）
    excludes=['pytest', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'matplotlib', 'numpy', 'fitz', 'pymupdf'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VA_Document',
    icon='assets/VA_Document.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
