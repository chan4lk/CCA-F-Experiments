"""Shared workspace helpers for the proposal-research plugin.

Stdlib only: hooks run under bare `python3`, outside any project venv.
"""
from __future__ import annotations

import json
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

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, hyphen-separated, <=60 chars, no leading/trailing hyphen."""
    s = _SLUG_STRIP.sub("-", text.lower()).strip("-")
    if len(s) <= 60:
        return s
    return s[:60].rstrip("-")


def workspace_root(cwd: Path, slug: str) -> Path:
    return Path(cwd) / "research" / slug


def ensure_workspace(root: Path) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def append_jsonl(path: Path, row: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


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


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
