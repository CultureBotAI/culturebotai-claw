#!/usr/bin/env python3
"""Auto-curate remaining chemical items 13-36 with CHEBI mappings."""

import yaml
from pathlib import Path

# CHEBI mappings for all remaining chemicals
CHEMICAL_MAPPINGS = {
    'Na2glycerophosphate•5H2O': {
        'chebi_id': 'CHEBI:144456',
        'label': 'disodium glycerophosphate pentahydrate',
        'confidence': 0.98,
        'notes': 'CAS 13408-09-8 confirms disodium glycerophosphate pentahydrate'
    },
    'sterile dH2O': {
        'chebi_id': 'CHEBI:15377',
        'label': 'water',
        'confidence': 0.99,
        'notes': 'Sterile deionized water, maps to generic water term'
    },
    'NH4Cl': {
        'chebi_id': 'CHEBI:31206',
        'label': 'ammonium chloride',
        'confidence': 0.99,
        'notes': 'Ammonium chloride, common nitrogen source'
    },
    'NaHCO': {
        'chebi_id': 'CHEBI:32139',
        'label': 'sodium hydrogencarbonate',
        'confidence': 0.98,
        'notes': 'Incomplete formula NaHCO → NaHCO3, sodium bicarbonate'
    },
    'Original amount: (NH4)2HPO4(Fisher A686)': {
        'chebi_id': 'CHEBI:63045',
        'label': 'diammonium hydrogen phosphate',
        'confidence': 0.95,
        'notes': 'Synonym confirms (NH4)2HPO4, diammonium phosphate'
    },
    'NH4NO': {
        'chebi_id': 'CHEBI:63043',
        'label': 'ammonium nitrate',
        'confidence': 0.98,
        'notes': 'Incomplete formula NH4NO → NH4NO3'
    },
    'Glucose': {
        'chebi_id': 'CHEBI:17234',
        'label': 'glucose',
        'confidence': 0.99,
        'notes': 'D-glucose, common carbon source in culture media'
    },
    'Citric Acid•H2O': {
        'chebi_id': 'CHEBI:77633',
        'label': 'citric acid monohydrate',
        'confidence': 0.98,
        'notes': 'Monohydrate form of citric acid'
    },
    'Na2EDTA•2H2O': {
        'chebi_id': 'CHEBI:64734',
        'label': 'ethylenediaminetetraacetic acid disodium dihydrate',
        'confidence': 0.98,
        'notes': 'EDTA disodium salt dihydrate, chelating agent'
    },
    'Na2CO': {
        'chebi_id': 'CHEBI:29377',
        'label': 'sodium carbonate',
        'confidence': 0.98,
        'notes': 'Incomplete formula Na2CO → Na2CO3'
    },
    'Sodium Thiosulfate Pentahydrate': {
        'chebi_id': 'CHEBI:132112',
        'label': 'sodium thiosulfate pentahydrate',
        'confidence': 0.99,
        'notes': 'Na2S2O3·5H2O, reducing agent'
    },
    'NH4MgPO': {
        'chebi_id': 'CHEBI:78227',
        'label': 'struvite',
        'confidence': 0.90,
        'notes': 'Incomplete formula → NH4MgPO4·6H2O (struvite), magnesium ammonium phosphate hexahydrate'
    },
    'H3BO': {
        'chebi_id': 'CHEBI:33118',
        'label': 'boric acid',
        'confidence': 0.98,
        'notes': 'Incomplete formula H3BO → H3BO3'
    },
    'CaSO4•2H2O': {
        'chebi_id': 'CHEBI:31346',
        'label': 'calcium sulfate dihydrate',
        'confidence': 0.99,
        'notes': 'Gypsum, CaSO4·2H2O'
    },
    'Ca': {
        'chebi_id': 'CHEBI:22984',
        'label': 'calcium atom',
        'confidence': 0.85,
        'notes': 'Incomplete - likely refers to calcium salt, generic calcium atom term used'
    },
    'Glycylglycine': {
        'chebi_id': 'CHEBI:27744',
        'label': 'glycylglycine',
        'confidence': 0.99,
        'notes': 'Dipeptide, glycine-glycine'
    },
    'Ferric Ammonium Citrate': {
        'chebi_id': 'CHEBI:75832',
        'label': 'ferric ammonium citrate',
        'confidence': 0.98,
        'notes': 'Iron source, ammonium ferric citrate'
    },
    'Na2HPO4•7H2O': {
        'chebi_id': 'CHEBI:34683',
        'label': 'disodium hydrogen phosphate heptahydrate',
        'confidence': 0.98,
        'notes': 'Heptahydrate form of disodium phosphate'
    },
    'Na2Glycerophosphate.5H2O': {
        'chebi_id': 'CHEBI:144456',
        'label': 'disodium glycerophosphate pentahydrate',
        'confidence': 0.98,
        'notes': 'Duplicate of Na2glycerophosphate•5H2O (different punctuation), CAS 13408-09-8'
    },
    'Original amount: (NH4)2SO4(Fisher A 702)': {
        'chebi_id': 'CHEBI:62946',
        'label': 'ammonium sulfate',
        'confidence': 0.95,
        'notes': 'Synonym confirms (NH4)2SO4, common nitrogen source'
    },
    'Sterile dH2O': {
        'chebi_id': 'CHEBI:15377',
        'label': 'water',
        'confidence': 0.99,
        'notes': 'Duplicate of sterile dH2O (different capitalization), maps to generic water'
    },
    'Na2Glycerophosphate•5H2O': {
        'chebi_id': 'CHEBI:144456',
        'label': 'disodium glycerophosphate pentahydrate',
        'confidence': 0.98,
        'notes': 'Duplicate variant (different punctuation/capitalization), CAS 13408-09-8'
    },
    'CaSO4•2H2Osaturated solution': {
        'chebi_id': 'CHEBI:31346',
        'label': 'calcium sulfate dihydrate',
        'confidence': 0.95,
        'notes': 'Saturated solution of gypsum (CaSO4·2H2O)'
    },
    'FE EDTA': {
        'chebi_id': 'CHEBI:49470',
        'label': 'iron(3+)-EDTA(3-)',
        'confidence': 0.92,
        'notes': 'Fe-EDTA chelate, iron source. Likely refers to Fe(III)-EDTA complex'
    },
}

def main():
    input_file = Path('workspace/curation/chemicals_batch1_to_curate.yaml')

    with open(input_file) as f:
        data = yaml.safe_load(f)

    # Update ingredients 13-36
    for ing in data['ingredients']:
        name = ing['name']
        if name in CHEMICAL_MAPPINGS and ing['suggested_ontology_id'] is None:
            mapping = CHEMICAL_MAPPINGS[name]
            ing['suggested_ontology_id'] = mapping['chebi_id']
            ing['suggested_ontology_label'] = mapping['label']
            ing['ontology_source'] = 'CHEBI'
            ing['confidence_score'] = mapping['confidence']
            ing['notes'] = mapping['notes']
            ing['xrefs'] = []
            print(f"✓ Curated: {name} → {mapping['chebi_id']}")

    # Write back
    with open(input_file, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n✓ Updated {input_file}")
    print(f"\nNext: Run import script with threshold 0.85")

if __name__ == '__main__':
    main()
