"""The MCP tool surface.

Four tools, not eighteen. Each description says what the tool is for, what it takes, what
it returns, and when to reach for a different one - tool descriptions are the only thing
the model selects on, and two tools that sound alike get confused with each other.
"""

from typing import Annotated

import backend
import errors
import normalize
from claude_agent_sdk import create_sdk_mcp_server, tool
from settings import REFUND_CEILING_USD

SERVER_NAME = "support"


@tool(
    "get_customer",
    "Identify and verify a customer, and return their account record. This is the only "
    "tool that establishes WHO you are talking to, and no refund can be processed until "
    "it has returned exactly one match. Takes any combination of email, order_id and "
    "postcode; more identifiers narrow the search. Returns one customer record, or a "
    "multiple-match result listing how many were found and nothing else - when that "
    "happens, ask the customer for another identifier rather than picking one. Use "
    "lookup_order instead when you already have a verified customer and want their orders.",
    {
        "email": Annotated[str, "Customer email address. Optional."],
        "order_id": Annotated[str, "An order id such as ORD-55120. Optional."],
        "postcode": Annotated[str, "Billing postcode, spacing ignored. Optional."],
    },
)
async def get_customer(args):
    email, order_id, postcode = args.get("email"), args.get("order_id"), args.get("postcode")
    if not any([email, order_id, postcode]):
        return errors.fail(
            errors.VALIDATION,
            "at least one of email, order_id or postcode is required",
            customer_message="Could I take your email address or an order number?",
        )

    matches = backend.find_customers(email=email, order_id=order_id, postcode=postcode)

    if not matches:
        # A query that ran and matched nothing. Not a failure - the agent must not retry it.
        return errors.empty("customer", searched_by=[k for k, v in args.items() if v])

    if len(matches) > 1:
        # Deliberately withholds the records. Handing back two candidates invites a guess;
        # the only correct next move is to ask for another identifier.
        return errors.fail(
            errors.VALIDATION,
            f"{len(matches)} customers match these identifiers",
            retryable=True,
            match_count=len(matches),
            customer_message="I can see more than one account with those details - could you give me your postcode as well?",
        )

    return errors.ok({"found": True, "customer": normalize.customer(matches[0]), "verified": True})


@tool(
    "lookup_order",
    "Return the orders belonging to an ALREADY VERIFIED customer, or one order by id. "
    "Takes customer_id (from get_customer) and optionally order_id to narrow to one. "
    "Returns normalised order records - ISO 8601 dates, named statuses, and only the "
    "fields a support conversation uses. An empty list means the customer has no matching "
    "orders; it does not mean the lookup failed. Use get_customer instead when you do not "
    "yet know who the customer is.",
    {
        "customer_id": Annotated[str, "Verified customer id, e.g. CUS-1001."],
        "order_id": Annotated[str, "Narrow to a single order. Optional."],
    },
)
async def lookup_order(args):
    customer_id = args.get("customer_id")
    if not customer_id:
        return errors.fail(errors.VALIDATION, "customer_id is required; call get_customer first")

    matches = backend.find_orders(customer_id=customer_id, order_id=args.get("order_id"))
    if not matches:
        return errors.empty("order", customer_id=customer_id)
    return errors.ok({"found": True, "orders": [normalize.order(o) for o in matches]})


@tool(
    "process_refund",
    "Issue a refund against one order. Requires a customer_id that get_customer has "
    "verified in this conversation, the order_id, the amount, and a reason. Returns a "
    "refund id on success. Refuses non-refundable orders and amounts above the policy "
    f"ceiling of {REFUND_CEILING_USD:.0f} - for those, use escalate_to_human. This tool "
    "moves money; do not call it to check whether a refund is possible.",
    {
        "customer_id": Annotated[str, "Verified customer id."],
        "order_id": Annotated[str, "Order to refund."],
        "amount": Annotated[float, "Refund amount in the order's currency."],
        "reason": Annotated[str, "Why the refund is being issued."],
    },
)
async def process_refund(args):
    orders = backend.find_orders(customer_id=args.get("customer_id"), order_id=args.get("order_id"))
    if not orders:
        return errors.fail(
            errors.VALIDATION,
            f"order {args.get('order_id')} does not belong to {args.get('customer_id')}",
        )

    order = orders[0]
    if not order["refundable"]:
        return errors.fail(
            errors.BUSINESS,
            f"order {order['order_id']} is marked non-refundable",
            retryable=False,
            customer_message="This order is outside the refund window, so I can't process it here - let me pass you to a colleague who can review it.",
        )

    amount = float(args.get("amount", 0))
    if amount > order["total"]:
        return errors.fail(
            errors.BUSINESS,
            f"requested {amount} exceeds the order total {order['total']}",
            retryable=False,
            customer_message="I can only refund up to what was paid on the order.",
        )

    refund = backend.record_refund(order["order_id"], amount, args.get("reason", ""))
    return errors.ok({"refunded": True, **refund})


@tool(
    "escalate_to_human",
    "Hand the conversation to a human agent with a written summary. Use when the customer "
    "asks for a person, when policy is silent or ambiguous on what they are asking for, or "
    "when you cannot make progress. Requires the customer_id, a root_cause, the "
    "recommended_action, and any amount in question. Returns the handoff record that was "
    "filed. The human receives that summary and NOT the conversation transcript, so "
    "anything omitted here is lost. This ends your handling of the case.",
    {
        "customer_id": Annotated[str, "Verified customer id, or 'unverified'."],
        "reason_code": Annotated[str, "One of: customer_request, policy_gap, over_ceiling, no_progress."],
        "root_cause": Annotated[str, "What is actually wrong, in one or two sentences."],
        "recommended_action": Annotated[str, "What you would do if you could."],
        "amount": Annotated[float, "Amount in question, 0 if none."],
        "order_ids": Annotated[str, "Comma-separated order ids referenced. Optional."],
    },
)
async def escalate_to_human(args):
    from handoff import summarise

    return errors.ok({"escalated": True, "handoff": summarise(args)})


TOOLS = [get_customer, lookup_order, process_refund, escalate_to_human]


def server():
    return create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=TOOLS)


def qualified(name: str) -> str:
    return f"mcp__{SERVER_NAME}__{name}"


ALLOWED_TOOLS = [qualified(t.name) for t in TOOLS]
