"""Deterministic Obsidian vault builder. Runs only after the gate passes."""
from __future__ import annotations

# Exported as `build_vault`, not `build`: re-exporting it as `build` would shadow
# the `research_agent.vault.build` module on the package, and `import
# research_agent.vault.build as m` would then bind the function instead.
from .build import build as build_vault
from .build import check_links

__all__ = ["build_vault", "check_links"]
