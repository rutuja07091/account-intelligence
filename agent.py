"""
The assistant: turns a stakeholder's question into governed metric queries.

How it works:
    1. Claude gets the question plus a catalog of every model, measure, and
       dimension in semantic_model.yaml.
    2. Claude has exactly one tool, query_metrics. It cannot write SQL.
    3. Our code validates the request, applies the user's territory, runs it,
       and hands the rows back. Claude may call the tool a few times.
    4. Claude answers in plain language and we keep every query it made, so
       the app can show exactly where each number came from.

Every live answer is also saved to cache/answers.json. Replay mode reads from
that file, so a demo still works if the network or the API is down.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from semantic_layer import MetricQuery, QueryError, SemanticLayer, User

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(HERE, "cache", "answers.json")
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_TOOL_ROUNDS = 5
MAX_ROWS_TO_MODEL = 50

QUERY_TOOL = {
    "name": "query_metrics",
    "description": (
        "Run a governed metric query. Choose one model, one or more of its measures, "
        "and optionally its dimensions, filters, a date range, ordering, and a limit. "
        "Only names listed in the catalog are accepted. Returns rows as JSON."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "model": {"type": "string", "description": "Model name from the catalog"},
            "measures": {"type": "array", "items": {"type": "string"}},
            "dimensions": {"type": "array", "items": {"type": "string"}},
            "filters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "dimension": {"type": "string"},
                        "operator": {"type": "string",
                                     "enum": ["equals", "not_equals", "contains", "in", "gt", "lt"]},
                        "values": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["dimension", "operator", "values"],
                },
            },
            "date_range": {"type": "array", "items": {"type": "string"},
                           "description": "[start, end] as YYYY-MM-DD, only for models with a date"},
            "order_by": {"type": "string"},
            "order_direction": {"type": "string", "enum": ["asc", "desc"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        },
        "required": ["model", "measures"],
    },
}


def system_prompt(layer: SemanticLayer, user: User) -> str:
    scope = (f"The user is {user.name}, the Territory Account Manager for {user.territory}. "
             f"Every query is automatically limited to {user.territory}; they cannot see other territories."
             if user.territory else
             f"The user is {user.name} and can see all territories.")
    return f"""You are an analytics assistant for a medical technology company's commercial team.
You answer questions about accounts, ordering physicians, case volume, and field programs.

{scope}

Rules:
- Every number you state must come from a query_metrics result in this conversation. Never estimate or invent figures.
- If the catalog has no measure that answers the question, say so plainly and suggest the closest thing you can answer.
- There is no patient-level data anywhere in this system, by design. If asked for patient names, dates of birth, scan dates, or any patient detail, decline in one sentence and explain that patient data is kept out of the commercial system.
- When matching an account, event, or physician name, use the 'contains' operator with a short distinctive word, since users rarely type exact names.
- If a territory-restricted user asks about another territory and gets no rows, tell them the data is outside their territory rather than saying nothing exists.
- If an account's data_status is 'Data gap' (or account_signal is 'Data gap'), its change in cases cannot be trusted because missing feed days look like a decline. Never call it a decline; say the data feed needs checking first.
- Lead with the answer in one or two sentences, then a short list only if it helps. Name the metric you used, and mention any caveat in its definition (for example, utilization is an estimate).
- Keep answers under 150 words.

Catalog of everything you can query:
{layer.catalog_text()}
"""


@dataclass
class Step:
    query: Dict[str, Any]
    sql: str = ""
    params: List[Any] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class AgentResult:
    answer: str
    steps: List[Step]
    from_cache: bool = False


def _cache_key(user: User, question: str) -> str:
    return f"{user.territory or 'ALL'}::{' '.join(question.lower().split())}"


def _load_cache() -> Dict[str, Any]:
    if not os.path.exists(CACHE_PATH):
        return {}
    with open(CACHE_PATH) as f:
        return json.load(f)


def _save_to_cache(user: User, question: str, result: AgentResult) -> None:
    cache = _load_cache()
    cache[_cache_key(user, question)] = {
        "question": question,
        "answer": result.answer,
        "steps": [s.__dict__ for s in result.steps],
    }
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2, default=str)


def replay(question: str, user: User) -> Optional[AgentResult]:
    hit = _load_cache().get(_cache_key(user, question))
    if not hit:
        return None
    return AgentResult(answer=hit["answer"], steps=[Step(**s) for s in hit["steps"]], from_cache=True)


def ask(question: str, user: User, layer: SemanticLayer,
        history: Optional[List[Dict[str, Any]]] = None) -> AgentResult:
    """Answer one question live. history is prior plain-text turns, for follow-ups."""
    import anthropic  # imported here so replay mode works without the package configured

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    messages: List[Dict[str, Any]] = list(history or []) + [{"role": "user", "content": question}]
    steps: List[Step] = []

    for _ in range(MAX_TOOL_ROUNDS + 1):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system_prompt(layer, user),
            tools=[QUERY_TOOL],
            messages=messages,
        )
        if response.stop_reason != "tool_use":
            answer = "".join(b.text for b in response.content if b.type == "text").strip()
            result = AgentResult(answer=answer, steps=steps)
            _save_to_cache(user, question, result)
            return result

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            step = Step(query=dict(block.input))
            try:
                df, sql, params = layer.run(MetricQuery.from_dict(block.input), user)
                step.sql, step.params = sql, params
                step.rows = json.loads(df.to_json(orient="records"))
                payload = {"row_count": len(df), "rows": step.rows[:MAX_ROWS_TO_MODEL],
                           "truncated": len(df) > MAX_ROWS_TO_MODEL}
                tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                     "content": json.dumps(payload, default=str)})
            except QueryError as e:
                # Hand the validation error back so the model can correct its request.
                step.error = str(e)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                     "content": f"Query rejected: {e}", "is_error": True})
            steps.append(step)
        messages.append({"role": "user", "content": tool_results})

    return AgentResult(answer="I could not finish answering within the query limit. Try a narrower question.",
                       steps=steps)
