"""The eval commands.

    python -m evals.runner reading --split S --engines mac|recorded --record DIR
                                   [--resume] [--limit N]
    python -m evals.runner filing --split S --recordings DIR
    python -m evals.runner smoke [--recordings DIR] [--search-recordings DIR]
    python -m evals.runner search --split S --recordings DIR (--record DIR | --replay DIR)
                                  [--smoke] [--results DIR]

`reading` and `filing` write `evals/results/<date>_<kind>_<split>_<commit>.json` and, for the
`test` split, rewrite `evals/results/summary.md`. `smoke` replays the committed recordings of the
smoke documents with no model, writes nothing and returns 1 when a number is below its
threshold in `evals/thresholds.toml`; it includes the search eval on the same documents.
`search` scores the `search-v1` questions of a split: with `--record` it calls the local models
and records their answers, with `--replay` it needs no model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evals.filing_eval import run_filing
from evals.reading_eval import (
    DocResult,
    dataset_info,
    run_reading,
    summarise_reading,
    write_results,
)
from evals.recordings import load_smoke
from evals.search_eval import (
    SMOKE_DIR,
    RecordedEmbedder,
    RecordedPromptReader,
    SearchEvalError,
    _manifest,
    load_smoke_questions,
    row_dicts,
    run_search,
    smoke_documents,
    summarise_search,
    write_smoke_questions,
)
from evals.search_set import EVAL_TODAY, SEARCH_DIR
from household_vault.config import load_settings
from household_vault.reading.engines import Engines, make_engines
from household_vault.reading.ollama import ModelError, ModelUnavailable, OllamaClient
from household_vault.reading.prompt import PROMPT_V4
from household_vault.reading.recorded import recorded_engines
from household_vault.search.query import PROMPT_READ_V1, PROMPT_READ_V2, OllamaPromptReader
from household_vault.search.vectors import OllamaEmbedder

ROOT = Path(__file__).resolve().parents[1]
SET_DIR = ROOT / "evals" / "datasets" / "eval-v1"
RESULTS = ROOT / "evals" / "results"
SMOKE_RECORDINGS = ROOT / "evals" / "recordings" / "eval-v1" / "smoke"
THRESHOLDS = ROOT / "evals" / "thresholds.toml"
HEADLINE = "Fields exactly right on photos"


def load_thresholds(path: Path = THRESHOLDS) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


# -- run facts ------------------------------------------------------------------------------------


def _recorded_engines_in(folder: Path) -> list[str]:
    """The engine names the recordings in a folder carry."""
    names: set[str] = set()
    for path in folder.glob("*.json"):
        names.add(str(json.loads(path.read_text(encoding="utf-8")).get("engine", "")))
    return sorted(names)


def _model_facts(engines_kind: str, folder: Path | None) -> dict[str, Any]:
    """Which models answered: the tags and digests for a live run, the recorded engine names for
    a replay."""
    if engines_kind == "mac":
        settings = load_settings()
        wanted = (settings.vision_model, settings.fallback_model)
        try:
            tags = OllamaClient(settings.ollama_url).tags()
        except (ModelUnavailable, ModelError):
            tags = {}
        return {"tags": {t: tags.get(t) for t in wanted}}
    return {"recorded_engines": _recorded_engines_in(folder) if folder else []}


def _run_facts(models: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dataset": dataset_info(SET_DIR),
        "models": dict(models),
        "prompt_version": PROMPT_V4.version,
        "thresholds": load_thresholds(),
    }


# -- commands -------------------------------------------------------------------------------------


def _reading(args: argparse.Namespace) -> int:
    record = Path(args.record) if args.record else None
    if args.engines == "mac":
        settings = load_settings().model_copy(update={"reader": "mac"})
        engines: Engines = make_engines(settings)
        record_to = record
    else:
        if record is None:
            print("error: --engines recorded needs --record DIR (the recordings to replay)")
            return 2
        engines = recorded_engines(record)
        record_to = None
    rows = run_reading(
        SET_DIR,
        args.split,
        engines,
        record_to=record_to,
        resume=args.resume,
        limit=args.limit,
    )
    summary = summarise_reading(rows)
    path = write_results(
        Path(args.results),
        "reading",
        args.split,
        summary,
        [r.model_dump() for r in rows],
        extra=_run_facts(_model_facts(args.engines, record)),
    )
    print(f"{HEADLINE}: {summary['field_exact']['photo']:.1%}")
    print(f"Wrote {path}")
    if args.split == "test":
        write_summary(Path(args.results))
    return 0


def _filing(args: argparse.Namespace) -> int:
    recordings = Path(args.recordings)
    with tempfile.TemporaryDirectory(prefix="vault-eval-") as work:
        report = run_filing(SET_DIR, args.split, recordings, Path(work))
    rows = [{"variant": v, **counts} for v, counts in report["by_variant"].items()]
    summary = {k: v for k, v in report.items() if k not in ("by_variant", "secret_hits")}
    path = write_results(
        Path(args.results),
        "filing",
        args.split,
        summary,
        rows,
        extra=_run_facts(_model_facts("recorded", recordings)),
    )
    print(f"Placement matches the decision: {summary['placement_matches_decision']:.1%}")
    print(f"Wrote {path}")
    if args.split == "test":
        write_summary(Path(args.results))
    return 0


def smoke_metrics(reading: Mapping[str, Any], filing: Mapping[str, Any]) -> dict[str, float]:
    """The numbers the smoke thresholds are written against."""
    return {
        "type_accuracy": reading["type_accuracy"],
        "person_accuracy": reading["person_accuracy"],
        "linked_accuracy": reading["linked_accuracy"],
        "field_exact_photo": reading["field_exact"].get("photo", 1.0),
        "field_exact_all": reading["field_exact"]["all"],
        "line_recall_photo": reading["line_recall_photo"] or 0.0,
        "silent_misfiles_per_100": reading["silent_misfiles_per_100"],
        "needs_a_look_expected_clean": reading["needs_a_look_share"]["expected_clean"],
        "placement_matches_decision": filing["placement_matches_decision"],
        "documents_placed": filing["documents_placed"],
        "exact_copies": filing["exact_copies"],
        "undo_tried": filing["undo_tried"],
        "exact_copies_caught": filing["exact_copies_caught"],
        "undo_same_path": filing["undo_same_path"],
        "wrong_merges": filing["wrong_merges"],
        "secrets_found": filing["secrets_found"],
        "cvv_stored": filing["cvv_stored"],
        "inbox_left": filing["inbox_left"],
        "filing_needs_a_look_expected_clean": filing["needs_a_look_share"]["expected_clean"],
    }


def check_smoke(metrics: Mapping[str, float], thresholds: Mapping[str, Any]) -> list[str]:
    """One line for every metric that misses its threshold, naming it and both numbers."""
    misses: list[str] = []
    for name, floor in thresholds["smoke"]["min"].items():
        if metrics[name] < floor:
            misses.append(f"{name}: {metrics[name]:.4g} is below the minimum {floor:.4g}")
    for name, ceiling in thresholds["smoke"]["max"].items():
        if metrics[name] > ceiling:
            misses.append(f"{name}: {metrics[name]:.4g} is above the maximum {ceiling:.4g}")
    return misses


def search_metrics(summary: Mapping[str, Any]) -> dict[str, float]:
    """The numbers the `[search_smoke]` thresholds are written against."""

    def overall(name: str) -> float:
        value = summary[name]["all"]
        return 0.0 if value is None else float(value)

    kinds = summary["kinds"]
    return {
        "top1": overall("top1"),
        "top3": overall("top3"),
        "answer_correct": overall("answer_correct"),
        "citation_accuracy": overall("citation_accuracy"),
        "list_reading": overall("list_reading"),
        "list_precision": overall("list_precision"),
        "list_recall": overall("list_recall"),
        "declined_when_answerable": overall("declined_when_answerable"),
        "declined_when_none": overall("declined_when_none"),
        "lookups": kinds.get("lookup", 0),
        "finds": kinds.get("find", 0),
        "lists": kinds.get("list", 0),
        "nones": kinds.get("none", 0),
        "readings_missing": summary["readings_missing"],
        "vectors_missing": summary["vectors_missing"],
        "expected_filed_but_not": summary["expected_filed_but_not"],
        "secrets_found": summary["secrets_found"],
    }


def check_search_smoke(metrics: Mapping[str, float], thresholds: Mapping[str, Any]) -> list[str]:
    """One line for every search metric that misses its threshold."""
    section = thresholds["search_smoke"]
    misses: list[str] = []
    for name, floor in section["min"].items():
        if metrics[name] < floor:
            misses.append(f"search {name}: {metrics[name]:.4g} is below the minimum {floor:.4g}")
    for name, ceiling in section["max"].items():
        if metrics[name] > ceiling:
            misses.append(f"search {name}: {metrics[name]:.4g} is above the maximum {ceiling:.4g}")
    return misses


def _smoke_search(
    reading_recordings: Path, search_recordings: Path
) -> tuple[dict[str, float], list[str]]:
    docs = smoke_documents()
    settings = load_settings()
    facts: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="vault-search-smoke-") as work:
        rows = run_search(
            "val",
            RecordedPromptReader(search_recordings, expect=settings.query_model),
            RecordedEmbedder(search_recordings, expect=settings.embed_model),
            reading_recordings,
            Path(work),
            docs=docs,
            questions=load_smoke_questions(search_recordings),
            facts=facts,
        )
    metrics = search_metrics(summarise_search(rows, facts))
    return metrics, [f"search: {h}" for h in facts["secret_hits"]]


def _smoke(args: argparse.Namespace) -> int:
    recordings = Path(args.recordings)
    ids = load_smoke(SET_DIR)
    try:
        rows: list[DocResult] = run_reading(
            SET_DIR,
            "val",
            recorded_engines(recordings),
            record_to=None,
            resume=False,
            limit=None,
            only=ids,
        )
        with tempfile.TemporaryDirectory(prefix="vault-smoke-") as work:
            filing = run_filing(SET_DIR, "val", recordings, Path(work), only=ids)
    except ModelUnavailable as exc:
        print(f"smoke: {exc} (a smoke document has no recording in {recordings})")
        return 1
    metrics = smoke_metrics(summarise_reading(rows), filing)
    thresholds = load_thresholds()
    misses = check_smoke(metrics, thresholds)
    leaks = list(filing["secret_hits"])
    try:
        found, search_leaks = _smoke_search(recordings, Path(args.search_recordings))
    except (SearchEvalError, ModelUnavailable) as exc:
        misses.append(f"search: {exc}")
    else:
        misses += check_search_smoke(found, thresholds)
        leaks += search_leaks
        metrics = {**metrics, **{f"search_{k}": v for k, v in found.items()}}
    for name, value in metrics.items():
        print(f"{name}: {value:.4g}")
    if misses:
        print("\nsmoke run failed:")
        for line in (*misses, *leaks):
            print(f"  {line}")
        return 1
    print(f"\nsmoke run passed on {len(ids)} documents")
    return 0


def results_folder(split: str, given: str | None = None) -> Path:
    """Where a search run writes: val numbers stay out of git, so val never defaults to the
    committed results folder."""
    if given:
        return Path(given)
    return ROOT / "var" / "results-val" if split == "val" else RESULTS


READING_PROMPTS = {"v1": PROMPT_READ_V1, "v2": PROMPT_READ_V2}


def _query_model(args: argparse.Namespace, configured: str) -> str:
    """The model that reads prompts: the `--query-model` switch, else the config's. The app's
    default does not change."""
    return str(args.query_model or configured)


def _search(args: argparse.Namespace) -> int:
    recordings = Path(args.recordings)
    system = READING_PROMPTS[args.prompt]
    settings = load_settings()
    settings = settings.model_copy(update={"query_model": _query_model(args, settings.query_model)})
    if args.smoke:
        docs = smoke_documents()
        questions = (
            write_smoke_questions(Path(args.record))
            if args.record and not (Path(args.record) / "questions.jsonl").exists()
            else load_smoke_questions(Path(args.record or args.replay))
        )
    else:
        docs, questions = None, None
    models: dict[str, Any]
    if args.record:
        record = Path(args.record)
        client = OllamaClient(settings.ollama_url, timeout_s=120.0)
        try:
            tags = client.tags()
        except (ModelUnavailable, ModelError):
            tags = {}
        reader = RecordedPromptReader(
            record,
            record,
            live=OllamaPromptReader(client, settings.query_model, system),
            model=settings.query_model,
            digest=tags.get(settings.query_model),
            system=system,
        )
        embedder = RecordedEmbedder(
            record,
            record,
            live=OllamaEmbedder(client, settings.embed_model),
            model=settings.embed_model,
            digest=tags.get(settings.embed_model),
        )
        models = {
            "prompt_reader": settings.query_model,
            "embedder": settings.embed_model,
            "digests": {m: tags.get(m) for m in (settings.query_model, settings.embed_model)},
            "live": True,
        }
    else:
        replay = Path(args.replay)
        try:
            tags = OllamaClient(settings.ollama_url, timeout_s=5.0).tags()
        except (ModelUnavailable, ModelError):
            tags = {}  # no Ollama to ask: the manifest alone is checked
        try:
            reader = RecordedPromptReader(
                replay,
                expect=settings.query_model,
                expect_digest=tags.get(settings.query_model),
                system=system,
            )
            if args.fill_vectors:
                # only the embedding model runs, and only for vectors the folder lacks; the
                # folder's manifest must name this very build of it
                embed_digest = tags.get(settings.embed_model)
                if embed_digest is None:
                    print("search: --fill-vectors needs Ollama and the embedding model's digest")
                    return 1
                embedder = RecordedEmbedder(
                    replay,
                    replay,
                    live=OllamaEmbedder(
                        OllamaClient(settings.ollama_url, timeout_s=120.0), settings.embed_model
                    ),
                    model=settings.embed_model,
                    digest=embed_digest,
                    require_digest=True,
                )
            else:
                embedder = RecordedEmbedder(
                    replay,
                    expect=settings.embed_model,
                    expect_digest=tags.get(settings.embed_model),
                )
        except SearchEvalError as exc:
            print(f"search: {exc}")
            return 1
        stamped = {role: _manifest(replay).get(role) for role in ("prompt_reader", "embedder")}
        models = {
            "prompt_reader": settings.query_model,
            "embedder": embedder.name,
            "digests": {
                body["model"]: body.get("digest")
                for body in stamped.values()
                if isinstance(body, dict) and "model" in body
            },
            "live": False,
        }
    facts: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="vault-search-") as work:
        rows = run_search(
            args.split,
            reader,
            embedder,
            recordings,
            Path(work),
            docs=docs,
            questions=questions,
            facts=facts,
        )
    summary = summarise_search(rows, facts)
    questions_file = SEARCH_DIR / f"{args.split}.jsonl"
    path = write_results(
        results_folder(args.split, args.results),
        "search_smoke" if args.smoke else "search",
        args.split,
        summary,
        row_dicts(rows),
        extra={
            "dataset": {
                "name": "search-v1",
                "questions_sha256": hashlib.sha256(questions_file.read_bytes()).hexdigest(),
                "eval_v1": dataset_info(SET_DIR),
            },
            "models": models,
            "reading_prompt_sha256": hashlib.sha256(system.encode()).hexdigest(),
            "today": EVAL_TODAY.isoformat(),
        },
    )
    for name in ("top1", "top3", "answer_correct", "citation_accuracy", "list_reading"):
        print(f"{name}: {summary[name]['all']}")
    print(f"secrets_found: {summary['secrets_found']}")
    print(f"Wrote {path}")
    return 0


# -- summary.md -----------------------------------------------------------------------------------


def _newest(folder: Path, kind: str) -> dict[str, Any] | None:
    # by run date (the name starts with it), then by when the file was written: two runs on one
    # day must not be ordered by their commit hashes
    found = sorted(
        folder.glob(f"*_{kind}_test_*.json"),
        key=lambda p: (p.name[:10], p.stat().st_mtime, p.name),
    )
    return json.loads(found[-1].read_text(encoding="utf-8")) if found else None


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def write_summary(folder: Path) -> Path | None:
    """Rewrite `summary.md` from the newest `test` results in folder, headline first. Every number
    is copied from a results file; the file says which."""
    reading = _newest(folder, "reading")
    filing = _newest(folder, "filing")
    if reading is None and filing is None:
        return None
    lines = ["# Results on eval-v1, test split", ""]
    if reading is not None:
        s = reading["summary"]
        run = reading["run"]
        lines += [
            f"**{HEADLINE}: {_pct(s['field_exact'].get('photo'))}**",
            "",
            f"Run {run['date']} on {run['machine']}, commit {run['commit']}, "
            f"{s['documents']} documents. Models: {json.dumps(reading['models'], sort_keys=True)}.",
            "",
            *(
                [
                    "These numbers replay the committed recordings in "
                    "`evals/recordings/eval-v1/test/` through this commit, with no model calls. "
                    "The recordings hold long digit runs masked, so a field made of one (such as "
                    "an acknowledgement number) scores as wrong on replay even when the live read "
                    "was right. The seconds are the live run's.",
                    "",
                ]
                if "recorded_engines" in reading["models"]
                else []
            ),
            "| Measure | Result |",
            "|---|---|",
            f"| Type accuracy | {_pct(s['type_accuracy'])} |",
            f"| Person accuracy (documents with a named person) | {_pct(s['person_accuracy'])} |",
            f"| Fields exactly right, all documents | {_pct(s['field_exact']['all'])} |",
            f"| Fields exactly right, clean PDFs | {_pct(s['field_exact'].get('clean'))} |",
            f"| Fields exactly right, scans | {_pct(s['field_exact'].get('scan'))} |",
            f"| Fields exactly right, locked PDFs | {_pct(s['field_exact'].get('locked'))} |",
            f"| Line recall on photos | {_pct(s['line_recall_photo'])} |",
            f"| Silent misfiles per 100 documents | {s['silent_misfiles_per_100']:.2f} |",
            f"| Needs a look, documents that should file | "
            f"{_pct(s['needs_a_look_share']['expected_clean'])} |",
            f"| Needs a look, all documents | {_pct(s['needs_a_look_share']['all'])} |",
            f"| Seconds per photo, median and maximum | "
            f"{s['seconds_photo']['median']} and {s['seconds_photo']['max']} |",
            "",
        ]
    if filing is not None:
        f = filing["summary"]
        lines += [
            "## Filing (real worker, recorded readings)",
            "",
            "| Measure | Result |",
            "|---|---|",
            f"| Placement equals the decision | {_pct(f['placement_matches_decision'])} |",
            f"| Exact copies caught | {_pct(f['exact_copies_caught'])} |",
            f"| Wrong merges | {f['wrong_merges']} |",
            f"| Secrets found by the leak scan | {f['secrets_found']} |",
            f"| Waiting originals skipped by it | {f.get('waiting_originals_skipped', 0)} |",
            f"| Values stored for cvv | {f['cvv_stored']} |",
            f"| Undo then retry back to the same path | {_pct(f['undo_same_path'])} |",
            f"| Files left in Inbox, apart from held ones | {f['inbox_left']} |",
            "",
        ]
    lines += [
        "Definitions of every measure are in `evals/README.md`. The numbers above are copied from "
        "the newest test results files in this folder.",
        "",
    ]
    path = folder / "summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# -- command line ---------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals.runner")
    sub = parser.add_subparsers(dest="command", required=True)

    reading = sub.add_parser("reading", help="read and decide every document of a split")
    reading.add_argument("--split", required=True, choices=["train", "val", "test"])
    reading.add_argument("--engines", required=True, choices=["mac", "recorded"])
    reading.add_argument("--record", help="folder to record into (mac) or replay from (recorded)")
    reading.add_argument("--resume", action="store_true", help="replay what is already recorded")
    reading.add_argument("--limit", type=int)
    reading.add_argument("--results", default=str(RESULTS))
    reading.set_defaults(run=_reading)

    filing = sub.add_parser("filing", help="replay recorded readings through the real worker")
    filing.add_argument("--split", required=True, choices=["train", "val", "test"])
    filing.add_argument("--recordings", required=True)
    filing.add_argument("--results", default=str(RESULTS))
    filing.set_defaults(run=_filing)

    smoke = sub.add_parser("smoke", help="the CI check: committed recordings, no model")
    smoke.add_argument("--recordings", default=str(SMOKE_RECORDINGS))
    smoke.add_argument("--search-recordings", default=str(SMOKE_DIR))
    smoke.set_defaults(run=_smoke)

    search = sub.add_parser("search", help="score the search-v1 questions of a split")
    search.add_argument("--split", required=True, choices=["val", "test"])
    search.add_argument("--recordings", required=True, help="the eval-v1 reading recordings")
    which = search.add_mutually_exclusive_group(required=True)
    which.add_argument("--record", help="call the local models and record into this folder")
    which.add_argument("--replay", help="replay the search recordings in this folder")
    search.add_argument("--smoke", action="store_true", help="the smoke documents and questions")
    search.add_argument(
        "--prompt",
        choices=sorted(READING_PROMPTS),
        default="v2",
        help="the reading prompt of the recordings (v1 is the untuned one)",
    )
    search.add_argument(
        "--query-model",
        help="the model that reads prompts (default: the config's query_model)",
    )
    search.add_argument(
        "--fill-vectors",
        action="store_true",
        help=(
            "with --replay: embed and record the vectors the folder lacks, query or document "
            "(no reading model; the folder must record the embedding model's digest)"
        ),
    )
    search.add_argument("--results", help="default: var/results-val for val, evals/results")
    search.set_defaults(run=_search)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    return int(args.run(args))


if __name__ == "__main__":
    raise SystemExit(main())
