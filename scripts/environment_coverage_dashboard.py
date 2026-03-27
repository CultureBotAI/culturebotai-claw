#!/usr/bin/env python3
"""
Environment Coverage Dashboard

Analyzes environmental coverage across CultureMech, MediaIngredientMech, and CommunityMech
to identify well-covered and under-resourced environments.

Usage:
    python environment_coverage_dashboard.py [--format {table|json|html}] [--output FILE]

Requirements:
    - PyYAML
    - tabulate (for table format)
    - jinja2 (for HTML format)
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

try:
    import yaml
except ImportError:
    print("Error: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


class EnvironmentCoverageAnalyzer:
    """Analyzes environment coverage across three repositories."""

    def __init__(
        self,
        culturemech_root: Path,
        mediaingredient_root: Path,
        communitymech_root: Path
    ):
        self.culturemech_root = culturemech_root
        self.mediaingredient_root = mediaingredient_root
        self.communitymech_root = communitymech_root

        # Environment tracking
        self.environments: Dict[str, Dict] = defaultdict(lambda: {
            'envo_id': None,
            'label': None,
            'communities': [],
            'media': [],
            'ingredients': [],
            'community_count': 0,
            'media_count': 0,
            'ingredient_count': 0
        })

    def analyze(self) -> Dict:
        """Run complete coverage analysis."""
        print("Scanning CommunityMech...", file=sys.stderr)
        self._scan_communities()

        print("Scanning CultureMech...", file=sys.stderr)
        self._scan_media()

        print("Scanning MediaIngredientMech...", file=sys.stderr)
        self._scan_ingredients()

        return self._generate_report()

    def _scan_communities(self):
        """Scan CommunityMech for environment terms."""
        community_dir = self.communitymech_root / "data" / "isolates"

        if not community_dir.exists():
            print(f"Warning: {community_dir} not found", file=sys.stderr)
            return

        for yaml_file in community_dir.glob("*.yaml"):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)

                if not data:
                    continue

                # Extract environment_term
                env_term = data.get('environment_term')
                if env_term:
                    envo_id = None
                    envo_label = None

                    # Handle both dict and list formats
                    if isinstance(env_term, dict):
                        term_data = env_term.get('term', {})
                        envo_id = term_data.get('id')
                        envo_label = term_data.get('label') or env_term.get('preferred_term')
                    elif isinstance(env_term, list) and env_term:
                        term_data = env_term[0].get('term', {})
                        envo_id = term_data.get('id')
                        envo_label = term_data.get('label') or env_term[0].get('preferred_term')

                    if envo_id:
                        env_key = envo_id
                        self.environments[env_key]['envo_id'] = envo_id
                        self.environments[env_key]['label'] = envo_label or envo_id
                        self.environments[env_key]['communities'].append({
                            'id': data.get('id'),
                            'name': data.get('name'),
                            'file': yaml_file.name
                        })
                        self.environments[env_key]['community_count'] += 1

            except Exception as e:
                print(f"Warning: Error reading {yaml_file}: {e}", file=sys.stderr)

    def _scan_media(self):
        """Scan CultureMech for source_environment fields."""
        media_dir = self.culturemech_root / "data"

        if not media_dir.exists():
            print(f"Warning: {media_dir} not found", file=sys.stderr)
            return

        for yaml_file in media_dir.rglob("*.yaml"):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)

                if not data:
                    continue

                # Extract source_environment
                source_env = data.get('source_environment')
                if source_env:
                    # Handle list format
                    if not isinstance(source_env, list):
                        source_env = [source_env]

                    for env_descriptor in source_env:
                        if isinstance(env_descriptor, dict):
                            term_data = env_descriptor.get('term', {})
                            envo_id = term_data.get('id')
                            envo_label = term_data.get('label') or env_descriptor.get('preferred_term')

                            if envo_id:
                                env_key = envo_id
                                self.environments[env_key]['envo_id'] = envo_id
                                self.environments[env_key]['label'] = envo_label or envo_id
                                self.environments[env_key]['media'].append({
                                    'id': data.get('id'),
                                    'name': data.get('name'),
                                    'file': yaml_file.name
                                })
                                self.environments[env_key]['media_count'] += 1

            except Exception as e:
                print(f"Warning: Error reading {yaml_file}: {e}", file=sys.stderr)

    def _scan_ingredients(self):
        """Scan MediaIngredientMech for environmental_context fields."""
        ingredient_dir = self.mediaingredient_root / "data"

        if not ingredient_dir.exists():
            print(f"Warning: {ingredient_dir} not found", file=sys.stderr)
            return

        for yaml_file in ingredient_dir.rglob("*.yaml"):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)

                if not data:
                    continue

                # Extract environmental_context
                env_context = data.get('environmental_context')
                if env_context:
                    # Handle list format
                    if not isinstance(env_context, list):
                        env_context = [env_context]

                    for context in env_context:
                        if isinstance(context, dict):
                            envo_id = context.get('environment_term')
                            envo_label = context.get('environment_label')
                            relevance = context.get('relevance')

                            if envo_id:
                                env_key = envo_id
                                self.environments[env_key]['envo_id'] = envo_id
                                self.environments[env_key]['label'] = envo_label or envo_id
                                self.environments[env_key]['ingredients'].append({
                                    'name': data.get('preferred_term'),
                                    'ontology_id': data.get('ontology_id'),
                                    'relevance': relevance,
                                    'file': yaml_file.name
                                })
                                self.environments[env_key]['ingredient_count'] += 1

            except Exception as e:
                print(f"Warning: Error reading {yaml_file}: {e}", file=sys.stderr)

    def _generate_report(self) -> Dict:
        """Generate coverage report."""
        report = {
            'summary': {
                'total_environments': len(self.environments),
                'environments_with_communities': sum(1 for e in self.environments.values() if e['community_count'] > 0),
                'environments_with_media': sum(1 for e in self.environments.values() if e['media_count'] > 0),
                'environments_with_ingredients': sum(1 for e in self.environments.values() if e['ingredient_count'] > 0),
                'fully_covered': sum(1 for e in self.environments.values()
                                   if e['community_count'] > 0 and e['media_count'] > 0 and e['ingredient_count'] > 0),
                'total_communities': sum(e['community_count'] for e in self.environments.values()),
                'total_media': sum(e['media_count'] for e in self.environments.values()),
                'total_ingredients': sum(e['ingredient_count'] for e in self.environments.values()),
            },
            'environments': []
        }

        # Sort environments by coverage (descending)
        for env_key in sorted(self.environments.keys(),
                             key=lambda k: (
                                 self.environments[k]['community_count'] +
                                 self.environments[k]['media_count'] +
                                 self.environments[k]['ingredient_count']
                             ), reverse=True):
            env_data = self.environments[env_key]

            # Calculate coverage score (0-100)
            has_community = 1 if env_data['community_count'] > 0 else 0
            has_media = 1 if env_data['media_count'] > 0 else 0
            has_ingredient = 1 if env_data['ingredient_count'] > 0 else 0
            coverage_score = (has_community + has_media + has_ingredient) * 33.33

            report['environments'].append({
                'envo_id': env_data['envo_id'],
                'label': env_data['label'],
                'community_count': env_data['community_count'],
                'media_count': env_data['media_count'],
                'ingredient_count': env_data['ingredient_count'],
                'coverage_score': round(coverage_score, 1),
                'coverage_level': self._get_coverage_level(has_community, has_media, has_ingredient),
                'communities': env_data['communities'],
                'media': env_data['media'],
                'ingredients': env_data['ingredients']
            })

        return report

    def _get_coverage_level(self, has_community: int, has_media: int, has_ingredient: int) -> str:
        """Determine coverage level."""
        total = has_community + has_media + has_ingredient
        if total == 3:
            return "FULL"
        elif total == 2:
            return "PARTIAL"
        elif total == 1:
            return "MINIMAL"
        else:
            return "NONE"


def format_table(report: Dict) -> str:
    """Format report as ASCII table."""
    try:
        from tabulate import tabulate
    except ImportError:
        print("Error: tabulate not installed. Run: pip install tabulate", file=sys.stderr)
        sys.exit(1)

    output = []
    output.append("=" * 80)
    output.append("ENVIRONMENT COVERAGE DASHBOARD")
    output.append("=" * 80)
    output.append("")

    # Summary
    summary = report['summary']
    output.append("SUMMARY")
    output.append("-" * 80)
    output.append(f"Total Environments Tracked: {summary['total_environments']}")
    output.append(f"  - With Communities: {summary['environments_with_communities']}")
    output.append(f"  - With Media: {summary['environments_with_media']}")
    output.append(f"  - With Ingredients: {summary['environments_with_ingredients']}")
    output.append(f"  - Fully Covered (all 3): {summary['fully_covered']}")
    output.append("")
    output.append(f"Total Resources:")
    output.append(f"  - Communities: {summary['total_communities']}")
    output.append(f"  - Media: {summary['total_media']}")
    output.append(f"  - Ingredients: {summary['total_ingredients']}")
    output.append("")

    # Coverage table
    output.append("COVERAGE BY ENVIRONMENT")
    output.append("-" * 80)

    table_data = []
    for env in report['environments']:
        table_data.append([
            env['envo_id'],
            env['label'][:30] if len(env['label']) > 30 else env['label'],
            env['community_count'],
            env['media_count'],
            env['ingredient_count'],
            f"{env['coverage_score']}%",
            env['coverage_level']
        ])

    headers = ['ENVO ID', 'Environment', 'Communities', 'Media', 'Ingredients', 'Score', 'Level']
    output.append(tabulate(table_data, headers=headers, tablefmt='grid'))
    output.append("")

    # Gaps analysis
    output.append("COVERAGE GAPS")
    output.append("-" * 80)

    gaps = {
        'communities_only': [],
        'media_only': [],
        'ingredients_only': [],
        'no_communities': [],
        'no_media': [],
        'no_ingredients': []
    }

    for env in report['environments']:
        if env['community_count'] > 0 and env['media_count'] == 0 and env['ingredient_count'] == 0:
            gaps['communities_only'].append(env)
        if env['media_count'] > 0 and env['community_count'] == 0 and env['ingredient_count'] == 0:
            gaps['media_only'].append(env)
        if env['ingredient_count'] > 0 and env['community_count'] == 0 and env['media_count'] == 0:
            gaps['ingredients_only'].append(env)
        if env['community_count'] == 0:
            gaps['no_communities'].append(env)
        if env['media_count'] == 0:
            gaps['no_media'].append(env)
        if env['ingredient_count'] == 0:
            gaps['no_ingredients'].append(env)

    if gaps['communities_only']:
        output.append(f"\nEnvironments with ONLY communities (no media/ingredients): {len(gaps['communities_only'])}")
        for env in gaps['communities_only'][:5]:
            output.append(f"  - {env['envo_id']}: {env['label']}")

    if gaps['no_media']:
        output.append(f"\nEnvironments MISSING media: {len(gaps['no_media'])}")
        for env in gaps['no_media'][:5]:
            output.append(f"  - {env['envo_id']}: {env['label']} ({env['community_count']} communities, {env['ingredient_count']} ingredients)")

    if gaps['no_ingredients']:
        output.append(f"\nEnvironments MISSING ingredients: {len(gaps['no_ingredients'])}")
        for env in gaps['no_ingredients'][:5]:
            output.append(f"  - {env['envo_id']}: {env['label']} ({env['community_count']} communities, {env['media_count']} media)")

    output.append("")
    output.append("=" * 80)

    return "\n".join(output)


def format_json(report: Dict) -> str:
    """Format report as JSON."""
    return json.dumps(report, indent=2)


def format_html(report: Dict) -> str:
    """Format report as HTML."""
    try:
        from jinja2 import Template
    except ImportError:
        print("Error: jinja2 not installed. Run: pip install jinja2", file=sys.stderr)
        sys.exit(1)

    template = Template("""
<!DOCTYPE html>
<html>
<head>
    <title>Environment Coverage Dashboard</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
        h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }
        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }
        .summary-card { background: #f9f9f9; padding: 15px; border-left: 4px solid #4CAF50; }
        .summary-card h3 { margin: 0 0 10px 0; font-size: 14px; color: #666; }
        .summary-card .value { font-size: 32px; font-weight: bold; color: #333; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th { background: #4CAF50; color: white; padding: 12px; text-align: left; }
        td { padding: 10px; border-bottom: 1px solid #ddd; }
        tr:hover { background: #f5f5f5; }
        .coverage-full { background: #4CAF50; color: white; padding: 5px 10px; border-radius: 3px; }
        .coverage-partial { background: #FF9800; color: white; padding: 5px 10px; border-radius: 3px; }
        .coverage-minimal { background: #FFC107; color: white; padding: 5px 10px; border-radius: 3px; }
        .coverage-none { background: #F44336; color: white; padding: 5px 10px; border-radius: 3px; }
        .gaps { background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🌍 Environment Coverage Dashboard</h1>

        <div class="summary">
            <div class="summary-card">
                <h3>Total Environments</h3>
                <div class="value">{{ summary.total_environments }}</div>
            </div>
            <div class="summary-card">
                <h3>Fully Covered</h3>
                <div class="value">{{ summary.fully_covered }}</div>
            </div>
            <div class="summary-card">
                <h3>Total Communities</h3>
                <div class="value">{{ summary.total_communities }}</div>
            </div>
            <div class="summary-card">
                <h3>Total Media</h3>
                <div class="value">{{ summary.total_media }}</div>
            </div>
            <div class="summary-card">
                <h3>Total Ingredients</h3>
                <div class="value">{{ summary.total_ingredients }}</div>
            </div>
        </div>

        <h2>Coverage by Environment</h2>
        <table>
            <thead>
                <tr>
                    <th>ENVO ID</th>
                    <th>Environment</th>
                    <th>Communities</th>
                    <th>Media</th>
                    <th>Ingredients</th>
                    <th>Score</th>
                    <th>Level</th>
                </tr>
            </thead>
            <tbody>
                {% for env in environments %}
                <tr>
                    <td><code>{{ env.envo_id }}</code></td>
                    <td>{{ env.label }}</td>
                    <td>{{ env.community_count }}</td>
                    <td>{{ env.media_count }}</td>
                    <td>{{ env.ingredient_count }}</td>
                    <td>{{ env.coverage_score }}%</td>
                    <td><span class="coverage-{{ env.coverage_level|lower }}">{{ env.coverage_level }}</span></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
    """)

    return template.render(
        summary=report['summary'],
        environments=report['environments']
    )


def main():
    parser = argparse.ArgumentParser(
        description="Analyze environmental coverage across CultureMech, MediaIngredientMech, and CommunityMech"
    )
    parser.add_argument(
        '--culturemech-root',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech',
        help='Path to CultureMech repository'
    )
    parser.add_argument(
        '--mediaingredient-root',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MediaIngredientMech',
        help='Path to MediaIngredientMech repository'
    )
    parser.add_argument(
        '--communitymech-root',
        type=Path,
        default=Path.home() / 'Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CommunityMech/CommunityMech',
        help='Path to CommunityMech repository'
    )
    parser.add_argument(
        '--format',
        choices=['table', 'json', 'html'],
        default='table',
        help='Output format (default: table)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Output file (default: stdout)'
    )

    args = parser.parse_args()

    # Validate paths
    for name, path in [
        ('CultureMech', args.culturemech_root),
        ('MediaIngredientMech', args.mediaingredient_root),
        ('CommunityMech', args.communitymech_root)
    ]:
        if not path.exists():
            print(f"Error: {name} repository not found at {path}", file=sys.stderr)
            sys.exit(1)

    # Analyze
    analyzer = EnvironmentCoverageAnalyzer(
        args.culturemech_root,
        args.mediaingredient_root,
        args.communitymech_root
    )
    report = analyzer.analyze()

    # Format
    if args.format == 'table':
        output = format_table(report)
    elif args.format == 'json':
        output = format_json(report)
    elif args.format == 'html':
        output = format_html(report)

    # Output
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == '__main__':
    main()
