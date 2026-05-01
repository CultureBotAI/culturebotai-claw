"""python -m kg_microbe_qc CLI entry."""
import sys

from kg_microbe_qc.generator import cli

if __name__ == "__main__":
    sys.exit(cli())
