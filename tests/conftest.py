"""試験の道具（標準 02「テスト」）。

設定と誤りの記録は、一時フォルダに置く（班長の設定〔%APPDATA%\\VA Document〕に書かない）。
使う字・ファイルの名前はすべて架空のもの（実データは使わない）。
"""
import os
import tempfile

import pytest


@pytest.fixture(scope="session", autouse=True)
def _session_config_dir():
    """試験の全体で使う置き場所。画面（test_app.py の main_window）のように、試験ごとの fixture より先に作るものも、
    班長の設定を読み書きしないようにする。"""
    with tempfile.TemporaryDirectory() as folder:
        old = os.environ.get("VA_DOCUMENT_CONFIG_DIR")
        os.environ["VA_DOCUMENT_CONFIG_DIR"] = folder
        yield folder
        if old is None:
            os.environ.pop("VA_DOCUMENT_CONFIG_DIR", None)
        else:
            os.environ["VA_DOCUMENT_CONFIG_DIR"] = old


@pytest.fixture(autouse=True)
def _config_dir(tmp_path, monkeypatch):
    """試験ごとの置き場所。"""
    folder = tmp_path / "設定"
    monkeypatch.setenv("VA_DOCUMENT_CONFIG_DIR", str(folder))
    return folder
