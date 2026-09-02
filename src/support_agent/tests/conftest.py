import json

import backend
import pytest
from case import Case
from tools import qualified


@pytest.fixture(autouse=True)
def clean_backend():
    backend.reset()
    yield
    backend.reset()


@pytest.fixture
def case():
    return Case()


@pytest.fixture
def verified_case():
    c = Case()
    c.verify("CUS-1001")
    return c


def payload(tool: str, **args):
    return {"tool_name": qualified(tool), "tool_input": args}


def response(tool: str, body: dict, is_error: bool = False):
    return {
        "tool_name": qualified(tool),
        "tool_input": {},
        "tool_response": {"content": [{"type": "text", "text": json.dumps(body)}], "isError": is_error},
    }


def unwrap(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


def denied(hook_result: dict) -> bool:
    out = hook_result.get("hookSpecificOutput", {})
    return out.get("permissionDecision") == "deny"


def reason(hook_result: dict) -> str:
    return hook_result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
