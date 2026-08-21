"""
Ingredient Repository Synchronizer Plugin

Bidirectional synchronization of canonical ingredient mappings
to CultureMech and MediaIngredientMech repositories.

Sync Logic:
- To CultureMech: Update mediaingredientmech_term fields in existing ingredients
- To MediaIngredientMech: Append newly mapped ingredients to mapped_ingredients.yaml
- Preserves repo-specific metadata while updating mappings
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from plugins.repository_settings import RepositorySettings

logger = logging.getLogger(__name__)


@dataclass
class SyncReport:
    """Report of synchronization operation."""

    repo: str
    added: int
    updated: int
    skipped: int
    errors: List[str]
    files_modified: List[str]
    timestamp: str


class IngredientRepoSynchronizer:
    """Synchronize canonical ingredient mappings to downstream repositories."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize synchronizer.

        Args:
            config: Configuration with repo paths
        """
        self.config = config or {}

        repository_config = self.config
        if "repositories" not in repository_config:
            repository_config = {
                "repositories": {
                    name: {"path": value}
                    for name, value in (
                        ("culturemech", self.config.get("culturemech_root")),
                        (
                            "mediaingredientmech",
                            self.config.get("mediaingredientmech_root"),
                        ),
                    )
                    if value is not None
                }
            }
        self.repository_settings = RepositorySettings.from_environment(repository_config)
        self.culturemech_root = self.repository_settings.get_target("culturemech").path
        self.mim_root = self.repository_settings.get_target("mediaingredientmech").path

        logger.info(f"IngredientRepoSynchronizer initialized: "
                   f"CultureMech={self.culturemech_root}, MIM={self.mim_root}")

    def sync_to_culturemech(
        self,
        canonical_mapped: List[Dict[str, Any]],
        dry_run: bool = True
    ) -> SyncReport:
        """
        Sync canonical mappings to CultureMech.

        Updates mediaingredientmech_term field in existing ingredient entries.

        Args:
            canonical_mapped: List of canonically mapped ingredients
            dry_run: If True, don't write files

        Returns:
            SyncReport with operation details
        """
        logger.info(f"Syncing {len(canonical_mapped)} mappings to CultureMech "
                   f"(dry_run={dry_run})")

        report = SyncReport(
            repo='culturemech',
            added=0,
            updated=0,
            skipped=0,
            errors=[],
            files_modified=[],
            timestamp=datetime.utcnow().isoformat()
        )

        # Build index of canonical mappings by preferred_term (normalized)
        canonical_by_name = {}
        for ing in canonical_mapped:
            name = ing.get('preferred_term', '').strip().lower()
            if name:
                canonical_by_name[name] = ing

        # Scan CultureMech media files
        media_dir = self.culturemech_root / "normalized_yaml"

        if not media_dir.exists():
            report.errors.append(f"CultureMech media directory not found: {media_dir}")
            return report

        # Process media files by category
        for category_dir in media_dir.iterdir():
            if not category_dir.is_dir():
                continue

            for media_file in category_dir.glob("*.yaml"):
                try:
                    modified = self._update_culturemech_file(
                        media_file, canonical_by_name, dry_run
                    )

                    if modified:
                        report.updated += modified
                        report.files_modified.append(str(media_file.relative_to(self.culturemech_root)))

                except Exception as e:
                    error_msg = f"Error processing {media_file}: {e}"
                    logger.error(error_msg)
                    report.errors.append(error_msg)

        logger.info(f"CultureMech sync complete: {report.updated} updated, "
                   f"{report.skipped} skipped, {len(report.errors)} errors")

        return report

    def _update_culturemech_file(
        self,
        media_file: Path,
        canonical_by_name: Dict[str, Dict[str, Any]],
        dry_run: bool
    ) -> int:
        """
        Update a single CultureMech media file.

        Args:
            media_file: Path to media YAML file
            canonical_by_name: Canonical mappings indexed by normalized name
            dry_run: If True, don't write file

        Returns:
            Number of ingredients updated
        """
        with open(media_file) as f:
            media_data = yaml.safe_load(f)

        if not media_data or 'ingredients' not in media_data:
            return 0

        updated_count = 0

        for ingredient in media_data['ingredients']:
            name = ingredient.get('preferred_term', '').strip().lower()

            # Skip if already has MediaIngredientMech link
            if 'mediaingredientmech_term' in ingredient:
                continue

            # Check for canonical mapping
            if name in canonical_by_name:
                canonical = canonical_by_name[name]

                # Add mediaingredientmech_term
                mim_id = canonical.get('ontology_id') or canonical.get('id')
                mim_label = canonical.get('preferred_term')

                if mim_id and mim_label:
                    ingredient['mediaingredientmech_term'] = {
                        'id': mim_id,
                        'label': mim_label
                    }
                    updated_count += 1

        # Write file if modified
        if updated_count > 0 and not dry_run:
            with open(media_file, 'w') as f:
                yaml.dump(media_data, f, default_flow_style=False, sort_keys=False)

        return updated_count

    def sync_to_mediaingredientmech(
        self,
        canonical_mapped: List[Dict[str, Any]],
        dry_run: bool = True
    ) -> SyncReport:
        """
        Sync canonical mappings to MediaIngredientMech.

        Appends newly mapped ingredients to mapped_ingredients.yaml.

        Args:
            canonical_mapped: List of canonically mapped ingredients
            dry_run: If True, don't write files

        Returns:
            SyncReport with operation details
        """
        logger.info(f"Syncing {len(canonical_mapped)} mappings to MediaIngredientMech "
                   f"(dry_run={dry_run})")

        report = SyncReport(
            repo='mediaingredientmech',
            added=0,
            updated=0,
            skipped=0,
            errors=[],
            files_modified=[],
            timestamp=datetime.utcnow().isoformat()
        )

        # Load existing mapped ingredients
        mapped_file = self.mim_root / "data" / "curated" / "mapped_ingredients.yaml"

        if not mapped_file.exists():
            report.errors.append(f"MediaIngredientMech mapped file not found: {mapped_file}")
            return report

        try:
            with open(mapped_file) as f:
                mim_data = yaml.safe_load(f) or {}

            existing_ingredients = mim_data.get('ingredients', [])

            # Build index of existing by ontology_id
            existing_by_id = {
                ing.get('ontology_id'): ing
                for ing in existing_ingredients
                if ing.get('ontology_id')
            }

            # Process canonical mappings
            for canonical_ing in canonical_mapped:
                ontology_id = canonical_ing.get('ontology_id') or canonical_ing.get('id')

                if not ontology_id:
                    report.skipped += 1
                    continue

                # Check if already exists
                if ontology_id in existing_by_id:
                    # Update occurrence_statistics
                    existing = existing_by_id[ontology_id]

                    if 'occurrence_statistics' in canonical_ing:
                        existing['occurrence_statistics'] = canonical_ing['occurrence_statistics']
                        report.updated += 1
                    else:
                        report.skipped += 1
                else:
                    # Add new ingredient
                    new_ingredient = self._prepare_mim_ingredient(canonical_ing)
                    existing_ingredients.append(new_ingredient)
                    report.added += 1

            # Update metadata
            if 'metadata' not in mim_data:
                mim_data['metadata'] = {}

            mim_data['metadata']['last_sync_from_canonical'] = datetime.utcnow().isoformat()
            mim_data['metadata']['total_ingredients'] = len(existing_ingredients)
            mim_data['ingredients'] = existing_ingredients

            # Write file
            if (report.added > 0 or report.updated > 0) and not dry_run:
                with open(mapped_file, 'w') as f:
                    yaml.dump(mim_data, f, default_flow_style=False, sort_keys=False)

                report.files_modified.append(str(mapped_file.relative_to(self.mim_root)))

        except Exception as e:
            error_msg = f"Error syncing to MediaIngredientMech: {e}"
            logger.error(error_msg)
            report.errors.append(error_msg)

        logger.info(f"MediaIngredientMech sync complete: {report.added} added, "
                   f"{report.updated} updated, {report.skipped} skipped")

        return report

    def _prepare_mim_ingredient(self, canonical_ing: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare canonical ingredient for MediaIngredientMech format.

        Args:
            canonical_ing: Canonical ingredient record

        Returns:
            MediaIngredientMech-formatted ingredient
        """
        mim_ing = canonical_ing.copy()

        # Add curation event
        if 'curation_history' not in mim_ing:
            mim_ing['curation_history'] = []

        mim_ing['curation_history'].append({
            'timestamp': datetime.utcnow().isoformat(),
            'curator': 'orchestration_claude',
            'action': 'SYNCED_FROM_CANONICAL',
            'changes': 'Added from canonical ingredient store',
            'llm_assisted': False
        })

        # Ensure mapping_status is set
        if 'mapping_status' not in mim_ing:
            mim_ing['mapping_status'] = 'MAPPED'

        return mim_ing

    def generate_sync_diff(
        self,
        canonical_mapped: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Generate a diff report of what would change in each repo.

        Args:
            canonical_mapped: List of canonically mapped ingredients

        Returns:
            Diff report with added/updated/conflicts per repo
        """
        logger.info(f"Generating sync diff for {len(canonical_mapped)} mappings")

        diff = {
            'culturemech': {
                'would_update': 0,
                'already_synced': 0,
                'sample_updates': []
            },
            'mediaingredientmech': {
                'would_add': 0,
                'would_update': 0,
                'already_synced': 0,
                'sample_additions': []
            },
            'timestamp': datetime.utcnow().isoformat()
        }

        # Build canonical index
        canonical_by_name = {}
        for ing in canonical_mapped:
            name = ing.get('preferred_term', '').strip().lower()
            if name:
                canonical_by_name[name] = ing

        # Check CultureMech
        media_dir = self.culturemech_root / "normalized_yaml"
        if media_dir.exists():
            for category_dir in media_dir.iterdir():
                if not category_dir.is_dir():
                    continue

                for media_file in category_dir.glob("*.yaml"):
                    try:
                        with open(media_file) as f:
                            media_data = yaml.safe_load(f)

                        if not media_data or 'ingredients' not in media_data:
                            continue

                        for ingredient in media_data['ingredients']:
                            name = ingredient.get('preferred_term', '').strip().lower()

                            if name in canonical_by_name:
                                if 'mediaingredientmech_term' in ingredient:
                                    diff['culturemech']['already_synced'] += 1
                                else:
                                    diff['culturemech']['would_update'] += 1

                                    # Sample first 5
                                    if len(diff['culturemech']['sample_updates']) < 5:
                                        diff['culturemech']['sample_updates'].append({
                                            'file': str(media_file.name),
                                            'ingredient': name,
                                            'would_add_mim_id': canonical_by_name[name].get('ontology_id')
                                        })

                    except Exception as e:
                        logger.warning(f"Error reading {media_file}: {e}")

        # Check MediaIngredientMech
        mapped_file = self.mim_root / "data" / "curated" / "mapped_ingredients.yaml"
        if mapped_file.exists():
            try:
                with open(mapped_file) as f:
                    mim_data = yaml.safe_load(f) or {}

                existing_ids = {
                    ing.get('ontology_id')
                    for ing in mim_data.get('ingredients', [])
                    if ing.get('ontology_id')
                }

                for canonical_ing in canonical_mapped:
                    ontology_id = canonical_ing.get('ontology_id') or canonical_ing.get('id')

                    if ontology_id:
                        if ontology_id in existing_ids:
                            diff['mediaingredientmech']['would_update'] += 1
                        else:
                            diff['mediaingredientmech']['would_add'] += 1

                            # Sample first 5
                            if len(diff['mediaingredientmech']['sample_additions']) < 5:
                                diff['mediaingredientmech']['sample_additions'].append({
                                    'ontology_id': ontology_id,
                                    'preferred_term': canonical_ing.get('preferred_term'),
                                    'occurrences': canonical_ing.get('occurrence_statistics', {}).get('total_occurrences', 0)
                                })

            except Exception as e:
                logger.warning(f"Error reading MediaIngredientMech file: {e}")

        return diff
