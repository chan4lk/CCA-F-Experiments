"""Review criteria.

"Be conservative" and "only report high-confidence findings" do not reduce false
positives - they ask the model to filter on a feeling. What reduces them is naming the
categories that count as findings and the ones that do not, and showing the boundary.
"""

REPORT = {
    "correctness": "Code that produces a wrong result for an input it will actually receive. Name the input.",
    "security": "Untrusted input reaching a sink: SQL, shell, path, template, deserializer. Name the source and the sink.",
    "resource-leak": "A file, socket, lock, or transaction on a path that can exit without releasing it.",
    "concurrency": "Shared mutable state without synchronisation, or an await/lock ordering that can deadlock.",
    "api-contract": "A caller in this repo that is now passing or expecting something this change made wrong.",
    "stale-comment": "A comment or docstring whose claimed behaviour contradicts what the code does. Quote both.",
}

SKIP = {
    "style": "Formatting, import order, quote style, line length. A formatter owns these.",
    "naming": "Preference for a different name where the current one is not actively misleading.",
    "local-convention": "A pattern that differs from your preference but matches the surrounding file.",
    "test-coverage-in-general": "'This could use more tests' without naming an untested branch that can fail.",
    "speculative-perf": "A performance concern with no measured or arithmetic basis at this input size.",
    "rewrite-suggestion": "A restructuring that does not fix a defect listed above.",
}

SEVERITY = {
    "blocking": (
        "Wrong output, data loss, or an exploitable path, on input the code will see in "
        "production. Example: `user_id` interpolated into an f-string SQL query."
    ),
    "important": (
        "A real defect on a reachable but narrower path - an unhandled error case, a leak "
        "on the exception path. Example: `open()` outside a `with` and a `raise` between "
        "open and close."
    ),
    "minor": (
        "A genuine defect with bounded consequence. Example: a docstring saying a function "
        "returns None when it returns an empty list."
    ),
}

# The boundary cases. Described in prose these get classified inconsistently; shown as
# pairs, the model generalises the distinction to patterns not listed here.
EXAMPLES = [
    {
        "code": 'cursor.execute(f"SELECT * FROM orders WHERE id = {order_id}")',
        "verdict": "report",
        "category": "security",
        "severity": "blocking",
        "why": "order_id reaches the SQL string directly. Parameterise it.",
    },
    {
        "code": 'cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))',
        "verdict": "skip",
        "why": "Parameterised. Reporting this trains reviewers to ignore the security category.",
    },
    {
        "code": 'log.info(f"processing order {order_id}")',
        "verdict": "skip",
        "why": "An f-string is not an injection. The sink is a logger, not a parser.",
    },
    {
        "code": "def total(items):\n    return sum(i.price for i in items) / len(items)",
        "verdict": "report",
        "category": "correctness",
        "severity": "blocking",
        "why": "ZeroDivisionError on an empty list, which callers pass. Name the input.",
    },
    {
        "code": "def total(items):\n    if not items:\n        return 0\n    return sum(i.price for i in items) / len(items)",
        "verdict": "skip",
        "why": "The empty case is handled. `0` versus `None` here is a preference, not a defect.",
    },
    {
        "code": '# returns None when the queue is empty\ndef pop(self):\n    return self._items.pop() if self._items else []',
        "verdict": "report",
        "category": "stale-comment",
        "severity": "minor",
        "why": "The comment says None, the code returns []. Quote both halves in the finding.",
    },
]
