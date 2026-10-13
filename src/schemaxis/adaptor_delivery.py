"""Discoverable development materials over the existing route registry.

Facts remain in declarations and route bindings. Curated development materials
state data/inspection boundaries and independent acceptance cases; they cannot
supply executable code or upgrade historical qualification into current support.
"""
import copy
import hashlib
import json
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from .adaptors import registry
from .authoring import patch
from .capabilities import digest
from .core.documents import load_document
from .core.faults import SchemaxisError
from .errors import fail
from .observations import bounded
from .workspaces import PANELS

PROTOCOL = 'schemaxis.adaptor-delivery/1'
FEATURES = ('workflow', 'native-inspection', 'composition', 'mpi', 'reusable-inputs',
            'time-batches', 'source-authoring', 'property-authoring', 'live-editing',
            'native-save', 'conversion')


def route_materials(version):
    provider, route = registry.resolve({'version': version})
    path = registry.adaptor_files(provider).joinpath('readiness.json')
    bundle = load_document(path.read_text()) if path.is_file() else {}
    if not isinstance(bundle, dict) or not isinstance(bundle.get('routes', {}), dict):
        fail('INVALID_DELIVERY', 'readiness.json must contain a routes object', provider)
    entry = bundle.get('routes', {}).get(version, {})
    if not isinstance(entry, dict):
        fail('INVALID_DELIVERY', 'route delivery must be an object', version)
    return provider, copy.deepcopy(route), copy.deepcopy(entry)


def source_digest(provider):
    """Conservative source identity, excluding other adaptors and evidence files."""
    root = files('schemaxis')
    records = {}
    def visit(folder, prefix=''):
        for path in sorted(folder.iterdir(), key=lambda p: p.name):
            name = prefix + path.name
            if path.is_dir():
                if path.name == '__pycache__':
                    continue
                if prefix == 'adaptors/' and path.name != provider:
                    continue
                visit(path, name + '/')
            elif path.name not in ('qualification.json', 'upstream.json') and not path.name.endswith(('.pyc', '.pyo')):
                records[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    visit(root)
    if registry.metadata(provider).get('source', 'builtin') != 'builtin':
        visit(registry.adaptor_files(provider), 'plugin/' + registry.adaptor_package(provider) + '/')
    from .readiness import repository_root
    checkout = repository_root(provider)
    path = registry.adaptor_files(provider).joinpath('readiness.json')
    bundle = load_document(path.read_text()) if path.is_file() else {}
    for entry in bundle.get('routes', {}).values():
        references = [e['reference'] for e in entry.get('examples', [])
                      if isinstance(e, dict) and isinstance(e.get('reference'), str)]
        references += [r for c in entry.get('development', {}).get('cases', [])
                       for r in c.get('resources', {}).values()]
        for reference in references:
            try:
                fixture = local_path(checkout, reference)
                records['fixture/' + reference] = hashlib.sha256(fixture.read_bytes()).hexdigest()
            except SchemaxisError:
                records['fixture/' + reference] = 'unavailable'
    return digest(records)


def local_path(root, reference):
    if not isinstance(reference, str) or not reference or Path(reference).is_absolute() or '..' in Path(reference).parts:
        fail('INVALID_DELIVERY', 'use a repository-relative file reference', str(reference))
    if root is None:
        fail('DELIVERY_UNAVAILABLE', 'matching repository checkout is required for this example', reference)
    root = Path(root).resolve()
    path = (root/reference).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        fail('DELIVERY_UNAVAILABLE', 'referenced fixture is absent or escapes the repository', reference)
    return path


def example_document(entry, identity, root=None):
    matches = [e for e in entry.get('examples', []) if isinstance(e, dict) and e.get('id') == identity]
    if len(matches) != 1:
        fail('INVALID_DELIVERY', 'case must name one registered example', str(identity))
    example = matches[0]
    if ('document' in example) == ('reference' in example):
        fail('INVALID_DELIVERY', 'example requires exactly one document or reference', identity)
    document = (copy.deepcopy(example['document']) if 'document' in example
                else load_document(local_path(root, example['reference']).read_text()))
    if not isinstance(document, dict):
        fail('INVALID_DELIVERY', 'example must be a document object', identity)
    return document


def case_document(entry, case, root=None):
    document = example_document(entry, case['example'], root)
    if case.get('edits'):
        document = patch(document, case['edits'])
    bindings = [{'op': 'replace', 'path': pointer, 'value': str(local_path(root, reference))}
                for pointer, reference in case.get('resources', {}).items()]
    return patch(document, bindings) if bindings else document


def case_document_digest(entry, case, root=None):
    """Portable input identity: fixture bytes and relative names, not checkout paths."""
    document = case_document(entry, case, root)
    bindings = [{'op': 'replace', 'path': pointer,
                 'value': {'fixture': reference, 'sha256': hashlib.sha256(local_path(root, reference).read_bytes()).hexdigest()}}
                for pointer, reference in case.get('resources', {}).items()]
    return digest(patch(document, bindings) if bindings else document)


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and not value.startswith('TODO')


def validate_development(version, entry):
    """Validate the reusable kit contract, without executing recipes or fetching URLs."""
    provider, route = registry.resolve({'version': version})
    dev = entry.get('development')
    def require(condition, message, location='development'):
        if not condition:
            fail('INVALID_DELIVERY', message, version + ':' + location)
    require(isinstance(dev, dict), 'add the development contract before admission')
    require(set(dev) == {'api', 'lifecycle', 'data', 'inspection', 'authoring', 'features', 'cases'},
            'development requires api, lifecycle, data, inspection, authoring, features and cases')
    require(isinstance(dev['api'], list) and bool(dev['api']), 'cite public native API sources')
    from .documentation_links import url_syntax
    for reference in dev['api']:
        require(_text(reference) and url_syntax(reference), 'API references must be non-placeholder HTTP(S) URLs', 'api')
    require(isinstance(dev['lifecycle'], dict) and set(dev['lifecycle']) == {'timeout', 'cancellation', 'logs', 'verification'}
            and all(_text(v) for v in dev['lifecycle'].values()), 'describe timeout scope, cancellation, retained logs and independent verification', 'lifecycle')
    authoring = dev['authoring']
    require(isinstance(authoring, dict) and set(authoring) == {'model', 'example', 'reuse'}, 'authoring needs model, example and reuse guidance', 'authoring')
    model = 'document' if route.get('graphEditing') is False else 'nodes'
    require(authoring['model'] == model and _text(authoring['reuse']), 'authoring model must match the routed document', 'authoring')
    examples = {e.get('id'): e for e in entry.get('examples', []) if isinstance(e, dict)}
    require(authoring['example'] in examples and examples[authoring['example']].get('expect', 'valid') == 'valid', 'choose a valid editable example', 'authoring')
    decisions = dev['features']
    require(isinstance(decisions, dict) and set(decisions) == set(FEATURES), 'record a decision for every optional feature; use unknown where unreviewed', 'features')
    manifest = registry.metadata(provider)
    claims = {'workflow': route.get('workflow'), 'composition': route.get('compose'),
              'time-batches': route.get('timeBatches'),
              'native-inspection': bool(route.get('hooks', {}).get('inspect') or route.get('hooks', {}).get('inspectionSetup')) or None,
              'reusable-inputs': bool(route.get('hooks', {}).get('reusableInputs')) or None}
    execution = manifest.get('executionCapabilities', {})
    claims['mpi'] = True if 'mpi' in execution.get('modes', []) else execution.get('mpi')
    if version == manifest['version']:
        claims['live-editing'] = manifest.get('consoleCapabilities', {}).get('liveGeometry')
        claims['native-save'] = bool(manifest.get('nativeExtension')) or None
    for name, decision in decisions.items():
        require(isinstance(decision, dict) and set(decision) == {'status', 'scope'}
                and decision['status'] in ('supported', 'unsupported', 'unknown') and _text(decision['scope']), 'feature decisions need status and scope', 'features.'+name)
        if name in claims and claims[name] is not None:
            require(decision['status'] == ('supported' if claims[name] else 'unsupported'), 'feature decision contradicts the authoritative manifest', 'features.'+name)
        if decision['status'] == 'supported' and name in ('native-inspection', 'reusable-inputs', 'mpi', 'workflow', 'composition', 'time-batches'):
            require(claims.get(name) is True, 'support requires the existing manifest flag/hook', 'features.'+name)
    require(isinstance(dev['data'], list) and bool(dev['data']), 'describe input/output artifact contracts', 'data')
    identities = set()
    for item in dev['data']:
        require(isinstance(item, dict) and set(item) == {'id', 'direction', 'kind', 'format', 'traits', 'losses', 'scope'}, 'invalid data contract fields', 'data')
        require(_text(item['id']) and item['id'] not in identities and item['direction'] in ('input', 'output'), 'data IDs must be unique; direction is input/output', 'data')
        identities.add(item['id'])
        require(all(_text(item[k]) for k in ('kind', 'format', 'scope')) and isinstance(item['traits'], dict) and bool(item['traits'])
                and isinstance(item['losses'], list) and all(_text(v) for v in item['losses']), 'data contracts need formats, explicit traits and losses', 'data')
        require(all(_text(k) and (v is None or isinstance(v, (str, int, float, bool, list))) for k, v in item['traits'].items()), 'traits must be JSON scalar/list values; null means unknown', 'data')
    # An external native input (e.g. a case directory) need not be a supported
    # workflow artifact. Every *advertised handoff* must still have a data contract.
    for kind in route.get('acceptedArtifacts', []):
        require(any(item['direction'] == 'input' and item['kind'] == kind for item in dev['data']),
                'accepted artifact kind needs an input data contract', 'data')
    require(isinstance(dev['inspection'], list) and bool(dev['inspection']), 'declare bounded reusable inspection representations', 'inspection')
    for view in dev['inspection']:
        require(isinstance(view, dict) and set(view) == {'panel', 'scope', 'limits'} and view['panel'] in PANELS
                and _text(view['scope']) and _text(view['limits']), 'inspection uses trusted panel IDs with scope and limits', 'inspection')
    cases = dev['cases']
    require(isinstance(cases, list) and len(cases) >= 2, 'supply a baseline and a distinct held-out acceptance case', 'cases')
    ids, documents = set(), set()
    for case in cases:
        require(isinstance(case, dict) and set(case) <= {'id', 'example', 'edits', 'resources', 'checks', 'scope'}
                and all(k in case for k in ('id', 'example', 'checks', 'scope')), 'invalid acceptance case fields', 'cases')
        require(_text(case['id']) and case['id'].replace('-', '_').isidentifier() and case['id'] not in ids
                and _text(case['scope']), 'cases need distinct slug IDs and scope', 'cases')
        ids.add(case['id'])
        require(case['example'] in examples and examples[case['example']].get('expect', 'valid') == 'valid', 'acceptance case must use a valid example', 'cases')
        require(isinstance(case.get('edits', []), list), 'edits use the existing closed JSON patch grammar', 'cases')
        resources = case.get('resources', {})
        require(isinstance(resources, dict), 'resources map JSON pointers to repository-relative fixtures', 'cases')
        for pointer, reference in resources.items():
            require(isinstance(pointer, str) and pointer.startswith('/')
                    and _text(reference) and not Path(reference).is_absolute() and '..' not in Path(reference).parts,
                    'resource bindings require JSON pointers and repository-relative fixture paths', 'cases')
        documents.add(digest({'example': case['example'], 'edits': case.get('edits', []), 'resources': resources}))
        require(isinstance(case['checks'], list) and bool(case['checks']), 'native acceptance needs independent numeric/text expectations', 'cases')
        for check in case['checks']:
            require(isinstance(check, dict) and set(check) <= {'file', 'format', 'pointer', 'expected', 'relative', 'absolute'}
                    and all(k in check for k in ('file', 'format', 'pointer', 'expected')), 'invalid acceptance assertion', 'cases')
            path = check['file']
            require(_text(path) and not Path(path).is_absolute() and '..' not in Path(path).parts,
                    'assertion file must stay within the native run', 'cases')
            require(check['format'] in ('json', 'csv', 'text') and isinstance(check['pointer'], str)
                    and (not check['pointer'] or check['pointer'].startswith('/')), 'assertions need a data format and JSON pointer', 'cases')
            for tolerance in ('relative', 'absolute'):
                value = check.get(tolerance, 0)
                require(type(value) in (int, float) and 0 <= value <= 1, 'tolerances must be finite values from zero to one', 'cases')
            require(check['expected'] is not None, 'null is not an independent acceptance expectation', 'cases')
    require(len(documents) >= 2, 'held-out case must change the authored input', 'cases')
    json.dumps(dev, allow_nan=False)
    return copy.deepcopy(dev)


def context(version, **page):
    provider, route, entry = route_materials(version)
    manifest = registry.metadata(provider)
    value = {'protocol': PROTOCOL, 'provider': provider, 'documentVersion': version,
             'route': route, 'runtimeFamily': manifest['runtimeFamily'],
             'declarations': manifest['declarations'] if version == manifest['version'] else None,
             'operationContext': 'capabilities.describe', 'materials': entry,
             'sourceDigest': source_digest(provider),
             'qualification': qualification_status(version),
             'scope': 'Declared guidance and fixtures; runtime availability is not probed.'}
    return bounded(value, 'adaptor/' + version, **page)


def qualification_status(version):
    provider, _ = registry.resolve({'version': version})
    path = registry.adaptor_files(provider).joinpath('qualification.json')
    if not path.is_file():
        return {'status': 'unknown', 'reason': 'No scoped development-kit receipt is registered.'}
    try:
        receipts = load_document(path.read_text())
        receipt = receipts['routes'][version]
        valid = (receipts['protocol'] == 'schemaxis.adaptor-qualification/1' and receipt['documentVersion'] == version
                 and receipt['provider'] == provider and receipt['verified'] is True and receipt['mode'] == 'native'
                 and isinstance(receipt['cases'], list) and len(receipt['cases']) >= 2
                 and all(c['verified'] is True and c.get('runtime') for c in receipt['cases']))
        if not valid:
            raise ValueError('malformed or unsuccessful native receipt')
        _, _, entry = route_materials(version)
        current = receipt['sourceDigest'] == source_digest(provider)
        if current:
            validate_receipt(receipt, version, entry)
        return {'status': 'source-current' if current else 'stale', 'receipt': receipt,
                'scope': 'Only cited cases and recorded runtimes; installation availability and untested profiles remain unknown.'}
    except (KeyError, TypeError, ValueError, SchemaxisError) as error:
        return {'status': 'unknown', 'reason': str(error)}


def validate_receipt(receipt, version, entry):
    """Internal receipt completeness, not an attestation against forged metadata."""
    cases = receipt.get('cases', [])
    expected = {c['id']: c for c in entry.get('development', {}).get('cases', [])}
    try:
        if (len(expected) < 2 or len(cases) != len(expected)
                or {c['id'] for c in cases} != set(expected)
                or receipt['host']['verified'] is not True or not receipt['host']['checks']
                or len(receipt['lifecycle']) != 2
                or {c['check'] for c in receipt['lifecycle']} != {'native runner timeout', 'pre-launch cancellation'}
                or any(c['verified'] is not True or c['fault'] != {'native runner timeout': 'RUNNER_TIMED_OUT',
                      'pre-launch cancellation': 'RUNNER_CANCELLED'}[c['check']] for c in receipt['lifecycle'])):
            raise ValueError('receipt omits host, case or lifecycle coverage')
        for case in cases:
            original = expected[case['id']]
            if (case['caseDigest'] != digest(original) or case['verified'] is not True or not case['runtime']
                    or not case['integrity'] or any(c['verified'] is not True for c in case['integrity'])
                    or len(case['checks']) != len(original['checks'])):
                raise ValueError('case is incomplete or differs from its recipe')
            from .readiness import repository_root
            if case['documentDigest'] != case_document_digest(entry, original, repository_root(registry.resolve({'version': version})[0])):
                raise ValueError('case document differs from the qualified input')
            evidence_checks = {c['check'] for c in case['integrity']}
            mandatory = {action + ' ' + name for name in ('authored.json', 'plan.json', 'verification.json')
                         for action in ('missing', 'tampered')}
            publication_checks = evidence_checks - mandatory
            if not mandatory <= evidence_checks or not any('tampered ' + name[8:] in publication_checks
                                                            for name in publication_checks if name.startswith('missing ')):
                raise ValueError('case lacks publication and retained-evidence integrity checks')
            for check, assertion in zip(case['checks'], original['checks']):
                if any(check[key] != assertion[key] for key in ('file', 'pointer', 'expected')):
                    raise ValueError('expectation does not match the registered fixture')
                from .tabular import close
                if (check.get('relative', 0) != assertion.get('relative', 0)
                        or check.get('absolute', 0) != assertion.get('absolute', 0)
                        or not close(check['observed'], assertion['expected'], rel=assertion.get('relative', 0), absolute=assertion.get('absolute', 0))):
                    raise ValueError('recorded observation fails its acceptance expectation')
    except (KeyError, TypeError, ValueError) as error:
        fail('INVALID_QUALIFICATION', str(error), version)


def reference_page():
    lines = ['# Adaptor delivery index', '',
             'Generated from installed routes and adaptor-owned readiness bundles.',
             'Context is curated; declarations and schemas remain authoritative. No native support is inferred.', '',
             '| Route | Guide | Development contract | Bounded context |',
             '| --- | --- | --- | --- |']
    for version, (provider, _) in registry.routes().items():
        _, _, entry = route_materials(version)
        guide = entry.get('guide')
        label = '[' + provider + '](' + '../../' + guide + ')' if guide else 'Not supplied'
        lines.append('| `' + version + '` | ' + label + ' | ' + ('supplied' if 'development' in entry else 'missing')
                     + ' | `schemaxis adaptor context ' + version + '` |')
    lines += ['', 'See the [development kit](../adaptor-development.md) for admission, scaffolding,',
              'conformance and source-bound qualification. Context retrieval supports JSON pointers',
              'and response budgets through both the CLI and `adaptor_context` agent method.', '']
    return '\n'.join(lines)
