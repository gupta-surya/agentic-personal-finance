import pytest

from finance_agent.model_gateway import ConfigError, ModelConfig
from finance_agent.model_gateway.config import authority_of


def test_defaults_are_the_native_local_ollama() -> None:
    c = ModelConfig.from_env({})
    assert (c.endpoint.url, c.endpoint.authority, c.model, c.timeout_seconds) == (
        "http://localhost:11434",
        "localhost:11434",
        "qwen3:8b",
        60.0,
    )
    assert c.remote_endpoint is None and c.pinned_lan_host is None and c.remote_jobs == frozenset()


def test_values_come_from_the_environment() -> None:
    c = ModelConfig.from_env(
        {
            "MODEL_ENDPOINT": "http://host.docker.internal:11434/",
            "MODEL_NAME": "qwen3:14b",
            "MODEL_TIMEOUT_SECONDS": "12.5",
        }
    )
    assert (c.endpoint.url, c.model, c.timeout_seconds) == (
        "http://host.docker.internal:11434",
        "qwen3:14b",
        12.5,
    )


@pytest.mark.parametrize(
    "value",
    [
        "not a url",
        "ftp://localhost:11434",
        "http://",
        "http://user:pw@localhost:11434",
        "http://localhost:11434/v1",
        "http://localhost:11434?x=1",
        "http://localhost:notaport",
    ],
)
def test_a_malformed_endpoint_fails_at_startup_without_echoing_it(value: str) -> None:
    with pytest.raises(ConfigError) as err:
        ModelConfig.from_env({"MODEL_ENDPOINT": value})
    assert "MODEL_ENDPOINT" in str(err.value)
    assert value not in str(err.value)


@pytest.mark.parametrize("value", ["abc", "0", "-3", "601"])
def test_a_bad_timeout_fails_at_startup(value: str) -> None:
    with pytest.raises(ConfigError, match="MODEL_TIMEOUT_SECONDS"):
        ModelConfig.from_env({"MODEL_TIMEOUT_SECONDS": value})


def test_the_lan_opt_in_is_one_host_equal_to_the_endpoint() -> None:
    env = {"MODEL_ENDPOINT": "http://192.168.1.20:11434"}
    assert ModelConfig.from_env(
        {**env, "LOCAL_MODEL_HOSTS": "192.168.1.20:11434"}
    ).pinned_lan_host == ("192.168.1.20:11434")
    for bad in ("192.168.1.20:9999", "192.168.1.21:11434", "192.168.1.20:11434,10.0.0.5:11434"):
        with pytest.raises(ConfigError, match="LOCAL_MODEL_HOSTS"):
            ModelConfig.from_env({**env, "LOCAL_MODEL_HOSTS": bad})


def test_authority_of_applies_default_ports_and_lowercases() -> None:
    assert authority_of("https://API.Example.com/api/chat") == "api.example.com:443"
    assert authority_of("http://[::1]:11434/api/tags") == "::1:11434"


@pytest.mark.parametrize(
    "value",
    [
        "http://localhost\\.evil.com:11434",
        "http://127.0.0.1%2f:11434",
        "http://localhost%00:80",
        "http://lo calhost:11434",
        "http://localhost:0",
        "http://①②⑦.0.0.1:11434",
    ],
)
def test_hosts_the_guard_and_httpx_could_read_differently_are_refused(value: str) -> None:
    with pytest.raises(ConfigError):
        ModelConfig.from_env({"MODEL_ENDPOINT": value})


@pytest.mark.parametrize(
    "endpoint",
    ["https://api.somecloud.com", "http://8.8.8.8:11434", "http://models.example.com:11434"],
)
def test_the_lan_opt_in_refuses_a_public_host(endpoint: str) -> None:
    from finance_agent.model_gateway.config import parse_endpoint

    authority = parse_endpoint("x", endpoint).authority
    with pytest.raises(ConfigError, match="not a LAN server"):
        ModelConfig.from_env({"MODEL_ENDPOINT": endpoint, "LOCAL_MODEL_HOSTS": authority})


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://192.168.1.20:11434",
        "http://10.0.0.5:11434",
        "http://mybox.local:11434",
        "http://mybox:11434",
    ],
)
def test_the_lan_opt_in_accepts_private_addresses_and_local_names(endpoint: str) -> None:
    from finance_agent.model_gateway.config import parse_endpoint

    authority = parse_endpoint("x", endpoint).authority
    c = ModelConfig.from_env({"MODEL_ENDPOINT": endpoint, "LOCAL_MODEL_HOSTS": authority})
    assert c.pinned_lan_host == authority


def test_the_remote_endpoint_must_be_https() -> None:
    with pytest.raises(ConfigError, match="https"):
        ModelConfig.from_env({"REMOTE_MODEL_ENDPOINT": "http://api.example.com"})
