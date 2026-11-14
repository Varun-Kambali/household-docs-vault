"""Settings for the app, read once at start-up.

Development mode reads the environment and an optional `.env` in the checkout and works only on
the synthetic vault. App mode (`vault run --app`) reads the real vault root from a small config
file in the app's own folder and ignores the environment for every path, so a stray variable
cannot point the installed app somewhere else.
"""

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from dotenv import dotenv_values
from pydantic import ValidationError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from household_vault.safety import assert_safe_path

PROJECT_NAME = "household-docs-vault"
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

# Settings field -> environment variable, for the fields that can come from the environment.
_ENV_NAMES = {
    "vault_root": "VAULT_ROOT",
    "db_path": "VAULT_DB",
    "household_path": "VAULT_HOUSEHOLD",
    "log_dir": "VAULT_LOG_DIR",
    "reader": "VAULT_READER",
    "recordings_dir": "VAULT_RECORDINGS",
    "ollama_url": "OLLAMA_URL",
    "vision_model": "VAULT_VISION_MODEL",
    "fallback_model": "VAULT_FALLBACK_MODEL",
    "host": "VAULT_HOST",
    "port": "VAULT_PORT",
}
_PATH_FIELDS = ("vault_root", "db_path", "household_path", "log_dir", "recordings_dir")
# In app mode these come from the app's own folder, never from the environment.
_APP_IGNORED = ("vault_root", "db_path", "household_path", "log_dir", "reader")


class ConfigError(ValueError):
    """The settings are missing, malformed or would send data off this Mac."""


class Settings(BaseSettings):
    """Every setting. `load_settings` passes the values in; nothing here reads the environment."""

    model_config = SettingsConfigDict(extra="forbid", frozen=True)

    mode: Literal["dev", "app"] = "dev"
    vault_root: Path = Path("./var/synthetic-vault")
    db_path: Path = Path("./var/vault.db")
    household_path: Path = Path("./var/household.json")
    log_dir: Path = Path("./var/logs")
    reader: Literal["mac", "stand-in", "recorded"] = "mac"
    recordings_dir: Path | None = None
    ollama_url: str = "http://127.0.0.1:11434"
    vision_model: str = "qwen3-vl:4b"
    fallback_model: str = "qwen3:4b"
    host: str = "127.0.0.1"
    port: int = 8710
    poll_seconds: float = 5.0
    settle_seconds: float = 10.0

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def source_root() -> Path | None:
    """The checkout this code runs from (its pyproject.toml names this project), else None."""
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if not pyproject.is_file() or not (parent / "src" / "household_vault").is_dir():
            continue
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if data.get("project", {}).get("name") == PROJECT_NAME:
            return parent
    return None


def app_config_dir() -> Path:
    return Path(os.path.expanduser("~")) / "Library" / "Application Support" / "household-vault"


def _read_app_config(config_dir: Path) -> dict[str, Any]:
    config_file = config_dir / "config.toml"
    try:
        data = tomllib.loads(config_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"missing {config_file}: it must set vault_root") from None
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {config_file}: {exc}") from None
    root = data.get("vault_root")
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise ConfigError(f"{config_file}: vault_root must be an absolute path")
    return data


def load_settings(
    app: bool = False,
    env: Mapping[str, str] | None = None,
    config_dir: Path | None = None,
) -> Settings:
    """Build the settings. A given `env` replaces both os.environ and `.env` (tests pass it)."""
    src = source_root()
    if env is None:
        merged: dict[str, str] = {}
        if not app and src is not None and (src / ".env").is_file():
            merged.update({k: v for k, v in dotenv_values(src / ".env").items() if v is not None})
        merged.update(os.environ)
        env = merged

    values: dict[str, Any] = {}
    for field, name in _ENV_NAMES.items():
        if app and field in _APP_IGNORED:
            continue
        if env.get(name):
            values[field] = env[name]

    if app:
        folder = (config_dir or app_config_dir()).expanduser()
        data = _read_app_config(folder)
        values["vault_root"] = Path(data["vault_root"])
        for key in ("vision_model", "fallback_model", "port"):
            if key in data:
                values[key] = data[key]
        values.update(
            db_path=folder / "vault.db",
            household_path=folder / "household.json",
            log_dir=folder / "logs",
            reader="mac",
        )

    try:
        settings = Settings(mode="app" if app else "dev", **values)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from None

    if not app:
        settings = _resolve_dev_paths(settings, src)

    _check_ollama_url(settings.ollama_url)
    if settings.host not in _LOCAL_HOSTS and settings.reader != "stand-in":
        raise ConfigError("VAULT_HOST must be localhost, 127.0.0.1 or ::1 when real readers run")
    return settings


def _check_ollama_url(url: str) -> None:
    problem = "OLLAMA_URL must be an http or https URL on this Mac (localhost, 127.0.0.1 or ::1)"
    if "\\" in url:
        raise ConfigError(problem)
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        parsed.port  # noqa: B018  (raises ValueError on a bad port)
    except ValueError:
        raise ConfigError(problem) from None
    if parsed.scheme not in ("http", "https") or "@" in parsed.netloc:
        raise ConfigError(problem)
    if hostname not in _LOCAL_HOSTS:
        raise ConfigError(problem)


def _resolve_dev_paths(settings: Settings, src: Path | None) -> Settings:
    """Make dev paths absolute against the checkout and run each through the safety guard."""
    resolved: dict[str, Path] = {}
    for field in _PATH_FIELDS:
        value: Path | None = getattr(settings, field)
        if value is None:
            continue
        path = value.expanduser()
        if not path.is_absolute():
            if src is None:
                raise ConfigError(
                    f"{_ENV_NAMES[field]} must be an absolute path outside a source checkout"
                )
            path = src / path
        resolved[field] = assert_safe_path(path)
    return settings.model_copy(update=resolved)
