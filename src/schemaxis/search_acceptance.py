# Copyright (C) 2026 David L F Gaden
"""Adaptor-owned acceptance phrases, shared by admission and Studio regressions."""
import re
from urllib.parse import quote

SURFACES = {'capabilities', 'adaptor', 'add', 'help'}
KINDS = {'synonym', 'multiword', 'ambiguous', 'negative'}


def validate_cases(cases, provider, declarations):
    def require(ok, message):
        if not ok:
            from .capabilities import fault
            fault('INVALID_CAPABILITY_METADATA', message, provider + ':searchCases')
    require(isinstance(cases, list), 'searchCases must be an array')
    identities = set()
    operations = {'operation/' + provider + '/' + quote(n, safe='') for n in declarations}
    for case in cases:
        require(isinstance(case, dict) and set(case) <= {'id', 'query', 'kind', 'status', 'expected', 'excluded', 'scope'}, 'invalid search case fields')
        identity = case.get('id')
        require(isinstance(identity, str) and re.fullmatch('[a-z][a-z0-9-]*', identity) and identity not in identities, 'search cases need unique slug IDs')
        identities.add(identity)
        require(case.get('status') in ('pending', 'reviewed') and case.get('kind') in KINDS, 'search case needs status and kind')
        require(isinstance(case.get('query'), str) and 0 < len(case['query'].strip()) <= 256, 'search query needs useful text (at most 256 characters)')
        require(isinstance(case.get('scope', 'root'), str) and bool(case.get('scope', 'root')), 'search scope must be a capability ID')
        expected, excluded = case.get('expected'), case.get('excluded', {})
        require(isinstance(expected, dict) and bool(expected) and set(expected) <= SURFACES, 'expected must map real search surfaces to capability IDs')
        require(isinstance(excluded, dict) and set(excluded) <= set(expected), 'excluded must use the expected surfaces')
        for surface in expected:
            allowed = {'app/' + provider} if surface == 'adaptor' else operations
            for values in (expected[surface], excluded.get(surface, [])):
                require(isinstance(values, list) and all(isinstance(v, str) for v in values), 'search expectations must be string arrays')
                require(len(values) == len(set(values)) and set(values) <= allowed, 'search case names duplicate or unknown capabilities for ' + surface)
            require(not set(expected[surface]) & set(excluded.get(surface, [])), 'expected and excluded capabilities overlap')
            require(bool(expected[surface] or excluded.get(surface)), 'each surface needs a positive or negative assertion')


def check_cases(catalogue, provider):
    cases = catalogue._metadata[provider].get('searchCases', [])
    reviewed = [c for c in cases if c['status'] == 'reviewed']
    coverage = {c['kind'] for c in reviewed}
    surfaces = {s for c in reviewed for s in c['expected']}
    failures, evidence = [], []
    for case in reviewed:
        if 'capabilities' not in case['expected']:
            continue
        observed, cursor = [], None
        while True:
            page = catalogue.search(case['query'], scope=case.get('scope', 'app/' + provider),
                                    cursor=cursor, limit=100, max_bytes=65536)
            observed.extend(i['id'] for i in page['items'])
            cursor = page['page']['nextCursor']
            if cursor is None:
                break
        if (set(case['expected']['capabilities']) - set(observed)
                or set(case.get('excluded', {}).get('capabilities', [])) & set(observed)):
            failures.append(case['id'])
        evidence.append({'case': case['id'], 'query': case['query'], 'observed': observed})
    return {'complete': bool(cases) and len(reviewed) == len(cases) and coverage == KINDS
                       and surfaces == SURFACES and not failures,
            'pending': [c['id'] for c in cases if c['status'] == 'pending'],
            'missingKinds': sorted(KINDS - coverage), 'missingSurfaces': sorted(SURFACES - surfaces),
            'failedCases': failures, 'evidence': evidence,
            'scope': 'Capability matching checked here; run Studio regressions for Add, selection and Help. Phrase usefulness requires review.'}
