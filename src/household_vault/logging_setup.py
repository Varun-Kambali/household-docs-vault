"""The application log: JSON lines in `vault.log`, every record redacted before it is written.

No request body, password, card number or traceback goes in. A record that carries an exception
logs the exception's type only, because an exception message can hold document text.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from household_vault.leakscan import install_log_redaction, redact

LOG_FILE = "vault.log"
_MARK = "_household_vault_handler"
_CONSOLE_MARK = "_household_vault_console"


class RedactFilter(logging.Filter):
    """Replaces the message with its redacted text and drops the traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            text = record.getMessage()
        except Exception:
            text = "a log line that could not be formatted"
        if record.exc_info:
            exc_type = record.exc_info[0]
            text = f"{text} ({exc_type.__name__ if exc_type else 'error'})"
        record.msg = redact(text)
        record.args = None
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="seconds"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            },
            ensure_ascii=False,
        )


def configure(log_dir: Path) -> None:
    """Write the application log to `log_dir/vault.log`. Safe to call again: the handler this
    function made earlier is replaced, so a second call never doubles the lines."""
    install_log_redaction()
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for old in [h for h in root.handlers if getattr(h, _MARK, False)]:
        root.removeHandler(old)
        old.close()
    handler = logging.FileHandler(log_dir / LOG_FILE, encoding="utf-8")
    setattr(handler, _MARK, True)
    handler.addFilter(RedactFilter())
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def add_console() -> None:
    """Also print the (redacted) log to the terminal, for `vault run`."""
    root = logging.getLogger()
    if any(getattr(h, _CONSOLE_MARK, False) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    setattr(handler, _CONSOLE_MARK, True)
    handler.addFilter(RedactFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
