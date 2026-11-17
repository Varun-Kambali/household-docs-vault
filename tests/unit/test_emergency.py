from datetime import date

from household_vault.emergency import sheet_html


def test_the_emergency_sheet(tmp_path):
    html = sheet_html(tmp_path / "Family Vault", date(2026, 11, 20))
    for text in (
        "KeePassXC",
        "KeePassDX",
        "Secrets.kdbx",
        "Master password:",
        str(tmp_path / "Family Vault"),
    ):
        assert text in html
    assert "<script" not in html and "<link" not in html and 'src="http' not in html


def test_the_sheet_says_where_everything_is_and_when_it_was_printed(tmp_path):
    root = tmp_path / "Family Vault"
    html = sheet_html(root, date(2026, 11, 20))
    assert "Family Vault: emergency sheet" in html
    assert "Google Drive, My Drive, Family Vault" in html
    assert f"{root}/Secrets.kdbx" in html
    assert "keepassxc.org" in html
    assert "Master password: ________________" in html
    assert "Printed on 20 November 2026" in html


def test_the_sheet_is_one_self_contained_a4_page(tmp_path):
    html = sheet_html(tmp_path / "Family Vault", date(2026, 11, 20))
    assert html.startswith("<!doctype html>") and "size: A4" in html
    assert chr(0x2014) not in html and chr(0x2013) not in html
    assert chr(0x2014) not in html and chr(0x2013) not in html


def test_a_path_with_markup_cannot_change_the_page(tmp_path):
    html = sheet_html(tmp_path / "<b>Vault</b> & co", date(2026, 11, 20))
    assert "<b>Vault</b>" not in html and "&lt;b&gt;Vault&lt;/b&gt; &amp; co" in html


def test_the_sheet_holds_no_em_dash_and_no_secret(tmp_path):
    html = sheet_html(tmp_path / "Family Vault", date(2026, 11, 20))
    assert chr(0x2014) not in html and chr(0x2013) not in html
