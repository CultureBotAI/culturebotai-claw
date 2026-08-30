"""#236. A capability `reason` is prose about another repository, and prose rots.

One reason named a `.github/workflows/generate-pages.yaml` that TraitMech does
not have; the sentence had been copied from the three Mechs that do. Nothing
noticed, because nothing checked -- and a reason is the *only* explanation a
reader gets for why a Mech opted out of a capability.

Rather than parse the English, each reason declares which paths it asserts about
and in which direction. These tests hold that declaration to both directions:

  - every path a reason mentions must be declared, so a new unchecked claim
    cannot be added by writing a sentence; and
  - every declared path must be mentioned, so the declaration cannot drift into
    a list of things the reason no longer says.

`absent` carries as much weight as `present`: over half these reasons exist to
say a Mech has *no* download.yaml, and a check that only confirmed existence
would have nothing to say about them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from kg_microbe_fleet import (
    FleetManifestError,
    ReasonClaims,
    load_fleet_manifest,
    parse_fleet_manifest,
)
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root

MANIFEST = load_fleet_manifest()
CLAW_ROOT = Path(__file__).resolve().parents[1]

# A path-like token: a name carrying an extension we would expect to resolve.
# `.html` is deliberately absent -- several reasons say "missing .html files"
# as a description of a class of file, not as a path.
_PATH_TOKEN = re.compile(
    r"(?<![\w/.])\.?[\w][\w./-]*\.(?:py|ya?ml|json|tsv|toml|cfg|sh)\b"
)

CLAW_PREFIX = "claw:"


def _declared(claims: ReasonClaims) -> tuple[str, ...]:
    return (*claims.present, *claims.absent)


def _reasons():
    for mech_name, mech in MANIFEST.mechs.items():
        for cap_name, capability in mech.capabilities.items():
            reason = (capability.reason or "").strip()
            if reason:
                yield mech_name, cap_name, " ".join(reason.split()), capability


_ALL = list(_reasons())
_IDS = [f"{m}.{c}" for m, c, _, _ in _ALL]


@pytest.mark.parametrize(("mech", "cap", "reason", "capability"), _ALL, ids=_IDS)
def test_every_path_a_reason_names_is_declared(mech, cap, reason, capability):
    """Forward direction: prose cannot make an unchecked claim."""
    declared = {Path(p.removeprefix(CLAW_PREFIX)).name for p in _declared(capability.reason_claims)}
    undeclared = {
        token for token in _PATH_TOKEN.findall(reason) if Path(token).name not in declared
    }
    assert not undeclared, (
        f"{mech}.{cap}'s reason names {sorted(undeclared)}, which it does not "
        f"declare in reason_claims, so nothing verifies the claim"
    )


@pytest.mark.parametrize(("mech", "cap", "reason", "capability"), _ALL, ids=_IDS)
def test_every_declared_path_is_one_the_reason_names(mech, cap, reason, capability):
    """Reverse direction: the declaration cannot outlive the sentence it checks."""
    orphans = [
        path
        for path in _declared(capability.reason_claims)
        if Path(path.removeprefix(CLAW_PREFIX)).name not in reason
    ]
    assert not orphans, (
        f"{mech}.{cap} declares {orphans}, which its reason no longer mentions; "
        f"either the reason was rewritten or the declaration is stale"
    )


def test_the_reasons_that_make_checkable_claims_are_the_ones_declared():
    """A ledger, so the count can only go up deliberately. Nine of the sixteen
    reasons name a path; the rest are judgements about scope ("trait records are
    not an environment inventory input") with nothing to resolve."""
    declared = sorted(
        f"{m}.{c}" for m, c, _, cap in _ALL if cap.reason_claims
    )
    assert declared == [
        "communitymech.page_budgets",
        "communitymech.source_catalogue",
        "culturemech.page_budgets",
        "culturemech.source_catalogue",
        "mediaingredientmech.page_budgets",
        "mediaingredientmech.source_catalogue",
        "proteintraitsmech.unmapped_inventory_input",
        "traitmech.page_budgets",
        "traitmech.unmapped_inventory_input",
    ]


@pytest.mark.parametrize(("mech", "cap", "reason", "capability"), _ALL, ids=_IDS)
def test_a_declared_claim_holds_against_the_checkout(mech, cap, reason, capability):
    """The point of the whole exercise: `present` must exist and `absent` must
    not, in the repository the declaration belongs to."""
    claims = capability.reason_claims
    if not claims:
        pytest.skip(f"{mech}.{cap} makes no checkable claim")

    def root_for(path: str) -> tuple[Path, str]:
        if path.startswith(CLAW_PREFIX):
            return CLAW_ROOT, path.removeprefix(CLAW_PREFIX)
        try:
            return resolve_mech_root(mech, claw_root=CLAW_ROOT), path
        except MechRootError as exc:
            pytest.skip(f"needs a {mech} checkout: {exc}")

    for path in claims.present:
        root, relative = root_for(path)
        assert (root / relative).exists(), (
            f"{mech}.{cap}'s reason asserts {relative} exists in {root.name}, "
            f"and it does not"
        )
    for path in claims.absent:
        root, relative = root_for(path)
        assert not (root / relative).exists(), (
            f"{mech}.{cap}'s reason asserts {relative} does NOT exist in "
            f"{root.name}, and it does"
        )


def test_the_claw_prefixed_claims_are_checked_even_with_no_mech_checkout():
    """`claw:` paths live in this repository, so they never skip. Both
    unmapped_inventory_input reasons name a claw script; if that check could
    skip, the only always-runnable case would be the one that never runs."""
    checked = 0
    for mech, cap, _, capability in _ALL:
        for path in capability.reason_claims.present:
            if path.startswith(CLAW_PREFIX):
                assert (CLAW_ROOT / path.removeprefix(CLAW_PREFIX)).exists(), (
                    f"{mech}.{cap} names a claw path that does not exist"
                )
                checked += 1
    assert checked == 2


# -- what the loader rejects ------------------------------------------------


MANIFEST_PATH = CLAW_ROOT / "src/kg_microbe_fleet/fleet.yaml"


def _parse(text: str):
    return parse_fleet_manifest(yaml.safe_load(text), MANIFEST_PATH)


def _manifest_with(claims_block: str) -> str:
    text = MANIFEST_PATH.read_text()
    anchor = """      source_catalogue:
        status: disabled
        reason: >-
          Has no download.yaml; its inputs arrive through per-source scripts
          rather than a declared catalogue. Adopting one would apply here;
          it has not been written.
        reason_claims:
          absent:
            - download.yaml
"""
    assert anchor in text
    replacement = anchor[: anchor.index("        reason_claims:")] + claims_block
    return text.replace(anchor, replacement, 1)


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ("        reason_claims:\n          maybe:\n            - x.yaml\n", "unknown keys"),
        ("        reason_claims:\n          present:\n            - /etc/passwd\n", "inside the"),
        # The prefixed forms: the scope must be split off before containment is
        # judged, or "claw:/etc/passwd" passes a startswith("/") check and the
        # consumer resolves an absolute path out of the repository.
        ("        reason_claims:\n          present:\n            - claw:/etc/passwd\n", "inside the"),
        ("        reason_claims:\n          present:\n            - claw:../escape.yaml\n", "inside the"),
        ("        reason_claims:\n          present:\n            - notascope:x.yaml\n", "unknown scope"),
        ("        reason_claims:\n          present:\n            - ../escape.yaml\n", "inside the"),
        (
            "        reason_claims:\n          present:\n            - a.yaml\n"
            "          absent:\n            - a.yaml\n",
            "both present and absent",
        ),
        (
            "        reason_claims:\n          present:\n            - a.yaml\n            - a.yaml\n",
            "repeats",
        ),
        ("        reason_claims:\n          present: notalist\n", "must be a list"),
    ],
    ids=[
        "unknown-key",
        "absolute",
        "scoped-absolute",
        "scoped-parent-escape",
        "unknown-scope",
        "parent-escape",
        "contradiction",
        "duplicate",
        "not-a-list",
    ],
)
def test_the_loader_rejects_an_unusable_declaration(block, message):
    with pytest.raises(FleetManifestError, match=message):
        _parse(_manifest_with(block))


def test_claims_without_a_reason_are_rejected():
    """A declaration with nothing to check is a mistake, not an empty success."""
    text = MANIFEST_PATH.read_text()
    anchor = """      vendored_sync:
        status: enabled
"""
    assert anchor in text
    broken = text.replace(
        anchor,
        anchor + "        reason_claims:\n          present:\n            - justfile\n",
        1,
    )
    with pytest.raises(FleetManifestError, match="nothing to check"):
        _parse(broken)
