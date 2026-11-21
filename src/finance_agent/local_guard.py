"""Localhost hardening: a loopback port that returns row data is readable by any web page via
DNS rebinding unless the server checks who is asking. Applied to the whole app by the serve
entrypoints (not by ``create_app``, so unit tests keep using TestClient's ``testserver`` host).

Order of checks: Host (421), then Origin (403), then the per-launch session token (401).
No CORS headers are ever added. The token lives in memory only; it is never logged or stored.
"""

import secrets
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
SESSION_HEADER = "X-Finance-Session"
_ROW_PREFIXES = ("/api/transactions", "/api/accounts")


def refuse_lan_bind(host: str, i_understand_lan: bool) -> str | None:
    """The error to show when binding beyond loopback without the explicit flag, else None."""
    if host in ("127.0.0.1", "localhost", "::1") or i_understand_lan:
        return None
    return (
        f"Refusing to bind {host}: it exposes your transactions to the network. "
        "Pass --i-understand-lan to allow it."
    )


def session_meta_tag(app: FastAPI) -> str:
    """The tag the static server injects into ``index.html`` so the page can authenticate."""
    return f'<meta name="finance-session" content="{app.state.session_token}">'


def harden(app: FastAPI, port: int | None = None) -> FastAPI:
    """Install the guard. ``port=None`` accepts any port (uvicorn's, when the entrypoint can't
    know it); the host names are always limited to loopback."""
    token = secrets.token_urlsafe(32)  # 32 random bytes
    app.state.session_token = token
    allowed = {f"{h}:{port}" for h in LOOPBACK_HOSTS} if port is not None else None

    def host_ok(host: str) -> bool:
        if allowed is not None:
            return host in allowed
        name, _, number = host.rpartition(":")
        return name in LOOPBACK_HOSTS and number.isdigit()

    @app.middleware("http")
    async def guard(request: Request, call_next: Any) -> Any:
        host = request.headers.get("host", "")
        if not host_ok(host):
            return JSONResponse({"detail": "Unrecognized Host."}, status_code=421)
        path = request.url.path
        origin = request.headers.get("origin")
        checks_origin = request.method != "GET" or path.startswith(_ROW_PREFIXES)
        if checks_origin and origin is not None and origin != f"http://{host}":
            return JSONResponse({"detail": "Cross-origin request refused."}, status_code=403)
        if path.startswith("/api/") and not secrets.compare_digest(
            request.headers.get(SESSION_HEADER, "").encode(), token.encode()
        ):
            return JSONResponse({"detail": "Missing or wrong session token."}, status_code=401)
        return await call_next(request)

    return app
