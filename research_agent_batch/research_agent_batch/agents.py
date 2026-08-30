"""The six agents, as batch request templates.

`research-agent` expresses these as SDK AgentDefinitions, where the tool grant
is a list the harness enforces. Here the grant is a `tools` array on a Messages
request — and it is enforced twice over, because this process is what executes
the tools. An agent not given `web_search` has no way to search, and even if it
asked for one by name the dispatcher has nothing to run.

Two roles have no tools at all. The synthesizer and the proposal-writer see only
the ledger rows and the pack the orchestrator inlines into their prompt, which is
a stronger version of the guarantee the SDK port makes with an empty tool list:
they cannot introduce a fact that is not in front of them.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import schemas
from .settings import MAX_ROUNDS, model_for
from .tools import WEB_FETCH, WEB_SEARCH

PROMPTS = Path(__file__).resolve().parent / "prompts"


@dataclass(frozen=True)
class Role:
    """One agent: what it is for, what it may run, and what it must return."""

    name: str
    description: str
    tools: tuple[dict[str, Any], ...]
    output_config: dict[str, Any]
    model_key: str = ""

    @property
    def model(self) -> str:
        return model_for(self.model_key or self.name)

    @property
    def max_rounds(self) -> int:
        """Turn ceiling. Each round is one batch, so this caps wall-clock too."""
        return MAX_ROUNDS[self.name]

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(t["name"] for t in self.tools)

    def prompt(self) -> str:
        return _prompt(self.name)


@lru_cache(maxsize=None)
def _prompt(name: str) -> str:
    """Cached by name rather than by Role.

    A Role carries its `tools` array and its output schema, which are dicts, so
    the Role itself is unhashable and cannot key a cache.
    """
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


PLANNER = Role(
    name="planner",
    description="Decomposes a proposal research question into independent, self-contained "
                "sub-questions, each tagged material or context. Cannot search.",
    tools=(),
    output_config=schemas.PLAN,
)

RESEARCHER = Role(
    name="researcher",
    description="Researches one self-contained sub-question and reports verbatim-quoted "
                "claims. Never paraphrases.",
    tools=(WEB_SEARCH, WEB_FETCH),
    output_config=schemas.CLAIMS,
)

VALIDATOR = Role(
    name="validator",
    description="Independently verifies one claim against its cited URL. Blind by "
                "construction — sees only the claim and the URL, and can fetch only that "
                "page's host.",
    # No web_search, by design: searching is how a validator finds a friendlier
    # source than the one it was asked about. Its fetch is additionally pinned to
    # the cited URL's domain when the request is built.
    tools=(WEB_FETCH,),
    output_config=schemas.VERDICT,
)

GAP_HUNTER = Role(
    name="gap-hunter",
    description="Reads the confirmed claim set and names what a domain expert would "
                "expect to see and does not. Emits new sub-questions.",
    # Search but not fetch: it establishes that material on a topic exists and
    # stops there. Reading the page would be doing the researcher's job.
    tools=(WEB_SEARCH,),
    output_config=schemas.GAPS,
)

SYNTHESIZER = Role(
    name="synthesizer",
    description="Writes the evidence pack from confirmed claims only. Has no tools and "
                "cannot introduce a fact absent from the ledger.",
    tools=(),
    output_config=schemas.PACK,
)

PROPOSAL_WRITER = Role(
    name="proposal-writer",
    description="Drafts the client-facing proposal from the human-approved evidence pack "
                "only. No tools, no ledger access beyond the pack.",
    tools=(),
    output_config=schemas.PACK,
)

ROLES: dict[str, Role] = {
    role.name: role
    for role in (PLANNER, RESEARCHER, VALIDATOR, GAP_HUNTER, SYNTHESIZER, PROPOSAL_WRITER)
}
