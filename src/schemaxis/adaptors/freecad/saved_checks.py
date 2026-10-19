"""Saved-run checks for captured STEP sources, import observations and hardened exports (host-only).

Saved verification never opens an original STEP path. It replays planning from the
retained copy (bound to its capture record and the saved plan), and checks every
newly produced modelling run's publications against exact native facts with the
host STL integrals in export_checks. Runs without that evidence are not verified:
they get RERUN_REQUIRED, never an automatic downgrade.
"""
import hashlib
import json
import math
from pathlib import Path
from schemaxis.errors import fail
from schemaxis.run_paths import owned_path

EXPORT_EVIDENCE = 'schemaxis.freecad.export/2'
SOURCE_NODES = ('readSTEP', 'importSTEP')


def records(directory):
    path = Path(directory)/'sources.json'
    if not path.exists():
        return {}
    value = json.loads(owned_path(directory, 'sources.json').read_text())
    if not isinstance(value, dict):
        fail('VERIFICATION_FAILED', 'STEP capture record must be an object', str(directory))
    return value


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_sources(directory, prepared, captured):
    """Authenticated {original path: sha256} of every STEP source, from retained bytes only."""
    from .step_source import consistent
    directory = Path(directory).absolute()
    expected = {n['id'] for n in prepared['nodes'] if n['filter'] in SOURCE_NODES}
    if set(captured) != expected:
        fail('VERIFICATION_FAILED', 'STEP source membership differs', str(directory))
    result, legacy, imports = {}, 0, 0
    for node in prepared['nodes']:
        if node['filter'] not in SOURCE_NODES:
            continue
        record = captured[node['id']]
        if not isinstance(record, dict):
            fail('VERIFICATION_FAILED', 'STEP source record is malformed', node['id'])
        if node['filter'] == 'readSTEP':
            name, legacy = 'source-'+str(legacy)+'.step', legacy+1
            if set(record) != {'file', 'retained', 'sha256'}:
                fail('VERIFICATION_FAILED', 'STEP source provenance differs', node['id'])
        else:
            name, imports = 'import-'+str(imports)+'.step', imports+1
            source = node['source']
            if (set(record) != {'file', 'retained', 'sha256', 'bytes', 'route'} or record['route'] != 'importSTEP'
                    or record['file'] != source['path'] or record['sha256'] != source['sha256'] or record['bytes'] != source['bytes']):
                fail('VERIFICATION_FAILED', 'Captured STEP source differs from its plan', node['id'])
        if not consistent(node['options']['file'], record.get('file')):
            fail('VERIFICATION_FAILED', 'STEP source provenance differs from the authored file', node['id'])
        retained = owned_path(directory, record['retained'])
        if retained != directory/name or retained.resolve().parent != directory.resolve():
            fail('VERIFICATION_FAILED', 'Retained STEP copy is not the run-owned capture', node['id'])
        if not isinstance(record['sha256'], str) or file_sha256(retained) != record['sha256']:
            fail('INPUT_CHANGED', 'Retained STEP copy changed after capture', node['id'])
        result[record['file']] = record['sha256']
    return result


def verify_saved_document(path, prepared, captured):
    """FCStd binds each STEP object to its captured digest, and each refine output to its source."""
    from .document_xml import Document, ARCHIVE_ERRORS
    from .operations import extra_objects
    try:
        xml = Document(path)
        for index, node in enumerate(prepared['nodes']):
            if node['filter'] not in SOURCE_NODES:
                continue
            name = 'N'+str(index)
            if xml.types.get(name) != 'Part::Feature' or xml.string(name, 'SourceSHA256') != captured[node['id']]['sha256']:
                raise ValueError('saved STEP object digest differs')
        for name, kind in extra_objects(prepared).items():
            if xml.types.get(name) != kind or xml.link(name, 'Source') != name[:-len('Refined')]:
                raise ValueError('saved refine output is not linked to its imported source')
        if any(n['filter'] == 'importSTEP' for n in prepared['nodes']):
            from . import gui_state
            from .operations import output_names
            output = output_names(prepared)[prepared['output']]
            gui_state.verify(path, {name: name == output for name in xml.types})
    except ARCHIVE_ERRORS as error:
        fail('VERIFICATION_FAILED', 'Saved FCStd archive or its XML is corrupt, malformed or uses an unsupported feature', 'model.FCStd',
             error=type(error).__name__, detail=str(error)[:300])
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
        fail('VERIFICATION_FAILED', 'Saved STEP provenance in the FCStd is missing or differs', 'model.FCStd',
             error=type(error).__name__, detail=str(error)[:300])


def _close(a, b, rel=1e-7, absolute=1e-6):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y, rel, absolute) for x, y in zip(a, b))
    return (type(a) in (int, float) and type(b) in (int, float) and math.isfinite(a) and math.isfinite(b)
            and math.isclose(a, b, rel_tol=rel, abs_tol=absolute))


IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]


def verify_imports(prepared, built, receipt):
    from .step_import import evaluate
    nodes = [(i, n) for i, n in enumerate(prepared['nodes']) if n['filter'] == 'importSTEP']
    first, second = built.get('importObservations'), receipt.get('importObservations')
    if not isinstance(first, dict) or not isinstance(second, dict) or set(first) != {n['id'] for _, n in nodes} or set(second) != set(first):
        fail('VERIFICATION_FAILED', 'Import observation membership differs')
    for index, node in nodes:
        frame = node['frame']
        r, t = frame['worldFromFile'], frame['translation']
        placement = [r[0][0], r[0][1], r[0][2], t[0], r[1][0], r[1][1], r[1][2], t[1], r[2][0], r[2][1], r[2][2], t[2]]
        for label, record in (('build', first[node['id']]), ('reopen', second[node['id']])):
            if not isinstance(record, dict) or record.get('sourceObject') != 'N'+str(index) \
                    or record.get('sourceSHA256') != node['source']['sha256'] or not _close(record.get('placement'), placement, 1e-9, 1e-9):
                fail('VERIFICATION_FAILED', 'Imported source object, digest or placement differs', node['id'], stage=label)
            evaluate(node['options']['expect'], record.get('part', {}), node['id']+'.options.expect')
            refine = record.get('refine')
            if node['options']['refine']:
                if (not isinstance(refine, dict) or refine.get('object') != 'N'+str(index)+'Refined'
                        or refine.get('source') != 'N'+str(index) or not _close(refine.get('placement'), IDENTITY, 0, 1e-12)
                        or record.get('outputObject') != 'N'+str(index)+'Refined'):
                    fail('VERIFICATION_FAILED', 'Refine output linkage or identity placement differs', node['id'], stage=label)
            elif refine is not None or record.get('outputObject') != 'N'+str(index):
                fail('VERIFICATION_FAILED', 'Import output object differs', node['id'], stage=label)
        a, b = first[node['id']], second[node['id']]
        for key in ('source', 'output'):
            for measure in ('volume', 'area', 'bounds', 'centreOfMass'):
                if not _close(a.get(key, {}).get(measure), b.get(key, {}).get(measure)):
                    fail('VERIFICATION_FAILED', 'Placed import facts changed after save and fresh reopening', node['id'],
                         facts=key, measure=measure)


def require_hardened(built, receipt, directory):
    for record in (built.get('exportEvidence'), receipt.get('exportEvidence')):
        if not isinstance(record, dict) or record.get('version') != EXPORT_EVIDENCE:
            fail('RERUN_REQUIRED', 'This run has no hardened export evidence (signed STL integrals, centre of mass, '
                 'curved area and STEP unit). Its receipt stays historical evidence but is not verified now; rerun the document.',
                 str(directory), exportChecks='unqualified-for-hardened-verification')


def verify_exports(directory, prepared, built, receipt):
    from .export_checks import native_facts, check_stl
    from .step_source import read_bounded, admit, EXPORT_LIMITS
    directory = Path(directory).absolute()
    require_hardened(built, receipt, directory)
    first, second = built['exportEvidence'], receipt['exportEvidence']
    meshing = first.get('meshing')
    if meshing != {'linearDeflection': prepared['linearDeflection']/2, 'angularDeflection': 0.1, 'relative': False}:
        fail('VERIFICATION_FAILED', 'Meshing parameters differ from the plan', str(directory))
    build = native_facts(first.get('shape'), 'build')
    native = native_facts(second.get('native'), 'reopen')
    step = native_facts(second.get('step'), 'step')
    old = built.get('shape', {})
    for measure in ('volume', 'area', 'bounds'):
        if not _close(old.get(measure), build[measure]):
            fail('VERIFICATION_FAILED', 'Hardened build facts differ from the build snapshot', measure=measure)
    for label, other, measures in (('reopen', native, ('volume', 'area', 'bounds', 'centreOfMass', 'curvedArea')),
                                   ('step', step, ('volume', 'area', 'bounds', 'centreOfMass'))):
        for measure in measures:
            if not _close(other[measure], build[measure]):
                fail('VERIFICATION_FAILED', 'Native export facts changed after export or fresh reopening', label, measure=measure)
    if native['faces'] != build['faces']:
        fail('VERIFICATION_FAILED', 'Native face count changed after fresh reopening')
    stl = check_stl(owned_path(directory, 'model.stl'), build, meshing['linearDeflection'])
    mesh = receipt.get('mesh', {})
    if mesh.get('facets') != stl['host']['facets']:
        fail('VERIFICATION_FAILED', 'Native and host STL facet counts differ')
    data = read_bounded(owned_path(directory, 'model.step'), 'model.step', limit=EXPORT_LIMITS['bytes'], code='VERIFICATION_FAILED')
    try:
        facts = admit(data, 'model.step', export=True)
    except Exception as error:
        from schemaxis.core.faults import SchemaxisError
        if isinstance(error, SchemaxisError):
            fail('VERIFICATION_FAILED', 'Published STEP does not declare one millimetre solid: '+error.fault.message, 'model.step')
        raise
    if facts['unit'] != 'mm':
        fail('VERIFICATION_FAILED', 'Published STEP declares a length unit other than mm', 'model.step', unit=facts['unit'])
    return {'level': 'hardened', 'volumeError': stl['volumeError'], 'volumeAllowance': stl['volumeAllowance'],
            'volumeCeiling': stl['volumeCeiling'], 'centreError': stl['centreError'], 'centreAllowance': stl['centreAllowance'],
            'mirrorDiscriminability': stl['mirrorDiscriminability'], 'stepUnit': facts['unit'], 'stlFacets': stl['host']['facets']}
