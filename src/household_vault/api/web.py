"""The built web app (`web/dist`), served by the API from the same origin.

The page and its files carry one Content-Security-Policy that allows only this origin, so the
app makes no request anywhere else. Paths the app owns (`/`, `/doc/12`, `/area/tax`) answer with
the app page and the app picks the screen; the API's own paths (`/v1/...`, `/healthz`) never do,
so a mistyped API path stays a JSON 404 instead of an HTML page.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response

APP_CSP = (
    "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'"
)
_API_PREFIXES = ("v1", "healthz")
_NO_STORE = "no-store"
_HASHED = "public, max-age=31536000, immutable"


def default_dist() -> Path | None:
    """Where `vault run` finds the build: `VAULT_WEB_DIST` if set (the image sets it), else
    `web/dist` beside `src/` in a checkout. None when there is no build, and the API then runs
    alone. `create_app` serves the app only when it is given a folder, so tests never pick up a
    build that happens to be lying in the working tree."""
    named = os.environ.get("VAULT_WEB_DIST")
    folder = Path(named) if named else Path(__file__).resolve().parents[3] / "web" / "dist"
    return folder if (folder / "index.html").is_file() else None


def _is_api_path(path: str) -> bool:
    first = path.split("/", 1)[0]
    return first in _API_PREFIXES


def add_web_routes(app: FastAPI, dist: Path | None) -> None:
    """Add the app's routes. Call it after every API route, so none of them is shadowed."""
    if dist is None or not (dist / "index.html").is_file():
        return
    root = dist.resolve()

    def page() -> Response:
        return FileResponse(
            root / "index.html",
            headers={"Content-Security-Policy": APP_CSP, "Cache-Control": _NO_STORE},
        )

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def web(path: str) -> Response:
        if _is_api_path(path):
            raise HTTPException(status_code=404, detail="Not found.")
        try:
            target = (root / path).resolve()
            is_file = bool(path) and target.is_relative_to(root) and target.is_file()
        except (ValueError, OSError):
            # A NUL byte or a name the filesystem refuses is not a file of the build.
            raise HTTPException(status_code=404, detail="Not found.") from None
        if is_file:
            hashed = target.parent.name == "assets"
            return FileResponse(
                target,
                headers={
                    "Content-Security-Policy": APP_CSP,
                    "Cache-Control": _HASHED if hashed else _NO_STORE,
                },
            )
        # A name with an extension is a file that is not there, not a screen of the app.
        if "." in path.rsplit("/", 1)[-1] or ".." in path.split("/"):
            raise HTTPException(status_code=404, detail="Not found.")
        return page()

    @app.api_route(
        "/{path:path}", methods=["POST", "PUT", "PATCH", "DELETE"], include_in_schema=False
    )
    def no_such_route(path: str) -> Response:
        # Nothing but a GET reaches the app, and every real route is registered before this one.
        raise HTTPException(status_code=404, detail="Not found.")
