"""Routing. Reviewer capacity is the scarce resource, so the job is to spend it on
the records most likely to be wrong."""

import random
from collections import defaultdict
from dataclasses import dataclass, field

from settings import REVIEW_THRESHOLD
from validate import Issue


@dataclass
class Decision:
    route: str  # "auto" | "review"
    reasons: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return self.route == "review"


def route(record: dict, issues: list[Issue], threshold: float = REVIEW_THRESHOLD) -> Decision:
    reasons = []

    for issue in issues:
        kind = "unresolved" if issue.retryable else "unfixable"
        reasons.append(f"{kind}: {issue}")

    low = {f: c for f, c in record.get("field_confidence", {}).items() if c < threshold}
    for name, score in sorted(low.items()):
        reasons.append(f"confidence: {name} scored {score} below {threshold}")

    if record.get("conflict_detected"):
        reasons.append(f"conflict: {record.get('conflict_note')}")

    return Decision("review" if reasons else "auto", reasons)


def audit_sample(decisions: list[tuple[str, Decision]], rate: float = 0.05, seed: int | None = None):
    """Stratified sample of the AUTO-approved records, by document type.

    Aggregate accuracy hides a document type that fails badly, and unsampled
    high-confidence output is where a novel error pattern lives undetected. Sampling
    per stratum keeps a rare type from vanishing out of the sample.
    """
    strata = defaultdict(list)
    for doc_type, decision in decisions:
        if not decision.needs_review:
            strata[doc_type].append((doc_type, decision))

    rng = random.Random(seed)
    picked = []
    for _, members in sorted(strata.items()):
        take = max(1, round(len(members) * rate))
        picked += rng.sample(members, min(take, len(members)))
    return picked
