"""Hooks: the rules that must hold every time.

Everything here could be written as a sentence in the system prompt, and would then hold
almost every time. The difference between "almost every time" and "every time" is the
whole reason these are hooks - identity verification before a financial operation and a
hard refund ceiling are not places for a probability.
"""

import json

import normalize
from case import Case
from settings import REFUND_CEILING_USD
from tools import SERVER_NAME


def bare(tool_name: str) -> str:
    """MCP tools arrive fully qualified; the same tool is named both ways depending on
    where you read it, so match on the tail."""
    prefix = f"mcp__{SERVER_NAME}__"
    return tool_name.removeprefix(prefix)


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _allow() -> dict:
    return {}


class Gate:
    """PreToolUse. Blocks the call rather than advising against it."""

    def __init__(self, case: Case, ceiling: float = REFUND_CEILING_USD):
        self.case = case
        self.ceiling = ceiling
        self.denials: list[tuple[str, str]] = []

    async def __call__(self, payload, tool_use_id, context):
        name = bare(payload.get("tool_name", ""))
        args = payload.get("tool_input", {}) or {}

        if name != "process_refund":
            return _allow()

        # Prerequisite: identity before money. get_customer must have returned a single
        # verified customer in THIS conversation.
        if not self.case.verified:
            return self._denied(name, "process_refund requires a verified customer. Call get_customer first and confirm exactly one match.")

        if args.get("customer_id") != self.case.verified_customer_id:
            return self._denied(
                name,
                f"process_refund was called for {args.get('customer_id')!r} but the verified customer is "
                f"{self.case.verified_customer_id!r}. Re-verify before refunding a different account.",
            )

        amount = float(args.get("amount") or 0)
        if amount > self.ceiling:
            return self._denied(
                name,
                f"{amount:.2f} exceeds the {self.ceiling:.2f} refund ceiling. This cannot be issued here - "
                f"call escalate_to_human with reason_code 'over_ceiling', the amount, and your recommended action.",
            )

        return _allow()

    def _denied(self, name: str, reason: str) -> dict:
        self.denials.append((name, reason))
        return _deny(reason)


class Normalizer:
    """PostToolUse. Rewrites tool output before the model reads it, and harvests the
    facts the case block carries forward."""

    def __init__(self, case: Case):
        self.case = case

    async def __call__(self, payload, tool_use_id, context):
        name = bare(payload.get("tool_name", ""))
        parsed = self._parse(payload.get("tool_response"))
        if parsed is None:
            return {}

        if name == "get_customer" and parsed.get("verified"):
            self.case.verify(parsed["customer"]["customer_id"])

        if name == "lookup_order" and parsed.get("orders"):
            # Normalised again here rather than trusted: a second backend, or a tool
            # someone adds later, will not have gone through normalize.order().
            parsed["orders"] = [normalize.order(o) for o in parsed["orders"]]
            for order in parsed["orders"]:
                self.case.record_order(order)

        if name == "process_refund" and parsed.get("refunded"):
            self.case.refunds.append(
                {"refund_id": parsed["refund_id"], "order_id": parsed["order_id"], "amount": parsed["amount"]}
            )

        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "updatedMCPToolOutput": {"content": [{"type": "text", "text": json.dumps(parsed)}]},
            }
        }

    @staticmethod
    def _parse(response):
        if isinstance(response, dict) and "content" in response:
            blocks = response["content"]
            if blocks and isinstance(blocks[0], dict) and "text" in blocks[0]:
                try:
                    return json.loads(blocks[0]["text"])
                except json.JSONDecodeError:
                    return None
        return None
