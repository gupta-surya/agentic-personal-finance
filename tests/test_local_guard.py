"""The localhost guard: DNS-rebinding, cross-origin and token checks, and the LAN-bind refusal."""

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finance_agent.cli.serve import run_serve
from finance_agent.local_guard import SESSION_HEADER, harden, session_meta_tag
from tests.test_cli_serve import _ctx

BASE = "http://127.0.0.1:8123"


def _client() -> tuple[TestClient, str]:
    app = FastAPI()

    @app.get("/api/transactions")
    def rows() -> dict[str, str]:
        return {"ok": "rows"}

    @app.get("/api/other")
    def other() -> dict[str, str]:
        return {"ok": "other"}

    @app.post("/charts/render")
    def render() -> dict[str, str]:
        return {"ok": "chart"}

    @app.get("/charts/meta")
    def meta() -> dict[str, str]:
        return {"ok": "meta"}

    harden(app, 8123)
    return TestClient(app, base_url=BASE), app.state.session_token


def test_foreign_host_is_421() -> None:
    client, token = _client()
    r = client.get("/charts/meta", headers={"Host": "evil.example"})
    assert r.status_code == 421
    r = client.get(
        "/api/transactions", headers={"Host": "evil.example:8123", SESSION_HEADER: token}
    )
    assert r.status_code == 421
    # right name, wrong port: a rebinding page on another local port is refused too
    assert client.get("/charts/meta", headers={"Host": "localhost:9999"}).status_code == 421


def test_loopback_hosts_are_accepted() -> None:
    client, _ = _client()
    for host in ("127.0.0.1:8123", "localhost:8123", "[::1]:8123"):
        assert client.get("/charts/meta", headers={"Host": host}).status_code == 200


def test_api_needs_the_session_token() -> None:
    client, token = _client()
    assert client.get("/api/other").status_code == 401
    assert client.get("/api/other", headers={SESSION_HEADER: "wrong"}).status_code == 401
    assert client.get("/api/other", headers={SESSION_HEADER: token}).status_code == 200
    # a POST without the token (nothing under /api/ gets in anonymously)
    assert client.post("/api/other").status_code == 401


def test_cross_origin_is_403_on_row_endpoints_and_writes() -> None:
    client, token = _client()
    evil = {"Origin": "http://evil.example", SESSION_HEADER: token}
    assert client.get("/api/transactions", headers=evil).status_code == 403
    assert (
        client.post("/charts/render", headers={"Origin": "http://evil.example"}).status_code == 403
    )
    # same origin or no Origin passes; a cross-origin GET elsewhere is not an Origin matter
    assert client.get("/api/transactions", headers={SESSION_HEADER: token}).status_code == 200
    same = {"Origin": BASE, SESSION_HEADER: token}
    assert client.get("/api/transactions", headers=same).status_code == 200
    assert client.post("/charts/render", headers={"Origin": BASE}).status_code == 200
    assert client.get("/api/other", headers=evil).status_code == 200


def test_no_cors_headers_and_token_shape() -> None:
    client, token = _client()
    r = client.get("/charts/meta", headers={"Origin": BASE})
    assert not [h for h in r.headers if h.lower().startswith("access-control-")]
    assert len(token) >= 43  # 32 random bytes, urlsafe base64


def test_meta_tag_carries_the_token() -> None:
    app = harden(FastAPI(), 8123)
    assert (
        session_meta_tag(app)
        == f'<meta name="finance-session" content="{app.state.session_token}">'
    )


def test_serve_refuses_lan_bind_without_the_flag(tmp_path: Any) -> None:
    called = False

    def fake_server(app: Any, host: str, port: int) -> None:
        nonlocal called
        called = True

    assert run_serve(_ctx(tmp_path, None), host="0.0.0.0", synthetic=True, server=fake_server) == 1
    assert called is False
    code = run_serve(
        _ctx(tmp_path, None),
        host="0.0.0.0",
        synthetic=True,
        i_understand_lan=True,
        server=fake_server,
    )
    assert code == 0 and called


def test_serve_hardens_the_app_it_runs(tmp_path: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_server(app: Any, host: str, port: int) -> None:
        captured["app"] = app

    run_serve(_ctx(tmp_path, None), synthetic=True, port=8123, server=fake_server, console=None)
    client = TestClient(captured["app"], base_url=BASE)
    assert client.get("/charts/meta", headers={"Host": "evil.example"}).status_code == 421
