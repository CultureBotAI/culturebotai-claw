"""
OAKQuery Plugin for OpenClaw

This plugin wraps MediaIngredientMech's OntologyClient with caching to reduce
duplicate API calls and improve performance for ontology searches.
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, looks_like, resolve_mech_root

CLAW_ROOT = Path(__file__).resolve().parents[1]

logger = logging.getLogger(__name__)


class OAKQueryPlugin:
    """Plugin for cached ontology queries using OAK (oaklib)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the OAKQuery plugin.

        Args:
            config: Plugin configuration with cache_ttl, cache_dir, enabled_ontologies
        """
        self.config = config or {}
        self.cache_ttl = self.config.get("cache_ttl", 86400)  # 24 hours default
        workspace = self.config.get(
            "cache_dir", os.getenv("OPENCLAW_WORKSPACE", "workspace")
        )
        self.cache_dir = Path(workspace) / ".cache" / "oak_queries"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.enabled_ontologies = self.config.get("enabled_ontologies",
                                                   ["CHEBI", "FOODON", "ENVO", "NCIT", "MESH", "UBERON"])

        # Thread-safe cache
        self.memory_cache: Dict[str, tuple[Any, float]] = {}
        self.cache_lock = Lock()

        # Lazy load the actual client
        self._client = None

        logger.info(f"OAKQueryPlugin initialized with cache_ttl={self.cache_ttl}s, "
                   f"cache_dir={self.cache_dir}, ontologies={self.enabled_ontologies}")

    def _get_client(self):
        """Lazily load the MediaIngredientMech OntologyClient.

        The root is resolved through `resolve_mech_root`, not read from the
        environment here (#283). Checking only that the variable is *set* let an
        unverified path reach `sys.path` and be imported from, so a stale or
        wrong value ran code out of the wrong tree. A configuration error is
        raised rather than degraded: it is not an OAK incompatibility, and
        reporting it as one is how a misconfigured deployment looks identical
        to a working one in the logs.

        The identity check is then repeated here, deliberately.
        `resolve_mech_root` trusts an explicitly configured variable once the
        directory exists -- an operator naming a path has made a decision, and
        second-guessing it would break legitimate layouts. That is right for a
        script that reads data. It is not enough here, because this path is
        inserted into `sys.path` and *imported from*: pointing the variable at
        the wrong checkout executes that checkout's code. So the package the
        manifest names must actually be there.

        Only ImportError degrades to delegation, which is what the original
        handler was written for. It previously caught everything -- an unset
        variable, a missing directory, a typo in this file -- and reported them
        all as "OAK compatibility issue".
        """
        if self._client is None:
            # Raises MechRootError if the root is unset, missing, or is not
            # MediaIngredientMech. Deliberately not caught below.
            root = resolve_mech_root("mediaingredientmech", claw_root=CLAW_ROOT)
            package = load_fleet_manifest().mechs["mediaingredientmech"].package_path
            if not looks_like(root, package):
                raise MechRootError(
                    f"{root} does not look like MediaIngredientMech: it has no "
                    f"{package}/. Refusing to import from it."
                )
            try:
                import sys

                src_path = root / "src"
                if str(src_path) not in sys.path:
                    sys.path.insert(0, str(src_path))

                from mediaingredientmech.utils.ontology_client import OntologyClient

                self._client = OntologyClient(sources=self.enabled_ontologies)
                logger.info("OntologyClient loaded successfully")

            except ImportError as e:
                logger.warning(f"OntologyClient unavailable (OAK compatibility issue): {e}")
                logger.info("Will use delegation to existing MediaIngredientMech code")
                # Return None to signal that delegation should be used
                self._client = "UNAVAILABLE"
                return None

        # Return None if client is unavailable
        if self._client == "UNAVAILABLE":
            return None

        return self._client

    def _get_cache_key(self, operation: str, **kwargs) -> str:
        """Generate a cache key from operation and parameters."""
        # Create deterministic string from sorted kwargs
        key_parts = [operation] + [f"{k}:{v}" for k, v in sorted(kwargs.items())]
        key_string = "|".join(str(p) for p in key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    def _get_from_cache(self, cache_key: str) -> Optional[Any]:
        """Get value from memory cache or disk cache."""
        # Try memory cache first
        with self.cache_lock:
            if cache_key in self.memory_cache:
                cached_value, timestamp = self.memory_cache[cache_key]
                if time.time() - timestamp < self.cache_ttl:
                    logger.debug(f"Memory cache HIT: {cache_key}")
                    return cached_value
                else:
                    # Expired, remove it
                    del self.memory_cache[cache_key]

        # Try disk cache
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    cached_data = json.load(f)

                timestamp = cached_data.get("timestamp", 0)
                if time.time() - timestamp < self.cache_ttl:
                    value = cached_data.get("value")
                    # Restore to memory cache
                    with self.cache_lock:
                        self.memory_cache[cache_key] = (value, timestamp)
                    logger.debug(f"Disk cache HIT: {cache_key}")
                    return value
                else:
                    # Expired, delete file
                    cache_file.unlink()
            except Exception as e:
                logger.warning(f"Error reading cache file {cache_file}: {e}")

        logger.debug(f"Cache MISS: {cache_key}")
        return None

    def _save_to_cache(self, cache_key: str, value: Any):
        """Save value to both memory and disk cache."""
        timestamp = time.time()

        # Save to memory cache
        with self.cache_lock:
            self.memory_cache[cache_key] = (value, timestamp)

        # Save to disk cache
        cache_file = self.cache_dir / f"{cache_key}.json"
        try:
            with open(cache_file, 'w') as f:
                json.dump({
                    "value": value,
                    "timestamp": timestamp
                }, f)
            logger.debug(f"Saved to cache: {cache_key}")
        except Exception as e:
            logger.warning(f"Error saving cache file {cache_file}: {e}")

    def search(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        max_results: int = 10,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Search ontologies for terms matching the query string.

        Args:
            query: The term to search for
            sources: Ontology sources to search (defaults to enabled ontologies)
            max_results: Maximum candidates to return per source
            use_cache: Whether to use caching (default True)

        Returns:
            List of candidate dictionaries with ontology_id, label, source, score, etc.
            Returns empty list if OAK unavailable (delegates to existing code)
        """
        sources = sources or self.enabled_ontologies

        # Check cache
        cache_key = self._get_cache_key("search", query=query, sources=str(sources), max_results=max_results)
        if use_cache:
            cached = self._get_from_cache(cache_key)
            if cached is not None:
                return cached

        # Execute search
        client = self._get_client()

        # If client unavailable, return empty list (delegation mode)
        if client is None:
            logger.debug(f"OAK unavailable for query '{query}', returning empty (use delegation)")
            return []

        try:
            candidates = client.search(query, sources, max_results)

            # Convert to dict for JSON serialization
            result = [
                {
                    "ontology_id": c.ontology_id,
                    "label": c.label,
                    "source": c.source,
                    "score": c.score,
                    "synonyms": c.synonyms,
                    "definition": c.definition,
                }
                for c in candidates
            ]

            # Save to cache
            if use_cache:
                self._save_to_cache(cache_key, result)

            return result

        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            return []

    def search_with_variants(
        self,
        queries: List[str],
        sources: Optional[List[str]] = None,
        max_results: int = 10,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Search ontologies with multiple query variants.

        Args:
            queries: List of query variants to try
            sources: Ontology sources to search
            max_results: Maximum candidates per source per query
            use_cache: Whether to use caching

        Returns:
            Deduplicated list of candidates sorted by score
        """
        sources = sources or self.enabled_ontologies

        # Check cache
        cache_key = self._get_cache_key("search_variants", queries=str(queries),
                                       sources=str(sources), max_results=max_results)
        if use_cache:
            cached = self._get_from_cache(cache_key)
            if cached is not None:
                return cached

        # Execute search
        client = self._get_client()
        try:
            candidates = client.search_with_variants(queries, sources, max_results)

            result = [
                {
                    "ontology_id": c.ontology_id,
                    "label": c.label,
                    "source": c.source,
                    "score": c.score,
                    "synonyms": c.synonyms,
                    "definition": c.definition,
                }
                for c in candidates
            ]

            if use_cache:
                self._save_to_cache(cache_key, result)

            return result

        except Exception as e:
            logger.error(f"Search with variants failed for queries {queries}: {e}")
            return []

    def validate_term(
        self,
        ontology_id: str,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        Validate that an ontology term exists and get its details.

        Args:
            ontology_id: The ontology ID (e.g., "CHEBI:32599")
            use_cache: Whether to use caching

        Returns:
            Dictionary with is_valid, label, definition, source
            Returns is_valid=None if OAK unavailable (use delegation)
        """
        cache_key = self._get_cache_key("validate", ontology_id=ontology_id)
        if use_cache:
            cached = self._get_from_cache(cache_key)
            if cached is not None:
                return cached

        client = self._get_client()

        # If client unavailable, return unavailable status (delegation mode)
        if client is None:
            logger.debug(f"OAK unavailable for validation of '{ontology_id}', use delegation")
            result = {
                "is_valid": None,  # None means "use delegation"
                "error": "OAK unavailable, use existing validation code",
                "ontology_id": ontology_id,
            }
            return result

        # Determine source from ID prefix
        prefix = ontology_id.split(":")[0] if ":" in ontology_id else ""
        source = prefix.upper() if prefix in self.enabled_ontologies else None

        if not source:
            result = {
                "is_valid": False,
                "error": f"Unknown ontology prefix: {prefix}",
                "ontology_id": ontology_id,
            }
            if use_cache:
                self._save_to_cache(cache_key, result)
            return result

        try:
            adapter = client._get_adapter(source)
            if adapter is None:
                result = {
                    "is_valid": False,
                    "error": f"Failed to load adapter for {source}",
                    "ontology_id": ontology_id,
                }
            else:
                label = adapter.label(ontology_id)
                definition = None
                try:
                    definition = adapter.definition(ontology_id)
                except Exception:
                    pass

                result = {
                    "is_valid": label is not None,
                    "ontology_id": ontology_id,
                    "label": label,
                    "definition": definition,
                    "source": source,
                }

            if use_cache:
                self._save_to_cache(cache_key, result)

            return result

        except Exception as e:
            logger.error(f"Validation failed for {ontology_id}: {e}")
            result = {
                "is_valid": False,
                "error": str(e),
                "ontology_id": ontology_id,
            }
            if use_cache:
                self._save_to_cache(cache_key, result)
            return result

    def clear_cache(self, older_than_seconds: Optional[int] = None):
        """
        Clear cached queries.

        Args:
            older_than_seconds: If specified, only clear entries older than this
        """
        if older_than_seconds is None:
            # Clear all
            with self.cache_lock:
                self.memory_cache.clear()

            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()

            logger.info("Cleared all cache")
        else:
            # Clear expired entries
            cutoff = time.time() - older_than_seconds

            with self.cache_lock:
                expired_keys = [
                    k for k, (_, ts) in self.memory_cache.items()
                    if ts < cutoff
                ]
                for k in expired_keys:
                    del self.memory_cache[k]

            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    with open(cache_file, 'r') as f:
                        data = json.load(f)
                    if data.get("timestamp", 0) < cutoff:
                        cache_file.unlink()
                except Exception:
                    pass

            logger.info(f"Cleared cache entries older than {older_than_seconds}s")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about cache usage."""
        with self.cache_lock:
            memory_count = len(self.memory_cache)

        disk_files = list(self.cache_dir.glob("*.json"))
        disk_count = len(disk_files)

        total_size = sum(f.stat().st_size for f in disk_files)

        return {
            "memory_cache_entries": memory_count,
            "disk_cache_entries": disk_count,
            "disk_cache_size_bytes": total_size,
            "disk_cache_size_mb": round(total_size / (1024 * 1024), 2),
            "cache_directory": str(self.cache_dir),
            "cache_ttl_seconds": self.cache_ttl,
        }


# Plugin registration for OpenClaw
def register_plugin():
    """Register the OAKQuery plugin with OpenClaw."""
    return {
        "name": "oak_query",
        "version": "1.0.0",
        "class": OAKQueryPlugin,
        "description": "Cached ontology queries using OAK (oaklib)",
    }
