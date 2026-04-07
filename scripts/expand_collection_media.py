#!/usr/bin/env python3
"""Expand collection media placeholder ingredients with curated constituents.

Stage 5 of the collection media curation pipeline:
- Loads curated ingredient mappings
- Loads fetched media specifications
- Updates CultureMech YAML files by replacing placeholders
- Adds ontology mappings, supplier info, curation metadata

Usage:
    python scripts/expand_collection_media.py \
        --fetch-results workspace/curation/collection_media/fetched/batch_001.yaml \
        --curated workspace/curation/collection_media/curated/batch_001_curated.yaml \
        --cm-root /path/to/CultureMech \
        --dry-run
"""

import argparse
import yaml
from pathlib import Path
from typing import Dict, List
from datetime import datetime
from collections import defaultdict


def load_fetch_results(fetch_file: Path) -> Dict:
    """Load fetched media specifications."""
    with open(fetch_file) as f:
        data = yaml.safe_load(f)

    # Index by media_id for quick lookup
    media_index = {}
    for result in data.get('results', []):
        media_id = result.get('media_id')
        if media_id:
            media_index[media_id] = result

    return media_index


def load_curated_mappings(curated_file: Path) -> Dict:
    """
    Load curated ingredient mappings.

    Returns dict mapping ingredient term to ontology info.
    """
    with open(curated_file) as f:
        data = yaml.safe_load(f)

    mappings = {}

    # Support both formats: results.suggestions (old) and ingredients (new)
    if 'results' in data:
        for suggestion in data.get('results', {}).get('suggestions', []):
            ingredient = suggestion.get('ingredient', '').lower().strip()

            if suggestion.get('action') in ['auto_accepted', 'accepted']:
                mappings[ingredient] = {
                    'ontology_id': suggestion.get('ontology_id'),
                    'ontology_label': suggestion.get('label') or suggestion.get('ontology_label'),
                    'ontology_source': suggestion.get('source') or suggestion.get('ontology_source'),
                    'confidence': suggestion.get('confidence', 0.0),
                }
    else:
        # New format: ingredients list with mapping_status
        for ing in data.get('ingredients', []):
            if ing.get('mapping_status') == 'MAPPED':
                term = ing.get('preferred_term', '').lower().strip()
                mappings[term] = {
                    'ontology_id': ing.get('ontology_id'),
                    'ontology_label': ing.get('preferred_term'),  # Use original term as label
                    'ontology_source': ing.get('mapping_source', 'UNKNOWN'),
                    'confidence': ing.get('confidence', 0.0),
                }

    return mappings


def expand_ingredients(
    fetched_spec: Dict,
    curated_mappings: Dict,
    source_type: str,
    source_id: str
) -> List[Dict]:
    """
    Convert fetched ingredients to CultureMech format with ontology mappings.

    Args:
        fetched_spec: Parsed specification from fetch stage
        curated_mappings: Ontology mappings from curation stage
        source_type: 'JCM' or 'CCAP'
        source_id: Medium ID (e.g., '185', 'C103')

    Returns:
        List of ingredient dicts in CultureMech format
    """
    ingredients = []

    for ing in fetched_spec.get('ingredients', []):
        term = ing.get('preferred_term', '').strip()
        if not term:
            continue

        # Create ingredient dict
        ingredient = {
            'preferred_term': term
        }

        # Add ontology mapping if available
        term_normalized = term.lower().strip()
        if term_normalized in curated_mappings:
            mapping = curated_mappings[term_normalized]
            ingredient['term'] = {
                'id': mapping['ontology_id'],
                'label': mapping['ontology_label']
            }

            # Add curation metadata
            ingredient['curation_metadata'] = {
                'mapping_quality': 'LLM_ASSISTED',
                'confidence_score': mapping['confidence'],
                'curation_date': datetime.now().isoformat(),
                'ontology_source': mapping['ontology_source']
            }
        else:
            # Ingredient not mapped - flag it
            ingredient['notes'] = 'Ontology mapping not yet available'

        # Add concentration
        if 'concentration' in ing:
            ingredient['concentration'] = ing['concentration']
        else:
            ingredient['concentration'] = {
                'value': 'variable',
                'unit': 'VARIABLE'
            }

        # Add source information
        source_label = f'{source_type} Medium {source_id}'
        ingredient['source'] = source_label

        # Add notes
        notes_parts = []
        if 'notes' in ing:
            notes_parts.append(ing['notes'])
        notes_parts.append(f'Curated from {source_label} specification')

        if 'notes' not in ingredient:  # Don't override existing notes
            ingredient['notes'] = '; '.join(notes_parts)
        else:
            ingredient['notes'] += '; ' + '; '.join(notes_parts)

        ingredients.append(ingredient)

    return ingredients


def expand_media_file(
    media_file: Path,
    media_id: str,
    fetched_spec: Dict,
    curated_mappings: Dict,
    dry_run: bool = True
) -> bool:
    """
    Expand a single media file with curated constituents.

    Args:
        media_file: Path to CultureMech YAML file
        media_id: CultureMech ID (e.g., 'CultureMech:000310')
        fetched_spec: Fetched specification result
        curated_mappings: Ontology mappings
        dry_run: If True, don't write changes

    Returns:
        True if successful, False otherwise
    """
    try:
        with open(media_file) as f:
            media = yaml.safe_load(f)

        if not media:
            return False

        # Get spec details
        spec = fetched_spec.get('spec')
        if not spec or not spec.get('parse_success'):
            print(f"  ⚠️  No valid specification for {media_id}")
            return False

        source_type = spec.get('source_type')
        source_id = spec.get('source_id')

        # Get expanded ingredients
        new_ingredients = expand_ingredients(
            spec,
            curated_mappings,
            source_type,
            source_id
        )

        if not new_ingredients:
            print(f"  ⚠️  No ingredients to expand for {media_id}")
            return False

        # Replace placeholder ingredients
        original_ingredients = media.get('ingredients', [])

        # Find and replace placeholders
        expanded_ingredients = []
        replaced = False

        for ing in original_ingredients:
            term = ing.get('preferred_term', '').lower()

            # Check if this is a placeholder
            is_placeholder = (
                'see source for composition' in term or
                'undefined component' in term.lower() or
                ing.get('has_placeholder', False)
            )

            if is_placeholder and not replaced:
                # Replace with all expanded constituents
                expanded_ingredients.extend(new_ingredients)
                replaced = True
                print(f"    Replaced placeholder with {len(new_ingredients)} curated ingredients")
            elif not is_placeholder:
                # Keep existing ingredient
                expanded_ingredients.append(ing)

        # If no placeholder found, append to existing ingredients
        if not replaced:
            print(f"    No placeholder found - appending {len(new_ingredients)} ingredients")
            expanded_ingredients.extend(new_ingredients)

        media['ingredients'] = expanded_ingredients

        # Update curation_history
        if 'curation_history' not in media:
            media['curation_history'] = []

        media['curation_history'].append({
            'timestamp': datetime.now().isoformat(),
            'curator': 'batch_process_collection_media',
            'action': 'EXPANDED_INGREDIENTS',
            'changes': f'Replaced placeholder with {len(new_ingredients)} curated ingredients from {source_type}',
            'source': f'{source_type} Medium {source_id}'
        })

        # Update data quality flags
        # Handle both list (old format) and dict (new format)
        if 'data_quality_flags' not in media:
            media['data_quality_flags'] = {}
        elif isinstance(media['data_quality_flags'], list):
            # Convert list to dict, preserving old flags
            old_flags = media['data_quality_flags']
            media['data_quality_flags'] = {flag: True for flag in old_flags}

        media['data_quality_flags']['has_ontology_mappings'] = any(
            'term' in ing for ing in new_ingredients
        )
        media['data_quality_flags']['ingredients_curated'] = True
        media['data_quality_flags']['curation_method'] = 'automated_expert_mapping'
        media['data_quality_flags']['incomplete_composition'] = False  # No longer incomplete

        # Write back if not dry-run
        if not dry_run:
            with open(media_file, 'w') as f:
                yaml.dump(media, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        return True

    except Exception as e:
        import traceback
        print(f"  ✗ Error processing {media_file}: {e}")
        traceback.print_exc()
        return False


def load_media_file_paths(input_file: Path) -> Dict:
    """Load media file paths from input file."""
    with open(input_file) as f:
        data = yaml.safe_load(f)

    paths = {}
    for media in data.get('high_priority', []):
        media_id = media.get('id')
        file_path = media.get('file')
        if media_id and file_path:
            paths[media_id] = file_path

    return paths


def main():
    parser = argparse.ArgumentParser(
        description='Expand collection media placeholder ingredients'
    )
    parser.add_argument(
        '--fetch-results',
        type=Path,
        required=True,
        help='Path to fetch results YAML'
    )
    parser.add_argument(
        '--curated',
        type=Path,
        required=True,
        help='Path to curated mappings YAML'
    )
    parser.add_argument(
        '--input',
        type=Path,
        help='Original input file with file paths (e.g., valid_media_only.yaml)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without writing files'
    )
    parser.add_argument(
        '--cm-root',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    # Load data
    print(f"Loading fetch results from {args.fetch_results}")
    media_index = load_fetch_results(args.fetch_results)
    print(f"✓ Loaded {len(media_index)} media specifications\n")

    print(f"Loading curated mappings from {args.curated}")
    curated_mappings = load_curated_mappings(args.curated)
    print(f"✓ Loaded {len(curated_mappings)} ontology mappings\n")

    # Load file paths if input file provided
    file_paths = {}
    if args.input:
        print(f"Loading file paths from {args.input}")
        file_paths = load_media_file_paths(args.input)
        print(f"✓ Loaded {len(file_paths)} file paths\n")

    # Expand media files
    print(f"Expanding media files in {args.cm_root}")
    print("=" * 80)

    success_count = 0
    error_count = 0
    modified_files = []

    for media_id, fetched_spec in media_index.items():
        # Get media file path from fetch result or input file
        media_file_str = fetched_spec.get('source_info', {}).get('file')
        if not media_file_str:
            # Try to find from identified_media entry
            original_media = fetched_spec.get('media_file')
            if original_media:
                media_file_str = original_media

        # Try file_paths from input file
        if not media_file_str and media_id in file_paths:
            media_file_str = file_paths[media_id]

        if not media_file_str:
            print(f"⚠️  No file path for {media_id}, skipping")
            error_count += 1
            continue

        # Construct full path
        media_file = args.cm_root / media_file_str.replace('data/', '')
        if not media_file.exists():
            media_file = args.cm_root / media_file_str

        if not media_file.exists():
            print(f"⚠️  File not found: {media_file}")
            error_count += 1
            continue

        print(f"\nProcessing: {media_id} ({media_file.name})")

        success = expand_media_file(
            media_file,
            media_id,
            fetched_spec,
            curated_mappings,
            dry_run=args.dry_run
        )

        if success:
            success_count += 1
            modified_files.append(str(media_file))
        else:
            error_count += 1

    # Save list of modified files
    if not args.dry_run and modified_files:
        output_dir = Path('workspace/curation/collection_media/expanded')
        output_dir.mkdir(parents=True, exist_ok=True)

        batch_id = args.fetch_results.stem
        output_file = output_dir / f'{batch_id}_expanded_files.txt'

        with open(output_file, 'w') as f:
            f.write('\n'.join(modified_files))

        print(f"\n✓ Saved list of modified files to {output_file}")

    # Summary
    print("\n" + "=" * 80)
    print("EXPANSION SUMMARY")
    print("=" * 80)
    print(f"Total media: {len(media_index)}")
    print(f"Successfully expanded: {success_count}")
    print(f"Errors: {error_count}")

    if args.dry_run:
        print("\n⚠️  DRY RUN - No files were modified")
        print("    Run without --dry-run to apply changes")

    return 0 if error_count == 0 else 1


if __name__ == '__main__':
    exit(main())
