"""Resume, fork, or start fresh.

Resuming is cheap and keeps everything. It is also wrong whenever the prior tool results
describe a repo that has since changed: the session is then reasoning over a snapshot,
confidently. Starting fresh with an injected summary costs the detail and keeps the
conclusions, which is the right trade once the snapshot is stale.
"""

from dataclasses import dataclass

from claude_agent_sdk import fork_session, get_session_info, list_sessions
from scratchpad import Manifest

RESUME = "resume"
RESUME_WITH_CHANGES = "resume_with_changes"
FRESH = "fresh"


@dataclass
class Plan:
    action: str
    session_id: str | None
    reason: str
    changed_files: list[str]

    @property
    def resuming(self) -> bool:
        return self.action != FRESH


def decide(manifest: Manifest | None, changed_files: list[str] | None = None, now: float | None = None) -> Plan:
    changed = changed_files or []

    if manifest is None or not manifest.session_id:
        return Plan(FRESH, None, "no prior session recorded", changed)

    if manifest.stale(now):
        return Plan(FRESH, None, "prior tool results are older than the staleness window", changed)

    touched = sorted(set(changed) & set(manifest.files_seen))
    if touched:
        # Resuming without saying what moved leaves the model answering from a file
        # state that no longer exists. It resumes, but it is told.
        return Plan(
            RESUME_WITH_CHANGES,
            manifest.session_id,
            f"{len(touched)} previously-analysed file(s) changed",
            touched,
        )

    return Plan(RESUME, manifest.session_id, "prior context is still valid", changed)


def change_notice(paths: list[str]) -> str:
    listed = "\n".join(f"- `{p}`" for p in paths)
    return (
        "These files have changed since you last read them:\n"
        f"{listed}\n\n"
        "Re-read only these before continuing. Everything else you established still "
        "holds — do not re-explore the repository."
    )


def branch(session_id: str, title: str, directory: str | None = None) -> str:
    """One analysis baseline, two branches. Comparing two refactors by running them in
    sequence costs the mapping phase twice and lets the first colour the second."""
    return fork_session(session_id, directory=directory, title=title).session_id


def find(title: str, directory: str | None = None):
    for info in list_sessions(directory=directory):
        if info.get("custom_title") == title:
            return info
    return None


def info(session_id: str, directory: str | None = None):
    return get_session_info(session_id, directory=directory)
