"""`wax test` scenarios for the evaluation path.

    wax -p eval test scenarios/ --list
    wax -p eval test scenarios/ --profile eval

Each scenario fires a signal through the real API, follows the 202's run id
until the run is terminal, and asserts on the trace. The reviewer scenarios
need the domain server up and registered (steps 3–4 of the README).
"""

from waxell_sdk.testing import Expect, Scenario, ToolCallExpect

hello = Scenario(
    name="hello_answers",
    signal="hello_run",
    agent="hello",
    signal_payload={"prompt": "Reply with exactly: READY"},
    expect=Expect(must_contain=["READY"], max_seconds=120),
    tags=["smoke", "autonomous"],
)

reviewer_claude = Scenario(
    name="reviewer_claude_reads_then_reviews",
    signal="review_claude",
    agent="reviewer_claude",
    signal_payload={"thing_id": "thing-001"},
    expect=Expect(
        tool_calls=[
            ToolCallExpect(name="things__get", count_min=1),
            ToolCallExpect(name="things__set_review", count_min=1),
        ],
        max_seconds=300,
    ),
    tags=["reviewer", "autonomous", "mutation"],
)

reviewer_autogen = Scenario(
    name="reviewer_autogen_reads_then_reviews",
    signal="review_autogen",
    agent="reviewer_autogen",
    signal_payload={"thing_id": "thing-002"},
    expect=Expect(
        tool_calls=[ToolCallExpect(name="things__get", count_min=1)],
        max_seconds=300,
    ),
    tags=["reviewer", "autonomous", "mutation"],
)

empty_body_is_revise = Scenario(
    name="reviewer_claude_empty_body_recommends_revise",
    signal="review_claude",
    agent="reviewer_claude",
    signal_payload={"thing_id": "thing-003"},
    expect=Expect(must_contain=["revise"], max_seconds=300),
    tags=["reviewer", "autonomous", "regression"],
)

SCENARIOS = [hello, reviewer_claude, reviewer_autogen, empty_body_is_revise]
