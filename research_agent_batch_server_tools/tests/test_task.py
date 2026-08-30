"""One agent, as one batch request.

The sibling's equivalent file is `test_conversation.py`, and most of it is about
a loop: a tool call comes back, the tools run, the results are appended, the next
round goes out. None of that exists here. What is tested instead is that a
finished turn is recognised as finished, that the one continuation case is
handled, and that a client-side tool call — which nothing in this process could
ever execute — fails loudly rather than hanging a run forever.
"""
import json

from fakes import Message, Usage, answered, fetched, paused, searched, text_message, tool_call

from research_agent_batch_server_tools.task import (
    ACTIVE,
    DONE,
    FAILED,
    MAX_RETRIES,
    Task,
    make_custom_id,
)

URL = "https://learn.microsoft.com/en-us/copilot/limits"


def a_task(**kw) -> Task:
    defaults = dict(custom_id="p2-researcher-Q1", role="researcher",
                    model="claude-sonnet-5", system="s",
                    messages=[{"role": "user", "content": "research Q1"}],
                    max_continuations=2)
    return Task(**{**defaults, **kw})


# --- custom ids -----------------------------------------------------------

def test_a_custom_id_reads_like_a_log_line():
    assert make_custom_id("p3", "validator", "C001-a") == "p3-validator-C001-a"


def test_a_custom_id_survives_a_key_with_punctuation_in_it():
    assert "/" not in make_custom_id("p2", "researcher", "Q1/a b")


def test_a_custom_id_is_bounded():
    assert len(make_custom_id("p2", "researcher", "x" * 200)) <= 64


# --- the request ----------------------------------------------------------

def test_the_request_carries_the_grant_and_the_schema():
    task = a_task(tools=[{"type": "web_search_20260209", "name": "web_search"}],
                  output_config={"format": {"type": "json_schema", "schema": {}}})
    params = task.params()
    assert params["tools"][0]["name"] == "web_search"
    assert params["output_config"]["format"]["type"] == "json_schema"


def test_a_toolless_task_sends_no_tools_key_at_all():
    """Not an empty list: an agent that must not search should not depend on the
    API reading `tools: []` the way this repo means it."""
    assert "tools" not in a_task().params()


# --- the normal case: one request, done ------------------------------------

def test_a_turn_that_searched_fetched_and_answered_is_finished():
    """The whole point of the port. In the sibling this is three batches; here
    the searching and the fetching already happened inside this one response."""
    task = a_task()
    task.advance(answered('{"claims": []}',
                          searched("copilot limits", [URL]),
                          fetched(URL)))
    assert task.status == DONE
    assert task.parsed == {"claims": []}
    assert task.continuations == 0


def test_advancing_returns_what_the_server_tools_retrieved():
    task = a_task()
    found = task.advance(answered("{}", searched("q", [URL]), fetched(URL)))
    assert [r.tool for r in found] == ["web_search", "web_fetch"]


def test_usage_is_accumulated():
    task = a_task()
    task.advance(answered("{}"))
    assert task.input_tokens == 100 and task.output_tokens == 50


def test_searches_are_counted_for_the_bill():
    """They are billed per request on top of tokens, so a run that does not
    count them under-reports what it cost."""
    task = a_task()
    task.advance(answered("{}", searched("q", [URL]), web_searches=3))
    assert task.web_searches == 3
    assert task.cost_usd > 0.03


def test_a_toolless_task_has_no_search_bill():
    task = a_task(model="claude-haiku-4-5")
    task.advance(text_message("{}"))
    assert task.web_searches == 0


# --- pause_turn: the only continuation -------------------------------------

def test_a_paused_turn_stays_active():
    task = a_task()
    task.advance(paused(searched("q", [URL])))
    assert task.status == ACTIVE
    assert task.continuations == 1


def test_a_paused_turn_is_resubmitted_as_it_came_back():
    """Nothing is appended: there are no tool results to compute. The server
    continues from where the paused message stops."""
    task = a_task()
    task.advance(paused(fetched(URL)))
    messages = task.params()["messages"]
    assert messages[-1]["role"] == "assistant"
    assert [b["type"] for b in messages[-1]["content"]] == \
        ["server_tool_use", "web_fetch_tool_result"]


def test_a_paused_turn_keeps_the_pages_it_already_read():
    """Dropping the result blocks would ask the model to continue a turn whose
    research it can no longer see."""
    task = a_task()
    task.advance(paused(fetched(URL)))
    echoed = json.dumps(task.params()["messages"][-1])
    assert URL in echoed


def test_a_turn_that_will_not_stop_pausing_fails():
    task = a_task(max_continuations=2)
    for _ in range(3):
        task.advance(paused(fetched(URL)))
    assert task.status == FAILED
    assert "still paused" in task.error


def test_a_paused_turn_that_then_answers_is_done():
    task = a_task()
    task.advance(paused(searched("q", [URL])))
    task.advance(answered('{"claims": []}', fetched(URL)))
    assert task.status == DONE and task.continuations == 1


def test_retrievals_from_a_paused_turn_are_still_logged():
    """The pages were read. A run that only logged the final turn would lose the
    provenance for everything the paused one fetched."""
    task = a_task()
    found = task.advance(paused(fetched(URL)))
    assert [r.url for r in found] == [URL]


# --- failures -------------------------------------------------------------

def test_a_client_side_tool_call_fails_loudly():
    """Nothing in this process could execute one, so the turn would hang forever
    waiting for a result nobody will produce. Say so instead."""
    task = a_task()
    task.advance(tool_call("Bash", {"command": "ls"}))
    assert task.status == FAILED
    assert "server-side" in task.error


def test_a_refusal_ends_the_task():
    message = answered("", stop_reason="refusal")
    message.stop_details = type("D", (), {"category": "cyber"})()
    task = a_task()
    task.advance(message)
    assert task.status == FAILED and "cyber" in task.error


def test_a_truncated_turn_with_no_text_fails():
    task = a_task()
    task.advance(Message([], "max_tokens", Usage()))
    assert task.status == FAILED and "output tokens" in task.error


def test_an_unparseable_answer_fails_rather_than_writing_nothing():
    task = a_task()
    task.advance(text_message("I could not find anything useful."))
    assert task.status == FAILED and "readable JSON" in task.error


def test_json_is_recovered_from_a_turn_that_ended_some_other_way():
    """`output_config.format` makes the plain load the normal path; the brace
    scan is for the turn that ended on a ceiling with a usable object in it."""
    task = a_task()
    task.advance(text_message('Here you go:\n{"claims": []}\nhope that helps'))
    assert task.parsed == {"claims": []}


def test_a_json_array_is_not_an_answer():
    task = a_task()
    task.advance(text_message('[{"claims": []}]'))
    assert task.status == FAILED


# --- retries --------------------------------------------------------------

def test_a_dead_request_is_not_retried_forever():
    """A retry produces no result, so it cannot be bounded by the continuation
    ceiling and needs one of its own."""
    task = a_task()
    for _ in range(MAX_RETRIES):
        assert task.retry("expired")
    assert not task.retry("expired")
    assert task.status == FAILED and "gave up" in task.error


# --- persistence ----------------------------------------------------------

def test_a_task_round_trips_through_json():
    """A batch may take 24 hours, so a task has to survive the process."""
    task = a_task(tools=[{"type": "web_fetch_20250910", "name": "web_fetch",
                          "allowed_domains": ["learn.microsoft.com"]}])
    task.advance(paused(fetched(URL)))
    restored = Task.from_dict(json.loads(json.dumps(task.to_dict())))
    assert restored.continuations == 1
    assert restored.tools[0]["allowed_domains"] == ["learn.microsoft.com"]
    assert restored.messages == task.messages


def test_a_restored_task_can_still_advance():
    task = Task.from_dict(json.loads(json.dumps(a_task().to_dict())))
    task.advance(answered('{"claims": []}', fetched(URL)))
    assert task.status == DONE
