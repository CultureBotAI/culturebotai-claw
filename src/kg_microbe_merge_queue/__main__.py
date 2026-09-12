"""Native merge queue policy CLI; inspection and planning never write GitHub."""
import argparse
import json
from pathlib import Path

from . import GitHub, QueueError, apply, plan, table, write_json


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "check"):
        command = commands.add_parser(name)
        command.add_argument("--repository", action="append", help="Manifest key, or claw; default all")
        command.add_argument("--output", type=Path, help="Save complete JSON evidence")
    command = commands.add_parser("apply")
    command.add_argument("--plan", type=Path, required=True)
    command.add_argument("--receipt", type=Path, required=True, help="New path; never overwrite receipts")
    args = parser.parse_args(argv)
    receipt_existed = args.command == "apply" and args.receipt.exists()
    try:
        if args.command == "apply":
            result = apply(GitHub(), json.loads(args.plan.read_text()), args.receipt)
        else:
            result = plan(GitHub(), args.repository)
            if args.output:
                write_json(args.output, result, exclusive=True)
        print(table(result["repositories"]))
        if args.command == "check":
            return int(any(row["status"] != "unchanged" for row in result["repositories"]))
        return int(any(row["status"] == "blocked" for row in result["repositories"]))
    except (QueueError, OSError, ValueError, KeyError) as exc:
        if args.command == "apply" and not receipt_existed and args.receipt.exists():
            try:
                print(table(json.loads(args.receipt.read_text())["repositories"]))
            except (OSError, ValueError, KeyError, TypeError) as receipt_error:
                # Keep the original operation failure visible even when storage
                # also prevents rendering recovery evidence (#403).
                print(f"Could not read receipt {args.receipt}: {receipt_error}")
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
