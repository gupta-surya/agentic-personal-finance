"""Untrusted text goes in a delimited user-message block, never in the system message."""

import re

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MAX_UNTRUSTED_CHARS = 200


def untrusted_block(label: str, text: str) -> str:
    """Wrap merchant/description text so the model treats it as data (CLAUDE.md invariant 5).

    Angle brackets are removed so the text cannot close the block, control characters are
    dropped, and the length is capped.
    """
    clean = _CONTROL.sub(" ", text).replace("<", " ").replace(">", " ")
    clean = " ".join(clean.split())[:MAX_UNTRUSTED_CHARS]
    return f"<untrusted_{label}>{clean}</untrusted_{label}>"
