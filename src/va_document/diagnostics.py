"""診断情報（［ヘルプ］→［診断情報をコピー］。2026-11-10 班長決定。VA mints・VA FAX・VA Case と同じ形）。

不具合を AI や作成者に相談するときに渡す文を作る。中身（文章、仮名化した語と記号、PDF・構文ファイルの名前、ファイルや
フォルダの場所、利用者・PC の名前、例外のメッセージの本文）は、一切入れない。入れてよいのは、版・環境・設定の値
（文書の種類などの選択肢・数値）・件数・字数・誤りの型と起きた場所（ファイル名・行・関数名）だけとする。
例外のメッセージの本文を入れないのは、ファイルの読み書きの誤り（OSError など）のメッセージに、フォルダの場所
（依頼者の名前が入ることがある）が入るため（VA FAX の F-24 と同じ考え方）。

誤りの記録は、この PC の設定と同じフォルダ（%APPDATA%\\VA Document\\errors.json）に書く（閉じた後・落ちた後でも渡せる
ように）。書くのは型と場所だけで、文書の中身は書かない（仕様.md の10）。
"""
import json
import os
import platform
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import config

KEEP_ERRORS = 30     # 覚えておく誤りの数（古いものから消す）
SHOW_ERRORS = 10     # 診断情報に載せる誤りの数（新しいものから）
MAX_FRAMES = 12      # 1つの誤りに載せる場所の数（深い方から）


def exception_record(exc, stage=""):
    """例外を、型の名前と起きた場所だけの記録にする（メッセージの本文は入れない）。"""
    frames = traceback.extract_tb(exc.__traceback__)[-MAX_FRAMES:]
    record = {
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stage": stage,
        "type": type(exc).__name__,
        "where": [f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in frames],
    }
    # OSError の番号（何の誤りかの手がかりになり、場所や名前は含まない）
    for name in ("errno", "winerror"):
        value = getattr(exc, name, None)
        if isinstance(value, int):
            record[name] = value
    cause = exc.__cause__ or exc.__context__
    if cause is not None:
        record["cause"] = type(cause).__name__
    return record


def errors_path():
    """誤りの記録の置き場所（この PC の設定と同じフォルダ）。"""
    return config.config_path().parent / "errors.json"


def _same(a, b):
    return all(a.get(k) == b.get(k) for k in ("stage", "type", "where", "errno", "winerror", "cause"))


class ErrorLog:
    """起きた誤りを覚える（型と場所だけ）。閉じた後や、落ちた後でも渡せるよう、ファイルにも書く。

    書けなくても、画面の動きは止めない（診断のための記録なので）。同じ誤りが続けて起きたとき（プレビューを組むたびに
    同じ誤りになるなど）は、1件にまとめて回数を数える（ほかの誤りが押し出されないように）。
    """

    def __init__(self, path=None):
        self.path = Path(path) if path else errors_path()
        try:
            records = json.loads(self.path.read_text(encoding="utf-8"))
            self.records = [r for r in records if isinstance(r, dict)][-KEEP_ERRORS:]
        except (OSError, ValueError, TypeError):
            self.records = []

    def record(self, exc, stage=""):
        try:
            new = exception_record(exc, stage)
            if self.records and _same(self.records[-1], new):
                last = self.records[-1]
                last["at"] = new["at"]
                last["count"] = int(last.get("count", 1)) + 1
            else:
                self.records.append(new)
                self.records = self.records[-KEEP_ERRORS:]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            # 改行を変えないよう、バイトで書く（Windows の write_text は \n を \r\n にする）
            tmp.write_bytes(json.dumps(self.records, ensure_ascii=False, indent=1).encode("utf-8"))
            os.replace(tmp, self.path)
        except Exception:
            pass

    def clear(self):
        self.records = []
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def format_record(record):
    """1件の誤りを、診断情報に載せる行にする。"""
    head = f"{record.get('at', '')}　{record.get('type', '')}"
    extra = [f"{key}={record[key]}" for key in ("errno", "winerror") if key in record]
    if record.get("cause"):
        extra.append(f"原因 {record['cause']}")
    if int(record.get("count", 1)) > 1:
        extra.append(f"続けて {record['count']} 回")
    if extra:
        head += "（" + "・".join(extra) + "）"
    lines = [head]
    if record.get("stage"):
        lines.append(f"    処理：{record['stage']}")
    for where in record.get("where", []):
        lines.append(f"    {where}")
    return lines


def environment_lines(root, title, version):
    """環境（版・OS・Python/Tk・画面）の行。利用者名・PC 名・フォルダの場所は入れない。"""
    frozen = getattr(sys, "frozen", False)
    lines = [
        f"ツール：{title}  {version}（{'exe' if frozen else 'ソースから起動'}）",
        f"OS：{platform.platform()}",
        f"Python：{platform.python_version()}　Tk：{_tk_patchlevel(root)}",
    ]
    try:
        scale = root.winfo_fpixels("1i") / 96.0
        lines.append(f"画面：{root.winfo_screenwidth()}×{root.winfo_screenheight()}・拡大率 {scale:.0%}・"
                     f"ウィンドウ {root.winfo_width()}×{root.winfo_height()}")
    except Exception:       # 画面の情報が取れなくても、診断情報は作る
        pass
    return lines


def folder_state(path):
    """フォルダの欄の状態（場所は出さない）。"""
    if not path:
        return "設定なし"
    try:
        return "設定あり（フォルダがある）" if Path(path).is_dir() else "設定あり（見つからない）"
    except OSError:
        return "設定あり（確かめられない）"


def _tk_patchlevel(root):
    try:
        return root.tk.call("info", "patchlevel")
    except Exception:
        return "不明"


# ---------------------------------------------------------------- 例外を画面に出すときの文（標準 02「メッセージとエラー」）

DIAGNOSTICS_HINT = "続くときは、［ヘルプ］→［診断情報をコピー］で診断情報をコピーして、記事のコメント欄でお知らせください。"
_JAPANESE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def is_for_user(e):
    """例外の文が、利用者向けに書いた文か。このパッケージが日本語の文で投げる例外（PdfMismatch・PrintError など）は、
    そのまま見せる文として書いてある。OSError（Windows の文と英語の混じった文。ファイルの場所が入る）や、部品が投げる
    英語の文の例外は、そうでない。"""
    if isinstance(e, OSError):
        return False
    return bool(_JAPANESE.search(str(e)))


def describe(e):
    """例外を画面に出すときの文。利用者向けに書いた文なら、そのまま返す。そうでなければ、例外の文（英語やプログラムの
    言葉、ファイルの場所）を出さず、何が起きたかの要旨と、診断情報の案内を返す（VA Case の errors.describe と同じ考え方）。"""
    if is_for_user(e):
        return str(e)
    if isinstance(e, PermissionError):
        text = "ほかのソフトがファイルを開いているか、読み書きする権限がありません。"
    elif isinstance(e, FileNotFoundError):
        text = "ファイルかフォルダが見つかりません。"
    elif isinstance(e, OSError):
        text = "ファイルかフォルダを読み書きできませんでした。"
    else:
        text = "予期しない誤りが起きました。"
    return f"{text}\n{DIAGNOSTICS_HINT}"
