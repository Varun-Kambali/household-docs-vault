"""Shared fixtures. The spike set is generated once per session (seed 7, two per type)."""

import csv
import hashlib
import io
import random
import sqlite3
import string
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, NoReturn

import pytest
from vault_synth.cli import generate
from vault_synth.household import HOUSEHOLD
from vault_synth.model import SynthDoc
from vault_synth.sets import load_set, locked_password

from household_vault import safety
from household_vault.actions import Actions
from household_vault.activity import Activity
from household_vault.checks import gstin_check_char, verhoeff_valid
from household_vault.config import load_settings
from household_vault.db import DocumentRow, Item, Store, connect, migrate
from household_vault.doctypes import REQUIRED, DocType
from household_vault.filing.filer import Filer
from household_vault.filing.records import stored_reading
from household_vault.reading.cues import CueCheck
from household_vault.reading.engines import Engines, PageReader
from household_vault.reading.lines import Line
from household_vault.reading.pipeline import Reading
from household_vault.reasons import Reason
from household_vault.vaultroot import INBOX, NEEDS_A_LOOK, VaultRoot
from household_vault.worker import CardHandler, HoldCards, Worker
from tests.fakes import EVAL_V1, TruthModels, TruthPages


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


SPIKE_DIR = Path(__file__).resolve().parents[1] / "evals" / "datasets" / "spike-v0"


@pytest.fixture(scope="session")
def spike_docs_all() -> list[SynthDoc]:
    """The committed, frozen spike-v0 set."""
    return load_set(SPIKE_DIR)


@pytest.fixture(scope="session")
def eval_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("eval-v1")


@pytest.fixture(scope="session")
def eval_docs(eval_dir: Path) -> list[SynthDoc]:
    """The test split of the nine hand-drawn types, generated once into `eval_dir`."""
    return generate("eval-v1", eval_dir, splits=("test",))


def group_by_base(docs: list[SynthDoc]) -> dict[str, list[SynthDoc]]:
    groups: dict[str, list[SynthDoc]] = {}
    for d in docs:
        groups.setdefault(d.base_id, []).append(d)
    return groups


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
    pdf.drawString(40, 330, "Policy schedule for the reader tests")
    pdf.save()
    return buf.getvalue()


@pytest.fixture
def clean_pdf_bytes() -> bytes:
    """A one-page PDF with no password. Its second line makes it read as a health policy page
    with the stand-in models ("policy schedule")."""
    return _pdf_bytes()


@pytest.fixture
def locked_pdf_bytes() -> bytes:
    """A one-page PDF that opens only with the password "pw"."""
    return _pdf_bytes("pw")


class AwareClock:
    """A callable that returns a settable, timezone-aware datetime."""

    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def set(self, t: datetime) -> None:
        self.t = t

    def advance(self, seconds: float = 0.0) -> None:
        self.t = self.t + timedelta(seconds=seconds)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 11, 20, 9, 0).astimezone()


@pytest.fixture
def clock(now: datetime) -> AwareClock:
    return AwareClock(now)


@pytest.fixture
def store(tmp_path: Path, clock: AwareClock) -> Iterator[Store]:
    """A migrated database outside the vault, with the synthetic household loaded."""
    conn = connect(tmp_path / "db" / "vault.db", tmp_path / "vault")
    migrate(conn)
    s = Store(conn, clock)
    s.set_household(HOUSEHOLD)
    yield s
    conn.close()


@pytest.fixture
def activity(store: Store, vault: "VaultRoot", clock: AwareClock) -> Activity:
    return Activity(store, vault, clock)


def row(doc_id: str, **fields: Any) -> DocumentRow:
    """A DocumentRow with plain defaults (item 1, owner p1); no database involved."""
    values: dict[str, Any] = {
        "id": doc_id,
        "item_id": 1,
        "doc_type": DocType.health_policy,
        "owner": "p1",
        "area": "insurance",
        "rel_path": f"Ravi Kumar Rao/Insurance/{doc_id}.pdf",
        "sha256": "c" * 64,
        "doc_date": date(2026, 11, 1),
        "date_source": "document",
        "description": "Health policy",
        "created_at": datetime(2026, 11, 20, 9, 0).astimezone(),
    }
    values.update(fields)
    return DocumentRow(**values)


TODAY = date(2026, 11, 20)


def reading_of(doc_type: DocType | None, **fields: Any) -> Reading:
    """A Reading as the reader would return it. Every REQUIRED field of the type holds a
    placeholder unless given (None leaves it out); `type_check` is "agrees" unless given;
    `issues` and `secret_values` are passed through."""
    issues = fields.pop("issues", {})
    secret_values = fields.pop("secret_values", {})
    type_check = fields.pop("type_check", CueCheck("agrees"))
    values: dict[str, Any] = {}
    if doc_type is not None:
        for name in sorted(REQUIRED.get(doc_type, ())):
            is_date = name == "date" or name.endswith("_date")
            values[name] = "2026-05-01" if is_date else f"Placeholder {name.replace('_', ' ')}"
    values.update(fields)
    return Reading(
        pages=[],
        english_letters=200,
        doc_type=doc_type,
        type_check=type_check if doc_type is not None else None,
        fields={k: v for k, v in values.items() if v is not None},
        issues=issues,
        secret_values=secret_values,
    )


def item_id(store: Store) -> int:
    """Add a queued item (no job) and return its id."""
    n = store.conn.execute("select count(*) from items").fetchone()[0]
    when = datetime(2026, 11, 20, 8, 0).astimezone()
    return store.add_item(f"{n:064x}", f"f{n}.pdf", f"Inbox/f{n}.pdf", when).id


def line(text: str) -> Line:
    return Line(text=text, bbox=(0.0, 0.0, 1.0, 0.1))


def csv_rows(vault: "VaultRoot", rel: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(vault.read_bytes(rel).decode("utf-8"))))


def reopen(store: Store) -> sqlite3.Connection:
    """A new connection to the same database file."""
    path = store.conn.execute("pragma database_list").fetchone()[2]
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


@pytest.fixture(scope="session")
def photo() -> bytes:
    """The JPEG bytes of one committed eval-v1 val photo (a health policy)."""
    return (EVAL_V1 / "health_policy-1-photo.jpg").read_bytes()


@pytest.fixture
def five_page_scan_pdf() -> bytes:
    """An image-only five-page PDF (no text layer), built with Pillow."""
    from PIL import Image

    pages = [Image.new("RGB", (300, 400), (255 - 20 * i, 255, 255)) for i in range(5)]
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()


# -- the whole intake, wired together (Task 19) ---------------------------------------------------


@dataclass
class World:
    vault: VaultRoot
    store: Store
    activity: Activity
    filer: Filer
    worker: Worker
    actions: Actions
    clock: AwareClock
    db_dir: Path

    def drain(self) -> None:
        self.worker.drain()


@pytest.fixture
def make_world(
    tmp_path: Path, vault: VaultRoot, store: Store, activity: Activity, clock: AwareClock
) -> Callable[..., World]:
    """A dev vault, store, filer, worker and actions with no settling delay. By default the
    engines answer from the eval-v1 truth and cards wait for the secrets store."""

    def build(
        pages: PageReader | None = None,
        models: TruthModels | None = None,
        cards: CardHandler | None = None,
    ) -> World:
        settings = load_settings(env={"VAULT_ROOT": str(vault.root)}).model_copy(
            update={"settle_seconds": 0.0}
        )
        vault.mkdirs("_system")  # as start-up makes it
        household = store.household()
        filer = Filer(vault, store, activity, household, clock)
        handler = cards if cards is not None else HoldCards()
        if hasattr(handler, "filer"):
            handler.filer = filer
        engines = Engines(pages or TruthPages(), models or TruthModels())
        worker = Worker(settings, vault, store, activity, engines, filer, handler, clock)
        actions = Actions(worker, filer, store, activity, household)
        return World(vault, store, activity, filer, worker, actions, clock, tmp_path / "db")

    return build


@pytest.fixture
def world(make_world: Callable[..., World]) -> World:
    return make_world()


@pytest.fixture
def asked_item(world: World, now: datetime) -> Item:
    """A card item waiting in Needs a look with a stored reading of its type."""
    data = b"card photo bytes"
    world.vault.write_atomic(f"{NEEDS_A_LOOK}/card.jpg", data)
    item = world.store.add_item(
        hashlib.sha256(data).hexdigest(), "card.jpg", f"{NEEDS_A_LOOK}/card.jpg", now
    )
    return world.store.update_item(
        item.id,
        state="asked",
        kind="jpeg",
        reasons=[Reason.card_unreadable],
        reading=stored_reading(reading_of(DocType.card_front)),
    )


def drop(vault: VaultRoot, name: str, data: bytes) -> None:
    """Put a file in Inbox, as Drive would."""
    vault.write_atomic(f"{INBOX}/{name}", data)


@dataclass(frozen=True)
class Fileable:
    doc: SynthDoc
    data: bytes
    sha: str


@lru_cache(maxsize=1)
def _eval_docs() -> list[SynthDoc]:
    return [d for d in load_set(EVAL_V1) if d.split in ("val", "test")]


def fileable(doc_type: DocType, variant: str = "clean") -> Fileable:
    """The first committed eval-v1 val or test document of the type and variant that the app
    should file without asking."""
    doc = next(
        d
        for d in _eval_docs()
        if d.doc_type == doc_type and d.variant == variant and not d.expected_ask
    )
    if doc.variant == "locked":
        doc = doc.model_copy(update={"password": locked_password(doc.base_id)})
    data = (EVAL_V1 / doc.files[0]).read_bytes()
    return Fileable(doc, data, hashlib.sha256(data).hexdigest())


def everything_written(world: World) -> bytes:
    """The bytes of every file in the vault and in the database folder (WAL files included)."""
    out: list[bytes] = []
    for root in (world.vault.root, world.db_dir):
        out.extend(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())
    return b"\n".join(out)
