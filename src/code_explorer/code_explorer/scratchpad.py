"""Findings on disk, and a manifest the coordinator reloads.

Two different failures are handled here. Long sessions degrade - the model starts
answering from "typical patterns" rather than the specific classes it found in phase one -
and a scratchpad it re-reads is what pulls it back to what was actually observed. And a
crash loses everything held only in context, so state is exported as it is produced rather
than reconstructed afterwards.
"""

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from settings import MANIFEST, SCRATCHPAD, STALE_AFTER_SECONDS, WORKSPACE


@dataclass
class Finding:
    question: str
    answer: str
    locations: list[str] = field(default_factory=list)

    def render(self) -> str:
        where = "\n".join(f"  - `{loc}`" for loc in self.locations)
        return f"## {self.question}\n\n{self.answer}\n\n{where}".rstrip() + "\n"


@dataclass
class Manifest:
    goal: str
    session_id: str | None = None
    phase: str = "map"
    updated_at: float = 0.0
    files_seen: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)

    def stale(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.updated_at > STALE_AFTER_SECONDS


class Scratchpad:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or WORKSPACE)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def notes(self) -> Path:
        return self.root / SCRATCHPAD

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST

    def append(self, finding: Finding) -> None:
        with self.notes.open("a") as handle:
            handle.write(finding.render() + "\n")

    def read(self) -> str:
        return self.notes.read_text() if self.notes.exists() else ""

    def save(self, manifest: Manifest) -> None:
        manifest.updated_at = time.time()
        self.manifest_path.write_text(json.dumps(asdict(manifest), indent=2))

    def load(self) -> Manifest | None:
        if not self.manifest_path.exists():
            return None
        return Manifest(**json.loads(self.manifest_path.read_text()))

    def summary(self, manifest: Manifest) -> str:
        """The block injected when starting fresh instead of resuming. Findings first:
        an aggregated input is read most reliably at its beginning and end, so the
        conclusions go at the top and the detail below them."""
        lines = [f"# Investigation so far — {manifest.goal}", "", "## Established"]
        lines += [f"- {f['question']} → {f['answer']}" for f in manifest.findings] or ["- (nothing yet)"]
        lines += ["", "## Still open"]
        lines += [f"- {q}" for q in manifest.open_questions] or ["- (none)"]
        lines += ["", "## Files already read", ", ".join(f"`{f}`" for f in manifest.files_seen) or "(none)"]
        lines += ["", "## Detail", self.read()]
        return "\n".join(lines)
