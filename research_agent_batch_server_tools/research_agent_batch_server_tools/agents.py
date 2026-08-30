"""The six agents, as batch request templates.

`research-agent` expresses these as SDK AgentDefinitions, where the tool grant
is a list the harness enforces. `research_agent_batch` expresses them as custom
tools it executes itself. Here a grant is a list of *server* tools, so it is
enforced by the API: an agent not given `web_search` cannot search, and there is
no dispatcher in this repo that could be talked into running one for it.

A Role names the tools it may hold; the definitions are built per request,
because two things about them are not known until then. The tool type variant
depends on the **model** — the validator's haiku takes the basic tools, the
researcher's sonnet takes the dynamic-filtering ones. And `allowed_domains`
depends on the **claim** — a validator is pinned to the host of the one page it
was asked about, which is not known until that claim exists.

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

from . import schemas, servertools
from .settings import MAX_CONTINUATIONS, max_uses, model_for

PROMPTS = Path(__file__).resolve().parent / "prompts"

BUILDERS = {"web_search": servertools.web_search, "web_fetch": servertools.web_fetch}


@dataclass(frozen=True)
class Role:
    """One agent: what it is for, what it may run, and what it must return."""

    name: str
    description: str
    tool_names: tuple[str, ...]
    output_config: dict[str, Any]
    model_key: str = ""

    @property
    def model(self) -> str:
        return model_for(self.model_key or self.name)

    @property
    def max_continuations(self) -> int:
        """Resubmissions allowed for a `pause_turn`. See settings.py."""
        return MAX_CONTINUATIONS[self.name]

    def tools(self, model: str = "",
              allowed_domains: list[str] | None = None) -> list[dict[str, Any]]:
        """This role's grant, for one request.

        A role with no tools returns an empty list rather than omitting the key
        for the caller to remember — an agent that must not search should not
        depend on someone else not passing `tools`.
        """
        model = model or self.model
        return [
            BUILDERS[name](model,
                           max_uses=max_uses(self.name, name),
                           allowed_domains=allowed_domains)
            for name in self.tool_names
        ]

    def prompt(self) -> str:
        return _prompt(self.name)


@lru_cache(maxsize=None)
def _prompt(name: str) -> str:
    """Cached by name rather than by Role.

    A Role carries its output schema, which is a dict, so the Role itself is
    unhashable and cannot key a cache.
    """
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


PLANNER = Role(
    name="planner",
    description="Decomposes a proposal research question into independent, self-contained "
                "sub-questions, each tagged material or context. Cannot search.",
    tool_names=(),
    output_config=schemas.PLAN,
)

RESEARCHER = Role(
    name="researcher",
    description="Researches one self-contained sub-question and reports verbatim-quoted "
                "claims. Never paraphrases.",
    tool_names=("web_search", "web_fetch"),
    output_config=schemas.CLAIMS,
)

VALIDATOR = Role(
    name="validator",
    description="Independently verifies one claim against its cited URL. Blind by "
                "construction — sees only the claim and the URL, and can fetch only that "
                "page's host.",
    # No web_search, by design: searching is how a validator finds a friendlier
    # source than the one it was asked about. Its fetch is additionally pinned to
    # the cited URL's domain when the request is built, which the API enforces.
    tool_names=("web_fetch",),
    output_config=schemas.VERDICT,
)

GAP_HUNTER = Role(
    name="gap-hunter",
    description="Reads the confirmed claim set and names what a domain expert would "
                "expect to see and does not. Emits new sub-questions.",
    # Search but not fetch: it establishes that material on a topic exists and
    # stops there. Reading the page would be doing the researcher's job.
    tool_names=("web_search",),
    output_config=schemas.GAPS,
)

SYNTHESIZER = Role(
    name="synthesizer",
    description="Writes the evidence pack from confirmed claims only. Has no tools and "
                "cannot introduce a fact absent from the ledger.",
    tool_names=(),
    output_config=schemas.PACK,
)

PROPOSAL_WRITER = Role(
    name="proposal-writer",
    description="Drafts the client-facing proposal from the human-approved evidence pack "
                "only. No tools, no ledger access beyond the pack.",
    tool_names=(),
    output_config=schemas.PACK,
)

ROLES: dict[str, Role] = {
    role.name: role
    for role in (PLANNER, RESEARCHER, VALIDATOR, GAP_HUNTER, SYNTHESIZER, PROPOSAL_WRITER)
}
