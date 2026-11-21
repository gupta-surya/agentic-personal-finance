"""Docker/Ollama checks with injected which+runner (no real subprocess)."""

from collections.abc import Callable

from finance_agent.cli.environment import check_docker, check_ollama


def _which(present: set[str]) -> Callable[[str], str | None]:
    return lambda name: ("/usr/bin/" + name) if name in present else None


def test_docker_missing_running_and_installed_not_running() -> None:
    assert check_docker(_which(set()), lambda c: (0, "")).present is False

    ok = check_docker(_which({"docker"}), lambda c: (0, "ok"))
    assert ok.present and ok.running and ok.detail == "ok"

    down = check_docker(_which({"docker"}), lambda c: (1, "cannot connect"))
    assert down.present and down.running is False


def test_ollama_missing_is_optional_and_has_a_link() -> None:
    missing = check_ollama(_which(set()), lambda c: (0, ""))
    assert missing.present is False
    assert missing.install_url.startswith("https://")
    running = check_ollama(_which({"ollama"}), lambda c: (0, "qwen3:8b"))
    assert running.present and running.running
