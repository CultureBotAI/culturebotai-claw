"""Contract tests for the canonical fleet manifest.

Phase 0 of the standardization plan exists because several components each
carried their own Mech list and they disagreed. These tests pin the manifest's
validation rules and fail the build if a supported component grows a divergent
list again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kg_microbe_fleet import (
    FleetManifestError,
    load_fleet_manifest,
    parse_fleet_manifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPOSITORY_ROOT / "conf" / "fleet.yaml"

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


def _minimal(*extra_lines: str, **overrides: str) -> str:
    """Build a one-Mech manifest, optionally appending already-indented lines.

    ``extra_lines`` are appended verbatim; they must carry their own
    indentation. Running them through ``textwrap.dedent`` would strip the
    nesting and silently promote them to top-level keys, which makes a
    negative test pass for the wrong reason.
    """

    lines = [
        "version: 1",
        "vendored_hub: culturemech",
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


def test_exactly_one_vendored_hub_and_it_matches_the_declaration():
    manifest = load_fleet_manifest(MANIFEST_PATH)

    hubs = [
        key for key, mech in manifest.mechs.items() if mech.vendored_role == "hub"
    ]
    assert hubs == [manifest.vendored_hub]


# --------------------------------------------------------------------------
# No component may carry its own fleet list
# --------------------------------------------------------------------------


def test_repository_registry_is_derived_from_the_manifest():
    """`DEFAULT_REPOSITORIES` was the three-Mech literal that started the drift."""

    from plugins.repository_settings import DEFAULT_REPOSITORIES

    manifest = load_fleet_manifest(MANIFEST_PATH)

    assert set(DEFAULT_REPOSITORIES) == set(manifest.keys)
    for key, definition in DEFAULT_REPOSITORIES.items():
        mech = manifest.get(key)
        assert definition.environment_variable == mech.environment_variable
        assert definition.expected_repository == mech.github


def test_openclaw_config_repositories_match_the_manifest():
    import yaml

    document = yaml.safe_load(
        (REPOSITORY_ROOT / "openclaw_config.yaml").read_text(encoding="utf-8")
    )
    manifest = load_fleet_manifest(MANIFEST_PATH)

    assert set(document["repositories"]) == set(manifest.keys)


def test_env_example_documents_every_manifest_root():
    text = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")
    manifest = load_fleet_manifest(MANIFEST_PATH)

    missing = [
        mech.environment_variable
        for mech in manifest.mechs.values()
        if f"{mech.environment_variable}=" not in text
    ]
    assert not missing, f".env.example is missing: {', '.join(missing)}"


@pytest.mark.parametrize(
    "relative_path",
    ["cli/main.py", "plugins/repository_settings.py"],
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

    body = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )
    named = sorted(
        {
            mech.key
            for mech in manifest.mechs.values()
            for token in (
                mech.environment_variable,
                mech.github,
                mech.display_name,
            )
            if token in body
        }
    )

    assert len(named) < 2, (
        f"{relative_path} enumerates multiple Mechs ({', '.join(named)}); "
        "derive them from the fleet manifest instead"
    )


def test_the_hardcoding_guard_would_have_caught_the_literals_it_replaced():
    """The guard must fail against the pre-manifest code, or it proves nothing.

    The first version of this check passed against `origin/main`'s three-Mech
    literals, so it enforced nothing while `conf/fleet.yaml` advertised that it
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

    named = {
        mech.key
        for mech in manifest.mechs.values()
        for token in (mech.environment_variable, mech.github, mech.display_name)
        if token in known_bad
    }

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


def test_unknown_vendored_role_is_rejected():
    with pytest.raises(FleetManifestError, match="vendored_role"):
        _parse(_minimal(**{"vendored_role: hub": "vendored_role: canonical"}))


def test_vendored_hub_must_match_the_repository_declaring_the_hub_role():
    with pytest.raises(FleetManifestError, match="vendored_hub"):
        _parse(_minimal(**{"vendored_hub: culturemech": "vendored_hub: traitmech"}))


def test_manifest_without_a_hub_is_rejected():
    with pytest.raises(FleetManifestError, match="exactly one vendored hub"):
        _parse(_minimal(**{"vendored_role: hub": "vendored_role: spoke"}))


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


def test_documented_and_ci_mypy_targets_agree():
    """The type-check gate must be the same in CLAUDE.md and in CI.

    These drifted while adding this package: CLAUDE.md gained
    `src/kg_microbe_fleet` and the workflow did not, so the fail-closed loader
    presented as the new source of truth was the one module CI never
    type-checked.
    """

    import re

    claude = (REPOSITORY_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "tests.yaml"
    ).read_text(encoding="utf-8")

    documented = re.search(r"uv run --extra dev mypy \\\n(.*?)\nuv run", claude, re.S)
    ci = re.search(r"uv run --extra dev mypy\n(.*?)\n\n", workflow, re.S)
    assert documented and ci, "could not locate both mypy invocations"

    documented_targets = set(documented.group(1).replace("\\", "").split())
    ci_targets = set(ci.group(1).split())

    assert documented_targets == ci_targets, (
        "CLAUDE.md and .github/workflows/tests.yaml disagree on mypy targets: "
        f"{documented_targets ^ ci_targets}"
    )
