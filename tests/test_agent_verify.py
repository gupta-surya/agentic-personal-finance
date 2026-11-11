"""The groundedness verifier, checked against real rendered specs (fake catalog, no DB)."""

from datetime import date

from finance_agent.agent.verify import ground_truth, verify
from finance_agent.charts.fake_catalog import fake_session
from finance_agent.charts.spec import ChartSpec
from finance_agent.charts.templates import default_registry

TODAY = date(2026, 10, 25)


def _render(template_id: str, params: dict[str, object]) -> ChartSpec:
    registry = default_registry()
    with fake_session() as catalog:
        return registry.render(template_id, {"template": template_id, **params}, catalog, TODAY)


def test_grounded_money_and_percent_pass() -> None:
    spec = _render("kpi", {"measure": "spend", "period": {"preset": "last_month"}})
    # title is "You spent $2,124.22, Sep 2026"; previous 1987.91; change_percent 0.0686
    prose = "You spent $2,124.22 last month, up 6.9% from $1,987.91."
    report = verify(prose, spec)
    assert report.ok, report.unmatched
    assert "$2,124.22" in report.checked


def test_invented_figure_is_blocked() -> None:
    spec = _render("kpi", {"measure": "spend", "period": {"preset": "last_month"}})
    report = verify("You spent $2,124.22, and saved $500.00 besides.", spec)
    assert report.ok is False
    assert "$500.00" in report.unmatched


def test_incidental_counts_and_years_are_ignored() -> None:
    spec = _render("cash_flow", {"period": {"preset": "last_3_months"}})
    # 3 (months), 2026 (year), "top 8" style counts must not be treated as figures
    report = verify("Over the last 3 months of 2026 your net was $3,511.27.", spec)
    assert report.ok, report.unmatched
    assert "3" not in report.checked and "2026" not in report.checked


def test_percent_share_reconciles_against_fraction() -> None:
    spec = _render("spend_breakdown", {"period": {"preset": "last_month"}, "top_n": 5})
    # share is stored as 0.7061; prose says 70.61%
    report = verify("Rent was your biggest category at 70.61%.", spec)
    assert report.ok, report.unmatched


def test_rounded_money_matches() -> None:
    spec = _render("cash_flow", {"period": {"preset": "last_3_months"}})
    report = verify("Your net cash flow was about $3,511.", spec)  # rounded from 3511.27
    assert report.ok, report.unmatched


def test_ground_truth_includes_series_values() -> None:
    spec = _render("spend_breakdown", {"period": {"preset": "last_month"}, "top_n": 5})
    from decimal import Decimal

    assert Decimal("1500.00") in ground_truth(spec)  # Rent amount


def test_conversational_text_is_grounded_only_without_figures() -> None:
    assert verify("Hi! Ask me about your spending or cash flow.", None).ok is True
    assert verify("You have $5,000 saved.", None).ok is False
