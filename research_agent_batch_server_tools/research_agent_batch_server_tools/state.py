"""The run's state on disk, so a run can outlive the process that started it.

A batch may take 24 hours. Holding a Python process open for that is not a plan,
so everything needed to continue lives in `batch-state.json` in the workspace:
which phase the run is in, which batch it is waiting on, and every agent's
request mid-flight.

That makes `resume` the normal way to advance a run, and `--wait` a convenience
that just calls it in a loop.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .task import Task

STATE_FILE = "batch-state.json"
VERSION = 1

# The phase machine. Batch phases submit a wave and wait; local phases run here
# and fall straight through to the next one.
PLAN = "plan"
RESEARCH = "research"
VALIDATE = "validate"
ESCALATE = "escalate"
GAPS = "gaps"
SYNTHESIZE = "synthesize"
GATE = "gate"
AWAITING_APPROVAL = "awaiting-approval"
DRAFT = "draft"
DONE = "done"

LOCAL_PHASES = {GATE}
TERMINAL = {AWAITING_APPROVAL, DONE}


@dataclass
class Intake:
    """Phase 0. What the plugin asked for with AskUserQuestion."""

    question: str
    client: str = ""
    audience: str = ""
    constraints: str = ""
    context_paths: list[str] = field(default_factory=list)
    prior_paths: list[str] = field(default_factory=list)

    def brief(self) -> str:
        lines = [f"Question: {self.question}"]
        for label, value in (("Client / prospect", self.client),
                             ("Audience", self.audience),
                             ("Hard constraints", self.constraints)):
            if value:
                lines.append(f"{label}: {value}")
        return "\n".join(lines)


@dataclass
class Submission:
    """One batch this run has sent, kept for `status` and for the cost report."""

    phase: str
    batch_id: str
    requests: int
    submitted_at: str
    ended_at: str = ""


@dataclass
class RunState:
    slug: str
    workspace: str
    intake: Intake
    phase: str = PLAN
    batch_id: str | None = None
    tasks: list[Task] = field(default_factory=list)
    history: list[Submission] = field(default_factory=list)
    # Claim-id blocks are handed out from here so a second research round cannot
    # collide with the first one's ids.
    next_id_block: int = 0
    gap_round: int = 0
    max_gap_rounds: int = 2
    subject: str = ""
    # What finished phases spent, banked when their tasks are cleared.
    retired: list[dict] = field(default_factory=list)
    version: int = VERSION

    # --- persistence -------------------------------------------------------

    @property
    def path(self) -> Path:
        return Path(self.workspace) / STATE_FILE

    def save(self) -> None:
        """Written whole, every time. The file is small and a torn one is worse
        than a stale one."""
        payload = {
            "version": self.version,
            "slug": self.slug,
            "workspace": self.workspace,
            "intake": asdict(self.intake),
            "phase": self.phase,
            "batch_id": self.batch_id,
            "tasks": [c.to_dict() for c in self.tasks],
            "history": [asdict(s) for s in self.history],
            "next_id_block": self.next_id_block,
            "gap_round": self.gap_round,
            "max_gap_rounds": self.max_gap_rounds,
            "subject": self.subject,
            "retired": self.retired,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @classmethod
    def load(cls, workspace: Path) -> "RunState":
        path = Path(workspace) / STATE_FILE
        if not path.is_file():
            raise FileNotFoundError(f"no run state at {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != VERSION:
            raise ValueError(
                f"{path} was written by version {data.get('version')}, this is {VERSION}")
        return cls(
            slug=data["slug"],
            workspace=data["workspace"],
            intake=Intake(**data["intake"]),
            phase=data["phase"],
            batch_id=data.get("batch_id"),
            tasks=[Task.from_dict(c) for c in data.get("tasks", [])],
            history=[Submission(**s) for s in data.get("history", [])],
            next_id_block=data.get("next_id_block", 0),
            gap_round=data.get("gap_round", 0),
            max_gap_rounds=data.get("max_gap_rounds", 2),
            subject=data.get("subject", ""),
            retired=data.get("retired", []),
        )

    @classmethod
    def exists(cls, workspace: Path) -> bool:
        return (Path(workspace) / STATE_FILE).is_file()

    # --- queries -----------------------------------------------------------

    @property
    def active(self) -> list[Task]:
        return [c for c in self.tasks if c.active]

    @property
    def done(self) -> list[Task]:
        return [c for c in self.tasks if c.status == "done"]

    @property
    def failed(self) -> list[Task]:
        return [c for c in self.tasks if c.status == "failed"]

    @property
    def cost_usd(self) -> float:
        """What the batches have cost so far, at batch rates.

        Sums the wave in flight plus every retired one, so the figure survives a
        resume — the phases that already ran are most of a finished run's bill.
        """
        return (sum(c.cost_usd for c in self.tasks)
                + sum(r.get("cost_usd", 0.0) for r in self.retired))

    def take_id_block(self, count: int = 1) -> int:
        """Reserve `count` consecutive claim-id blocks and return the first."""
        first = self.next_id_block
        self.next_id_block += count
        return first

    def retire(self, extra: list[dict[str, Any]] | None = None) -> None:
        """Bank the finished wave's cost, then clear it.

        Tasks are cleared between phases so the state file does not grow a full
        transcript of every agent that has ever run — and here a transcript
        includes every page that agent fetched, which is most of its bulk. The
        money they spent has to survive, or the run's total silently resets each
        phase.
        """
        self.retired += [
            {"role": c.role, "model": c.model, "cost_usd": c.cost_usd,
             "input_tokens": c.input_tokens, "output_tokens": c.output_tokens,
             "web_searches": c.web_searches, "continuations": c.continuations,
             "status": c.status}
            for c in self.tasks]
        self.retired += extra or []
        self.tasks = []
