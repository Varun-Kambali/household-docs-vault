"""Records the API replies the web app's tests and accessibility check use, from the synthetic
dev vault only: eval-v1 val documents are dropped in a temporary Inbox, the worker files them
with the synthetic truth as the reader, and the app is asked through a test client. Nothing real
is read and no model is called: the prompt reader is a table of fixed readings. Run from the
repo root:

    uv run python web/scripts/record_fixtures.py          # everything
    uv run python web/scripts/record_fixtures.py --inbox  # only the Inbox replies

The replies carry the real shape of the API. Document ids are random, so they are replaced by
`doc-photo` and `doc-pdf` in every file the app's tests and the fixture API read.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image
from vault_synth.household import HOUSEHOLD

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from household_vault.api.app import create_app  # noqa: E402
from household_vault.app_state import build_app_state  # noqa: E402
from household_vault.config import Settings  # noqa: E402
from household_vault.reading.engines import Engines  # noqa: E402
from household_vault.reading.ollama import ModelUnavailable  # noqa: E402
from tests.conftest import MASTER_PASSWORD  # noqa: E402
from tests.fakes import TruthModels, TruthPages  # noqa: E402

EVAL_V1 = ROOT / "evals" / "datasets" / "eval-v1"
OUT = ROOT / "web" / "fixtures"
LIMIT = 6
# The documents the search and the viewer fixtures are made of: a PDF and a photograph.
PDF = "health_policy-1-clean.pdf"
PHOTO = "health_policy-6-photo.jpg"
AADHAAR = "aadhaar-1-clean.pdf"
PNG_BYTES = 300_000


class _Reader:
    """A table of fixed readings, standing in for the model that reads a prompt."""

    name = "recorded-fixtures"

    def __init__(self) -> None:
        self.off = False

    def read(self, prompt: str) -> str:
        if self.off:
            raise ModelUnavailable("off")
        text = prompt.lower()
        if "expire" in text or "diwali" in text:
            # A list: health policies by their expiry. "Diwali" is a date the code cannot read.
            phrase = "before Diwali" if "diwali" in text else "next 12 months"
            return json.dumps(
                {
                    "intent": "list",
                    "people": [],
                    "types": ["health_policy"],
                    "areas": [],
                    "field": None,
                    "date": {"role": "expiry", "phrase": phrase},
                    "place": None,
                    "words": "",
                }
            )
        known = "anil" not in prompt.lower()
        return json.dumps(
            {
                "intent": "lookup",
                "people": [],
                "types": ["health_policy"] if known else [],
                "areas": [],
                "field": "policy_number" if known else "expiry_date",
                "date": None,
                "place": None,
                "words": "" if known else prompt,
            }
        )


def _area(area: str) -> dict[str, Any]:
    """The query an area page sends: its area and nothing else."""
    return {
        "intent": "list",
        "people": [],
        "types": [],
        "areas": [area],
        "field": None,
        "role": None,
        "range": None,
        "place": None,
        "words": "",
        "unread": [],
    }


def _small_png(data: bytes) -> bytes:
    """The page image, quantised to a palette if it is over the size a fixture should have."""
    if len(data) <= PNG_BYTES:
        return data
    import io

    image = Image.open(io.BytesIO(data)).convert("L")
    for colours in (64, 32, 16):
        buffer = io.BytesIO()
        image.quantize(colours).save(buffer, format="PNG", optimize=True)
        if buffer.tell() <= PNG_BYTES:
            return buffer.getvalue()
    return buffer.getvalue()


INBOX_POLICY = "health_policy-1-clean.pdf"
# Three copies of one prescription. The model stand-in reads the patient as someone outside the
# household, so each one waits on "Whose is it?" and the three ask the very same question.
INBOX_WAITING = ["prescription-1-clean.pdf", "prescription-1-photo.jpg", "prescription-1-scan.pdf"]


def inbox() -> None:
    """The Inbox replies: files waiting on the same question, the activity log, the batch, the
    secrets status and a page image of a waiting file. The master password used to make the
    secrets file is the tests' made-up one and is never written to a fixture."""
    with tempfile.TemporaryDirectory(prefix="vault-fixtures-") as tmp:
        folder = Path(tmp)
        household = folder / "household.json"
        household.write_text(HOUSEHOLD.model_dump_json())
        settings = Settings(
            mode="dev",
            vault_root=folder / "vault",
            db_path=folder / "vault.db",
            household_path=household,
            log_dir=folder / "logs",
            reader="stand-in",
            settle_seconds=0.0,
        )
        models = TruthModels()
        state = build_app_state(
            settings, engines=Engines(TruthPages(), models), prompt_reader=_Reader()
        )
        try:
            client = TestClient(
                create_app(state, start_worker=False, web_dist=folder / "none"),
                base_url="http://localhost",
            )
            state.vault.write_atomic(f"Inbox/{INBOX_POLICY}", (EVAL_V1 / INBOX_POLICY).read_bytes())
            state.worker.start_up()
            state.worker.drain()
            models.patch = {"patient": "Anita Sharma"}
            for name in INBOX_WAITING:
                state.vault.write_atomic(f"Inbox/{name}", (EVAL_V1 / name).read_bytes())
            state.worker.drain()
            waiting = client.get("/v1/needs-a-look").json()
            assert len(waiting) == len(INBOX_WAITING), [w["question"]["text"] for w in waiting]
            assert len({w["question"]["text"] for w in waiting}) == 1
            page = client.get(f"/v1/items/{waiting[0]['id']}/pages/0.png?width=900")
            assert page.status_code == 200
            status_none = client.get("/v1/secrets/status").json()
            assert client.post(
                "/v1/secrets/create", json={"master_password": MASTER_PASSWORD}
            ).is_success
            status_open = client.get("/v1/secrets/status").json()
            state.gate.lock()
            status_locked = client.get("/v1/secrets/status").json()
            replies: dict[str, Any] = {
                "needs-a-look-group.json": waiting,
                "needs-a-look-one.json": waiting[:1],
                "activity.json": client.get("/v1/activity?limit=20").json(),
                "progress.json": client.get("/v1/inbox/progress").json(),
                "secrets-status-none.json": status_none,
                "secrets-status-open.json": status_open,
                "secrets-status-locked.json": status_locked,
            }
            png = _small_png(page.content)
        finally:
            state.gate.lock()
            state.store.conn.close()
    OUT.mkdir(exist_ok=True)
    for file, body in replies.items():
        (OUT / file).write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
        print(f"wrote web/fixtures/{file}")
    (OUT / "item-page-0.png").write_bytes(png)
    print(f"wrote web/fixtures/item-page-0.png ({len(png)} bytes)")


def main() -> None:
    if "--inbox" in sys.argv:
        return inbox()
    manifest = json.loads((EVAL_V1 / "manifest.json").read_text())
    names = [n for d in manifest["documents"] if d["split"] == "val" for n in d["files"]][:LIMIT]
    # The other copies of the photographed policy would be filed as duplicates of it.
    others = [n for n in names if not n.startswith("health_policy-6-")]
    names = list(dict.fromkeys([PDF, PHOTO, AADHAAR, *others]))
    reader = _Reader()
    with tempfile.TemporaryDirectory(prefix="vault-fixtures-") as tmp:
        folder = Path(tmp)
        household = folder / "household.json"
        household.write_text(HOUSEHOLD.model_dump_json())
        settings = Settings(
            mode="dev",
            vault_root=folder / "vault",
            db_path=folder / "vault.db",
            household_path=household,
            log_dir=folder / "logs",
            reader="stand-in",
            settle_seconds=0.0,
        )
        state = build_app_state(
            settings, engines=Engines(TruthPages(), TruthModels()), prompt_reader=reader
        )
        try:
            for name in names:
                state.vault.write_atomic(f"Inbox/{name}", (EVAL_V1 / name).read_bytes())
            state.worker.start_up()
            state.worker.drain()
            client = TestClient(
                create_app(state, start_worker=False, web_dist=folder / "none"),
                base_url="http://localhost",
            )

            def post(prompt: str, full: bool) -> dict[str, Any]:
                return client.post("/v1/search", json={"prompt": prompt, "full": full}).json()

            listed = post("health policies that expire", True)
            unread = post("health policies that expire before Diwali", True)
            by_person = client.post(
                "/v1/search/list",
                json={
                    "query": listed["query"],
                    "change": {"slot": "who", "value": "p4"},
                },
            ).json()
            area = client.post("/v1/search/list", json={"query": _area("insurance")}).json()
            area_empty = client.post("/v1/search/list", json={"query": _area("rent")}).json()
            quick = post("policy", False)
            answer = post("policy number", True)
            declined = post("anil's policy", True)
            reader.off = True
            off = post("policy", True)
            reader.off = False
            by_name = {
                Path(r["rel_path"]).suffix: r["document_id"]
                for r in quick["rows"]
                if r["doc_type"] == "health_policy"
            }
            ids = {".jpg": "doc-photo", ".pdf": "doc-pdf"}
            real = {ids[ext]: doc_id for ext, doc_id in by_name.items() if ext in ids}
            assert set(real) == {"doc-photo", "doc-pdf"}, [r["rel_path"] for r in quick["rows"]]
            replies: dict[str, Any] = {
                "needs-a-look.json": client.get("/v1/needs-a-look").json(),
                "healthz.json": client.get("/healthz").json(),
                "people.json": client.get("/v1/people").json(),
                "search-quick.json": quick,
                "search-answer.json": answer,
                "search-no-answer.json": declined,
                "search-model-off.json": off,
                "search-list.json": listed,
                "search-list-unread.json": unread,
                "list-changed.json": by_person,
                "list-area.json": area,
                "list-area-empty.json": area_empty,
            }
            pngs: dict[str, bytes] = {}
            for alias, doc_id in real.items():
                replies[f"{alias}.json"] = client.get(f"/v1/documents/{doc_id}").json()
                pages = replies[f"{alias}.json"]["page_count"]
                for page in range(pages):
                    replies[f"{alias}-lines-{page}.json"] = client.get(
                        f"/v1/documents/{doc_id}/pages/{page}/lines"
                    ).json()
                    reply = client.get(f"/v1/documents/{doc_id}/pages/{page}.png?width=900")
                    assert reply.status_code == 200
                    pngs[f"{alias}-page-{page}.png"] = _small_png(reply.content)
        finally:
            state.store.conn.close()
    OUT.mkdir(exist_ok=True)
    for file, body in replies.items():
        text = json.dumps(body, indent=2, sort_keys=True) + "\n"
        for alias, doc_id in real.items():
            text = text.replace(doc_id, alias)
        (OUT / file).write_text(text)
        print(f"wrote web/fixtures/{file}")
    for file, data in pngs.items():
        (OUT / file).write_bytes(data)
        print(f"wrote web/fixtures/{file} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
