"""Low-confidence transfer matches, listed so a wrong one can't hide real spend unseen.

A match with no transfer word on either leg is still made (that is what lets a
bank-to-wallet cash-out net out), but round amounts make coincidences likely, so the
user gets to confirm or reject each one. Confirm with ``confirm_transfer``; reject
with ``mark_not_transfer`` on either leg.
"""

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict

from finance_agent.db.loader import Connection
from finance_agent.queries.meta import data_stamp
from finance_agent.queries.result import Money, QueryResult

AMOUNTS_IN = (
    "Decimal amounts as strings. amount is the positive size of the transfer; "
    "out_* is the leg that lost money and in_* the leg that gained it."
)


class LowConfidenceMatchRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    group_id: int
    amount: Money
    gap_days: int
    out_account: str
    out_date: date
    out_description: str
    in_account: str
    in_date: date
    in_description: str


def list_low_confidence_matches(
    conn: Connection, tenant_id: str
) -> QueryResult[LowConfidenceMatchRow]:
    """Every transfer group still awaiting confirmation, oldest first."""
    rows = conn.execute(
        """
        SELECT g.id, abs(o.amount), abs(i.posted_date - o.posted_date),
               ao.name, o.posted_date, o.description,
               ai.name, i.posted_date, i.description
        FROM transfer_groups g
        JOIN transactions o ON o.tenant_id = g.tenant_id AND o.transfer_group_id = g.id
                           AND o.amount < 0
        JOIN transactions i ON i.tenant_id = g.tenant_id AND i.transfer_group_id = g.id
                           AND i.amount > 0
        JOIN accounts ao ON ao.tenant_id = o.tenant_id AND ao.id = o.account_id
        JOIN accounts ai ON ai.tenant_id = i.tenant_id AND ai.id = i.account_id
        WHERE g.tenant_id = %s AND g.match_confidence = 'low'
        ORDER BY least(o.posted_date, i.posted_date), g.id
        """,
        (tenant_id,),
    ).fetchall()
    data_version, as_of = data_stamp(conn, tenant_id)
    return QueryResult[LowConfidenceMatchRow](
        query="low_confidence_transfer_matches",
        params={},
        result_id=uuid.uuid4().hex,
        data_version=data_version,
        as_of=as_of,
        amounts_in=AMOUNTS_IN,
        rows=[
            LowConfidenceMatchRow(
                group_id=r[0],
                amount=r[1],
                gap_days=r[2],
                out_account=r[3],
                out_date=r[4],
                out_description=r[5],
                in_account=r[6],
                in_date=r[7],
                in_description=r[8],
            )
            for r in rows
        ],
    )
