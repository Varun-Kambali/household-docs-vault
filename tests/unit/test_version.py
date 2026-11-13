import re
from importlib import metadata

from household_vault import __version__
from household_vault.cli import main


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_version_matches_the_installed_package() -> None:
    assert metadata.version("household-docs-vault") == __version__


def test_cli_prints_version(capsys) -> None:  # type: ignore[no-untyped-def]
    main()
    assert capsys.readouterr().out.strip() == f"household-docs-vault {__version__}"
