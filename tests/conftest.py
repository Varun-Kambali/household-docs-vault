"""Shared fixtures. The spike set is generated once per session (seed 7, two per type)."""

import random
import string
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import pytest
from vault_synth.cli import generate
from vault_synth.model import SynthDoc

from household_vault import safety
from household_vault.checks import gstin_check_char, verhoeff_valid
from household_vault.config import load_settings
from household_vault.doctypes import DocType
from household_vault.vaultroot import INBOX, NEEDS_A_LOOK, VaultRoot


@pytest.fixture(autouse=True)
def fake_homes(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point $HOME and the password-database home at temp folders for every test.

    The path guard stats folders under the home's Library; no test may look at the real one.
    Returns the $HOME folder; the password-database home is a sibling called "pwd-home".
    """
    base = tmp_path_factory.mktemp("homes")
    home, pwd_home = base / "home", base / "pwd-home"
    home.mkdir()
    pwd_home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("VAULT_REAL_ROOT", raising=False)
    monkeypatch.setattr(safety, "_pwd_home", lambda: pwd_home)
    return home


@pytest.fixture(scope="session")
def spike_docs_all(tmp_path_factory: pytest.TempPathFactory) -> list[SynthDoc]:
    out: Path = tmp_path_factory.mktemp("spike-v0")
    return generate("spike-v0", per_type=2, seed=7, out=out)


@pytest.fixture(scope="session")
def spike_docs(spike_docs_all: list[SynthDoc]) -> Callable[[DocType], list[SynthDoc]]:
    def of_type(doc_type: DocType) -> list[SynthDoc]:
        return [d for d in spike_docs_all if d.doc_type == doc_type]

    return of_type


@pytest.fixture
def vault(tmp_path: Path) -> VaultRoot:
    """A development vault on a temp folder, with Inbox, Needs a look and Home made."""
    root = VaultRoot.from_settings(load_settings(env={"VAULT_ROOT": str(tmp_path / "vault")}))
    for rel in (INBOX, NEEDS_A_LOOK, "Home"):
        root.mkdirs(rel)
    return root


def raise_(exc: BaseException) -> Callable[..., NoReturn]:
    """A function that raises exc whatever it is called with."""

    def fail(*args: object, **kwargs: object) -> NoReturn:
        raise exc

    return fail


class FakeClock:
    """A callable that returns its .t, so a test sets the time by hand."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def valid_aadhaar(rng: random.Random | None = None) -> str:
    """A 12-digit number that passes Verhoeff, built at runtime so no valid one is committed."""
    rng = rng or random.Random()
    body = str(rng.randint(2, 9)) + "".join(rng.choice(string.digits) for _ in range(10))
    return body + next(d for d in string.digits if verhoeff_valid(body + d))


def valid_gstin(rng: random.Random | None = None) -> str:
    """A 15-character GSTIN with its real check character, built at runtime."""
    rng = rng or random.Random()
    body = (
        "29"
        + "".join(rng.choice(string.ascii_uppercase) for _ in range(5))
        + "".join(rng.choice(string.digits) for _ in range(4))
        + rng.choice(string.ascii_uppercase)
        + "1Z"
    )
    return body + gstin_check_char(body)


def one_digit_changed(number: str) -> str:
    """The same number with the digit in the middle moved by one."""
    i = len(number) // 2
    assert number[i].isdigit()
    return number[:i] + str((int(number[i]) + 1) % 10) + number[i + 1 :]


def _pdf_bytes(encrypt: str | None = None) -> bytes:
    import io

    from reportlab.lib.pdfencrypt import StandardEncryption
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    kwargs = {"encrypt": StandardEncryption(encrypt)} if encrypt else {}
    pdf = canvas.Canvas(buf, pagesize=(300, 400), **kwargs)
    pdf.drawString(40, 350, "Synthetic page")
    pdf.save()
    return buf.getvalue()


@pytest.fixture
def clean_pdf_bytes() -> bytes:
    """A one-page PDF with no password."""
    return _pdf_bytes()


@pytest.fixture
def locked_pdf_bytes() -> bytes:
    """A one-page PDF that opens only with the password "pw"."""
    return _pdf_bytes("pw")
