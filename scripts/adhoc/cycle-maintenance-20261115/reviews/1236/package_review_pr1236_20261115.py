"""Archival-only PR1236 narrative packager; retired 2026-11-15, issues 1265/1266.

The exact former public helper is preserved in
../../inventory/archive/package_review_pr1236_20261115.executed.py.txt.
Its private predecessor and recorded packaging edits remain retained separately.
Existing reports are unchanged. This helper encoded historical conclusions and
could overwrite reports; it is not a generic assessor. --help works; execution
refuses before reading inputs, invoking Git, or writing reports. Future generic
packaging needs independently reviewed input-authentication/output contracts.
Original public SHA256: f6508c1be607ed661ffbc05620631b7b8e24cef3280fef97c436f63a0b37f0e9.
"""
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-tree", required=True)
    parser.parse_args(argv)
    parser.error("archival-only helper: execution retired; original evidence and outputs must remain unchanged")


if __name__ == "__main__":
    main()
