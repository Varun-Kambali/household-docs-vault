"""The `vault` command. Only prints the version until the app has more to do."""

from household_vault import __version__


def main() -> None:
    print(f"household-docs-vault {__version__}")
