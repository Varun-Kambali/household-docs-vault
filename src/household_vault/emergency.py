"""The printable emergency sheet: where the vault and its secrets file are, and how to open the
file with a standard KeePass app if the owner's Mac or this app is not there.

The master password is never printed. The sheet has a line to fill in by hand, and it is kept
with the original papers (ADR 0004). One self-contained A4 page: inline styles, no scripts, no
links, no fonts from outside.
"""

from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path

from household_vault.vaultroot import SECRETS_FILE

TITLE = "Family Vault: emergency sheet"
DRIVE_PLACE = "Google Drive, My Drive, Family Vault"

_STYLE = """
@page { size: A4; margin: 18mm; }
* { box-sizing: border-box; }
body { margin: 0; color: #111; background: #fff; font: 12pt/1.5 Georgia, "Times New Roman", serif; }
main { max-width: 174mm; margin: 0 auto; padding: 8mm 0; }
h1 { font-size: 20pt; margin: 0 0 6mm; }
h2 { font-size: 13pt; margin: 7mm 0 2mm; }
p, ol, ul { margin: 0 0 3mm; }
ol, ul { padding-left: 6mm; }
code { font: 11pt/1.4 Menlo, Consolas, monospace; overflow-wrap: anywhere; }
.pw { margin: 8mm 0 4mm; padding: 4mm; border: 1.5px solid #111; font-size: 14pt; }
.small { font-size: 10pt; color: #333; }
@media print { main { padding: 0; } }
""".strip()


def sheet_html(vault_root: Path, made_on: date) -> str:
    folder = escape(str(vault_root))
    file_path = escape(str(vault_root / SECRETS_FILE))
    printed = f"{made_on.day} {made_on:%B %Y}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(TITLE)}</title>
<style>
{_STYLE}
</style>
</head>
<body>
<main>
<h1>{escape(TITLE)}</h1>

<h2>Where everything is</h2>
<p>The documents are in the folder <strong>{escape(DRIVE_PLACE)}</strong> in Google Drive.
On the Mac the folder is <code>{folder}</code>.</p>
<p>Card numbers, security codes, PINs and passwords are not in the documents. They are in one
encrypted file, <code>{escape(SECRETS_FILE)}</code>, in that same folder:
<code>{file_path}</code>. Without the master password below, nobody can read it.</p>

<h2>Open it on a computer</h2>
<ol>
<li>Install KeePassXC from keepassxc.org. It is free.</li>
<li>Download {escape(SECRETS_FILE)} from the Drive folder to the computer.</li>
<li>In KeePassXC choose Open Database, pick the file, and type the master password.</li>
<li>The groups are Cards and Documents. Open an entry to see its number, security code and
photos.</li>
</ol>

<h2>Open it on an Android phone</h2>
<ol>
<li>Install KeePassDX from the Play Store. It is free.</li>
<li>Open it, choose Open existing database, and pick {escape(SECRETS_FILE)} from Google Drive.</li>
<li>Type the master password.</li>
</ol>

<p class="pw">Master password: ________________</p>
<p class="small">Write the master password by hand and keep this sheet with the original
papers. Do not keep it in the Drive folder.</p>

<p class="small">Printed on {escape(printed)}</p>
</main>
</body>
</html>
"""
