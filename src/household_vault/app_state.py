"""Everything the app needs at run time, built once and shared by the API, the worker and the
command line. One clock drives the store, the activity log, the worker and the secrets gate, so
a test can move time for all of them at once.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from household_vault.actions import Actions
from household_vault.activity import Activity
from household_vault.config import Settings
from household_vault.db import Store, connect, migrate
from household_vault.filing.filer import Filer
from household_vault.leakscan import install_log_redaction
from household_vault.people import Household, load_household
from household_vault.reading.engines import Engines, make_engines
from household_vault.reading.ollama import OllamaClient
from household_vault.reveal import MacRevealer, Revealer
from household_vault.search.index import KeywordIndex
from household_vault.search.query import OllamaPromptReader, PromptReader
from household_vault.search.retrieve import Searcher
from household_vault.search.vectors import Embedder, VectorIndex, embedder_for
from household_vault.secrets.cards import CardIntake
from household_vault.secrets.gate import SecretsGate
from household_vault.vaultroot import (
    BACKUP,
    INBOX,
    LOGS,
    NEEDS_A_LOOK,
    RECORDS,
    VaultGone,
    VaultRoot,
)
from household_vault.worker import Worker

log = logging.getLogger(__name__)

_FOLDERS = (INBOX, NEEDS_A_LOOK, RECORDS, LOGS, BACKUP)


def _now() -> datetime:
    return datetime.now().astimezone()


@dataclass
class AppState:
    settings: Settings
    vault: VaultRoot
    store: Store
    activity: Activity
    household: Household
    engines: Engines
    filer: Filer
    gate: SecretsGate
    cards: CardIntake
    worker: Worker
    actions: Actions
    vectors: VectorIndex
    searcher: Searcher
    prompt_reader: PromptReader | None  # None: no model reads prompts (the reading is off)
    revealer: Revealer


def build_app_state(
    settings: Settings,
    *,
    engines: Engines | None = None,
    embedder: Embedder | None = None,
    prompt_reader: PromptReader | None = None,
    revealer: Revealer | None = None,
    clock: Callable[[], datetime] | None = None,
) -> AppState:
    """Make the folders, open and migrate the database, load the household file and wire the
    parts. There is one secrets gate, shared by the actions and the card intake. Passing
    `engines` means no real models run, so the embedder and the prompt reader are then only the
    ones passed."""
    install_log_redaction()  # before anything can log
    now = clock or _now
    vault = VaultRoot.from_settings(settings)
    try:
        for rel in _FOLDERS:
            vault.mkdirs(rel)
    except VaultGone:
        # The vault folder is away (Drive not mounted). The worker waits for it to come back.
        log.warning("the vault folder is not there yet")
    conn = connect(settings.db_path, vault.root)
    migrate(conn)
    store = Store(conn, now)
    if settings.household_path.exists():
        store.set_household(load_household(settings.household_path))
    household = store.household()
    chosen = engines or make_engines(settings)
    if embedder is None and engines is None:
        embedder = embedder_for(settings)
    if prompt_reader is None and engines is None and settings.reader == "mac":
        prompt_reader = OllamaPromptReader(
            OllamaClient(settings.ollama_url, timeout_s=60.0), settings.query_model
        )
    vectors = VectorIndex(store, embedder)
    searcher = Searcher(store, KeywordIndex(store), vectors)
    activity = Activity(store, vault, now)
    filer = Filer(vault, store, activity, household, now)
    gate = SecretsGate(vault, lambda: now().timestamp())
    cards = CardIntake(gate, vault, filer, activity, store, chosen, household)
    worker = Worker(settings, vault, store, activity, chosen, filer, cards, now, vectors)
    actions = Actions(worker, filer, store, activity, household, gate)
    activity.backfill_csv()  # rows a failed CSV write left behind reach the vault log
    return AppState(
        settings,
        vault,
        store,
        activity,
        household,
        chosen,
        filer,
        gate,
        cards,
        worker,
        actions,
        vectors,
        searcher,
        prompt_reader,
        revealer or MacRevealer(),
    )
