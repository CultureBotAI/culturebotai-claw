#!/usr/bin/env python3
"""Create complex formulations database and clean up unmapped list."""

import yaml
from pathlib import Path
from datetime import datetime

# Items to remove from unmapped (media, solutions, and metadata)
ITEMS_TO_REMOVE = [
    # Metadata placeholders
    'See source for composition',
    'Full composition available at source database',

    # Complete media (14)
    'Allen Medium',
    'Beijerinck\'s Solution',
    'BG-11 Medium',
    'Bold 1NV Medium',
    'Bristol Medium',
    'DYIII Medium',
    'Erdschreiber\'s Medium',
    'Euglena Medium',
    'F/2 Medium',
    'Modified Bold 3N Medium',
    'Modified COMBO Medium',
    'Volvox Medium',
    'Waris Medium',

    # Stock solutions (27)
    'A+ Trace Components',
    'Algal Trace Elements Solution',
    'BG-11 Trace Metals Solution',
    'Bold Trace Stock',
    'Boron Stock',
    'Chelated Iron Solution',
    'Chu Stock Solution',
    'DAS Macro Solution',
    'DAS Vitamin Cocktail',
    'DYV Metal Solution',
    'EDTA Stock',
    'Enrichment Solution for Seawater Medium',
    'G9 Trace Metals for J medium',
    'Hunter\'s Trace Stock Solution',
    'Iron Stock',
    'Macro Component 1 for J Medium',
    'Macro Component 2 for J medium',
    'Minor Nutrients',
    'Modified P-IV chelated Micronutrient Solution',
    'MWC Metal Solution',
    'P-II Metal Solution',
    'P-IV Metal Solution',
    'Phosphate Buffer Stock Solution',
    'Spir solution',
    'Trace Metals Solution',
    'WC Trace Elements Solution',
]

# Complex formulations data structure
FORMULATIONS = {
    'metadata': {
        'version': '1.0',
        'created_date': '2026-03-27',
        'description': 'Complex media formulations and stock solutions that are multi-component mixtures',
        'note': 'These are not single ingredients but complete formulations. Individual components may be mapped in mapped_ingredients.yaml',
        'source': 'Research compiled from UTEX, CCAP, NCMA, SAG, and peer-reviewed literature',
        'research_document': 'ALGAL_MEDIA_RESEARCH_SUMMARY.md'
    },

    'complete_media': [
        {
            'name': 'BG-11 Medium',
            'category': 'complete_medium',
            'subcategory': 'freshwater',
            'purpose': 'Freshwater, soil, thermal, and marine cyanobacteria culture',
            'organisms': ['cyanobacteria'],
            'key_components': [
                'NaNO3 (sodium nitrate)',
                'K2HPO4 (dipotassium phosphate)',
                'MgSO4·7H2O (magnesium sulfate)',
                'CaCl2·2H2O (calcium chloride)',
                'Na2CO3 (sodium carbonate)',
                'Citric acid',
                'Ferric ammonium citrate',
                'EDTA (disodium salt)',
                'BG-11 Trace Metals Solution'
            ],
            'references': [
                'UTEX Culture Collection protocols',
                'Allen, M.M. and Stanier, R.Y. (1968)',
                'Hughes et al. (1958)'
            ],
            'occurrence_statistics': {}
        },
        {
            'name': 'Bold 1NV Medium',
            'category': 'complete_medium',
            'subcategory': 'freshwater',
            'purpose': 'General purpose freshwater medium for xenic cultures',
            'organisms': ['green algae', 'various algae classes'],
            'key_components': [
                'NaNO3',
                'CaCl2·2H2O',
                'MgSO4·7H2O',
                'K2HPO4',
                'KH2PO4',
                'NaCl',
                'Bold Trace Stock Solution',
                'Vitamins (thiamine, biotin, B12)'
            ],
            'references': [
                'UTEX Culture Collection protocols',
                'Bold, H.C. (1949)'
            ],
            'occurrence_statistics': {}
        },
        {
            'name': 'Bristol Medium',
            'category': 'complete_medium',
            'subcategory': 'freshwater',
            'purpose': 'General purpose freshwater medium for green algae (Chlorophyta)',
            'organisms': ['Chlorophyta', 'green algae'],
            'key_components': [
                'Standard freshwater nutrients',
                'Simple reliable formulation'
            ],
            'references': [
                'UTEX Culture Collection protocols',
                'Cyanosite Growth Media database'
            ],
            'occurrence_statistics': {}
        },
        {
            'name': 'Modified Bold 3N Medium',
            'category': 'complete_medium',
            'subcategory': 'freshwater',
            'purpose': 'General purpose freshwater medium for blue-greens and red algae',
            'organisms': ['cyanobacteria', 'red algae'],
            'key_components': [
                '3-fold nitrogen compared to standard Bold\'s',
                'pH 6.2 (acidic)',
                'Vitamins'
            ],
            'references': [
                'UTEX Culture Collection protocols',
                'CCAP media recipes'
            ],
            'occurrence_statistics': {}
        },
        {
            'name': 'F/2 Medium',
            'category': 'complete_medium',
            'subcategory': 'marine',
            'purpose': 'Coastal marine algae, especially diatoms',
            'organisms': ['diatoms', 'marine algae'],
            'key_components': [
                'Filtered seawater base',
                'NaNO3 (75 mg/L)',
                'NaH2PO4·H2O (5 mg/L)',
                'Na2SiO3·9H2O (30 mg/L)',
                'F/2 Trace Metals Solution',
                'F/2 Vitamins Solution'
            ],
            'references': [
                'NCMA protocols',
                'Guillard, R.R.L. and Ryther, J.H. (1962)',
                'Guillard, R.R.L. (1975)'
            ],
            'occurrence_statistics': {}
        },
        {
            'name': 'Allen Medium',
            'category': 'complete_medium',
            'subcategory': 'freshwater',
            'purpose': 'Freshwater cyanobacteria, axenic and xenic cultures',
            'organisms': ['cyanobacteria'],
            'key_components': [
                'Similar to BG-11',
                'Modified for axenic culture'
            ],
            'references': [
                'UTEX Culture Collection protocols',
                'Allen (1968)'
            ],
            'occurrence_statistics': {}
        },
        {
            'name': 'Volvox Medium',
            'category': 'complete_medium',
            'subcategory': 'freshwater',
            'purpose': 'Volvox and colonial green algae',
            'organisms': ['Volvox', 'colonial green algae'],
            'key_components': [
                'Specialized for colonial forms',
                'Modified nutrient ratios'
            ],
            'references': [
                'UTEX Culture Collection protocols'
            ],
            'occurrence_statistics': {}
        },
        {
            'name': 'Waris Medium',
            'category': 'complete_medium',
            'subcategory': 'freshwater',
            'purpose': 'Desmids',
            'organisms': ['desmids'],
            'key_components': [
                'Low nutrient formulation',
                'Specialized for desmids'
            ],
            'references': [
                'UTEX Culture Collection protocols',
                'Waris (1950)'
            ],
            'occurrence_statistics': {}
        },
        {
            'name': 'Euglena Medium',
            'category': 'complete_medium',
            'subcategory': 'freshwater',
            'purpose': 'Euglena and Chlorogonium',
            'organisms': ['Euglena', 'Chlorogonium'],
            'key_components': [
                'Organic nutrients',
                'Specialized for mixotrophs'
            ],
            'references': [
                'UTEX Culture Collection protocols'
            ],
            'occurrence_statistics': {}
        },
        {
            'name': 'Erdschreiber\'s Medium',
            'category': 'complete_medium',
            'subcategory': 'marine',
            'purpose': 'General marine algae',
            'organisms': ['marine algae'],
            'key_components': [
                'Seawater base',
                'Soil extract',
                'Simple formulation'
            ],
            'references': [
                'UTEX Culture Collection protocols',
                'Erdschreiber (1952)'
            ],
            'occurrence_statistics': {}
        },
        {
            'name': 'DYIII Medium',
            'category': 'complete_medium',
            'subcategory': 'freshwater',
            'purpose': 'Chrysophytes and cryptomonads',
            'organisms': ['chrysophytes', 'cryptomonads'],
            'key_components': [
                'Low phosphate',
                'Specialized for oligotrophs'
            ],
            'references': [
                'UTEX Culture Collection protocols',
                'Andersen (2005)'
            ],
            'occurrence_statistics': {}
        },
        {
            'name': 'Modified COMBO Medium',
            'category': 'complete_medium',
            'subcategory': 'freshwater',
            'purpose': 'Algae and zooplankton co-culture',
            'organisms': ['algae', 'zooplankton'],
            'key_components': [
                'Balanced nutrients for co-culture',
                'Modified for mixed communities'
            ],
            'references': [
                'UTEX Culture Collection protocols',
                'Kilham et al. (1998)'
            ],
            'occurrence_statistics': {}
        },
        {
            'name': 'Beijerinck\'s Solution',
            'category': 'complete_medium',
            'subcategory': 'freshwater',
            'purpose': 'General freshwater algae',
            'organisms': ['freshwater algae'],
            'key_components': [
                'Simple nutrient formulation',
                'Historic medium'
            ],
            'references': [
                'UTEX Culture Collection protocols',
                'Beijerinck (1890s)'
            ],
            'occurrence_statistics': {}
        },
    ],

    'stock_solutions': [
        {
            'name': 'BG-11 Trace Metals Solution',
            'category': 'stock_solution',
            'subcategory': 'trace_metals',
            'purpose': 'Micronutrient supplement for BG-11 Medium',
            'key_components': [
                'H3BO3 (boric acid)',
                'MnCl2·4H2O (manganese chloride)',
                'ZnSO4·7H2O (zinc sulfate)',
                'Na2MoO4·2H2O (sodium molybdate)',
                'CuSO4·5H2O (copper sulfate)',
                'Co(NO3)2·6H2O (cobalt nitrate)'
            ],
            'usage': '1 mL per liter of BG-11 Medium',
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Bold Trace Stock',
            'category': 'stock_solution',
            'subcategory': 'trace_metals',
            'purpose': 'Micronutrient supplement for Bold media',
            'key_components': [
                'ZnSO4·7H2O',
                'MnCl2·4H2O',
                'MoO3',
                'CuSO4·5H2O',
                'Co(NO3)2·6H2O',
                'H2SO4 (1 N)'
            ],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'P-IV Metal Solution',
            'category': 'stock_solution',
            'subcategory': 'trace_metals',
            'purpose': 'EDTA-chelated trace metals for various media',
            'key_components': [
                'Na2EDTA·2H2O',
                'FeCl3·6H2O',
                'MnCl2·4H2O',
                'ZnCl2',
                'CoCl2·6H2O',
                'Na2MoO4·2H2O'
            ],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'P-II Metal Solution',
            'category': 'stock_solution',
            'subcategory': 'trace_metals',
            'purpose': 'Alternative trace metal formulation',
            'key_components': [
                'Na2EDTA·2H2O',
                'H3BO3',
                'FeCl3·6H2O',
                'MnSO4·H2O',
                'ZnSO4·7H2O',
                'CoCl2·6H2O'
            ],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'WC Trace Elements Solution',
            'category': 'stock_solution',
            'subcategory': 'trace_metals',
            'purpose': 'Trace metals for Woods Hole Culture Medium',
            'key_components': [
                'Na2EDTA·2H2O',
                'FeCl3·6H2O',
                'CuSO4·5H2O',
                'ZnSO4·7H2O',
                'CoCl2·6H2O',
                'MnCl2·4H2O',
                'Na2MoO4·2H2O',
                'Na3VO4 (vanadium)'
            ],
            'references': ['UTEX Culture Collection protocols', 'Guillard and Lorenzen (1972)'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Hunter\'s Trace Stock Solution',
            'category': 'stock_solution',
            'subcategory': 'trace_metals',
            'purpose': 'Comprehensive trace metal solution',
            'key_components': [
                'Na2EDTA·2H2O (50 g/L)',
                'ZnSO4·7H2O (22 g/L)',
                'H3BO3 (11.4 g/L)',
                'MnCl2·4H2O (5.1 g/L)',
                'FeSO4·7H2O (5 g/L)',
                'CoCl2·6H2O (1.6 g/L)',
                'CuSO4·5H2O (1.16 g/L)',
                '(NH4)6Mo7O24·4H2O (1.1 g/L)'
            ],
            'references': ['UTEX Culture Collection protocols', 'Chlamydomonas Resource Center'],
            'occurrence_statistics': {}
        },
        {
            'name': 'F/2 Vitamins',
            'category': 'stock_solution',
            'subcategory': 'vitamins',
            'purpose': 'Vitamin supplement for F/2 Medium',
            'key_components': [
                'Thiamine HCl (vitamin B1)',
                'Biotin (vitamin H)',
                'Cyanocobalamin (vitamin B12)'
            ],
            'usage': '0.5 mL per liter of F/2 Medium',
            'references': ['NCMA protocols', 'Guillard (1975)'],
            'occurrence_statistics': {}
        },
        {
            'name': 'DAS Vitamin Cocktail',
            'category': 'stock_solution',
            'subcategory': 'vitamins',
            'purpose': 'Comprehensive vitamin mixture',
            'key_components': [
                'Thiamine',
                'Biotin',
                'Cyanocobalamin',
                'PABA (para-aminobenzoic acid)',
                'Additional B vitamins'
            ],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'DAS Macro Solution',
            'category': 'stock_solution',
            'subcategory': 'macronutrients',
            'purpose': 'Macronutrient stock for DAS Medium',
            'key_components': [
                'Nitrate',
                'Phosphate'
            ],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Macro Component 1 for J Medium',
            'category': 'stock_solution',
            'subcategory': 'macronutrients',
            'purpose': 'Primary macronutrient stock for J Medium',
            'key_components': [
                'Nitrogen source',
                'Phosphorus source',
                'Potassium source',
                'Tricine buffer'
            ],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Chu Stock Solution',
            'category': 'stock_solution',
            'subcategory': 'complete_nutrients',
            'purpose': 'Complete macro and micronutrient stock',
            'key_components': [
                'Macronutrients',
                'Micronutrients',
                'Complete formulation'
            ],
            'references': ['UTEX Culture Collection protocols', 'Chu (1942)'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Chelated Iron Solution',
            'category': 'stock_solution',
            'subcategory': 'iron',
            'purpose': 'Iron supplement with EDTA chelation',
            'key_components': [
                'FeCl3 or FeSO4',
                'Na2EDTA·2H2O'
            ],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Iron Stock',
            'category': 'stock_solution',
            'subcategory': 'iron',
            'purpose': 'General iron supplement',
            'key_components': [
                'Iron salt (various forms)',
                'May include chelating agent'
            ],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'EDTA Stock',
            'category': 'stock_solution',
            'subcategory': 'chelating_agent',
            'purpose': 'Chelating agent for preventing metal precipitation',
            'key_components': [
                'Na2EDTA·2H2O'
            ],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Boron Stock',
            'category': 'stock_solution',
            'subcategory': 'micronutrient',
            'purpose': 'Boron supplement',
            'key_components': [
                'H3BO3 (boric acid)'
            ],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Phosphate Buffer Stock Solution',
            'category': 'stock_solution',
            'subcategory': 'buffer',
            'purpose': 'pH buffering',
            'key_components': [
                'K2HPO4',
                'KH2PO4'
            ],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        # Additional entries for remaining solutions
        {
            'name': 'MWC Metal Solution',
            'category': 'stock_solution',
            'subcategory': 'trace_metals',
            'purpose': 'Trace metals for Modified WC Medium',
            'key_components': [
                'Na2EDTA', 'H3BO3', 'FeCl3·6H2O', 'MnCl2·4H2O',
                'ZnSO4·7H2O', 'CoCl2·6H2O', 'Na2MoO4·2H2O'
            ],
            'references': ['CCAP Modified WC Medium protocol'],
            'occurrence_statistics': {}
        },
        {
            'name': 'DYV Metal Solution',
            'category': 'stock_solution',
            'subcategory': 'trace_metals',
            'purpose': 'Trace metals for DYV Medium (chrysophytes/synurophytes)',
            'key_components': ['Specialized for chrysophyte requirements'],
            'references': ['UTEX Culture Collection protocols', 'Andersen (2005)'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Algal Trace Elements Solution',
            'category': 'stock_solution',
            'subcategory': 'trace_metals',
            'purpose': 'General algal micronutrients',
            'key_components': ['Trace metals including selenium and vanadium'],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'A+ Trace Components',
            'category': 'stock_solution',
            'subcategory': 'trace_metals',
            'purpose': 'Trace supplement for A+ medium',
            'key_components': ['Micronutrient mixture'],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'G9 Trace Metals for J medium',
            'category': 'stock_solution',
            'subcategory': 'trace_metals',
            'purpose': 'Trace metals for J Medium',
            'key_components': ['Includes iodide'],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Modified P-IV chelated Micronutrient Solution',
            'category': 'stock_solution',
            'subcategory': 'trace_metals',
            'purpose': 'Chelated trace metals for marine media',
            'key_components': ['Enhanced chelation for marine conditions'],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Enrichment Solution for Seawater Medium',
            'category': 'stock_solution',
            'subcategory': 'complete_nutrients',
            'purpose': 'Nutrient enrichment for seawater-based media',
            'key_components': ['Macronutrients and micronutrients for marine media'],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Macro Component 2 for J medium',
            'category': 'stock_solution',
            'subcategory': 'macronutrients',
            'purpose': 'Secondary macronutrient stock for J Medium',
            'key_components': ['Macronutrient mixture'],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Minor Nutrients',
            'category': 'stock_solution',
            'subcategory': 'complete_nutrients',
            'purpose': 'General micronutrient mixture',
            'key_components': ['Micronutrients and vitamins'],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Spir solution',
            'category': 'stock_solution',
            'subcategory': 'specialized',
            'purpose': 'Nutrient solution for Spirulina medium',
            'key_components': ['Alkaline carbonates and nutrients'],
            'references': ['UTEX Culture Collection protocols'],
            'occurrence_statistics': {}
        },
        {
            'name': 'Trace Metals Solution',
            'category': 'stock_solution',
            'subcategory': 'trace_metals',
            'purpose': 'Generic trace metal supplement',
            'key_components': ['EDTA-chelated micronutrients'],
            'references': ['UTEX Culture Collection protocols', 'Schlösser (1994)'],
            'occurrence_statistics': {}
        },
    ]
}

def main():
    workspace = Path('workspace')
    mim_root = Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech'

    # Create complex formulations file
    formulations_file = workspace / 'reference/complex_formulations.yaml'
    formulations_file.parent.mkdir(parents=True, exist_ok=True)

    with open(formulations_file, 'w') as f:
        yaml.dump(FORMULATIONS, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"✓ Created complex formulations: {formulations_file}")
    print(f"  - {len(FORMULATIONS['complete_media'])} complete media")
    print(f"  - {len(FORMULATIONS['stock_solutions'])} stock solutions")

    # Remove from unmapped
    unmapped_file = mim_root / 'data/curated/unmapped_ingredients.yaml'

    with open(unmapped_file) as f:
        unmapped_data = yaml.safe_load(f)

    original_count = len(unmapped_data['ingredients'])
    print(f"\nOriginal unmapped count: {original_count}")

    # Filter out items
    remaining = []
    removed_count = 0

    for ing in unmapped_data['ingredients']:
        preferred_term = ing.get('preferred_term', '')
        if preferred_term in ITEMS_TO_REMOVE:
            removed_count += 1
            print(f"  Removing: {preferred_term}")
        else:
            remaining.append(ing)

    # Update counts
    unmapped_data['ingredients'] = remaining
    unmapped_data['total_count'] = len(remaining)
    unmapped_data['unmapped_count'] = len(remaining)

    # Write back
    with open(unmapped_file, 'w') as f:
        yaml.dump(unmapped_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n✓ Removed {removed_count} items from unmapped list")
    print(f"✓ Remaining unmapped: {len(remaining)}")
    print(f"✓ Updated {unmapped_file}")

    print(f"\n✓ Complex formulations documented in: {formulations_file}")
    print(f"✓ Research details available in: ALGAL_MEDIA_RESEARCH_SUMMARY.md")

if __name__ == '__main__':
    main()
