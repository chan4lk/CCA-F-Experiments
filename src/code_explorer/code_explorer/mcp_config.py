"""MCP configuration.

Project-scoped servers are committed and everyone on the team gets them; personal or
experimental ones stay in user scope so a half-working server is not everyone's problem.
Credentials are referenced by environment variable, never written into the file.
"""

import json
import os
import re
from pathlib import Path

VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")

PROJECT_CONFIG = Path(".mcp.json")


def expand(value):
    """${GITHUB_TOKEN} in the committed file, the secret only in the environment."""
    if isinstance(value, str):
        return VAR.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v) for v in value]
    return value


def load(path: Path | None = None) -> dict:
    path = Path(path or PROJECT_CONFIG)
    if not path.exists():
        return {}
    return expand(json.loads(path.read_text())).get("mcpServers", {})


def missing_credentials(path: Path | None = None) -> list[str]:
    """A server whose token did not resolve costs its tools, not the run - but silently,
    which is worse than loudly. Name them at startup."""
    path = Path(path or PROJECT_CONFIG)
    if not path.exists():
        return []
    raw = path.read_text()
    return sorted({name for name in VAR.findall(raw) if not os.environ.get(name)})
