"""The `vault` command.

vault                          print the version
vault run [--app]              the API and the worker on the configured address
vault process                  run the worker once over what is in Inbox and print counts
vault emergency-sheet --out P  write the printable emergency sheet
vault index --rebuild          index every filed document again for search
vault dev-vault --from DIR     fill the synthetic Inbox from a dataset (development only)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import get_args

from household_vault import __version__
from household_vault.config import ConfigError, Settings, load_settings
from household_vault.db import ItemState
from household_vault.emergency import sheet_html
from household_vault.people import Household
from household_vault.safety import UnsafePathError, assert_safe_path, is_within
from household_vault.vaultroot import INBOX, VaultRoot

_SAFE_NAME = re.compile(r"[\w.\- ]+")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vault", description="Private document vault.")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="serve the app and run the worker")
    run.add_argument("--app", action="store_true", help="use the real vault from the app config")

    sub.add_parser("process", help="run the worker once over what is in Inbox")

    sheet = sub.add_parser("emergency-sheet", help="write the printable emergency sheet")
    sheet.add_argument("--out", required=True, type=Path)
    sheet.add_argument("--app", action="store_true", help="use the real vault from the app config")

    index = sub.add_parser("index", help="manage the search index")
    index.add_argument("--rebuild", action="store_true", required=True, help="index it all again")
    index.add_argument("--app", action="store_true", help="use the real vault from the app config")

    dev = sub.add_parser("dev-vault", help="fill the synthetic Inbox from a dataset")
    dev.add_argument("--from", dest="source", required=True, type=Path)
    dev.add_argument("--split", default="val", choices=["train", "val", "test"])
    dev.add_argument("--limit", type=int, default=12)
    dev.add_argument("--app", action="store_true", help=argparse.SUPPRESS)
    return parser


def _fail(message: str) -> SystemExit:
    print(f"error: {message}", file=sys.stderr)
    return SystemExit(2)


def _settings(app: bool = False) -> Settings:
    try:
        return load_settings(app=app)
    except (ConfigError, UnsafePathError) as exc:
        raise _fail(str(exc)) from None


def console() -> None:
    """The `vault` entry point: the arguments come from the shell."""
    main(sys.argv[1:])


def main(argv: list[str] | None = None) -> None:
    """Run a command. With no argv (None) it acts as if no command was given and prints the
    version, so calling `main()` never reads the arguments of the process that imports it."""
    args = _parser().parse_args(argv or [])
    if args.command is None:
        print(f"household-docs-vault {__version__}")
    elif args.command == "run":
        _run(args.app)
    elif args.command == "process":
        _process()
    elif args.command == "emergency-sheet":
        _emergency_sheet(args.out, args.app)
    elif args.command == "index":
        _index(args.app)
    elif args.command == "dev-vault":
        _dev_vault(args.source, args.split, args.limit, args.app)


def _run(app: bool) -> None:
    import uvicorn

    from household_vault.api.app import create_app
    from household_vault.app_state import build_app_state
    from household_vault.logging_setup import add_console

    settings = _settings(app)
    state = build_app_state(settings)
    api = create_app(state)
    add_console()
    # The access log is off: it would carry the id of every document the owner opens.
    uvicorn.run(api, host=settings.host, port=settings.port, access_log=False, log_config=None)


def _process() -> None:
    from household_vault.app_state import build_app_state

    # Run by hand over files that are already there, so nothing waits for a file to settle.
    state = build_app_state(_settings().model_copy(update={"settle_seconds": 0.0}))
    try:
        state.worker.start_up()
        state.worker.drain()
        counts = Counter(i.state for i in state.store.items(_ALL_STATES))
    finally:
        state.store.conn.close()
    if not counts:
        print("Nothing in Inbox.")
    for name, n in sorted(counts.items()):
        print(f"{name}: {n}")


_ALL_STATES = get_args(ItemState)


def _index(app: bool) -> None:
    from household_vault.db import Store, connect, migrate
    from household_vault.search.index import KeywordIndex

    settings = _settings(app)
    conn = connect(settings.db_path, settings.vault_root)
    try:
        migrate(conn)
        count = KeywordIndex(Store(conn)).rebuild()
    finally:
        conn.close()
    print(f"Indexed {count} documents.")


def _emergency_sheet(out: Path, app: bool) -> None:
    settings = _settings(app)
    try:
        target = assert_safe_path(out.expanduser().absolute())
    except UnsafePathError as exc:
        raise _fail(str(exc)) from None
    if is_within(target, settings.vault_root):
        raise _fail("write the sheet outside the vault folder, so Drive does not keep a copy")
    target.write_text(sheet_html(settings.vault_root, date.today()), encoding="utf-8")
    print(f"Wrote {target}")


def _dev_vault(source: Path, split: str, limit: int, app: bool) -> None:
    if app:
        raise _fail("dev-vault works only on the synthetic vault, never on the real one")
    settings = _settings()
    if settings.mode != "dev":
        raise _fail("dev-vault works only on the synthetic vault, never on the real one")
    try:
        folder = assert_safe_path(source.expanduser().absolute())
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        household = Household.model_validate_json((folder / "household.json").read_text())
    except (UnsafePathError, OSError, ValueError) as exc:
        raise _fail(f"cannot read the dataset in {source}: {type(exc).__name__}") from None
    names = [
        name for doc in manifest["documents"] if doc["split"] == split for name in doc["files"]
    ][: max(limit, 0)]
    for name in names:
        if not _SAFE_NAME.fullmatch(name) or name in (".", "..") or ".." in name:
            raise _fail("the dataset lists a file name that is not a plain name")
    vault = VaultRoot.from_settings(settings)
    vault.mkdirs(INBOX)
    copied = 0
    for name in names:
        rel = f"{INBOX}/{name}"
        if vault.exists(rel):
            continue
        vault.write_atomic(rel, (folder / name).read_bytes())
        copied += 1
    settings.household_path.parent.mkdir(parents=True, exist_ok=True)
    assert_safe_path(settings.household_path).write_text(
        household.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    print(f"Copied {copied} of {len(names)} {split} files into {INBOX}.")
