#!/usr/bin/env python3
"""Validate ontology mappings from curation stage.

Stage 4 of the collection media curation pipeline:
- Validates CURIE format (e.g., "CHEBI:26716")
- Verifies ontology terms exist (via simple format checks)
- Checks semantic appropriateness (CHEBI for chemicals, etc.)
- Flags low-confidence mappings
- Detects duplicate/conflicting mappings

Usage:
    python scripts/validate_mappings.py \
        --curated workspace/curation/collection_media/curated/batch_001_curated.yaml \
        --output workspace/curation/collection_media/validated/batch_001_validation_report.yaml \
        --confidence-threshold 0.5
"""

import argparse
import re
import yaml
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime
from collections import defaultdict


# Ontology prefixes and their typical use cases
ONTOLOGY_DOMAINS = {
    'CHEBI': 'chemicals, compounds, molecules',
    'FOODON': 'food products, ingredients, peptones, extracts',
    'UBERON': 'anatomical tissues, organs',
    'ENVO': 'environmental materials, substrates',
    'NCIT': 'general terms, cancer-related',
    'MESH': 'medical subject headings',
}

# Expected prefixes for ingredient types
EXPECTED_ONTOLOGIES = {
    'chemical': ['CHEBI', 'MESH'],
    'food_product': ['FOODON', 'CHEBI'],
    'tissue': ['UBERON'],
    'environmental': ['ENVO', 'CHEBI'],
}


def load_curated_data(curated_file: Path) -> Dict:
    """Load curated ingredients from YAML file."""
    with open(curated_file) as f:
        return yaml.safe_load(f)


def validate_curie_format(ontology_id: str) -> Tuple[bool, str]:
    """
    Validate CURIE format: PREFIX:ID

    Returns: (is_valid, error_message)
    """
    if not ontology_id:
        return False, "Empty ontology ID"

    # CURIE pattern: PREFIX:NUMERIC_ID or PREFIX:ALPHANUMERIC
    curie_pattern = r'^([A-Z]+):(\w+)$'
    match = re.match(curie_pattern, ontology_id)

    if not match:
        return False, f"Invalid CURIE format: {ontology_id}"

    prefix = match.group(1)
    if prefix not in ONTOLOGY_DOMAINS:
        return False, f"Unknown ontology prefix: {prefix}"

    return True, ""


def infer_ingredient_type(term: str) -> str:
    """
    Infer ingredient type from term name.

    Returns: 'chemical', 'food_product', 'tissue', or 'environmental'
    """
    term_lower = term.lower()

    # Chemical indicators
    if any(chem in term_lower for chem in ['acid', 'chloride', 'sulfate', 'phosphate', 'sodium', 'potassium', 'calcium', 'magnesium']):
        return 'chemical'

    # Food product indicators
    if any(food in term_lower for food in ['peptone', 'extract', 'yeast', 'beef', 'casein', 'tryptone', 'soytone', 'hydrolysate']):
        return 'food_product'

    # Tissue indicators
    if any(tissue in term_lower for tissue in ['brain', 'heart', 'liver', 'muscle']):
        return 'tissue'

    # Environmental indicators
    if any(env in term_lower for env in ['soil', 'water', 'sediment', 'sludge']):
        return 'environmental'

    # Default to chemical for simple compounds
    return 'chemical'


def validate_semantic_appropriateness(
    term: str,
    ontology_id: str
) -> Tuple[bool, str]:
    """
    Check if ontology source matches ingredient type.

    Returns: (is_valid, warning_message)
    """
    prefix = ontology_id.split(':')[0]
    inferred_type = infer_ingredient_type(term)

    expected_prefixes = EXPECTED_ONTOLOGIES.get(inferred_type, [])

    if prefix not in expected_prefixes:
        return False, f"Unexpected ontology {prefix} for {inferred_type} '{term}' (expected: {', '.join(expected_prefixes)})"

    return True, ""


def detect_duplicates(ingredients: List[Dict]) -> List[Dict]:
    """
    Detect duplicate or conflicting mappings.

    Returns list of conflicts.
    """
    # Group by normalized term
    term_mappings = defaultdict(list)

    for ing in ingredients:
        term = ing.get('preferred_term', '').lower().strip()
        ontology_id = ing.get('ontology_id')

        if term and ontology_id:
            term_mappings[term].append(ontology_id)

    # Find conflicts (same term, different ontology IDs)
    conflicts = []
    for term, ontology_ids in term_mappings.items():
        unique_ids = set(ontology_ids)
        if len(unique_ids) > 1:
            conflicts.append({
                'term': term,
                'conflicting_ids': sorted(list(unique_ids)),
                'occurrences': len(ontology_ids)
            })

    return conflicts


def validate_mappings(curated_data: Dict, confidence_threshold: float = 0.5) -> Dict:
    """
    Validate all curated mappings.

    Returns validation report dict.
    """
    # Support both formats: results.suggestions (old) and ingredients (new)
    if 'results' in curated_data:
        results = curated_data.get('results', {})
        suggestions = results.get('suggestions', [])
    else:
        # New format: ingredients list with mapping_status
        all_ingredients = curated_data.get('ingredients', [])
        suggestions = [
            {
                'ingredient': ing['preferred_term'],
                'ontology_id': ing.get('ontology_id'),
                'confidence': ing.get('confidence', 0.0)
            }
            for ing in all_ingredients
            if ing.get('mapping_status') == 'MAPPED'
        ]

    validation_report = {
        'total_mappings': len(suggestions),
        'valid': 0,
        'warnings': 0,
        'errors': 0,
        'low_confidence': 0,
        'issues': [],
        'conflicts': [],
    }

    for suggestion in suggestions:
        ingredient = suggestion.get('ingredient')
        ontology_id = suggestion.get('ontology_id')
        confidence = suggestion.get('confidence', 0.0)

        # Validation checks
        issues_for_ingredient = []

        # 1. CURIE format validation
        is_valid, error_msg = validate_curie_format(ontology_id)
        if not is_valid:
            issues_for_ingredient.append({
                'severity': 'error',
                'check': 'curie_format',
                'message': error_msg
            })
            validation_report['errors'] += 1

        # 2. Confidence threshold
        if confidence < confidence_threshold:
            issues_for_ingredient.append({
                'severity': 'warning',
                'check': 'low_confidence',
                'message': f"Confidence {confidence:.2f} below threshold {confidence_threshold}"
            })
            validation_report['low_confidence'] += 1
            validation_report['warnings'] += 1

        # 3. Semantic appropriateness
        if is_valid:  # Only check if CURIE is valid
            is_appropriate, warning_msg = validate_semantic_appropriateness(ingredient, ontology_id)
            if not is_appropriate:
                issues_for_ingredient.append({
                    'severity': 'warning',
                    'check': 'semantic_appropriateness',
                    'message': warning_msg
                })
                validation_report['warnings'] += 1

        # Record issues
        if issues_for_ingredient:
            validation_report['issues'].append({
                'ingredient': ingredient,
                'ontology_id': ontology_id,
                'confidence': confidence,
                'issues': issues_for_ingredient
            })
        else:
            validation_report['valid'] += 1

    # 4. Duplicate detection (convert suggestions to ingredient format)
    ingredients_for_dup_check = [
        {
            'preferred_term': s['ingredient'],
            'ontology_id': s['ontology_id']
        }
        for s in suggestions
    ]
    conflicts = detect_duplicates(ingredients_for_dup_check)
    if conflicts:
        validation_report['conflicts'] = conflicts
        validation_report['warnings'] += len(conflicts)

    return validation_report


def save_validation_report(report: Dict, output_file: Path, metadata: Dict):
    """Save validation report to YAML file."""
    output_data = {
        'metadata': {
            'validation_date': datetime.now().isoformat(),
            'source_file': metadata.get('source_file', ''),
            'confidence_threshold': metadata.get('confidence_threshold', 0.5),
        },
        'summary': {
            'total_mappings': report['total_mappings'],
            'valid': report['valid'],
            'warnings': report['warnings'],
            'errors': report['errors'],
            'low_confidence': report['low_confidence'],
        },
        'issues': report['issues'],
        'conflicts': report['conflicts'],
    }

    with open(output_file, 'w') as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def main():
    parser = argparse.ArgumentParser(
        description='Validate curated ontology mappings'
    )
    parser.add_argument(
        '--curated',
        type=Path,
        required=True,
        help='Path to curated YAML file (from batch_curate.py report)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Output validation report path (default: auto-generated in validated/ directory)'
    )
    parser.add_argument(
        '--confidence-threshold',
        type=float,
        default=0.5,
        help='Minimum confidence threshold (default: 0.5)'
    )

    args = parser.parse_args()

    # Load curated data
    print(f"Loading curated data from {args.curated}")
    curated_data = load_curated_data(args.curated)

    # Validate mappings
    print(f"Validating mappings (confidence threshold: {args.confidence_threshold})\n")
    validation_report = validate_mappings(curated_data, args.confidence_threshold)

    # Determine output path
    if args.output:
        output_file = args.output
    else:
        output_dir = Path('workspace/curation/collection_media/validated')
        output_dir.mkdir(parents=True, exist_ok=True)

        # Use same batch ID as input
        batch_id = args.curated.stem.replace('_curated', '')
        output_file = output_dir / f'{batch_id}_validation_report.yaml'

    # Save validation report
    metadata = {
        'source_file': str(args.curated),
        'confidence_threshold': args.confidence_threshold,
    }
    save_validation_report(validation_report, output_file, metadata)
    print(f"✓ Saved validation report to {output_file}")

    # Summary
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    print(f"Total mappings: {validation_report['total_mappings']}")
    print(f"Valid: {validation_report['valid']}")
    print(f"Warnings: {validation_report['warnings']}")
    print(f"Errors: {validation_report['errors']}")
    print(f"Low confidence: {validation_report['low_confidence']}")

    if validation_report['conflicts']:
        print(f"\nConflicts detected: {len(validation_report['conflicts'])}")
        for conflict in validation_report['conflicts'][:5]:
            print(f"  - {conflict['term']}: {conflict['conflicting_ids']}")

    if validation_report['errors'] > 0:
        print("\n⚠️  Validation found errors - review report for details")
        return 1

    if validation_report['warnings'] > 0:
        print("\n⚠️  Validation found warnings - review may be needed")

    return 0


if __name__ == '__main__':
    exit(main())
