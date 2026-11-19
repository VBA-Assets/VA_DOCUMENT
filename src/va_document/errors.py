"""例外を画面に出すときの文を作る（標準 02「メッセージとエラー」。雛形の errors.py と同じ形。Ver303 で diagnostics.py から分けた）。

このツールが自分で投げる例外（日本語の文の ValueError など）は、利用者に見せる文として書いてあるので、そのまま出す。
OSError（Windows の文と英語の混じった文。ファイルの場所が入ることもある）や、部品が投げる思わぬ例外は、文を出さず、
何が起きたかの要旨と、［ヘルプ］→［診断情報をコピー］の案内を出す（例外の型と場所は、診断情報に記録する）。

日本語を含むかだけでは決めない。部品の例外の文にも、日本語のファイル名が入ることがあるため、誤りが起きた場所が
このツールのパッケージの中かも合わせて見る（2026-11-19、VA mints で分かった）。
"""
import re
import traceback
from pathlib import Path

PACKAGE = __package__ or "va_document"     # このツールのパッケージの名前（写したツールでは、そのツールの名前になる）

# 診断情報の案内（予期しない誤りのときに添える）
DIAGNOSTICS_HINT = "続くときは、［ヘルプ］→［診断情報をコピー］で診断情報をコピーして、記事のコメント欄でお知らせください。"

_JAPANESE = re.compile(r"[぀-ヿ一-鿿]")


def raised_by_this_tool(e):
    """例外が、このツールのコード（パッケージの中）で投げられたか。投げていない例外（作っただけ）は真とする。"""
    frames = traceback.extract_tb(e.__traceback__)
    if not frames:
        return True
    return PACKAGE in Path(frames[-1].filename).parts


def is_for_user(e):
    """例外の文が、利用者向けに書いた文か（このツールが日本語の文で投げたものか）。"""
    if isinstance(e, OSError):
        return False
    return bool(_JAPANESE.search(str(e))) and raised_by_this_tool(e)


def describe(e, detail=True):
    """例外を画面に出すときの文。利用者向けに書いた文なら、そのまま返す。そうでなければ、例外の文（英語やプログラムの
    言葉、ファイルの場所）を出さず、何が起きたかの要旨を返す。detail が真なら、診断情報の案内を添える。"""
    if is_for_user(e):
        return str(e)
    if isinstance(e, PermissionError):
        text = "ほかのソフトがファイルを開いているか、読み書きする権限がありません。"
    elif isinstance(e, FileNotFoundError):
        text = "ファイルかフォルダが見つかりません。"
    elif isinstance(e, FileExistsError):
        text = "同じ名前のファイルかフォルダが、すでにあります。"
    elif isinstance(e, OSError):
        text = "ファイルかフォルダを読み書きできませんでした。"
    else:
        text = "予期しない誤りが起きました。"
    return f"{text}\n\n{DIAGNOSTICS_HINT}" if detail else text
