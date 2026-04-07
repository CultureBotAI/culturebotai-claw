#!/usr/bin/env python3
"""Categorize media in the 'unknown' category based on content analysis.

Analyzes media names, ingredients, applications, and source information
to assign appropriate categories (bacterial, fungal, algae, archaea, specialized).

Usage:
    python scripts/categorize_unknown_media.py --dry-run  # Preview changes
    python scripts/categorize_unknown_media.py            # Apply changes
"""

import argparse
import yaml
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict


# Keyword-based categorization rules
CATEGORY_KEYWORDS = {
    'bacterial': {
        'names': ['broth', 'nutrient', 'luria', 'lb', 'tryptic', 'tsb', 'tsa', 'blood', 'agar',
                  'mueller', 'macconkey', 'eosin', 'emb', 'salmonella', 'e_coli', 'staphylococcus',
                  'bacillus', 'lactobacillus', 'streptococcus', 'enterobacteria', 'vibrio'],
        'ingredients': ['peptone', 'tryptone', 'yeast extract', 'beef extract', 'casein',
                       'bile salts', 'crystal violet', 'neutral red'],
        'applications': ['bacteria', 'bacterial', 'gram-negative', 'gram-positive', 'enterobacteria',
                        'antibiotic', 'susceptibility', 'enteric'],
        'sources': ['atcc', 'dsmz', 'jcm', 'nbrc', 'togo', 'komodo']
    },
    'fungal': {
        'names': ['sabouraud', 'czapek', 'potato dextrose', 'pda', 'yeast', 'malt', 'fungal',
                  'candida', 'aspergillus', 'penicillium', 'saccharomyces'],
        'ingredients': ['malt extract', 'potato extract', 'dextrose', 'chloramphenicol',
                       'cycloheximide'],
        'applications': ['fungi', 'fungal', 'yeast', 'mold', 'mycology'],
        'sources': []
    },
    'algae': {
        'names': ['bbm', 'bg11', 'bg-11', 'f/2', 'f2', 'chu', 'asw', 'artificial seawater',
                  'phytoplankton', 'cyanobacteri', 'chlorella', 'chlamydomonas', 'spirulina',
                  'ccap'],
        'ingredients': ['nitrate', 'silicate', 'trace metals', 'vitamins'],
        'applications': ['algae', 'algal', 'cyanobacteri', 'phytoplankton', 'photosynthetic'],
        'sources': ['ccap', 'utex']
    },
    'archaea': {
        'names': ['archaea', 'archaeal', 'methanogen', 'halophile', 'thermophile',
                  'sulfolobus', 'halobacterium'],
        'ingredients': ['sulfur', 'thiosulfate', 'sodium sulfide'],
        'applications': ['archaea', 'archaeal', 'extreme', 'thermophilic', 'halophilic',
                        'methanogenic'],
        'sources': []
    },
    'specialized': {
        'names': ['selective', 'differential', 'enrichment', 'isolation', 'minimal'],
        'ingredients': [],
        'applications': ['selective', 'differential', 'enrichment', 'isolation'],
        'sources': []
    }
}


def score_media_for_category(media: Dict, category: str) -> float:
    """
    Score how well a media matches a given category.

    Returns: Score 0.0 - 1.0 (higher = better match)
    """
    keywords = CATEGORY_KEYWORDS[category]
    score = 0.0
    max_score = 0.0

    # Check name (weight: 3.0)
    name = media.get('name', '').lower()
    original_name = media.get('original_name', '').lower()
    max_score += 3.0
    for kw in keywords['names']:
        if kw in name or kw in original_name:
            score += 3.0
            break

    # Check ingredients (weight: 2.0)
    max_score += 2.0
    ingredients = media.get('ingredients', [])
    ing_text = ' '.join([ing.get('preferred_term', '').lower() for ing in ingredients])
    for kw in keywords['ingredients']:
        if kw in ing_text:
            score += 2.0
            break

    # Check applications (weight: 1.5)
    max_score += 1.5
    applications = media.get('applications', [])
    app_text = ' '.join([str(app).lower() for app in applications])
    for kw in keywords['applications']:
        if kw in app_text:
            score += 1.5
            break

    # Check source references (weight: 1.0)
    max_score += 1.0
    curation_history = media.get('curation_history', [])
    source_text = ' '.join([h.get('notes', '').lower() for h in curation_history])
    for kw in keywords['sources']:
        if kw in source_text:
            score += 1.0
            break

    # Normalize score
    return score / max_score if max_score > 0 else 0.0


def categorize_media(media: Dict) -> Tuple[str, float, str]:
    """
    Categorize a media file.

    Returns: (category, confidence, reason)
    """
    # Special case: already categorized but lowercase
    current_cat = media.get('category', '').lower()
    if current_cat in ['bacterial', 'fungal', 'algae', 'archaea', 'specialized']:
        return (current_cat, 1.0, f"Already categorized as '{current_cat}'")

    # Score against all categories
    scores = {}
    for category in CATEGORY_KEYWORDS.keys():
        scores[category] = score_media_for_category(media, category)

    # Find best match
    best_category = max(scores, key=scores.get)
    best_score = scores[best_category]

    # Determine confidence and reason
    if best_score >= 0.5:
        confidence = min(best_score, 0.95)
        reason = f"Matched keywords (score: {best_score:.2f})"
    elif best_score > 0.0:
        confidence = best_score * 0.8
        reason = f"Weak match (score: {best_score:.2f}), defaulting to bacterial"
        best_category = 'bacterial'  # Default for weak matches
    else:
        confidence = 0.3
        reason = "No clear match, defaulting to bacterial"
        best_category = 'bacterial'  # Default for no match

    return (best_category, confidence, reason)


def process_unknown_media(cm_root: Path, dry_run: bool = True, min_confidence: float = 0.4) -> Dict:
    """
    Process all media with missing/unknown category and recategorize them.

    Returns: Statistics dict
    """
    data_dir = cm_root / 'data' / 'normalized_yaml'

    if not data_dir.exists():
        print(f"✗ Data directory not found: {data_dir}")
        return {'stats': {}, 'categorized': {}}

    stats = defaultdict(int)
    stats['total'] = 0
    categorized = defaultdict(list)

    # Process all YAML files recursively
    for yaml_file in data_dir.rglob('*.yaml'):
        try:
            with open(yaml_file) as f:
                media = yaml.safe_load(f)

            if not media:
                stats['invalid'] += 1
                continue

            # Only process files with missing or unknown category
            current_cat = media.get('category', None)
            if current_cat not in [None, 'unknown', 'UNKNOWN']:
                continue

            stats['total'] += 1

            # Categorize
            new_category, confidence, reason = categorize_media(media)
            stats[new_category] += 1
            categorized[new_category].append({
                'file': yaml_file,
                'name': media.get('name'),
                'confidence': confidence,
                'reason': reason
            })

            # Update media file if not dry-run
            if not dry_run and confidence >= min_confidence:
                # Update category
                old_category = media.get('category', 'MISSING')
                media['category'] = new_category

                # Add curation history entry
                if 'curation_history' not in media:
                    media['curation_history'] = []

                from datetime import datetime
                media['curation_history'].append({
                    'timestamp': datetime.now().isoformat(),
                    'curator': 'categorize_unknown_media',
                    'action': 'CATEGORIZED',
                    'changes': f"Set category to '{new_category}' (was: {old_category})",
                    'notes': f"Automated categorization (confidence: {confidence:.2f}). {reason}"
                })

                # Determine target directory based on category
                # Files are organized by category in subdirectories
                current_subdir = yaml_file.parent.name

                # If file is in wrong directory, move it
                if current_subdir != new_category:
                    new_dir = cm_root / 'data' / 'normalized_yaml' / new_category
                    new_dir.mkdir(parents=True, exist_ok=True)
                    new_file = new_dir / yaml_file.name

                    # Check if target file already exists
                    if new_file.exists():
                        print(f"  ⚠️  Target file exists, updating in place: {yaml_file.name}")
                        # Update in place
                        with open(yaml_file, 'w') as f:
                            yaml.dump(media, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                        stats['updated'] += 1
                    else:
                        # Write to new location
                        with open(new_file, 'w') as f:
                            yaml.dump(media, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                        # Remove old file
                        yaml_file.unlink()
                        stats['moved'] += 1
                else:
                    # Update in place (already in correct directory)
                    with open(yaml_file, 'w') as f:
                        yaml.dump(media, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                    stats['updated'] += 1

        except Exception as e:
            print(f"  ✗ Error processing {yaml_file.name}: {e}")
            stats['errors'] += 1

    return {'stats': stats, 'categorized': categorized}


def main():
    parser = argparse.ArgumentParser(
        description='Categorize media in unknown category'
    )
    parser.add_argument(
        '--cm-root',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview categorization without moving files'
    )
    parser.add_argument(
        '--min-confidence',
        type=float,
        default=0.4,
        help='Minimum confidence threshold for categorization (default: 0.4)'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    print("Categorizing unknown media...")
    print(f"CultureMech root: {args.cm_root}")
    print(f"Min confidence threshold: {args.min_confidence}\n")

    result = process_unknown_media(args.cm_root, args.dry_run, args.min_confidence)
    stats = result['stats']
    categorized = result['categorized']

    # Print summary
    print("\n" + "=" * 80)
    print("CATEGORIZATION SUMMARY")
    print("=" * 80)
    print(f"Total media processed: {stats['total']}")
    print(f"Invalid files: {stats.get('invalid', 0)}")
    print(f"Errors: {stats.get('errors', 0)}")
    print()
    print("New categories:")
    for category in ['bacterial', 'fungal', 'algae', 'archaea', 'specialized']:
        count = stats.get(category, 0)
        pct = (count / stats['total'] * 100) if stats['total'] > 0 else 0
        print(f"  {category:15s}: {count:5,} ({pct:5.1f}%)")

    if not args.dry_run:
        print(f"\nFiles moved: {stats.get('moved', 0)}")
        print(f"Files updated in place: {stats.get('updated', 0)}")
        print(f"Total modified: {stats.get('moved', 0) + stats.get('updated', 0)}")
    else:
        print(f"\n⚠️  DRY RUN - No files were modified")
        print("    Run without --dry-run to apply categorization")

    # Print sample categorizations
    print("\n" + "=" * 80)
    print("SAMPLE CATEGORIZATIONS (first 5 per category)")
    print("=" * 80)
    for category in ['bacterial', 'fungal', 'algae', 'archaea', 'specialized']:
        if category in categorized and categorized[category]:
            print(f"\n{category.upper()}:")
            for item in categorized[category][:5]:
                name = item['name'] or 'UNNAMED'
                print(f"  {name:50s} (conf: {item['confidence']:.2f}) - {item['reason']}")

    return 0 if stats.get('errors', 0) == 0 else 1


if __name__ == '__main__':
    exit(main())
