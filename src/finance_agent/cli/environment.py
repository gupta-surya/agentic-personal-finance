"""Check the machine for Docker and Ollama without ever failing on a traceback.

Pure given an injected ``which`` and command ``runner`` (tests pass fakes), so the six-step
setup can report "Docker ok / not found: <download link>" deterministically.
"""

import shutil
from collections.abc import Callable
from dataclasses import dataclass

Runner = Callable[[list[str]], tuple[int, str]]
Which = Callable[[str], str | None]

DOCKER_URL = "https://www.docker.com/products/docker-desktop/"
OLLAMA_URL = "https://ollama.com/download"


@dataclass(frozen=True)
class ToolCheck:
    name: str
    present: bool
    running: bool
    detail: str
    install_url: str


def _run(command: list[str]) -> tuple[int, str]:
    import subprocess

    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as err:
        return 1, type(err).__name__
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def check_docker(which: Which = shutil.which, runner: Runner = _run) -> ToolCheck:
    if which("docker") is None:
        return ToolCheck("Docker", False, False, "not installed", DOCKER_URL)
    code, _ = runner(["docker", "info"])
    if code != 0:
        return ToolCheck("Docker", True, False, "installed but not running", DOCKER_URL)
    return ToolCheck("Docker", True, True, "ok", DOCKER_URL)


def check_ollama(which: Which = shutil.which, runner: Runner = _run) -> ToolCheck:
    if which("ollama") is None:
        return ToolCheck("Ollama", False, False, "not installed (optional)", OLLAMA_URL)
    code, _ = runner(["ollama", "list"])
    if code != 0:
        return ToolCheck("Ollama", True, False, "installed but not running", OLLAMA_URL)
    return ToolCheck("Ollama", True, True, "ok", OLLAMA_URL)
