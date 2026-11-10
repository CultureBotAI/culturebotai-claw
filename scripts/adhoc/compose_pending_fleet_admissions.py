"""Compose reviewed pending admissions without replacing historical sources.

Inputs: immutable PR heads #1056, #1072, #1074 and current checkout.
Outputs: combined registration candidate; source declarations stay attributed.
Purpose: requested public-membership integration, 2026-11-10. Run once on main.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import yaml

ROOT = Path(__file__).resolve().parents[2]
ADMISSIONS = {
    "cofactormech": "d1ac875d7037d059a7bc97429480ae01eea9f2f9",
    "assaymech": "3cb87b411bc4ebc6c91a45bc48848361e713ebe2",
    "scaleupmech": "f006a24a4ff4164498db0a222ff81d9b875d1616",
}


def read(ref, path):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode()


def write(path, content):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def replace(path, old, new):
    content = (ROOT / path).read_text()
    assert old in content, (path, old)
    write(path, content.replace(old, new))


def main():
    latest = ADMISSIONS["scaleupmech"]
    common = [
        "src/kg_microbe_governance/__init__.py",
        "src/kg_microbe_governance/infrastructure_admission.py",
        "src/kg_microbe_governance/cycle_release_audit.py",
        ".github/workflows/governance-fleet-audit.yaml",
        ".github/workflows/tests.yaml",
        "tests/test_governance_cycle_release_workflow.py",
    ]
    base = subprocess.check_output(["git", "merge-base", "origin/main", latest], cwd=ROOT).decode().strip()
    patch = subprocess.check_output(["git", "diff", base, latest, "--", *common], cwd=ROOT)
    subprocess.run(["git", "apply", "--check"], cwd=ROOT, input=patch, check=True)
    subprocess.run(["git", "apply"], cwd=ROOT, input=patch, check=True)
    for path in ["src/kg_microbe_governance/consumer_admission.py",
                 "tests/test_governance_consumer_admission.py",
                 "tests/test_governance_consumer_sync.py",
                 "tests/test_governance_private_release_hook.py"]:
        write(path, read(latest, path))

    manifest_path = "src/kg_microbe_governance/vendored_artifacts.json"
    manifest = json.loads((ROOT / manifest_path).read_text())
    ledger_path = "tests/test_vendored_consumer_completeness.py"
    ledger = (ROOT / ledger_path).read_text()
    ledger_marker = "INCOMPLETE_CONSUMERS: dict[str, IncompleteConsumer] = {"
    ledger_entries = []
    for key, ref in ADMISSIONS.items():
        fleet_path = "src/kg_microbe_fleet/fleet.yaml"
        source = read(ref, fleet_path)
        header = source.rfind("\n  # ")
        assert f"\n  {key}:\n" in source[header:]
        entry = source[header:]
        if key == "scaleupmech":
            entry = entry.replace("    display_name: ScaleupMech", "    tags: [exclude-from-public]\n    display_name: ScaleupMech")
        write(fleet_path, (ROOT / fleet_path).read_text().rstrip() + "\n" + entry)

        source_manifest = json.loads(read(ref, manifest_path))
        manifest["consumers"][key] = source_manifest["consumers"][key]
        for artifact in manifest["artifacts"]:
            original = next(a for a in source_manifest["artifacts"] if a["id"] == artifact["id"])
            if isinstance(artifact["consumers"], list) and key in original["consumers"]:
                artifact["consumers"].append(key)

        for suffix in ["admission-v1.json", "source-manifest.json"]:
            path = f"src/kg_microbe_governance/releases/{key}-infrastructure-{suffix}"
            content = read(ref, path)
            if key == "scaleupmech" and suffix == "admission-v1.json":
                policy = json.loads(content)
                raw = yaml.safe_load(entry)[key]
                policy["fleet_entry_sha256"] = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                content = json.dumps(policy, indent=2) + "\n"
            write(path, content)

        config = "src/kg_microbe_config/openclaw_config.yaml"
        block = read(ref, config).split(f"\n  {key}:\n", 1)[1].split("\nagents:", 1)[0]
        replace(config, "\nagents:", f"\n  {key}:\n{block}\nagents:")
        env = ".env.example"
        write(env, (ROOT / env).read_text() + next(line for line in read(ref, env).splitlines(keepends=True) if line.startswith(key.upper() + "_ROOT=")))
        rollout = "src/kg_microbe_embeddings/rollout.yaml"
        write(rollout, (ROOT / rollout).read_text().rstrip() + f"\n\n  {key}:\n" + read(ref, rollout).split(f"\n  {key}:\n", 1)[1])
        queue = "src/kg_microbe_merge_queue/policy.json"
        queue_doc = json.loads((ROOT / queue).read_text())
        source_queue = json.loads(read(ref, queue))
        queue_doc[key] = source_queue[key]
        write(queue, json.dumps(queue_doc, indent=2) + "\n")
        display = yaml.safe_load(entry)[key]["display_name"]
        replace("src/kg_microbe_research/schema/research.yaml", "      EdgeMech:\n", f"      EdgeMech:\n      {display}:\n")
        replace("src/kg_microbe_fleet/schema/fleet_pull.yaml", "  FleetPullStatusEnum:", f"      {key}:\n        description: {display} repository.\n\n  FleetPullStatusEnum:")
        replace("tests/test_fleet_manifest.py", '    "edgemech",\n)', f'    "{key}",\n    "edgemech",\n)')
        profiles = "tests/test_fleet_manifest_profiles.py"
        block = read(ref, profiles).split("EXPECTED_PROFILES = {\n", 1)[1].split('    "aimech":', 1)[0]
        replace(profiles, "EXPECTED_PROFILES = {\n", "EXPECTED_PROFILES = {\n" + block)
        domain = "tests/test_review_domain_fit.py"
        line = next(line for line in read(ref, domain).splitlines(keepends=True) if line.startswith(f'    "{key}":'))
        replace(domain, "CASES = {\n", "CASES = {\n" + line)
        ledger_entries.append(read(ref, ledger_path).split(ledger_marker, 1)[1].split("\n}\n", 1)[0])
        test_path = f"tests/test_{key}_admission.py"
        write(test_path, read(ref, test_path))
        doc = f"docs/guides/{key.upper()}_ADMISSION.md"
        write(doc, read(ref, doc))

    write(manifest_path, json.dumps(manifest, indent=2) + "\n")
    assert ledger_marker + "}" in ledger
    write(ledger_path, ledger.replace(ledger_marker + "}", ledger_marker + "".join(ledger_entries) + "\n}"))
    replace("tests/test_agent_fleet_scope.py", 'excluded.add("edgemech")', 'excluded |= {"edgemech", "cofactormech", "assaymech", "scaleupmech"}')
    replace("tests/test_fleet_count_prose.py", "assert len(load_fleet_manifest().mechs) == 15", "assert len(load_fleet_manifest().mechs) == 18")
    replace("tests/test_governance_consumer_admission.py", 'assert set(additions) == {"scaleupmech"}', 'assert set(additions) == {"cofactormech", "assaymech", "scaleupmech"}')


def refresh_candidate():
    """Reconcile the newly added catalogue capability and reseal unpublished entries."""
    path = ROOT / "src/kg_microbe_fleet/fleet.yaml"
    content = path.read_text()
    for key in ADMISSIONS:
        start = content.index(f"\n  {key}:\n")
        next_entry = content.find("\n  # ", start)
        end = next_entry if next_entry >= 0 else len(content)
        block = content[start:end]
        if "      taxon_links:" not in block:
            block = block.rstrip() + "\n      taxon_links:\n        status: disabled\n        reason: Taxon-bearing slots cannot be measured before the scaffold and seed reach the default branch.\n"
            content = content[:start] + block + content[end:]
    path.write_text(content)
    doc = yaml.safe_load(content)
    for key in ADMISSIONS:
        policy_path = ROOT / f"src/kg_microbe_governance/releases/{key}-infrastructure-admission-v1.json"
        policy = json.loads(policy_path.read_text())
        policy["fleet_entry_sha256"] = hashlib.sha256(json.dumps(doc["mechs"][key], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        policy_path.write_text(json.dumps(policy, indent=2) + "\n")


if __name__ == "__main__":
    if "--refresh-candidate" not in sys.argv:
        main()
    refresh_candidate()
