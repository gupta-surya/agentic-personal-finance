import ast
import json
from pathlib import Path

import pytest
from psycopg import Connection

from finance_agent.categorize.rules import categorize
from finance_agent.categorize.starter_rules import seed_starter_rules
from finance_agent.model_gateway import ModelConfig, ModelUnavailable, check, model_status_signal
from finance_agent.model_gateway.health import server_version
from finance_agent.model_gateway.transport import Response
from tests.categorize_helpers import TENANT, Txn, load, state
from tests.model_gateway_helpers import LOCAL, FakeTransport

OFFLINE = "Model offline: new merchants stay uncategorized until it is back."
NOT_INSTALLED = "Model not installed: new merchants stay uncategorized until it is."


def tags(*names: str) -> Response:
    return Response(200, json.dumps({"models": [{"name": n} for n in names]}).encode())


def with_tags(reply: Response | Exception) -> FakeTransport:
    fake = FakeTransport()
    fake.get_replies["tags"] = reply
    return fake


def test_a_reachable_endpoint_with_the_model_is_healthy_and_silent() -> None:
    fake = with_tags(tags("codestral:latest", "qwen3:8b"))

    status = check(LOCAL, fake)

    assert (status.available, status.model_present, status.detail) == (True, True, "ok")
    assert model_status_signal(status) is None
    assert fake.gets == ["http://localhost:11434/api/tags"] and fake.posts == []


def test_a_reachable_endpoint_without_the_model_says_so() -> None:
    status = check(LOCAL, with_tags(tags("codestral:latest")))

    assert (status.available, status.model_present) == (True, False)
    assert model_status_signal(status) == NOT_INSTALLED


def test_an_unreachable_endpoint_is_offline_and_the_signal_names_no_host() -> None:
    status = check(LOCAL, with_tags(ModelUnavailable("model endpoint is unreachable")))

    assert (status.available, status.model_present) == (False, False)
    signal = model_status_signal(status)
    assert signal == OFFLINE
    assert "localhost" not in signal and "11434" not in signal


@pytest.mark.parametrize(
    "reply", [Response(500, b""), Response(200, b"nonsense"), Response(404, b"")]
)
def test_a_bad_health_reply_counts_as_offline(reply: Response) -> None:
    assert not check(LOCAL, with_tags(reply)).available


def test_an_untagged_model_name_matches_latest() -> None:
    config = ModelConfig.from_env({"MODEL_NAME": "qwen3"})
    assert check(config, with_tags(tags("qwen3:latest"))).model_present
    assert not check(config, with_tags(tags("qwen3:8b"))).model_present


def test_the_server_version_is_read_when_available() -> None:
    fake = FakeTransport()
    fake.get_replies["version"] = Response(200, b'{"version": "0.40.10"}')
    assert server_version(LOCAL, fake) == "0.40.10"
    assert server_version(LOCAL, FakeTransport()) is None


def test_with_the_model_down_ingest_and_categorization_still_complete_via_rules(
    conn: Connection,
) -> None:
    config = ModelConfig.from_env({"MODEL_ENDPOINT": "http://127.0.0.1:1"})  # nothing listens
    status = check(config)
    assert (status.available, model_status_signal(status)) == (False, OFFLINE)

    load(conn, [Txn("n1", "NETFLIX"), Txn("s1", "STARBUCKS #1234"), Txn("x1", "MYSTERY CORP")])
    seed_starter_rules(conn, TENANT)
    categorize(conn, TENANT)

    assert state(conn) == {
        "n1": ("subscriptions", "rule"),
        "s1": ("dining", "rule"),
        "x1": (None, None),  # a novel merchant waits for the model
    }


def test_nothing_in_the_data_pipeline_imports_the_gateway() -> None:
    src = Path(__file__).resolve().parents[1] / "src" / "finance_agent"
    offenders = []
    for pkg in ("ingest", "categorize", "reconcile", "queries", "db", "clients"):
        for path in (src / pkg).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                if any("model_gateway" in n for n in names):
                    offenders.append(str(path.relative_to(src)))
    assert offenders == []
