"""Word の文書（.docx）の取り込み（docxmarkdown.py。Ver420。2026-11-24 班長指示。検討_Word文書の読み込み.md）。"""
import io
import zipfile

import pytest
from pypdf import PdfReader

from docxbuild import (dele, docx, field, ins, line_break, p, page_break, pic, png, sect, t, textbox)
from va_document import config, vamd
from va_document.docxmarkdown import DocxError, convert, notices
from va_document.session import NoTextInDocx, Session

BUSINESS = vamd.Settings("Business").normalized()


def md(data, settings=BUSINESS):
    return convert(data, settings)


# ---------- 取り込まないもの（2026-11-24 班長決定） ----------

SECRET_BODY = "".join([
    p(t("通知書"), '<w:jc w:val="center"/>'),
    p(t("先日の打合せのとおり、") + ins("契約を解除します") + dele("和解金として100万円を支払う用意があります") + t("。")),
    p('<w:commentRangeStart w:id="0"/>' + t("期限は来月末とします。") + '<w:commentRangeEnd w:id="0"/>'
      + '<w:r><w:commentReference w:id="0"/></w:r>'),
    p(t("連絡先は") + t("（社内メモ：相手は資金繰りに困っている）", "<w:vanish/>") + t("当職までお願いします。")),
    p(t("根拠は次の条項です") + '<w:r><w:footnoteReference w:id="1"/></w:r>' + t("。")),
    p(textbox("テキストボックスの中の字") + t("本文の続き。")),
    p(t("隠し（文字のスタイル）") + '<w:r><w:rPr><w:rStyle w:val="hide"/></w:rPr><w:t>スタイルで隠した字</w:t></w:r>'),
    p(t("段落ごと隠した段落", "<w:vanish/>"), '<w:rPr><w:vanish/></w:rPr>'),
    p(t("段落記号を消した段落と、"), '<w:rPr><w:del w:id="3" w:author="X"/></w:rPr>'),
    p(t("次の段落。"), '<w:jc w:val="right"/>'),
    '<w:tbl><w:tr><w:tc>' + p(t("項目")) + '</w:tc><w:tc>' + p(t("内容")) + '</w:tc></w:tr>'
    '<w:tr><w:trPr><w:del w:id="4" w:author="X"/></w:trPr><w:tc>' + p(dele("消した行")) + '</w:tc><w:tc>'
    + p(dele("見せない")) + '</w:tc></w:tr>'
    '<w:tr><w:tc>' + p(ins("足した行")) + '</w:tc><w:tc>' + p(t("残す")) + '</w:tc></w:tr></w:tbl>',
    p(t("以上"), '<w:jc w:val="right"/>'),
    sect(),
])
SECRETS = ["100万円", "和解金", "資金繰り", "社内メモ", "再確認", "第１２条", "テキストボックス", "スタイルで隠した",
           "段落ごと隠した", "消した行", "見せない", "作成者の名前", "最後に保存した人", "文書の題"]


def secret_docx():
    return docx(SECRET_BODY, comments=["この期限で本当によいか、依頼者に再確認"], footnotes=["契約書第１２条"])


def test_hidden_information_is_not_taken():
    """変更履歴は、すべて承諾した後の字だけ。コメント・隠し文字・脚注・テキストボックスの字・文書情報は取り込まない。"""
    c = md(secret_docx())
    for word in SECRETS:
        assert word not in c.text, word
    assert c.text.splitlines() == [
        ":=: 通知書", "先日の打合せのとおり、契約を解除します。", "期限は来月末とします。", "連絡先は当職までお願いします。",
        "根拠は次の条項です。", "本文の続き。", "隠し（文字のスタイル）",
        "--: 段落記号を消した段落と、次の段落。",           # 段落記号を消すと、後の段落とつながり、後の段落の配置になる
        "| 項目 | 内容 |", "|---|---|", "| 足した行 | 残す |", "--: 以上"]


def test_notices_tell_what_was_left_out():
    """取り込まなかったものの数と、変更履歴を承諾した後の字を取ったことを知らせる（2026-11-24 班長決定）。"""
    msgs = notices(md(secret_docx()).report)
    assert msgs[0] == "変更履歴は、すべて承諾した後の字を取りました（削除した字・行は取り込んでいません）。"
    assert msgs[1] == ("次のものは取り込んでいません：コメント 1 個、隠し文字 38 字、脚注・文末脚注 1 個、"
                       "テキストボックス・図形の中の字 1 か所。")
    assert notices(md(docx(p(t("本文")) + sect())).report) == []


def test_session_does_not_leak_into_vamd_or_pdf(tmp_path):
    """開いて保存しても、取り込まなかった字は、構文ファイルにも PDF にも入らない。docx の名前・場所も書かない。"""
    src = tmp_path / "依頼者甲野の通知書.docx"
    src.write_bytes(secret_docx())
    s = Session(config.AppConfig(vamd_folder=str(tmp_path / "構文ファイル")))
    r = s.open_docx(src)
    assert "変更履歴は、すべて承諾した後の字" in r.messages[0] and "コメント 1 個" in r.messages[0]
    pdf = tmp_path / "通知書.pdf"
    s.save(r.text, pdf)
    vamd_text = s.vamd_path.read_text(encoding="utf-8")
    pdf_text = "".join(page.extract_text() for page in PdfReader(str(pdf)).pages).replace("\n", "")
    for word in SECRETS + ["依頼者甲野", str(tmp_path)]:
        assert word not in vamd_text and word not in pdf_text, word
    assert "契約を解除します" in pdf_text
    assert src.read_bytes() == secret_docx()            # 開いた docx は書き換えない


# ---------- 見出し・番号・書式 ----------

def test_headings_come_from_word_levels_not_number_text():
    """見出しのスタイル（アウトラインのレベル）の段落は、そのレベルの見出しにする。Word の自動の番号は字にしない
    （2026-11-24 班長指摘）。手で打った同じ番号は外し、違う番号は字のまま残す。"""
    body = "".join([
        p(t("当事者"), '<w:pStyle w:val="1"/>'),
        p(t("原告"), '<w:pStyle w:val="2"/>'),
        p(t("住所"), '<w:pStyle w:val="3"/>'),
        p(t("第２　主張"), '<w:pStyle w:val="1"/>'),        # 組んだときと同じ番号を手で打った
        p(t("第９　飛んだ番号"), '<w:pStyle w:val="1"/>'),   # 組んだときと違う番号
        p(t("本文"), '<w:outlineLvl w:val="1"/>'),           # 段落に直接付けたレベル
        sect(),
    ])
    c = md(docx(body), vamd.Settings("Saiban").normalized())
    assert c.text.splitlines() == ["# 当事者", "## 原告", "### 住所", "# 主張", "# 第９　飛んだ番号", "## 本文"]
    assert c.settings.doc_type == "Saiban"                  # 見出しのレベルのある文書は、今の設定の文書の種類


def test_list_numbers_without_levels():
    """見出しのレベルのない段落に Word が振った番号：全角・半角まで見出しの番号と同じなら見出し（契約書の「第１条」）、
    でなければ段落番号・箇条書き。"""
    body = "".join([
        p(t("目的"), '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr>'),
        p(t("定義"), '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr>'),
        p(t("一つ目"), '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="3"/></w:numPr>'),
        p(t("二つ目"), '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="3"/></w:numPr>'),
        p(t("箇条書き"), '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="4"/></w:numPr>'),
        sect(),
    ])
    lines = md(docx(body), vamd.Settings("Keiyaku2").normalized()).text.splitlines()
    assert lines == ["# 目的", "# 定義", "1. 一つ目", "2. 二つ目", "- 箇条書き"]
    lines = md(docx(body), vamd.Settings("Saiban").normalized()).text.splitlines()
    assert lines[:2] == ["1. 目的", "2. 定義"] and lines[-1] == "- 箇条書き"


def test_hand_typed_numbers_are_read_like_pdf():
    """番号もレベルもない段落の先頭に手で打った番号は、PDF の取り込みと同じく字から読む（VA疑似アウトライン）。"""
    body = "".join(p(t(s)) for s in ["準備書面", "第１　当事者", "　当事者の本文。", "１(1)　原告の住所", "ア　会社員",
                                     "・箇条書き", "第２　主張"]) + sect()
    lines = md(docx(body), vamd.Settings("Saiban").normalized()).text.splitlines()
    assert lines == ["準備書面", "# 当事者", "　当事者の本文。", "##", "### 原告の住所", "#### 会社員", "- 箇条書き",
                     "# 主張"]


def test_inline_formats_alignment_and_indent():
    """太字・傍点・蛍光ペン、中央・右、最初の見出しより前の段落の字下げ。"""
    body = "".join([
        p(t("準備書面"), '<w:jc w:val="center"/>'),
        p(t("令和８年１月１日"), '<w:jc w:val="right"/>'),
        p(t("前文の字下げ"), '<w:ind w:firstLineChars="100" w:firstLine="240"/>'),
        p(t("当事者"), '<w:pStyle w:val="1"/>'),
        p(t("原告は、") + t("株式会社", "<w:b/>") + t("である。") + t("重要", '<w:em w:val="dot"/>')
          + t("な点", '<w:highlight w:val="yellow"/>') + t("と", "") + t("両方", '<w:b/><w:highlight w:val="yellow"/>')),
        p(t("星*印", "<w:b/>")),                             # 記号と重なる字は、書式を付けない（字を変えない）
        sect(),
    ])
    lines = md(docx(body)).text.splitlines()
    assert lines == [":=: 準備書面", "--: 令和８年１月１日", "　前文の字下げ", "# 当事者",
                     "原告は、**株式会社**である。*重要*==な点==と**==両方==**", "星*印"]


def test_tables_toc_breaks_header_footer_page_number():
    toc = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" </w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')
    body = "".join([
        p(toc + t("第１　当事者\t1")),
        p(t("第２　主張\t2") + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'),
        p(t("当事者") + page_break(), '<w:pStyle w:val="1"/>'),
        p(t("改ページの後") + line_break() + t("改行の後")),
        p(t("前の段落の前で改ページ"), '<w:pageBreakBefore/>'),
        '<w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>' + p(t("結合")) + '</w:tc><w:tc>' + p(t("金額"))
        + '</w:tc></w:tr><w:tr><w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr>' + p(t("甲")) + '</w:tc><w:tc>'
        + p(t("1行目")) + '</w:tc><w:tc>' + p(t("|100")) + '</w:tc></w:tr><w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr>' + p("")
        + '</w:tc><w:tc>' + p(t("2行目")) + '</w:tc><w:tc>' + p(t("200")) + '</w:tc></w:tr></w:tbl>',
        p(t("リンク：") + field("HYPERLINK \"https://example.com\"", "例のページ")),
        sect(header=True, footer=True, line_numbers=True),
    ])
    c = md(docx(body, header=p(t("令和８年（ワ）第１２３号"), '<w:jc w:val="right"/>'),
                footer=p('<w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>', '<w:jc w:val="center"/>')),
           vamd.Settings("Saiban").normalized())
    assert c.text.splitlines() == [
        "[HEADER] --: 令和８年（ワ）第１２３号", "[TOC]", "# 当事者", "<<<", "改ページの後", "改行の後", "<<<",
        "前の段落の前で改ページ", "| 結合 |  | 金額 |", "|---|---|---|", "| 甲 | 1行目 | \\|100 |", "|  | 2行目 | 200 |",
        "リンク：例のページ"]
    assert c.settings.page_number == "BottomCenter" and c.settings.line_numbers
    assert notices(c.report) == ["段落の中の改行 1 か所は、段落を分けました。"]


def test_page_number_positions():
    for footer, jc, want in (("1", "right", "BottomRight"), ("- 1 -", "center", "BottomCenterDecorated")):
        f = p('<w:fldSimple w:instr=" PAGE "><w:r><w:t>' + footer + '</w:t></w:r></w:fldSimple>', f'<w:jc w:val="{jc}"/>')
        assert md(docx(p(t("本文")) + sect(footer=True), footer=f)).settings.page_number == want
    h = p(field("PAGE", "1"), '<w:jc w:val="right"/>')
    assert md(docx(p(t("本文")) + sect(header=True), header=h)).settings.page_number == "TopRight"
    assert md(docx(p(t("本文")) + sect())).settings.page_number == "None"


def test_doc_type_from_page_geometry():
    """用紙・余白・1行の字数が VA Document の文書の種類に合えば、その種類にする（VA公用文で整えた文書など）。"""
    from va_document.doctypes import DOC_TYPES, MM
    dt = DOC_TYPES["Saiban"]
    top, bottom, left, right = (round(v * MM * 20) for v in dt.margins)
    width = 11906 - left - right
    pitch = width / 20 / dt.chars_lines[0]
    grid = round((pitch - 12) * 4096)
    body = p(t("本文")) + sect(margins=(top, right, bottom, left), grid=grid)
    assert md(docx(body), vamd.Settings("Business").normalized()).settings.doc_type == "Saiban"


# ---------- 画像とキャプション（2026-11-24 班長決定「画像は取り込む」） ----------

def test_images_and_captions(tmp_path):
    """画像は付加情報を除いて取り込み、行内の画像は段落の中の位置に、浮動の画像は段落の後ろに置く。キャプションは
    普通の段落として字のまま残る。テキストボックスのキャプションは落ちる。"""
    body = "".join([
        p(pic(8), '<w:jc w:val="center"/>'),
        p(t("図 ") + field("SEQ 図 \\* ARABIC", "1") + t("　見取図"), '<w:pStyle w:val="caption"/><w:jc w:val="center"/>'),
        p(pic(5) + line_break() + t("写真１　正面から"), '<w:jc w:val="center"/>'),
        p(pic(4, anchor=True) + t("本文の段落に、浮動の画像をつないだ。")),
        p(pic(5, anchor=True) + textbox("写真３　背面から")),
        p(pic(3, crop=(25000, 0, 25000, 0))),
        p(pic(3, rid="rIdEmf")),
        sect(),
    ])
    data = docx(body, images={"rIdImg": ("image1.png", png(text_chunk="撮影者の名前")),
                              "rIdEmf": ("image2.emf", b"not an image")})
    c = md(data)
    # 最初の見出しより前の、最初の中央の段落は表題になる（PDF の取り込みと同じ規則）
    assert c.text.splitlines() == [
        ":-: [IMAGE 1]{19}", ":=: **図 1　見取図**", ":-: [IMAGE 2]{12}", ":-: 写真１　正面から",
        "本文の段落に、浮動の画像をつないだ。", "[IMAGE 3]{9}", "[IMAGE 4]{12}", "[IMAGE 5]{7}"]
    assert sorted(c.pictures) == [1, 2, 3, 4, 5]
    assert c.pictures[5].size == (100, 100)                  # 切り抜いた後の画像
    for pic_ in c.pictures.values():
        assert "撮影者の名前".encode("utf-8") not in pic_.data and b"Author" not in pic_.data
    assert notices(c.report) == [
        "次のものは取り込んでいません：テキストボックス・図形の中の字 1 か所、読めない形式の画像（EMF など） 1 個。",
        "画像 5 個を取り込みました（文字列の折り返しを指定した画像 2 個は、置いてあった段落の後ろに置きました）。",
        "段落の中の改行 1 か所は、段落を分けました。"]
    # 保存すると PDF に5か所の画像が入り、構文ファイルには記号の行だけが入る
    src = tmp_path / "写真.docx"
    src.write_bytes(data)
    s = Session(config.AppConfig(vamd_folder=str(tmp_path / "構文ファイル")))
    r = s.open_docx(src)
    pdf = tmp_path / "写真.pdf"
    s.save(r.text, pdf)
    import pypdfium2
    page = pypdfium2.PdfDocument(str(pdf))[0]
    assert len(list(page.get_objects(filter=[3]))) == 5
    vamd_bytes = s.vamd_path.read_bytes()
    assert b"PNG" not in vamd_bytes and "[IMAGE 5]{7}".encode() in vamd_bytes


# ---------- 読めない文書 ----------

def test_unreadable_documents(tmp_path):
    with pytest.raises(DocxError, match="パスワード"):
        md(b"\xd0\xcf\x11\xe0 old doc")
    evil = docx(p(t("本文")) + sect())
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(evil)) as zin, zipfile.ZipFile(buf, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = data.replace(b"<w:document", b'<!DOCTYPE x [<!ENTITY a "aaaa">]><w:document', 1)
            zout.writestr(item, data)
    with pytest.raises(DocxError):
        md(buf.getvalue())
    s = Session(config.AppConfig(vamd_folder=str(tmp_path / "構文ファイル")))
    empty = tmp_path / "空.docx"
    empty.write_bytes(docx(p("") + sect()))
    with pytest.raises(NoTextInDocx):
        s.open_docx(empty)


def test_strict_namespace_is_read():
    """Strict 形式（ISO の厳密な形。Word の［名前を付けて保存］で選べる）の名前空間も読む。"""
    data = docx(p(t("厳密な形")) + sect())
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(buf, "w") as zout:
        for item in zin.infolist():
            raw = zin.read(item.filename).replace(b"http://schemas.openxmlformats.org/wordprocessingml/2006/main",
                                                  b"http://purl.oclc.org/ooxml/wordprocessingml/main")
            zout.writestr(item, raw)
    assert md(buf.getvalue()).text == "厳密な形"
