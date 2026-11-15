"""Archival-only follow-up packager; retired 2026-11-15, issues 1265/1266.

The executed historical generator and its original receipt hashes are preserved
in ../inventory/archive/package_followup_reviews.executed.py.txt (SHA256 below).
It assumed specific historical inputs and rewrote private REVIEW.md/review.json.
Those results remain unchanged; this entry point no longer evaluates arbitrary
inputs or writes reports. --help is supported; all execution requests refuse.
A new generic packager needs independently reviewed input and output contracts.
Original SHA256: 42ad7c3549aaf2428531aa41dcc0d0ca59c35cdfb524911d19093db2cc602615.
"""
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviews-root", required=True)
    parser.parse_args(argv)
    parser.error("archival-only helper: execution retired; original evidence and outputs must remain unchanged")


if __name__ == "__main__":
    main()
