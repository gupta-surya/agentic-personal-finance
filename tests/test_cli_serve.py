"""finance serve builds the right app without actually serving (no DB needed for synthetic)."""

from typing import Any

from finance_agent.cli.serve import run_serve
from finance_agent.crypto import FileKeyStore
from finance_agent.secrets import FileSecretStore


def _ctx(tmp_path: Any, url: str | None) -> Any:
    from zoneinfo import ZoneInfo

    from finance_agent.cli.context import AppContext

    config = FileSecretStore(tmp_path / "config.json")
    if url is not None:
        config.set("database_url", url)
    return AppContext(
        config=config,
        keystore=FileKeyStore(tmp_path / "k.json"),
        tenant_id="local",
        tz=ZoneInfo("UTC"),
    )


def test_serve_synthetic_builds_app_and_serves(tmp_path: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_server(app: Any, host: str, port: int) -> None:
        captured["app"] = app
        captured["bind"] = (host, port)

    code = run_serve(_ctx(tmp_path, None), synthetic=True, server=fake_server, port=8123)
    assert code == 0
    assert captured["bind"] == ("127.0.0.1", 8123)
    # It's the charts app: it exposes /charts/meta.
    from fastapi.testclient import TestClient

    client = TestClient(captured["app"])
    assert client.get("/charts/meta").json() == {"source": "synthetic"}


def test_serve_without_setup_refuses(tmp_path: Any) -> None:
    called = False

    def fake_server(app: Any, host: str, port: int) -> None:
        nonlocal called
        called = True

    code = run_serve(_ctx(tmp_path, None), synthetic=False, server=fake_server)
    assert code == 1
    assert called is False
