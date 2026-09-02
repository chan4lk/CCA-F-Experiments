"""Prompt construction. Everything variable — prior findings, the existing test suite,
the diff — is passed in context; nothing is left for the model to go looking for."""

import json

from criteria import EXAMPLES, REPORT, SEVERITY, SKIP


def _block(title: str, body: str) -> str:
    return f"--- {title} ---\n{body}\n--- END {title} ---"


def _criteria() -> str:
    report = "\n".join(f"- {k}: {v}" for k, v in REPORT.items())
    skip = "\n".join(f"- {k}: {v}" for k, v in SKIP.items())
    severity = "\n".join(f"- {k}: {v}" for k, v in SEVERITY.items())
    examples = "\n\n".join(
        f"{e['verdict'].upper()}"
        + (f" as {e['category']}/{e['severity']}" if e["verdict"] == "report" else "")
        + f"\n{e['code']}\n-> {e['why']}"
        for e in EXAMPLES
    )
    return (
        f"REPORT a finding only in these categories:\n{report}\n\n"
        f"SKIP these entirely. They are not findings, and reporting them costs the "
        f"reviewer's trust in the categories above:\n{skip}\n\n"
        f"Severity:\n{severity}\n\n"
        f"Boundary cases:\n\n{examples}"
    )


SYSTEM = (
    "You review a pull request diff and return findings as structured output. You did not "
    "write this code and have no reasoning context from writing it - read what is there, "
    "not what it was probably meant to do.\n\n" + _criteria()
)


def file_pass(path: str, diff: str, source: str, prior: list[dict] | None = None) -> str:
    """One file, in isolation. A single prompt spanning twenty files dilutes attention
    across all of them and produces findings that contradict each other."""
    parts = [
        f"Review the changes to {path} for defects local to this file.",
        _block("DIFF", diff),
        _block("FILE AS IT NOW STANDS", source),
    ]
    if prior:
        parts.append(_prior(prior, path))
    parts.append(
        "Report only issues visible within this file. Cross-file consequences are covered "
        "by a separate pass - do not speculate about callers you cannot see."
    )
    return "\n\n".join(parts)


def integration_pass(diff: str, prior: list[dict] | None = None) -> str:
    """The pass the per-file passes structurally cannot do."""
    parts = [
        "Review this change set for defects that only exist ACROSS files.",
        _block("FULL DIFF", diff),
    ]
    if prior:
        parts.append(_prior(prior))
    parts.append(
        "Look for: a changed signature whose callers were not updated; a changed data shape "
        "consumed elsewhere; an invariant enforced in one file and assumed in another; a "
        "renamed or removed export still imported. Do not repeat single-file issues - "
        "another pass already covered those."
    )
    return "\n\n".join(parts)


def test_pass(path: str, source: str, existing_tests: str) -> str:
    """The existing suite goes in context, or the model proposes tests that already exist."""
    return "\n\n".join(
        [
            f"Propose tests for the uncovered failure modes in {path}.",
            _block("SOURCE", source),
            _block("EXISTING TESTS", existing_tests or "(none)"),
            (
                "Every proposal must name the branch the existing suite does not reach. If "
                "the existing suite already covers a behaviour, do not propose it again in "
                "different wording. Prefer one test that can fail over three that restate "
                "the happy path."
            ),
        ]
    )


def _prior(prior: list[dict], path: str | None = None) -> str:
    """Prior findings in context so a re-run after new commits reports only what is new or
    still unaddressed, instead of posting the same comment on every push."""
    relevant = [f for f in prior if path is None or f.get("file") == path]
    return _block(
        "ALREADY REPORTED ON THIS PR",
        json.dumps(relevant, indent=2) if relevant else "(none)",
    ) + (
        "\n\nDo not report any of the above again. If one has been fixed by this diff, say "
        "nothing about it. Report only new issues, or an already-reported issue whose "
        "severity this diff has raised."
    )
