"""例外を画面に出すときの文（標準 02「メッセージとエラー」）。使う字・ファイルの名前は架空のもの。"""
from va_document import errors


def test_own_japanese_message_is_shown():
    """このツールが日本語の文で作った例外は、そのまま出す（ここでは投げずに作ったもので確かめる。試験のファイルは
    パッケージの外なので、ここで投げると部品の例外と同じに扱われる）。"""
    e = ValueError("字の大きさは、8〜20 の数で入れてください。")
    assert errors.describe(e) == str(e)


def test_os_error_is_summarized():
    e = PermissionError(13, "Access is denied", r"C:\架空のフォルダ\文書.txt")
    text = errors.describe(e)
    assert "架空のフォルダ" not in text and "Access" not in text and "診断情報" in text


def test_library_error_with_japanese_file_name_is_summarized():
    """部品の中で投げられた例外は、日本語のファイル名を含んでいても、文を出さない。"""
    try:
        int("架空の文書.json")          # 部品（ここでは Python）が、日本語を含む文で投げる
    except ValueError as e:
        assert not errors.is_for_user(e)
        assert "架空の文書" not in errors.describe(e)
