#!/usr/bin/env python3
"""
Enrich FEBA ingredient ontology mappings using CAS-RN lookups.

Queries ChEBI API to find CHEBI IDs for ingredients that have CAS-RN
but no ontology term ID, then updates CultureMech media files.
"""

import yaml
import requests
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List
import argparse
from xml.etree import ElementTree as ET


class ChEBIEnricher:
    """Enriches ingredient ontology mappings via ChEBI API."""

    def __init__(self):
        self.stats = {
            'total_processed': 0,
            'chebi_found': 0,
            'chebi_not_found': 0,
            'api_errors': 0
        }
        self.session = requests.Session()
        # ChEBI REST API endpoint
        self.base_url = "https://www.ebi.ac.uk/webservices/chebi/2.0/test"
        self.results = {}

    def query_chebi_by_cas(self, cas_rn: str) -> Optional[Dict]:
        """
        Query ChEBI API for compound using CAS Registry Number.

        ChEBI REST API: getLiteEntity by CAS-RN
        Returns: Dict with chebiId, chebiAsciiName, or None
        """
        try:
            # ChEBI SOAP-like REST endpoint
            url = f"{self.base_url}/getLiteEntity"

            # Build SOAP-style request (ChEBI uses SOAP over REST)
            soap_body = f'''<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:tns="https://www.ebi.ac.uk/webservices/chebi">
  <soap:Body>
    <tns:getLiteEntity>
      <tns:search>{cas_rn}</tns:search>
      <tns:searchCategory>REGISTRY NUMBER</tns:searchCategory>
      <tns:maximumResults>1</tns:maximumResults>
      <tns:stars>THREE ONLY</tns:stars>
    </tns:getLiteEntity>
  </soap:Body>
</soap:Envelope>'''

            headers = {
                'Content-Type': 'text/xml; charset=utf-8',
                'SOAPAction': ''
            }

            time.sleep(0.5)  # Rate limiting
            response = self.session.post(
                url,
                data=soap_body,
                headers=headers,
                timeout=10
            )

            if response.status_code != 200:
                self.stats['api_errors'] += 1
                return None

            # Parse SOAP response
            root = ET.fromstring(response.content)

            # Find chebiId and name in response
            ns = {
                'soap': 'http://schemas.xmlsoap.org/soap/envelope/',
                'chebi': 'https://www.ebi.ac.uk/webservices/chebi'
            }

            entity = root.find('.//chebi:return', ns)
            if entity is None:
                return None

            chebi_id = entity.find('chebi:chebiId', ns)
            chebi_name = entity.find('chebi:chebiAsciiName', ns)

            if chebi_id is not None and chebi_id.text:
                return {
                    'chebi_id': f"CHEBI:{chebi_id.text.replace('CHEBI:', '')}",
                    'chebi_name': chebi_name.text if chebi_name is not None else '',
                    'source': 'ChEBI API via CAS-RN'
                }

            return None

        except ET.ParseError:
            self.stats['api_errors'] += 1
            return None
        except Exception as e:
            self.stats['api_errors'] += 1
            return None

    def query_chebi_simple(self, cas_rn: str) -> Optional[Dict]:
        """
        Simpler approach: Query ChEBI using their search endpoint.

        Alternative to SOAP API - uses PubChem as intermediary.
        """
        try:
            # Use PubChem to get ChEBI ID via CAS-RN
            import urllib.parse

            # First get PubChem CID from CAS
            encoded_cas = urllib.parse.quote(cas_rn)
            pubchem_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded_cas}/cids/JSON"

            time.sleep(0.21)
            response = self.session.get(pubchem_url, timeout=10)

            if response.status_code != 200:
                return None

            data = response.json()
            cids = data.get('IdentifierList', {}).get('CID', [])

            if not cids:
                return None

            cid = cids[0]

            # Get ChEBI xref from PubChem
            xref_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/xrefs/RegistryID/JSON"

            time.sleep(0.21)
            response = self.session.get(xref_url, timeout=10)

            if response.status_code != 200:
                return None

            xref_data = response.json()
            registry_ids = xref_data.get('InformationList', {}).get('Information', [{}])[0].get('RegistryID', [])

            # Look for ChEBI ID
            for reg_id in registry_ids:
                if reg_id.startswith('CHEBI:'):
                    # Get ChEBI name
                    chebi_num = reg_id.replace('CHEBI:', '')

                    # Query ChEBI for name (if needed)
                    return {
                        'chebi_id': reg_id,
                        'chebi_name': '',  # Will be filled from PubChem if available
                        'source': 'PubChem ChEBI xref via CAS-RN'
                    }

            return None

        except Exception as e:
            self.stats['api_errors'] += 1
            return None

    def process_ingredient(self, ingredient_name: str, cas_rn: str) -> Optional[Dict]:
        """
        Process a single ingredient - query ChEBI API.

        Returns: Dict with chebi_id, chebi_name, source
        """
        self.stats['total_processed'] += 1

        # Try simple PubChem approach first
        result = self.query_chebi_simple(cas_rn)

        if result:
            self.stats['chebi_found'] += 1
            self.results[ingredient_name] = {
                'cas_rn': cas_rn,
                'chebi_id': result['chebi_id'],
                'chebi_name': result['chebi_name'],
                'source': result['source']
            }
            return result

        self.stats['chebi_not_found'] += 1
        return None

    def save_results(self, output_file: Path):
        """Save enrichment results to YAML."""
        output_file.parent.mkdir(parents=True, exist_ok=True)

        report = {
            'metadata': {
                'date': datetime.now().isoformat(),
                'total_processed': self.stats['total_processed'],
                'chebi_found': self.stats['chebi_found'],
                'success_rate': f"{(self.stats['chebi_found'] / self.stats['total_processed'] * 100):.1f}%" if self.stats['total_processed'] > 0 else '0%'
            },
            'statistics': self.stats,
            'enrichments': self.results
        }

        with open(output_file, 'w') as f:
            yaml.dump(report, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        print(f"\n✅ Results saved to: {output_file}")

    def print_stats(self):
        """Print enrichment statistics."""
        print("\n" + "=" * 80)
        print("CHEBI ENRICHMENT STATISTICS")
        print("=" * 80)
        print(f"Total ingredients processed: {self.stats['total_processed']}")
        print(f"  ChEBI ID found: {self.stats['chebi_found']}")
        print(f"  ChEBI ID not found: {self.stats['chebi_not_found']}")
        print(f"  API errors: {self.stats['api_errors']}")

        if self.stats['total_processed'] > 0:
            success_rate = (self.stats['chebi_found'] / self.stats['total_processed']) * 100
            print(f"\nSuccess rate: {success_rate:.1f}%")


def load_cas_rn_mappings(cas_results_file: Path) -> Dict[str, str]:
    """
    Load CAS-RN mappings from previous results.

    Returns: Dict of ingredient_name -> cas_rn
    """
    mappings = {}

    # Load from notation mapping results
    if cas_results_file.exists():
        with open(cas_results_file) as f:
            data = yaml.safe_load(f)

        for result in data.get('results', []):
            name = result.get('original_name')
            cas_rn = result.get('cas_rn')

            if name and cas_rn:
                mappings[name] = cas_rn

    return mappings


def extract_cas_from_media_files(culturemech_root: Path) -> Dict[str, str]:
    """
    Extract CAS-RN directly from CultureMech media files' notes fields.

    Returns: Dict of ingredient_name -> cas_rn
    """
    import re

    cas_mappings = {}
    normalized_yaml = culturemech_root / 'data/normalized_yaml'

    # Pattern to extract CAS-RN: "CAS: XXXXX-XX-X"
    cas_pattern = re.compile(r'CAS:\s*(\d{2,7}-\d{2}-\d)')

    for yaml_file in normalized_yaml.rglob('*.yaml'):
        try:
            with open(yaml_file) as f:
                media = yaml.safe_load(f)

            if not media:
                continue

            # Check if FEBA media
            notes = media.get('notes', '')
            if 'FEBA media definitions' not in notes:
                continue

            # Extract CAS-RN from ingredient notes
            for ingredient in media.get('ingredients', []):
                preferred_term = ingredient.get('preferred_term', '')
                ingredient_notes = ingredient.get('notes', '')

                if not preferred_term:
                    continue

                # Check if ingredient already has ontology ID
                term = ingredient.get('term', {})
                if term.get('id'):
                    continue  # Skip if already mapped

                # Extract CAS-RN from notes
                match = cas_pattern.search(ingredient_notes)
                if match:
                    cas_rn = match.group(1)
                    # Store first occurrence (avoid overwriting)
                    if preferred_term not in cas_mappings:
                        cas_mappings[preferred_term] = cas_rn

        except Exception as e:
            continue

    return cas_mappings


def extract_unmapped_with_cas(
    ontology_report: Path,
    cas_mapping_results: Path,
    cas_resolvable_results: Path,
    culturemech_root: Path = None
) -> Dict[str, str]:
    """
    Extract ingredients that have CAS-RN but no ontology ID.

    Returns: Dict of ingredient_name -> cas_rn
    """
    # Load ontology report
    with open(ontology_report) as f:
        ontology_data = yaml.safe_load(f)

    # Get ingredients without ontology
    unmapped = ontology_data.get('ingredients_without_ontology', {})

    # Load CAS-RN from various sources
    cas_mappings = {}

    # From notation mapping results
    if cas_mapping_results.exists():
        with open(cas_mapping_results) as f:
            mapping_data = yaml.safe_load(f)

        for result in mapping_data.get('results', []):
            name = result.get('original_name')
            cas_rn = result.get('cas_rn')
            if name and cas_rn:
                cas_mappings[name] = cas_rn

    # From resolvable resolution results
    if cas_resolvable_results.exists():
        with open(cas_resolvable_results) as f:
            resolvable_data = yaml.safe_load(f)

        for result in resolvable_data.get('results', []):
            name = result.get('original_name')
            cas_rn = result.get('cas_rn')
            if name and cas_rn:
                cas_mappings[name] = cas_rn

    # From CultureMech media files (NEW: parse notes field)
    if culturemech_root and culturemech_root.exists():
        print("Extracting CAS-RN from CultureMech media file notes...")
        media_cas = extract_cas_from_media_files(culturemech_root)
        print(f"  Found {len(media_cas)} ingredients with CAS-RN in notes")
        # Merge with existing mappings (don't overwrite)
        for name, cas_rn in media_cas.items():
            if name not in cas_mappings:
                cas_mappings[name] = cas_rn

    # Match unmapped ingredients with CAS-RN
    result = {}
    for ingredient_name in unmapped.keys():
        if ingredient_name in cas_mappings:
            result[ingredient_name] = cas_mappings[ingredient_name]

    return result


def main():
    parser = argparse.ArgumentParser(
        description='Enrich FEBA ingredient ontology mappings using CAS-RN'
    )
    parser.add_argument(
        '--ontology-report',
        type=Path,
        default=Path('workspace/feba_ontology_coverage_report.yaml'),
        help='Ontology coverage report'
    )
    parser.add_argument(
        '--cas-mapping-results',
        type=Path,
        default=Path('workspace/feba_notation_mapping_results.yaml'),
        help='CAS-RN notation mapping results'
    )
    parser.add_argument(
        '--cas-resolvable-results',
        type=Path,
        default=Path('workspace/feba_resolvable_resolution_results.yaml'),
        help='CAS-RN resolvable resolution results'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('workspace/feba_chebi_enrichment_results.yaml'),
        help='Output enrichment results'
    )
    parser.add_argument(
        '--max-queries',
        type=int,
        help='Maximum number of queries (for testing)'
    )
    parser.add_argument(
        '--culturemech',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository (for extracting CAS-RN from media notes)'
    )

    args = parser.parse_args()

    print("Extracting ingredients with CAS-RN but no ontology ID...")

    # Extract target ingredients
    ingredients_with_cas = extract_unmapped_with_cas(
        args.ontology_report,
        args.cas_mapping_results,
        args.cas_resolvable_results,
        args.culturemech
    )

    print(f"Found {len(ingredients_with_cas)} ingredients with CAS-RN but no ontology ID\n")

    if not ingredients_with_cas:
        print("No ingredients to process. Exiting.")
        return

    # Query ChEBI API
    enricher = ChEBIEnricher()

    query_count = 0
    for ingredient_name, cas_rn in sorted(ingredients_with_cas.items()):
        if args.max_queries and query_count >= args.max_queries:
            print(f"\n[Reached max queries limit: {args.max_queries}]")
            break

        print(f"[{query_count + 1}/{len(ingredients_with_cas)}] {ingredient_name:50s} (CAS: {cas_rn}) ", end='', flush=True)

        result = enricher.process_ingredient(ingredient_name, cas_rn)

        if result:
            print(f"✓ {result['chebi_id']}")
        else:
            print(f"✗ No ChEBI ID found")

        query_count += 1

    # Print statistics
    enricher.print_stats()

    # Save results
    enricher.save_results(args.output)


if __name__ == '__main__':
    main()
