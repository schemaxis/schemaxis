# Copyright (C) 2026 David L F Gaden
"""Host-only admission checks over the installed registry, never native qualification.

Delivery metadata contains curated guidance and fixture pointers, not a second
operation registry. Checks are deliberately scoped: present hooks and historical
receipts cannot establish native behaviour, availability or current correctness.
"""
import ast
import copy
import json
import re
from importlib import import_module
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote, urlsplit, unquote

from .adaptors import registry
from .capabilities import CapabilityCatalogue
from .core.documents import load_document
from .core.faults import SchemaxisError
from .errors import fail
from .schema import option_schema
from .documentation_links import markdown_anchors, url_syntax

PROTOCOL = 'schemaxis.readiness/1'
CONTEXT = ('purpose', 'assumptions', 'constraints', 'inspection', 'recovery')
PROFILES = ('workflow', 'native-inspection', 'composition', 'mpi')


def repository_root(provider=None):
    """Source checkout that owns delivery links; None for an installed wheel.

    External adaptor packages resolve links against their own checkout (the
    folder holding ``pyproject.toml`` above the package), not the core's.
    """
    item = registry.ADAPTORS.get(provider) if isinstance(provider, str) else None
    if item is not None and item.get('source', 'builtin') != 'builtin':
        folder = Path(str(registry.adaptor_files(provider))).resolve()
        depth = registry.adaptor_package(provider).count('.')
        candidates = folder.parents[depth:depth + 2]
    else:
        candidates = [Path(__file__).resolve().parents[2]]
    return next((c for c in candidates if (c/'pyproject.toml').is_file() and (c/'docs').is_dir()), None)


class Audit:
    def __init__(self, root):
        self.root = Path(root).resolve() if root is not None else None
        self.checks = []
        self._file_cache = {}

    def add(self, code, status, message, sources, recovery=None, *, required=True, **details):
        self.checks.append({'code': code, 'status': status, 'message': message,
                            'sources': sources, 'recovery': recovery, 'required': required, **details})
        return status

    def link(self, reference, code, *, local=False):
        """Resolve repo-relative files, Markdown headings and Python symbol suffixes.

        Never fetch remote URLs. Installed wheels need an explicit source root for
        repository delivery checks. Symlink/path escapes are rejected.
        """
        recovery = 'Use an existing repository-relative file/heading/symbol reference.'
        if not isinstance(reference, str) or not reference.strip():
            return self.add(code, 'fail', 'Reference must be a nonempty string.', [], recovery)
        try:
            parsed = urlsplit(reference)
        except ValueError as error:
            return self.add(code, 'fail', str(error), [reference], recovery)
        if parsed.scheme in ('https', 'http') and parsed.netloc:
            if not url_syntax(reference):
                return self.add(code, 'fail', 'Malformed or placeholder upstream URL.', [reference], recovery)
            return self.add(code, 'fail' if local else 'unknown',
                            'A local delivery fixture is required.' if local else 'External reference retained; not fetched.',
                            [reference], 'Supply a local fixture.' if local else 'Review the upstream source separately.', required=local)
        # Python source references use repo/path.py:symbol, not a URL scheme.
        path_text, _, anchor = reference.partition('#')
        path_text, separator, symbol = path_text.partition(':')
        if (not path_text or Path(path_text).is_absolute() or '..' in Path(path_text).parts
                or (parsed.scheme and not (separator and path_text.endswith('.py')))):
            return self.add(code, 'fail', 'Reference must stay inside the repository.', [reference], recovery)
        if self.root is None:
            return self.add(code, 'unknown', 'Repository materials are unavailable in this installation.',
                            [reference], 'Pass --repository-root pointing to the matching source checkout.')
        try:
            path = (self.root/path_text).resolve()
            if not path.is_relative_to(self.root) or not path.is_file():
                raise ValueError('Referenced file is missing or escapes the repository')
            def material():
                if path not in self._file_cache:
                    self._file_cache[path] = {'text': path.read_text()}
                return self._file_cache[path]
            if separator:
                # Legacy provenance may label a line range after a space.
                # Validate the range while retaining the complete attribution.
                if re.match(r'^\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*(?:\s|$)', symbol):
                    symbol = symbol.split()[0]
                if path.suffix == '.json':
                    # Historical provenance names a top-level JSON member.
                    data = material()
                    if 'json' not in data:
                        data['json'] = json.loads(data['text'])
                    if symbol.strip() not in data['json']:
                        raise ValueError('JSON member is absent')
                elif re.fullmatch(r'\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*', symbol):
                    data = material()
                    if 'lineCount' not in data:
                        data['lineCount'] = len(data['text'].splitlines())
                    for section in symbol.split(','):
                        bounds = [int(n) for n in section.split('-')]
                        if not 1 <= bounds[0] <= bounds[-1] <= data['lineCount']:
                            raise ValueError('Source line range is absent')
                else:
                    data = material()
                    if 'symbols' not in data:
                        data['symbols'] = {n.name for n in ast.walk(ast.parse(data['text']))
                                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                    if not symbol or symbol not in data['symbols']:
                        raise ValueError('Python symbol is absent')
            if anchor:
                data = material()
                if path.suffix == '.json':
                    pointer = unquote(anchor)
                    if not pointer.startswith('/') or re.search(r'~(?![01])', pointer):
                        raise ValueError('JSON fragment must be an RFC 6901 pointer')
                    if 'json' not in data:
                        data['json'] = json.loads(data['text'])
                    value = data['json']
                    try:
                        for part in pointer[1:].split('/'):
                            part = part.replace('~1', '/').replace('~0', '~')
                            if isinstance(value, list):
                                if not re.fullmatch('0|[1-9][0-9]*', part):
                                    raise ValueError('Invalid JSON array index')
                                value = value[int(part)]
                            else:
                                value = value[part]
                    except (KeyError, IndexError, TypeError):
                        raise ValueError('JSON fragment is absent')
                else:
                    if 'anchors' not in data:
                        data['anchors'] = markdown_anchors(data['text'])
                    if unquote(anchor) not in data['anchors']:
                        raise ValueError('Markdown heading is absent')
        except (OSError, UnicodeError, SyntaxError, ValueError, RuntimeError) as error:
            return self.add(code, 'fail', str(error), [reference], recovery)
        return self.add(code, 'pass', 'Local reference resolves; contents are not a qualification claim.', [reference])

    def markdown_links(self, reference, code):
        """Inspect local guide navigation as well as the guide's own address."""
        if self.root is None or not isinstance(reference, str):
            return
        path = (self.root / reference.split('#')[0]).resolve()
        if not path.is_relative_to(self.root) or not path.is_file() or path.suffix != '.md':
            return
        for i, target in enumerate(dict.fromkeys(re.findall(r'\]\(([^)]+)\)', path.read_text()))):
            target = target.strip('<>')
            if target.startswith(('mailto:', 'tel:')):
                continue
            try:
                scheme = urlsplit(target).scheme
            except ValueError:
                scheme = 'invalid'
            if scheme:
                self.link(target, code + '.' + str(i))
                continue
            relative, _, anchor = target.partition('#')
            destination = (path.parent / unquote(relative)).resolve() if relative else path
            if not destination.is_relative_to(self.root):
                self.add(code + '.' + str(i), 'fail', 'Guide link escapes repository.', [target])
            else:
                self.link(destination.relative_to(self.root).as_posix() + ('#' + anchor if anchor else ''), code + '.' + str(i))

    def example(self, example, version, code):
        recovery = 'Provide a complete route-matching document and expected valid/invalid outcome; invalid cases need an exact fault code.'
        source = example.get('reference') if isinstance(example, dict) else None
        sources = [source] if isinstance(source, str) else []
        if (not isinstance(example, dict) or set(example) - {'id', 'purpose', 'document', 'reference', 'expect', 'fault', 'schemaValid'}
                or ('schemaValid' in example and type(example['schemaValid']) is not bool)
                or example.get('expect', 'valid') not in ('valid', 'invalid')
                or ('document' in example) == ('reference' in example)
                or ('reference' in example and (not isinstance(source, str) or not source.strip()))
                or (example.get('expect') == 'invalid' and not isinstance(example.get('fault'), str))):
            return self.add(code, 'fail', 'Malformed example contract.', sources, recovery)
        if source is not None and self.link(source, code + '.reference', local=True) != 'pass':
            return self.add(code, 'unknown', 'Example planning could not be checked because its source is unavailable.', sources, recovery)
        try:
            if source is not None and ('#' in source or ':' in source or not source.endswith('.json')):
                raise ValueError('Example references must identify a complete .json file without a suffix')
            document = (load_document((self.root/source).read_text()) if source is not None else copy.deepcopy(example['document']))
            if not isinstance(document, dict) or document.get('version') != version:
                raise ValueError('Example must target this exact document route')
        except (OSError, ValueError, SchemaxisError) as error:
            return self.add(code, 'fail', str(error), sources, recovery)
        try:
            result = registry.plan(document)
            json.dumps(result, allow_nan=False)
        except SchemaxisError as error:
            matched = example.get('expect') == 'invalid' and error.fault.code == example.get('fault')
            return self.add(code, 'pass' if matched else 'fail',
                            'Planner rejected the example with ' + error.fault.code + '.', sources,
                            None if matched else recovery, observedFault=error.to_dict())
        except Exception as error:
            return self.add(code, 'fail', 'Planner raised an unstructured error: ' + str(error), sources, recovery)
        matched = example.get('expect', 'valid') == 'valid'
        return self.add(code, 'pass' if matched else 'fail',
                        'Host planning accepted the example; native correctness is untested.', sources,
                        None if matched else 'Make the invalid fixture exercise a real planner constraint.')


def _load(folder, name):
    path = folder.joinpath(name)
    return load_document(path.read_text()) if path.is_file() else None


def _delivery(audit, folder, manifest):
    source = registry.adaptor_source(manifest['id'], 'readiness.json')
    try:
        value = _load(folder, 'readiness.json')
        if value is None:
            audit.add('delivery.bundle', 'fail', 'No versioned delivery bundle is registered.', [source],
                      'Add readiness.json using docs/adaptor-readiness.md; existing routing remains supported.')
            return {}
        if (not isinstance(value, dict) or set(value) != {'version', 'routes'} or value['version'] != PROTOCOL
                or not isinstance(value['routes'], dict) or set(value['routes']) - set(manifest['routes'])):
            raise ValueError('Expected schemaxis.readiness/1 with only registered routes')
        for version, entry in value['routes'].items():
            if not isinstance(entry, dict) or set(entry) - {'guide', 'context', 'examples', 'conformance', 'acceptance', 'profiles', 'development', 'completion'}:
                raise ValueError('Invalid route delivery fields for ' + version)
        audit.add('delivery.bundle', 'pass', 'Delivery bundle names registered routes.', [source])
        return value['routes']
    except Exception as error:
        audit.add('delivery.bundle', 'fail', 'Malformed delivery bundle: ' + str(error), [source],
                  'Repair the versioned bundle; do not remove failed checks.')
        return {}


def _profiles(audit, manifest, route, entry, source):
    hooks = route.get('hooks', {})
    execution = manifest.get('executionCapabilities', {})
    if (not isinstance(execution, dict) or ('mpi' in execution and type(execution['mpi']) is not bool)
            or not isinstance(execution.get('modes', []), list)
            or any(not isinstance(mode, str) for mode in execution.get('modes', []))):
        audit.add('profiles.flags', 'fail', 'executionCapabilities needs boolean MPI flags and a string-array modes list.',
                  [source], 'Correct the existing executionCapabilities declaration.')
        execution = {}
    mpi_mode = 'mpi' in execution.get('modes', [])
    if execution.get('mpi') is False and (mpi_mode or hooks.get('validateExecution')):
        audit.add('profiles.mpi-conflict', 'fail', 'MPI is explicitly false but a mode or route hook advertises it.',
                  [source], 'Align execution modes, MPI flags and route validation hooks.')
    claims = {
        'workflow': route.get('workflow'),
        'native-inspection': bool(hooks.get('inspect') or hooks.get('inspectionSetup')) or None,
        'composition': route.get('compose'),
        'mpi': True if mpi_mode else execution.get('mpi'),
    }
    profiles = entry.get('profiles', {})
    if not isinstance(profiles, dict) or set(profiles) - set(PROFILES):
        audit.add('profiles.metadata', 'fail', 'Unknown profile or malformed profile metadata.', [source],
                  'Use only the documented profile names with scope and references.')
        profiles = {}
    result = {}
    for name, claim in claims.items():
        # Existing flags/hooks are authoritative, never copied to delivery metadata.
        state = 'declared' if claim is True else 'unsupported' if claim is False else 'unknown'
        result[name] = {'declaration': state, 'qualification': 'unknown'}
        code = 'profile.' + name
        item = profiles.get(name)
        if claim is not True:
            audit.add(code, 'fail' if name in profiles else 'not-applicable',
                      'Profile documentation contradicts or lacks a manifest claim.' if name in profiles
                      else 'No positive profile claim; no obligations applied.', [source],
                      'Align the manifest capability and scoped profile documentation.' if name in profiles else None)
            continue
        if name == 'mpi' and not hooks.get('validateExecution'):
            audit.add(code + '.binding', 'fail', 'MPI is advertised without a route validation hook.', [source],
                      'Supply validateExecution or correct the MPI advertisement.')
        if (not isinstance(item, dict) or set(item) != {'scope', 'references'}
                or not isinstance(item.get('scope'), str) or not item['scope'].strip()
                or not isinstance(item.get('references'), list) or not item['references']):
            audit.add(code, 'fail', 'Declared profile lacks scoped supporting references.', [source],
                      'Document the supported subset, limitations and conformance/acceptance references for this profile.')
            continue
        audit.add(code, 'pass', item['scope'], [source])
        for i, reference in enumerate(item['references']):
            audit.link(reference, code + '.reference.' + str(i), local=True)
    accepted = route.get('acceptedArtifacts', [])
    valid = isinstance(accepted, list) and all(isinstance(k, str) and k.strip() for k in accepted)
    valid = valid and (not accepted or route.get('workflow') is True)
    audit.add('profiles.artifacts', 'pass' if valid else 'fail',
              'Incoming artifact kinds are structurally consistent.' if valid else 'Incoming artifacts require a workflow route and string kinds.',
              [source], None if valid else 'Correct acceptedArtifacts and the workflow claim.', acceptedArtifacts=accepted)
    audit.add('contracts.artifact-traits', 'unknown' if accepted else 'not-applicable',
              'Kind labels do not establish formats, units, losses or consumer compatibility.' if accepted else 'No incoming artifact kinds declared.',
              [source], 'Review typed handoff traits on real fixtures.' if accepted else None, required=False)
    return result


def _context(audit, entry, source):
    context = entry.get('context', {})
    if not isinstance(context, dict) or set(context) - set(CONTEXT):
        audit.add('context.structure', 'fail', 'Context must use the documented fields.', [source], 'Repair the context object.')
        context = {}
    for key in CONTEXT:
        good = isinstance(context.get(key), str) and bool(context[key].strip())
        audit.add('context.' + key, 'pass' if good else 'fail',
                  context[key] if good else 'Missing curated ' + key + ' guidance.', [source],
                  None if good else 'Describe route-specific ' + key + '; field names alone are insufficient.')
    audit.link(entry.get('guide'), 'delivery.guide', local=True)
    examples = entry.get('examples', [])
    if not isinstance(examples, list):
        examples = []
    for outcome in ('valid', 'invalid'):
        present = any(isinstance(e, dict) and e.get('expect', 'valid') == outcome for e in examples)
        audit.add('delivery.example.' + outcome, 'pass' if present else 'fail',
                  'An example is supplied; its planning outcome is checked separately.' if present else 'No ' + outcome + ' fixture.',
                  [source], None if present else 'Add a meaningful ' + outcome + ' planner fixture.')
    ids = set()
    for i, example in enumerate(examples):
        identity = example.get('id') if isinstance(example, dict) else None
        if not isinstance(identity, str) or not re.fullmatch('[a-z][a-z0-9-]*', identity) or identity in ids:
            audit.add('examples.identity.' + str(i), 'fail', 'Examples need unique stable slug IDs.', [source], 'Assign a unique example ID.')
            identity = str(i)
        ids.add(identity)
        audit.example(example, audit.version, 'examples.' + identity)
    for key in ('conformance', 'acceptance'):
        references = entry.get(key)
        if not isinstance(references, list) or not references:
            audit.add('delivery.' + key, 'fail', 'Missing ' + key + ' recipe/test references.', [source],
                      'Link maintained host tests or a bounded native acceptance recipe as appropriate.')
        else:
            for i, reference in enumerate(references):
                audit.link(reference, 'delivery.' + key + '.' + str(i), local=True)


def _contracts(audit, provider, manifest, version, route, source):
    try:
        module = import_module(route['module'])
        for name in ('plan', 'run', 'verify'):
            value = registry.binding(route['hooks']['verify']) if name == 'verify' and route.get('hooks', {}).get('verify') else getattr(module, name, None)
            audit.add('contracts.' + name, 'pass' if callable(value) else 'fail',
                      'Host entry point resolves; runtime behaviour is untested.' if callable(value) else 'Required callable is missing.',
                      [route['module'] + ':' + name], None if callable(value) else 'Implement the route entry point.')
        for name, path in route.get('hooks', {}).items():
            if not callable(registry.binding(path)):
                raise ValueError('Hook is not callable: ' + name)
        schema = registry.binding(route['schema'])()
        if not isinstance(schema, dict) or schema.get('properties', {}).get('version', {}).get('const') != version:
            raise ValueError('Route schema must declare its exact document version')
        json.dumps(schema, allow_nan=False)
        audit.add('contracts.schema', 'pass', 'Schema is JSON-serialisable and declares the routed document version.', [route['schema']])
    except Exception as error:
        audit.add('contracts.schema', 'fail', str(error), [source], 'Repair the route schema or entry-point binding.')
    if version != manifest['version']:
        audit.add('contracts.operations', 'not-applicable', 'Secondary route uses its own document schema; primary operation declarations are not attributed to it.', [route['schema']])
        return
    declaration_checked = False
    try:
        declarations = registry.declarations(provider)
        if not isinstance(declarations, dict) or not declarations:
            raise ValueError('Primary route needs nonempty operation declarations')
        for name, declaration in declarations.items():
            if not isinstance(declaration, dict) or not isinstance(declaration.get('inputs'), dict) or not declaration.get('native'):
                raise ValueError('Operation lacks inputs or native binding: ' + name)
            for port in declaration['inputs'].values():
                if not isinstance(port, dict) or any(key in port and type(port[key]) is not bool for key in ('required', 'multiple')):
                    raise ValueError('Malformed input port: ' + name)
            kinds = declaration.get('kinds', ['data'])
            if not isinstance(kinds, list) or not kinds or any(not isinstance(k, str) or not k for k in kinds):
                raise ValueError('Malformed output kinds: ' + name)
            option_schema(declaration)
        audit.add('contracts.operations', 'pass', 'Primary declarations and typed option schemas resolve.', [manifest['declarations']], operationCount=len(declarations))
        declaration_checked = True
        catalogue = CapabilityCatalogue([provider])
        metadata = catalogue._metadata[provider]
        operations = metadata.get('operations', {})
        missing = sorted(name for name in declarations if not operations.get(name, {}).get('purpose', '').strip())
        audit.add('context.operations', 'fail' if missing else 'pass',
                  'Operations missing curated selection guidance.' if missing else 'Every primary operation has curated purpose text.',
                  [manifest.get('capabilities', manifest['declarations'])],
                  'Add purpose metadata to the existing capability catalogue.' if missing else None, missingOperations=missing)
        for i, reference in enumerate(metadata.get('references', [])):
            audit.link(reference, 'context.reference.' + str(i))
        for name, operation in operations.items():
            for i, example in enumerate(operation.get('examples', [])):
                audit.example(example, version, 'context.example.' + name + '.' + str(i))
    except Exception as error:
        audit.add('context.metadata' if declaration_checked else 'contracts.operations', 'fail', str(error), [manifest['declarations']],
                  'Repair declarations or capability metadata without weakening validation.')


def _qualification(audit, folder, source):
    try:
        upstream = _load(folder, 'upstream.json')
        if not isinstance(upstream, dict) or not isinstance(upstream.get('evidence'), list) or not upstream['evidence']:
            raise ValueError('No historical qualification evidence is registered')
        for i, reference in enumerate(upstream['evidence']):
            audit.link(reference, 'qualification.reference.' + str(i), local=True)
        historic = {'attribution': 'provider-wide historical metadata; route/profile applicability unreviewed',
                    **{k: upstream.get(k) for k in ('absorbedVersion', 'scope', 'evidence', 'acceptance')}}
    except Exception as error:
        historic = None
        audit.add('qualification.references', 'unknown', str(error), [source], 'Link bounded historical acceptance evidence in upstream.json.', required=False)
    audit.add('qualification.current', 'unknown', 'Historical receipts are not fresh route/profile/runtime qualification.', [source],
              'Run bounded native acceptance and record exact route, fixtures, runtime and scope.', required=False)
    return historic


def _completion(audit, provider, manifest, version, entry, folder):
    """Objective completion obligations extend the existing opt-in admission."""
    source = registry.adaptor_source(provider, 'readiness.json')
    review = entry.get('completion', {})
    features = entry.get('development', {}).get('features', {})
    valid = (isinstance(review, dict) and set(review) <= {'scope', 'review', 'notApplicable'}
             and isinstance(review.get('scope'), str) and review['scope'].strip()
             and not review['scope'].strip().lower().startswith(('todo', 'tbd'))
             and isinstance(review.get('review'), list) and bool(review['review'])
             and isinstance(review.get('notApplicable', {}), dict))
    if valid:
        for feature, reason in review.get('notApplicable', {}).items():
            valid = valid and features.get(feature, {}).get('status') == 'unsupported' and isinstance(reason, str) and bool(reason.strip())
    audit.add('completion.review', 'pass' if valid else 'unknown',
              'Scoped review evidence supplied; prose and domain correctness still require review.' if valid else 'No valid scoped completion review/exception record.', [source],
              'Retain scope, review references and justified unsupported feature exceptions; see docs/adaptor-completion.md.')
    if valid:
        for i, reference in enumerate(review['review']):
            audit.link(reference, 'completion.review.' + str(i), local=True)
    audit.markdown_links(entry.get('guide'), 'delivery.guide.link')
    for i, reference in enumerate(entry.get('development', {}).get('api', [])):
        audit.link(reference, 'delivery.api.' + str(i))
    try:
        from .studio_library import load_library, instantiate_item, plan_item
        if not folder.joinpath('studio.json').is_file():
            raise ValueError('studio.json is missing')
        library = load_library(provider)
        if library.get('helpGuide'):
            audit.link(library['helpGuide'], 'studio.help.guide', local=True)
        if not library.get('templates'):
            raise ValueError('Supply an editable Studio starter')
        for item in library.get('templates', []) + library.get('snippets', []):
            plan_item(instantiate_item(library, item, provider=provider))
        audit.add('studio.library', 'pass', 'Validated library and filled recipes plan; native availability and prose quality are untested.', [str(folder.joinpath('studio.json'))])
    except Exception as error:
        audit.add('studio.library', 'fail', str(error), [str(folder.joinpath('studio.json'))], 'Complete and host-test Studio metadata and starter prerequisites.')
    try:
        from .studio_catalogue import catalogue
        from .search_acceptance import check_cases
        discovery = CapabilityCatalogue([provider])
        metadata = discovery._metadata[provider]
        app = metadata.get('application', {})
        useful = bool(app.get('purpose', '').strip()) and not app.get('purpose', '').strip().lower().startswith('todo')
        audit.add('discovery.application', 'pass' if useful else 'unknown', 'Curated application purpose supplied.' if useful else 'Application selection lacks curated purpose.', [manifest.get('capabilities', source)], 'Author application-level purpose and terms in the capability binding.')
        if version == manifest['version']:
            terms = [name for name in registry.declarations(provider) if not metadata.get('operations', {}).get(name, {}).get('keywords')]
            audit.add('discovery.terms', 'unknown' if terms else 'pass', 'Operations without curated search terms: ' + str(len(terms)), [manifest.get('capabilities', source)], 'Review domain terms, verbs, synonyms and native names per operation; avoid shared keyword stuffing.', missingOperations=terms)
            cases = check_cases(discovery, provider)
            audit.add('discovery.acceptance', 'pass' if cases['complete'] else 'unknown', cases['scope'], [manifest.get('capabilities', source)], 'Complete adaptor-owned cases and run CLI/agent and Studio regressions.', **cases)
        additions = catalogue(provider, version)
        covered = {i['operation'] for i in additions['items'] if i.get('operation')}
        missing = sorted(set(registry.declarations(provider)) - covered) if version == manifest['version'] else []
        audit.add('studio.add', 'fail' if missing or not additions['items'] else 'pass', 'Literal route authoring projected; contextual Help remains separate.', [manifest.get('studioCatalogue', source)], missingOperations=missing)
        index_path = files('schemaxis').joinpath('studio_ui/help/index.json')
        index = json.loads(index_path.read_text())
        topics = {(e.get('provider'), e.get('operation')): e for e in index['entries']}
        missing_help = [n for n in registry.declarations(provider) if (provider, n) not in topics] if version == manifest['version'] else []
        guide = entry.get('guide', '').partition('#')[0]
        guide_found = any(e['source'] == guide for e in index['entries'])
        target_ids = {topics[(provider, n)]['id'] for n in covered if (provider, n) in topics}
        targets_exist = all(files('schemaxis').joinpath('studio_ui/help/' + identity + '.json').is_file() for identity in target_ids)
        audit.add('studio.help', 'pass' if guide_found and not missing_help and targets_exist else 'fail', 'Packaged guide and operation targets checked; run generated-output --check for freshness.', [str(index_path)], 'Regenerate references and packaged Help; every operation needs its own topic.', missingOperations=missing_help)
    except Exception as error:
        audit.add('completion.metadata', 'fail', str(error), [source], 'Repair metadata or projection; keep discovery host-only.')


def report(providers=None, *, root=None, admission=False):
    """Audit trusted installed adaptors. Does not install, execute or probe native apps."""
    explicit = root
    rows = []
    for provider in sorted(registry.ADAPTORS if providers is None else set(providers)):
        root = repository_root(provider) if explicit is None else explicit
        manifest = registry.metadata(provider)
        folder = registry.adaptor_files(provider)
        provider_audit = Audit(root)
        delivery = _delivery(provider_audit, folder, manifest)
        historic = _qualification(provider_audit, folder, registry.adaptor_source(provider, 'upstream.json'))
        from .studio_guidance import audit as guidance_audit
        try:
            conceptual = guidance_audit(provider, root=root)
            provider_audit.add('studio.guidance', 'pass' if conceptual['complete'] else 'unknown',
                'Conceptual guidance coverage: ' + str(conceptual['counts']),
                [registry.adaptor_source(provider, 'guidance.json')],
                'Complete pending records and remove stale addresses using tools/studio_guidance.py.',
                required=admission, counts=conceptual['counts'], stale=conceptual['stale'], linkIssues=conceptual['linkIssues'])
        except SchemaxisError as error:
            provider_audit.add('studio.guidance', 'fail', str(error),
                [registry.adaptor_source(provider, 'guidance.json')], required=admission)
        for version, route in sorted(manifest['routes'].items()):
            audit = Audit(root)
            audit.version = version
            audit.checks = copy.deepcopy(provider_audit.checks)
            source = registry.adaptor_source(provider, 'adaptor.json')
            ready_source = registry.adaptor_source(provider, 'readiness.json')
            entry = delivery.get(version, {})
            identity_known = all(isinstance(manifest.get(k), str) and manifest[k].strip()
                                 for k in ('runtimeFamily', 'execution'))
            identity_known = identity_known and manifest['runtimeFamily'] != 'unspecified' and manifest['execution'] != 'adaptor-defined execution'
            audit.add('contracts.identity', 'pass' if identity_known else 'fail',
                      'Runtime family and bounded execution scope are declared.' if identity_known else 'Runtime family or execution scope is unspecified.',
                      [source], None if identity_known else 'Declare runtimeFamily and a bounded execution scope in adaptor.json.')
            _contracts(audit, provider, manifest, version, route, source)
            _context(audit, entry, ready_source)
            profiles = _profiles(audit, manifest, route, entry, source)
            if admission or 'development' in entry:
                from .adaptor_delivery import validate_development
                try:
                    validate_development(version, entry)
                    audit.add('delivery.development', 'pass', 'Development decisions and bounded acceptance recipes are structurally complete.', [ready_source])
                except Exception as error:
                    audit.add('delivery.development', 'fail', str(error), [ready_source],
                              'Complete the development contract in docs/adaptor-development.md; do not claim untested optional features.')
            if admission:
                _completion(audit, provider, manifest, version, entry, folder)
            audit.add('lifecycle.behaviour', 'unknown', 'Timeout, cancellation, retained logs and independent verification require behavioural conformance.',
                      [route['module']], 'Run scoped host conformance and native acceptance; callable presence is insufficient.', required=False)
            counts = {status: sum(c['status'] == status for c in audit.checks) for status in ('pass', 'fail', 'unknown', 'not-applicable')}
            counts['requiredUnknown'] = sum(c['status'] == 'unknown' and c['required'] for c in audit.checks)
            identity = 'route/' + provider + '/' + quote(version, safe='')
            for check in audit.checks:
                check['id'] = identity + '/' + check['code']
                if not check['sources']:
                    check['sources'] = [ready_source]
            rows.append({'id': identity, 'provider': provider, 'documentVersion': version,
                         'documentModel': 'non-node' if route.get('graphEditing') is False else 'node',
                         'structural': 'incomplete' if counts['fail'] or counts['requiredUnknown'] else 'complete',
                         'implementation': {
                             'entryPoints': 'present' if all(any(c['code'] == 'contracts.' + name and c['status'] == 'pass'
                                                                 for c in audit.checks) for name in ('plan', 'run', 'verify')) else 'incomplete',
                             'behaviour': 'unreviewed'},
                         'runtimeAvailability': 'unknown', 'nativeQualification': 'unknown',
                         'documentationCompleteness': {'coverage': ('incomplete' if any(c['required'] and c['status'] in ('fail', 'unknown') and c['code'].startswith(('studio.', 'discovery.', 'completion.')) for c in audit.checks) else 'complete') if admission else 'unknown', 'editorialReview': 'unreviewed'},
                         'profiles': profiles, 'historicalQualification': historic,
                         'counts': counts, 'checks': audit.checks})
    gaps = [{'route': row['id'], 'failures': row['counts']['fail'], 'unknowns': row['counts']['unknown'],
             'requiredUnknowns': row['counts']['requiredUnknown'],
             'checks': [c['id'] for c in row['checks'] if c['status'] == 'fail' or (c['status'] == 'unknown' and c['required'])]} for row in rows]
    gaps.sort(key=lambda row: (-row['failures'], -row['unknowns'], row['route']))
    return {'protocol': PROTOCOL, 'scope': 'Host structural admission only; no native execution, availability probes or new qualification.',
            'repositoryRoot': str(root) if root is not None else None,
            'routes': rows, 'gaps': gaps,
            'structurallyComplete': all(row['structural'] == 'complete' for row in rows)}


def enforce(result):
    """Opt-in gate; never change legacy registration or discovery behaviour."""
    if not result['structurallyComplete']:
        fail('ADAPTOR_NOT_READY', 'Required structural admission checks failed; inspect the readiness report.',
             'readiness', report=result)
    return result
