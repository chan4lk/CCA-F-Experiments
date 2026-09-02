"""Orchestration: per-file passes, then one integration pass."""

import subprocess

import prompts
from dedupe import new_only
from runner import run
from schema import FINDINGS, TESTS

BLOCKING = "blocking"


def changed_files(base: str, git=subprocess.run) -> list[str]:
    out = git(["git", "diff", "--name-only", f"{base}...HEAD"], capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line.strip()]


def diff_for(base: str, path: str | None = None, git=subprocess.run) -> str:
    command = ["git", "diff", f"{base}...HEAD"] + (["--", path] if path else [])
    return git(command, capture_output=True, text=True, check=True).stdout


def read(path: str) -> str:
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return ""


def review(base: str, files: list[str], prior: list[dict] | None = None, **kwargs) -> list[dict]:
    prior = prior or []
    findings: list[dict] = []

    for path in files:
        result = run(
            prompts.file_pass(path, diff_for(base, path), read(path), prior),
            prompts.SYSTEM,
            FINDINGS,
            **kwargs,
        )
        findings += result.get("findings", [])

    result = run(prompts.integration_pass(diff_for(base), prior), prompts.SYSTEM, FINDINGS, **kwargs)
    findings += result.get("findings", [])

    return new_only(findings, prior)


def propose_tests(path: str, test_path: str, **kwargs) -> list[dict]:
    result = run(prompts.test_pass(path, read(path), read(test_path)), prompts.SYSTEM, TESTS, **kwargs)
    return result.get("tests", [])


def blocking(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f.get("severity") == BLOCKING]
