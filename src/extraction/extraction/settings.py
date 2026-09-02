import os

MODEL = os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5")
MAX_TOKENS = 4096

# Calibrate against a labelled validation set before trusting it; the exam's point
# is that an aggregate accuracy number hides per-field failure.
REVIEW_THRESHOLD = float(os.environ.get("EXTRACTION_REVIEW_THRESHOLD", "0.85"))

MAX_ATTEMPTS = int(os.environ.get("EXTRACTION_MAX_ATTEMPTS", "3"))
