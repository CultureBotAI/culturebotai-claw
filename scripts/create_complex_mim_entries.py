#!/usr/bin/env python3
"""Create MediaIngredientMech entries for complex formulations."""

import yaml
from pathlib import Path
from datetime import datetime

def search_culturemech_id(cm_root: Path, search_name: str) -> str:
    """Search for CultureMech ID by media name."""
    # Simple search - look for files with matching names
    search_pattern = search_name.lower().replace(' ', '_').replace('-', '')

    for yaml_file in cm_root.glob('data/normalized_yaml/**/*.yaml'):
        if search_pattern in yaml_file.stem.lower():
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)
                    if data and 'id' in data:
                        return data['id'], str(yaml_file.relative_to(cm_root))
            except:
                continue

    return None, None

def main():
    workspace = Path('workspace')
    cm_root = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech'
    mim_root = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech'

    # Load complex formulations
    with open('reference/complex_formulations.yaml') as f:
        formulations = yaml.safe_load(f)

    # Get occurrence statistics from previous unmapped entries
    # (We'll need to reconstruct this from git history or CultureMech)

    # Complete media to add
    media_to_add = [
        {'name': 'BG-11 Medium', 'occurrences': 2},
        {'name': 'BG-11 Trace Metals Solution', 'occurrences': 5},
        {'name': 'Bold 1NV Medium', 'occurrences': 1},
        {'name': 'Bold Trace Stock', 'occurrences': 3},
        {'name': 'Bristol Medium', 'occurrences': 1},
        {'name': 'F/2 Medium', 'occurrences': 8},
        {'name': 'Allen Medium', 'occurrences': 1},
        {'name': 'Volvox Medium', 'occurrences': 1},
        {'name': 'Waris Medium', 'occurrences': 1},
        {'name': 'Euglena Medium', 'occurrences': 1},
        {'name': "Erdschreiber's Medium", 'occurrences': 1},
        {'name': 'DYIII Medium', 'occurrences': 1},
        {'name': 'Modified Bold 3N Medium', 'occurrences': 1},
        {'name': 'Modified COMBO Medium', 'occurrences': 1},
        {'name': "Beijerinck's Solution", 'occurrences': 1},
    ]

    # Stock solutions to add
    solutions_to_add = [
        {'name': 'P-IV Metal Solution', 'occurrences': 3},
        {'name': 'P-II Metal Solution', 'occurrences': 2},
        {'name': 'WC Trace Elements Solution', 'occurrences': 2},
        {'name': "Hunter's Trace Stock Solution", 'occurrences': 2},
        {'name': 'Trace Metals Solution', 'occurrences': 15},
        {'name': 'MWC Metal Solution', 'occurrences': 1},
        {'name': 'DYV Metal Solution', 'occurrences': 1},
        {'name': 'Algal Trace Elements Solution', 'occurrences': 1},
        {'name': 'DAS Macro Solution', 'occurrences': 1},
        {'name': 'DAS Vitamin Cocktail', 'occurrences': 1},
        {'name': 'Chelated Iron Solution', 'occurrences': 4},
        {'name': 'Iron Stock', 'occurrences': 5},
        {'name': 'EDTA Stock', 'occurrences': 3},
        {'name': 'Boron Stock', 'occurrences': 2},
        {'name': 'Phosphate Buffer Stock Solution', 'occurrences': 3},
        {'name': 'Enrichment Solution for Seawater Medium', 'occurrences': 2},
        {'name': 'Spir solution', 'occurrences': 1},
        {'name': 'Chu Stock Solution', 'occurrences': 1},
        {'name': 'A+ Trace Components', 'occurrences': 1},
        {'name': 'G9 Trace Metals for J medium', 'occurrences': 1},
        {'name': 'Macro Component 1 for J Medium', 'occurrences': 1},
        {'name': 'Macro Component 2 for J medium', 'occurrences': 1},
        {'name': 'Modified P-IV chelated Micronutrient Solution', 'occurrences': 1},
        {'name': 'Minor Nutrients', 'occurrences': 2},
    ]

    all_items = media_to_add + solutions_to_add

    # Create MediaIngredientMech entries
    new_entries = []

    for idx, item in enumerate(all_items, start=1):
        name = item['name']
        occurrences = item['occurrences']

        # Search for CultureMech ID
        cm_id, cm_file = search_culturemech_id(cm_root, name)

        entry = {
            'ontology_id': f'MediaIngredientMech:COMPLEX_{idx:04d}',
            'preferred_term': name,
            'ontology_source': 'COMPLEX_FORMULATION',
            'mapping_status': 'MAPPED',
            'formulation_type': 'complete_medium' if item in media_to_add else 'stock_solution',
            'synonyms': [
                {
                    'synonym_text': name,
                    'synonym_type': 'RAW_TEXT',
                    'source': 'CultureMech'
                }
            ],
            'occurrence_statistics': {
                'total_occurrences': occurrences,
                'media_count': occurrences
            },
            'notes': f'Complex formulation - see reference/complex_formulations.yaml for details',
            'curation_history': [
                {
                    'timestamp': datetime.utcnow().isoformat(),
                    'curator': 'complex_formulation_curator',
                    'action': 'CREATED',
                    'changes': 'Created entry for complex formulation',
                    'llm_assisted': True
                }
            ]
        }

        # Add CultureMech cross-reference if found
        if cm_id:
            entry['culturemech_reference'] = {
                'id': cm_id,
                'file': cm_file,
                'note': 'Complete formulation available in CultureMech'
            }

        # Add reference to complex_formulations.yaml
        entry['xrefs'] = [
            {
                'database': 'CultureBotAI-CLAW',
                'id': 'reference/complex_formulations.yaml',
                'description': 'Detailed composition and preparation protocol'
            }
        ]

        new_entries.append(entry)
        print(f"✓ Created entry: {name}")
        if cm_id:
            print(f"  → CultureMech: {cm_id}")

    # Export for import
    export_data = {
        'metadata': {
            'batch_name': 'complex_formulations',
            'total_terms': len(new_entries),
            'curation_date': '2026-03-27',
            'description': 'Complex media formulations and stock solutions',
            'note': 'These are multi-component mixtures, not single chemical entities'
        },
        'entries': new_entries
    }

    output_file = workspace / 'curation/complex_formulations_mim_entries.yaml'
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        yaml.dump(export_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n✓ Created {len(new_entries)} MediaIngredientMech entries")
    print(f"✓ Output: {output_file}")
    print(f"\nNext: Import these into MediaIngredientMech/data/curated/mapped_ingredients.yaml")

if __name__ == '__main__':
    main()
