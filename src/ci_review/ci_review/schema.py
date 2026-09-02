"""Output schemas passed to `claude -p --json-schema`. Structured output is what makes
the result postable as inline comments without parsing prose."""

FINDING = {
    "type": "object",
    "properties": {
        "file": {"type": "string", "description": "Repo-relative path."},
        "line": {"type": "integer", "description": "1-indexed line in the file's current state."},
        "category": {
            "type": "string",
            "enum": [
                "correctness",
                "security",
                "resource-leak",
                "concurrency",
                "api-contract",
                "stale-comment",
            ],
        },
        "severity": {"type": "string", "enum": ["blocking", "important", "minor"]},
        "issue": {"type": "string", "description": "The defect in one sentence."},
        "failure_input": {
            "type": "string",
            "description": "The concrete input or state that produces the wrong result. A finding without one is a guess.",
        },
        "suggested_fix": {"type": "string"},
        "detected_pattern": {
            "type": "string",
            "description": (
                "A short slug for the code construct that triggered this, e.g. "
                "'fstring-in-execute', 'divide-by-len'. Findings are grouped by this "
                "slug to find which patterns developers keep dismissing."
            ),
        },
    },
    "required": [
        "file",
        "line",
        "category",
        "severity",
        "issue",
        "failure_input",
        "suggested_fix",
        "detected_pattern",
    ],
    "additionalProperties": False,
}

FINDINGS = {
    "type": "object",
    "properties": {"findings": {"type": "array", "items": FINDING}},
    "required": ["findings"],
    "additionalProperties": False,
}

TESTS = {
    "type": "object",
    "properties": {
        "tests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Function or branch under test."},
                    "name": {"type": "string"},
                    "why_uncovered": {
                        "type": "string",
                        "description": "The branch the existing suite does not reach. Required so duplicates are visible.",
                    },
                    "code": {"type": "string"},
                },
                "required": ["target", "name", "why_uncovered", "code"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tests"],
    "additionalProperties": False,
}
