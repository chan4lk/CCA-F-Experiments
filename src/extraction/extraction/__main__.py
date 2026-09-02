import json
import sys
from pathlib import Path

from extract import extract


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m extraction <file> [invoice|receipt]", file=sys.stderr)
        return 2

    path = Path(argv[0])
    doc_type = argv[1] if len(argv) > 1 else None
    result = extract(path.read_text(), doc_type=doc_type, document_id=path.stem)

    if result.error:
        print(f"failed: {result.error}", file=sys.stderr)
        return 1

    print(json.dumps(result.record, indent=2))
    print(f"\ntool      : {result.tool_name}")
    print(f"attempts  : {result.attempts}")
    print(f"route     : {result.decision.route}")
    for reason in result.decision.reasons:
        print(f"  - {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
