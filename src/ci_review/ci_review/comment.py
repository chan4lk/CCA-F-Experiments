"""Rendering findings for `gh api` inline review comments."""

ICON = {"blocking": "🛑", "important": "⚠️", "minor": "💬"}


def body(finding: dict) -> str:
    return (
        f"{ICON.get(finding['severity'], '💬')} **{finding['severity']}** · `{finding['category']}`\n\n"
        f"{finding['issue']}\n\n"
        f"**Fails on:** {finding['failure_input']}\n\n"
        f"**Suggested fix:** {finding['suggested_fix']}\n\n"
        f"<sub>pattern: `{finding['detected_pattern']}` — "
        f"reply `not-an-issue` to record a dismissal</sub>"
    )


def review_payload(findings: list[dict], event: str = "COMMENT") -> dict:
    """One review with N inline comments, not N separate comments — a PR with fifteen
    notifications gets muted, and a muted reviewer catches nothing."""
    return {
        "event": event,
        "body": _summary(findings),
        "comments": [
            {"path": f["file"], "line": f["line"], "body": body(f)} for f in findings
        ],
    }


def _summary(findings: list[dict]) -> str:
    if not findings:
        return "No findings in the reportable categories."
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    parts = [f"{counts[s]} {s}" for s in ("blocking", "important", "minor") if s in counts]
    return f"{len(findings)} finding(s): {', '.join(parts)}."
