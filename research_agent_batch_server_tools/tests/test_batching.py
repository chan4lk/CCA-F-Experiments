"""Submitting a wave and collecting what comes back.

Unchanged from `research_agent_batch`: a batch is a batch whether the tools
inside it run in this process or on Anthropic's servers.
"""
from fakes import FakeClient, text_message

from research_agent_batch_server_tools.batching import (
    Failure,
    collect,
    counts,
    has_ended,
    submit,
)
from research_agent_batch_server_tools.task import Task


def task(custom_id="a", status="active") -> Task:
    one = Task(custom_id=custom_id, role="validator", model="claude-haiku-4-5",
               system="s", messages=[{"role": "user", "content": "c"}],
               output_config={"format": {"type": "json_schema", "schema": {}}})
    one.status = status
    return one


def test_one_batch_carries_every_active_task():
    client = FakeClient(lambda *a: text_message("{}"))
    batch_id = submit(client, [task("a"), task("b")])
    assert batch_id.startswith("msgbatch_")
    assert [r["custom_id"] for r in client.batches.submitted[0]] == ["a", "b"]


def test_a_finished_task_is_not_resubmitted():
    """Resubmitting a done agent is a request that is paid for and discarded."""
    client = FakeClient(lambda *a: text_message("{}"))
    submit(client, [task("a"), task("b", status="done")])
    assert [r["custom_id"] for r in client.batches.submitted[0]] == ["a"]


def test_submitting_nothing_is_a_bug_not_an_empty_batch():
    client = FakeClient(lambda *a: text_message("{}"))
    try:
        submit(client, [task("a", status="done")])
    except ValueError as exc:
        assert "no active tasks" in str(exc)
    else:
        raise AssertionError("expected a ValueError")


def test_each_request_carries_its_tasks_params():
    client = FakeClient(lambda *a: text_message("{}"))
    submit(client, [task("a")])
    params = client.batches.submitted[0][0]["params"]
    assert params["model"] == "claude-haiku-4-5"
    assert params["output_config"]["format"]["type"] == "json_schema"


# --- collecting -----------------------------------------------------------

def test_successes_are_keyed_by_custom_id():
    client = FakeClient(lambda cid, p, r: text_message(f'{{"who":"{cid}"}}'))
    submit(client, [task("a"), task("b")])
    collected = collect(client, "msgbatch_01")
    assert set(collected.messages) == {"a", "b"}
    assert collected.failures == []


def test_one_bad_request_does_not_discard_the_rest():
    """A batch is a set of independent requests; ninety good validators must not
    be thrown away because one was malformed."""
    client = FakeClient(lambda cid, p, r: text_message("{}"),
                        fail={"b": ("invalid_request_error", "bad shape")})
    submit(client, [task("a"), task("b")])
    collected = collect(client, "msgbatch_01")
    assert set(collected.messages) == {"a"}
    assert [f.custom_id for f in collected.failures] == ["b"]
    assert collected.failures[0].error_type == "invalid_request_error"
    assert "bad shape" in collected.failures[0].message


# --- retryability ---------------------------------------------------------

def test_a_malformed_request_is_not_retryable():
    """It will fail identically however often it is resubmitted."""
    assert not Failure("a", "errored", "invalid_request_error").retryable


def test_an_auth_or_permission_failure_is_not_retryable():
    for error_type in ("authentication_error", "permission_error", "not_found_error"):
        assert not Failure("a", "errored", error_type).retryable, error_type


def test_a_server_error_is_retryable():
    assert Failure("a", "errored", "api_error").retryable
    assert Failure("a", "errored", "overloaded_error").retryable


def test_an_expired_or_canceled_request_is_retryable():
    """The request was fine as written; it just never ran."""
    assert Failure("a", "expired").retryable
    assert Failure("a", "canceled").retryable


# --- status ---------------------------------------------------------------

def test_ended_and_counts_read_the_batch():
    client = FakeClient(lambda *a: text_message("{}"), ends_after_polls=1)
    submit(client, [task("a")])
    first = client.messages.batches.retrieve("msgbatch_01")
    assert not has_ended(first)
    assert counts(first)["processing"] == 1
    assert has_ended(client.messages.batches.retrieve("msgbatch_01"))
