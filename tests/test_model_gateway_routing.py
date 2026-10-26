import pytest

from finance_agent.model_gateway import ConfigError, Job, ModelConfig
from finance_agent.model_gateway.routing import DataClass, Router


def router(**env: str) -> Router:
    return Router(ModelConfig.from_env(env))


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://127.0.0.2:11434",
        "http://[::1]:11434",
        "http://host.docker.internal:11434",
    ],
)
def test_raw_jobs_resolve_to_local_endpoints(endpoint: str) -> None:
    r = router(MODEL_ENDPOINT=endpoint)
    for job in (Job.CATEGORIZE_MERCHANT, Job.AGENT_TURN, Job.BENCHMARK):
        assert job.data_class is DataClass.RAW
        assert not r.route(job).remote


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://192.168.1.20:11434",
        "https://api.example.com",
        "http://localhost.evil.example:11434",
        "http://127.0.0.1.evil.example:11434",
    ],
)
def test_a_non_local_endpoint_is_refused_at_construction(endpoint: str) -> None:
    with pytest.raises(ConfigError, match="not local"):
        router(MODEL_ENDPOINT=endpoint)


def test_a_pinned_lan_host_is_local_but_only_that_one() -> None:
    r = router(MODEL_ENDPOINT="http://192.168.1.20:11434", LOCAL_MODEL_HOSTS="192.168.1.20:11434")
    assert r.route(Job.CATEGORIZE_MERCHANT).endpoint.authority == "192.168.1.20:11434"
    assert r.authorities() == {"192.168.1.20:11434"}
    with pytest.raises(ConfigError, match="not local"):
        router(MODEL_ENDPOINT="http://192.168.1.21:11434")


def test_only_the_aggregate_job_can_go_remote() -> None:
    r = router(
        REMOTE_MODEL_ENDPOINT="https://api.example.com",
        REMOTE_MODEL_NAME="big",
        REMOTE_MODEL_JOBS="narration",
    )
    remote = r.route(Job.NARRATION)
    assert (remote.remote, remote.endpoint.url, remote.model) == (
        True,
        "https://api.example.com:443",
        "big",
    )
    assert not r.route(Job.CATEGORIZE_MERCHANT).remote
    assert r.authorities() == {"localhost:11434", "api.example.com:443"}


@pytest.mark.parametrize("job", ["categorize_merchant", "agent_turn", "benchmark"])
def test_a_raw_job_cannot_be_routed_remote(job: str) -> None:
    with pytest.raises(ConfigError, match="raw data and cannot go remote"):
        router(REMOTE_MODEL_ENDPOINT="https://api.example.com", REMOTE_MODEL_JOBS=job)


def test_remote_routing_needs_a_remote_and_a_known_job() -> None:
    with pytest.raises(ConfigError, match="no remote"):
        router(REMOTE_MODEL_JOBS="narration")
    with pytest.raises(ConfigError, match="unknown job"):
        router(REMOTE_MODEL_ENDPOINT="https://api.example.com", REMOTE_MODEL_JOBS="everything")


def test_nothing_is_remote_by_default() -> None:
    r = router()
    assert not any(r.route(j).remote for j in Job)
