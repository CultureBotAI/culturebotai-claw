"""
Ingredient Deduplicator Plugin

Merges unmapped ingredient lists from CultureMech and MediaIngredientMech
into a single deduplicated canonical set.

Deduplication Strategies:
1. Exact match - Same normalized name
2. CHEBI ID match - Same ontology_id
3. Synonym overlap - Synonyms lists share terms
4. Priority - MediaIngredientMech wins for conflicts (more metadata)
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ConflictRecord:
    """Record of a merge conflict requiring human review."""

    ingredient_a_name: str
    ingredient_b_name: str
    conflict_type: str  # SYNONYM_AMBIGUITY, METADATA_MISMATCH, etc.
    culturemech_id: Optional[str]
    mediaingredientmech_id: Optional[str]
    reason: str
    suggested_resolution: str


class IngredientDeduplicator:
    """Deduplicate unmapped ingredients from multiple repositories."""

    # Normalization patterns (from MediaIngredientMech)
    HYDRATE_PATTERNS = [
        r'[•·.×xX]\s*\d+\s*H2O',  # •2H2O, .7H2O, ×nH2O, x 7 H2O
        r'\s*hydrate',
        r'\s*\(hydrated\)',
        r'\s*heptahydrate',
        r'\s*dihydrate',
        r'\s*monohydrate',
        r'\s*trihydrate',
        r'\s*pentahydrate',
        r'\s*hexahydrate',
    ]

    CATALOG_PATTERNS = [
        r'\s*\(Fisher [^)]+\)',
        r'\s*\(Sigma [^)]+\)',
        r'\s*\(CAS:\s*[^)]+\)',
        r'\s*\([A-Z]{2,5}[- ][\w-]+\)',
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize deduplicator.

        Args:
            config: Configuration with synonym_overlap_threshold, etc.
        """
        self.config = config or {}
        self.synonym_overlap_threshold = self.config.get('synonym_overlap_threshold', 0.5)

        # Stats tracking
        self.stats = {
            'culturemech_original': 0,
            'mediaingredientmech_original': 0,
            'exact_matches': 0,
            'chebi_matches': 0,
            'synonym_matches': 0,
            'duplicates_merged': 0,
            'conflicts_detected': 0,
            'final_count': 0,
        }

        logger.info(f"IngredientDeduplicator initialized with "
                   f"synonym_overlap_threshold={self.synonym_overlap_threshold}")

    def normalize_name(self, name: str) -> str:
        """
        Normalize ingredient name for matching.

        Args:
            name: Raw ingredient name

        Returns:
            Normalized name (lowercase, stripped, hydrates removed)
        """
        if not name:
            return ""

        normalized = name.strip()

        # Remove hydrate notation
        for pattern in self.HYDRATE_PATTERNS:
            normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE)

        # Remove catalog numbers
        for pattern in self.CATALOG_PATTERNS:
            normalized = re.sub(pattern, '', normalized)

        # Normalize whitespace
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        # Lowercase for comparison
        return normalized.lower()

    def extract_chebi_id(self, ingredient: Dict[str, Any]) -> Optional[str]:
        """
        Extract CHEBI ID from ingredient record.

        Args:
            ingredient: Ingredient record dict

        Returns:
            CHEBI ID (e.g., "CHEBI:26710") or None
        """
        # Check ontology_mapping
        if 'ontology_mapping' in ingredient:
            mapping = ingredient['ontology_mapping']
            if mapping.get('ontology_source') == 'CHEBI':
                return mapping.get('ontology_id')

        # Check ontology_id directly
        if 'ontology_id' in ingredient:
            oid = ingredient['ontology_id']
            if oid and oid.startswith('CHEBI:'):
                return oid

        # Check term field (CultureMech pattern)
        if 'term' in ingredient and ingredient['term']:
            term_id = ingredient['term'].get('id')
            if term_id and term_id.startswith('CHEBI:'):
                return term_id

        return None

    def get_synonyms(self, ingredient: Dict[str, Any]) -> Set[str]:
        """
        Extract and normalize synonyms from ingredient.

        Args:
            ingredient: Ingredient record dict

        Returns:
            Set of normalized synonyms
        """
        synonyms = set()

        # MediaIngredientMech format
        if 'synonyms' in ingredient:
            for syn in ingredient['synonyms']:
                if isinstance(syn, dict):
                    text = syn.get('text', '')
                elif isinstance(syn, str):
                    text = syn
                else:
                    continue
                if text:
                    synonyms.add(self.normalize_name(text))

        # Add preferred_term
        if 'preferred_term' in ingredient:
            synonyms.add(self.normalize_name(ingredient['preferred_term']))

        # Add parsed_chemical_name (CultureMech unmapped format)
        if 'parsed_chemical_name' in ingredient and ingredient['parsed_chemical_name']:
            synonyms.add(self.normalize_name(ingredient['parsed_chemical_name']))

        return synonyms

    def calculate_synonym_overlap(self, syns_a: Set[str], syns_b: Set[str]) -> float:
        """
        Calculate Jaccard similarity between synonym sets.

        Args:
            syns_a: First synonym set
            syns_b: Second synonym set

        Returns:
            Overlap score (0.0 - 1.0)
        """
        if not syns_a or not syns_b:
            return 0.0

        intersection = len(syns_a & syns_b)
        union = len(syns_a | syns_b)

        return intersection / union if union > 0 else 0.0

    def merge_occurrence_stats(
        self,
        ingredient_a: Dict[str, Any],
        ingredient_b: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge occurrence statistics from two ingredients.

        Args:
            ingredient_a: First ingredient (CultureMech)
            ingredient_b: Second ingredient (MediaIngredientMech)

        Returns:
            Merged occurrence_statistics dict
        """
        stats_a = ingredient_a.get('occurrence_statistics', {})
        stats_b = ingredient_b.get('occurrence_statistics', {})

        # CultureMech uses occurrence_count, MediaIngredientMech uses total_occurrences
        count_a = ingredient_a.get('occurrence_count', stats_a.get('total_occurrences', 0))
        count_b = ingredient_b.get('occurrence_count', stats_b.get('total_occurrences', 0))

        # Merge media lists
        media_a = set(ingredient_a.get('media_occurrences', stats_a.get('sample_media', [])))
        media_b = set(ingredient_b.get('media_occurrences', stats_b.get('sample_media', [])))

        return {
            'total_occurrences': count_a + count_b,
            'media_count': len(media_a | media_b),
            'sample_media': sorted(list(media_a | media_b)),
            'culturemech_occurrences': count_a,
            'mediaingredientmech_occurrences': count_b,
        }

    def merge_ingredients(
        self,
        ingredient_a: Dict[str, Any],
        ingredient_b: Dict[str, Any],
        merge_reason: str
    ) -> Dict[str, Any]:
        """
        Merge two ingredient records, prioritizing MediaIngredientMech metadata.

        Args:
            ingredient_a: CultureMech ingredient
            ingredient_b: MediaIngredientMech ingredient
            merge_reason: Reason for merge (EXACT_MATCH, CHEBI_MATCH, etc.)

        Returns:
            Merged ingredient record
        """
        # Priority: MediaIngredientMech wins for conflicts (more metadata)
        # But preserve unique data from both

        merged = ingredient_b.copy()  # Start with MIM data

        # Merge occurrence stats
        merged['occurrence_statistics'] = self.merge_occurrence_stats(ingredient_a, ingredient_b)

        # Merge synonyms
        syns_a = self.get_synonyms(ingredient_a)
        syns_b = self.get_synonyms(ingredient_b)
        all_synonyms = syns_a | syns_b

        if 'synonyms' not in merged:
            merged['synonyms'] = []

        # Add unique synonyms from CultureMech
        existing_syns = {self.normalize_name(s.get('text', s) if isinstance(s, dict) else s)
                        for s in merged['synonyms']}

        for syn in syns_a:
            if syn and syn not in existing_syns:
                merged['synonyms'].append({'text': syn, 'type': 'RAW_TEXT'})

        # Add merge metadata
        merged['deduplication_metadata'] = {
            'merge_reason': merge_reason,
            'merged_from_culturemech': ingredient_a.get('preferred_term') or ingredient_a.get('placeholder_id'),
            'merged_from_mediaingredientmech': ingredient_b.get('preferred_term'),
            'merged_at': '2026-03-24T19:48:00Z',
        }

        return merged

    def detect_conflicts(
        self,
        culturemech_ingredient: Dict[str, Any],
        mim_ingredient: Dict[str, Any]
    ) -> Optional[ConflictRecord]:
        """
        Detect if two ingredients have conflicting metadata.

        Args:
            culturemech_ingredient: CultureMech ingredient
            mim_ingredient: MediaIngredientMech ingredient

        Returns:
            ConflictRecord if conflict detected, None otherwise
        """
        conflicts = []

        # Check CHEBI ID mismatch
        chebi_a = self.extract_chebi_id(culturemech_ingredient)
        chebi_b = self.extract_chebi_id(mim_ingredient)

        if chebi_a and chebi_b and chebi_a != chebi_b:
            conflicts.append(
                ConflictRecord(
                    ingredient_a_name=culturemech_ingredient.get('preferred_term', 'Unknown'),
                    ingredient_b_name=mim_ingredient.get('preferred_term', 'Unknown'),
                    conflict_type='CHEBI_ID_MISMATCH',
                    culturemech_id=chebi_a,
                    mediaingredientmech_id=chebi_b,
                    reason=f"CultureMech has {chebi_a} but MediaIngredientMech has {chebi_b}",
                    suggested_resolution="Review ontology mappings - keep higher confidence one"
                )
            )

        return conflicts[0] if conflicts else None

    def deduplicate_unmapped(
        self,
        culturemech_unmapped: List[Dict[str, Any]],
        mim_unmapped: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[ConflictRecord]]:
        """
        Deduplicate unmapped ingredients from both repositories.

        Args:
            culturemech_unmapped: CultureMech unmapped ingredients list
            mim_unmapped: MediaIngredientMech unmapped ingredients list

        Returns:
            (deduplicated_ingredients, conflicts)
        """
        logger.info(f"Deduplicating: {len(culturemech_unmapped)} CultureMech + "
                   f"{len(mim_unmapped)} MediaIngredientMech ingredients")

        self.stats['culturemech_original'] = len(culturemech_unmapped)
        self.stats['mediaingredientmech_original'] = len(mim_unmapped)

        # Index MediaIngredientMech ingredients
        mim_by_normalized_name: Dict[str, Dict[str, Any]] = {}
        mim_by_chebi: Dict[str, Dict[str, Any]] = {}
        mim_by_synonyms: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for mim_ing in mim_unmapped:
            # Index by normalized name
            norm_name = self.normalize_name(mim_ing.get('preferred_term', ''))
            if norm_name:
                mim_by_normalized_name[norm_name] = mim_ing

            # Index by CHEBI ID
            chebi_id = self.extract_chebi_id(mim_ing)
            if chebi_id:
                mim_by_chebi[chebi_id] = mim_ing

            # Index by synonyms
            for syn in self.get_synonyms(mim_ing):
                if syn:
                    mim_by_synonyms[syn].append(mim_ing)

        # Deduplicate
        deduplicated = []
        conflicts = []
        matched_mim_ids = set()

        for cm_ing in culturemech_unmapped:
            cm_norm_name = self.normalize_name(cm_ing.get('preferred_term', ''))
            cm_chebi = self.extract_chebi_id(cm_ing)
            cm_syns = self.get_synonyms(cm_ing)

            matched = False

            # Strategy 1: Exact normalized name match
            if cm_norm_name and cm_norm_name in mim_by_normalized_name:
                mim_match = mim_by_normalized_name[cm_norm_name]
                mim_id = id(mim_match)

                if mim_id not in matched_mim_ids:
                    conflict = self.detect_conflicts(cm_ing, mim_match)
                    if conflict:
                        conflicts.append(conflict)
                        self.stats['conflicts_detected'] += 1

                    merged = self.merge_ingredients(cm_ing, mim_match, 'EXACT_MATCH')
                    deduplicated.append(merged)
                    matched_mim_ids.add(mim_id)
                    self.stats['exact_matches'] += 1
                    self.stats['duplicates_merged'] += 1
                    matched = True

            # Strategy 2: CHEBI ID match
            if not matched and cm_chebi and cm_chebi in mim_by_chebi:
                mim_match = mim_by_chebi[cm_chebi]
                mim_id = id(mim_match)

                if mim_id not in matched_mim_ids:
                    merged = self.merge_ingredients(cm_ing, mim_match, 'CHEBI_MATCH')
                    deduplicated.append(merged)
                    matched_mim_ids.add(mim_id)
                    self.stats['chebi_matches'] += 1
                    self.stats['duplicates_merged'] += 1
                    matched = True

            # Strategy 3: Synonym overlap
            if not matched and cm_syns:
                best_match = None
                best_score = 0.0

                for syn in cm_syns:
                    if syn in mim_by_synonyms:
                        for mim_candidate in mim_by_synonyms[syn]:
                            mim_id = id(mim_candidate)
                            if mim_id not in matched_mim_ids:
                                mim_syns = self.get_synonyms(mim_candidate)
                                overlap = self.calculate_synonym_overlap(cm_syns, mim_syns)
                                if overlap > best_score:
                                    best_score = overlap
                                    best_match = mim_candidate

                if best_match and best_score >= self.synonym_overlap_threshold:
                    mim_id = id(best_match)
                    merged = self.merge_ingredients(cm_ing, best_match, f'SYNONYM_MATCH (score={best_score:.2f})')
                    deduplicated.append(merged)
                    matched_mim_ids.add(mim_id)
                    self.stats['synonym_matches'] += 1
                    self.stats['duplicates_merged'] += 1
                    matched = True

            # No match - keep CultureMech ingredient
            if not matched:
                deduplicated.append(cm_ing)

        # Add unmatched MediaIngredientMech ingredients
        for mim_ing in mim_unmapped:
            if id(mim_ing) not in matched_mim_ids:
                deduplicated.append(mim_ing)

        self.stats['final_count'] = len(deduplicated)

        logger.info(f"Deduplication complete: {len(deduplicated)} total "
                   f"({self.stats['duplicates_merged']} merged, {len(conflicts)} conflicts)")

        return deduplicated, conflicts

    def get_stats(self) -> Dict[str, int]:
        """Get deduplication statistics."""
        return self.stats.copy()
