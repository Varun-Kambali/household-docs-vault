import json
from pathlib import Path

import pytest

from household_vault import cli
from household_vault.cli import main
from household_vault.config import ConfigError
from tests.fakes import EVAL_V1


@pytest.fixture
def dev_env(tmp_path, monkeypatch):
    for name, path in (
        ("VAULT_ROOT", "vault"),
        ("VAULT_DB", "v.db"),
        ("VAULT_LOG_DIR", "logs"),
        ("VAULT_HOUSEHOLD", "h.json"),
    ):
        monkeypatch.setenv(name, str(tmp_path / path))  # never a developer's own .env values
    monkeypatch.setenv("VAULT_READER", "stand-in")
    return tmp_path


def test_cli_writes_the_emergency_sheet(tmp_path, monkeypatch):
    for name, path in (
        ("VAULT_ROOT", "vault"),
        ("VAULT_DB", "v.db"),
        ("VAULT_LOG_DIR", "logs"),
        ("VAULT_HOUSEHOLD", "h.json"),
    ):
        monkeypatch.setenv(name, str(tmp_path / path))  # never a developer's own .env values
    main(["emergency-sheet", "--out", str(tmp_path / "sheet.html")])
    assert "Master password:" in (tmp_path / "sheet.html").read_text()


def test_dev_vault_copies_val_documents_and_the_household(dev_env, capsys):
    main(["dev-vault", "--from", str(EVAL_V1), "--split", "val", "--limit", "3"])
    inbox = dev_env / "vault" / "Inbox"
    assert len(list(inbox.iterdir())) == 3
    people = json.loads((dev_env / "h.json").read_text())["people"]
    assert people[0]["id"] == "p1"
    assert "3" in capsys.readouterr().out
    # a second run adds nothing it already put there
    main(["dev-vault", "--from", str(EVAL_V1), "--split", "val", "--limit", "3"])
    assert len(list(inbox.iterdir())) == 3


def test_dev_vault_refuses_app_mode(dev_env, monkeypatch):
    def app_settings(app=False, **kwargs):
        raise AssertionError("dev-vault must not load app settings")

    monkeypatch.setattr(cli, "load_settings", app_settings)
    with pytest.raises(SystemExit):
        main(["dev-vault", "--app", "--from", str(EVAL_V1)])


def test_process_runs_once_and_prints_counts(dev_env, capsys):
    main(["dev-vault", "--from", str(EVAL_V1), "--split", "val", "--limit", "2"])
    capsys.readouterr()
    main(["process"])
    out = capsys.readouterr().out
    counts = dict(line.split(": ") for line in out.strip().splitlines())
    assert sum(int(n) for n in counts.values()) == 2 and set(counts) <= {"filed", "asked", "held"}


def test_run_serves_on_the_configured_address(dev_env, monkeypatch):
    seen = {}

    def fake_run(app, **kwargs):
        seen.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    main(["run"])
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8710 and seen["access_log"] is False


def test_run_app_reads_the_app_settings(monkeypatch):
    asked = {}

    def fake_load(app=False, **kwargs):
        asked["app"] = app
        raise ConfigError("stop here")

    monkeypatch.setattr(cli, "load_settings", fake_load)
    with pytest.raises(SystemExit):
        main(["run", "--app"])
    assert asked["app"] is True


def test_a_bad_setting_is_one_plain_line(dev_env, monkeypatch, capsys):
    monkeypatch.setenv("OLLAMA_URL", "http://example.com")
    with pytest.raises(SystemExit):
        main(["run"])
    assert "OLLAMA_URL" in capsys.readouterr().err
    assert isinstance(Path("."), Path)


def test_the_vault_command_reads_the_shell_arguments(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["vault"])
    cli.console()
    assert capsys.readouterr().out.startswith("household-docs-vault ")
    monkeypatch.setattr("sys.argv", ["vault", "bogus"])
    with pytest.raises(SystemExit):
        cli.console()
