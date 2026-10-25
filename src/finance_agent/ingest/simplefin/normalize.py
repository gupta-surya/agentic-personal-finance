"""SimpleFIN entry point: bytes in, a ``NormalizeResult`` out. Never raises on bad input."""

from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from finance_agent.ingest.contract import NormalizeResult, RawPull
from finance_agent.ingest.simplefin.common import describe_validation_error, load_json
from finance_agent.ingest.simplefin.detect import detect_dialect
from finance_agent.ingest.simplefin.v1 import normalize_v1
from finance_agent.ingest.simplefin.v2 import normalize_v2


def normalize_simplefin(pull: RawPull, tz: ZoneInfo) -> NormalizeResult:
    """``tz`` is the user's timezone: dates are the user's local calendar dates."""
    try:
        doc = load_json(pull.body)
    except (UnicodeDecodeError, ValueError) as error:
        return NormalizeResult(status="invalid", message=f"not valid JSON: {type(error).__name__}")

    detection = detect_dialect(doc)
    if detection.dialect == "unrecognized":
        return NormalizeResult(status="unrecognized", message="not a SimpleFIN account set")

    assert isinstance(doc, dict)
    typed: dict[str, Any] = doc
    try:
        if detection.dialect == "v2":
            batch = normalize_v2(typed, tz, detection.warnings)
        else:
            batch = normalize_v1(typed, tz, detection.warnings)
    except ValidationError as error:
        return NormalizeResult(
            status="invalid", dialect=detection.dialect, message=describe_validation_error(error)
        )
    except ValueError as error:
        return NormalizeResult(status="invalid", dialect=detection.dialect, message=str(error))
    except (AttributeError, KeyError, TypeError):
        return NormalizeResult(
            status="invalid", dialect=detection.dialect, message="unexpected payload structure"
        )

    message = "; ".join(batch.warnings) or None
    return NormalizeResult(status="ok", batch=batch, dialect=detection.dialect, message=message)
