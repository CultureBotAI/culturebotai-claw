#!/usr/bin/env python3
"""Revert each distinction in kg_microbe_links and confirm a test goes red.

Purpose: AGENTS.md requires a test for a distinction to be driven by an input
where the two sides differ, and mutation is how that is shown. Each mutant
below undoes one rule in src/kg_microbe_links/taxa.py or __main__.py; the
named test must fail with the mutant applied, and the two test files must
pass without it. The list includes every mutant the first review of PR 897
(culturebotai-claw#910) found surviving, those the second (#939-#944) did, those the third (#968-#973) did, those the fourth (#991-#993) did, those the fifth (#994, #995 and its surviving mutants) did, those the Codex review (#998-#1003) did, the merge-chain pair found after it (#1017, #1018), the review of those two rounds (#1019-#1023), and the verification of that (#1042).
Inputs: none; run from the claw checkout or worktree holding the script.
Outputs: one line per mutant (KILLED or SURVIVED) and a nonzero exit if any
survives, a mutant does not parse, a named test cannot be collected, or an
unmutated test file fails. A mutant whose test runs past TIMEOUT seconds (an
endless loop) is a kill: the test did not pass. Each
source file is restored after every mutant, also on error. Each run is a
fresh Python process running pytest.
Serves: culturebotai-claw PR 897. Written 2026-11-07.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAXA = "src/kg_microbe_links/taxa.py"
CLI = "src/kg_microbe_links/__main__.py"
TESTS = ["tests/test_taxon_links.py", "tests/test_taxon_links_cli.py"]
UNIT, CLI_TESTS = TESTS

MUTANTS = [
    (TAXA, "scope before merge table", "        if taxon in self.merged:  # before the scope", "        if False:  #",
     f"{UNIT}::test_a_retired_id_that_the_scope_still_lists_is_retired_not_a_record"),
    (TAXA, "no record verdict", "        if taxon in self.scope:\n            return Judgement(Verdict.RECORD, taxon)\n", "",
     f"{UNIT}::test_a_scoped_species_is_a_record"),
    (TAXA, "strain not resolved", "if ancestor is not None and below_species:", "if False:",
     f"{UNIT}::test_a_strain_resolves_to_its_scoped_species[511145-562]"),
    (TAXA, "genus not above species", 'if rank != "species" and not below_species:', "if False:",
     f"{UNIT}::test_a_genus_or_family_is_above_species[561]"),
    (TAXA, "metagenome not unplaced", 'if domain == "other":', "if False:", f"{UNIT}::test_a_metagenome_under_no_domain_is_unplaced_but_a_rank_above_species_there_is_above_species"),
    (TAXA, "protist outside the domain", "(domain == \"Eukaryota\" and kingdom not in NON_MICROBIAL_KINGDOMS)", "False",
     f"{UNIT}::test_an_unscoped_fungus_or_protist_is_unattested_but_an_animal_and_a_virus_are_outside_the_domain"),
    (TAXA, "animal unattested", 'NON_MICROBIAL_KINGDOMS = {"Metazoa", "Viridiplantae"}', "NON_MICROBIAL_KINGDOMS = set()",
     f"{UNIT}::test_an_unscoped_fungus_or_protist_is_unattested_but_an_animal_and_a_virus_are_outside_the_domain"),
    (TAXA, "retired without current verdict", "current=current, current_verdict=inner.verdict)", "current=current)",
     f"{UNIT}::test_a_retired_id_reports_its_current_id_and_that_id_s_own_verdict"),
    (TAXA, "inventory rank not lowercased", '(row["rank"] or "NO_RANK").lower().replace("_", " ")', '(row["rank"] or "NO_RANK")',
     f"{UNIT}::test_a_strain_resolves_to_its_scoped_species[83333-562]"),
    (TAXA, "taxdump read eagerly", "        if taxon in self.inventory:\n            return self.inventory[taxon]\n", "",
     f"{UNIT}::test_the_taxdump_is_read_only_for_taxa_the_inventory_lacks"),
    (TAXA, "names re-read", "        if self._names is None and any(", "        if any(",
     f"{UNIT}::test_names_come_from_the_inventory_or_the_taxdump_read_once"),
    (TAXA, "mis-bracketed path accepted", 'if not name or "[" in name or "]" in name or part != name + "[]" * lists:',
     "if not name:", f"{UNIT}::test_a_bad_slot_path_is_refused_before_any_record_is_read[a]].b]"),
    (TAXA, "other identifiers judged", 'if not (isinstance(value, str) and value.startswith("NCBITaxon:")):', "if False:",
     f"{UNIT}::test_collect_counts_occurrences_records_and_findings"),
    (TAXA, "null values judged", "                if value is None:\n                    continue\n", "",
     f"{UNIT}::test_a_null_value_is_neither_a_link_nor_a_finding"),
    (TAXA, "records counted per occurrence", "                if verdict not in seen_in_record:", "                if True:",
     f"{UNIT}::test_collect_counts_occurrences_records_and_findings"),
    (TAXA, "findings unsorted", '"findings": sorted(self.findings, key=lambda f: (f["record"], f["slot"], f["value"])),',
     '"findings": list(self.findings),', f"{UNIT}::test_findings_are_sorted_and_resolvable_is_most_cited_first"),
    (TAXA, "resolvable unsorted", "for t, n in sorted(self.resolvable.items(), key=lambda kv: (-kv[1], kv[0]))]",
     "for t, n in self.resolvable.items()]", f"{UNIT}::test_findings_are_sorted_and_resolvable_is_most_cited_first"),
    (TAXA, "sample ignored", "scope_size=len(index.scope), sample=sample)", "scope_size=len(index.scope))",
     f"{UNIT}::test_a_sample_reads_the_first_records_and_says_so"),
    (TAXA, "bad path not refused before the walk", "        resolve_all({}, slot)  # a bad path fails", "        pass  #",
     f"{UNIT}::test_collect_refuses_an_unusable_corpus_before_walking"),
    (CLI, "strict ignores unreadable records", 'if payload["unreadable"] or any(', "if any(",
     f"{CLI_TESTS}::test_strict_fails_when_the_only_record_will_not_parse"),
    (CLI, "strict ignores findings", "    return 1 if args.strict and blocking else 0", "    return 0",
     f"{CLI_TESTS}::test_strict_fails_on_a_retired_id_and_passes_without_one"),
    (CLI, "strict ignores absent", 'BLOCKING = {Verdict.RETIRED.value, Verdict.ABSENT.value, Verdict.MALFORMED.value}',
     'BLOCKING = {Verdict.RETIRED.value, Verdict.MALFORMED.value}',
     f"{CLI_TESTS}::test_strict_fails_on_an_absent_or_malformed_id[NCBITaxon:424242]"),
    (CLI, "strict ignores malformed", 'BLOCKING = {Verdict.RETIRED.value, Verdict.ABSENT.value, Verdict.MALFORMED.value}',
     'BLOCKING = {Verdict.RETIRED.value, Verdict.ABSENT.value}',
     f"{CLI_TESTS}::test_strict_fails_on_an_absent_or_malformed_id[NCBITaxon:bogus]"),
    (CLI, "per-Mech error exits 0", "            return 2\n        reports[key] = payload",
     "            return 0\n        reports[key] = payload",
     f"{CLI_TESTS}::test_an_unusable_mech_root_is_exit_two"),
    (CLI, "as_dict outside the guard",
     "            payload = report.as_dict(index)  # may read the taxdump, which can be missing: still exit 2\n        except (MechRootError, TaxonLinksError) as exc:\n            print(str(exc), file=sys.stderr)\n            return 2\n        reports[key] = payload",
     "        except (MechRootError, TaxonLinksError) as exc:\n            print(str(exc), file=sys.stderr)\n            return 2\n        payload = report.as_dict(index)\n        reports[key] = payload",
     f"{CLI_TESTS}::test_a_taxdump_needed_only_for_names_that_is_missing_is_exit_two"),
    (TAXA, "unplaced before above_species", '        if rank != "species" and not below_species:\n            return Judgement(Verdict.ABOVE_SPECIES, taxon, rank=rank, domain=domain, kingdom=kingdom)\n        if domain == "other":\n            return Judgement(Verdict.UNPLACED, taxon, rank=rank, domain=domain, kingdom=kingdom)\n',
     '        if domain == "other":\n            return Judgement(Verdict.UNPLACED, taxon, rank=rank, domain=domain, kingdom=kingdom)\n        if rank != "species" and not below_species:\n            return Judgement(Verdict.ABOVE_SPECIES, taxon, rank=rank, domain=domain, kingdom=kingdom)\n',
     f"{UNIT}::test_a_metagenome_under_no_domain_is_unplaced_but_a_rank_above_species_there_is_above_species"),
    (TAXA, "unattested unsorted", "for t, n in sorted(self.unattested.items(), key=lambda kv: (-kv[1], kv[0]))]",
     "for t, n in self.unattested.items()]", f"{UNIT}::test_unattested_taxa_are_listed_most_cited_first"),
    (TAXA, "findings' taxa looked up", "| set(self.unattested)))", "| set(self.unattested) | {f['taxon'] for f in self.findings if f.get('taxon')}))",
     f"{UNIT}::test_findings_need_no_taxdump_names"),
    (CLI, "--all dumps the last Mech only", "json.dump(reports if args.all else reports.get(keys[0], {}),",
     "json.dump(reports.get(keys[-1], {}),", f"{CLI_TESTS}::test_all_reports_every_enabled_mech_and_skips_the_rest"),
    (CLI, "--all stops at a non-enabled Mech", "            if not args.all:\n                print(", "            if True:\n                print(",
     f"{CLI_TESTS}::test_all_reports_every_enabled_mech_and_skips_the_rest"),
    (TAXA, "absent taxdump member is a KeyError", "            try:\n                handle = tar.extractfile(member)  # KeyError for an absent name; None for a non-file member\n            except KeyError:\n                handle = None\n",
     "            handle = tar.extractfile(member)\n", f"{CLI_TESTS}::test_a_taxdump_needed_only_for_names_that_is_missing_is_exit_two"),
    (TAXA, "corrupt taxdump is a TarError", "    except (tarfile.TarError, EOFError, OSError, zlib.error) as exc:", "    except ValueError as exc:",
     f"{CLI_TESTS}::test_a_taxdump_that_is_not_a_tarball_is_exit_two"),
    (TAXA, "truncated taxdump escapes mid-stream", "    except (tarfile.TarError, EOFError, OSError, zlib.error) as exc:", "    except tarfile.TarError as exc:",
     f"{CLI_TESTS}::test_a_truncated_taxdump_tarball_is_exit_two"),
    (TAXA, "absent tarball yields absent", "    if not tar_path.is_file():\n        raise TaxonLinksError(f\"TaxonMech's pinned taxdump {tar_path} is not present\")\n",
     "    if not tar_path.is_file():\n        return\n", f"{CLI_TESTS}::test_an_absent_taxdump_tarball_is_exit_two"),
    (TAXA, "names() swallows a taxdump error", '            self._names = self._dmp_table("names.dmp", lambda f: (int(f[0]), f[1]) if f[3] == "scientific name" else None)\n',
     '            try:\n                self._names = self._dmp_table("names.dmp", lambda f: (int(f[0]), f[1]) if f[3] == "scientific name" else None)\n            except TaxonLinksError:\n                self._names = {}\n',
     f"{CLI_TESTS}::test_a_taxdump_needed_only_for_names_that_is_missing_is_exit_two"),
    (TAXA, "names() guard re-added", "        if self._names is None and any(t not in self._inventory_names for t in taxa):",
     "        if self._names is None and any(t not in self._inventory_names for t in taxa) and self.taxdump_path.is_file():",
     f"{UNIT}::test_names_refuse_an_absent_tarball_as_nodes_do"),
    (TAXA, "OSError dropped from the archive errors", "    except (tarfile.TarError, EOFError, OSError, zlib.error) as exc:", "    except (tarfile.TarError, EOFError, zlib.error) as exc:",
     f"{CLI_TESTS}::test_an_unreadable_taxdump_tarball_is_exit_two"),
    (TAXA, "row parse errors not mapped", "        except (ValueError, IndexError) as exc:", "        except () as exc:",
     f"{CLI_TESTS}::test_a_member_that_is_not_taxdump_shaped_is_exit_two"),
    (TAXA, "pinned sha256 not checked", "        if pinned is not None and not self._taxdump_verified:", "        if False:",
     f"{CLI_TESTS}::test_a_tarball_that_does_not_match_the_pinned_sha256_is_exit_two"),
    (TAXA, "sha256 re-hashed on every access", "            self._taxdump_verified = True\n", "            self._taxdump_verified = False\n",
     f"{UNIT}::test_a_pinned_sha256_is_checked_once_per_process"),
    (TAXA, "unreadable tarball under a pin is a traceback", "            try:\n                actual = _sha256(path)\n            except OSError as exc:\n                raise TaxonLinksError(f\"{path} cannot be read to check its sha256: {exc}\") from exc\n",
     "            actual = _sha256(path)\n", f"{CLI_TESTS}::test_an_unreadable_tarball_under_a_pinned_digest_is_exit_two"),
    (TAXA, "malformed pin not refused", "            if not SHA256_HEX.fullmatch(expected):", "            if False:",
     f"{CLI_TESTS}::test_a_pinned_digest_is_validated_before_it_is_compared[0000000000000000000000000000000000000000-2]"),
    (TAXA, "pin compared case-sensitively", "            expected = str(pinned).lower()", "            expected = str(pinned)",
     f"{CLI_TESTS}::test_a_pinned_digest_is_validated_before_it_is_compared[UPPER-0]"),
    (TAXA, "absent tarball under a pin falls through", "            if not path.is_file():\n                raise TaxonLinksError(f\"TaxonMech's pinned taxdump {path} is not present\")\n            try:",
     "            try:", f"{CLI_TESTS}::test_an_absent_tarball_under_a_pinned_digest_is_exit_two"),
    (TAXA, "digest verified at construction", "        self.inventory = self._read_inventory()  # taxon -> (rank, parent)\n",
     "        self.inventory = self._read_inventory()  # taxon -> (rank, parent)\n        self.taxdump_path\n",
     f"{UNIT}::test_a_pinned_digest_is_checked_lazily_not_at_construction"),
    (TAXA, "IndexError not mapped at the parse", "        except (ValueError, IndexError) as exc:", "        except ValueError as exc:",
     f"{CLI_TESTS}::test_a_short_row_is_not_taxdump_shaped_either"),
    (TAXA, "archive error re-wrapped by the parse", "        except (ValueError, IndexError) as exc:", "        except (ValueError, IndexError, TaxonLinksError) as exc:",
     f"{CLI_TESTS}::test_a_taxdump_that_is_not_a_tarball_is_exit_two"),
    (TAXA, "trailing newline accepted", "        if not isinstance(value, str) or not CURIE.fullmatch(value):", "        if not isinstance(value, str) or not CURIE.match(value):",
     f"{UNIT}::test_anything_but_a_curie_is_malformed[NCBITaxon:562\\n]"),
    (TAXA, "oversized id accepted", 'CURIE = re.compile(r"NCBITaxon:([1-9][0-9]{0,11})")', 'CURIE = re.compile(r"NCBITaxon:([1-9][0-9]*)")',
     f"{UNIT}::test_anything_but_a_curie_is_malformed[NCBITaxon:" + "1" * 5000 + "]"),
    (TAXA, "missing column is a KeyError", "            if missing:\n", "            if False:\n",
     f"{UNIT}::test_a_malformed_taxonmech_tsv_is_refused_not_a_traceback[curation/seed_scope.tsv-wrong_column\\nNCBITaxon:562\\n-has no identifier column]"),
    (TAXA, "empty scope accepted", "        if not rows and not may_be_empty:", "        if False:",
     f"{UNIT}::test_a_malformed_taxonmech_tsv_is_refused_not_a_traceback[curation/seed_scope.tsv-identifier\\tadded\\treason\\n-lists no taxa]"),
    # The cycle is accepted silently instead of refused (it terminates, so the kill comes from the assertion).
    (TAXA, "merge cycle not refused", "                if taxon in on_path:\n                    raise TaxonLinksError(f\"{MERGED_PATH} maps NCBITaxon:{taxon} in a cycle\")\n",
     "                if taxon in on_path:\n                    break\n",
     f"{UNIT}::test_a_self_mapping_or_cyclic_merge_table_is_refused[old_taxon_id\\tcurrent_taxon_id\\nNCBITaxon:562\\tNCBITaxon:562\\n]"),
    (TAXA, "merge chains not compressed when read", "            for walked in path:\n                merged[walked] = taxon  # the end: not itself merged\n", "",
     f"{UNIT}::test_a_retired_id_merged_twice_reports_the_end_of_the_chain"),
    (TAXA, "merge chains not compressed, so every start re-walks", "            for walked in path:\n                merged[walked] = taxon  # the end: not itself merged\n", "",
     f"{UNIT}::test_a_long_merge_chain_is_read_in_linear_time"),
    (TAXA, "short row placed under the root", "            if None in row or None in row.values():", "            if False:",
     f"{UNIT}::test_a_malformed_taxonmech_tsv_is_refused_not_a_traceback[data/raw/ncbitaxon_taxa.tsv-taxon_id\\tlabel\\trank\\tparent_id\\nNCBITaxon:1\\troot\\tNO_RANK\\t\\nNCBITaxon:1423\\tBacillus subtilis\\n-row 3 has a different number of cells than the header]"),
    (TAXA, "only the first row's shape checked", "        for n, row in enumerate(rows, 2):\n            if None in row", "        for n, row in enumerate(rows[:1], 2):\n            if None in row",
     f"{UNIT}::test_a_malformed_taxonmech_tsv_is_refused_not_a_traceback[data/raw/ncbitaxon_taxa.tsv-taxon_id\\tlabel\\trank\\tparent_id\\nNCBITaxon:1\\troot\\tNO_RANK\\t\\nNCBITaxon:1423\\tBacillus subtilis\\n-row 3 has a different number of cells than the header]"),
    (TAXA, "csv errors not mapped", "            except (csv.Error, UnicodeDecodeError) as exc:", "            except UnicodeDecodeError as exc:",
     f"{UNIT}::test_a_malformed_taxonmech_tsv_is_refused_not_a_traceback[curation/seed_scope.tsv-identifier\\nNCBITaxon:" + "1" * 200_000 + "\\n-cannot be read as a TSV]"),
    (TAXA, "bad bytes in a TSV not mapped", "            except (csv.Error, UnicodeDecodeError) as exc:", "            except csv.Error as exc:",
     f"{UNIT}::test_a_tsv_that_is_not_utf8_is_refused_not_a_traceback"),
    (TAXA, "YAML timestamp ValueError not mapped", "        except (yaml.YAMLError, ValueError) as exc:", "        except yaml.YAMLError as exc:",
     f"{UNIT}::test_a_malformed_taxdump_conf_is_refused_not_a_traceback[snapshot: 2026-13-45\\npath: data/source_snapshots/taxdump.tar.gz\\n-cannot be parsed]"),
    (TAXA, "thirteen digits accepted", 'CURIE = re.compile(r"NCBITaxon:([1-9][0-9]{0,11})")', 'CURIE = re.compile(r"NCBITaxon:([1-9][0-9]{0,12})")',
     f"{UNIT}::test_anything_but_a_curie_is_malformed[NCBITaxon:" + "1" * 13 + "]"),
    (TAXA, "TaxonMech's own CURIEs matched as a prefix", "    if not isinstance(value, str) or not CURIE.fullmatch(value):\n        raise TaxonLinksError(f\"{where}: {value!r} is not an NCBITaxon CURIE\")",
     "    if not isinstance(value, str) or not CURIE.match(value):\n        raise TaxonLinksError(f\"{where}: {value!r} is not an NCBITaxon CURIE\")",
     f"{UNIT}::test_a_malformed_taxonmech_tsv_is_refused_not_a_traceback[curation/seed_scope.tsv-identifier\\nNCBITaxon:562x\\n-row 2: 'NCBITaxon:562x' is not an NCBITaxon CURIE]"),
    (TAXA, "conf path of the wrong type accepted", '        if not isinstance(conf, dict) or not isinstance(conf.get("path"), str):', '        if not isinstance(conf, dict) or conf.get("path") is None:',
     f"{UNIT}::test_a_malformed_taxdump_conf_is_refused_not_a_traceback[path: 5\\n-must be a mapping with a path]"),
    (TAXA, "YAML error not mapped", "        except (yaml.YAMLError, ValueError) as exc:", "        except ValueError as exc:",
     f"{UNIT}::test_a_malformed_taxdump_conf_is_refused_not_a_traceback[path: [\\n-cannot be parsed]"),
    (TAXA, "conf shape not checked", '        if not isinstance(conf, dict) or not isinstance(conf.get("path"), str):', "        if False:",
     f"{UNIT}::test_a_malformed_taxdump_conf_is_refused_not_a_traceback[-must be a mapping with a path]"),
    (TAXA, "farthest scoped ancestor", "        ancestor = next((a for a in chain[1:] if a in self.scope), None)", "        ancestor = next((a for a in reversed(chain[1:]) if a in self.scope), None)",
     f"{UNIT}::test_a_strain_resolves_to_its_nearest_scoped_ancestor_not_the_farthest"),
    (TAXA, "archaea not microbial", 'MICROBIAL_DOMAINS = {"Bacteria", "Archaea"}', 'MICROBIAL_DOMAINS = {"Bacteria"}',
     f"{UNIT}::test_an_unscoped_archaeon_is_unattested_and_a_plant_is_outside_the_domain"),
    (TAXA, "plants microbial", 'NON_MICROBIAL_KINGDOMS = {"Metazoa", "Viridiplantae"}', 'NON_MICROBIAL_KINGDOMS = {"Metazoa"}',
     f"{UNIT}::test_an_unscoped_archaeon_is_unattested_and_a_plant_is_outside_the_domain"),
    (CLI, "negative sample accepted", "    if args.sample is not None and args.sample < 1:\n", "    if False:\n",
     f"{CLI_TESTS}::test_a_sample_below_one_is_a_usage_error"),
    (TAXA, "synonyms named", 'lambda f: (int(f[0]), f[1]) if f[3] == "scientific name" else None)', 'lambda f: (int(f[0]), f[1]))',
     f"{UNIT}::test_a_synonym_row_never_names_a_taxon"),
    (CLI, "strict blocks every verdict but record", 'BLOCKING = {Verdict.RETIRED.value, Verdict.ABSENT.value, Verdict.MALFORMED.value}',
     'BLOCKING = {v.value for v in Verdict} - {Verdict.RECORD.value}', f"{CLI_TESTS}::test_strict_passes_on_every_non_blocking_verdict"),
    (TAXA, "unplaced only at species rank", '        if domain == "other":', '        if domain == "other" and rank == "species":',
     f"{UNIT}::test_a_strain_under_a_metagenome_is_unplaced_too"),
    (TAXA, "resolvable tie not broken on the id", "for t, n in sorted(self.resolvable.items(), key=lambda kv: (-kv[1], kv[0]))]",
     "for t, n in sorted(self.resolvable.items(), key=lambda kv: -kv[1])]", f"{UNIT}::test_findings_are_sorted_and_resolvable_is_most_cited_first"),
    (TAXA, "unattested tie not broken on the id", "for t, n in sorted(self.unattested.items(), key=lambda kv: (-kv[1], kv[0]))]",
     "for t, n in sorted(self.unattested.items(), key=lambda kv: -kv[1])]", f"{UNIT}::test_unattested_taxa_are_listed_most_cited_first"),
    (TAXA, "merged.dmp fallback restored", '            self._nodes = self._dmp_table("nodes.dmp", lambda f: (int(f[0]), (f[2], int(f[1]))))\n',
     '            self._nodes = self._dmp_table("nodes.dmp", lambda f: (int(f[0]), (f[2], int(f[1]))))\n            if not self.merged:\n                self.merged = {int(o): int(n) for o, n in _dmp_rows(self.taxdump_path, "merged.dmp")}\n',
     f"{UNIT}::test_the_merge_table_is_the_only_merge_source"),
    (CLI, "--sample dropped", "index, sample=args.sample)", "index)", f"{CLI_TESTS}::test_sample_is_honoured_and_recorded"),
    (CLI, "missing TaxonMech file not exit 2", "    except (MechRootError, TaxonLinksError) as exc:\n        print(str(exc), file=sys.stderr)\n        return 2\n\n    keys",
     "    except (MechRootError, TaxonLinksError) as exc:\n        print(str(exc), file=sys.stderr)\n        return 0\n\n    keys",
     f"{CLI_TESTS}::test_a_missing_taxonmech_file_is_exit_two"),
]


TIMEOUT = 30  # seconds; a normal case takes about two, so a mutant that hangs is a kill, and the limit bounds its memory


def pytest(selector: str) -> int:
    try:
        return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", selector],
                              cwd=ROOT, capture_output=True, text=True, check=False, timeout=TIMEOUT).returncode
    except subprocess.TimeoutExpired:
        return 1  # the named test did not pass within the limit


def main() -> int:
    for test_file in TESTS:
        if pytest(test_file) != 0:
            print(f"the unmutated {test_file} fails")
            return 1
    survived = 0
    originals = {path: (ROOT / path).read_text(encoding="utf-8") for path in (TAXA, CLI)}
    try:
        for path, name, before, after, test in MUTANTS:
            original = originals[path]
            if original.count(before) != 1:
                print(f"{name}: anchor {before!r} occurs {original.count(before)} times")
                return 1
            mutated = original.replace(before, after)
            try:
                ast.parse(mutated)
            except SyntaxError as exc:
                print(f"{name}: the mutant does not parse ({exc.msg})")
                return 1
            (ROOT / path).write_text(mutated, encoding="utf-8")
            try:
                rc = pytest(test)
            finally:
                (ROOT / path).write_text(original, encoding="utf-8")
            if rc not in (0, 1):
                print(f"{name}: pytest exited {rc} for {test}, which is neither a pass nor a failure")
                return 1
            killed = rc == 1
            survived += not killed
            print(f"{'KILLED  ' if killed else 'SURVIVED'} {name} ({test.split('::')[1]})")
    finally:
        for path, original in originals.items():
            (ROOT / path).write_text(original, encoding="utf-8")
    print(f"{len(MUTANTS) - survived}/{len(MUTANTS)} killed")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
