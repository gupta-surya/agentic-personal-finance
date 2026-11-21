"""The prompt layer. One small Protocol so command flows can be scripted in tests and run
non-interactively from flags; the questionary/rich implementation is the only code that
reads a TTY. Every real prompt has a default and hides secret input.
"""

from collections.abc import Sequence
from typing import Protocol


class Prompter(Protocol):
    def text(self, message: str, *, default: str | None = None) -> str: ...

    def secret(self, message: str) -> str: ...

    def confirm(self, message: str, *, default: bool = True) -> bool: ...

    def select(self, message: str, options: Sequence[str]) -> str: ...

    def multiselect(self, message: str, options: Sequence[str]) -> list[str]: ...


class ScriptedPrompter:
    """A test double: answers are queued and returned in order."""

    def __init__(
        self,
        *,
        text: Sequence[str] = (),
        secret: Sequence[str] = (),
        confirm: Sequence[bool] = (),
        select: Sequence[str] = (),
        multiselect: Sequence[Sequence[str]] = (),
    ) -> None:
        self._text = list(text)
        self._secret = list(secret)
        self._confirm = list(confirm)
        self._select = list(select)
        self._multiselect = [list(m) for m in multiselect]

    def text(self, message: str, *, default: str | None = None) -> str:
        return self._text.pop(0) if self._text else (default or "")

    def secret(self, message: str) -> str:
        return self._secret.pop(0)

    def confirm(self, message: str, *, default: bool = True) -> bool:
        return self._confirm.pop(0) if self._confirm else default

    def select(self, message: str, options: Sequence[str]) -> str:
        return self._select.pop(0)

    def multiselect(self, message: str, options: Sequence[str]) -> list[str]:
        return self._multiselect.pop(0) if self._multiselect else []


class QuestionaryPrompter:
    """The real prompter. Imports questionary lazily so tests never need a TTY."""

    def text(self, message: str, *, default: str | None = None) -> str:
        import questionary

        return str(questionary.text(message, default=default or "").ask() or "")

    def secret(self, message: str) -> str:
        import questionary

        return str(questionary.password(message).ask() or "")

    def confirm(self, message: str, *, default: bool = True) -> bool:
        import questionary

        return bool(questionary.confirm(message, default=default).ask())

    def select(self, message: str, options: Sequence[str]) -> str:
        import questionary

        return str(questionary.select(message, choices=list(options)).ask() or "")

    def multiselect(self, message: str, options: Sequence[str]) -> list[str]:
        import questionary

        chosen = questionary.checkbox(message, choices=list(options)).ask()
        return [str(c) for c in (chosen or [])]
