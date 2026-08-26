"""Contract tests for the canonical fleet manifest.

Phase 0 of the standardization plan exists because several components each
carried their own Mech list and they disagreed. These tests pin the manifest's
validation rules and fail the build if a supported component grows a divergent
list again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kg_microbe_config import default_config_path
from kg_microbe_fleet import (
    FleetManifestError,
    load_fleet_manifest,
    parse_fleet_manifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPOSITORY_ROOT / "src" / "kg_microbe_fleet" / "fleet.yaml"

EXPECTED_MECHS = (
    "culturemech",
    "mediaingredientmech",
    "communitymech",
    "traitmech",
    "proteintraitsmech",
)


def _parse(document_text: str, name: str = "fleet.yaml"):
    import yaml

    return parse_fleet_manifest(yaml.safe_load(document_text), Path(name))


def _shipped_document():
    import yaml

    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))


def _authoritative_document():
    document = _shipped_document()
    assert document["vendored_governance"]["state"] == "authoritative"
    return document


def _transition_document():
    """Return a valid legacy-state fixture without weakening shipped state."""

    document = _shipped_document()
    governance = document["vendored_governance"]
    governance["state"] = "transition"
    governance["legacy_hub"] = "culturemech"
    for key, mech in document["mechs"].items():
        is_legacy_hub = key == "culturemech"
        mech["vendored_role"] = "hub" if is_legacy_hub else "spoke"
        vendored_sync = mech["capabilities"]["vendored_sync"]
        if is_legacy_hub:
            vendored_sync["status"] = "not_applicable"
            vendored_sync["reason"] = "valid synthetic transition fixture"
    return document


def _minimal(*extra_lines: str, **overrides: str) -> str:
    """Build a one-Mech manifest, optionally appending already-indented lines.

    ``extra_lines`` are appended verbatim; they must carry their own
    indentation. Running them through ``textwrap.dedent`` would strip the
    nesting and silently promote them to top-level keys, which makes a
    negative test pass for the wrong reason.
    """

    lines = [
        "version: 1",
        "vendored_governance:",
        "  state: transition",
        "  canonical_repository: CultureBotAI/culturebotai-claw",
        "  manifest_path: src/kg_microbe_governance/vendored_artifacts.json",
        "  pin_path: scripts/.vendored_canon_ref",
        "  legacy_hub: culturemech",
        "mechs:",
        "  culturemech:",
        "    display_name: CultureMech",
        "    github: CultureBotAI/CultureMech",
        "    environment_variable: CULTUREMECH_ROOT",
        "    vendored_role: hub",
        *extra_lines,
    ]
    body = "\n".join(lines) + "\n"
    for old, new in overrides.items():
        body = body.replace(old, new)
    return body


# --------------------------------------------------------------------------
# The shipped manifest
# --------------------------------------------------------------------------


def test_shipped_manifest_declares_all_five_mechs():
    manifest = load_fleet_manifest(MANIFEST_PATH)

    assert set(manifest.keys) == set(EXPECTED_MECHS)


def test_proteintraitsmech_github_slug_is_lowercase():
    """The display name is CamelCase but the slug is not; reconstructing the
    identity from the display name yields a 404."""

    manifest = load_fleet_manifest(MANIFEST_PATH)

    mech = manifest.get("proteintraitsmech")
    assert mech.github == "CultureBotAI/proteintraitsmech"
    assert mech.display_name == "ProteinTraitsMech"


def test_knowledge_gap_scan_is_not_applicable_to_proteintraitsmech_with_a_reason():
    manifest = load_fleet_manifest(MANIFEST_PATH)

    capability = manifest.get("proteintraitsmech").capability("knowledge_gap_scan")
    assert capability is not None
    assert capability.status == "not_applicable"
    assert capability.reason
    assert not manifest.get("proteintraitsmech").supports("knowledge_gap_scan")


def test_every_non_enabled_capability_states_a_reason():
    manifest = load_fleet_manifest(MANIFEST_PATH)

    for mech in manifest.mechs.values():
        for capability in mech.capabilities.values():
            if capability.status != "enabled":
                assert capability.reason, (
                    f"{mech.key}.{capability.name} is '{capability.status}' "
                    "without a recorded reason"
                )


def test_shipped_governance_is_authoritative_with_only_consumers():
    manifest = load_fleet_manifest(MANIFEST_PATH)

    assert manifest.vendored_governance.state == "authoritative"
    assert manifest.vendored_hub is None
    assert (
        manifest.vendored_governance.canonical_repository
        == "CultureBotAI/culturebotai-claw"
    )
    assert manifest.vendored_governance.manifest_path.endswith(
        "vendored_artifacts.json"
    )
    assert all(
        mech.vendored_role == "consumer" for mech in manifest.mechs.values()
    )
    assert all(
        mech.capability("vendored_sync").status == "enabled"
        for mech in manifest.mechs.values()
    )


# --------------------------------------------------------------------------
# No component may carry its own fleet list
# --------------------------------------------------------------------------


def test_repository_registry_is_derived_from_the_manifest():
    """The old default registry was the three-Mech literal that started drift."""

    from plugins.repository_settings import repository_definitions

    manifest = load_fleet_manifest(MANIFEST_PATH)
    definitions = repository_definitions(manifest)

    assert set(definitions) == set(manifest.keys)
    for key, definition in definitions.items():
        mech = manifest.get(key)
        assert definition.environment_variable == mech.environment_variable
        assert definition.expected_repository == mech.github


def test_openclaw_config_repositories_match_the_manifest():
    import yaml

    document = yaml.safe_load(
        default_config_path().read_text(encoding="utf-8")
    )
    manifest = load_fleet_manifest(MANIFEST_PATH)

    assert set(document["repositories"]) == set(manifest.keys)
    for key, mech in manifest.mechs.items():
        assert document["repositories"][key]["path"] == (
            "${" + mech.environment_variable + "}"
        )


def test_env_example_documents_every_manifest_root():
    text = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")
    manifest = load_fleet_manifest(MANIFEST_PATH)

    missing = [
        mech.environment_variable
        for mech in manifest.mechs.values()
        if f"{mech.environment_variable}=" not in text
    ]
    assert not missing, f".env.example is missing: {', '.join(missing)}"


def _mechs_named_in(body: str, manifest) -> list[str]:
    """The single detector shared by the guard and its meta-test.

    Kept as one function on purpose: when the guard and the test that proves
    the guard works are separate copies, weakening the guard leaves the proof
    green — which is how the first version shipped enforcing nothing.

    ``mech.key`` is included because both literals this rule removed were keyed
    by the lowercase key, so a key-only re-declaration is the most likely
    regression and the most likely thing to be missed.
    """

    return sorted(
        {
            mech.key
            for mech in manifest.mechs.values()
            for token in (
                mech.key,
                mech.environment_variable,
                mech.github,
                mech.display_name,
            )
            if token in body
        }
    )


def _scannable_body(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )


@pytest.mark.parametrize(
    "relative_path",
    [
        "cli/main.py",
        "plugins/repository_settings.py",
        "scripts/fleet_pr_status.py",
        "scripts/check_edison_keys.py",
        "scripts/environment_coverage_dashboard.py",
        "scripts/install_hooks.sh",
        "validate_setup.py",
        ".github/workflows/knowledge-gap-scan.yaml",
        ".claude/skills/fleet-pr-review/SKILL.md",
    ],
)
def test_supported_components_do_not_hardcode_a_fleet_list(relative_path: str):
    """Reject a reintroduced literal enumerating Mech identities or roots.

    Scans the whole non-comment body, not line by line. A per-line check is
    vacuous against ruff-formatted code: the three-Mech literals this rule
    exists to prevent put one repository per line, so nothing ever
    co-occurred. Naming two or more distinct Mechs anywhere in a supported
    module is the actual signal; naming one is legitimate.
    """

    text = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
    manifest = load_fleet_manifest(MANIFEST_PATH)

    named = _mechs_named_in(_scannable_body(text), manifest)

    assert len(named) < 2, (
        f"{relative_path} enumerates multiple Mechs ({', '.join(named)}); "
        "derive them from the fleet manifest instead"
    )


def test_the_hardcoding_guard_would_have_caught_the_literals_it_replaced():
    """The guard must fail against the pre-manifest code, or it proves nothing.

    The first version of this check passed against `origin/main`'s three-Mech
    literals, so it enforced nothing while `src/kg_microbe_fleet/fleet.yaml` advertised that it
    did. This pins the guard to a known-bad input.
    """

    manifest = load_fleet_manifest(MANIFEST_PATH)
    # A faithful reproduction of the shape that actually drifted: one
    # repository per line, exactly as ruff formats it.
    known_bad = "\n".join(
        [
            "repository_names = {",
            '    "culturemech": "CultureMech",',
            '    "mediaingredientmech": "MediaIngredientMech",',
            '    "communitymech": "CommunityMech",',
            "}",
        ]
    )

    named = _mechs_named_in(known_bad, manifest)

    assert len(named) >= 2, (
        "the guard does not detect a one-per-line three-Mech literal, which is "
        "the exact form this rule exists to reject"
    )


def test_cli_commands_report_every_manifest_mech():
    """Behavioural counterpart to the grep guard.

    A module could satisfy the text scan while still displaying a truncated
    fleet, so assert on what the commands actually print.
    """

    from click.testing import CliRunner

    from cli.main import cli

    manifest = load_fleet_manifest(MANIFEST_PATH)
    runner = CliRunner()
    status_output = runner.invoke(cli, ["status"]).output
    show_output = runner.invoke(cli, ["config", "show"]).output

    for mech in manifest.mechs.values():
        assert mech.display_name in status_output, (
            f"`status` omits {mech.key}"
        )
        assert mech.environment_variable in show_output, (
            f"`config show` omits {mech.key}"
        )


# --------------------------------------------------------------------------
# Loader validation is fail-closed
# --------------------------------------------------------------------------


def test_unsupported_version_is_rejected():
    with pytest.raises(FleetManifestError, match="version"):
        _parse(_minimal(**{"version: 1": "version: 99"}))


def test_capability_without_a_status_is_rejected():
    document = _minimal(
        "    capabilities:",
        "      id_label_validation:",
        "        reason: no status given",
    )

    with pytest.raises(FleetManifestError, match="status must be one of"):
        _parse(document)


def test_not_applicable_without_a_reason_is_rejected():
    """A capability may be switched off, but never silently."""

    document = _minimal(
        "    capabilities:",
        "      knowledge_gap_scan:",
        "        status: not_applicable",
    )

    with pytest.raises(FleetManifestError, match="reason is required"):
        _parse(document)


def test_disabled_without_a_reason_is_rejected():
    document = _minimal(
        "    capabilities:",
        "      knowledge_gap_scan:",
        "        status: disabled",
    )

    with pytest.raises(FleetManifestError, match="reason is required"):
        _parse(document)


def test_malformed_github_identity_is_rejected():
    with pytest.raises(FleetManifestError, match="owner/repository"):
        _parse(_minimal(**{"github: CultureBotAI/CultureMech": "github: CultureMech"}))


@pytest.mark.parametrize("repository", [".", ".."])
def test_github_identity_rejects_path_segments(repository: str):
    with pytest.raises(FleetManifestError, match="owner/repository"):
        _parse(
            _minimal(
                **{
                    "github: CultureBotAI/CultureMech": (
                        f"github: CultureBotAI/{repository}"
                    )
                }
            )
        )


def test_unknown_vendored_role_is_rejected():
    with pytest.raises(FleetManifestError, match="vendored_role"):
        _parse(_minimal(**{"vendored_role: hub": "vendored_role: canonical"}))


def test_vendored_hub_must_match_the_repository_declaring_the_hub_role():
    with pytest.raises(FleetManifestError, match="legacy_hub"):
        _parse(_minimal(**{"legacy_hub: culturemech": "legacy_hub: traitmech"}))


def test_manifest_without_a_hub_is_rejected():
    with pytest.raises(FleetManifestError, match="exactly one legacy vendored hub"):
        _parse(_minimal(**{"vendored_role: hub": "vendored_role: spoke"}))


def test_authoritative_governance_requires_every_mech_to_be_a_consumer():
    document = _minimal(
        **{
            "state: transition": "state: authoritative",
            "  legacy_hub: culturemech\n": "",
        }
    )
    with pytest.raises(FleetManifestError, match="vendored_role 'consumer'"):
        _parse(document)


def test_authoritative_governance_has_no_mech_hub_or_circular_pin():
    manifest = parse_fleet_manifest(_authoritative_document(), Path("fleet.yaml"))
    assert manifest.vendored_hub is None
    assert manifest.vendored_governance.state == "authoritative"
    assert manifest.get("culturemech").vendored_role == "consumer"


def test_authoritative_governance_rejects_null_legacy_hub():
    document = _authoritative_document()
    document["vendored_governance"]["legacy_hub"] = None

    with pytest.raises(FleetManifestError, match="must omit legacy_hub"):
        parse_fleet_manifest(document, Path("fleet.yaml"))


@pytest.mark.parametrize("status", ["disabled", "not_applicable"])
def test_authoritative_governance_requires_enabled_vendored_sync(status: str):
    document = _authoritative_document()
    capability = document["mechs"]["culturemech"]["capabilities"]["vendored_sync"]
    capability["status"] = status
    capability["reason"] = "intentionally invalid final-state fixture"

    with pytest.raises(
        FleetManifestError,
        match="vendored_sync.status must be 'enabled' for an authoritative consumer",
    ):
        parse_fleet_manifest(document, Path("fleet.yaml"))


@pytest.mark.parametrize("status", ["enabled", "disabled"])
def test_transition_requires_hub_vendored_sync_not_applicable(status: str):
    document = _transition_document()
    capability = document["mechs"]["culturemech"]["capabilities"]["vendored_sync"]
    capability["status"] = status
    if status == "disabled":
        capability["reason"] = "intentionally invalid transition fixture"
    else:
        capability.pop("reason", None)

    with pytest.raises(
        FleetManifestError,
        match=(
            "vendored_sync.status must be 'not_applicable' for a transition "
            "legacy hub"
        ),
    ):
        parse_fleet_manifest(document, Path("fleet.yaml"))


@pytest.mark.parametrize("status", ["disabled", "not_applicable"])
def test_transition_requires_spoke_vendored_sync_enabled(status: str):
    document = _transition_document()
    capability = document["mechs"]["traitmech"]["capabilities"]["vendored_sync"]
    capability["status"] = status
    capability["reason"] = "intentionally invalid transition fixture"

    with pytest.raises(
        FleetManifestError,
        match="vendored_sync.status must be 'enabled' for a transition spoke",
    ):
        parse_fleet_manifest(document, Path("fleet.yaml"))


def test_vendored_authority_cannot_be_a_mech_repository():
    with pytest.raises(FleetManifestError, match="external to the Mech fleet"):
        _parse(
            _minimal(
                **{
                    "canonical_repository: CultureBotAI/culturebotai-claw": (
                        "canonical_repository: CultureBotAI/CultureMech"
                    )
                }
            )
        )


@pytest.mark.parametrize("repository", [".", ".."])
def test_vendored_authority_rejects_path_segments(repository: str):
    with pytest.raises(FleetManifestError, match="owner/repository"):
        _parse(
            _minimal(
                **{
                    "canonical_repository: CultureBotAI/culturebotai-claw": (
                        f"canonical_repository: CultureBotAI/{repository}"
                    )
                }
            )
        )


def test_transition_rejects_a_partial_consumer_role_flip():
    with pytest.raises(FleetManifestError, match="atomic authority flip"):
        _parse(
            _minimal(
                "  traitmech:",
                "    display_name: TraitMech",
                "    github: CultureBotAI/TraitMech",
                "    environment_variable: TRAITMECH_ROOT",
                "    vendored_role: consumer",
            )
        )


def test_duplicate_github_identity_is_rejected():
    document = _minimal(
        "  traitmech:",
        "    display_name: TraitMech",
        "    github: CultureBotAI/CultureMech",
        "    environment_variable: TRAITMECH_ROOT",
        "    vendored_role: spoke",
    )

    with pytest.raises(FleetManifestError, match="duplicate GitHub identity"):
        _parse(document)


def test_duplicate_environment_variable_is_rejected():
    document = _minimal(
        "  traitmech:",
        "    display_name: TraitMech",
        "    github: CultureBotAI/TraitMech",
        "    environment_variable: CULTUREMECH_ROOT",
        "    vendored_role: spoke",
    )

    with pytest.raises(FleetManifestError, match="duplicate environment variable"):
        _parse(document)


def test_missing_manifest_file_is_rejected():
    with pytest.raises(FleetManifestError, match="Unable to load"):
        load_fleet_manifest(Path("/nonexistent/fleet.yaml"))


def test_duplicate_yaml_mapping_key_is_rejected(tmp_path: Path):
    """A typo must not silently replace an earlier security boundary."""

    manifest_path = tmp_path / "duplicate.yaml"
    manifest_path.write_text(
        _minimal(**{"github: CultureBotAI/CultureMech": "github: CultureBotAI/CultureMech\n"
                    "    github: CultureBotAI/Impostor"}),
        encoding="utf-8",
    )

    with pytest.raises(FleetManifestError, match="duplicate key 'github'"):
        load_fleet_manifest(manifest_path)


def test_documented_and_ci_mypy_targets_agree():
    """The type-check gate must be the same in both docs and CI.

    These drifted while adding this package: CLAUDE.md gained
    `src/kg_microbe_fleet` and the workflow did not, so the fail-closed loader
    presented as the new source of truth was the one module CI never
    type-checked.
    """

    import re

    claude = (REPOSITORY_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "tests.yaml"
    ).read_text(encoding="utf-8")

    documented = re.search(r"uv run --extra dev mypy \\\n(.*?)\nuv run", claude, re.S)
    readme_documented = re.search(
        r"uv run --extra dev mypy \\\n(.*?)\nuv run", readme, re.S
    )
    ci = re.search(r"uv run --extra dev mypy\n(.*?)\n\n", workflow, re.S)
    assert documented and readme_documented and ci, (
        "could not locate all three mypy invocations"
    )

    documented_targets = set(documented.group(1).replace("\\", "").split())
    readme_targets = set(
        readme_documented.group(1).replace("\\", "").split()
    )
    ci_targets = set(ci.group(1).split())

    assert documented_targets == readme_targets == ci_targets, (
        "README.md, CLAUDE.md, and CI disagree on mypy targets: "
        f"{(documented_targets ^ ci_targets) | (readme_targets ^ ci_targets)}"
    )


def test_manifest_ships_inside_the_package():
    """The manifest must be packaged, not left at the repository root.

    `plugins.repository_settings` builds its registry at import time, so a
    manifest missing from the wheel makes the installed distribution
    un-importable and the console script unable to start. An editable install
    hides this, so assert the packaging declaration directly.
    """

    import tomllib

    manifest_file = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(manifest_file.read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]

    assert MANIFEST_PATH.is_file(), "the manifest must live inside the package"
    assert MANIFEST_PATH.name in package_data.get("kg_microbe_fleet", []), (
        "kg_microbe_fleet package-data must ship the manifest"
    )
