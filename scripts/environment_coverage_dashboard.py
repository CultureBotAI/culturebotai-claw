#!/usr/bin/env python3
"""
Environment Coverage Dashboard

Analyzes environmental coverage across the exact repositories selected by the
canonical fleet manifest to identify well-covered and under-resourced environments.

Usage:
    python environment_coverage_dashboard.py [--format {table|json|html}] [--output FILE]

Requirements:
    - PyYAML
    - tabulate (for table format)
    - jinja2 (for HTML format)
"""

import argparse
import json
import stat
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from kg_microbe_fleet import (
    FleetManifestError,
    UniqueKeySafeLoader,
    load_fleet_manifest,
)
from plugins.repository_settings import (
    RepositoryConfigurationError,
    RepositorySettings,
    merged_repository_environment,
)

try:
    import yaml
except ImportError:
    print("Error: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


@dataclass(frozen=True)
class CoverageSource:
    """One trusted, manifest-selected source of environment records."""

    key: str
    display_name: str
    root: Path
    record_globs: tuple[str, ...]


class CoverageInputError(ValueError):
    """Raised when a selected record cannot be represented in the report."""


class EnvironmentCoverageAnalyzer:
    """Analyze environment-bearing records without repository-specific routing."""

    def __init__(self, sources: Sequence[CoverageSource]):
        self.sources = tuple(sources)
        self.input_errors: list[str] = []

        # Environment tracking
        self.environments: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
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
        for source in self.sources:
            print(f"Scanning {source.display_name}...", file=sys.stderr)
            self._scan_source(source)

        if self.input_errors:
            raise CoverageInputError(
                "environment coverage inputs are incomplete: "
                + "; ".join(self.input_errors)
            )

        return self._generate_report()

    def _scan_source(self, source: CoverageSource) -> None:
        """Scan exactly the manifest record globs for one validated checkout."""

        try:
            files = sorted(
                {
                    path
                    for pattern in source.record_globs
                    for path in source.root.glob(pattern)
                }
            )
        except (OSError, ValueError) as exc:
            self.input_errors.append(
                f"{source.key}: cannot enumerate record_globs: {exc}"
            )
            return
        if not files:
            self.input_errors.append(
                f"{source.key}: record_globs matched no files: "
                + ", ".join(source.record_globs)
            )
            return
        for yaml_file in files:
            try:
                path_stat = yaml_file.lstat()
            except OSError as exc:
                self.input_errors.append(
                    f"{source.key}:{yaml_file}: cannot inspect matched path: {exc}"
                )
                continue
            if stat.S_ISLNK(path_stat.st_mode):
                self.input_errors.append(
                    f"{source.key}:{yaml_file} is a symlink"
                )
                continue
            if not stat.S_ISREG(path_stat.st_mode):
                self.input_errors.append(
                    f"{source.key}:{yaml_file} is not a regular file"
                )
                continue
            try:
                yaml_file.resolve(strict=True).relative_to(source.root)
                data = yaml.load(
                    yaml_file.read_text(encoding="utf-8"),
                    Loader=UniqueKeySafeLoader,
                )
                if not isinstance(data, Mapping):
                    self.input_errors.append(
                        f"{source.key}:{yaml_file} root is not a mapping"
                    )
                    continue
                self._record_communities(data, yaml_file)
                self._record_media(data, yaml_file)
                self._record_ingredients(data, yaml_file)
            except (OSError, ValueError, yaml.YAMLError) as exc:
                self.input_errors.append(f"{source.key}:{yaml_file}: {exc}")

    def _descriptors(
        self,
        data: Mapping[str, Any],
        field: str,
        yaml_file: Path,
    ) -> tuple[Mapping[str, Any], ...]:
        if field not in data:
            return ()
        value = data[field]
        if isinstance(value, Mapping):
            return (value,)
        if isinstance(value, list):
            descriptors: list[Mapping[str, Any]] = []
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    descriptors.append(item)
                else:
                    self.input_errors.append(
                        f"{yaml_file}:{field}[{index}] must be a mapping"
                    )
            return tuple(descriptors)
        self.input_errors.append(
            f"{yaml_file}:{field} must be a mapping or list of mappings"
        )
        return ()

    def _term(
        self,
        descriptor: Mapping[str, Any],
        field: str,
        yaml_file: Path,
    ) -> tuple[str | None, Any]:
        # A descriptor may legitimately be curated but not yet ontology-grounded
        # (for example, it can carry only preferred_term and notes). It cannot
        # contribute an ENVO bucket, but it is not malformed. Once `term` is
        # present, however, its shape and identifier must be valid.
        if "term" not in descriptor:
            return None, None
        term = descriptor["term"]
        if not isinstance(term, Mapping):
            self.input_errors.append(f"{yaml_file}:{field}.term must be a mapping")
            return None, None
        envo_id = term.get("id")
        if not isinstance(envo_id, str) or not envo_id.strip():
            self.input_errors.append(
                f"{yaml_file}:{field}.term.id must be a non-empty string"
            )
            return None, None
        return envo_id.strip(), term.get("label") or descriptor.get("preferred_term")

    def _remember(self, envo_id: Any, label: Any) -> Dict[str, Any]:
        key = str(envo_id)
        environment = self.environments[key]
        environment["envo_id"] = key
        environment["label"] = str(label or key)
        return environment

    def _record_communities(
        self, data: Mapping[str, Any], yaml_file: Path
    ) -> None:
        field = "environment_term"
        for descriptor in self._descriptors(data, field, yaml_file):
            envo_id, envo_label = self._term(descriptor, field, yaml_file)
            if not envo_id:
                continue
            environment = self._remember(envo_id, envo_label)
            environment["communities"].append(
                {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "file": yaml_file.name,
                }
            )
            environment["community_count"] += 1

    def _record_media(self, data: Mapping[str, Any], yaml_file: Path) -> None:
        field = "source_environment"
        for descriptor in self._descriptors(data, field, yaml_file):
            envo_id, envo_label = self._term(descriptor, field, yaml_file)
            if not envo_id:
                continue
            environment = self._remember(envo_id, envo_label)
            environment["media"].append(
                {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "file": yaml_file.name,
                }
            )
            environment["media_count"] += 1

    def _record_ingredients(
        self, data: Mapping[str, Any], yaml_file: Path
    ) -> None:
        field = "environmental_context"
        for context in self._descriptors(data, field, yaml_file):
            environment_term = context.get("environment_term")
            if isinstance(environment_term, Mapping):
                envo_id = environment_term.get("id")
                envo_label = environment_term.get("label")
            else:
                envo_id = environment_term
                envo_label = None
            if not isinstance(envo_id, str) or not envo_id.strip():
                self.input_errors.append(
                    f"{yaml_file}:{field}.environment_term must contain a "
                    "non-empty string identifier"
                )
                continue
            environment = self._remember(
                envo_id.strip(), context.get("environment_label") or envo_label
            )
            environment["ingredients"].append(
                {
                    "name": data.get("preferred_term"),
                    "ontology_id": data.get("ontology_id"),
                    "relevance": context.get("relevance"),
                    "file": yaml_file.name,
                }
            )
            environment["ingredient_count"] += 1

    def _generate_report(self) -> Dict[str, Any]:
        """Generate coverage report."""
        report: Dict[str, Any] = {
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
    output.append("Total Resources:")
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

    gaps: Dict[str, list[Dict[str, Any]]] = {
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
        from jinja2 import Environment
    except ImportError:
        print("Error: jinja2 not installed. Run: pip install jinja2", file=sys.stderr)
        sys.exit(1)

    template = Environment(autoescape=True).from_string("""
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


def _coverage_sources(dotenv_path: Path | None = None) -> tuple[CoverageSource, ...]:
    """Resolve the complete manifest capability scope before reading records."""

    manifest = load_fleet_manifest()
    keys = manifest.with_capability("environment_coverage")
    if not keys:
        raise FleetManifestError(
            "Capability 'environment_coverage' has no enabled Mechs"
        )
    environ = merged_repository_environment(dotenv_path)
    settings = RepositorySettings.from_environment(manifest=manifest, environ=environ)

    invalid = {key: settings.invalid[key] for key in keys if key in settings.invalid}
    if invalid:
        details = "; ".join(f"{key}: {message}" for key, message in invalid.items())
        raise RepositoryConfigurationError(
            f"configured environment coverage target is untrustworthy: {details}"
        )

    unconfigured = [key for key in keys if key in settings.unconfigured]
    if unconfigured:
        details = "; ".join(
            f"{key}: {settings.errors[key]}" for key in unconfigured
        )
        raise RepositoryConfigurationError(
            f"environment coverage target is not configured: {details}"
        )

    # Revalidate every target before scanning any of them. A checkout whose
    # origin changed after settings construction must not yield a partial report.
    sources: list[CoverageSource] = []
    for key in keys:
        mech = manifest.get(key)
        capability = mech.capability("environment_coverage")
        if capability is None:  # pragma: no cover - selected by this capability
            raise FleetManifestError(f"{key} does not declare environment_coverage")
        globs = capability.settings.get("record_globs")
        if not isinstance(globs, tuple) or not globs:
            raise FleetManifestError(
                f"{key}.environment_coverage.record_globs is not a validated profile"
            )
        sources.append(
            CoverageSource(
                key=key,
                display_name=mech.display_name,
                root=settings.get_target(key).path,
                record_globs=globs,
            )
        )
    return tuple(sources)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze environmental coverage across the canonical manifest's "
            "environment_coverage capability scope"
        )
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
    parser.add_argument(
        '--dotenv',
        type=Path,
        help=(
            'explicit dotenv file for checkout roots; exported values take '
            'precedence (default: this source checkout\'s .env when present)'
        ),
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    # Analyze
    try:
        dotenv_path = args.dotenv
        if dotenv_path is None:
            project_dotenv = Path(__file__).resolve().parents[1] / ".env"
            if project_dotenv.exists() or project_dotenv.is_symlink():
                dotenv_path = project_dotenv
        analyzer = EnvironmentCoverageAnalyzer(_coverage_sources(dotenv_path))
        report = analyzer.analyze()
    except (
        CoverageInputError,
        FleetManifestError,
        RepositoryConfigurationError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

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
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
