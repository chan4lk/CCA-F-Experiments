"""The agent loop, rebuilt across batch rounds.

The Batches API returns `stop_reason: "tool_use"` and stops. Everything that an
agent harness would have done next happens in Conversation.advance.
"""
import json

import pytest
from fakes import Block, FakeHTTP, FakeResponse, Message, Usage, text_message, tool_call

from research_agent_batch.conversation import (
    ACTIVE,
    DONE,
    FAILED,
    Conversation,
    _parse,
    make_custom_id,
)


def conversation(**kw) -> Conversation:
    defaults = dict(
        custom_id="p3-validator-C001-a", role="validator", model="claude-haiku-4-5",
        system="you verify one claim", messages=[{"role": "user", "content": "claim"}],
        tools=[{"name": "web_fetch"}], output_config={"format": {}}, max_rounds=4)
    return Conversation(**{**defaults, **kw})


# --- custom ids -----------------------------------------------------------

def test_a_custom_id_is_readable_and_safe():
    assert make_custom_id("p3", "validator", "C001-b") == "p3-validator-C001-b"
    assert make_custom_id("p2", "gap-hunter", "G1") == "p2-gap-hunter-G1"


def test_unsafe_characters_are_replaced():
    """custom_id round-trips through the API; a slash or a space in one is a
    request that fails for a reason nobody enjoys diagnosing."""
    assert make_custom_id("p2", "researcher", "Q1 / x:y") == "p2-researcher-Q1---x-y"


def test_a_custom_id_is_capped():
    assert len(make_custom_id("p2", "researcher", "x" * 200)) == 64


# --- the request ----------------------------------------------------------

def test_the_request_carries_the_grant_and_the_schema():
    params = conversation().params()
    assert params["model"] == "claude-haiku-4-5"
    assert params["tools"] == [{"name": "web_fetch"}]
    assert params["output_config"] == {"format": {}}
    assert params["system"] == "you verify one claim"


def test_a_toolless_agent_sends_no_tools_key():
    """An empty `tools` array is not the same as no tools; send neither."""
    assert "tools" not in conversation(tools=[]).params()


def test_max_tokens_can_be_generous():
    """A batch request is never streamed and never held open, so the HTTP
    timeout that caps a live request's max_tokens does not apply."""
    assert conversation(max_tokens=32000).params()["max_tokens"] == 32000


# --- advancing on a tool call ---------------------------------------------

def test_a_tool_call_is_executed_here_and_fed_back():
    conv = conversation()
    http = FakeHTTP()
    retrievals = conv.advance(
        tool_call("web_fetch", {"url": "https://learn.microsoft.com/a"}), http)

    assert conv.status == ACTIVE
    assert conv.round == 1
    assert http.requested == ["https://learn.microsoft.com/a"]
    assert [r.tool for r in retrievals] == ["web_fetch"]

    assistant, user = conv.messages[-2], conv.messages[-1]
    assert assistant["role"] == "assistant"
    assert user["role"] == "user"
    assert user["content"][0]["type"] == "tool_result"
    assert "A maximum of 10 tools" in user["content"][0]["content"]


def test_all_tool_results_go_back_in_one_user_message():
    """Splitting them across several messages silently trains the model out of
    asking for parallel calls."""
    conv = conversation(tools=[{"name": "web_fetch"}])
    message = Message([
        Block({"type": "tool_use", "id": "t1", "name": "web_fetch",
               "input": {"url": "https://learn.microsoft.com/a"}}),
        Block({"type": "tool_use", "id": "t2", "name": "web_fetch",
               "input": {"url": "https://learn.microsoft.com/b"}}),
    ], "tool_use")
    conv.advance(message, FakeHTTP())

    user = conv.messages[-1]
    assert len(user["content"]) == 2
    assert [b["tool_use_id"] for b in user["content"]] == ["t1", "t2"]
    assert sum(1 for m in conv.messages if m["role"] == "user") == 2  # the original + this


def test_a_thinking_block_is_echoed_back_unchanged():
    """On every model here except haiku, thinking is on by default, and a
    thinking block must go back verbatim when the turn continues on that model."""
    conv = conversation()
    conv.advance(tool_call("web_fetch", {"url": "https://learn.microsoft.com/a"},
                           thinking="let me read the page"), FakeHTTP())
    blocks = conv.messages[-2]["content"]
    assert blocks[0]["type"] == "thinking"
    assert blocks[0]["thinking"] == "let me read the page"
    assert blocks[0]["signature"] == "sig-abc"


def test_a_failed_fetch_comes_back_as_an_error_result_not_an_exception():
    """A tool that throws ends the turn with an API error. A tool that says
    "I could not read this" lets a validator rule NOT_FOUND, which is correct."""
    conv = conversation()
    http = FakeHTTP(default=FakeResponse(b"", status=503))
    conv.advance(tool_call("web_fetch", {"url": "https://learn.microsoft.com/a"}), http)

    result = conv.messages[-1]["content"][0]
    assert result["is_error"] is True
    assert "503" in result["content"]
    assert conv.status == ACTIVE, "a dead page is a fact to reason about, not a crash"


def test_a_blocked_fetch_records_no_provenance():
    """Provenance is a record of what happened. A refused request retrieved
    nothing, so nothing may appear in the log."""
    conv = conversation(allowed_domains=["learn.microsoft.com"])
    retrievals = conv.advance(
        tool_call("web_fetch", {"url": "https://elsewhere.com/a"}), FakeHTTP())
    assert retrievals == []
    assert conv.messages[-1]["content"][0]["is_error"] is True


# --- finishing ------------------------------------------------------------

def test_a_structured_answer_finishes_the_conversation():
    conv = conversation()
    conv.advance(text_message('{"claim_id":"C001","verdict":"CONFIRMED","quote":"x"}'))
    assert conv.status == DONE
    assert conv.parsed["verdict"] == "CONFIRMED"


def test_usage_accumulates_across_rounds():
    conv = conversation()
    conv.advance(tool_call("web_fetch", {"url": "https://learn.microsoft.com/a"}),
                 FakeHTTP())
    conv.advance(text_message('{"verdict":"CONFIRMED"}'))
    assert conv.input_tokens == 200 and conv.output_tokens == 100
    assert conv.cost_usd > 0


def test_the_cost_is_the_batch_rate():
    from research_agent_batch.settings import cost_usd
    conv = conversation()
    conv.input_tokens, conv.output_tokens = 1_000_000, 0
    assert conv.cost_usd == cost_usd("claude-haiku-4-5", 1_000_000, 0)
    assert conv.cost_usd == 0.5, "haiku input is $1/MTok, halved for batch"


# --- failure modes --------------------------------------------------------

def test_the_round_ceiling_ends_a_looping_agent():
    """Each round is a batch, so an agent with no ceiling is unbounded
    wall-clock as well as unbounded spend."""
    conv = conversation(max_rounds=2)
    for _ in range(2):
        conv.advance(tool_call("web_fetch", {"url": "https://learn.microsoft.com/a"}),
                     FakeHTTP())
    assert conv.status == FAILED
    assert "ceiling" in conv.error


def test_unreadable_output_fails_rather_than_guessing():
    conv = conversation()
    conv.advance(text_message("I could not tell you"))
    assert conv.status == FAILED
    assert "no readable JSON" in conv.error


def test_a_refusal_is_reported_not_silently_treated_as_an_answer():
    conv = conversation()
    message = text_message("", stop_reason="refusal")
    message.stop_details = type("D", (), {"category": "cyber"})()
    conv.advance(message)
    assert conv.status == FAILED
    assert "declined" in conv.error and "cyber" in conv.error


def test_running_out_of_output_tokens_is_a_failure_not_an_empty_answer():
    conv = conversation()
    conv.advance(text_message("", stop_reason="max_tokens"))
    assert conv.status == FAILED
    assert "output tokens" in conv.error


# --- parsing --------------------------------------------------------------

def test_json_is_parsed_directly():
    assert _parse('{"a": 1}') == {"a": 1}


def test_an_object_is_recovered_from_surrounding_text():
    """output_config guarantees clean JSON; this is for the turn that ended some
    other way with a usable object still in it."""
    assert _parse('here: {"a": 2} done') == {"a": 2}


@pytest.mark.parametrize("text", ["", "nope", "{not json}", "[1,2]", "null"])
def test_anything_else_is_no_answer(text):
    assert _parse(text) is None


# --- persistence ----------------------------------------------------------

def test_a_conversation_round_trips_through_json():
    """A run may pause between rounds for hours; the conversation has to survive
    the process that created it."""
    conv = conversation()
    conv.advance(tool_call("web_fetch", {"url": "https://learn.microsoft.com/a"}),
                 FakeHTTP())
    restored = Conversation.from_dict(json.loads(json.dumps(conv.to_dict())))
    assert restored.messages == conv.messages
    assert restored.round == 1 and restored.allowed_domains == conv.allowed_domains
    assert restored.params() == conv.params()


# --- retries --------------------------------------------------------------

def test_a_resubmission_is_bounded_separately_from_rounds():
    """A retryable failure produces no result, so advance() never runs and
    `round` never increments. Without its own ceiling, an expired request would
    be resubmitted forever."""
    from research_agent_batch.conversation import MAX_RETRIES
    conv = conversation()
    for _ in range(MAX_RETRIES):
        assert conv.retry("expired") is True
        assert conv.status == ACTIVE
    assert conv.retry("expired") is False
    assert conv.status == FAILED
    assert "gave up after" in conv.error


def test_the_retry_count_survives_a_reload():
    """A run may be resumed by a different process between every round."""
    conv = conversation()
    conv.retry("expired")
    restored = Conversation.from_dict(json.loads(json.dumps(conv.to_dict())))
    assert restored.retries == 1
