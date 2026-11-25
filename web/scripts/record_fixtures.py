"""Records the API replies the web app's tests and accessibility check use, from the synthetic
dev vault only: eval-v1 val documents are dropped in a temporary Inbox, the worker reads them with
the stand-in reader, and the app is asked through a test client. Nothing real is read and no
model is called. Run from the repo root:

    uv run python web/scripts/record_fixtures.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from vault_synth.household import HOUSEHOLD

from household_vault.api.app import create_app
from household_vault.app_state import build_app_state
from household_vault.config import Settings

ROOT = Path(__file__).resolve().parents[2]
EVAL_V1 = ROOT / "evals" / "datasets" / "eval-v1"
OUT = ROOT / "web" / "fixtures"
LIMIT = 6


def main() -> None:
    manifest = json.loads((EVAL_V1 / "manifest.json").read_text())
    names = [n for d in manifest["documents"] if d["split"] == "val" for n in d["files"]][:LIMIT]
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
        state = build_app_state(settings)
        try:
            for name in names:
                state.vault.write_atomic(f"Inbox/{name}", (EVAL_V1 / name).read_bytes())
            state.worker.start_up()
            state.worker.drain()
            client = TestClient(
                create_app(state, start_worker=False, web_dist=folder / "none"),
                base_url="http://localhost",
            )
            replies = {
                "needs-a-look.json": client.get("/v1/needs-a-look").json(),
                "healthz.json": client.get("/healthz").json(),
            }
        finally:
            state.store.conn.close()
    OUT.mkdir(exist_ok=True)
    for file, body in replies.items():
        (OUT / file).write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
        print(f"wrote web/fixtures/{file}")


if __name__ == "__main__":
    main()
