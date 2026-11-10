"""Narration: one or two sentences around an already-computed chart.

The gateway runs this as a NARRATION job (aggregate-class, may be remote). The caller contract
is aggregates only: the summary is built from the chart's title and series totals, never from
raw line items (invariant 3). The verifier gates whatever comes back.
"""

from typing import Protocol

from pydantic import BaseModel, Field

from finance_agent.charts.spec import ChartSpec
from finance_agent.ingest.sanitize import sanitize_for_display
from finance_agent.model_gateway.client import ModelGateway
from finance_agent.model_gateway.routing import Job
from finance_agent.model_gateway.structured import Message


class Narration(BaseModel):
    prose: str = Field(max_length=600)


class Narrator(Protocol):
    def narrate(self, question: str, spec: ChartSpec) -> str: ...


def aggregate_summary(spec: ChartSpec) -> str:
    """Aggregates only (title + per-series totals). Series labels from the bank (merchant
    names) are sanitized before the model sees them (invariant 5)."""
    lines = [f"Chart: {spec.title}"]
    for series in spec.series:
        totals = ", ".join(
            f"{sanitize_for_display(p.x)}={p.y}" for p in series.points if p.y is not None
        )
        if totals:
            lines.append(f"{sanitize_for_display(series.label)}: {totals}")
    return "\n".join(lines)


SYSTEM = """Answer the question in ONE or TWO plain sentences using ONLY the figures in the
data provided. State dollar amounts and percentages exactly as they appear. Never invent a
number. No financial advice."""


class GatewayNarrator:
    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    def narrate(self, question: str, spec: ChartSpec) -> str:
        messages: list[Message] = [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": f"Question: {question}\n\nData:\n{aggregate_summary(spec)}",
            },
        ]
        return self._gateway.generate(Job.NARRATION, messages, Narration).prose
