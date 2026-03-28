#!/usr/bin/env python3
"""Fix incomplete NaNO formula and map to CHEBI."""

import yaml
from pathlib import Path
from datetime import datetime

def main():
    workspace = Path('workspace')

    # Create export for NaNO
    export_data = {
        'metadata': {
            'batch_name': 'incomplete_formula_fix',
            'total_terms': 1,
            'curation_date': '2026-03-27',
            'instructions': 'Fix incomplete formula NaNO → NaNO3 (sodium nitrate) based on CAS 7631-99-4'
        },
        'ingredients': [{
            'id': 1,
            'name': 'NaNO',
            'suggested_ontology_id': 'CHEBI:63068',
            'suggested_ontology_label': 'sodium nitrate',
            'ontology_source': 'CHEBI',
            'confidence_score': 0.98,
            'notes': 'Incomplete formula NaNO → NaNO3, confirmed by CAS 7631-99-4 and Fisher catalog number',
            'xrefs': [],
        }]
    }

    output_file = workspace / 'curation/nano_fix.yaml'
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        yaml.dump(export_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"✓ Created curation file: {output_file}")
    print(f"\nMapping: NaNO → CHEBI:63068 (sodium nitrate)")
    print(f"Confidence: 0.98")
    print(f"\nNext: Import with threshold 0.85")

if __name__ == '__main__':
    main()
