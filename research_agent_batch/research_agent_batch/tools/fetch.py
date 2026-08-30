"""web_fetch, executed here rather than on Anthropic's servers.

This is the part client-side tools buy you. Because this process performs every
retrieval, provenance is a direct observation rather than something recovered
from a hook, and a validator's reach can be pinned to a single host in code:
`allowed_domains` is not advice to the model, it is a check before the socket
opens.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx2

from ..settings import FETCH_TIMEOUT_SECONDS, MAX_FETCH_BYTES, MAX_TEXT_CHARS

DEFINITION = {
    "name": "web_fetch",
    "description": (
        "Fetch one web page or PDF and return its text. Use this to read a page you "
        "found by searching, or the exact page you were told to verify."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The full http(s) URL to retrieve."},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}

USER_AGENT = "research-agent-batch/0.1 (+proposal research; contact via repo)"

_TAG = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_MARKUP = re.compile(r"<[^>]+>")
_BLANK = re.compile(r"\n{3,}")
_SPACE = re.compile(r"[ \t]{2,}")

_ENTITIES = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
             "&quot;": '"', "&#39;": "'", "&apos;": "'"}


@dataclass
class Fetched:
    url: str
    ok: bool
    text: str
    content_type: str = ""
    error: str = ""


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def domain_allowed(url: str, allowed: list[str] | None) -> bool:
    """True when `url`'s host is, or is a subdomain of, one of `allowed`.

    ``None`` means unrestricted. An empty list means nothing is allowed, which is
    a real state — not a synonym for unrestricted — so it is not folded in.
    """
    if allowed is None:
        return True
    host = host_of(url)
    return any(host == a.lower() or host.endswith("." + a.lower()) for a in allowed)


def html_to_text(html: str) -> str:
    text = _TAG.sub(" ", html)
    text = _MARKUP.sub(" ", text)
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    text = _SPACE.sub(" ", text)
    return _BLANK.sub("\n\n", text).strip()


def pdf_to_text(body: bytes) -> str:
    """Extract a PDF's text.

    57% of the claims in the plugin's first real run cited PDFs, and the Agent
    SDK's WebFetch cannot decode one — which is the whole reason its validator
    had to hold Bash. Doing the fetch here means a PDF is just bytes to parse,
    and the validator needs no shell at all.
    """
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - pypdf is a declared dependency
        return ""
    try:
        reader = PdfReader(io.BytesIO(body))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as exc:  # noqa: BLE001 — a malformed PDF is a fetch failure
        raise ValueError(f"could not read PDF: {exc}") from exc


def fetch(url: str, allowed_domains: list[str] | None = None,
          client: object | None = None) -> Fetched:
    """Retrieve one URL. Never raises: a failure is a result the model can act on.

    A tool that throws ends the agent's turn with an API error; a tool that
    returns "I could not read this" lets a validator rule NOT_FOUND, which is a
    correct and useful answer.
    """
    if not url or not url.startswith(("http://", "https://")):
        return Fetched(url, False, "", error="url must be an http(s) URL")

    if not domain_allowed(url, allowed_domains):
        return Fetched(url, False, "", error=(
            f"{host_of(url)} is outside the domains you may fetch "
            f"({', '.join(allowed_domains or []) or 'none'}). You were given one page to "
            f"read; fetch that page. Finding a different source is not your job."))

    try:
        response = _get(url, client)
    except Exception as exc:  # noqa: BLE001 — network failure is a verdict, not a crash
        return Fetched(url, False, "", error=f"could not retrieve: {type(exc).__name__}: {exc}")

    if response.status_code >= 400:
        return Fetched(url, False, "", error=f"HTTP {response.status_code}")

    content_type = (response.headers.get("content-type") or "").split(";")[0].strip()
    body = response.content[:MAX_FETCH_BYTES]

    try:
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            text = pdf_to_text(body)
        else:
            text = html_to_text(body.decode("utf-8", errors="replace"))
    except ValueError as exc:
        return Fetched(url, False, "", content_type, str(exc))

    if not text.strip():
        return Fetched(url, False, "", content_type,
                       "the page returned no readable text")

    truncated = text[:MAX_TEXT_CHARS]
    if len(text) > MAX_TEXT_CHARS:
        truncated += f"\n\n[truncated at {MAX_TEXT_CHARS:,} characters]"
    return Fetched(url, True, truncated, content_type)


def _get(url: str, client: object | None):
    if client is not None:
        return client.get(url)
    with httpx2.Client(follow_redirects=True, timeout=FETCH_TIMEOUT_SECONDS,
                       headers={"User-Agent": USER_AGENT}) as http:
        return http.get(url)
