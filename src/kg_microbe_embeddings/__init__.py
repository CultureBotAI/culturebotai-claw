"""Independent embedding sets with provenance-bound PaCMAP projections.

Encoders remain domain-owned. This package reads existing vectors; it never
downloads a model, runs inference, calls a provider, or publishes a website.
"""

from .registry import EmbeddingError, load_registry

__all__ = ["EmbeddingError", "load_registry"]
