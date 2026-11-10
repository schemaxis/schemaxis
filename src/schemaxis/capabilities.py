# Copyright (C) 2026 David L F Gaden
"""Progressive, host-only views of the installed adaptor registry.

A catalogue is an immutable-by-interface snapshot. Navigation metadata belongs to
adaptors; schemas and executable declarations are never copied into a second registry.
"""
import base64
import copy
import difflib
import hashlib
import json
import re
from urllib.parse import quote

from .adaptors import registry
from .core.faults import Fault, SchemaxisError

PROTOCOL = 'schemaxis.capabilities/1'
DEFAULT_LIMIT = 12
DEFAULT_BYTES = 8192
SECTIONS = ('declaration', 'schema', 'requirements', 'examples', 'provenance')


def digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                               allow_nan=False).encode('utf-8')).hexdigest()


def response_bytes(value):
    """Bytes emitted by the public CLI, including its trailing newline."""
    return len((json.dumps(value, indent=2, allow_nan=False) + '\n').encode('utf-8'))


def fault(code, message, location='$', recovery='Browse root or search using purpose keywords.', **observed):
    raise SchemaxisError(Fault(code, message, location, 'discovery',
                              observed=observed, recovery=recovery))


def operation_id(provider, operation):
    return 'operation/' + provider + '/' + quote(operation, safe='')


class CapabilityCatalogue:
    """Transport-neutral browse/search/describe service over one registry snapshot.

    Construct a fresh instance after installing or changing trusted adaptor code.
    Runtime availability, qualification and input compatibility are deliberately
    unknown: this service neither probes applications nor inspects input resources.
    """

    def __init__(self, providers=None):
        selected = list(registry.ADAPTORS if providers is None else providers)
        from .assessments import assessment
        # A plugin whose bindings fail is excluded (see registry.exclude_plugin).
        found = {p: registry.isolated(p, lambda p=p: (registry.declarations(p), self._extra(p)))[0]
                 for p in selected}
        self._manifests = copy.deepcopy({p: registry.metadata(p) for p in selected if found[p] is not None})
        self._declarations = {p: found[p][0] for p in self._manifests}
        self._assessments = {p: assessment(p) for p in self._manifests}
        self._metadata = {}
        self._entries = {'root': {'id': 'root', 'kind': 'root', 'label': 'Capabilities',
                                 'purpose': 'Browse applications or curated task domains.', 'parents': []}}
        self._children = {'root': set()}
        self._contracts = {}
        self._document_schemas = {}
        self._schema_documents = {}
        for provider, manifest in self._manifests.items():
            extra = found[provider][1]
            self._metadata[provider] = copy.deepcopy(extra)
            self._add_provider(provider, manifest, extra)
        self.revision = digest({'protocol': PROTOCOL, 'manifests': self._manifests,
                                'declarations': self._declarations, 'navigation': self._metadata,
                                'assessments': self._assessments})

    @staticmethod
    def _extra(provider):
        path = registry.metadata(provider).get('capabilities')
        return registry.binding(path)() if path else {}

    def _add(self, entry):
        identity = entry['id']
        if identity in self._entries and self._entries[identity] != entry:
            fault('INVALID_CAPABILITY_METADATA', 'conflicting navigation identity', identity)
        self._entries[identity] = entry
        self._children.setdefault(identity, set())
        for parent in entry['parents']:
            self._children.setdefault(parent, set()).add(identity)

    def _add_provider(self, provider, manifest, extra):
        location = manifest.get('capabilities', provider)
        if not isinstance(extra, dict) or set(extra) - {'groups', 'operations', 'requirements', 'references', 'application', 'searchCases'}:
            fault('INVALID_CAPABILITY_METADATA', 'expected groups, operations, requirements and references', location)
        for key in ('requirements', 'references'):
            if not isinstance(extra.get(key, []), list) or any(not isinstance(v, str) for v in extra.get(key, [])):
                fault('INVALID_CAPABILITY_METADATA', key + ' must be a string array', location)
        groups, operations = extra.get('groups', {}), extra.get('operations', {})
        if not isinstance(groups, dict) or not isinstance(operations, dict):
            fault('INVALID_CAPABILITY_METADATA', 'groups and operations must be objects', location)
        unknown = set(operations) - set(self._declarations[provider])
        if unknown:
            fault('INVALID_CAPABILITY_METADATA', 'navigation names undeclared operations', location,
                  operations=sorted(unknown))
        app = 'app/' + provider
        application = extra.get('application', {})
        if (not isinstance(application, dict) or set(application) - {'label', 'purpose', 'keywords'}
                or any(not isinstance(application[k], str) or not application[k].strip() for k in ('label', 'purpose') if k in application)
                or not isinstance(application.get('keywords', []), list)
                or any(not isinstance(k, str) or not k.strip() for k in application.get('keywords', []))):
            fault('INVALID_CAPABILITY_METADATA', 'application requires label/purpose text and a keywords array', location)
        from .search_acceptance import validate_cases
        validate_cases(extra.get('searchCases', []), provider, self._declarations[provider])
        self._add({'id': app, 'kind': 'application', 'label': application.get('label', provider),
                   'purpose': application.get('purpose', manifest['execution']), 'parents': ['root']})
        for name, group in groups.items():
            if not isinstance(name, str) or not re.fullmatch('[a-z][a-z0-9-]*', name) or not isinstance(group, dict):
                fault('INVALID_CAPABILITY_METADATA', 'invalid group', location)
            if set(group) != {'label', 'purpose', 'domain'} or not all(isinstance(v, str) and v for v in group.values()):
                fault('INVALID_CAPABILITY_METADATA', 'group needs label, purpose and domain strings', location)
            domain = group['domain']
            if not re.fullmatch('[a-z][a-z0-9-]*', domain):
                fault('INVALID_CAPABILITY_METADATA', 'invalid domain', location)
            self._add({'id': 'domain/' + domain, 'kind': 'domain', 'label': domain.replace('-', ' '),
                       'purpose': 'Curated ' + domain.replace('-', ' ') + ' capabilities.', 'parents': ['root']})
            self._add({'id': 'group/' + provider + '/' + name, 'kind': 'group',
                       'label': group['label'], 'purpose': group['purpose'],
                       'parents': [app, 'domain/' + domain]})
        for name, declaration in self._declarations[provider].items():
            item = operations.get(name, {})
            if not isinstance(item, dict) or set(item) - {'purpose', 'groups', 'keywords', 'related', 'examples', 'semantics'}:
                fault('INVALID_CAPABILITY_METADATA', 'invalid operation metadata', location, operation=name)
            for field in ('groups', 'keywords', 'related', 'semantics'):
                if not isinstance(item.get(field, []), list) or any(not isinstance(s, str) or (field == 'keywords' and not s.strip()) for s in item.get(field, [])):
                    fault('INVALID_CAPABILITY_METADATA', field + ' must be a string array', location)
            if set(item.get('groups', [])) - set(groups) or set(item.get('related', [])) - set(self._declarations[provider]):
                fault('INVALID_CAPABILITY_METADATA', 'unknown group or related operation', location, operation=name)
            examples = item.get('examples', [])
            if not isinstance(examples, list) or any(
                    not isinstance(example, dict) or not isinstance(example.get('purpose'), str)
                    or not (isinstance(example.get('document'), dict) or isinstance(example.get('reference'), str))
                    for example in examples):
                fault('INVALID_CAPABILITY_METADATA', 'examples require a purpose and document or reference', location)
            purpose = item.get('purpose', declaration.get('summary', 'Declared ' + name + ' operation.'))
            if not isinstance(purpose, str) or not purpose:
                fault('INVALID_CAPABILITY_METADATA', 'purpose must be a nonempty string', location)
            self._add({'id': operation_id(provider, name), 'kind': 'operation', 'label': name,
                       'provider': provider, 'purpose': purpose,
                       'parents': [app] + ['group/' + provider + '/' + g for g in item.get('groups', [])]})

    def _check_revision(self, revision):
        if revision is not None and revision != self.revision:
            fault('STALE_CATALOGUE', 'catalogue revision changed', recovery='Restart navigation without the old cursor or revision.',
                  catalogueRevision=self.revision)

    def _resolve(self, identity):
        if not isinstance(identity, str) or not identity or len(identity) > 512:
            fault('INVALID_CAPABILITY_ID', 'provide a nonempty capability ID of at most 512 characters')
        if identity in self._entries:
            return identity
        matches = sorted(k for k, v in self._entries.items() if v['label'].casefold() == identity.casefold())
        if len(matches) == 1:
            return matches[0]
        if matches:
            fault('AMBIGUOUS_CAPABILITY', 'use a canonical capability ID', identity,
                  alternatives=matches[:8], alternativesTruncated=len(matches) > 8)
        parts = identity.split('/')
        parent = 'app/' + parts[1] if len(parts) > 2 and 'app/' + parts[1] in self._entries else 'root'
        alternatives = difflib.get_close_matches(identity, sorted(self._entries), n=5, cutoff=0.35)
        fault('UNKNOWN_CAPABILITY', 'capability is not in this catalogue', identity,
              parent=parent, alternatives=alternatives, search={'scope': parent, 'query': parts[-1]})

    @staticmethod
    def _status():
        return {'declaration': 'declared', 'runtimeAvailability': 'unknown',
                'qualification': 'unknown', 'inputCompatibility': 'unknown'}

    def _summary(self, identity):
        entry = copy.deepcopy(self._entries[identity])
        if entry['kind'] == 'operation':
            declaration = self._declarations[entry['provider']][entry['label']]
            metadata = self._metadata[entry['provider']].get('operations', {}).get(entry['label'], {})
            entry.update(status=self._status(),
                         inputKinds=sorted({p.get('kind', 'unknown') for p in declaration.get('inputs', {}).values()}),
                         outputKinds=copy.deepcopy(declaration.get('kinds', ['unknown'])),
                         requiredInputs=sorted(k for k, v in declaration.get('inputs', {}).items() if v.get('required')),
                         related=[operation_id(entry['provider'], n) for n in metadata.get('related', [])])
        else:
            entry['childCount'] = len(self._children[identity])
            if entry['kind'] == 'application':
                from .assessments import summary
                provider = identity.partition('/')[2]
                entry['status'] = self._status()
                entry['routeCount'] = len(self._manifests[provider]['routes'])
                entry['assessment'] = summary(self._assessments[provider])
        return entry

    def _descendants(self, identity):
        found, pending = set(), [identity]
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            pending.extend(self._children[current])
        return found

    def _page(self, identities, request, *, limit, cursor, max_bytes, summarise=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            fault('INVALID_PAGE_LIMIT', 'limit must be an integer from 1 to 100', 'limit')
        if type(max_bytes) is not int or not 2048 <= max_bytes <= 65536:
            fault('INVALID_BYTE_LIMIT', 'max_bytes must be an integer from 2048 to 65536', 'max_bytes')
        offset, request_digest = 0, digest(request)
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or len(cursor) > 2048:
                    raise ValueError('invalid cursor size')
                decoded = json.loads(base64.b64decode(cursor, altchars=b'-_', validate=True))
                if not isinstance(decoded, dict) or set(decoded) != {'revision', 'request', 'offset'}:
                    raise ValueError('invalid cursor shape')
                self._check_revision(decoded['revision'])
                offset = decoded['offset']
                if decoded['request'] != request_digest or type(offset) is not int or not 0 <= offset < len(identities):
                    raise ValueError('cursor does not belong to this request')
            except (ValueError, TypeError, UnicodeError):
                fault('INVALID_CURSOR', 'cursor is malformed or belongs to another request', 'cursor',
                      recovery='Repeat the original browse/search request without a cursor.')
        end = min(offset + limit, len(identities))
        while True:
            next_cursor = (base64.urlsafe_b64encode(json.dumps({'revision': self.revision,
                'request': request_digest, 'offset': end}, separators=(',', ':')).encode()).decode()
                if end < len(identities) else None)
            result = {'protocol': PROTOCOL, 'catalogueRevision': self.revision, **copy.deepcopy(request),
                      'items': [(summarise or self._summary)(i) for i in identities[offset:end]],
                      'page': {'offset': offset, 'returned': end-offset, 'total': len(identities),
                               'limit': limit, 'maxBytes': max_bytes, 'nextCursor': next_cursor,
                               'hasMore': end < len(identities)}}
            if response_bytes(result) <= max_bytes:
                return result
            end -= 1
            if end <= offset:
                fault('PAGE_BUDGET_TOO_SMALL', 'one complete summary exceeds the byte budget',
                      recovery='Increase max_bytes (up to 65536) or describe the capability directly.',
                      capability=identities[offset] if identities else request['scope'])

    def browse(self, scope='root', *, limit=DEFAULT_LIMIT, cursor=None,
               revision=None, max_bytes=DEFAULT_BYTES):
        self._check_revision(revision)
        scope = self._resolve(scope)
        return self._page(sorted(self._children[scope]),
                          {'action': 'browse', 'scope': scope, 'parents': self._entries[scope]['parents']},
                          limit=limit, cursor=cursor, max_bytes=max_bytes)

    def search(self, query, *, scope='root', input_kind=None, output_kind=None,
               limit=DEFAULT_LIMIT, cursor=None, revision=None, max_bytes=DEFAULT_BYTES):
        self._check_revision(revision)
        if not isinstance(query, str) or len(query) > 256:
            fault('INVALID_QUERY', 'query must be a string of at most 256 characters', 'query')
        for name, value in (('input_kind', input_kind), ('output_kind', output_kind)):
            if value is not None and (not isinstance(value, str) or not value or len(value) > 128):
                fault('INVALID_QUERY', name + ' must be a nonempty string of at most 128 characters', name)
        scope = self._resolve(scope)
        tokens, matches = query.casefold().split(), []
        for identity in sorted(self._descendants(scope)):
            entry = self._entries[identity]
            if entry['kind'] != 'operation':
                continue
            provider, name = entry['provider'], entry['label']
            item = self._metadata[provider].get('operations', {}).get(name, {})
            declaration = self._declarations[provider][name]
            text = self.operation_search_text(provider, name).casefold()
            summary = self._summary(identity)
            if (all(t in text for t in tokens)
                    and (input_kind is None or input_kind in summary['inputKinds'])
                    and (output_kind is None or output_kind in summary['outputKinds'])):
                matches.append(identity)
        return self._page(matches, {'action': 'search', 'scope': scope, 'query': ' '.join(tokens),
                          'inputKind': input_kind, 'outputKind': output_kind},
                          limit=limit, cursor=cursor, max_bytes=max_bytes)

    def operation_search_text(self, provider, name):
        """One authoritative projection for operation discovery, Add and Help.

        Application-wide keywords remain for compatibility. Do not copy new
        application synonyms onto every operation; curate its own terms instead.
        """
        entry = self._entries[operation_id(provider, name)]
        declaration = self._declarations[provider][name]
        item = self._metadata[provider].get('operations', {}).get(name, {})
        return ' '.join([entry['id'], entry['purpose'], str(declaration.get('native', '')),
                         *self._manifests[provider]['keywords'], *item.get('keywords', [])])

    def application_projection(self, provider):
        """Studio selection can find an app by its supported operation phrases."""
        app = self._entries['app/' + provider]
        extra = self._metadata[provider].get('application', {})
        return {'label': app['label'], 'purpose': app['purpose'],
                'searchText': ' '.join([app['id'], app['label'], app['purpose'],
                    *extra.get('keywords', []),
                    *(self.operation_search_text(provider, name) for name in self._declarations[provider])])}

    def _contract(self, identity):
        if identity not in self._contracts:
            from .schema import DRAFT, option_schema, export_schema
            entry = self._entries[identity]
            provider, name = entry['provider'], entry['label']
            manifest = self._manifests[provider]
            declaration = self._declarations[provider][name]
            extra = self._metadata[provider]
            item = extra.get('operations', {}).get(name, {})
            builder = registry.binding(manifest['optionSchema']) if manifest.get('optionSchema') else option_schema
            if provider not in self._document_schemas:
                self._schema_documents[provider] = export_schema(provider, authored=True, version=manifest['version'])
                self._document_schemas[provider] = digest(self._schema_documents[provider])
            document = {'documentVersion': manifest['version'],
                        'digest': self._document_schemas[provider],
                        'command': ['schemaxis', 'schema', '--authored', '--version', manifest['version']],
                        'browseCommand': ['schemaxis', 'capabilities', 'schema', identity],
                        'nodePointer': self._node_pointer(self._schema_documents[provider], name)}
            self._contracts[identity] = {
                'declaration': declaration,
                'schema': {'literalOptions': {'$schema': DRAFT, 'title': provider + '.' + name + ' literal options', **builder(copy.deepcopy(declaration))},
                           'authoredDocument': document,
                           'scope': 'Literal options only. Retrieve the document schema for node placement and authored syntax; plan for semantic constraints.'},
                'requirements': {'documentVersion': manifest['version'],
                    'runtimeFamily': manifest['runtimeFamily'], 'executables': manifest['executables'],
                    'executionScope': manifest['execution'], 'inputs': declaration.get('inputs', {}),
                    'requires': declaration.get('requires', []), 'checks': declaration.get('checks', []),
                    'semantics': extra.get('requirements', []) + item.get('semantics', []),
                    'statusScope': 'Declaration only; installation, native qualification and resource compatibility have not been checked.',
                    'validation': 'Use plan for dependencies and semantic checks; run and verify for native evidence.'},
                'examples': {'items': item.get('examples', []),
                             'scope': 'Curated authored examples; presence is not native qualification.'},
                'provenance': {'declarations': manifest['declarations'], 'operationKey': name,
                    'navigation': manifest.get('capabilities'),
                    'documentSchema': manifest['routes'][manifest['version']]['schema'],
                    'references': extra.get('references', []),
                    'digestScope': 'Returned contract sections and referenced authored document schema; planner/native implementation and runtime installation are not hashed.',
                    'identityScope': 'Primary document route; native inventories and additional document routes are not operation contracts here.'}}
        return self._contracts[identity]

    @staticmethod
    def _node_pointer(document, operation):
        """Find the existing authored node schema, without rewriting any constraints."""
        def find(value, pointer):
            if isinstance(value, dict):
                selector = value.get('properties', {}).get('filter', {})
                while isinstance(selector, dict) and 'anyOf' in selector:
                    selector = selector['anyOf'][0]
                # Discriminator guards also contain filter.const, but are not the node contract.
                if ('id' in value.get('properties', {}) and isinstance(selector, dict)
                        and selector.get('const') == operation):
                    return pointer
                for key, child in value.items():
                    found = find(child, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
                    if found is not None:
                        return found
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    found = find(child, pointer + '/' + str(index))
                    if found is not None:
                        return found
            return None
        return find(document.get('properties', {}).get('nodes', {}), '/properties/nodes')

    def schema(self, identity, *, pointer='', limit=DEFAULT_LIMIT, cursor=None,
               revision=None, max_bytes=DEFAULT_BYTES):
        """Read an exact schema fragment, or page lossless links to its children.

        Pointers and $refs are relative to the *whole* authored document schema.
        A members response is navigation data, never a truncated JSON Schema.
        """
        self._check_revision(revision)
        identity = self._resolve(identity)
        if self._entries[identity]['kind'] != 'operation':
            fault('NOT_AN_OPERATION', 'select an operation to address its document schema', identity)
        if not isinstance(pointer, str) or len(pointer) > 2048 or (pointer and not pointer.startswith('/')):
            fault('INVALID_SCHEMA_POINTER', 'use an RFC 6901 JSON Pointer (empty for root)', 'pointer')
        contract = self._contract(identity)
        provider = self._entries[identity]['provider']
        value = self._schema_documents[provider]
        try:
            for token in pointer.split('/')[1:] if pointer else []:
                if re.search('~(?![01])', token):
                    raise ValueError('invalid pointer escape')
                token = token.replace('~1', '/').replace('~0', '~')
                if isinstance(value, list):
                    if not re.fullmatch('0|[1-9][0-9]*', token):
                        raise ValueError('invalid array index')
                    value = value[int(token)]
                else:
                    value = value[token]
        except (KeyError, IndexError, ValueError, TypeError):
            fault('INVALID_SCHEMA_POINTER', 'pointer does not address this schema', pointer or '$',
                  recovery='Browse the parent pointer and follow the returned child pointers.',
                  parent=pointer.rpartition('/')[0])
        request = {'action': 'schema', 'scope': identity, 'pointer': pointer,
                   'schemaDigest': self._document_schemas[provider],
                   'documentVersion': contract['requirements']['documentVersion']}
        # Validate the same transport bounds even when the fragment fits in one response.
        self._page([], request, limit=limit, cursor=None, max_bytes=max_bytes)
        whole = {'protocol': PROTOCOL, 'catalogueRevision': self.revision, **request,
                 'mode': 'value', 'maxBytes': max_bytes, 'value': copy.deepcopy(value),
                 'referenceBase': 'All local $refs resolve from the document schema root, not this fragment.'}
        if cursor is None and response_bytes(whole) <= max_bytes:
            return whole
        if not isinstance(value, (dict, list)):
            fault('SCHEMA_FRAGMENT_TOO_LARGE', 'scalar schema value exceeds the response budget', pointer or '$',
                  recovery='Increase max_bytes or retrieve the complete schema using the command provided.',
                  command=contract['schema']['authoredDocument']['command'])
        names = sorted(value) if isinstance(value, dict) else list(range(len(value)))
        def summary(key):
            child = value[key]
            kind = ('object' if isinstance(child, dict) else 'array' if isinstance(child, list) else 'scalar')
            return {'key': key, 'pointer': pointer + '/' + str(key).replace('~', '~0').replace('/', '~1'),
                    'kind': kind}
        return self._page(names, {**request, 'mode': 'members',
                          'container': 'object' if isinstance(value, dict) else 'array'},
                          limit=limit, cursor=cursor, max_bytes=max_bytes, summarise=summary)

    def describe(self, identity, *, sections=None, known_digest=None, revision=None):
        """Return complete selected sections, never truncated required constraints.

        Unlike summary pages, complete sections have no byte cap. Clients may fetch
        sections separately and cache by contractDigest. Document schemas use the
        existing exact-version schema endpoint rather than embedding unrelated nodes.
        """
        self._check_revision(revision)
        identity = self._resolve(identity)
        if self._entries[identity]['kind'] != 'operation':
            fault('NOT_AN_OPERATION', 'browse this entry to select an operation', identity,
                  scope=identity)
        if sections is None:
            sections = list(SECTIONS)
        if (not isinstance(sections, (list, tuple)) or not sections
                or any(not isinstance(s, str) or s not in SECTIONS for s in sections)):
            fault('UNKNOWN_CONTRACT_SECTION', 'select one or more available sections',
                  availableSections=list(SECTIONS))
        contract = self._contract(identity)
        contract_digest = digest({'protocol': PROTOCOL, 'id': identity, 'sections': contract})
        result = {'protocol': PROTOCOL, 'catalogueRevision': self.revision,
                  'capability': self._summary(identity), 'contractDigest': contract_digest,
                  'availableSections': list(SECTIONS),
                  'notModified': known_digest == contract_digest}
        if not result['notModified']:
            result['sections'] = {s: copy.deepcopy(contract[s]) for s in SECTIONS if s in sections}
            result['completeSections'] = list(result['sections'])
        return result
