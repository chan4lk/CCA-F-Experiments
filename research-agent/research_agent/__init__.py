"""proposal-research as a Claude Agent SDK application.

The Claude Code plugin this was ported from put an LLM in the orchestrator's
seat: a SKILL.md told the model to dispatch subagents, batch verdicts, and
respect the gate. That worked, but the orchestrator's own context became 65% of
the run's token cost, and three of the run's worst failure modes were failures
of instruction-following rather than of research.

Here the orchestrator is Python. It dispatches each agent as its own SDK query,
so agent identity is a value this process holds rather than something recovered
from a hook payload, and the gate is a function call rather than a rule the
model is asked to honour.
"""
from __future__ import annotations

__version__ = "0.1.0"
