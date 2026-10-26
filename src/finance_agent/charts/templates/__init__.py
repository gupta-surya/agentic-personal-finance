"""The template registry the API serves."""

from finance_agent.charts.registry import TemplateRegistry
from finance_agent.charts.templates import cash_flow, spend_breakdown, spend_over_time


def default_registry() -> TemplateRegistry:
    registry = TemplateRegistry()
    for module in (cash_flow, spend_over_time, spend_breakdown):
        registry.register(module.TEMPLATE)
    return registry
