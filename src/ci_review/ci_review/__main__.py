import argparse
import json
import sys
from pathlib import Path

import review as reviewer
from comment import review_payload
from dedupe import by_pattern


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ci_review")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("review", help="review the diff against base")
    run.add_argument("--base", default="origin/main")
    run.add_argument("--prior", type=Path, help="JSON file of findings already posted on this PR")
    run.add_argument("--out", type=Path, default=Path("review.json"))
    run.add_argument("--fail-on-blocking", action="store_true")

    tests = sub.add_parser("tests", help="propose tests for one file")
    tests.add_argument("source")
    tests.add_argument("existing_tests")

    args = parser.parse_args(argv)

    if args.command == "tests":
        print(json.dumps(reviewer.propose_tests(args.source, args.existing_tests), indent=2))
        return 0

    prior = json.loads(args.prior.read_text()) if args.prior and args.prior.exists() else []
    files = reviewer.changed_files(args.base)
    if not files:
        print("no changed files", file=sys.stderr)
        return 0

    findings = reviewer.review(args.base, files, prior)
    args.out.write_text(json.dumps(review_payload(findings), indent=2))

    print(json.dumps(by_pattern(findings), indent=2), file=sys.stderr)
    print(f"{len(findings)} finding(s) -> {args.out}", file=sys.stderr)

    if args.fail_on_blocking and reviewer.blocking(findings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
