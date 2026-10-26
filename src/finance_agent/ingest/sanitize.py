"""Connector error text is untrusted: it comes from a bank-side server.

Store it untouched, and pass it through ``sanitize_for_display`` before showing it.
"""

import html


def sanitize_for_display(message: str, limit: int = 200) -> str:
    """Drop control and invisible characters, truncate, then HTML-escape."""
    printable = "".join(ch for ch in message if ch.isprintable())
    if len(printable) > limit:
        printable = printable[: limit - 1] + "\u2026"
    return html.escape(printable, quote=True)
