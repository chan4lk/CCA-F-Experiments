"""Invoking Claude Code non-interactively.

Each pass is a fresh process. That is the point: an instance that has just written or
just reviewed code carries the reasoning that produced it and is measurably worse at
questioning it than one that arrives with only the diff.
"""

import json
import subprocess

from dotenv import load_dotenv
from settings import ALLOWED_TOOLS, MAX_BUDGET_USD, MODEL, TIMEOUT_SECONDS

# Puts ANTHROPIC_API_KEY from .env into os.environ, which the `claude` subprocess
# inherits. In CI the key comes from the job env instead and this is a no-op.
load_dotenv()


class ReviewError(RuntimeError):
    pass


def build_command(system: str, schema: dict, model: str = MODEL, cwd_tools: list[str] | None = None) -> list[str]:
    """-p is what stops the CLI waiting on a tty and hanging the job. --output-format
    json wraps the run in an envelope with cost and session id; --json-schema constrains
    what lands in its `result`."""
    return [
        "claude",
        "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--append-system-prompt", system,
        "--allowed-tools", *(cwd_tools or ALLOWED_TOOLS),
        "--model", model,
        "--max-budget-usd", str(MAX_BUDGET_USD),
    ]


def parse_envelope(stdout: str) -> dict:
    """`result` is the schema-constrained payload; older CLI builds hand it back as a
    JSON string rather than an object, so both are accepted."""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ReviewError(f"CLI did not return JSON: {stdout[:200]}") from exc

    if envelope.get("is_error"):
        raise ReviewError(envelope.get("result") or "CLI reported an error")

    result = envelope.get("result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError as exc:
            raise ReviewError(f"result was not schema JSON: {result[:200]}") from exc
    if not isinstance(result, dict):
        raise ReviewError(f"unexpected result type: {type(result).__name__}")
    return result


def run(prompt: str, system: str, schema: dict, runner=subprocess.run, **kwargs) -> dict:
    command = build_command(system, schema, **kwargs)
    completed = runner(
        command,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise ReviewError(f"claude exited {completed.returncode}: {completed.stderr[:400]}")
    return parse_envelope(completed.stdout)
