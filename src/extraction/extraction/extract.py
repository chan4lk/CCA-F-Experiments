"""The extraction call and its retry loop."""

from dataclasses import dataclass, field

import anthropic
import prompts
from dotenv import load_dotenv
from review import Decision, route
from schema import TOOLS, TOOLS_BY_NAME
from settings import MAX_ATTEMPTS, MAX_TOKENS, MODEL
from validate import Issue, retryable, validate

load_dotenv()


@dataclass
class Result:
    document_id: str
    tool_name: str | None
    record: dict | None
    issues: list[Issue] = field(default_factory=list)
    decision: Decision | None = None
    attempts: int = 0
    error: str | None = None


def tool_choice(doc_type: str | None):
    """Forced selection when the type is known: the enrichment steps downstream
    assume a particular shape, so the model must not pick. When it is unknown, "any"
    still guarantees a tool call - just not which one - and never conversational text."""
    if doc_type is None:
        return {"type": "any"}
    return {"type": "tool", "name": TOOLS_BY_NAME[f"extract_{doc_type}"]["name"]}


def _call(client, messages, choice):
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[{"type": "text", "text": prompts.SYSTEM, "cache_control": {"type": "ephemeral"}}],
        tools=TOOLS,
        tool_choice=choice,
        messages=messages,
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.name, block.input
    return None, None


def extract(
    document: str,
    doc_type: str | None = None,
    document_id: str = "doc",
    client=None,
    max_attempts: int = MAX_ATTEMPTS,
) -> Result:
    client = client or anthropic.Anthropic()
    choice = tool_choice(doc_type)
    messages = [{"role": "user", "content": document}]

    name, record, issues = None, None, []
    for attempt in range(1, max_attempts + 1):
        name, record = _call(client, messages, choice)
        if record is None:
            return Result(document_id, None, None, attempts=attempt, error="no tool_use block returned")

        issues = validate(record)
        fixable = retryable(issues)
        if not fixable:
            break

        # The retry is only worth a request while something in it is fixable; a
        # value absent from the source stays absent however many times we ask.
        if attempt < max_attempts:
            choice = {"type": "tool", "name": name}
            messages = [{"role": "user", "content": prompts.retry_prompt(document, record, [str(i) for i in fixable])}]

    return Result(
        document_id=document_id,
        tool_name=name,
        record=record,
        issues=issues,
        decision=route(record, issues),
        attempts=attempt,
    )
