"""診断情報（［ヘルプ］→［診断情報をコピー］。2026-11-10 班長決定）の部品の試験。画面の側は test_app.py。

要点：中身（文章、ファイルの名前、ファイルやフォルダの場所、例外のメッセージの本文）が一切入らないこと
（diagnostics.py の冒頭。VA FAX の F-24 と同じ考え方）。
"""
import json

from va_document import config, diagnostics


def _raise_with_secret():
    raise OSError(13, "アクセスが拒否されました", r"C:\Users\秘密太郎\事件\準備書面（甲野）.pdf")


def test_exception_record_hides_message_and_paths():
    try:
        _raise_with_secret()
    except OSError as exc:
        record = diagnostics.exception_record(exc, "保存")
    dumped = json.dumps(record, ensure_ascii=False)
    # errno 13 の OSError は、Python が PermissionError に読み替える
    assert record["type"] == "PermissionError" and record["stage"] == "保存"
    assert record["errno"] == 13
    assert any("test_diagnostics.py" in w for w in record["where"])      # 場所（ファイル名・行・関数名）は入る
    assert "秘密太郎" not in dumped and "甲野" not in dumped              # メッセージの本文・パスは入らない
    assert "アクセスが拒否" not in dumped


def test_exception_record_includes_cause_type():
    try:
        try:
            raise ValueError("元の誤り")
        except ValueError as inner:
            raise RuntimeError("包んだ誤り") from inner
    except RuntimeError as exc:
        record = diagnostics.exception_record(exc)
    assert record["cause"] == "ValueError"
    assert "元の誤り" not in json.dumps(record, ensure_ascii=False)


def _record_value_error(log, i, stage="試験"):
    try:
        raise ValueError(f"誤り {i}")
    except ValueError as exc:
        log.record(exc, stage)


def test_error_log_persists_and_caps(tmp_path):
    path = tmp_path / "errors.json"
    log = diagnostics.ErrorLog(path)
    for i in range(diagnostics.KEEP_ERRORS + 5):
        _record_value_error(log, i, f"試験 {i}")                         # 処理の名前が違えば、別の誤り
    assert len(log.records) == diagnostics.KEEP_ERRORS                   # 上限で古いものから消える
    assert log.records[0]["stage"] == "試験 5"
    reloaded = diagnostics.ErrorLog(path)                                # 別の起動でも読み戻せる
    assert len(reloaded.records) == diagnostics.KEEP_ERRORS
    assert reloaded.records[-1]["type"] == "ValueError"
    assert b"\r\n" not in path.read_bytes()                              # 改行を変えない
    log.clear()
    assert not path.exists() and log.records == []


def test_same_error_in_a_row_is_counted(tmp_path):
    """プレビューを組むたびに同じ誤りになるときは、1件にまとめて回数を数える（ほかの誤りを押し出さない）。"""
    log = diagnostics.ErrorLog(tmp_path / "errors.json")
    for i in range(50):
        _record_value_error(log, i)
    assert len(log.records) == 1 and log.records[0]["count"] == 50
    assert "続けて 50 回" in diagnostics.format_record(log.records[0])[0]
    _record_value_error(log, 0, "別の処理")
    assert len(log.records) == 2


def test_error_log_survives_broken_file(tmp_path):
    path = tmp_path / "errors.json"
    path.write_bytes("{壊れたJSON".encode("utf-8"))
    log = diagnostics.ErrorLog(path)
    assert log.records == []                                             # 壊れていても起動を妨げない
    _record_value_error(log, 1)
    assert len(diagnostics.ErrorLog(path).records) == 1


def test_error_log_never_raises(tmp_path):
    """書けない場所でも、画面の動きを止めない。"""
    blocker = tmp_path / "ファイル"
    blocker.write_bytes(b"")
    log = diagnostics.ErrorLog(blocker / "errors.json")                  # ファイルの下には書けない
    _record_value_error(log, 1)
    assert len(log.records) == 1


def test_errors_path_is_next_to_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "VA Document" / "settings.json")
    assert diagnostics.errors_path() == tmp_path / "VA Document" / "errors.json"


def test_folder_state_hides_location(tmp_path):
    secret = tmp_path / "甲野太郎の事件"
    secret.mkdir()
    assert diagnostics.folder_state(str(secret)) == "設定あり（フォルダがある）"
    assert diagnostics.folder_state(str(tmp_path / "ない")) == "設定あり（見つからない）"
    assert diagnostics.folder_state("") == "設定なし"
