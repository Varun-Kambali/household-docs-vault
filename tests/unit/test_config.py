from pathlib import Path

import pytest

from household_vault import config
from household_vault.config import ConfigError, load_settings, source_root
from household_vault.safety import UnsafePathError
from household_vault.vaultroot import VaultRoot


def test_dev_root_must_pass_the_safety_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_REAL_ROOT", str(tmp_path / "real"))
    with pytest.raises(UnsafePathError):
        load_settings(env={"VAULT_ROOT": str(tmp_path / "real" / "Family Vault")})


def test_relative_root_resolves_against_the_checkout_not_the_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir("/")
    src = source_root()
    assert src is not None
    assert load_settings(env={}).vault_root == src / "var" / "synthetic-vault"


def test_app_mode_takes_the_root_from_its_config_file_only(
    tmp_path: Path, fake_homes: Path
) -> None:
    (tmp_path / "config.toml").write_text('vault_root = "/Volumes/x/Family Vault"\n')
    s = load_settings(app=True, env={"VAULT_ROOT": "/tmp/other"}, config_dir=tmp_path)
    assert (s.mode, s.vault_root, s.db_path, s.reader) == (
        "app",
        Path("/Volumes/x/Family Vault"),
        tmp_path / "vault.db",
        "mac",
    )
    cloud = fake_homes / "Library/CloudStorage/GoogleDrive-x/My Drive/Family Vault"
    with pytest.raises(UnsafePathError):
        VaultRoot(cloud, mode="dev")
    assert VaultRoot(cloud, mode="app").root == cloud.resolve()


def test_models_and_the_server_stay_on_this_mac() -> None:
    for env in ({"OLLAMA_URL": "http://192.168.1.5:11434"}, {"VAULT_HOST": "0.0.0.0"}):
        with pytest.raises(ConfigError):
            load_settings(env=env)
    host = load_settings(env={"VAULT_HOST": "0.0.0.0", "VAULT_READER": "stand-in"}).host
    assert host == "0.0.0.0"


def test_app_mode_needs_an_absolute_root_in_its_config(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_settings(app=True, env={}, config_dir=tmp_path)
    (tmp_path / "config.toml").write_text('vault_root = "relative/place"\n')
    with pytest.raises(ConfigError):
        load_settings(app=True, env={}, config_dir=tmp_path)


def test_bad_values_become_config_errors() -> None:
    with pytest.raises(ConfigError):
        load_settings(env={"VAULT_READER": "cloud"})
    with pytest.raises(ConfigError):
        load_settings(env={"VAULT_PORT": "high"})


@pytest.mark.parametrize(
    "url",
    [
        "file://localhost/x",
        "http://evil.com\\@127.0.0.1:11434",
        "http://u:p@127.0.0.1:11434",
        "ftp://127.0.0.1:11434",
        "http://127.0.0.1:99999999",
    ],
)
def test_ollama_url_must_be_plain_http_to_this_mac(url: str) -> None:
    with pytest.raises(ConfigError):
        load_settings(env={"OLLAMA_URL": url})
    assert load_settings(env={"OLLAMA_URL": "https://localhost:11434"}).ollama_url


def test_dev_reads_dotenv_and_the_environment_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".env").write_text("VAULT_PORT=9000\nVAULT_VISION_MODEL=from-dotenv\n")
    monkeypatch.setattr(config, "source_root", lambda: checkout)
    for name in ("VAULT_ROOT", "VAULT_DB", "VAULT_HOUSEHOLD", "VAULT_LOG_DIR", "VAULT_RECORDINGS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VAULT_VISION_MODEL", "from-environment")
    s = load_settings()
    assert (s.port, s.vision_model) == (9000, "from-environment")
    assert s.vault_root == checkout.resolve() / "var" / "synthetic-vault"
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "config.toml").write_text('vault_root = "/Volumes/x/Family Vault"\n')
    app = load_settings(app=True, config_dir=app_dir)
    assert app.port == 8710


def test_without_a_checkout_a_relative_path_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "source_root", lambda: None)
    with pytest.raises(ConfigError, match="VAULT_DB"):
        load_settings(env={"VAULT_ROOT": str(tmp_path / "v")})


def test_recordings_dir_resolves_against_the_checkout() -> None:
    src = source_root()
    assert src is not None
    s = load_settings(env={"VAULT_RECORDINGS": "./var/rec"})
    assert s.recordings_dir == src / "var" / "rec"
