"""Turn step 8's policy off again (same name, ``enabled=False``).

    wax -p eval policies push policies/unblock_publish.py

Pushing a policy with an existing name updates it in place, so this disables
``eval_block_publish`` without deleting it — the Governance page still shows it
(disabled) and its evaluations stay on the runs it blocked. Push
``block_publish.py`` again to turn it back on.
"""

from waxell_sdk import policy

block_publish = policy(
    name="eval_block_publish",
    category="domain-governance",
    description="Runtime evaluation: reviewers may read and annotate things but never publish.",
    scope={"agents": ["reviewer_claude", "reviewer_crewai", "reviewer_autogen"]},
    rules={
        "blocked_actions": {"things": ["publish"]},
        "log_all_calls": True,
        "action_on_violation": "block",
    },
    priority=10,
    enabled=False,
)
