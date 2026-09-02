"""Semantic validation. tool_use already guarantees the record is schema-valid, so
nothing here checks types or required keys - only the errors a schema cannot express."""

import re
from dataclasses import dataclass

TOLERANCE = 0.01
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Business-required fields. A null here is either a correctable miss or a genuine
# absence, and the two need opposite handling.
REQUIRED = ["vendor_name", "document_number", "issue_date", "stated_total"]


@dataclass(frozen=True)
class Issue:
    field: str
    message: str
    retryable: bool

    def __str__(self) -> str:
        return f"[{self.field}] {self.message}"


def _sum_lines(record: dict) -> float:
    return round(sum(item["amount"] for item in record.get("line_items", [])), 2)


def validate(record: dict) -> list[Issue]:
    issues: list[Issue] = []
    confidence = record.get("field_confidence", {})

    # Absent-from-source vs missed. Confidence 0.0 on a null field is the model
    # reporting the document does not contain it; re-asking cannot conjure it, so
    # this is terminal and routes to human review instead of another API call.
    for field in REQUIRED:
        if record.get(field) is None:
            key = field if field in confidence else None
            if key and confidence[key] == 0.0:
                issues.append(Issue(field, "absent from the source document", retryable=False))
            else:
                issues.append(Issue(field, "null but not reported as absent", retryable=True))

    lines_total = _sum_lines(record)
    calculated = record.get("calculated_total")
    if record.get("line_items") and calculated is None:
        issues.append(Issue("calculated_total", "line items present but no sum given", retryable=True))
    elif calculated is not None and abs(calculated - lines_total) > TOLERANCE:
        issues.append(
            Issue(
                "calculated_total",
                f"reported {calculated} but the line amounts sum to {lines_total}",
                retryable=True,
            )
        )

    stated = record.get("stated_total")
    if stated is not None and calculated is not None:
        mismatch = abs(stated - calculated) > TOLERANCE
        if mismatch and not record.get("conflict_detected"):
            issues.append(
                Issue(
                    "conflict_detected",
                    f"stated_total {stated} and calculated_total {calculated} disagree "
                    "but the conflict was not flagged",
                    retryable=True,
                )
            )

    if record.get("conflict_detected") and not record.get("conflict_note"):
        issues.append(Issue("conflict_note", "conflict flagged without an explanation", retryable=True))

    date = record.get("issue_date")
    if date is not None and not ISO_DATE.match(date):
        issues.append(Issue("issue_date", f"{date!r} is not YYYY-MM-DD", retryable=True))

    issues += _enum_detail(record, "currency", "currency_detail")
    if "payment_terms" in record:
        issues += _enum_detail(record, "payment_terms", "payment_terms_detail")
    if "payment_method" in record:
        issues += _enum_detail(record, "payment_method", "payment_method_detail")

    for item in record.get("line_items", []):
        qty, unit, amount = item["quantity"], item["unit_price"], item["amount"]
        if qty is not None and unit is not None and abs(qty * unit - amount) > TOLERANCE:
            issues.append(
                Issue(
                    "line_items",
                    f"{item['description']!r}: {qty} x {unit} is {round(qty * unit, 2)}, not {amount}",
                    retryable=True,
                )
            )

    return issues


def _enum_detail(record: dict, field: str, detail: str) -> list[Issue]:
    value, extra = record.get(field), record.get(detail)
    if value == "other" and not extra:
        return [Issue(detail, f"{field} is 'other' but no detail was given", retryable=True)]
    if value != "other" and extra:
        return [Issue(detail, f"{field} is {value!r} so {detail} must be null", retryable=True)]
    return []


def retryable(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.retryable]
