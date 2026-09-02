import os

MODEL = os.environ.get("CI_REVIEW_MODEL", "claude-haiku-4-5")
MAX_BUDGET_USD = os.environ.get("CI_REVIEW_BUDGET_USD", "1.00")

# Read-only. A reviewer that can edit the branch it is reviewing is a different,
# much larger permission grant than a reviewer that reports.
ALLOWED_TOOLS = ["Read", "Grep", "Glob"]

TIMEOUT_SECONDS = int(os.environ.get("CI_REVIEW_TIMEOUT", "600"))
