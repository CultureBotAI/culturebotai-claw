#!/usr/bin/env python3
"""Apply a named cadence profile from .github/cron-profiles.yaml to the workflows.

Rewrites ONLY the `on.schedule:` block of each canonical governed workflow,
and updates its manifest checksum. Downstream copies require the normal re-pin.
Inputs, jobs and every comment outside that block are left byte-for-byte alone,
which is why this
edits lines rather than round-tripping through a YAML dumper — a dumper would
discard the comments that carry the reasoning.

    python scripts/apply_cron_profile.py <profile> [--dry-run] [--config PATH]
    python scripts/apply_cron_profile.py --list

Exit codes: 0 ok, 1 configuration/workflow/application failure, 2 bad usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from kg_microbe_governance import Artifact, parse_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / ".github" / "cron-profiles.yaml"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
MANIFEST_PATH = REPO_ROOT / "src/kg_microbe_governance/vendored_artifacts.json"
CANONICAL_WORKFLOW_DIR = REPO_ROOT / "src/kg_microbe_governance/artifacts/workflows"


class UniqueLoader(yaml.BaseLoader):
    """Keep GitHub's `on` key a string and reject duplicate mapping keys."""


def _unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ValueError(f"invalid or duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _yaml(text: str):
    try:
        return yaml.load(text, Loader=UniqueLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML: {exc}") from exc


@dataclass(frozen=True)
class Target:
    artifact: Artifact
    path: Path


def resolve_targets(config: dict) -> dict[str, Target]:
    """Resolve implemented workflows only through the canonical manifest.

    Planned names may have future cadences, but cannot conceal an existing
    workflow. Every canonical workflow needs an explicit profile declaration.
    Directory walks include ignored/untracked payloads so a new workflow cannot
    acquire a schedule outside the manifest and silently pass the kill switch.
    """
    declarations = config.get("targets")
    if not isinstance(declarations, dict) or not declarations:
        raise ValueError("targets must explicitly classify every managed workflow")
    if set(declarations) != managed_workflows(config):
        raise ValueError("targets and profile workflow names must match exactly")
    manifest = parse_manifest(MANIFEST_PATH.read_bytes())
    workflows = {
        artifact.artifact_id: artifact
        for artifact in manifest.artifacts
        if PurePosixPath(artifact.target).parent == PurePosixPath(".github/workflows")
        and PurePosixPath(artifact.target).suffix in {".yaml", ".yml"}
    }
    targets = {}
    for stem, declaration in declarations.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", stem):
            raise ValueError(f"invalid workflow stem: {stem!r}")
        if not isinstance(declaration, dict):
            raise ValueError(f"{stem}: target must be an object")
        if any((WORKFLOW_DIR / f"{stem}{ext}").exists() for ext in (".yaml", ".yml")):
            raise ValueError(f"{stem}: local workflow bypasses canonical governance")
        if declaration.get("state") == "planned":
            if (
                set(declaration) != {"state", "reason"}
                or not isinstance(declaration["reason"], str)
                or not declaration["reason"].strip()
            ):
                raise ValueError(f"{stem}: planned target requires a reason and no artifact")
            continue
        if set(declaration) != {"state", "artifact"} or declaration.get("state") != "governed":
            raise ValueError(f"{stem}: target must be governed with an artifact, or planned")
        if not isinstance(declaration["artifact"], str):
            raise ValueError(f"{stem}: artifact must be an identifier string")
        artifact = workflows.get(declaration["artifact"])
        if artifact is None or PurePosixPath(artifact.target).stem != stem:
            raise ValueError(f"{stem}: missing or mismatched governed workflow artifact")
        path = REPO_ROOT / artifact.source
        if path.is_symlink() or not path.resolve().is_relative_to(REPO_ROOT.resolve()):
            raise ValueError(f"{stem}: unsafe canonical workflow path")
        if not path.is_file():
            raise ValueError(f"{stem}: canonical workflow missing: {artifact.source}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != artifact.sha256:
            raise ValueError(f"{stem}: canonical workflow checksum differs from manifest")
        targets[stem] = Target(artifact, path)
    resolved_ids = {target.artifact.artifact_id for target in targets.values()}
    if resolved_ids != set(workflows):
        raise ValueError(
            f"canonical workflows lack governed targets: {sorted(set(workflows) - resolved_ids)}"
        )
    if not targets:
        raise ValueError("no implemented governed workflow targets")
    registered_paths = {target.path.resolve() for target in targets.values()}
    discovered = {
        path.resolve()
        for path in CANONICAL_WORKFLOW_DIR.rglob("*")
        if path.is_file() and path.suffix in {".yaml", ".yml"}
    }
    if discovered - registered_paths:
        raise ValueError(
            "canonical workflow files are missing from governed targets: "
            + ", ".join(str(path) for path in sorted(discovered - registered_paths))
        )
    return targets


def load_config(path: Path) -> dict:
    data = _yaml(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        raise ValueError(f"{path} must have a profiles mapping")
    if not data["profiles"]:
        raise ValueError("profiles must not be empty")
    for name, profile in data["profiles"].items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
            raise ValueError(f"invalid profile name: {name!r}")
        if not isinstance(profile, dict) or not isinstance(profile.get("workflows"), dict):
            raise ValueError(f"{name}: profile must have a workflows mapping")
        for stem, entries in profile["workflows"].items():
            if not isinstance(entries, list):
                raise ValueError(f"{name}/{stem}: schedule must be a list")
            for entry in entries:
                if not isinstance(entry, dict) or not set(entry) <= {"cron", "comment"}:
                    raise ValueError(f"{name}/{stem}: invalid schedule entry")
                cron = entry.get("cron")
                if (
                    not isinstance(cron, str)
                    or len(cron.split()) != 5
                    or any(char in cron for char in ("\n", "\r", '"', "'"))
                ):
                    raise ValueError(f"{name}/{stem}: cron must have five fields on one line")
                comment = entry.get("comment", "")
                if not isinstance(comment, str) or any(char in comment for char in "\r\n"):
                    raise ValueError(f"{name}/{stem}: comment must be on one line")
    if "off" not in data["profiles"] or any(data["profiles"]["off"]["workflows"].values()):
        raise ValueError("off profile must exist and remove every schedule")
    return data


def managed_workflows(config: dict) -> set[str]:
    """Every workflow named by any profile.

    Union rather than intersection so a workflow added to one profile but
    forgotten in another is caught by the completeness check below instead of
    being silently unmanaged.
    """
    names: set[str] = set()
    for profile in config["profiles"].values():
        names.update((profile.get("workflows") or {}).keys())
    return names


def check_profiles_complete(config: dict) -> list[str]:
    """A profile that omits a managed workflow would leave it on its old cadence.

    That is the exact failure this file exists to prevent, so it is an error
    rather than a warning.
    """
    problems = []
    everything = managed_workflows(config)
    for name, profile in config["profiles"].items():
        missing = everything - set((profile.get("workflows") or {}).keys())
        if missing:
            problems.append(f"profile '{name}' does not mention: {', '.join(sorted(missing))}")
    return problems


def render_schedule(entries: list[dict]) -> list[str]:
    lines = ["  schedule:"]
    for entry in entries:
        cron = entry["cron"]
        comment = entry.get("comment")
        suffix = f"   # {comment}" if comment else ""
        lines.append(f'    - cron: "{cron}"{suffix}')
    return lines


def schedule_crons(text: str) -> list[str]:
    """Read YAML semantics so inline, unquoted and alternate-indent cron cannot hide."""
    document = _yaml(text)
    if not isinstance(document, dict) or not isinstance(document.get("on"), dict):
        raise ValueError("no top-level `on:` mapping")
    events = document["on"]
    if "schedule" not in events:
        return []
    entries = events["schedule"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("on.schedule must be a nonempty list; remove the key to disable")
    if any(
        not isinstance(entry, dict)
        or set(entry) != {"cron"}
        or not isinstance(entry["cron"], str)
        or len(entry["cron"].split()) != 5
        for entry in entries
    ):
        raise ValueError("on.schedule entries must contain one five-field cron string")
    return [entry["cron"] for entry in entries]


def check_active_profile(config: dict) -> list[str]:
    """Compare actual governed bytes to the active profile; planned names aren't live."""
    active = config.get("active")
    if active not in config.get("profiles", {}):
        return [f"active profile {active!r} does not exist"]
    try:
        targets = resolve_targets(config)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    problems = []
    wanted = config["profiles"][active]["workflows"]
    for stem, target in sorted(targets.items()):
        expected = [entry["cron"] for entry in wanted[stem]]
        try:
            actual = schedule_crons(target.path.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"{stem}: {exc}")
            continue
        if actual != expected:
            problems.append(f"{stem}: active={active} expects {expected}, found {actual}")
    return problems


def render_active_profile(text: str, profile: str) -> bytes:
    """Stage only the active scalar from the captured configuration bytes."""
    lines = text.splitlines()
    matches = [i for i, line in enumerate(lines) if line.startswith("active:")]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one top-level active key, found {len(matches)}")
    idx = matches[0]
    comment = ""
    if "#" in lines[idx]:
        comment = "  #" + lines[idx].split("#", 1)[1]
    lines[idx] = f"active: {json.dumps(profile)}{comment}"
    return ("\n".join(lines) + "\n").encode("utf-8")


def rewrite(text: str, entries: list[dict]) -> tuple[str, str]:
    """Return (new_text, what_changed). Raises ValueError if the shape is unexpected."""
    schedule_crons(text)  # validate semantics before editing a supported block shape
    lines = text.splitlines()

    on_idx = next((i for i, line in enumerate(lines) if line.rstrip() == "on:"), None)
    if on_idx is None:
        raise ValueError("no top-level `on:` block")

    # The `on:` block runs until the next line that starts in column 0 and is not
    # blank or a comment.
    end = len(lines)
    for i in range(on_idx + 1, len(lines)):
        stripped = lines[i]
        if stripped and not stripped[0].isspace() and not stripped.startswith("#"):
            end = i
            break

    sched_idx = next(
        (i for i in range(on_idx + 1, end) if lines[i].rstrip() == "  schedule:"), None
    )

    semantic_schedule = schedule_crons(text)
    if sched_idx is None and semantic_schedule:
        raise ValueError("schedule is not in the supported indented block form")
    if sched_idx is None:
        if not entries:
            return text, "already unscheduled"
        # Insert immediately after `on:` so the schedule reads first.
        new_lines = lines[: on_idx + 1] + render_schedule(entries) + lines[on_idx + 1 :]
        return "\n".join(new_lines) + "\n", f"added {len(entries)} cron entr(y/ies)"

    # Extent of the existing schedule block: only lines indented DEEPER than
    # `  schedule:` belong to it. A comment at two-space indent belongs to the
    # next key, and swallowing it would discard exactly the prose this script
    # exists to preserve (#39). Blank lines are consumed only when more of the
    # block follows, never as trailing padding.
    sched_end = sched_idx + 1
    pending_blanks = 0
    while sched_end < end:
        line = lines[sched_end]
        if line.strip() == "":
            pending_blanks += 1
            sched_end += 1
            continue
        if line.startswith("    "):
            pending_blanks = 0
            sched_end += 1
            continue
        break
    sched_end -= pending_blanks  # hand back trailing blank lines

    if not entries:
        new_lines = lines[:sched_idx] + lines[sched_end:]
        return "\n".join(new_lines) + "\n", "removed the schedule block"

    new_lines = lines[:sched_idx] + render_schedule(entries) + lines[sched_end:]
    return "\n".join(new_lines) + "\n", f"set {len(entries)} cron entr(y/ies)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile", nargs="?", help="profile name from cron-profiles.yaml")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true", dest="do_list")
    ap.add_argument(
        "--check-active",
        action="store_true",
        help="fail if managed workflow schedules do not match the active profile",
    )
    args = ap.parse_args(argv)

    try:
        config = load_config(Path(args.config))
        targets = resolve_targets(config)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    problems = check_profiles_complete(config)
    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        print(
            "Every profile must name every managed workflow — an omission would "
            "silently leave it on its previous cadence.",
            file=sys.stderr,
        )
        return 1

    if args.check_active:
        active_problems = check_active_profile(config)
        if active_problems:
            for problem in active_problems:
                print(f"error: {problem}", file=sys.stderr)
            return 1
        print(
            f"active profile '{config.get('active')}' matches {len(targets)} governed workflows; "
            "deployed state requires fleet-audit"
        )
        return 0

    if args.do_list or not args.profile:
        active = config.get("active")
        print(f"active: {active}")
        for name, profile in config["profiles"].items():
            marker = "*" if name == active else " "
            desc = " ".join((profile.get("description") or "").split())
            print(f" {marker} {name}: {desc}")
        if not args.profile:
            return 0
        return 0

    if args.profile not in config["profiles"]:
        print(
            f"error: unknown profile '{args.profile}'. Known: {', '.join(config['profiles'])}",
            file=sys.stderr,
        )
        return 2

    wanted = config["profiles"][args.profile]["workflows"]
    edits: dict[Path, bytes] = {}
    originals: dict[Path, bytes] = {}
    descriptions = []
    manifest_bytes = MANIFEST_PATH.read_bytes()
    originals[MANIFEST_PATH] = manifest_bytes
    manifest_data = json.loads(manifest_bytes)
    manifest_artifacts = {artifact["id"]: artifact for artifact in manifest_data["artifacts"]}
    try:
        # Prepare and verify the whole change before touching any file. A missing
        # target or unsupported YAML shape must not leave half a profile applied.
        for stem, entries in sorted(wanted.items()):
            if stem not in targets:
                descriptions.append(f"  planned {stem}: {config['targets'][stem]['reason']}")
                continue
            target = targets[stem]
            original = target.path.read_bytes()
            originals[target.path] = original
            updated, what = rewrite(original.decode("utf-8"), entries)
            if schedule_crons(updated) != [entry["cron"] for entry in entries]:
                raise ValueError(f"{stem}: rewrite did not produce the requested schedule")
            updated_bytes = updated.encode("utf-8")
            if updated_bytes == original:
                descriptions.append(f"  ok    {stem}: {target.artifact.source} unchanged")
                continue
            edits[target.path] = updated_bytes
            manifest_artifacts[target.artifact.artifact_id]["sha256"] = hashlib.sha256(
                updated_bytes
            ).hexdigest()
            descriptions.append(
                f"  {'would' if args.dry_run else 'wrote'} {stem}: {what} ({target.artifact.source})"
            )
        workflow_changes = len(edits)
        if edits:
            edits[MANIFEST_PATH] = (json.dumps(manifest_data, indent=2) + "\n").encode()
        config_path = Path(args.config)
        originals[config_path] = config_path.read_bytes()
        if _yaml(originals[config_path].decode()) != config or resolve_targets(config) != targets:
            raise ValueError("profile inputs changed during planning")
        expected_config = {**config, "active": args.profile}
        rendered_config = render_active_profile(originals[config_path].decode(), args.profile)
        if _yaml(rendered_config.decode()) != expected_config:
            raise ValueError("rendered active profile does not match the requested configuration")
        if rendered_config != originals[config_path]:
            edits[config_path] = rendered_config
    except (OSError, ValueError) as exc:
        print(f"error: {exc}; no files changed", file=sys.stderr)
        return 1

    if not args.dry_run:
        written: list[Path] = []
        try:
            for path, data in edits.items():
                _check_snapshot(originals, edits, written)
                # Record an attempted write too: promotion may succeed before a
                # cleanup failure is raised, so recovery must inspect its bytes.
                written.append(path)
                _atomic_write(path, data)
            _check_snapshot(originals, edits, written)
            actual_config = load_config(config_path)
            if actual_config != expected_config:
                raise ValueError("written configuration differs from the requested profile")
            problems = check_active_profile(actual_config)
            if problems:
                raise ValueError("post-apply verification failed: " + "; ".join(problems))
        except (OSError, ValueError) as exc:
            recovery_errors = _restore_attempted_writes(written, originals, edits)
            if recovery_errors:
                print(
                    f"error: {exc}; rollback incomplete: " + "; ".join(recovery_errors),
                    file=sys.stderr,
                )
            else:
                print(f"error: {exc}; this operation's changes restored", file=sys.stderr)
            return 1
    for description in descriptions:
        print(description)
    print(
        f"\nprofile '{args.profile}': {len(targets)} governed, "
        f"{len(wanted) - len(targets)} planned, "
        f"{workflow_changes} workflow changes"
    )
    if args.dry_run:
        print("Dry run: workflows, checksums and active profile left unchanged.")
    else:
        print(
            f"Active profile set to '{args.profile}'. Canonical files only; "
            "deployment requires publishing a reviewed claw revision, fleet re-pin and fleet-audit."
        )
    return 0


def _check_snapshot(
    originals: dict[Path, bytes], edits: dict[Path, bytes], written: list[Path]
) -> None:
    """Reject observed concurrent edits before promotion and at verification."""
    for path, original in originals.items():
        expected = edits[path] if path in written else original
        if path.read_bytes() != expected:
            raise ValueError(f"concurrent change detected; preserving {path}")


def _restore_attempted_writes(
    written: list[Path], originals: dict[Path, bytes], edits: dict[Path, bytes]
) -> list[str]:
    errors = []
    for path in reversed(written):
        try:
            current = path.read_bytes()
            if current == originals[path]:
                continue
            if current != edits[path]:
                raise ValueError("intervening bytes preserved")
            _atomic_write(path, originals[path])
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    return errors


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + f".tmp-{secrets.token_hex(4)}")
    try:
        temporary.write_bytes(data)
        temporary.chmod(path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
