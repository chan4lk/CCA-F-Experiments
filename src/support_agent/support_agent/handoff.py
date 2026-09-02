"""The escalation summary.

The human who picks this up cannot see the conversation. Everything they need is either
in this object or gone, so the fields are required and the renderer is not free-form.
"""

from datetime import UTC, datetime

REASONS = {
    "customer_request": "Customer asked for a human",
    "policy_gap": "Policy is silent or ambiguous on the request",
    "over_ceiling": "Refund exceeds the policy ceiling",
    "no_progress": "Agent could not make meaningful progress",
}


def summarise(args: dict, case_facts: dict | None = None) -> dict:
    orders = [o.strip() for o in str(args.get("order_ids", "")).split(",") if o.strip()]
    return {
        "raised_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_id": args.get("customer_id", "unverified"),
        "reason_code": args.get("reason_code", "no_progress"),
        "reason": REASONS.get(args.get("reason_code"), "Unspecified"),
        "root_cause": args.get("root_cause", ""),
        "recommended_action": args.get("recommended_action", ""),
        "amount": float(args.get("amount", 0) or 0),
        "order_ids": orders,
        "case_facts": case_facts or {},
    }


def render(handoff: dict) -> str:
    lines = [
        f"ESCALATION {handoff['raised_at']}",
        f"  customer   : {handoff['customer_id']}",
        f"  reason     : {handoff['reason']} ({handoff['reason_code']})",
        f"  orders     : {', '.join(handoff['order_ids']) or '-'}",
        f"  amount     : {handoff['amount']:.2f}",
        f"  root cause : {handoff['root_cause']}",
        f"  recommend  : {handoff['recommended_action']}",
    ]
    for key, value in handoff.get("case_facts", {}).items():
        lines.append(f"  fact       : {key} = {value}")
    return "\n".join(lines)
