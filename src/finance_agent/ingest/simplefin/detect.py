"""Tell SimpleFIN protocol v1 from v2 by the shape of the response."""

from dataclasses import dataclass, field
from typing import Literal

Dialect = Literal["v1", "v2", "unrecognized"]


@dataclass(frozen=True)
class Detection:
    dialect: Dialect
    warnings: list[str] = field(default_factory=list)


def detect_dialect(doc: object) -> Detection:
    """v2 has ``errlist``, ``connections`` or an account ``conn_id``; v1 has an account
    ``org`` object (or just the older top-level ``errors``).

    Both shapes at once is treated as v2 and recorded as a warning. Neither is
    ``unrecognized``: the bytes stay in bronze and silver is untouched.
    """
    if not isinstance(doc, dict) or not isinstance(doc.get("accounts"), list):
        return Detection("unrecognized")
    accounts = [a for a in doc["accounts"] if isinstance(a, dict)]

    v2_signal = "errlist" in doc or "connections" in doc or any("conn_id" in a for a in accounts)
    v1_signal = any("org" in a for a in accounts)

    if v2_signal and v1_signal:
        return Detection("v2", ["payload has both v1 (org) and v2 (conn_id/errlist) fields"])
    if v2_signal:
        return Detection("v2")
    if v1_signal or "errors" in doc:
        return Detection("v1")
    return Detection("unrecognized")
