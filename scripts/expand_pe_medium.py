#!/usr/bin/env python3
"""Expand PE (Plymouth Erdshreiber) medium - the single parse failure from HTTP retries."""

import yaml
from pathlib import Path
from datetime import datetime


def expand_pe_medium(cm_root: Path, dry_run: bool = True):
    """Expand PE medium with manually extracted composition."""

    file_path = cm_root / 'data/normalized_yaml/algae/pe.yaml'

    if not file_path.exists():
        print(f"✗ File not found: {file_path}")
        return False

    print(f"\nProcessing: CultureMech:000110 (PE - Plymouth Erdshreiber)")
    print(f"  File: {file_path.name}")
    print(f"  Source: CCAP PDF (manual extraction)")

    if dry_run:
        print(f"  [DRY RUN] Would add 5 ingredients")
        return True

    # Load media file
    with open(file_path) as f:
        media = yaml.safe_load(f)

    # Create ingredients list (manually extracted from PDF)
    ingredients = [
        {
            'preferred_term': 'Sodium nitrate',
            'term': {
                'id': 'CHEBI:34754',
                'label': 'sodium nitrate'
            },
            'concentration': {
                'value': '0.2',  # 200 g per 1000 mL stock, 1 mL stock per 1000 mL = 0.2 g/L
                'unit': 'G_PER_L'
            },
            'curation_metadata': {
                'mapping_quality': 'MANUAL',
                'confidence_score': 1.0,
                'curation_date': datetime.now().isoformat(),
                'ontology_source': 'CHEBI'
            },
            'notes': 'From salt solution stock (200 g/L stock, 1 mL/L final); nitrogen source',
            'source': 'CCAP PE medium PDF'
        },
        {
            'preferred_term': 'Disodium hydrogen phosphate dodecahydrate',
            'term': {
                'id': 'CHEBI:86416',
                'label': 'sodium phosphate dibasic dodecahydrate'
            },
            'concentration': {
                'value': '0.02',  # 20 g per 1000 mL stock, 1 mL stock per 1000 mL = 0.02 g/L
                'unit': 'G_PER_L'
            },
            'curation_metadata': {
                'mapping_quality': 'MANUAL',
                'confidence_score': 1.0,
                'curation_date': datetime.now().isoformat(),
                'ontology_source': 'CHEBI'
            },
            'notes': 'From salt solution stock (20 g/L stock, 1 mL/L final); phosphate source and buffer',
            'source': 'CCAP PE medium PDF'
        },
        {
            'preferred_term': 'Natural seawater (filtered, 95% strength)',
            'term': {
                'id': 'ENVO:00002149',
                'label': 'sea water'
            },
            'concentration': {
                'value': '950',
                'unit': 'ML_PER_L'
            },
            'curation_metadata': {
                'mapping_quality': 'MANUAL',
                'confidence_score': 1.0,
                'curation_date': datetime.now().isoformat(),
                'ontology_source': 'ENVO'
            },
            'notes': 'Filtered natural seawater diluted to 95% with distilled water; provides minerals and salts',
            'source': 'CCAP PE medium PDF'
        },
        {
            'preferred_term': 'Soil extract (SE1)',
            'concentration': {
                'value': '50',
                'unit': 'ML_PER_L'
            },
            'notes': 'Soil extract preparation SE1 (see CCAP protocols); provides vitamins, trace elements, and growth factors',
            'source': 'CCAP PE medium PDF'
        },
        {
            'preferred_term': 'Salt solution stock',
            'concentration': {
                'value': '1',
                'unit': 'ML_PER_L'
            },
            'notes': 'Contains NaNO3 and Na2HPO4·12H2O (see above for individual concentrations)',
            'source': 'CCAP PE medium PDF'
        }
    ]

    # Replace placeholder
    media['ingredients'] = ingredients

    # Update curation history
    if 'curation_history' not in media:
        media['curation_history'] = []

    media['curation_history'].append({
        'timestamp': datetime.now().isoformat(),
        'curator': 'expand_pe_medium',
        'action': 'EXPANDED_MANUAL',
        'changes': f"Replaced placeholder with manually extracted composition ({len(ingredients)} ingredients)",
        'source': 'CCAP PE medium PDF - manual extraction after parse failure',
        'notes': 'PDF was accessible but failed automated table extraction; composition manually extracted from text'
    })

    # Update data quality flags
    if 'data_quality_flags' not in media:
        media['data_quality_flags'] = {}
    elif isinstance(media['data_quality_flags'], list):
        old_flags = media['data_quality_flags']
        media['data_quality_flags'] = {flag: True for flag in old_flags}

    media['data_quality_flags']['incomplete_composition'] = False
    media['data_quality_flags']['has_ontology_mappings'] = True
    media['data_quality_flags']['ingredients_curated'] = True
    media['data_quality_flags']['manual_extraction'] = True

    # Save
    with open(file_path, 'w') as f:
        yaml.dump(media, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"  ✓ Expanded with {len(ingredients)} ingredients")
    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Expand PE medium')
    parser.add_argument(
        '--cm-root',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without writing files'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    print("=" * 80)
    print("PE MEDIUM EXPANSION")
    print("=" * 80)

    success = expand_pe_medium(args.cm_root, args.dry_run)

    print("\n" + "=" * 80)
    print("PE MEDIUM EXPANSION SUMMARY")
    print("=" * 80)

    if success:
        print("✅ PE medium expanded")
        if not args.dry_run:
            print("   Ingredients: 5 (3 with ontology mappings)")
            print("   Source: CCAP PDF (manual extraction)")
        else:
            print("⚠️  DRY RUN - No files were modified")
    else:
        print("✗ Failed to expand medium")

    return 0 if success else 1


if __name__ == '__main__':
    exit(main())
