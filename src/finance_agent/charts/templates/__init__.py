"""The template registry the API serves."""

from finance_agent.charts.registry import TemplateRegistry
from finance_agent.charts.templates import cash_flow


def default_registry() -> TemplateRegistry:
    registry = TemplateRegistry()
    registry.register(cash_flow.TEMPLATE)
    return registry
