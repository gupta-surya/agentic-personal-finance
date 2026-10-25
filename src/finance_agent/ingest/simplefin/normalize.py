"""SimpleFIN entry point: bytes in, a ``NormalizeResult`` out. Never raises on bad input."""

from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from finance_agent.ingest.contract import NormalizeResult, RawPull
from finance_agent.ingest.simplefin.common import (
    describe_validation_error,
    load_json,
    local_date,
)
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

    try:
        batch = batch.model_copy(update=_request_window(pull, tz))
    except ValueError:
        return NormalizeResult(
            status="invalid", dialect=detection.dialect, message="unreadable request parameter"
        )
    message = "; ".join(batch.warnings) or None
    return NormalizeResult(status="ok", batch=batch, dialect=detection.dialect, message=message)


def _request_window(pull: RawPull, tz: ZoneInfo) -> dict[str, Any]:
    """What the request asked for, as the loader needs it (dates in the user's timezone)."""
    params = pull.request_params
    return {
        "pending_requested": params.get("pending") == "1",
        "window_start": local_date(int(params["start-date"]), tz)
        if "start-date" in params
        else None,
        "window_end": local_date(int(params["end-date"]), tz) if "end-date" in params else None,
    }
