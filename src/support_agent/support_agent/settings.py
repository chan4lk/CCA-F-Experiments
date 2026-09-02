import os

MODEL = os.environ.get("SUPPORT_MODEL", "claude-haiku-4-5")

# The policy ceiling. Enforced by a hook, not by the system prompt: a prompt rule has a
# non-zero failure rate, and the failure here spends real money.
REFUND_CEILING_USD = float(os.environ.get("SUPPORT_REFUND_CEILING_USD", "500"))

MAX_BUDGET_USD = float(os.environ.get("SUPPORT_BUDGET_USD", "1.00"))

# Fields a refund conversation actually uses. An order record carries forty; the rest
# accumulate in context at a cost unrelated to their usefulness.
ORDER_FIELDS_KEPT = [
    "order_id",
    "customer_id",
    "status",
    "placed_at",
    "delivered_at",
    "total",
    "currency",
    "items",
    "refundable",
]
