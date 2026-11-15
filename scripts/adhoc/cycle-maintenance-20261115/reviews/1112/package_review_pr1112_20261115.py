"""Archival-only PR1112 narrative packager; retired 2026-11-15, issues 1265/1266.

The exact former public helper is preserved in
../../inventory/archive/package_review_pr1112_20261115.executed.py.txt.
Its private predecessor and recorded packaging edits remain retained separately.
Existing reports are unchanged. This helper encoded historical conclusions and
could overwrite reports; it is not a generic assessor. --help works; execution
refuses before reading inputs, invoking Git, or writing reports. Future generic
packaging needs independently reviewed input-authentication/output contracts.
Original public SHA256: 0f409dfc6059def0e31309c9dfe79c4b1fadd8fb7d907377353a2659218fe6d6.
"""
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-tree", required=True)
    parser.parse_args(argv)
    parser.error("archival-only helper: execution retired; original evidence and outputs must remain unchanged")


if __name__ == "__main__":
    main()
