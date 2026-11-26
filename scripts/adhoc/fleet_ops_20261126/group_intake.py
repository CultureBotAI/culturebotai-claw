"""Route captured queue evidence into provisional themes; no closure decisions."""
import argparse
import collections
import json
import re
from pathlib import Path

if __package__:
    from .pr_batches import refuse_existing, write_new
else:
    from pr_batches import refuse_existing, write_new

rules = [
    ('licence-and-source-access', r'licen[cs]|copyright|redistribut|unverified abstract'),
    ('validation-and-admission', r'\bci\b|failing|pytest|validation|freshness|admission|schema|vendored|workflow'),
    ('identifiers-and-grounding', r'grounding|grounded|curie|accession|identifier|taxon|taxonomy|uniprot|chebi|synonym'),
    ('graphs-and-mechanisms', r'graph|mechanis|causal|predicate|parthood'),
    ('evidence-and-scientific-scope', r'evidence|citation|source|claim|scope|support|review|qualif|attribution'),
    ('site-and-generated-artifacts', r'page|html|svg|render|site|readme|embedding|map|browser'),
]

def route(root):
    refuse_existing([root / 'routing.json', root / 'routing.md'])
    rows = []
    for kind, filename in [('issue', 'issues.json'), ('pr', 'prs.json')]:
        for item in json.loads((root / filename).read_text()):
            title = item['title']
            theme = next((name for name, pattern in rules if re.search(pattern, title, re.I)), 'other-maintenance')
            rows.append({'kind': kind, 'number': item['number'], 'url': item['html_url'],
                         'title': title, 'theme': theme, 'routing_basis': 'provisional title match; body and code review required',
                         'review_priority': 'Unranked', 'review_action': 'unreviewed',
                         'reason': 'No closure or scientific verdict follows from intake routing.'})
    write_new(root / 'routing.json', json.dumps(rows, indent=2) + '\n')
    counts = collections.Counter((r['kind'], r['theme']) for r in rows)
    lines = ['# Provisional queue routing', '',
             'These intake buckets do not assert shared causes or completed evidence review.', '',
             '| Kind | Theme | Count |', '|---|---|---:|']
    lines += [f'| {kind} | {theme} | {count} |' for (kind, theme), count in sorted(counts.items())]
    lines += ['', '| Kind | Number | Theme | Title |', '|---|---|---|---|']
    lines += [f"| {r['kind']} | [{r['number']}]({r['url']}) | {r['theme']} | {r['title'].replace('|', '/')} |" for r in rows]
    write_new(root / 'routing.md', '\n'.join(lines) + '\n')
    print(json.dumps({f'{kind}/{theme}': count for (kind, theme), count in sorted(counts.items())}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args(argv)
    route(args.directory)


if __name__ == '__main__':
    main()
