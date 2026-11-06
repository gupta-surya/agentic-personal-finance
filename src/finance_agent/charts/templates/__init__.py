"""The template registry the API serves."""

from finance_agent.charts.registry import TemplateRegistry
from finance_agent.charts.templates import (
    cash_flow,
    clarify,
    kpi,
    spend_breakdown,
    spend_over_time,
)


def default_registry() -> TemplateRegistry:
    registry = TemplateRegistry()
    for module in (cash_flow, spend_over_time, spend_breakdown, kpi):
        registry.register(module.TEMPLATE)
    # Registered last: it validates its options against everything registered before it.
    registry.register(clarify.make_template(registry))
    return registry
