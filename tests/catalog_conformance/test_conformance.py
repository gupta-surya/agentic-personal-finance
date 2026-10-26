"""One suite, two implementations: the fake and Postgres must give identical results."""

from datetime import date
from decimal import Decimal

import pytest

from finance_agent.db.loader import Connection
from finance_agent.queries.series import SeriesCatalog
from tests.catalog_conformance.calls import (
    CALLS,
    FEBRUARY,
    FULL,
    HALF,
    MARCH,
    MONTH_END,
    OCTOBER,
    PARTIAL,
    RAISED,
    TIE_DAY,
    UNCAT,
    ZERO_ROW,
    comparable,
    invoke,
)
from tests.catalog_conformance.dataset import dataset, to_fake, to_postgres

TENANT = "demo-tenant"


@pytest.fixture(params=["fake", "postgres"])
def catalog(request: pytest.FixtureRequest, conn: Connection) -> SeriesCatalog:
    rows = dataset()
    if request.param == "fake":
        return to_fake(rows)
    return to_postgres(conn, TENANT, rows)


# --- layer (a): hard-calculated values, each implementation on its own ----------


def test_march_cash_flow(catalog: SeriesCatalog) -> None:
    result = catalog.cash_flow(*MARCH, "USD")

    assert result.rows is not None and len(result.rows) == 1
    row = result.rows[0]
    # inflow = 3200 income + 25 groceries refund; outflow = rent, two grocery runs,
    # dining, transport and the 19.99 uncategorized charge
    assert (row.month, row.inflow, row.outflow, row.net) == (
        date(2026, 3, 1),
        Decimal("3225.00"),
        Decimal("2058.35"),
        Decimal("1166.65"),
    )
    assert result.totals == {
        "inflow": Decimal("3225.00"),
        "outflow": Decimal("2058.35"),
        "net": Decimal("1166.65"),
    }


def test_february_cash_flow_excludes_the_transfer_pair(catalog: SeriesCatalog) -> None:
    row = (catalog.cash_flow(*FEBRUARY, "USD").rows or [])[0]

    # the +500/-500 pair on Feb 10 is not income or spend
    assert (row.inflow, row.outflow, row.net) == (
        Decimal("3200.00"),
        Decimal("1947.05"),
        Decimal("1252.95"),
    )


def test_march_kpis(catalog: SeriesCatalog) -> None:
    assert catalog.kpi("spend", *MARCH, "USD").value == Decimal("2033.35")
    assert catalog.kpi("income", *MARCH, "USD").value == Decimal("3200.00")
    assert catalog.kpi("net", *MARCH, "USD").value == Decimal("1166.65")
    # two grocery runs (192.78 + 198.42) net of the 25.00 refund
    assert catalog.kpi("spend", *MARCH, "USD", category="groceries").value == Decimal("366.20")


def test_march_breakdown_amounts_shares_and_order(catalog: SeriesCatalog) -> None:
    result = catalog.spend_breakdown(*MARCH, "USD")

    assert result.rows is not None
    assert [(r.group, r.amount, r.share, r.is_other) for r in result.rows] == [
        ("rent", Decimal("1500.00"), Decimal("0.7377"), False),
        ("groceries", Decimal("366.20"), Decimal("0.1801"), False),
        ("dining", Decimal("94.50"), Decimal("0.0465"), False),
        ("transport", Decimal("52.66"), Decimal("0.0259"), False),
        (None, Decimal("19.99"), Decimal("0.0098"), False),
    ]
    assert result.totals == {"spend": Decimal("2033.35")}


def test_top_two_folds_the_rest_into_a_flagged_last_row(catalog: SeriesCatalog) -> None:
    result = catalog.monthly_spend_by_category(*MARCH, "USD", top_n=2)

    assert result.rows is not None
    assert [(r.category, r.spend, r.is_other) for r in result.rows] == [
        ("groceries", Decimal("366.20"), False),
        ("rent", Decimal("1500.00"), False),
        (None, Decimal("167.15"), True),  # 94.50 + 52.66 + 19.99
    ]
    assert result.totals == {"spend": Decimal("2033.35")}


def test_ties_break_by_name_with_uncategorized_last(catalog: SeriesCatalog) -> None:
    result = catalog.spend_breakdown(*TIE_DAY, "USD")

    assert result.rows is not None
    assert [(r.group, r.amount) for r in result.rows] == [
        ("groceries", Decimal("55.00")),
        ("dining", Decimal("40.00")),
        ("transport", Decimal("40.00")),
        (None, Decimal("40.00")),
    ]


@pytest.mark.parametrize(
    ("top_n", "kept"),
    [(1, ["groceries"]), (2, ["groceries", "dining"]), (3, ["groceries", "dining", "transport"])],
)
def test_top_n_with_tied_groups_keeps_the_first_by_name(
    catalog: SeriesCatalog, top_n: int, kept: list[str]
) -> None:
    rows = catalog.spend_breakdown(*TIE_DAY, "USD", top_n=top_n).rows

    assert rows is not None
    assert [r.group for r in rows if not r.is_other] == kept
    folded = [r for r in rows if r.is_other]
    assert folded[0].amount == Decimal("175.00") - sum(
        (r.amount for r in rows if not r.is_other), Decimal(0)
    )


def test_a_zero_amount_row_makes_its_month_appear_with_zeros(catalog: SeriesCatalog) -> None:
    flow = catalog.cash_flow(*ZERO_ROW, "USD")
    breakdown = catalog.spend_breakdown(*ZERO_ROW, "USD")

    assert flow.rows is not None and len(flow.rows) == 1
    row = flow.rows[0]
    assert (row.month, row.inflow, row.outflow, row.net) == (
        date(2027, 1, 1),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
    )
    assert flow.totals == {"inflow": Decimal("0"), "outflow": Decimal("0"), "net": Decimal("0")}
    # a zero total never divides: the share is 0
    assert breakdown.rows is not None
    assert [(r.group, r.amount, r.share) for r in breakdown.rows] == [
        (None, Decimal("0"), Decimal("0"))
    ]
    assert breakdown.totals == {"spend": Decimal("0")}


def test_a_kept_uncategorized_row_sorts_before_the_folded_row(catalog: SeriesCatalog) -> None:
    folded = catalog.monthly_spend_by_category(*UNCAT, "USD", top_n=1)
    everything = catalog.monthly_spend_by_category(*UNCAT, "USD")

    assert folded.rows is not None and everything.rows is not None
    assert [(r.category, r.spend, r.is_other) for r in folded.rows] == [
        (None, Decimal("400.00"), False),
        (None, Decimal("30.00"), True),  # groceries, folded into the flagged bucket
    ]
    assert [(r.category, r.spend) for r in everything.rows] == [
        ("groceries", Decimal("30.00")),
        (None, Decimal("400.00")),
    ]


def test_shares_on_a_half_boundary_round_to_the_even_digit(catalog: SeriesCatalog) -> None:
    rows = catalog.spend_breakdown(*HALF, "USD").rows

    # 19999/20000 = 0.99995 and 1/20000 = 0.00005: both exact ties
    assert rows is not None
    assert [(r.group, r.amount, r.share) for r in rows] == [
        ("rent", Decimal("19999.00"), Decimal("1.0000")),
        ("dining", Decimal("1.00"), Decimal("0.0000")),
    ]


def test_the_last_day_of_a_month_and_the_first_of_the_next_bucket_apart(
    catalog: SeriesCatalog,
) -> None:
    rows = catalog.monthly_spend_by_category(*MONTH_END, "USD").rows

    assert rows is not None
    assert [(r.month, r.category, r.spend) for r in rows] == [
        (date(2027, 4, 1), "dining", Decimal("12.00")),
        (date(2027, 5, 1), "dining", Decimal("7.00")),
    ]


def test_the_pending_charge_and_the_other_currency_are_excluded(catalog: SeriesCatalog) -> None:
    # October dining is 87.50; the 50.00 pending charge does not count
    assert catalog.kpi("spend", *OCTOBER, "USD", category="dining").value == Decimal("87.50")
    # the only EUR row is a 30.00 dining charge in March
    assert catalog.kpi("spend", *MARCH, "EUR").value == Decimal("30.00")
    assert catalog.kpi("spend", *MARCH, "GBP").value == Decimal("0")


def test_empty_results_have_no_rows_and_no_totals(catalog: SeriesCatalog) -> None:
    for result in (
        catalog.cash_flow(date(2020, 1, 1), date(2020, 2, 1), "USD"),
        catalog.spend_breakdown(date(2020, 1, 1), date(2020, 2, 1), "USD"),
        catalog.monthly_spend_by_category(date(2020, 1, 1), date(2020, 2, 1), "USD"),
    ):
        assert result.rows == [] and result.totals == {}


# --- layer (b): the two implementations agree on every call ---------------------


def test_the_call_matrix_has_unique_ids_and_covers_every_method() -> None:
    ids = [c.id for c in CALLS]
    assert len(ids) == len(set(ids))
    assert {c.method for c in CALLS} == {
        "monthly_spend_by_category",
        "cash_flow",
        "spend_breakdown",
        "kpi",
    }
    assert len(CALLS) >= 100


def test_postgres_loaded_every_row_of_the_dataset(conn: Connection) -> None:
    to_postgres(conn, TENANT, dataset())

    count = conn.execute("SELECT count(*) FROM transactions").fetchone()
    assert count == (len(dataset()),)


def test_the_fake_and_postgres_agree_on_every_call(conn: Connection) -> None:
    rows = dataset()
    fake, postgres = to_fake(rows), to_postgres(conn, TENANT, rows)

    mismatches = []
    errors = 0
    for call in CALLS:
        expected, actual = invoke(fake, call), invoke(postgres, call)
        errors += expected == RAISED
        if comparable(expected) != comparable(actual):
            mismatches.append(
                f"{call.id}\n    fake:     {comparable(expected)}\n"
                f"    postgres: {comparable(actual)}"
            )

    assert not mismatches, f"{len(mismatches)} of {len(CALLS)} calls differ:\n" + "\n".join(
        mismatches[:5]
    )
    assert errors == 6  # top_n=0 and -3 on two methods, and kpi category on income and net


# --- envelope and cross-method invariants, per implementation -------------------


def test_each_call_gets_a_fresh_result_id_and_a_stable_version(catalog: SeriesCatalog) -> None:
    first = catalog.cash_flow(*MARCH, "USD")
    second = catalog.cash_flow(*MARCH, "USD")

    assert first.result_id != second.result_id
    assert first.data_version == second.data_version
    assert first.as_of.tzinfo is not None and first.amounts_in


@pytest.mark.parametrize("window", [FULL, MARCH, FEBRUARY, PARTIAL, OCTOBER])
def test_the_methods_agree_with_each_other(
    catalog: SeriesCatalog, window: tuple[date, date]
) -> None:
    start, end = window
    flow = catalog.cash_flow(start, end, "USD")
    breakdown = catalog.spend_breakdown(start, end, "USD")
    monthly = catalog.monthly_spend_by_category(start, end, "USD")

    assert catalog.kpi("net", start, end, "USD").value == flow.totals["net"]
    spend = catalog.kpi("spend", start, end, "USD").value
    assert spend == breakdown.totals["spend"] == monthly.totals["spend"]
    assert breakdown.rows is not None
    shares = sum((r.share for r in breakdown.rows), Decimal(0))
    assert abs(shares - 1) <= Decimal("0.0001") * len(breakdown.rows)
