#!/usr/bin/env python3
"""Seed, audit or export conceptual-help review work for every installed adaptor."""
import argparse
import json
from pathlib import Path
from schemaxis.adaptors import registry
from schemaxis.studio_guidance import (VERSION, SHARED, fields, load, audit, audit_shared, shared_fields,
                                      shared_schema, validate_record)

ROOT = Path(__file__).resolve().parents[1]
DERIVED = 'guidance:'
INHERITED = ('explanation', 'units', 'defaultMeaning', 'pitfalls', 'examples', 'fileExtensions')
OPERATION = DERIVED + 'operation '
OPERATION_KEYS = ('status', 'explanation', 'pitfalls')

def seed(provider):
    meta = registry.metadata(provider)
    guide = load(provider)
    caps = registry.binding(meta['capabilities'])() if meta.get('capabilities') else {}
    operations = caps.get('operations', {})
    source = 'src/schemaxis/adaptors/' + provider + '/'
    for name, declaration in registry.declarations(provider).items():
        if name in guide['operations']:
            continue
        context = operations.get(name, {})
        explanation = context.get('purpose') or declaration.get('summary')
        explanation = explanation.strip() if isinstance(explanation, str) else ''
        guide['operations'][name] = {'status': 'reference' if explanation else 'pending',
            **({'explanation': explanation, 'sources': [meta['capabilities'] if context.get('purpose') else meta['declarations']]} if explanation else {}),
            **({'pitfalls': [text for text in context['semantics'] if isinstance(text, str) and text.strip()]} if context.get('semantics') else {}),
            **({'examples': context['examples']} if context.get('examples') else {}),
            'question': 'When would you choose this operation, what does it produce, and what assumptions matter?'}
    for version, route in meta['routes'].items():
        records = guide['routes'].setdefault(version, {'fields': {}})['fields']
        for address, spec in fields(registry.binding(route['schema'])()):
            if address in records:
                continue
            explanation = spec.get('description') or spec.get('summary')
            explanation = explanation.strip() if isinstance(explanation, str) else ''
            records[address] = {'status': 'reference' if explanation else 'pending',
                **({'explanation': explanation, 'sources': [route['schema']]} if explanation else {})}
    target = ROOT / 'src/schemaxis/adaptors' / provider / 'guidance.json'
    target.write_text(json.dumps(guide, ensure_ascii=False, indent=2) + '\n')


def merge(current, patch):
    """Overlay a review patch; null removes a key and omitted metadata is retained."""
    result = {**(current or {}), **patch}
    return {key: value for key, value in result.items() if value is not None}


def reference(node):
    """Return the local definition address of a pure $ref node, if it is one."""
    target = node.get('$ref') if isinstance(node, dict) and set(node) == {'$ref'} else None
    return target[1:] if isinstance(target, str) and target.startswith('#/$defs/') else None


def origins(schema):
    """Map structural addresses to the record whose meaning they share.

    A pure local $ref has its definition's meaning. In a two-branch value
    wrapper whose other branch is such a $ref (for example a literal or a
    runtime expression), the literal branch is the wrapped field itself. A
    definition can supply a readable label to its references; a literal branch
    keeps its value-type title instead of repeating the field's label.
    """
    nodes = dict(fields(schema))
    result = {}
    for path, node in nodes.items():
        target = reference(node)
        if target is not None and target in nodes:
            result[path] = (target, True)
        for key in ('anyOf', 'oneOf'):
            branches = node.get(key)
            if not isinstance(branches, list) or len(branches) != 2:
                continue
            wrapped = [reference(branch) is not None for branch in branches]
            if sum(wrapped) == 1:
                result[path + '/' + key + '/' + str(wrapped.index(False))] = (path, False)
    return result


PROVIDERS = list(registry.ADAPTORS) + sorted(set(SHARED.values()))


def routes(provider):
    """Yield (version, schema, owned addresses) for an adaptor or shared document provider."""
    if provider in registry.ADAPTORS:
        for version, route in registry.metadata(provider)['routes'].items():
            schema = registry.binding(route['schema'])()
            yield version, schema, {path for path, _ in fields(schema)}
        return
    for version in [v for v, name in SHARED.items() if name == provider]:
        schema = shared_schema(version)
        yield version, schema, {path for path, _ in shared_fields(version, schema)}


def report(provider):
    return audit(provider) if provider in registry.ADAPTORS else audit_shared(provider)


def derive(provider):
    """Fill structural records from the record they share; never replace prose.

    Derived records carry a final ``guidance:<address>`` source. Rerunning
    refreshes them when the origin changes; remove that source to make a
    record independent. Pending origins leave their derivatives pending.
    A record whose final source is ``guidance:operation <id>`` repeats that
    operation record's status, explanation and pitfalls.
    """
    guide = load(provider)
    changed = 0
    for version, schema, owned in routes(provider):
        records = guide['routes'].setdefault(version, {'fields': {}})['fields']
        links = {path: link for path, link in origins(schema).items() if path in owned and link[0] in owned}
        for _ in range(len(links) + 1):
            progress = False
            for path, (origin, labelled) in sorted(links.items()):
                current = records.get(path, {'status': 'pending'})
                sources = current.get('sources', [])
                derived = current['status'] == 'pending' or (sources and sources[-1].startswith(DERIVED))
                source = records.get(origin, {'status': 'pending'})
                if not derived or source['status'] == 'pending':
                    continue
                label = source.get('label') if labelled else current.get('label')
                record = {'status': source['status'], **{key: source[key] for key in INHERITED if key in source},
                          **({'label': label} if label else {}),
                          'sources': [s for s in source.get('sources', []) if not s.startswith(DERIVED)] + [DERIVED + origin]}
                validate_record(record)
                if record != current:
                    records[path] = record
                    changed += 1
                    progress = True
            if not progress:
                break
        # A node variant ("a node running operation X") repeats that operation's record.
        for path, current in records.items():
            sources = current.get('sources', [])
            if not sources or not sources[-1].startswith(OPERATION):
                continue
            source = guide['operations'].get(sources[-1][len(OPERATION):], {'status': 'pending'})
            if source['status'] == 'pending':
                continue
            record = {**{k: v for k, v in current.items() if k not in OPERATION_KEYS},
                      **{k: source[k] for k in OPERATION_KEYS if k in source},
                      'sources': [s for s in source.get('sources', []) if not s.startswith(DERIVED)] + [sources[-1]]}
            validate_record(record)
            if record != current:
                records[path] = record
                changed += 1
    target = ROOT / 'src/schemaxis/adaptors' / provider / 'guidance.json'
    target.write_text(json.dumps(guide, ensure_ascii=False, indent=2) + '\n')
    return changed


def apply_review(path):
    patches = json.loads(path.read_text())
    updates = {}
    for provider, patch in patches.items():
        if provider not in PROVIDERS or set(patch) - {'file', 'operations', 'routes'}:
            raise ValueError('unknown adaptor or review keys')
        guide = load(provider)
        result = report(provider)
        for name, record in patch.get('operations', {}).items():
            if name not in result['operations']:
                raise ValueError('unknown operation: ' + name)
            record = merge(guide['operations'].get(name), record)
            validate_record(record)
            guide['operations'][name] = record
        for version, route in patch.get('routes', {}).items():
            if version not in result['routes'] or set(route) != {'fields'}:
                raise ValueError('unknown route or review fields: ' + version)
            for address, record in route['fields'].items():
                if address not in result['routes'][version]:
                    raise ValueError('stale field address: ' + address)
                record = merge(guide['routes'].get(version, {}).get('fields', {}).get(address), record)
                validate_record(record)
                guide['routes'].setdefault(version, {'fields': {}})['fields'][address] = record
        updates[provider] = guide
    # Validate the whole review before writing any adaptor; the file hint is never trusted.
    for provider, guide in updates.items():
        target = ROOT / 'src/schemaxis/adaptors' / provider / 'guidance.json'
        target.write_text(json.dumps(guide, ensure_ascii=False, indent=2) + '\n')


def missing_sources(provider):
    """Shared offline provenance checks include anchors, symbols and origins."""
    from schemaxis.studio_guidance import audit_links
    return sorted({s for issue in audit_links(load(provider), ROOT)
                   for s in issue.get('sources', [issue.get('source', '')])})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', action='store_true', help='Add missing records; never replace existing guidance')
    parser.add_argument('--derive', action='store_true', help='Fill or refresh structural records from the field they wrap')
    parser.add_argument('--check', action='store_true', help='Fail when guidance is pending or stale')
    parser.add_argument('--app', action='append', choices=PROVIDERS)
    parser.add_argument('--apply-review', type=Path, help='Validate and merge edited review records')
    parser.add_argument('--review', type=Path, help='Write editable JSON of pending records for human review')
    args = parser.parse_args()
    if args.apply_review:
        apply_review(args.apply_review)
    reports, review = [], {}
    for provider in args.app or PROVIDERS:
        if args.seed and provider in registry.ADAPTORS:
            seed(provider)
        if args.derive:
            derive(provider)
        result = report(provider)
        reports.append(result)
        counts = result['counts']
        missing = missing_sources(provider) if args.check else []
        result['complete'] = result['complete'] and not missing
        print(f"{provider}: {counts['reviewed']} reviewed, {counts['reference']} from references, {counts['pending']} pending; {len(result['stale'])} stale"
              + (f"; missing sources: {', '.join(missing)}" if missing else ''))
        guide = load(provider)
        review[provider] = {'file': 'src/schemaxis/adaptors/' + provider + '/guidance.json',
            'operations': {key: value for key, value in guide['operations'].items() if value['status'] == 'pending'},
            'routes': {version: {'fields': {key: value for key, value in route['fields'].items() if value['status'] == 'pending'}} for version, route in guide['routes'].items()}}
    if args.review:
        args.review.parent.mkdir(parents=True, exist_ok=True)
        args.review.write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
    if args.check and any(not result['complete'] for result in reports):
        raise SystemExit(1)

if __name__ == '__main__':
    main()
