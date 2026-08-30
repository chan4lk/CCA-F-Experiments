"""The run state on disk, which is what makes a 24-hour batch survivable."""
import json

import pytest

from research_agent_batch import state as st
from research_agent_batch.conversation import Conversation


def a_state(tmp_path, **kw) -> st.RunState:
    defaults = dict(slug="run-a", workspace=str(tmp_path),
                    intake=st.Intake(question="q", client="Acme"))
    return st.RunState(**{**defaults, **kw})


def test_a_run_round_trips_through_the_file(tmp_path):
    run = a_state(tmp_path, phase=st.VALIDATE, batch_id="msgbatch_07", gap_round=1)
    run.conversations = [Conversation(
        custom_id="p3-validator-C001-a", role="validator", model="claude-haiku-4-5",
        system="s", messages=[{"role": "user", "content": "claim"}],
        allowed_domains=["learn.microsoft.com"], key="C001")]
    run.history = [st.Submission("plan", "msgbatch_01", 1, "2026-08-30T10:00:00Z",
                                 "2026-08-30T10:40:00Z")]
    run.save()

    loaded = st.RunState.load(tmp_path)
    assert loaded.phase == st.VALIDATE and loaded.batch_id == "msgbatch_07"
    assert loaded.gap_round == 1
    assert loaded.intake.client == "Acme"
    assert loaded.conversations[0].allowed_domains == ["learn.microsoft.com"]
    assert loaded.history[0].batch_id == "msgbatch_01"


def test_a_missing_state_file_says_so(tmp_path):
    with pytest.raises(FileNotFoundError, match="no run state"):
        st.RunState.load(tmp_path)


def test_a_state_file_from_another_version_is_refused(tmp_path):
    """Silently misreading a run's phase would resubmit a wave that already ran."""
    (tmp_path / st.STATE_FILE).write_text(json.dumps({"version": 99}))
    with pytest.raises(ValueError, match="version 99"):
        st.RunState.load(tmp_path)


def test_the_write_is_atomic(tmp_path):
    """A torn state file is worse than a stale one: it loses the run."""
    run = a_state(tmp_path)
    run.save()
    run.save()
    assert not list(tmp_path.glob("*.tmp"))
    assert json.loads(run.path.read_text())["version"] == st.VERSION


def test_exists_does_not_need_the_file_parsed(tmp_path):
    assert not st.RunState.exists(tmp_path)
    a_state(tmp_path).save()
    assert st.RunState.exists(tmp_path)


# --- id blocks ------------------------------------------------------------

def test_id_blocks_are_handed_out_once(tmp_path):
    """A second research round reusing the first round's ids would collide in
    the ledger, and add_claim would reject the later ones as duplicates."""
    run = a_state(tmp_path)
    assert run.take_id_block() == 0
    assert run.take_id_block(2) == 1
    assert run.next_id_block == 3


def test_the_id_cursor_survives_a_reload(tmp_path):
    run = a_state(tmp_path)
    run.take_id_block(3)
    run.save()
    assert st.RunState.load(tmp_path).take_id_block() == 3


# --- retiring a phase -----------------------------------------------------

def test_retiring_clears_the_conversations(tmp_path):
    """Otherwise the state file grows a full transcript of every agent that has
    ever run, and it is rewritten on every tick."""
    run = a_state(tmp_path)
    run.conversations = [Conversation(custom_id="a", role="planner", model="claude-sonnet-5",
                                      system="s", messages=[])]
    run.retire()
    assert run.conversations == []


def test_retiring_banks_what_the_phase_spent(tmp_path):
    """The money has to survive the clearing, or the run's total silently resets
    at every phase boundary."""
    run = a_state(tmp_path)
    conv = Conversation(custom_id="a", role="planner", model="claude-sonnet-5",
                        system="s", messages=[])
    conv.input_tokens, conv.output_tokens = 1_000_000, 0
    run.conversations = [conv]
    spent = conv.cost_usd
    run.retire()
    assert run.cost_usd == pytest.approx(spent)
    assert spent == 1.0, "sonnet input is $2/MTok, halved for batch"


def test_cost_accumulates_across_several_phases(tmp_path):
    run = a_state(tmp_path)
    for _ in range(3):
        conv = Conversation(custom_id="a", role="planner", model="claude-sonnet-5",
                            system="s", messages=[])
        conv.input_tokens = 1_000_000
        run.conversations = [conv]
        run.retire()
    assert run.cost_usd == pytest.approx(3.0)


# --- queries --------------------------------------------------------------

def test_active_done_and_failed_partition_the_wave(tmp_path):
    run = a_state(tmp_path)
    statuses = ["active", "done", "failed", "done"]
    run.conversations = []
    for index, status in enumerate(statuses):
        conv = Conversation(custom_id=f"c{index}", role="validator",
                            model="claude-haiku-4-5", system="s", messages=[])
        conv.status = status
        run.conversations.append(conv)
    assert len(run.active) == 1 and len(run.done) == 2 and len(run.failed) == 1


def test_the_intake_brief_omits_what_was_not_given(tmp_path):
    assert st.Intake(question="q").brief() == "Question: q"
    assert "Client" in st.Intake(question="q", client="Acme").brief()


def test_banked_cost_survives_a_resume(tmp_path):
    """The bug this replaces: retired cost lived on an attribute save() never
    wrote, so a run's total silently reset to zero on the first resume — and the
    phases that already ran are most of a finished run's bill."""
    run = a_state(tmp_path)
    conv = Conversation(custom_id="a", role="planner", model="claude-sonnet-5",
                        system="s", messages=[])
    conv.input_tokens = 1_000_000
    run.conversations = [conv]
    run.retire()
    run.save()

    assert st.RunState.load(tmp_path).cost_usd == pytest.approx(run.cost_usd) == 1.0


def test_cost_counts_the_wave_in_flight_as_well_as_retired_ones(tmp_path):
    run = a_state(tmp_path)
    first = Conversation(custom_id="a", role="planner", model="claude-sonnet-5",
                         system="s", messages=[])
    first.input_tokens = 1_000_000
    run.conversations = [first]
    run.retire()

    second = Conversation(custom_id="b", role="planner", model="claude-sonnet-5",
                          system="s", messages=[])
    second.input_tokens = 1_000_000
    run.conversations = [second]
    assert run.cost_usd == pytest.approx(2.0)
