"""Read-only deterministic acceptance; invoke only after root confirms generation.

Author of the pure helper; this is not independent review or canonical promotion.
Only the exclusive --output child below this script's directory is written.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from collections import Counter

HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), f"Symlink input: {path}")
    s = path.stat()
    require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1, f"Nonregular/aliased input: {path}")
    return path


def filehash(path):
    h = hashlib.sha256()
    with regular(path).open('rb') as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def digest_or_none(path):
    return filehash(path) if path.exists() else None


def load(path):
    return json.loads(regular(path).read_bytes())


def emit(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def git(root, *argv):
    return subprocess.check_output(['git', '-C', str(root), *argv])


def revision(root):
    return git(root, 'rev-parse', 'HEAD').decode().strip()


def module(name, path, captured_source=None):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    # Compile the inspected bytes; do not accept a timestamp-valid old pyc.
    source = regular(path).read_bytes() if captured_source is None else captured_source
    exec(compile(source, str(path), 'exec', dont_inherit=True), result.__dict__)
    return result


def checked_inventory(inventory):
    require(isinstance(inventory, dict), 'Expected path-keyed input inventory')
    for raw, entry in inventory.items():
        p = Path(raw)
        require(p.is_absolute(), f'Inventory path is not absolute: {raw}')
        require(filehash(p) == entry['sha256'] and p.stat().st_size == entry['bytes'],
                f'Inventory bytes changed: {p}')


def table(path, *, sssom):
    """Only SSSOM has leading metadata; plain TSV hash-prefixed values survive."""
    text = regular(path).read_text(encoding='utf-8')
    stream = io.StringIO(text, newline='')
    prelude = []
    if sssom:
        while True:
            position = stream.tell()
            line = stream.readline()
            if not line.startswith('#'):
                stream.seek(position)
                break
            prelude.append(line.rstrip('\n'))
    reader = csv.DictReader(stream, delimiter='\t')
    rows = list(reader)
    require(reader.fieldnames and len(reader.fieldnames) == len(set(reader.fieldnames)),
            f'Missing/duplicate columns: {path}')
    require(all(None not in row and None not in row.values() for row in rows), f'Malformed table: {path}')
    return prelude, reader.fieldnames, rows


def token_keys(row):
    return {x.strip().casefold() for x in row['other'].split('|') if x.strip()}


def row_index(rows):
    result = {}
    for row in rows:
        key = (row['subject_id'], row['object_id'])
        require(key not in result, f'Duplicate subject/object row: {key}')
        result[key] = row
    return result


def compare_rows(old, new, pairs, label_changes, current_unfiltered):
    before, after = row_index(old), row_index(new)
    added, removed = sorted(after.keys()-before.keys()), sorted(before.keys()-after.keys())
    changes = []
    for key in sorted(before.keys() & after.keys()):
        a, b = before[key], after[key]
        fields = {k: {'before': a[k], 'after': b[k]} for k in a if a[k] != b[k]}
        if not fields:
            continue
        lost, gained = sorted(token_keys(a)-token_keys(b)), sorted(token_keys(b)-token_keys(a))
        classes = []
        if lost:
            classes.append('owned-name suppression' if all((key[0], x) in pairs for x in lost)
                           else 'other-token removal requiring explanation')
        label_changed = ('object_label' in fields and key[1] in label_changes
                         and b['object_label'] == label_changes[key[1]]['after_returned'])
        label_gains = ([token for token in gained if token == a['object_label'].strip().casefold()]
                       if label_changed else [])
        cap_gains = [token for token in gained if token not in label_gains
                    and token not in token_keys(current_unfiltered[key])]
        if label_gains:
            classes.append('stored target label exposed by observed canonical-label resolution')
        if cap_gains:
            classes.append('additional aliases exposed before cap; diagnostic only')
        if set(gained)-set(label_gains)-set(cap_gains):
            classes.append('other-token addition requiring explanation')
        if label_changed:
            detail = label_changes[key[1]]
            classes.append('observed canonical-label resolution from stored-label fallback'
                           if detail['before_returned'] is None else 'observed canonical-label resolution change')
        if 'other' in fields and not lost and not gained:
            classes.append('other spelling/order serialization')
        if 'validation_method' in fields:
            classes.append('prior-stamp replay from recorded inputs; exact native replay verified')
        other_fields = sorted(set(fields)-{'other', 'validation_method'}
                              - ({'object_label'} if label_changed else set()))
        if other_fields:
            classes.append('other column changes requiring explanation: '+','.join(other_fields))
        changes.append({'subject_id': key[0], 'object_id': key[1], 'classes': classes,
                        'columns': fields, 'lost_token_keys': lost, 'gained_token_keys': gained})
    return {'old_rows': len(old), 'new_rows': len(new), 'added': added, 'removed': removed,
            'changed_rows': len(changes), 'unchanged_rows': len(before.keys() & after.keys())-len(changes),
            'class_counts': dict(Counter(c for x in changes for c in x['classes'])), 'changes': changes}


def run(args, out):
    import yaml
    mim, claw, kg = (p.resolve() for p in (args.mim_root, args.claw_root, args.kg_root))
    bundle, old_bundle = args.bundle.resolve(), args.old_bundle.resolve()
    candidate = bundle/'candidate.sssom.tsv'
    sidecar = bundle/'suppressed_aliases.tsv'
    manifest_path = bundle/'candidate.sssom.tsv.manifest.json'
    artifacts = (candidate, sidecar, manifest_path)
    require(not any(p.is_relative_to(out) for p in (*artifacts, old_bundle)), 'Output aliases input directory')
    require(re.fullmatch(r'[0-9a-f]{40}', args.producer_revision), 'Use the full immutable producer SHA')
    require(not args.producer_revision.startswith('e78e220'),
            'Known superseded producer e78e220: issues #706/#707 require corrected generation')
    require(revision(mim) == args.mim_revision, 'MIM revision changed')
    require(revision(claw) == args.producer_revision, 'Producer revision changed')
    require(not git(mim, 'status', '--porcelain=v1', '-z', '--untracked-files=all'), 'MIM checkout is not clean')
    require(not git(claw, 'status', '--porcelain=v1', '-z', '--untracked-files=all'), 'Producer checkout is not clean')
    tracked_yaml = {p.decode() for p in git(mim, 'ls-tree', '-r', '-z', '--name-only', args.mim_revision,
                                          '--', 'data/ingredients').split(b'\0') if p.endswith(b'.yaml')}
    actual_yaml = {str(p.relative_to(mim)) for p in (mim/'data/ingredients').rglob('*.yaml')}
    require(actual_yaml == tracked_yaml, 'Tracked/actual individual YAML path set differs, including ignored files')
    require(not git(mim, 'diff', '--name-only', '-z', args.mim_revision, '--', 'data/ingredients',
                    'data/curated', 'mappings/ingredient_mappings.sssom.tsv',
                    'mappings/other_cross_record_baseline.tsv'), 'Maintained MIM inputs differ from baseline')
    data_inputs = [mim/p for p in sorted(actual_yaml)] + [
        mim/'data/curated/mapped_ingredients.yaml', mim/'data/curated/unmapped_ingredients.yaml',
        mim/'mappings/ingredient_mappings.sssom.tsv', mim/'mappings/other_cross_record_baseline.tsv']
    tree = git(mim, 'ls-tree', '-r', '-z', args.mim_revision, '--', 'data/ingredients',
               'data/curated', 'mappings/ingredient_mappings.sssom.tsv',
               'mappings/other_cross_record_baseline.tsv')
    blobs = {entry.split(b'\t', 1)[1].decode(): entry.split(b'\t', 1)[0].split()[2].decode()
             for entry in tree.split(b'\0') if entry}
    object_format = git(mim, 'rev-parse', '--show-object-format').decode().strip()
    for path in data_inputs:
        content = regular(path).read_bytes()
        h = hashlib.new(object_format)
        h.update(b'blob '+str(len(content)).encode()+b'\0'+content)
        require(blobs[str(path.relative_to(mim))] == h.hexdigest(), f'Baseline blob differs: {path}')
    data_before = {str(p): filehash(p) for p in data_inputs}
    emit(out/'maintained-mim-before.json', data_before)

    receipt = load(bundle/'generation-receipt.json')
    before, after = load(bundle/'inputs-before.json'), load(bundle/'inputs-after.json')
    require(before == after, 'Generation before/after input inventories differ')
    checked_inventory(before)
    require(receipt['input_bytes_unchanged'] is True and receipt['scientific_approval_added'] is False,
            'Generation receipt does not declare immutable inputs/no approval')
    require(receipt.get('supervisor_binding') is None, 'Unexpected invented supervisor binding')
    for path, field in zip(artifacts, ('candidate_sha256', 'sidecar_sha256', 'native_generation_manifest_sha256')):
        require(filehash(path) == receipt[field], f'Generation receipt artifact mismatch: {path}')
    require(filehash(bundle/'inputs-before.json') == receipt['input_manifest_sha256'], 'Before-inventory receipt mismatch')
    require(filehash(args.generation_harness.resolve()) == receipt['harness_sha256'], 'Generation harness changed')
    require(receipt['producer_revision'] == args.producer_revision, 'Receipt producer revision mismatch')
    manifest = load(manifest_path)
    require(manifest['schema_version'] == 1 and manifest['external_sssom_validation'] == 'passed',
            'Schema/external generation validation not verified')
    require(manifest['source_revisions'] == {'claw': args.producer_revision,
                                           'mim': args.mim_revision, 'kg_microbe': revision(kg)},
            'Generation repository revisions differ from current inputs')
    context = load(bundle/'repository-context.json')
    for key, root in [('mim', mim), ('claw', claw), ('kg_microbe', kg)]:
        require(Path(context[key]['path']).resolve() == root and context[key]['revision'] == revision(root),
                f'Repository receipt mismatch: {key}')
    require(not context['claw']['status'] and not context['mim']['status'], 'Generation began with a dirty owned checkout')
    for path, role in [(candidate, 'sssom'), (sidecar, 'suppressed_aliases')]:
        matches = [x for x in manifest['artifacts'] if x['role'] == role]
        require(len(matches) == 1 and Path(matches[0]['path']) == path and matches[0]['sha256'] == filehash(path),
                f'Native artifact manifest mismatch: {role}')
    require(len(manifest['artifacts']) == 2, 'Unexpected native artifact role')

    sys.path[:0] = [str(claw/'src'), str(claw/'scripts'), str(mim/'src')]
    entry_path = claw/'scripts/build_mim_ingredient_sssom.py'
    entry_source = regular(entry_path).read_bytes()
    entry_sha = sha(entry_source)
    declared_sources = {Path(x['path']): x['sha256'] for x in manifest['source_inputs']}
    require(len(declared_sources) == len(manifest['source_inputs']), 'Duplicate source declarations')
    require(entry_sha == receipt['executed_entry_source_sha256'] == receipt['producer_sha256']
            == before[str(entry_path)]['sha256'] == declared_sources[entry_path],
            'Trusted entrypoint bytes differ from the executed-source receipts')
    # Check declared dependency bytes before allowing their private compilation.
    # The builder independently enumerates/binds the complete path set at import.
    for source_path, source_sha in declared_sources.items():
        if source_path.is_relative_to(claw):
            require(digest_or_none(source_path) == source_sha,
                    f'Declared producer input changed before import: {source_path}')
    builder = module('accepted_native_builder', entry_path, entry_source)
    require(builder._IMPORTED_PRODUCER_BYTES[entry_path] == entry_source,
            'Builder captured a different entrypoint')
    imported_producers = {str(path): sha(content)
                          for path, content in builder._IMPORTED_PRODUCER_BYTES.items()}
    require(imported_producers == manifest['producer_import_snapshot'],
            'Executed producer graph differs from the generation import snapshot')
    require(set(imported_producers) == {str(path) for path in builder._producer_paths()},
            'Imported producer graph path inventory is incomplete')
    require(all(declared_sources[Path(path)] == digest for path, digest in imported_producers.items()),
            'Import snapshot differs from generation source inventory')
    builder._check_producer_bindings()
    policy = builder._POLICY_PRODUCER
    artifact = builder._ARTIFACT_PRODUCER
    require(policy is builder._PRODUCER_MODULES['kg_microbe_utils.owned_name_policy']
            and artifact is builder._PRODUCER_MODULES['kg_microbe_utils.sssom_artifacts'],
            'Builder private module aliases are not the captured producer graph')
    require(builder.build_owner_index is policy.build_owner_index
            and builder.filter_owned_aliases is policy.filter_owned_aliases
            and builder.render_suppressed_aliases is policy.render_suppressed_aliases,
            'Builder policy function aliases differ from captured private functions')
    require(builder._row_from_yaml.__globals__ is builder.__dict__
            and builder._row_from_yaml.__globals__['filter_owned_aliases'] is policy.filter_owned_aliases,
            'Row builder does not use the inspected policy binding')
    build_owner_index = policy.build_owner_index
    render_suppressed_aliases = policy.render_suppressed_aliases
    _validate_pair = artifact._validate_pair
    native_path = mim/'scripts/validate_sssom_invariants.py'
    native_source = regular(native_path).read_bytes()
    require(git(mim, 'show', args.mim_revision+':scripts/validate_sssom_invariants.py') == native_source,
            'Native validator differs from the immutable MIM baseline')
    native = module('accepted_native_invariants', native_path, native_source)
    require(manifest['policy_version'] == policy.POLICY_VERSION, 'Policy version mismatch')
    require(builder.MIM_ROOT.resolve() == mim and builder.KGM_ROOT.resolve() == kg,
            'Runtime environment roots do not match the accepted generation')
    _validate_pair(candidate.read_bytes(), sidecar.read_bytes())
    mapped = tuple(sorted((mim/'data/ingredients/mapped').glob('*.yaml')))
    require(manifest['mapped_record_paths'] == [str(p) for p in mapped], 'Native mapped path set mismatch')
    items = manifest['source_inputs']
    inputs = {Path(x['path']): x['sha256'] for x in items}
    require(len(inputs) == len(items) and all(p.is_absolute() for p in inputs), 'Duplicate/relative manifest inputs')
    stamps = [Path(x) for x in manifest['prior_stamp_sources']]
    expected_inputs = set(mapped) | set(builder._producer_paths()) | set(stamps) | {
        builder.RESIDUAL_JSON, builder.KGM_UNIFIED_TSV, builder.MIM_PUBLISHED_SSSOM}
    require(set(inputs) == expected_inputs, 'Native source inventory is incomplete or contains extra paths')
    require(str(receipt['prior_stamps']) in manifest['prior_stamp_sources'], 'Harness/native prior-stamp inputs differ')
    require(filehash(Path(receipt['prior_stamps'])) == receipt['prior_sha256'], 'Prior-stamp source changed')
    journal = load(args.journal)
    require(journal['status'] == 'complete' and Path(journal['root']) == bundle, 'Incomplete/wrong-root native journal')
    changed, created = set(journal['changed']), set(journal['created'])
    require(not (changed & created) and changed | created <= {str(p) for p in artifacts}, 'Native journal path mismatch')
    require(set(journal['previous']) == changed and bool(changed | created), 'Native journal beforeimage mismatch')
    source_bytes = {}
    for path, expected_sha in inputs.items():
        if path == candidate and path in stamps:
            if str(path) in journal['previous']:
                content = journal['previous'][str(path)].encode('utf-8')
            elif str(path) in created:
                content = None
            else:
                content = path.read_bytes()
            require((sha(content) if content is not None else None) == expected_sha,
                    'Working-copy stamp preimage is not bound to the journal')
        else:
            require(digest_or_none(path) == expected_sha, f'Native source hash mismatch: {path}')
            content = path.read_bytes() if expected_sha is not None else None
        source_bytes[path] = content
    require(inputs[claw/'scripts/build_mim_ingredient_sssom.py'] == receipt['producer_sha256'],
            'Builder source hash mismatch')
    comparison = load(bundle/'comparison-inputs.json')
    checked_inventory(comparison)
    require(not (set(comparison) & {str(p) for p in mapped}), 'Comparison inputs became source owners')

    label_files = sorted(bundle.glob('label-input-*.json'))
    require({p.name for p in label_files} == set(receipt['label_maps']), 'Observed label-capture path set differs')
    labels = {}
    for path in label_files:
        require(filehash(path) == receipt['label_maps'][path.name], f'Observed label capture changed: {path}')
        labels.update(load(path)['labels'])
    require(labels == manifest['canonical_label_resolution'], 'Observed/native label maps differ')
    records = {path: yaml.safe_load(source_bytes[path]) for path in mapped}
    native.INGREDIENTS_DIR = mim/'data/ingredients/mapped'
    native.KGM_TRANSFORMS_DIR = kg/'data/transformed/ontologies'
    native._subject_to_path.cache_clear()
    native._preferred_term_owners.cache_clear()
    native._other_baseline = lambda: frozenset()  # Deliberately in-memory only.
    subject_paths = native._subject_to_path()
    owners = native._preferred_term_owners()
    require(build_owner_index({builder._mim_curie(p.name): d for p, d in records.items()}) == owners,
            'Helper ownership diverges from native Rule K')
    residual_bytes = source_bytes[builder.RESIDUAL_JSON]
    residual = ({x['source_file']: x for x in json.loads(residual_bytes)['decisions']}
                if residual_bytes is not None else {})
    kg_sources = builder.load_kgm_source_index(builder.KGM_UNIFIED_TSV) if inputs[builder.KGM_UNIFIED_TSV] else {}
    kg_labels = builder.load_kgm_labels(builder.KGM_UNIFIED_TSV) if inputs[builder.KGM_UNIFIED_TSV] else {}
    emitted, events = [], []
    for path, data in records.items():
        emitted.extend(builder._row_from_yaml(path, residual, kg_sources, kg_labels, labels,
                                              record=data, owners=owners, suppressions=events))
    final = list({(r['subject_id'], r['object_id']): r for r in emitted}.values())
    # An explicitly in-memory counterfactual distinguishes candidate encounters
    # from tokens the same formatter would otherwise actually publish. This is
    # not the old producer and is never written as a candidate artifact.
    original_filter = builder.filter_owned_aliases
    original_private_filter = policy.filter_owned_aliases
    require(original_filter is original_private_filter, 'Counterfactual policy binding changed')
    counterfactual_calls = 0
    counterfactual_encounters = set()

    def observe_unfiltered(subject, candidates, index):
        nonlocal counterfactual_calls
        counterfactual_calls += 1
        observed = tuple(candidates)
        for candidate_alias in observed:
            key = candidate_alias.text.strip().casefold()
            holders = index.get(key)
            if key and holders and subject.strip() not in holders:
                counterfactual_encounters.add((subject.strip(), key))
        return observed, ()

    # The native row function currently calls the entry-module alias. Set both
    # aliases explicitly, prove the actual call site and restore in all cases.
    builder.filter_owned_aliases = observe_unfiltered
    policy.filter_owned_aliases = observe_unfiltered
    require(builder._row_from_yaml.__globals__['filter_owned_aliases'] is observe_unfiltered,
            'Counterfactual did not patch the bound row-policy call')
    try:
        unfiltered_rows = []
        for path, data in records.items():
            unfiltered_rows.extend(builder._row_from_yaml(path, residual, kg_sources, kg_labels, labels,
                                                          record=data, owners=owners, suppressions=None))
    finally:
        builder.filter_owned_aliases = original_filter
        policy.filter_owned_aliases = original_private_filter
    require(builder.filter_owned_aliases is policy.filter_owned_aliases is original_filter,
            'Counterfactual policy bindings were not restored')
    require(counterfactual_calls > 0, 'Counterfactual policy call was never exercised')
    require(counterfactual_encounters == {(event.subject_id, event.token.casefold()) for event in events},
            'Counterfactual did not encounter the same real policy decisions')
    builder._check_producer_bindings()
    current_unfiltered = row_index(list({(r['subject_id'], r['object_id']): r
                                        for r in unfiltered_rows}.values()))
    prior = {}
    for path in stamps:
        content = source_bytes[path]
        if content is not None:
            # Replay exact frozen beforeimages; never reread an overwritten working copy.
            temp = out/f'prior-{len(prior)}-{sha(str(path).encode())[:12]}.sssom.tsv'
            temp.write_bytes(content)
            prior.update(builder._load_existing_validation_method(temp))
            temp.unlink()
    stamp_outcomes = builder.apply_replayed_stamps(final, prior)
    expected_tsv = (builder.HEADER_YAML.format(version=builder._mapping_set_version(final))
                    + '\t'.join(builder.COLUMNS)+'\n'
                    + ''.join('\t'.join(str(r.get(c, '')) for c in builder.COLUMNS)+'\n' for r in final)).encode()
    require(expected_tsv == candidate.read_bytes(), 'Exact offline native candidate replay differs')
    require(render_suppressed_aliases(events) == sidecar.read_bytes(), 'Exact sidecar event replay differs')
    prelude, columns, rows = table(candidate, sssom=True)
    _, side_columns, suppressed = table(sidecar, sssom=False)
    require(len(rows) == manifest['emitted_rows'], 'Manifest emitted-row count mismatch')
    metadata = yaml.safe_load('\n'.join(line[2:] if line.startswith('# ') else line[1:] for line in prelude))
    dates = [r['mapping_date'] for r in rows if r['mapping_date']]
    require(dates and all(re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', d) for d in dates), 'Invalid row date shape')
    newest = max(dt.date.fromisoformat(d) for d in dates).isoformat()
    require(str(metadata['mapping_date']) == newest and str(metadata['mapping_set_version']) == newest,
            'Header dates do not match newest row provenance date')
    published = {}
    for row in rows:
        published.setdefault(row['subject_id'], set()).update(token_keys(row))
    pairs, proofs = set(), []
    for row in suppressed:
        pair = row['subject_id'], row['token_key']
        require(pair not in pairs, f'Duplicate suppression: {pair}')
        pairs.add(pair)
        subject_record = records[subject_paths[pair[0]]]
        source_rejected = {token.strip().casefold()
                           for synonym in subject_record.get('synonyms') or []
                           if isinstance(synonym, dict)
                           and str(synonym.get('synonym_type') or '').strip().upper() == 'REJECTED_LABEL'
                           for token in str(synonym.get('synonym_text') or '').split('|')
                           if token.strip()}
        require(pair[1] not in source_rejected,
                f'SUPPRESS incorrectly credits a prior source-rejected token (#707): {pair}')
        expected_owners = owners.get(pair[1], frozenset())
        require(expected_owners and pair[0] not in expected_owners
                and json.loads(row['owner_subject_ids']) == sorted(expected_owners), f'Wrong credited owner: {pair}')
        require(pair[0] in published and pair[1] not in published[pair[0]], f'Suppressed token still published: {pair}')
        owner_proofs = [{'subject_id': owner, 'path': str(subject_paths[owner]),
                         'sha256': inputs[subject_paths[owner]]} for owner in sorted(expected_owners)]
        refs = []
        for ref in json.loads(row['source_refs']):
            source, sep, selector = ref.rpartition('#')
            path = Path(source)
            require(sep and path in inputs and inputs[path] is not None, f'Unbound suppression source: {ref}')
            resolved_selector = selector
            if path in records:
                data = records[path]
                match = re.fullmatch(r'synonyms\[([0-9]+)\]', selector)
                if match:
                    synonym = data['synonyms'][int(match.group(1))]
                    require(str(synonym.get('synonym_type', '')).strip().upper() != 'REJECTED_LABEL',
                            f'Suppression falsely attributed to a rejected alias: {ref}')
                    names = [synonym['synonym_text']]
                elif selector == 'ontology_mapping.ontology_label':
                    names = [data['ontology_mapping']['ontology_label']]
                elif selector == 'chemical_properties.cas_rn-or-cross_references':
                    # Historical broad CAS selector: record its actual supplied-form/chemistry field.
                    selected = next(((i, x['cas_rn']) for i, x in enumerate(data.get('supplied_form') or [])
                                     if (x or {}).get('cas_rn') and str(x['cas_rn']).strip()), None)
                    if selected:
                        resolved_selector = f'supplied_form[{selected[0]}].cas_rn'
                        names = ['CAS:'+str(selected[1]).strip()]
                    else:
                        resolved_selector = 'chemical_properties.cas_rn'
                        names = ['CAS:'+str(data['chemical_properties']['cas_rn']).strip()]
                elif selector.startswith('supplied_form[') or selector == 'chemical_properties.cas_rn':
                    match = re.fullmatch(r'supplied_form\[([0-9]+)\]\.cas_rn', selector)
                    number = (data['supplied_form'][int(match.group(1))]['cas_rn'] if match
                              else data['chemical_properties']['cas_rn'])
                    names = ['CAS:'+str(number).strip()]
                else:
                    raise ValueError(f'Unsupported source selector needs inspection: {ref}')
            elif path == builder.KGM_UNIFIED_TSV and selector.startswith('object_id='):
                name, synonyms = kg_labels[selector.split('=', 1)[1]]
                names = [name, *synonyms]
            else:
                raise ValueError(f'Unsupported source reference needs inspection: {ref}')
            require(pair[1] in {part.strip().casefold() for name in names for part in name.split('|')
                               if part.strip()}, f'Source does not contain the suppressed token: {ref}')
            refs.append({'reference': ref, 'sha256': inputs[path], 'selector': selector,
                         'resolved_source_field': resolved_selector})
        require(set(json.loads(row['evidence_refs'])) <= set(manifest['policy_evidence']), 'Unbound policy evidence')
        proofs.append({'subject_id': pair[0], 'token_key': pair[1], 'credited_owner_inputs': owner_proofs,
                       'source_inputs': refs})
    emit(out/'suppression-proofs.json', proofs)
    require(not list(native.evaluate_rule_k(rows)), 'Native Rule K rejects the empty-baseline candidate')
    b4 = sorted({r['object_id'].split(':')[0] for r in rows} & native.B4_PREFIXES)
    transforms = [native.KGM_TRANSFORMS_DIR/f'{prefix.lower()}_nodes.tsv' for prefix in b4]
    available_transforms = [p for p in transforms if p.is_file()]
    missing_transforms = [p for p in transforms if not p.is_file()]
    transforms_before = {str(p): filehash(p) for p in available_transforms}
    missing_prefixes = [p.name.removesuffix('_nodes.tsv').upper() for p in missing_transforms]
    b4_coverage = {
        'contract': 'Unmodified native warn-and-skip for missing transforms; no synthetic transforms',
        'full_prefix_coverage': not missing_prefixes,
        'in_use_prefixes': b4,
        'available_transform_sha256': transforms_before,
        'missing_transforms': [{'prefix': prefix, 'expected_path': str(path),
                                'affected_rows': [{'subject_id': row['subject_id'],
                                                   'object_id': row['object_id'],
                                                   'object_label': row['object_label']}
                                                  for row in rows if row['object_id'].split(':')[0] == prefix]}
                               for prefix, path in zip(missing_prefixes, missing_transforms, strict=True)],
        'captured_label_comparison': 'Separate observed-input supplement; not replacement ontology transforms',
    }
    for item in b4_coverage['missing_transforms']:
        item['affected_row_count'] = len(item['affected_rows'])
    emit(out/'b4-coverage.json', b4_coverage)
    with (out/'native-invariants.log').open('x') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        native_code = native.main([str(mim/'scripts/validate_sssom_invariants.py'), str(candidate),
                                   '--reject-tsv', str(out/'native-rejects.tsv')])
    require(native_code == 0, 'Native invariants failed; inspect native-invariants.log and native-rejects.tsv')
    command = ['sssom', 'validate', '-V', 'JsonSchema', '-V', 'PrefixMapCompleteness',
               '-V', 'StrictCurieFormat', str(candidate)]
    proc = subprocess.run(command, capture_output=True)
    (out/'sssom-schema.log').write_bytes(proc.stdout+proc.stderr)
    require(proc.returncode == 0, 'Independent schema validation failed')

    old_receipt = load(old_bundle/'generation-receipt.json')
    old_candidate = old_bundle/'candidate.sssom.tsv'
    require(filehash(old_candidate) == old_receipt['candidate_sha256'], 'Archived Step 4 candidate changed')
    old_before, old_after = load(old_bundle/'inputs-before.json'), load(old_bundle/'inputs-after.json')
    require(old_before == old_after, 'Archived Step 4 generation input preservation was not established')
    require(filehash(old_bundle/'inputs-before.json') == old_receipt['input_manifest_sha256'], 'Archived input receipt mismatch')
    mapped_delta = [{'path': str(p), 'old': old_before.get(str(p)), 'new_sha256': inputs[p]}
                    for p in mapped if old_before.get(str(p), {}).get('sha256') != inputs[p]]
    require(not mapped_delta, 'Source owners changed since the raw Step 4 candidate; no Step 5 YAML correction is authorized here')
    old_prelude, old_columns, old_rows = table(old_candidate, sssom=True)
    require(old_columns == columns, 'Diagnostic candidate column contract changed')
    old_labels = {}
    for name, expected_sha in sorted(old_receipt['label_maps'].items()):
        path = old_bundle/name
        require(filehash(path) == expected_sha, f'Archived label capture changed: {path}')
        old_labels.update(load(path)['labels'])
    label_changes = {identifier: {'before_returned': old_labels.get(identifier),
                                  'after_returned': labels.get(identifier)}
                     for identifier in sorted(set(old_labels) | set(labels))
                     if old_labels.get(identifier) != labels.get(identifier)}
    for key, row in row_index(rows).items():
        if key[1] in label_changes and label_changes[key[1]]['before_returned'] is None:
            old_row = row_index(old_rows).get(key)
            if old_row:
                data = records[subject_paths[key[0]]]
                require(old_row['object_label'] == data['ontology_mapping']['ontology_label'],
                        f'Old label fallback needs explanation: {key}')
    delta = compare_rows(old_rows, rows, pairs, label_changes, current_unfiltered)
    delta['observed_label_resolution_changes'] = label_changes
    old_published_pairs = {(r['subject_id'], token) for r in old_rows for token in token_keys(r)}
    unfiltered_pairs = {(r['subject_id'], token) for r in current_unfiltered.values() for token in token_keys(r)}
    prior_row_index = row_index(old_rows)
    classes = []
    for subject, token in sorted(pairs):
        prior_rows = [row for (s, _), row in prior_row_index.items() if s == subject]
        old_drop_names = {row[field].strip().casefold() for row in prior_rows
                          for field in ('subject_label', 'object_label')}
        classes.append({'subject_id': subject, 'token_key': token,
                        'published_in_step4_raw_candidate': (subject, token) in old_published_pairs,
                        'published_in_current_unfiltered_counterfactual': (subject, token) in unfiltered_pairs,
                        'prior_formatter_dedicated_label_exclusion': token in old_drop_names,
                        'classification': ('previously published token removed' if (subject, token) in old_published_pairs
                                           else 'candidate encounter already excluded as a dedicated label'
                                           if token in old_drop_names else 'candidate encounter absent from prior published other')})
    emit(out/'policy-encounter-classification.json', classes)
    delta['policy_encounter_classes'] = dict(Counter(x['classification'] for x in classes))
    delta['unique_suppression_pairs'] = len(pairs)
    delta['previously_published_pairs_removed'] = len(pairs & old_published_pairs)
    delta['current_counterfactual_published_pairs_removed'] = len(pairs & unfiltered_pairs)
    delta['scope_warning'] = ('These are diagnostic candidate encounters, not canonical removals. '
                              'Do not copy this sidecar into the bounded MIM promotion.')
    delta['metadata_before'] = old_prelude
    delta['metadata_after'] = prelude
    delta['old_candidate_sha256'] = filehash(old_candidate)
    delta['new_candidate_sha256'] = filehash(candidate)
    delta['note'] = ('Full diagnostic comparison, not canonical promotion. Source owners are unchanged; '
                     'native replay uses observed label maps and recorded prior stamps. Counts are measured, not pinned.')
    emit(out/'step4-candidate-delta.json', delta)
    require(not delta['added'] and not delta['removed'], 'Unexpected row-set changes need review')
    require(not any('requiring explanation' in c for x in delta['changes'] for c in x['classes']),
            'Unexplained changed row class; inspect delta before accepting')
    builder._check_producer_bindings()
    checked_inventory(before)
    checked_inventory(comparison)
    require({str(p): filehash(p) for p in data_inputs} == data_before, 'Maintained MIM data changed during acceptance')
    require({str(p): filehash(p) for p in available_transforms} == transforms_before, 'Native B4 inputs changed during acceptance')
    require(all(not p.is_file() for p in missing_transforms), 'Native B4 availability changed during acceptance')
    for path, digest in inputs.items():
        if path != candidate:
            require(digest_or_none(path) == digest, f'Native generation input changed during acceptance: {path}')
    require(not git(claw, 'status', '--porcelain=v1', '-z', '--untracked-files=all'), 'Producer became dirty')
    require(not git(mim, 'status', '--porcelain=v1', '-z', '--untracked-files=all'), 'MIM became dirty')
    result = {'status': 'PASS_WITH_LIMITATIONS' if missing_prefixes else 'PASS',
              'limitations': ([{'rule': 'B4', 'kind': 'missing ontology transforms',
                               'prefixes': missing_prefixes,
                               'affected_row_count': sum(x['affected_row_count'] for x in b4_coverage['missing_transforms'])}]
                              if missing_prefixes else []),
              'b4_coverage': b4_coverage, 'classification': 'Deterministic author acceptance; not independent scientific review',
              'canonical_promotion': False, 'scientific_approval_added': False,
              'revisions': manifest['source_revisions'], 'artifacts': {str(p): filehash(p) for p in artifacts},
              'generation_receipt_sha256': filehash(bundle/'generation-receipt.json'),
              'journal': {'path': str(args.journal.resolve()), 'sha256': filehash(args.journal)},
              'native_validator_sha256': filehash(mim/'scripts/validate_sssom_invariants.py'),
              'native_invariants_exit_code': native_code, 'rule_k_baseline': 'empty in memory; canonical baseline untouched',
              'schema_validation': {'argv': command, 'exit_code': proc.returncode},
              'rows': len(rows), 'suppression_events': len(events), 'unique_suppressed_pairs': len(pairs),
              'previously_published_pairs_removed': delta['previously_published_pairs_removed'],
              'policy_encounter_classes': delta['policy_encounter_classes'],
              'observed_label_resolution_changes': label_changes,
              'mapped_source_records': len(mapped), 'all_individual_yaml_records': len(actual_yaml),
              'source_yaml_bytes_unchanged': True, 'canonical_and_baseline_unchanged': True,
              'exact_native_candidate_and_sidecar_replay': True, 'stamp_replay': stamp_outcomes,
              'trusted_entry_source_sha256': entry_sha,
              'producer_import_snapshot': imported_producers,
              'producer_binding_scope': manifest['producer_binding_scope'],
              'counterfactual': {'policy_calls': counterfactual_calls,
                                 'unique_encountered_pairs': len(counterfactual_encounters),
                                 'same_policy_encounters_as_real_replay': True,
                                 'private_and_entry_aliases_restored': True},
              'newest_row_mapping_date': newest, 'b4_input_sha256': transforms_before,
              'changed_row_classes': delta['class_counts'], 'changed_rows': delta['changed_rows'],
              'candidate_columns': columns, 'sidecar_columns': side_columns}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mim-root', 'claw-root', 'kg-root', 'bundle', 'old-bundle', 'journal', 'generation-harness', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--mim-revision', required=True)
    parser.add_argument('--producer-revision', required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    require(out.is_relative_to(HERE) and out != HERE, 'Output must be a new child of the acceptance directory')
    out.mkdir(parents=True, exist_ok=False)
    sys.pycache_prefix = str(out/'fresh-bytecode')
    sys.dont_write_bytecode = True
    initial = {str(p): filehash(p) for p in (args.bundle/'candidate.sssom.tsv',
                args.bundle/'suppressed_aliases.tsv', args.bundle/'candidate.sssom.tsv.manifest.json', args.journal)}
    try:
        result = run(args, out)
        require(all(filehash(Path(p)) == digest for p, digest in initial.items()), 'Accepted artifact/journal changed')
    except Exception as error:
        emit(out/'acceptance.json', {'status': 'FAIL', 'error': str(error), 'classification': 'Deterministic author acceptance',
                                    'scientific_approval_added': False, 'inputs_at_start': initial})
        raise
    result['timestamp'] = dt.datetime.now(dt.timezone.utc).isoformat()
    result['verifier_sha256'] = filehash(Path(__file__))
    emit(out/'acceptance.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
