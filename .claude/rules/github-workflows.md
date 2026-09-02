---
description: Conventions for GitHub Actions workflows that invoke Claude
paths:
  - ".github/workflows/**"
---

# Workflow conventions

Path-scoped: loads only when a workflow file is open. Irrelevant to every other task in the
repo, and CI YAML is where the non-interactive flags actually matter.

## Invoking Claude Code in a job

- `-p` is mandatory. Without it the CLI waits on a tty and the job hangs to its timeout rather
  than failing.
- `--output-format json` plus `--json-schema` whenever the output feeds another step. Nothing
  in a workflow should parse prose.
- `--allowed-tools` is a grant, so grant the minimum. A reviewer gets `Read Grep Glob`; it
  reports, it does not edit the branch it is reviewing.
- `--max-budget-usd` on every invocation. A runaway loop in CI is a bill, not an error.
- `--model` pinned to a full id. An alias moves under you between runs.

## Job hygiene

- `fetch-depth: 0` on checkout for anything that diffs against a base ref.
- `concurrency` with `cancel-in-progress` keyed on the PR number — three pushes should not run
  three reviews.
- `permissions` narrowed per job: `contents: read` unless the job genuinely writes.
- The API key comes from `secrets.ANTHROPIC_API_KEY`, never from a committed file.

## Feeding state back in

A re-run after a new commit must know what the previous run already said, or it posts the same
comment again. Read prior findings back from the API and pass them into the prompt; also
de-duplicate deterministically in code, because a prompt instruction has a non-zero failure
rate and the failure is visible on someone's PR.
