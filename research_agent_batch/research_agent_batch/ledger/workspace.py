"""Shared workspace helpers for the proposal-research plugin.

Stdlib only: hooks run under bare `python3`, outside any project venv.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

CLAIM_ID_RE = re.compile(r"C\d{3,}")

VERDICTS = {
    "CONFIRMED",
    "CONTRADICTED",
    "NOT_FOUND",
    "MISLEADING",
    "INTERNAL_UNVERIFIED",
}
TIERS = {"material", "context"}
SOURCE_TYPES = {
    "vendor_doc",
    "regulator",
    "analyst",
    "blog",
    "forum",
    "internal",
}

MAX_QUOTE_WORDS = 50

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, hyphen-separated, <=60 chars, no leading/trailing hyphen."""
    s = _SLUG_STRIP.sub("-", text.lower()).strip("-")
    if len(s) <= 60:
        return s
    return s[:60].rstrip("-")


def normalize_url(url: str | None) -> str:
    """Compare URLs ignoring fragment and trailing slash.

    One implementation on purpose: the gate, the verdict CLI and the ingester all
    join on URLs, so if they ever normalised differently a claim could pass one
    and fail another for no visible reason.
    """
    if not url or not url.strip():
        return ""
    return url.strip().split("#", 1)[0].rstrip("/")


def iter_fence_state(text: str):
    """Yield ``(line, in_fence)`` for every line of markdown text.

    A ``` line toggles the state and is itself reported as inside the fence, so a
    caller that skips fenced lines drops the fence markers too. A plain toggle is
    the only correct reading of a fence: any attempt to infer the state from a
    block's shape fails open on a closing fence that stands alone.
    """
    in_fence = False
    for line in (text or "").splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            yield line, True
            continue
        yield line, in_fence


def workspace_root(cwd: Path, slug: str) -> Path:
    return Path(cwd) / "research" / slug


def ensure_workspace(root: Path) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def append_jsonl(path: Path, row: dict) -> None:
    """Atomically append one row to a JSONL file.

    Uses POSIX O_APPEND to ensure the write is atomic below PIPE_BUF, so concurrent
    appends from parallel processes never interleave.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def read_jsonl(path: Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}: malformed JSON at line {lineno}: {exc}") from exc
    return rows


def agent_role(agent_type: str | None) -> str:
    """The bare role from a hook payload's agent_type.

    Claude Code namespaces a plugin's agents, so the fetch log holds
    `proposal-research:validator`, not `validator`. Two checks compared against
    the bare string and were therefore dead for every one of the 531 retrievals
    in the first real run. Compare roles through this.
    """
    return (agent_type or "").rsplit(":", 1)[-1]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def active_runs_path(cwd: Path) -> Path:
    """Maps session_id -> slug, so hooks can find the run they belong to."""
    return Path(cwd) / "research" / ".active.json"


def _load_active(cwd: Path) -> dict:
    path = active_runs_path(cwd)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def set_active_run(cwd: Path, session_id: str, slug: str) -> None:
    path = active_runs_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_active(cwd)
    data[session_id] = slug
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_active_run(cwd: Path, session_id: str) -> str | None:
    return _load_active(cwd).get(session_id)
