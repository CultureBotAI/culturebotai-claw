"""kg_microbe_qc — repo-agnostic QC dashboard generator.

Walks YAML records (configurable glob), computes per-slot coverage,
and renders a static HTML dashboard with matplotlib charts. Used by
CultureMech, MIM, and CommunityMech (Phase 2/5 of the dismech-pattern
port).

Usage:
    from kg_microbe_qc import generate_dashboard
    generate_dashboard(
        config_path=Path("conf/qc_config.yaml"),
        output_dir=Path("dashboard"),
    )

Or via CLI:
    python -m kg_microbe_qc --config conf/qc_config.yaml \
        --output dashboard
"""
from kg_microbe_qc.generator import generate_dashboard

__all__ = ["generate_dashboard"]
__version__ = "0.1.0"
