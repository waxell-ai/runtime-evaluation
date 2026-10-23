"""The pydantic_ai reviewer — ordinary pydantic_ai code, no Waxell imports.

`entrypoint: agent:reviewer` points at `reviewer` below. The runtime calls
`reviewer.run_sync(prompt)` and records `.output` (a `Review`, JSON-projected)
as the run's result.

pydantic_ai's Anthropic provider uses the official `anthropic` client, which
reads ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY from the environment — the
runtime points those at the run's governed proxy.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent


class Review(BaseModel):
    summary: str = Field(description="One sentence.")
    findings: list[str] = Field(
        description="Specific, checkable points about this body."
    )
    recommendation: Literal["publish", "revise", "cancel"]
    confidence: float = Field(ge=0.0, le=1.0)


reviewer = Agent(
    "anthropic:claude-sonnet-4-6",
    output_type=Review,
    system_prompt=(
        "You review work items for a small team. Be careful and brief. Findings "
        "must be specific to the body you were given. An empty or unreadable body "
        "is 'revise'."
    ),
)
