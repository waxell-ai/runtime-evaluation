"""The LangGraph reviewer — ordinary LangGraph code, no Waxell imports.

`entrypoint: graph:app` in ../waxell.yaml points at `app` below. The runtime
calls `app.invoke(payload)` with the signal body (minus runtime keys) and
takes the last message's content as the run's text.

`ChatAnthropic` reads ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY from the
container environment, which the runtime points at the run's governed proxy:
your real key never enters this container, every call is policy-checked and
appears on the run page with tokens and cost.
"""

from __future__ import annotations

import json
from typing import TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

RULES = (
    "You review work items for a small team. Return ONLY a JSON object with "
    'keys "summary" (one sentence), "findings" (list of specific, checkable '
    'points about THIS body), "recommendation" ("publish" | "revise" | '
    '"cancel") and "confidence" (0.0-1.0). An empty or unreadable body is '
    '"revise".'
)

llm = ChatAnthropic(model="claude-sonnet-4-6", max_tokens=600, temperature=0)


class State(TypedDict, total=False):
    thing_id: str
    title: str
    body: str
    review: dict
    messages: list


def review(state: State) -> State:
    body = (state.get("body") or "").strip()
    prompt = (
        f"Title: {state.get('title') or '(untitled)'}\n\nBody:\n{body or '(empty)'}"
    )
    reply = llm.invoke([SystemMessage(content=RULES), HumanMessage(content=prompt)])
    text = (
        reply.content if isinstance(reply.content, str) else json.dumps(reply.content)
    )
    try:
        parsed = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except (ValueError, json.JSONDecodeError):
        parsed = {
            "summary": text[:200],
            "findings": [],
            "recommendation": "revise",
            "confidence": 0.2,
        }
    parsed["thing_id"] = state.get("thing_id", "")
    return {"review": parsed, "messages": [reply]}


g = StateGraph(State)
g.add_node("review", review)
g.add_edge(START, "review")
g.add_edge("review", END)
app = g.compile()
