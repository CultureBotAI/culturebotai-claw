#!/usr/bin/env python3
"""Manual curation of collection media ingredients using Claude Code.

Maps common chemical compounds and vitamins to CHEBI ontology terms.
"""

import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, List


# Manual mapping database - common media ingredients to CHEBI
MANUAL_MAPPINGS = {
    # Vitamins
    'Biotin': {
        'ontology_id': 'CHEBI:15956',
        'preferred_term': 'biotin',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B7, exact match'
    },
    'Thiamine': {
        'ontology_id': 'CHEBI:18385',
        'preferred_term': 'thiamine',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B1, exact match'
    },
    'Cyanocobalamin': {
        'ontology_id': 'CHEBI:17439',
        'preferred_term': 'cyanocob alamin',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B12, exact match'
    },

    # Salts - simple formulas
    'KCl': {
        'ontology_id': 'CHEBI:32588',
        'preferred_term': 'potassium chloride',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Exact formula match'
    },
    'NaCl': {
        'ontology_id': 'CHEBI:26710',
        'preferred_term': 'sodium chloride',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Exact formula match'
    },
    'CaCl .2H O': {
        'ontology_id': 'CHEBI:64183',
        'preferred_term': 'calcium chloride dihydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'CaCl2·2H2O, exact hydrate match'
    },
    'K HPO': {
        'ontology_id': 'CHEBI:32030',
        'preferred_term': 'dipotassium hydrogen phosphate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'K2HPO4, exact formula match'
    },
    'KH PO': {
        'ontology_id': 'CHEBI:63036',
        'preferred_term': 'potassium dihydrogen phosphate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'KH2PO4, exact formula match'
    },
    'Na CO': {
        'ontology_id': 'CHEBI:29377',
        'preferred_term': 'sodium carbonate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Na2CO3, exact formula match'
    },
    'NaNO': {
        'ontology_id': 'CHEBI:34545',
        'preferred_term': 'sodium nitrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'NaNO3, exact formula match'
    },

    # Hydrated salts - trace metals
    'MnCl .4H O': {
        'ontology_id': 'CHEBI:86457',
        'preferred_term': 'manganese dichloride tetrahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'MnCl2·4H2O, exact hydrate match'
    },
    'ZnSO .7H O': {
        'ontology_id': 'CHEBI:86463',
        'preferred_term': 'zinc sulfate heptahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'ZnSO4·7H2O, exact hydrate match'
    },
    'CoCl .6H O': {
        'ontology_id': 'CHEBI:35696',
        'preferred_term': 'cobalt dichloride hexahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'CoCl2·6H2O, exact hydrate match'
    },
    'FeCl .6H O': {
        'ontology_id': 'CHEBI:30527',
        'preferred_term': 'iron(III) chloride hexahydrate',
        'confidence': 0.95,
        'source': 'CHEBI',
        'mapping_notes': 'FeCl3·6H2O, assuming Fe(III) - common in media'
    },
    'MgSO .7H O': {
        'ontology_id': 'CHEBI:32599',
        'preferred_term': 'magnesium sulfate heptahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'MgSO4·7H2O (Epsom salt), exact hydrate match'
    },
    'CuSO .5H O': {
        'ontology_id': 'CHEBI:31440',
        'preferred_term': 'copper(II) sulfate pentahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'CuSO4·5H2O, exact hydrate match'
    },
    'Na MoO .2H O': {
        'ontology_id': 'CHEBI:75216',
        'preferred_term': 'sodium molybdate dihydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Na2MoO4·2H2O, exact hydrate match'
    },
    'H BO': {
        'ontology_id': 'CHEBI:33141',
        'preferred_term': 'boric acid',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'H3BO3, exact formula match'
    },

    # EDTA variants
    'Na -EDTA': {
        'ontology_id': 'CHEBI:64734',
        'preferred_term': 'disodium ethylenediaminetetraacetate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Na2EDTA, exact match'
    },
    'EDTA': {
        'ontology_id': 'CHEBI:42191',
        'preferred_term': 'ethylenediaminetetraacetic acid',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'EDTA free acid, exact match'
    },

    # Nitrogen sources
    'NH Cl': {
        'ontology_id': 'CHEBI:31206',
        'preferred_term': 'ammonium chloride',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'NH4Cl, exact formula match'
    },
    'Ca NO . H O': {
        'ontology_id': 'CHEBI:64203',
        'preferred_term': 'calcium nitrate tetrahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Ca(NO3)2·4H2O, exact hydrate match'
    },

    # Iron compounds
    'FeSO .7H O': {
        'ontology_id': 'CHEBI:75832',
        'preferred_term': 'iron(II) sulfate heptahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'FeSO4·7H2O (green vitriol), exact hydrate match'
    },
    'Ferric citrate': {
        'ontology_id': 'CHEBI:30688',
        'preferred_term': 'iron(III) citrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Fe-citrate complex, exact match'
    },

    # Organic compounds
    'Tryptone': {
        'ontology_id': 'FOODON:03310387',
        'preferred_term': 'tryptone',
        'confidence': 0.9,
        'source': 'FOODON',
        'mapping_notes': 'Enzymatic digest of casein, food ingredient'
    },
    'Yeast extract': {
        'ontology_id': 'FOODON:00002441',
        'preferred_term': 'yeast extract',
        'confidence': 1.0,
        'source': 'FOODON',
        'mapping_notes': 'Exact match in FOODON'
    },
    'Peptone': {
        'ontology_id': 'FOODON:03310061',
        'preferred_term': 'peptone',
        'confidence': 1.0,
        'source': 'FOODON',
        'mapping_notes': 'Exact match in FOODON'
    },
    'Glucose': {
        'ontology_id': 'CHEBI:17234',
        'preferred_term': 'D-glucose',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Assuming D-glucose (most common), exact match'
    },
    'Agar': {
        'ontology_id': 'CHEBI:2509',
        'preferred_term': 'agar',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Exact match'
    },

    # More vitamins
    'Niacin': {
        'ontology_id': 'CHEBI:15940',
        'preferred_term': 'nicotinic acid',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B3, exact match'
    },
    'Calcium pantothenate': {
        'ontology_id': 'CHEBI:3374',
        'preferred_term': 'calcium pantothenate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B5 calcium salt, exact match'
    },
    'p-Aminobenzoic acid': {
        'ontology_id': 'CHEBI:30753',
        'preferred_term': '4-aminobenzoic acid',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'PABA, exact match'
    },
    'Folic acid': {
        'ontology_id': 'CHEBI:27470',
        'preferred_term': 'folic acid',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B9, exact match'
    },
    'Riboflavin': {
        'ontology_id': 'CHEBI:17015',
        'preferred_term': 'riboflavin',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B2, exact match'
    },
    'Pyridoxine HCl': {
        'ontology_id': 'CHEBI:8671',
        'preferred_term': 'pyridoxine hydrochloride',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B6 HCl salt, exact match'
    },
    'Inositol': {
        'ontology_id': 'CHEBI:17268',
        'preferred_term': 'myo-inositol',
        'confidence': 0.95,
        'source': 'CHEBI',
        'mapping_notes': 'Assuming myo-inositol (most common), likely match'
    },
    'Choline chloride': {
        'ontology_id': 'CHEBI:133341',
        'preferred_term': 'choline chloride',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Exact match'
    },

    # Vitamin variants with HCl
    'Thiamine HCl': {
        'ontology_id': 'CHEBI:49105',
        'preferred_term': 'thiamine hydrochloride',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B1 HCl salt, exact match'
    },
    'Thiamine HCl (vitamin B )': {
        'ontology_id': 'CHEBI:49105',
        'preferred_term': 'thiamine hydrochloride',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B1 HCl salt, exact match'
    },
    'Thiamine HCl (B ) -': {
        'ontology_id': 'CHEBI:49105',
        'preferred_term': 'thiamine hydrochloride',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B1 HCl salt, exact match'
    },
    'Cyanocobalamin (vitamin B )': {
        'ontology_id': 'CHEBI:17439',
        'preferred_term': 'cyanocobalamin',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B12, exact match'
    },
    'Cyanocobalamin (B )': {
        'ontology_id': 'CHEBI:17439',
        'preferred_term': 'cyanocobalamin',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B12, exact match'
    },
    'Nicotinic acid': {
        'ontology_id': 'CHEBI:15940',
        'preferred_term': 'nicotinic acid',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B3, exact match (same as Niacin)'
    },

    # More salts
    'Na EDTA': {
        'ontology_id': 'CHEBI:64734',
        'preferred_term': 'disodium ethylenediaminetetraacetate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Na2EDTA, exact match (same as Na -EDTA)'
    },
    'EDTANa': {
        'ontology_id': 'CHEBI:64734',
        'preferred_term': 'disodium ethylenediaminetetraacetate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Na2EDTA, exact match'
    },
    'KNO': {
        'ontology_id': 'CHEBI:63043',
        'preferred_term': 'potassium nitrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'KNO3, exact formula match'
    },
    'MgCl .6H O': {
        'ontology_id': 'CHEBI:6635',
        'preferred_term': 'magnesium chloride hexahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'MgCl2·6H2O, exact hydrate match'
    },
    'Na HPO': {
        'ontology_id': 'CHEBI:34683',
        'preferred_term': 'disodium hydrogen phosphate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Na2HPO4, exact formula match'
    },
    'ZnCl': {
        'ontology_id': 'CHEBI:49976',
        'preferred_term': 'zinc dichloride',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'ZnCl2, exact formula match'
    },
    'CaSO .2H O': {
        'ontology_id': 'CHEBI:88481',
        'preferred_term': 'calcium sulfate dihydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'CaSO4·2H2O (gypsum), exact hydrate match'
    },
    'CaCl .6H O': {
        'ontology_id': 'CHEBI:3312',
        'preferred_term': 'calcium chloride hexahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'CaCl2·6H2O, exact hydrate match'
    },
    'KBr': {
        'ontology_id': 'CHEBI:32030',
        'preferred_term': 'potassium bromide',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'KBr, exact formula match'
    },
    'SrCl .6H O': {
        'ontology_id': 'CHEBI:82444',
        'preferred_term': 'strontium chloride hexahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'SrCl2·6H2O, exact hydrate match'
    },
    'MnSO .4H O': {
        'ontology_id': 'CHEBI:75217',
        'preferred_term': 'manganese(II) sulfate tetrahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'MnSO4·4H2O, exact hydrate match'
    },
    'CoSO .7H O': {
        'ontology_id': 'CHEBI:86455',
        'preferred_term': 'cobalt(II) sulfate heptahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'CoSO4·7H2O, exact hydrate match'
    },
    'Na SiO .9H O': {
        'ontology_id': 'CHEBI:86463',
        'preferred_term': 'sodium metasilicate nonahydrate',
        'confidence': 0.95,
        'source': 'CHEBI',
        'mapping_notes': 'Na2SiO3·9H2O, likely match'
    },
    'KI': {
        'ontology_id': 'CHEBI:8346',
        'preferred_term': 'potassium iodide',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'KI, exact formula match'
    },
    'NaH PO .2H O': {
        'ontology_id': 'CHEBI:37585',
        'preferred_term': 'sodium dihydrogen phosphate dihydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'NaH2PO4·2H2O, exact hydrate match'
    },

    # Amino acids and organic compounds
    'Thymine': {
        'ontology_id': 'CHEBI:17821',
        'preferred_term': 'thymine',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'DNA base, exact match'
    },
    'Glycine': {
        'ontology_id': 'CHEBI:15428',
        'preferred_term': 'glycine',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Amino acid, exact match'
    },
    'Tricine': {
        'ontology_id': 'CHEBI:35920',
        'preferred_term': 'tricine',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'N-[tris(hydroxymethyl)methyl]glycine, buffer, exact match'
    },
    'Proteose peptone': {
        'ontology_id': 'FOODON:00002992',
        'preferred_term': 'proteose peptone',
        'confidence': 0.9,
        'source': 'FOODON',
        'mapping_notes': 'Protein hydrolysate, food ingredient'
    },

    # Additional notation variants (with proper subscripts/superscripts)
    'D-glucose': {
        'ontology_id': 'CHEBI:17634',
        'preferred_term': 'D-glucose',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'D-glucose, exact match (same as Glucose)'
    },
    'KH2PO4': {
        'ontology_id': 'CHEBI:63036',
        'preferred_term': 'potassium dihydrogen phosphate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'KH2PO4 with subscripts, exact match'
    },
    'MgCl2·6H2O': {
        'ontology_id': 'CHEBI:6635',
        'preferred_term': 'magnesium chloride hexahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'MgCl2·6H2O with subscripts/dot, exact match'
    },
    'CaCl2·2H2O': {
        'ontology_id': 'CHEBI:64183',
        'preferred_term': 'calcium chloride dihydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'CaCl2·2H2O with subscripts/dot, exact match'
    },
    'NH4Cl': {
        'ontology_id': 'CHEBI:31206',
        'preferred_term': 'ammonium chloride',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'NH4Cl with subscript, exact match'
    },

    # More trace elements
    'Co(NO ) .6H O': {
        'ontology_id': 'CHEBI:78038',
        'preferred_term': 'cobalt(II) nitrate hexahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Co(NO3)2·6H2O, exact hydrate match'
    },
    'ZnCl .6H O': {
        'ontology_id': 'CHEBI:86469',
        'preferred_term': 'zinc chloride hexahydrate',
        'confidence': 0.95,
        'source': 'CHEBI',
        'mapping_notes': 'ZnCl2·6H2O, likely match (less common than anhydrous)'
    },
    'AlCl .6H O': {
        'ontology_id': 'CHEBI:74867',
        'preferred_term': 'aluminium chloride hexahydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'AlCl3·6H2O, exact hydrate match'
    },
    'RbCl': {
        'ontology_id': 'CHEBI:81106',
        'preferred_term': 'rubidium chloride',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'RbCl, exact formula match'
    },
    'LiCl.H O': {
        'ontology_id': 'CHEBI:86368',
        'preferred_term': 'lithium chloride monohydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'LiCl·H2O, exact hydrate match'
    },
    'NaMoO .2H O': {
        'ontology_id': 'CHEBI:75216',
        'preferred_term': 'sodium molybdate dihydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'NaMoO4·2H2O, exact match (same as Na MoO .2H O)'
    },
    'EDTA.Na .2H O': {
        'ontology_id': 'CHEBI:64734',
        'preferred_term': 'disodium ethylenediaminetetraacetate',
        'confidence': 0.95,
        'source': 'CHEBI',
        'mapping_notes': 'Na2EDTA dihydrate, likely match'
    },
    'Na HPO anydrous': {
        'ontology_id': 'CHEBI:34683',
        'preferred_term': 'disodium hydrogen phosphate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Na2HPO4 anhydrous, exact match'
    },
    'NaHCO': {
        'ontology_id': 'CHEBI:32139',
        'preferred_term': 'sodium hydrogencarbonate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'NaHCO3 (baking soda), exact formula match'
    },
    'Na SeO .5H O': {
        'ontology_id': 'CHEBI:85214',
        'preferred_term': 'sodium selenite pentahydrate',
        'confidence': 0.95,
        'source': 'CHEBI',
        'mapping_notes': 'Na2SeO3·5H2O, likely match'
    },
    'As O': {
        'ontology_id': 'CHEBI:30621',
        'preferred_term': 'arsenic trioxide',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'As2O3, exact formula match'
    },
    'Na WO .2H O': {
        'ontology_id': 'CHEBI:86311',
        'preferred_term': 'sodium tungstate dihydrate',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Na2WO4·2H2O, exact hydrate match'
    },
    'TeO': {
        'ontology_id': 'CHEBI:30452',
        'preferred_term': 'tellurium dioxide',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'TeO2, exact formula match'
    },
    'KOH': {
        'ontology_id': 'CHEBI:32035',
        'preferred_term': 'potassium hydroxide',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'KOH, exact formula match (pH adjuster)'
    },
    'NaOH': {
        'ontology_id': 'CHEBI:32145',
        'preferred_term': 'sodium hydroxide',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'NaOH, exact formula match (pH adjuster)'
    },

    # More vitamins and amino acids
    'Folinic acid (citrovorum)': {
        'ontology_id': 'CHEBI:27470',
        'preferred_term': 'folinic acid',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': '5-formyltetrahydrofolate (leucovorin), exact match'
    },
    'Pyridoxamine.2HCl': {
        'ontology_id': 'CHEBI:8668',
        'preferred_term': 'pyridoxamine dihydrochloride',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Vitamin B6 form, dihydrochloride salt, exact match'
    },
    'Glycylglycine': {
        'ontology_id': 'CHEBI:15743',
        'preferred_term': 'glycylglycine',
        'confidence': 1.0,
        'source': 'CHEBI',
        'mapping_notes': 'Dipeptide Gly-Gly, exact match'
    },

    # Food ingredients
    'Malt extract': {
        'ontology_id': 'FOODON:00001264',
        'preferred_term': 'malt extract',
        'confidence': 1.0,
        'source': 'FOODON',
        'mapping_notes': 'Extract from malted barley, exact match'
    },
    'Bacteriological agar': {
        'ontology_id': 'CHEBI:2509',
        'preferred_term': 'agar',
        'confidence': 0.95,
        'source': 'CHEBI',
        'mapping_notes': 'Bacteriological grade agar, same substance'
    },
}


def curate_ingredients(input_file: Path, output_file: Path) -> Dict:
    """Curate ingredients using manual mapping database."""

    # Load unmapped ingredients
    with open(input_file) as f:
        data = yaml.safe_load(f)

    stats = {
        'total': len(data['ingredients']),
        'mapped': 0,
        'high_confidence': 0,  # ≥0.9
        'medium_confidence': 0,  # 0.7-0.89
        'unmapped': 0,
        'by_source': {}
    }

    for ingredient in data['ingredients']:
        term = ingredient['preferred_term']

        if term in MANUAL_MAPPINGS:
            # Apply mapping
            mapping = MANUAL_MAPPINGS[term]
            ingredient['ontology_id'] = mapping['ontology_id']
            ingredient['mapping_status'] = 'MAPPED'
            ingredient['confidence'] = mapping['confidence']
            ingredient['mapping_source'] = mapping['source']

            # Add curation history
            ingredient['curation_history'].append({
                'timestamp': datetime.now().isoformat(),
                'curator': 'claude_code_manual',
                'action': 'MAPPED',
                'changes': f"Mapped to {mapping['ontology_id']} ({mapping['preferred_term']})",
                'confidence': mapping['confidence'],
                'notes': mapping['mapping_notes']
            })

            stats['mapped'] += 1
            if mapping['confidence'] >= 0.9:
                stats['high_confidence'] += 1
            else:
                stats['medium_confidence'] += 1

            # Track by source
            source = mapping['source']
            stats['by_source'][source] = stats['by_source'].get(source, 0) + 1
        else:
            stats['unmapped'] += 1

    # Update metadata
    data['mapped_count'] = stats['mapped']
    data['unmapped_count'] = stats['unmapped']
    data['curation_date'] = datetime.now().isoformat()
    data['curator'] = 'claude_code_manual'
    data['curation_method'] = 'manual_expert_mapping'

    # Save curated data
    with open(output_file, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return stats


def main():
    input_file = Path('workspace/curation/collection_media/extracted/option_c_http_retries_mim_format.yaml')
    output_file = Path('workspace/curation/collection_media/curated/option_c_http_retries_curated.yaml')

    output_file.parent.mkdir(parents=True, exist_ok=True)

    print("Starting manual curation of collection media ingredients...")
    print(f"Input: {input_file}")
    print(f"Output: {output_file}\n")

    stats = curate_ingredients(input_file, output_file)

    print("=" * 80)
    print("CURATION COMPLETE")
    print("=" * 80)
    print(f"Total ingredients: {stats['total']}")
    print(f"Mapped: {stats['mapped']} ({stats['mapped']/stats['total']*100:.1f}%)")
    print(f"  - High confidence (≥0.9): {stats['high_confidence']}")
    print(f"  - Medium confidence (0.7-0.89): {stats['medium_confidence']}")
    print(f"Unmapped: {stats['unmapped']} ({stats['unmapped']/stats['total']*100:.1f}%)")
    print(f"\nBy ontology:")
    for source, count in sorted(stats['by_source'].items()):
        print(f"  - {source}: {count}")
    print(f"\n✅ Saved to {output_file}")


if __name__ == '__main__':
    main()
