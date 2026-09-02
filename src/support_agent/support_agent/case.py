"""Case facts: the transactional record held outside the summarised history.

Progressive summarisation is lossy in exactly the wrong direction - it keeps the shape of
the conversation and condenses the amounts, dates and order numbers into "the customer
discussed a refund". These are carried verbatim and re-injected, so a compacted
conversation still knows the number.
"""

from dataclasses import dataclass, field


@dataclass
class Case:
    verified_customer_id: str | None = None
    facts: dict = field(default_factory=dict)
    orders: dict = field(default_factory=dict)
    refunds: list = field(default_factory=list)
    issues: list = field(default_factory=list)

    def verify(self, customer_id: str) -> None:
        self.verified_customer_id = customer_id
        self.facts["customer_id"] = customer_id

    @property
    def verified(self) -> bool:
        return self.verified_customer_id is not None

    def record_order(self, order: dict) -> None:
        self.orders[order["order_id"]] = {
            "status": order.get("status"),
            "total": order.get("total"),
            "currency": order.get("currency"),
            "placed_at": order.get("placed_at"),
            "delivered_at": order.get("delivered_at"),
            "refundable": order.get("refundable"),
        }

    def open_issue(self, description: str) -> None:
        """One request often carries several concerns. Tracking them separately is what
        stops the second one being dropped once the first is resolved."""
        self.issues.append({"description": description, "resolved": False})

    def resolve_issue(self, index: int) -> None:
        self.issues[index]["resolved"] = True

    @property
    def unresolved(self) -> list[dict]:
        return [i for i in self.issues if not i["resolved"]]

    def block(self) -> str:
        """Rendered into every prompt, outside the summarised history."""
        lines = [f"{k}: {v}" for k, v in self.facts.items()]
        for order_id, facts in self.orders.items():
            lines.append(f"{order_id}: " + ", ".join(f"{k}={v}" for k, v in facts.items()))
        for refund in self.refunds:
            lines.append(f"refund {refund['refund_id']}: {refund['amount']} on {refund['order_id']}")
        for issue in self.issues:
            lines.append(f"issue ({'resolved' if issue['resolved'] else 'open'}): {issue['description']}")
        return "CASE FACTS (verbatim, do not summarise)\n" + ("\n".join(lines) or "(none yet)")
