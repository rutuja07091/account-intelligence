"""
Tests the assistant's plumbing with a fake Claude client, so CI needs no API key.
The fake first sends a bad query, then a good one, then a final answer, which
checks that rejected queries are fed back and that answers are cached.
"""
from types import SimpleNamespace

import anthropic

import agent


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            block = SimpleNamespace(type="tool_use", id="t1", name="query_metrics",
                                    input={"model": "cases", "measures": ["revenue"]})
            return SimpleNamespace(stop_reason="tool_use", content=[block])
        if self.calls == 2:
            # The rejected query must have come back to the model as an error.
            last = kwargs["messages"][-1]["content"][0]
            assert last["is_error"] is True and "revenue" in last["content"]
            block = SimpleNamespace(type="tool_use", id="t2", name="query_metrics", input={
                "model": "event_followup", "measures": ["went_quiet"],
                "filters": [{"dimension": "event_name", "operator": "contains", "values": ["Riverbend"]}]})
            return SimpleNamespace(stop_reason="tool_use", content=[block])
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text="Four physicians went quiet.")])


def test_ask_recovers_from_bad_query_and_caches(layer, vp, monkeypatch, tmp_path):
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    monkeypatch.setattr(agent, "CACHE_PATH", str(tmp_path / "answers.json"))

    result = agent.ask("Who went quiet after the Riverbend dinner?", vp, layer)
    assert result.answer == "Four physicians went quiet."
    assert result.steps[0].error is not None
    assert result.steps[1].rows == [{"went_quiet": 4}]

    again = agent.replay("who went quiet after the  Riverbend dinner?", vp)
    assert again is not None and again.from_cache and again.answer == result.answer


def test_system_prompt_states_territory_scope(layer, ohio_tam):
    text = agent.system_prompt(layer, ohio_tam)
    assert "Ohio Valley" in text and "query_metrics" in text
