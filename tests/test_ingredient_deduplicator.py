"""
Tests for Ingredient Deduplicator Plugin

Tests the deduplication logic for merging unmapped ingredients
from CultureMech and MediaIngredientMech.
"""

import pytest
from plugins.ingredient_deduplicator import IngredientDeduplicator, ConflictRecord


@pytest.fixture
def deduplicator():
    """Create a deduplicator instance."""
    return IngredientDeduplicator()


@pytest.fixture
def sample_culturemech_ingredients():
    """Sample CultureMech unmapped ingredients."""
    return [
        {
            'preferred_term': 'Sodium chloride',
            'occurrence_count': 50,
            'media_occurrences': ['medium_001', 'medium_002'],
        },
        {
            'preferred_term': 'CaCl2·2H2O',
            'occurrence_count': 30,
            'term': {
                'id': 'CHEBI:86158',
                'label': 'calcium chloride dihydrate'
            },
            'media_occurrences': ['medium_003'],
        },
        {
            'preferred_term': 'Magnesium sulfate',
            'occurrence_count': 25,
        },
        {
            'preferred_term': 'Unknown vitamin mix',
            'occurrence_count': 5,
            'parsed_chemical_name': 'Vitamin solution B12',
        }
    ]


@pytest.fixture
def sample_mim_ingredients():
    """Sample MediaIngredientMech unmapped ingredients."""
    return [
        {
            'preferred_term': 'sodium chloride',  # Exact match (case-insensitive)
            'ontology_id': 'UNMAPPED_001',
            'occurrence_statistics': {
                'total_occurrences': 40,
                'sample_media': ['media_a', 'media_b'],
            },
            'synonyms': [
                {'text': 'NaCl', 'type': 'RAW_TEXT'},
                {'text': 'table salt', 'type': 'STANDARDIZED'},
            ]
        },
        {
            'preferred_term': 'Calcium chloride dihydrate',  # CHEBI ID match
            'ontology_id': 'CHEBI:86158',
            'occurrence_statistics': {
                'total_occurrences': 20,
                'sample_media': ['media_c'],
            },
            'synonyms': [
                {'text': 'CaCl2 dihydrate', 'type': 'CHEMICAL_NAME'},
            ]
        },
        {
            'preferred_term': 'MgSO4',  # Should match via synonym
            'ontology_id': 'UNMAPPED_002',
            'occurrence_statistics': {
                'total_occurrences': 15,
            },
            'synonyms': [
                {'text': 'Magnesium sulfate', 'type': 'STANDARDIZED'},
                {'text': 'MgSO4', 'type': 'CHEMICAL_NAME'},
            ]
        },
        {
            'preferred_term': 'Peptone',  # No match
            'ontology_id': 'UNMAPPED_003',
            'occurrence_statistics': {
                'total_occurrences': 100,
            }
        }
    ]


class TestNormalization:
    """Test name normalization."""

    def test_normalize_name_basic(self, deduplicator):
        """Test basic normalization."""
        assert deduplicator.normalize_name("Sodium Chloride") == "sodium chloride"
        assert deduplicator.normalize_name("  NaCl  ") == "nacl"

    def test_normalize_name_hydrates(self, deduplicator):
        """Test hydrate stripping."""
        assert deduplicator.normalize_name("CaCl2•7H2O") == "cacl2"
        assert deduplicator.normalize_name("MgSO4 · 7 H2O") == "mgso4"
        assert deduplicator.normalize_name("Copper sulfate pentahydrate") == "copper sulfate"

    def test_normalize_name_catalog_numbers(self, deduplicator):
        """Test catalog number removal."""
        assert deduplicator.normalize_name("NaCl (Fisher S271)") == "nacl"
        assert deduplicator.normalize_name("Peptone (Sigma P5905)") == "peptone"


class TestCHEBIExtraction:
    """Test CHEBI ID extraction."""

    def test_extract_chebi_from_ontology_mapping(self, deduplicator):
        """Test extraction from ontology_mapping field."""
        ingredient = {
            'ontology_mapping': {
                'ontology_id': 'CHEBI:26710',
                'ontology_source': 'CHEBI'
            }
        }
        assert deduplicator.extract_chebi_id(ingredient) == 'CHEBI:26710'

    def test_extract_chebi_from_ontology_id(self, deduplicator):
        """Test extraction from ontology_id field."""
        ingredient = {'ontology_id': 'CHEBI:86158'}
        assert deduplicator.extract_chebi_id(ingredient) == 'CHEBI:86158'

    def test_extract_chebi_from_term(self, deduplicator):
        """Test extraction from term field (CultureMech pattern)."""
        ingredient = {
            'term': {
                'id': 'CHEBI:15377',
                'label': 'water'
            }
        }
        assert deduplicator.extract_chebi_id(ingredient) == 'CHEBI:15377'

    def test_extract_chebi_none(self, deduplicator):
        """Test when no CHEBI ID present."""
        ingredient = {'preferred_term': 'Unknown compound'}
        assert deduplicator.extract_chebi_id(ingredient) is None


class TestSynonymExtraction:
    """Test synonym extraction and normalization."""

    def test_get_synonyms_from_list(self, deduplicator):
        """Test extraction from synonyms list."""
        ingredient = {
            'preferred_term': 'Sodium chloride',
            'synonyms': [
                {'text': 'NaCl'},
                {'text': 'table salt'},
            ]
        }
        syns = deduplicator.get_synonyms(ingredient)
        assert 'nacl' in syns
        assert 'table salt' in syns
        assert 'sodium chloride' in syns

    def test_synonym_overlap_calculation(self, deduplicator):
        """Test Jaccard similarity calculation."""
        syns_a = {'sodium chloride', 'nacl', 'salt'}
        syns_b = {'sodium chloride', 'nacl', 'table salt'}

        overlap = deduplicator.calculate_synonym_overlap(syns_a, syns_b)
        # Intersection: {sodium chloride, nacl} = 2
        # Union: {sodium chloride, nacl, salt, table salt} = 4
        # Jaccard = 2/4 = 0.5
        assert overlap == 0.5


class TestOccurrenceMerging:
    """Test occurrence statistics merging."""

    def test_merge_occurrence_stats(self, deduplicator):
        """Test merging occurrence counts and media lists."""
        ing_a = {
            'occurrence_count': 50,
            'media_occurrences': ['medium_001', 'medium_002'],
        }
        ing_b = {
            'occurrence_statistics': {
                'total_occurrences': 40,
                'sample_media': ['media_a', 'media_b', 'medium_002'],  # One overlap
            }
        }

        merged = deduplicator.merge_occurrence_stats(ing_a, ing_b)

        assert merged['total_occurrences'] == 90  # 50 + 40
        assert merged['culturemech_occurrences'] == 50
        assert merged['mediaingredientmech_occurrences'] == 40
        assert merged['media_count'] == 4  # 4 unique media
        assert 'medium_002' in merged['sample_media']  # Deduplicated


class TestDeduplication:
    """Test core deduplication logic."""

    def test_exact_match_deduplication(
        self,
        deduplicator,
        sample_culturemech_ingredients,
        sample_mim_ingredients
    ):
        """Test exact normalized name matching."""
        # 'Sodium chloride' (CM) should match 'sodium chloride' (MIM)
        deduplicated, conflicts = deduplicator.deduplicate_unmapped(
            [sample_culturemech_ingredients[0]],  # Sodium chloride
            [sample_mim_ingredients[0]]  # sodium chloride
        )

        assert len(deduplicated) == 1  # Merged into one
        stats = deduplicator.get_stats()
        assert stats['exact_matches'] == 1
        assert stats['duplicates_merged'] == 1

        # Check merged occurrence stats
        merged = deduplicated[0]
        assert merged['occurrence_statistics']['total_occurrences'] == 90  # 50 + 40

    def test_chebi_id_match_deduplication(
        self,
        deduplicator,
        sample_culturemech_ingredients,
        sample_mim_ingredients
    ):
        """Test CHEBI ID matching."""
        # CaCl2·2H2O (CM) with CHEBI:86158 should match Calcium chloride dihydrate (MIM) with same ID
        deduplicated, conflicts = deduplicator.deduplicate_unmapped(
            [sample_culturemech_ingredients[1]],  # CaCl2·2H2O
            [sample_mim_ingredients[1]]  # Calcium chloride dihydrate
        )

        assert len(deduplicated) == 1
        stats = deduplicator.get_stats()
        assert stats['chebi_matches'] == 1
        assert stats['duplicates_merged'] == 1

    def test_synonym_overlap_deduplication(
        self,
        deduplicator,
        sample_culturemech_ingredients,
        sample_mim_ingredients
    ):
        """Test synonym overlap matching."""
        # 'Magnesium sulfate' (CM) should match 'MgSO4' (MIM) via synonyms
        deduplicated, conflicts = deduplicator.deduplicate_unmapped(
            [sample_culturemech_ingredients[2]],  # Magnesium sulfate
            [sample_mim_ingredients[2]]  # MgSO4 (with 'Magnesium sulfate' synonym)
        )

        assert len(deduplicated) == 1
        stats = deduplicator.get_stats()
        assert stats['synonym_matches'] == 1
        assert stats['duplicates_merged'] == 1

    def test_no_match_keeps_both(
        self,
        deduplicator,
        sample_culturemech_ingredients,
        sample_mim_ingredients
    ):
        """Test that unmatched ingredients are kept."""
        # 'Unknown vitamin mix' (CM) vs 'Peptone' (MIM) - no match
        deduplicated, conflicts = deduplicator.deduplicate_unmapped(
            [sample_culturemech_ingredients[3]],  # Unknown vitamin mix
            [sample_mim_ingredients[3]]  # Peptone
        )

        assert len(deduplicated) == 2  # Both kept
        stats = deduplicator.get_stats()
        assert stats['duplicates_merged'] == 0

    def test_full_deduplication(
        self,
        deduplicator,
        sample_culturemech_ingredients,
        sample_mim_ingredients
    ):
        """Test full deduplication with multiple matches."""
        deduplicated, conflicts = deduplicator.deduplicate_unmapped(
            sample_culturemech_ingredients,
            sample_mim_ingredients
        )

        stats = deduplicator.get_stats()

        # Expect:
        # - 1 exact match (Sodium chloride)
        # - 1 CHEBI match (CaCl2 dihydrate)
        # - 1 synonym match (Magnesium sulfate)
        # - 1 CM-only (Unknown vitamin mix)
        # - 1 MIM-only (Peptone)
        # Total: 5 ingredients

        assert len(deduplicated) == 5
        assert stats['exact_matches'] == 1
        assert stats['chebi_matches'] == 1
        assert stats['synonym_matches'] == 1
        assert stats['duplicates_merged'] == 3


class TestConflictDetection:
    """Test conflict detection logic."""

    def test_chebi_id_mismatch_conflict(self, deduplicator):
        """Test detection of CHEBI ID conflicts."""
        ing_a = {
            'preferred_term': 'Water',
            'term': {'id': 'CHEBI:15377'}  # Actual water CHEBI
        }
        ing_b = {
            'preferred_term': 'Water',
            'ontology_id': 'CHEBI:26710'  # Sodium chloride (wrong!)
        }

        conflict = deduplicator.detect_conflicts(ing_a, ing_b)

        assert conflict is not None
        assert conflict.conflict_type == 'CHEBI_ID_MISMATCH'
        assert 'CHEBI:15377' in conflict.reason
        assert 'CHEBI:26710' in conflict.reason

    def test_no_conflict_when_ids_match(self, deduplicator):
        """Test no conflict when CHEBI IDs match."""
        ing_a = {
            'preferred_term': 'NaCl',
            'term': {'id': 'CHEBI:26710'}
        }
        ing_b = {
            'preferred_term': 'Sodium chloride',
            'ontology_id': 'CHEBI:26710'
        }

        conflict = deduplicator.detect_conflicts(ing_a, ing_b)
        assert conflict is None


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_lists(self, deduplicator):
        """Test deduplication with empty input lists."""
        deduplicated, conflicts = deduplicator.deduplicate_unmapped([], [])
        assert len(deduplicated) == 0
        assert len(conflicts) == 0

    def test_missing_preferred_term(self, deduplicator):
        """Test handling of ingredients without preferred_term."""
        ing_a = {'occurrence_count': 10}  # No preferred_term
        ing_b = {'preferred_term': 'Salt', 'occurrence_count': 5}

        deduplicated, conflicts = deduplicator.deduplicate_unmapped([ing_a], [ing_b])
        assert len(deduplicated) == 2  # Both kept (no match possible)

    def test_case_insensitive_matching(self, deduplicator):
        """Test that matching is case-insensitive."""
        ing_a = {'preferred_term': 'SODIUM CHLORIDE', 'occurrence_count': 10}
        ing_b = {'preferred_term': 'sodium chloride', 'occurrence_count': 5}

        deduplicated, conflicts = deduplicator.deduplicate_unmapped([ing_a], [ing_b])
        assert len(deduplicated) == 1  # Merged
        stats = deduplicator.get_stats()
        assert stats['exact_matches'] == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
