"""Archival-only source-review packager; retired 2026-11-15, issues 1265/1266.

The executed historical generator and its original receipt hashes are preserved
in ../inventory/archive/package_source_reviews.executed.py.txt (SHA256 below).
It assumed specific historical inputs and could overwrite existing results.
Those results remain unchanged; this entry point no longer evaluates arbitrary
inputs or writes reports. --help is supported; all execution requests refuse.
A new generic packager needs independently reviewed input and output contracts.
Original SHA256: 8f361c8b49222b363af157a55572e37d503e22ba55fc88fb68bd9c234f4e120a.
"""
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--finding-issue-url")
    parser.parse_args(argv)
    parser.error("archival-only helper: execution retired; original evidence and outputs must remain unchanged")


if __name__ == "__main__":
    main()
