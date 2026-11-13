# VA Document — 実名を AI に渡さずに、VA公用文と同じ書式の文書を作るツール

VA Document は、AI（Claude など）で書面を起案・推敲するときに、依頼者などの名前を記号（〔人名Ａ〕など）に置き換えてから渡し、AI の回答を取り込むと元の名前に戻し、裁判所提出書類・公用文・契約書などを VA公用文（Word のアドイン）で整えたものと同じ書式の PDF にする、Windows 用の無料ツールです（Python 製）。Word とは別のプログラムで、書く・仮名化する・AI とやり取りする・PDF に仕上げるまでを1つの画面で行います。

Ver160 までは「VA DocuMake」という名前でした（2026-10-27 の Ver200 で改めました）。

- 配布：[VBAアセット](https://vba-assets.net/)（実行ファイルとインストーラーは、サイトの記事からダウンロードしてください）
- ライセンス：MIT License（[LICENSE](LICENSE)。Ver300 から。Ver2A0 までは GNU Affero General Public License 第3版）。使っている部品のライセンスは [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)
- 操作マニュアル：[docs/manual/VA_Document_操作マニュアル.md](docs/manual/VA_Document_操作マニュアル.md)
- 仕様：[仕様.md](仕様.md)

## フォルダの構成

| フォルダ・ファイル | 内容 |
|---|---|
| `src/va_document/` | 本体のソース |
| `tests/` | テスト（pytest）。`tests/data/` は、VA公用文で整えた見本の文書と、その字の位置（正解） |
| `scripts/` | マニュアルの PDF・アイコン・ライセンスの表示・配布物を作るスクリプト |
| `assets/` | アプリのアイコン |
| `main.py` | ソースから起動するときの入口 |
| `va_document.spec` | 実行ファイルを作る PyInstaller の設定 |

開発用の内部資料（検討のメモ、VA公用文の正解を作るために Word を操作する試作の道具）は、このリポジトリには含めていません。ソースのコメントでそれらを参照している箇所があります。

## ソースから動かす

Windows 10・11 と Python 3 で動かします。

```
python -m pip install -r requirements.txt
python main.py
```

### Mac で動かす（動作は保証しません）

Mac 用の実行ファイルは配っていません。Python 3（Tk の入ったもの。python.org の macOS 用のインストーラーの Python には入っています）で、ソースから動かしてください。

```
python3 -m pip install -r requirements.txt
python3 main.py
```

- PDF の書体は、Windows ではＭＳ 明朝・ＭＳ ゴシック、Mac などＭＳ 明朝のない PC では、同梱の IPA明朝・IPAゴシック（`assets/fonts/`。IPAフォントライセンス v1.0）を使います。字の位置・行の切れ目・ページの切れ目は Windows と同じで、字の形だけが違います。
- ［印刷］は使えません（Windows だけ）。保存した PDF を開いて印刷してください。
- Ctrl のキー（Ctrl+S など）は、⌘ でも効きます（置換の Ctrl+H は Ctrl だけ。⌘H は Mac の「隠す」のため）。
- Mac の実機では動作を確かめていません。

テストは `python -m pytest` で走ります。実行ファイルは `python -m PyInstaller va_document.spec --noconfirm` で `dist\VA_Document.exe` にできます。

## ライセンス

Copyright (c) 2026 VBAアセット

MIT License で公開しています。著作権の表示とライセンスの文を残せば、使う・直す・配る・売ることが自由にできます。何の保証もありません。詳しくは [LICENSE](LICENSE) をご覧ください。

Ver2A0 までは、PDF の表示・印刷・読み書きに AGPL-3.0 の PyMuPDF を使っていたため、GNU Affero General Public License 第3版で公開していました。Ver300 で、PDF を扱う部品を MIT License と両立するもの（pdfplumber・pypdf・pypdfium2）に替え、MIT License に改めました。それまでに公開した版は、手に入れた方にとっては AGPL-3.0 のままです。

ボタンのアイコンの PNG（`src/va_document/icons/png/`）は、開発のときに `scripts/make_icons.py` で SVG から作ります。このスクリプトだけは PyMuPDF を使います（開発の PC に入れるもので、`requirements.txt` には入れていません。配布物には入りません）。
