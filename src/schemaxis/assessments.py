"""Scoped editorial strength assessments owned by registered adaptor packages.

This is a projection of the existing registry, never an alternative registry or a
runtime probe. Percentages describe judgements, not qualification or API counts.
"""
import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import PurePosixPath
import re

from .adaptors import registry
from .core.documents import load_document
from .core.faults import Fault, SchemaxisError

PROTOCOL = 'schemaxis.adaptor-assessment/1'
REPORT = 'schemaxis.adaptor-assessments/1'
RUBRIC = 'schemaxis.strength-rubric/1'
SOURCE_SCOPE = ('All adaptor-owned resource files regardless of extension; excludes assessment, '
                'readiness, qualification, upstream, Studio/guidance metadata, caches, '
                'tests, guides outside the adaptor package and shared framework code. Adaptor-local guides are included. A matching fingerprint '
                'detects no change in this scope; it does not prove semantic or native freshness.')
RUBRIC_DESCRIPTION = {
    'id': RUBRIC,
    'status': 'subjective editorial estimates; rounded to five percentage points',
    'coverage': {'scope': 'whole-application',
        'meaning': 'Estimated breadth of useful application functionality expressible through all assessed routes, against the named functional families; not native API enumeration.',
        'anchors': {'0': 'No useful application workflow covered.',
                    '25': 'A few useful workflow families, with major application areas missing.',
                    '50': 'Several central families, with substantial gaps.',
                    '75': 'Most central workflows, with specialist gaps.',
                    '100': 'Essentially complete useful application breadth; requires exceptional justification.'}},
    'abstraction': {'scope': 'declared-workflows',
        'meaning': 'How well the supported workflows express user intent and decisions rather than native procedural details. This denominator is the explicitly named supported slice, not the whole application.',
        'anchors': {'0': 'Raw native procedures and configuration dominate.',
                    '25': 'Thin typed wrappers; users assemble most domain decisions.',
                    '50': 'Reusable domain operations with explicit units and constraints; substantial manual composition.',
                    '75': 'Workflow intent, defaults, requirements and useful deliverables; some native detail remains.',
                    '100': 'Complete supported task intent with coherent decisions and handoffs; no material native plumbing exposed.'}},
    'comparison': 'Compare like scopes and rubric versions. Scores are ordinal planning aids, not measured ratios, promises or an overall quality rank. Do not average them across unlike applications.',
    'independentAxes': 'Verification confidence, local runtime availability and source-bound qualification are separate readiness facts; tests and operation counts are evidence, not score denominators.'}


def _text(value):
    return (isinstance(value, str) and bool(value.strip())
            and re.match(r'(?:TODO|TBD)\b', value.lstrip(), re.IGNORECASE) is None)


def _latest_civil_day():
    """Latest current civil date worldwide, without assuming the user's zone."""
    return (datetime.now(timezone.utc) + timedelta(hours=14)).date()


def source_fingerprint(provider):
    """Portable identity of declared adaptor source, including plugin resources."""
    registry.metadata(provider)
    ignored = {'assessment.json', 'readiness.json', 'qualification.json', 'upstream.json',
               'guidance.json', 'studio.json', '.DS_Store'}
    ignored_folders = {'__pycache__', 'studio', 'tests', '.pytest_cache',
                       '.git', '.hg', '.svn', 'node_modules'}
    records = {}
    def visit(folder, prefix=''):
        for path in sorted(folder.iterdir(), key=lambda p: p.name):
            name = prefix + path.name
            if path.is_dir():
                if path.name not in ignored_folders:
                    visit(path, name + '/')
            elif path.name not in ignored and not path.name.endswith(('.pyc', '.pyo')):
                records[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    visit(registry.adaptor_files(provider))
    return 'sha256:' + hashlib.sha256(json.dumps(records, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate(value, provider):
    """Validate metadata without fetching references or importing native code."""
    registry.metadata(provider)
    location = provider + ':assessment.json'
    def require(condition, message, field=''):
        if not condition:
            raise SchemaxisError(Fault('INVALID_ASSESSMENT', message,
                location + (':' + field if field else ''), 'discovery',
                recovery='Repair the adaptor-owned assessment metadata; execution contracts are unchanged.'))
    require(isinstance(value, dict) and set(value) == {
        'version', 'rubric', 'assessmentVersion', 'assessedOn', 'assessor',
        'provider', 'providerVersion', 'routes', 'sourceFingerprint',
        'coverage', 'abstraction', 'evidence', 'limitations'}, 'assessment fields do not match the contract')
    require(value['version'] == PROTOCOL and value['rubric'] == RUBRIC, 'unsupported assessment or rubric version')
    require(value['provider'] == provider, 'assessment must belong to its registered provider', 'provider')
    require(_text(value['providerVersion']) and _text(value['assessmentVersion']) and _text(value['assessor']),
            'providerVersion, assessmentVersion and assessor require nonempty text')
    try:
        require(isinstance(value['assessedOn'], str) and date.fromisoformat(value['assessedOn']).isoformat() == value['assessedOn'],
                'assessedOn must use YYYY-MM-DD', 'assessedOn')
        require(date.fromisoformat(value['assessedOn']) <= _latest_civil_day(),
                'assessedOn cannot be later than the current civil date in every timezone', 'assessedOn')
    except (ValueError, TypeError):
        require(False, 'assessedOn must use YYYY-MM-DD', 'assessedOn')
    require(isinstance(value['routes'], list) and bool(value['routes'])
            and all(_text(v) for v in value['routes']) and len(set(value['routes'])) == len(value['routes']),
            'routes require distinct assessed document versions', 'routes')
    # Old removed routes are retained as historical assessment scope and make the
    # record stale below. They never register or authorise routes themselves.
    require(isinstance(value['sourceFingerprint'], str) and re.fullmatch(r'sha256:[0-9a-f]{64}', value['sourceFingerprint']),
            'sourceFingerprint must be a SHA-256 source identity', 'sourceFingerprint')
    for dimension, kind in (('coverage', 'whole-application'), ('abstraction', 'declared-workflows')):
        metric = value[dimension]
        require(isinstance(metric, dict) and set(metric) == {'percent', 'status', 'scope', 'rationale', 'confidence'},
                'metric requires percent, status, scope, rationale and confidence', dimension)
        require(type(metric['percent']) is int and 0 <= metric['percent'] <= 100 and metric['percent'] % 5 == 0,
                'use a whole percentage from 0 to 100 rounded to five points', dimension + '.percent')
        require(metric['status'] == 'subjective', 'this rubric defines subjective estimates', dimension + '.status')
        require(metric['confidence'] in ('low', 'medium', 'high') and _text(metric['rationale']),
                'state confidence in the estimate and a substantive rationale', dimension)
        scope = metric['scope']
        require(isinstance(scope, dict) and set(scope) == {'kind', 'description', 'denominator'}
                and scope['kind'] == kind and _text(scope['description']) and _text(scope['denominator']),
                'scope needs its explicit kind, description and denominator', dimension + '.scope')
    for key in ('evidence', 'limitations'):
        require(isinstance(value[key], list) and bool(value[key]) and all(_text(v) for v in value[key]),
                key + ' must contain nonempty references or limitations', key)
    for reference in value['evidence']:
        path = PurePosixPath(reference)
        require(not path.is_absolute() and '..' not in path.parts and '\\' not in reference and ':' not in reference,
                'evidence must use portable repository-relative references', 'evidence')
    return copy.deepcopy(value)


def assessment(provider):
    """Return a record or explicit absence; stale estimates remain labelled."""
    manifest = registry.metadata(provider)
    try:
        path = registry.adaptor_files(provider).joinpath('assessment.json')
        if not path.is_file():
            return {'status': 'missing', 'record': None,
                    'reason': 'This registered provider has no editorial assessment.'}
        value = validate(load_document(path.read_text()), provider)
        observed = source_fingerprint(provider)
    except (SchemaxisError, ValueError, TypeError, RecursionError, UnicodeError, OSError, ImportError) as error:
        # Editorial metadata never excludes a provider or changes its executable
        # contracts. Malformed metadata stays visible as an independent axis.
        fault = (error.fault if isinstance(error, SchemaxisError) and error.fault.code == 'INVALID_ASSESSMENT'
                 else Fault('INVALID_ASSESSMENT', 'assessment metadata or its source identity could not be read',
                            provider + ':assessment.json', 'discovery',
                            recovery='Repair the adaptor-owned assessment; provider planning and execution remain available.'))
        return {'status': 'invalid', 'record': None, 'fault': fault.to_dict()}
    reasons = []
    if value['sourceFingerprint'] != observed:
        reasons.append('Adaptor implementation resources changed after assessment.')
    if value['providerVersion'] != manifest['version'] or set(value['routes']) != set(manifest['routes']):
        reasons.append('Registered document versions or route inventory changed after assessment.')
    return {'status': 'stale' if reasons else 'current', 'record': value,
            'freshness': {'observedSourceFingerprint': observed, 'scope': SOURCE_SCOPE,
                          'reasons': reasons}}


def summary(value):
    """Compact catalogue/discovery link; the full query retains all qualifications."""
    record = value['record']
    result = {'status': value['status'], 'command': ['schemaxis', 'assessments']}
    if value.get('fault'):
        result['fault'] = copy.deepcopy(value['fault'])
    if record is not None:
        result.update(coveragePercent=record['coverage']['percent'],
                      coverageScope=record['coverage']['scope']['kind'],
                      abstractionPercent=record['abstraction']['percent'],
                      abstractionScope=record['abstraction']['scope']['kind'],
                      estimateStatus='subjective', assessedOn=record['assessedOn'])
        result['command'].extend(['--app', record['provider']])
    return result


def report(providers=None):
    """Aggregate installed/registered providers, never executable availability."""
    selected = sorted(registry.ADAPTORS if providers is None else set(providers))
    entries = []
    for provider in selected:
        manifest = registry.metadata(provider)
        value = assessment(provider)
        entries.append({'id': provider, 'source': manifest.get('source', 'builtin'),
            'label': manifest.get('display', {}).get('name', provider),
            'routes': sorted(manifest['routes']), 'routeCount': len(manifest['routes']),
            'assessment': value,
            'verification': {'runtimeAvailability': 'not checked',
                'qualification': 'not evaluated by the strength query',
                'readinessCommand': ['schemaxis', 'readiness', '--app', provider],
                'scope': 'Estimate confidence is editorial confidence, not native verification confidence.'}})
    result = {'version': REPORT, 'providerCount': len(entries),
        'routeCount': sum(v['routeCount'] for v in entries),
        'selection': {'mode': 'all' if providers is None else 'providers', 'providers': selected},
        'inventoryScope': 'Registered providers in this process, including enabled installed plugins. Routes are authorable document versions, not additional applications. Executable installations were not probed.',
        'rubric': copy.deepcopy(RUBRIC_DESCRIPTION),
        'counts': {status: sum(v['assessment']['status'] == status for v in entries)
                   for status in ('current', 'stale', 'missing', 'invalid')}, 'providers': entries}
    if registry.PLUGIN_FAULTS:
        result['pluginFaults'] = [f.to_dict() for f in registry.PLUGIN_FAULTS]
    return result


def human_summary(value):
    lines = [f"{value['providerCount']} registered application providers; {value['routeCount']} authorable routes.",
        'Subjective percentages: whole-application breadth / abstraction within declared workflows.',
        'Five-point estimates; confidence, rationale, denominators and evidence are in the JSON query.',
        'Runtime availability and native qualification are separate; neither was checked here.', '',
        'Provider | Routes | Breadth | Abstraction | Assessment']
    for entry in value['providers']:
        item = entry['assessment']; record = item['record']
        scores = (str(record['coverage']['percent']) + '%', str(record['abstraction']['percent']) + '%') if record else ('unknown', 'unknown')
        lines.append(f"{entry['id']} | {entry['routeCount']} | {scores[0]} | {scores[1]} | {item['status']}")
    lines.extend(['', 'High abstraction in a narrow workflow does not imply broad application coverage.',
                  'Inspect a provider: schemaxis assessments --app PROVIDER'])
    return '\n'.join(lines) + '\n'


def compare(current, baseline):
    """Compare saved estimates only when both metric denominators are unchanged."""
    def require(condition):
        if not condition:
            raise SchemaxisError(Fault('INVALID_ASSESSMENT_BASELINE',
                'use a complete assessments JSON report with unique provider identities and valid scoped estimates',
                'baseline', 'discovery', recovery='Select a saved schemaxis assessments JSON report.'))
    require(isinstance(baseline, dict) and baseline.get('version') == REPORT
            and isinstance(baseline.get('providers'), list)
            and isinstance(baseline.get('rubric'), dict))
    previous = {}
    for entry in baseline['providers']:
        require(isinstance(entry, dict) and _text(entry.get('id')) and entry['id'] not in previous
                and isinstance(entry.get('assessment'), dict))
        record = entry['assessment'].get('record')
        require(record is None or isinstance(record, dict))
        if record is not None:
            require(record.get('provider') == entry['id'] and _text(record.get('assessmentVersion')))
            for dimension in ('coverage', 'abstraction'):
                metric = record.get(dimension)
                require(isinstance(metric, dict) and type(metric.get('percent')) is int
                        and 0 <= metric['percent'] <= 100 and metric['percent'] % 5 == 0
                        and metric.get('status') == 'subjective' and isinstance(metric.get('scope'), dict)
                        and set(metric['scope']) == {'kind', 'description', 'denominator'}
                        and all(_text(v) for v in metric['scope'].values()))
        previous[entry['id']] = entry
    baseline_selection = baseline.get('selection')
    require(isinstance(baseline_selection, dict)
                and set(baseline_selection) == {'mode', 'providers'}
                and baseline_selection['mode'] in ('all', 'providers')
                and isinstance(baseline_selection['providers'], list)
                and all(_text(provider) for provider in baseline_selection['providers'])
                and len(set(baseline_selection['providers'])) == len(baseline_selection['providers'])
                and set(baseline_selection['providers']) == set(previous))
    now = {entry['id']: entry for entry in current['providers']}
    # Selection is query provenance, never evidence that an unrequested provider
    # disappeared. Selection provenance is required; an incomplete snapshot must
    # never masquerade as evidence of added or removed providers.
    selection = copy.deepcopy(current['selection'])
    baseline_not_selected = []
    if selection['mode'] == 'providers':
        baseline_not_selected = sorted(set(previous) - set(selection['providers']))
        previous = {provider: entry for provider, entry in previous.items()
                    if provider in selection['providers']}
    current_not_selected = []
    if baseline_selection['mode'] == 'providers':
        current_not_selected = sorted(set(now) - set(baseline_selection['providers']))
        now = {provider: entry for provider, entry in now.items()
               if provider in baseline_selection['providers']}
    changes = []
    for provider in sorted(set(previous) | set(now)):
        old = previous.get(provider); new = now.get(provider)
        item = {'id': provider, 'inventoryChange': 'added' if old is None else 'removed' if new is None else 'retained'}
        before = old['assessment'].get('record') if old else None
        after = new['assessment'].get('record') if new else None
        for dimension in ('coverage', 'abstraction'):
            comparable = (before is not None and after is not None
                          and baseline['rubric'].get('id') == current['rubric']['id']
                          and before[dimension]['scope'] == after[dimension]['scope'])
            item[dimension] = {'beforePercent': before[dimension]['percent'] if before else None,
                'afterPercent': after[dimension]['percent'] if after else None,
                'comparable': comparable,
                'deltaPoints': after[dimension]['percent'] - before[dimension]['percent'] if comparable else None}
        if old and new:
            item['assessmentStatus'] = new['assessment']['status']
            item['assessmentVersionChanged'] = bool(before and after and before['assessmentVersion'] != after['assessmentVersion'])
        changes.append(item)
    return {'scope': 'Score changes are subjective estimate changes, not measured functional progress. Deltas require identical rubric and metric scope; stale estimates retain their stale label. Filtered snapshots compare only mutually selected providers; unselected providers are neither removals nor additions. Baselines require explicit selection provenance.',
            'selection': {'current': selection,
                          'baseline': copy.deepcopy(baseline_selection),
                          'baselineNotSelected': baseline_not_selected,
                          'currentNotSelectedInBaseline': current_not_selected},
            'providers': changes}
