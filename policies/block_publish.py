"""A governance policy as code: no reviewer may call things.publish.

    wax -p eval policies push policies/block_publish.py --dry-run
    wax -p eval policies push policies/block_publish.py

The ``domain-governance`` category is enforced *before* a domain call leaves
the runtime — on every framework. After pushing, fire any reviewer: the run's
event stream shows a ``[governance]`` block on things/publish and your domain
server's ``/api/calls`` has no publish row. Remove the block with
``wax -p eval policies list`` / the Governance page, or push with
``enabled=False``.
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
)
