"""The explore subagent.

Its whole purpose is to spend context that the coordinator then does not have to. Read-only
tools, cheap model, summary out.
"""

from claude_agent_sdk import AgentDefinition
from settings import SUBAGENT_MODEL

EXPLORE = AgentDefinition(
    description=(
        "Investigates ONE self-contained question about the codebase and returns a short "
        "summary with file:line references. Give it the full question and every constraint "
        "it needs — it cannot see this conversation. Use it for anything that means reading "
        "widely: finding all callers, tracing a data flow, locating a convention."
    ),
    prompt=(
        "You answer one question about a codebase by reading it. Grep for content, Glob for "
        "paths, Read only the files the search pointed at. Follow imports outward from the "
        "entry point rather than reading directories whole.\n\n"
        "Return under 300 words: the answer first, then the evidence as `path:line` "
        "references, then anything you could not determine. Never paste file contents, and "
        "never speculate past what you read — 'not found' is a valid answer."
    ),
    tools=["Read", "Grep", "Glob"],
    # No effort setting: Haiku 4.5 rejects it. The cheapness here comes from the model
    # and from the 300-word cap in the prompt, not from a knob.
    model=SUBAGENT_MODEL,
)

AGENTS = {"explore": EXPLORE}
