"""The six agents, as SDK AgentDefinitions.

In the plugin each of these was a markdown file with YAML frontmatter that
Claude Code parsed. Here the prompt body still lives in its own file — prompts
are prose and belong in prose files — but the frontmatter becomes real Python:
the tool grant is a list the SDK enforces, not a line a reader has to trust.

The grants are the load-bearing part. Two of this pipeline's guarantees are
properties of what an agent *cannot* do:

- the synthesizer and the proposal-writer have no web tools, so neither can
  introduce a fact that is not already in the ledger;
- the validator has no Read, no Grep, no Glob and no WebSearch, so it cannot
  reach the researcher's quote or shop for a friendlier source.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from claude_agent_sdk import AgentDefinition

from .settings import available_tools, model_for

PROMPTS = Path(__file__).resolve().parent / "prompts"

# The in-process ledger server (research_agent.tools). Named here rather than
# inline so the researcher's grant reads the same way as every other one.
LEDGER_SERVER = "ledger"
ADD_CLAIM_TOOL = f"mcp__{LEDGER_SERVER}__add_claim"


@dataclass(frozen=True)
class Role:
    """One agent: what it is for, what it may touch, and which model runs it."""

    name: str
    description: str
    tools: tuple[str, ...]
    model_key: str = ""
    writes: tuple[str, ...] = ()
    """Workspace files this role is expected to produce. Documentation, and the
    orchestrator's post-condition check — a phase that produced no file failed,
    however cheerful the agent's final message was."""

    max_turns: int = 30
    """Turn ceiling for one dispatch. A researcher that has not finished in 40
    turns is looping, not researching, and every extra turn re-reads everything
    it has already read."""

    @property
    def model(self) -> str:
        return model_for(self.model_key or self.name)

    @lru_cache(maxsize=None)  # noqa: B019 — Role is frozen; the cache is per-role
    def prompt(self) -> str:
        return (PROMPTS / f"{self.name}.md").read_text(encoding="utf-8")

    def definition(self, servers: dict[str, Any] | None = None) -> AgentDefinition:
        """An SDK AgentDefinition with MCP tools filtered to configured servers."""
        return AgentDefinition(
            description=self.description,
            prompt=self.prompt(),
            tools=list(available_tools(list(self.tools), servers)),
            model=self.model,
        )


PLANNER = Role(
    max_turns=12,
    name="planner",
    description=(
        "Decomposes a proposal research question into independent, self-contained "
        "sub-questions, each tagged material or context. Cannot search."
    ),
    tools=("Read", "Write"),
    writes=("plan.md",),
)

RESEARCHER = Role(
    max_turns=40,
    name="researcher",
    description=(
        "Researches one self-contained sub-question and appends verbatim-quoted claims "
        "to the ledger. Never paraphrases."
    ),
    # No Bash and no Write. The plugin's researcher held Bash only to shell out to
    # add_claim.py; the in-process tool replaced that, and dropping Bash closed the
    # `curl` provenance hole with it — a run once lost 17 claims to pages read with
    # curl, which the retrieval recorder cannot see.
    tools=(
        "WebSearch",
        "WebFetch",
        ADD_CLAIM_TOOL,
        "mcp__microsoft_docs_mcp__microsoft_docs_search",
        "mcp__microsoft_docs_mcp__microsoft_docs_fetch",
        "mcp__headroom__headroom_compress",
    ),
)

VALIDATOR = Role(
    max_turns=10,
    name="validator",
    description=(
        "Independently verifies one claim against its cited URL. Blind by construction — "
        "sees only the claim and the URL, cannot read the ledger, cannot search."
    ),
    # Bash is here because 57% of the claims in the first real run cited PDFs and
    # WebFetch cannot decode a PDF binary. validator_guard blocks that Bash from
    # reaching the workspace; see hooks.py.
    tools=("WebFetch", "Bash", "mcp__microsoft_docs_mcp__microsoft_docs_fetch"),
)

GAP_HUNTER = Role(
    max_turns=20,
    name="gap-hunter",
    description=(
        "Reads the confirmed claim set and names what a domain expert would expect to "
        "see and does not. Emits new sub-questions."
    ),
    tools=("Read", "WebSearch", "Write"),
    writes=("gaps.md",),
)

SYNTHESIZER = Role(
    max_turns=25,
    name="synthesizer",
    description=(
        "Writes the evidence pack from confirmed claims only. Has no web tools and "
        "cannot introduce a fact absent from the ledger."
    ),
    tools=("Read", "Write"),
    writes=("evidence-pack.md",),
)

PROPOSAL_WRITER = Role(
    max_turns=25,
    name="proposal-writer",
    description=(
        "Drafts the client-facing proposal from the human-approved evidence pack only. "
        "No web tools, no ledger access beyond the pack."
    ),
    tools=("Read", "Write"),
    writes=("proposal.md",),
)

ROLES: dict[str, Role] = {
    role.name: role
    for role in (PLANNER, RESEARCHER, VALIDATOR, GAP_HUNTER, SYNTHESIZER, PROPOSAL_WRITER)
}


def agent_definitions(servers: dict[str, Any] | None = None) -> dict[str, AgentDefinition]:
    """All six as an ``agents=`` mapping.

    The programmatic orchestrator dispatches each role as its own query and does
    not need this. It exists so the same six agents can be handed to a single
    coordinator session — ``ClaudeAgentOptions(agents=agent_definitions())`` —
    without redefining them.
    """
    return {name: role.definition(servers) for name, role in ROLES.items()}
