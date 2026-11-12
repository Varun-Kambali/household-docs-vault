from household_vault import __version__
from household_vault.cli import main


def test_version_is_semver() -> None:
    assert __version__ == "0.0.0"


def test_cli_prints_version(capsys) -> None:  # type: ignore[no-untyped-def]
    main()
    assert capsys.readouterr().out.strip() == "household-docs-vault 0.0.0"
