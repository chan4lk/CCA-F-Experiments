"""proposal-research on the Message Batches API.

A sibling of `research-agent/`, which runs the same six-agent pipeline on the
Claude Agent SDK. The pipeline, the ledgers and the gate are identical; what
changes is the engine underneath, and the trade is a real one.

The Agent SDK gives you an agent loop and built-in tools, and runs a turn in
seconds. The Batches API gives you neither loop nor tools, and a turn takes as
long as the batch does — but it costs half as much, and every request in a wave
runs at once rather than eight at a time.

So the loop is rebuilt here: each round is one batch holding every agent's next
turn, tool calls come back to this process to execute, and the results go into
the next round's batch. Nine researchers taking six turns each is six batches,
not fifty-four requests.
"""
from __future__ import annotations

__version__ = "0.1.0"
