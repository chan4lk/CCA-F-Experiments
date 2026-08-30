"""Keep the suite off the network.

`fetch` resolves a host before it connects, so without this every test that
fetches would depend on DNS — and on `https://x/` happening not to exist. One
permissive resolver stands in for it; the tests that exercise the guard pass
their own `resolve` to `fetch()`, which takes precedence over this.
"""
from __future__ import annotations

import pytest

import research_agent_batch.tools.fetch as fetch_tool

# example.com. Public, so the guard lets it through.
PUBLIC_ADDRESS = "93.184.216.34"


@pytest.fixture(autouse=True)
def resolve_every_host_publicly(monkeypatch):
    monkeypatch.setattr(fetch_tool, "_resolve", lambda _host: [PUBLIC_ADDRESS])
