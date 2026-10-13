#!/usr/bin/env python3
"""Audit every packaged Studio recipe and guidance route without native imports.

Host planning verifies the supplied fixture values, not the user's actual data.
Editorial flags are review candidates rather than assertions of scientific error.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
from schemaxis.adaptors import registry
from schemaxis.studio_library import load_library, instantiate_item, plan_item
from schemaxis.studio_guidance import audit, fields, load


def review_kind(address, specification):
    if 'const' in specification or specification.get('enum') and len(specification['enum']) == 1:
        return 'discriminator'
    if '/properties/' in address and '/' not in address.rsplit('/properties/', 1)[1]:
        return 'named-field'
    return 'schema-structure'


def run():
    report = {'scope': 'Host planning of every packaged snippet/template and editorial inventory; no native acceptance.',
              'libraries': [], 'guidance': []}
    root = Path(__file__).resolve().parents[1] / 'src/schemaxis/adaptors'
    for path in sorted(root.glob('*/studio.json')):
        provider = path.parent.name
        library = load_library(provider)
        items = []
        descriptions = Counter(item.get('description') for group in ('snippets', 'templates') for item in library[group])
        for group in ('snippets', 'templates'):
            for item in library[group]:
                row = {'id': item['id'], 'kind': group, 'title': item['title'], 'flags': []}
                try:
                    document = instantiate_item(library, item, provider=provider)
                    plan_item(document)
                    row['hostPlan'] = 'pass'
                except Exception as error:
                    row.update(hostPlan='fail', error=str(error))
                if descriptions[item.get('description')] > 1:
                    row['flags'].append('Repeated description: check that purpose distinguishes this recipe.')
                if not item.get('description'):
                    row['flags'].append('Missing recipe description.')
                for name, spec in item.get('fields', {}).items():
                    if spec['type'] == 'path' and 'default' in spec:
                        row['flags'].append(f'{name}: path has a demonstration default; consider a testValue and explicit user selection.')
                    if spec['type'] in ('vector3', 'bounds', 'field') and not spec.get('description'):
                        row['flags'].append(f'{name}: spatial/array field lacks a contextual description.')
                items.append(row)
        report['libraries'].append({'provider': provider, 'items': items})
    for provider, meta in registry.ADAPTORS.items():
        inventory = audit(provider)
        guide = load(provider)
        categories = Counter()
        pending = []
        for version, route in meta['routes'].items():
            for address, spec in fields(registry.binding(route['schema'])()):
                kind = review_kind(address, spec)
                record = guide['routes'].get(version, {}).get('fields', {}).get(address, {'status': 'pending'})
                categories[kind + ':' + record['status']] += 1
                if kind == 'named-field' and record['status'] == 'pending':
                    pending.append({'route': version, 'address': address})
        report['guidance'].append({'provider': provider, 'counts': inventory['counts'],
            'fieldCategories': dict(categories), 'stale': inventory['stale'], 'pendingNamedFields': pending})
    report['totals'] = {'libraries': len(report['libraries']),
        **{kind: sum(item['kind'] == kind for lib in report['libraries'] for item in lib['items']) for kind in ('snippets','templates')},
        'hostPlanFailures': sum(item['hostPlan'] != 'pass' for lib in report['libraries'] for item in lib['items']),
        'editorialCandidates': sum(bool(item['flags']) for lib in report['libraries'] for item in lib['items'])}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['totals']))
    return bool(report['totals']['hostPlanFailures'] or any(item['stale'] for item in report['guidance']))


if __name__ == '__main__':
    raise SystemExit(main())
