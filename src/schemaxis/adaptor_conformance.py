# Copyright (C) 2026 David L F Gaden
"""Reusable developer conformance and bounded native acceptance.

Native execution is opt-in and only uses installed route entry points. Expected
values are literal reviewed fixtures, never derived from the producer's result.
Failure receipts are retained; no result flag can promote a failed check.
"""
import copy
import json
import math
import sys
from pathlib import Path
import threading
from datetime import datetime, timezone

from .adaptors import registry
from .adaptor_delivery import (case_document, case_document_digest, example_document, local_path,
                               route_materials, source_digest, validate_development, validate_receipt)
from .artifacts import atomic_json, file_digest
from .capabilities import digest
from .core.documents import load_document
from .core.faults import SchemaxisError, Fault
from .core.runners import Interpreter
from .dispatch import allocation, SubprocessRunner
from .errors import fail
from .observations import at_pointer
from .readiness import repository_root
from .schema import argument_schema, export_schema
from .tabular import close, read_csv

PROTOCOL = 'schemaxis.adaptor-qualification/1'


def host(version, *, root=None):
    """Developer-only schema checks; jsonschema is not a host runtime dependency."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        fail('CONFORMANCE_DEPENDENCY_UNAVAILABLE', 'install the optional jsonschema developer dependency before conformance')
    provider, route, entry = route_materials(version)
    root = repository_root(provider) if root is None else Path(root)
    dev = validate_development(version, entry)
    schema = export_schema(version=version, authored=True)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    checks = []
    def require(value, message):
        if not value:
            fail('CONFORMANCE_FAILED', message, version)
        checks.append(message)
    for example in entry['examples']:
        document = example_document(entry, example['id'], root)
        expected = example.get('expect', 'valid')
        before = digest(document)
        errors = list(validator.iter_errors(document))
        schema_valid = example.get('schemaValid', True)
        require((not errors) == schema_valid, 'schema expectation: ' + example['id'])
        try:
            prepared = registry.plan(document)
        except SchemaxisError as error:
            require(expected == 'invalid' and error.fault.code == example.get('fault'), 'exact invalid fault: ' + example['id'])
        else:
            require(expected == 'valid', 'valid plan: ' + example['id'])
            require(digest(registry.plan(document)) == digest(prepared), 'deterministic planning: ' + example['id'])
        require(digest(document) == before, 'planner preserves caller input: ' + example['id'])
    # A universal structural adversary catches schema/parser envelope drift.
    document = example_document(entry, dev['authoring']['example'], root)
    document['__undeclared_admission_field__'] = True
    require(not validator.is_valid(document), 'schema rejects an undeclared root field')
    try:
        registry.plan(document)
    except SchemaxisError:
        checks.append('planner rejects an undeclared root field with a structured fault')
    else:
        fail('CONFORMANCE_FAILED', 'planner accepts undeclared root fields', version)
    plans = set()
    for case in dev['cases']:
        document = case_document(entry, case, root)
        require(validator.is_valid(document), 'acceptance case matches authored schema: ' + case['id'])
        prepared = registry.plan(document)
        plans.add(digest(prepared))
    require(len(plans) >= 2, 'baseline and held-out case produce distinct effective plans')
    if version == registry.metadata(provider)['version']:
        for name, declaration in registry.declarations(provider).items():
            for option, binding in declaration['options'].items():
                specification = binding['value']
                if 'default' in specification:
                    require(Draft202012Validator(argument_schema(specification)).is_valid(specification['default']),
                            'typed default: ' + name + '.' + option)
    return {'verified': True, 'scope': 'Fixture schema/planner agreement, deterministic validation and typed defaults; not exhaustive input equivalence.', 'checks': checks}


def _run_file(directory, name):
    path = local_path(directory, name)
    if (Path(directory)/name).is_symlink():
        fail('CONFORMANCE_FAILED', 'acceptance file may not be a symlink', name)
    if path.stat().st_size > 8*1024*1024:
        fail('CONFORMANCE_FAILED', 'acceptance observation exceeds 8 MiB', name)
    return path


def assertions(directory, checks):
    results = []
    for check in checks:
        path = _run_file(directory, check['file'])
        if check['format'] == 'csv':
            value = read_csv(path)
        elif check['format'] == 'json':
            value = load_document(path.read_text())
        else:
            value = path.read_text(encoding='utf-8')
        actual = at_pointer(value, check['pointer'])
        if not close(actual, check['expected'], rel=check.get('relative', 0), absolute=check.get('absolute', 0)):
            fail('CONFORMANCE_FAILED', 'independent expectation differs', check['file'] + check['pointer'],
                 expected=check['expected'], actual=actual)
        results.append({'file': check['file'], 'pointer': check['pointer'], 'observed': actual,
                        'expected': check['expected'], 'relative': check.get('relative', 0),
                        'absolute': check.get('absolute', 0), 'sha256': file_digest(path)})
    return results


def _rejection(action, label, codes=None):
    try:
        action()
    except SchemaxisError as error:
        if codes is not None and error.fault.code not in codes:
            fail('CONFORMANCE_FAILED', label + ' raised the wrong structured fault', observed=error.to_dict())
        return {'check': label, 'fault': error.fault.code, 'verified': True}
    except Exception as error:
        fail('CONFORMANCE_FAILED', label + ' raised an unstructured exception: ' + str(error))
    fail('CONFORMANCE_FAILED', label + ' was incorrectly accepted')


def integrity(directory, document):
    """Mutate only a newly generated qualification run; restore even on failure."""
    directory = Path(directory).resolve()
    receipt = load_document((directory/'verification.json').read_text())
    artifacts = receipt.get('artifacts', [receipt['artifact']] if 'artifact' in receipt else [])
    if not isinstance(artifacts, list) or not artifacts:
        fail('CONFORMANCE_FAILED', 'verification evidence must name at least one publication')
    targets = []
    for artifact in artifacts:
        path = Path(artifact['file'])
        if not path.is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(directory) or not path.is_file():
            fail('CONFORMANCE_FAILED', 'publication escapes its qualification run', str(path))
        if file_digest(path) != artifact.get('sha256'):
            fail('CONFORMANCE_FAILED', 'publication digest differs', str(path))
        targets.append(path)
    checks = []
    # Preserve the original bytes by renaming, including large binary publications.
    for path in [*targets, directory/'authored.json', directory/'plan.json', directory/'verification.json']:
        backup = path.with_name(path.name + '.qualification-original')
        if backup.exists():
            fail('CONFORMANCE_FAILED', 'qualification backup already exists', str(backup))
        path.rename(backup)
        try:
            checks.append(_rejection(lambda: registry.verify(directory, document), 'missing ' + path.name))
            path.write_text('{"tampered":true}\n')
            checks.append(_rejection(lambda: registry.verify(directory, document), 'tampered ' + path.name))
        finally:
            if path.exists():
                path.unlink()
            backup.rename(path)
    registry.verify(directory, document)
    return checks


def _native_worker(request):
    """Fixed trusted worker; authored documents cannot select code or shell commands."""
    document, run = request['document'], Path(request['run'])
    options = {'locations': request['locations'], 'timeout': request['timeout']}
    if request['action'] == 'case':
        registry.run(document, run, **options)
        verified = registry.verify(run, document)
        if verified.get('verified') is not True or not verified.get('runtime'):
            fail('CONFORMANCE_FAILED', 'native verification must report success and observed runtime identity')
        case = request['case']
        return {'id': case['id'], 'scope': case['scope'], 'verified': True,
                'documentDigest': request['documentDigest'], 'authoredDigest': digest(document), 'caseDigest': digest(case),
                'runtime': verified['runtime'], 'checks': assertions(run, case['checks']),
                'integrity': integrity(run, document)}
    if request['action'] == 'timeout':
        return _rejection(lambda: registry.run(document, run, locations=request['locations'], timeout=1e-9),
                          'native runner timeout', {'RUNNER_TIMED_OUT'})
    if request['action'] == 'cancel':
        cancel = threading.Event()
        cancel.set()
        with allocation({'threads': 1, 'ranks': 1}, cancel):
            return _rejection(lambda: registry.run(document, run, **options),
                              'pre-launch cancellation', {'RUNNER_CANCELLED'})
    fail('INVALID_REQUEST', 'unknown conformance worker action')


def _bounded_native(request, workspace, seconds):
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=False)
    response = workspace/'response.json'
    source = ('import json\nfrom schemaxis.adaptor_conformance import _native_worker\n'
              'from schemaxis.artifacts import atomic_json\nfrom schemaxis.core.faults import SchemaxisError\n'
              + 'request = json.loads(' + repr(json.dumps(request, allow_nan=False)) + ')\n'
              + 'try:\n    result = {"result": _native_worker(request)}\n'
              + 'except SchemaxisError as error:\n    result = {"fault": error.fault.to_dict()}\n'
              + 'except Exception as error:\n    result = {"error": type(error).__name__ + ": " + str(error)}\n'
              + 'atomic_json(' + repr(str(response)) + ', result)\n')
    try:
        SubprocessRunner(Interpreter('adaptor-conformance', sys.executable), workspace, timeout=seconds)(source)
    except SchemaxisError as error:
        if error.fault.code == 'RUNNER_TIMED_OUT':
            fail('CONFORMANCE_WATCHDOG', 'adaptor exceeded the independent qualification wall-clock limit', str(workspace))
        raise
    result = load_document(response.read_text())
    if 'fault' in result:
        raise SchemaxisError(Fault(**result['fault']))
    if 'error' in result:
        fail('CONFORMANCE_FAILED', result['error'], str(workspace))
    return result['result']


def qualify(version, directory, *, native=False, root=None, locations=None, timeout=120, wall_timeout=300):
    """Retain a source-bound receipt. Native runs are always fresh and bounded."""
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_EXECUTION', 'qualification timeout must be positive and at most 3600 seconds')
    if type(wall_timeout) not in (int, float) or not math.isfinite(wall_timeout) or not 0 < wall_timeout <= 3600:
        fail('INVALID_EXECUTION', 'qualification wall timeout must be positive and at most 3600 seconds')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'choose a new qualification directory', str(directory))
    provider, route, entry = route_materials(version)
    start_digest = source_digest(provider)
    report = {'protocol': PROTOCOL, 'provider': provider, 'documentVersion': version,
              'mode': 'native' if native else 'host', 'verified': False,
              'sourceDigest': start_digest, 'recordedAt': datetime.now(timezone.utc).isoformat(),
              'scope': 'Only named cases, recorded runtimes and tested lifecycle paths. No MPI or exhaustive operation qualification.',
              'cases': [], 'lifecycle': [], 'host': None}
    directory.mkdir(parents=True)
    try:
        report['host'] = host(version, root=root)
        if native:
            for case in entry['development']['cases']:
                document = case_document(entry, case, root or repository_root(provider))
                run = directory/case['id']
                request = {'action': 'case', 'document': document, 'case': case, 'run': str(run),
                           'locations': locations, 'timeout': timeout,
                           'documentDigest': case_document_digest(entry, case, root or repository_root(provider))}
                report['cases'].append(_bounded_native(request, directory/'.conformance'/case['id'], wall_timeout))
            document = case_document(entry, entry['development']['cases'][0], root or repository_root(provider))
            for action in ('timeout', 'cancel'):
                request = {'action': action, 'document': document, 'run': str(directory/action),
                           'locations': locations, 'timeout': timeout}
                report['lifecycle'].append(_bounded_native(request, directory/'.conformance'/action, min(10, wall_timeout)))
        if source_digest(provider) != start_digest:
            fail('CONFORMANCE_FAILED', 'adaptor/framework source changed during qualification; repeat against a stable checkout')
        report['verified'] = True
    except Exception as error:
        report['fault'] = error.to_dict() if isinstance(error, SchemaxisError) else {'message': str(error), 'type': type(error).__name__}
        raise
    finally:
        atomic_json(directory/'qualification.json', report)
    return report


def register(receipt_path):
    """Explicitly retain a successful native receipt in the owning source package."""
    receipt = load_document(Path(receipt_path).read_text())
    provider, _, entry = route_materials(receipt.get('documentVersion'))
    if (receipt.get('protocol') != PROTOCOL or receipt.get('provider') != provider
            or receipt.get('mode') != 'native' or receipt.get('verified') is not True
            or receipt.get('sourceDigest') != source_digest(provider)):
        fail('INVALID_QUALIFICATION', 'receipt must be a successful native run against current source')
    validate_receipt(receipt, receipt['documentVersion'], entry)
    path = Path(str(files_for_provider(provider)))/'qualification.json'
    existing = load_document(path.read_text()) if path.is_file() else {'protocol': PROTOCOL, 'routes': {}}
    if existing.get('protocol') != PROTOCOL or not isinstance(existing.get('routes'), dict):
        fail('INVALID_QUALIFICATION', 'existing receipt bundle is malformed', str(path))
    existing['routes'][receipt['documentVersion']] = receipt
    atomic_json(path, existing)
    return {'registered': str(path), 'documentVersion': receipt['documentVersion'], 'sourceDigest': receipt['sourceDigest']}


def files_for_provider(provider):
    from .adaptors.registry import adaptor_files
    return adaptor_files(provider)
