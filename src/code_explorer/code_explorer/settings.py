import os
from pathlib import Path

MODEL = os.environ.get("EXPLORER_MODEL", "claude-haiku-4-5")
SUBAGENT_MODEL = os.environ.get("EXPLORER_SUBAGENT_MODEL", "claude-haiku-4-5")

MAX_BUDGET_USD = float(os.environ.get("EXPLORER_BUDGET_USD", "2.00"))

# Written to disk, not held in context. Context is the thing that runs out.
WORKSPACE = Path(os.environ.get("EXPLORER_WORKSPACE", ".explorer"))
SCRATCHPAD = "findings.md"
MANIFEST = "manifest.json"

# A session's own tool results go stale as soon as the files change. Past this, resuming
# means reasoning over a snapshot of a repo that no longer exists.
STALE_AFTER_SECONDS = int(os.environ.get("EXPLORER_STALE_AFTER", str(24 * 3600)))
