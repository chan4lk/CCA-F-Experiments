"""Second line of defence on duplicate comments.

Prior findings go into the prompt, but a prompt instruction has a non-zero failure rate
and the cost of it failing is a comment posted twice on someone's PR. Fingerprinting is
deterministic, so it does not.
"""


def fingerprint(finding: dict) -> tuple:
    return (finding.get("file"), finding.get("category"), finding.get("detected_pattern"))


def new_only(findings: list[dict], prior: list[dict]) -> list[dict]:
    seen = {fingerprint(f) for f in prior}
    out, added = [], set()
    for finding in findings:
        key = fingerprint(finding)
        if key in seen or key in added:
            continue
        added.add(key)
        out.append(finding)
    return out


def by_pattern(findings: list[dict]) -> dict[str, int]:
    """Which constructs keep producing findings. Cross-referenced with dismissals, this
    is what identifies a category to disable and rewrite rather than tune in place."""
    counts: dict[str, int] = {}
    for finding in findings:
        slug = finding.get("detected_pattern", "unknown")
        counts[slug] = counts.get(slug, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
