"""``ingest``: bronze first, then normalize, then silver."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from finance_agent.db.loader import Connection
from finance_agent.ingest.bronze import finish_pull, record_pull
from finance_agent.ingest.contract import NormalizeResult, RawPull
from finance_agent.ingest.silver_loader import load_batch
from finance_agent.ingest.simplefin.normalize import normalize_simplefin

Normalizer = Callable[[RawPull, ZoneInfo], NormalizeResult]

NORMALIZERS: Mapping[str, Normalizer] = {"simplefin": normalize_simplefin}


@dataclass(frozen=True)
class IngestResult:
    raw_pull_id: int
    created: bool  # False when these exact bytes were already stored
    status: str  # ok | unrecognized | invalid
    dialect: str | None
    accounts: int
    transactions: int
    message: str | None


def ingest(
    conn: Connection,
    tenant_id: str,
    pull: RawPull,
    tz: ZoneInfo,
    normalizers: Mapping[str, Normalizer] = NORMALIZERS,
) -> IngestResult:
    """Store the pull's exact bytes, then normalize and load them.

    ``tz`` is the user's timezone; stored dates are the user's local dates.
    Malformed or unrecognized input is recorded in bronze and returned as a
    status, never raised, so one bad payload can't crash a sync. A tenant with no
    categories still raises ``TenantNotProvisionedError``; the bronze row is kept
    with a NULL status so the pull can be reprocessed.
    """
    raw_pull_id, created = record_pull(conn, tenant_id, pull)

    normalizer = normalizers.get(pull.source)
    if normalizer is None:
        result = NormalizeResult(
            status="unrecognized", message=f"no normalizer for {pull.source!r}"
        )
    else:
        result = normalizer(pull, tz)

    if result.batch is None:
        finish_pull(conn, tenant_id, raw_pull_id, result.status, result.dialect, result.message)
        return IngestResult(
            raw_pull_id, created, result.status, result.dialect, 0, 0, result.message
        )

    load_batch(conn, tenant_id, raw_pull_id, result.batch)
    finish_pull(conn, tenant_id, raw_pull_id, result.status, result.dialect, result.message)
    return IngestResult(
        raw_pull_id,
        created,
        result.status,
        result.dialect,
        len(result.batch.accounts),
        len(result.batch.transactions),
        result.message,
    )
