"""web_fetch, executed here rather than on Anthropic's servers.

This is the part client-side tools buy you. Because this process performs every
retrieval, provenance is a direct observation rather than something recovered
from a hook, and a validator's reach can be pinned to a single host in code:
`allowed_domains` is not advice to the model, it is a check before the socket
opens.

It is also the part that makes this process the one holding the socket, which is
a responsibility the server-side port does not have. Two rules follow, and both
are enforced on **every hop** rather than once on the URL the model supplied:

**Redirects do not launder a destination.** The client does not follow redirects
itself. Each `Location` is resolved here and re-checked from the top, so a
redirect off a validator's pinned host is refused rather than followed — and the
page the model ends up reading is the page it was allowed to read.

**The private network is not the web.** The fetch URL is model-chosen, and the
model's choices come from pages it just read off the open web, so a prompt
injection on any of them is a path to `169.254.169.254` or `127.0.0.1`. Every
host is resolved and rejected unless every address it answers with is global.
"""
from __future__ import annotations

import io
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

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

# A redirect chain longer than this is a loop or a crawler trap, not a document.
MAX_REDIRECTS = 5

REDIRECT_CODES = {301, 302, 303, 307, 308}

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
    # The URL the body actually came from. Differs from `url` when a redirect
    # was followed, and the provenance log records both — a row naming only the
    # requested URL would say the run read a page it did not read.
    final_url: str = ""


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


# --- the private network is not the web -----------------------------------

def _resolve(host: str) -> list[str]:
    """Every address `host` answers with. Overridable so the guard is testable
    without a network and without a DNS server that agrees with the test."""
    return [str(info[4][0]) for info in socket.getaddrinfo(host, None)]


def host_is_public(host: str, resolve=None) -> bool:
    """True only when every address `host` resolves to is globally routable.

    Every address, not the first: a host that answers with one public address
    and one loopback address is a bypass, not a partial success.

    This is a resolve-then-connect check, so it does not close DNS rebinding —
    a name that answers differently on the second lookup can still move. That
    needs pinning the resolved address into the connection, which httpx2 does
    not expose here. It does close the reachable case: a model-chosen URL, or a
    redirect to one, naming a private or loopback destination outright.
    """
    resolve = resolve or _resolve
    if not host:
        return False
    try:
        addresses = resolve(host)
    except OSError:
        return False
    if not addresses:
        return False
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        # is_global is false for loopback, link-local (169.254.169.254 included),
        # RFC1918, multicast, reserved and unspecified addresses alike.
        if not ip.is_global:
            return False
    return True


def refusal_for(url: str, allowed: list[str] | None, resolve=None) -> str:
    """Why `url` may not be fetched, or "" when it may.

    Called once per hop rather than once per fetch. A redirect is a new
    destination and gets the same scrutiny as the one the model asked for.
    """
    if not url or not url.startswith(("http://", "https://")):
        return "url must be an http(s) URL"
    if not domain_allowed(url, allowed):
        return (f"{host_of(url)} is outside the domains you may fetch "
                f"({', '.join(allowed or []) or 'none'}). You were given one page to "
                f"read; fetch that page. Finding a different source is not your job.")
    if not host_is_public(host_of(url), resolve):
        return (f"{host_of(url)} is not a public internet host, so it will not be "
                f"retrieved. Private, loopback and link-local addresses are not "
                f"sources.")
    return ""


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
          client: Any = None, resolve=None) -> Fetched:
    """Retrieve one URL. Never raises: a failure is a result the model can act on.

    A tool that throws ends the agent's turn with an API error; a tool that
    returns "I could not read this" lets a validator rule NOT_FOUND, which is a
    correct and useful answer.

    Redirects are followed here rather than by the client, because the checks
    have to run *before* each hop is requested. Checking `response.history`
    afterwards would mean the request to the disallowed host had already been
    made, which for an internal address is the whole of the damage.
    """
    target = url
    for _ in range(MAX_REDIRECTS + 1):
        refusal = refusal_for(target, allowed_domains, resolve)
        if refusal:
            return Fetched(url, False, "", error=refusal)

        try:
            response = _get(target, client)
        except Exception as exc:  # noqa: BLE001 — network failure is a verdict, not a crash
            return Fetched(url, False, "",
                           error=f"could not retrieve: {type(exc).__name__}: {exc}")

        location = response.headers.get("location") if _is_redirect(response) else None
        if not location:
            return _read(url, target, response)
        target = urljoin(target, location)

    return Fetched(url, False, "", error=f"more than {MAX_REDIRECTS} redirects")


def _is_redirect(response) -> bool:
    return getattr(response, "status_code", 0) in REDIRECT_CODES


def _read(requested: str, final: str, response) -> Fetched:
    if response.status_code >= 400:
        return Fetched(requested, False, "", error=f"HTTP {response.status_code}",
                       final_url=final)

    content_type = (response.headers.get("content-type") or "").split(";")[0].strip()
    body = response.content[:MAX_FETCH_BYTES]

    try:
        if "pdf" in content_type or final.lower().endswith(".pdf"):
            text = pdf_to_text(body)
        else:
            text = html_to_text(body.decode("utf-8", errors="replace"))
    except ValueError as exc:
        return Fetched(requested, False, "", content_type, str(exc), final)

    if not text.strip():
        return Fetched(requested, False, "", content_type,
                       "the page returned no readable text", final)

    truncated = text[:MAX_TEXT_CHARS]
    if len(text) > MAX_TEXT_CHARS:
        truncated += f"\n\n[truncated at {MAX_TEXT_CHARS:,} characters]"
    return Fetched(requested, True, truncated, content_type, final_url=final)


def _get(url: str, client: Any):
    if client is not None:
        return client.get(url)
    # follow_redirects=False on purpose: see fetch(). The client must not reach a
    # host this module has not cleared.
    with httpx2.Client(follow_redirects=False, timeout=FETCH_TIMEOUT_SECONDS,
                       headers={"User-Agent": USER_AGENT}) as http:
        return http.get(url)
