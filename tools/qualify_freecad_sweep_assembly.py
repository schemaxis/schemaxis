"""Qualify swept CAD histories composed into editable shared-instance assemblies."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

from schemaxis import workflow
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad.assembly_sources_saved import verify_saved
from schemaxis.adaptors.freecad.history_copy_verify import regenerate
from schemaxis.adaptors.freecad.process import SubprocessRunner
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json, runtime_archive
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from freecad_sweep_cases import flanged, elbow_integrals


def project(variant=False):
    model = flanged()
    if variant:
        for key, value in dict(bendRadius=12, outerRadius=3.25, wall=.75, flangeRadius=5.5, flangeLength=4).items():
            model['parameters'][key]['value'] = value
    assembly = {'version': 'schemaxis.freecad.assembly/1', 'parts': [
        {'id': 'elbow', 'source': {'$artifact': 'part', 'index': 2},
         'mounts': {'base': {}, 'mate': {'position': [60 if variant else 50, 0, 0]}}}],
        'components': [{'id': 'fixed', 'part': 'elbow', 'position': [20, -15, 7] if variant else [0, 0, 0],
                        'rotation': 90 if variant else 0}, {'id': 'copy', 'part': 'elbow'}],
        'grounded': 'fixed', 'joints': [{'id': 'mate', 'type': 'fixed',
            'parent': {'component': 'fixed', 'mount': 'mate'},
            'child': {'component': 'copy', 'mount': 'base'}, 'clocking': 90 if variant else 0}]}
    return {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'part', 'document': model}, {'id': 'assembly', 'document': assembly}]}


def near(actual, expected):
    assert math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-7), (actual, expected)


def check(snapshot, variant, bend):
    """Independent annular torus-segment plus two straight annular flanges."""
    expected = elbow_integrals(bend=bend, outer=3.25 if variant else 3,
        inner=2.5 if variant else 2, flange=5.5 if variant else 5, length=4 if variant else 5)
    x, y, z = expected['centre']
    centres = {'fixed': [20-y, -15+x, 7+z], 'copy': [20-x, 45-y, 7+z]} if variant else {
        'fixed': [x, y, z], 'copy': [50+x, y, z]}
    assert snapshot['badStates'] == {} and snapshot['externalLinks'] == []
    components = snapshot['components']
    assert components['fixed']['linked'] == components['copy']['linked']
    for identity, centre in centres.items():
        shape = components[identity]['shape']
        assert shape['valid'] and shape['solids'] == 1
        near(shape['volume'], expected['volume'])
        for actual, wanted in zip(shape['centreOfMass'], centre):
            near(actual, wanted)


def native(directory, stage, request, executable):
    atomic_json(directory/('edit-request.json' if stage == 'edit_probe' else 'inspect-request.json'), request)
    (directory/'trusted-runtime.zip').write_bytes(runtime_archive())
    code = ('import sys\nsys.path.insert(0,'+repr(str(directory/'trusted-runtime.zip'))+')\n'
        'from schemaxis.adaptors.freecad.assembly_sources_native import '+stage+'\n'
        'from schemaxis.native_boundary import execute_guarded\nexecute_guarded('+stage+','+repr(str(directory))+')\n')
    SubprocessRunner(Interpreter('freecad', executable), directory, timeout=180)(code)
    assert not (directory/'native-fault.json').exists()


def attacks(directory, executable):
    plan = json.loads((directory/'plan.json').read_text())
    built = json.loads((directory/'built.json').read_text())
    retained = {p['id']: directory/plan['native']['retained'][p['id']] for p in plan['parts']}
    path = directory/'model.FCStd'
    original, metadata = path.read_bytes(), (directory/'verification.json').read_bytes()
    with ZipFile(path) as archive:
        members = {n: archive.read(n) for n in archive.namelist()}
    from xml.etree import ElementTree as ET
    mutations = {}
    name = built['renames']['elbow']['N6']
    for label, prop, tag, field, value in (
        ('point-engine', 'AttacherEngine', 'Integer', 'value', '1'),
        ('flange-placement', 'Placement', 'PropertyPlacement', 'Pz', '10.000001'),
    ):
        root = ET.fromstring(members['Document.xml'])
        root.find(f'./ObjectData/Object[@name="{name}"]/Properties/Property[@name="{prop}"]/{tag}').set(field, value)
        prefix = members['Document.xml'].split(b'<Document ', 1)[0]
        mutations[label] = {'Document.xml': prefix+ET.tostring(root)}
    table = ET.fromstring(members['Document.xml']).find('StringHasher2').get('file')
    lines = members[table].decode().splitlines()
    lines[0] = 'StringTableStart v1 '+str(int(lines[0].split()[-1])+1)
    lines.append('7fffffff.0 0:unused-semantic-attack')
    mutations['unused-string'] = {table: ('\n'.join(lines)+'\n').encode()}
    messages = {}
    try:
        with regenerate(directory, plan, retained, executable=executable, timeout=180) as oracle:
            verify_saved(plan, path, built['renames'], retained, oracle)
            for label, changes in mutations.items():
                assert all(members[n] != value for n, value in changes.items()), label
                with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
                    for member, value in members.items():
                        archive.writestr(member, changes.get(member, value))
                receipt = json.loads(metadata)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                receipt['artifact']['sha256'] = digest
                receipt['artifacts'][0]['sha256'] = digest
                atomic_json(directory/'verification.json', receipt)
                try:
                    verify_saved(plan, path, built['renames'], retained, oracle)
                except SchemaxisError as error:
                    assert error.fault.code == 'VERIFICATION_FAILED'
                    messages[label] = error.fault.observed['detail']
                else:
                    raise AssertionError('saved semantic attack accepted: '+label)
    finally:
        path.write_bytes(original)
        (directory/'verification.json').write_bytes(metadata)
    assert registry.verify(directory)['verified']
    return messages


def qualify(directory, executable):
    # Explicit runtime selection must cover later bare workflow verification,
    # not only the producer. Never rely on the user's local configuration.
    from schemaxis.configuration import location_context
    with location_context({'freecad': executable}):
        return _qualify_at_location(directory, executable)


def _qualify_at_location(directory, executable):
    directory.mkdir(parents=True)
    report = {'verified': False, 'sourceDigest': source_digest('freecad'), 'checks': {}}
    try:
        for variant in (False, True):
            name = 'variant' if variant else 'baseline'
            root = directory/name
            result = workflow.execute(project(variant), root/'workflow', locations={'freecad': executable}, timeout=360)
            assert workflow.verify(root/'workflow')['verified']
            assembly = next(Path(job['directory']) for job in result['jobs'] if job['operation'] == 'assembly')
            saved = json.loads((assembly/'verification.json').read_text())
            for stage in ('persisted', 'solved'):
                check(saved['snapshots'][stage], variant, 12 if variant else 10)
            edits = root/'edits'
            edits.mkdir()
            for filename in ('model.FCStd', 'built.json', 'plan.json'):
                shutil.copyfile(assembly/filename, edits/filename)
            pids = []
            for bend in ((13, 14) if variant else (11, 12)):
                native(edits, 'edit_probe', {'part': 'elbow', 'parameter': 'bendRadius', 'value': bend, 'output': 'edited.FCStd'}, executable)
                changed = json.loads((edits/'edit.json').read_text())
                for stage in ('recomputed', 'solved', 'probed'):
                    check(changed['snapshots'][stage], variant, bend)
                native(edits, 'inspect_copy', {'file': str(edits/'edited.FCStd'), 'receipt': 'reopened.json'}, executable)
                reopened = json.loads((edits/'reopened.json').read_text())
                assert reopened['pid'] != changed['pid']
                for stage in ('persisted', 'solved'):
                    check(reopened['snapshots'][stage], variant, bend)
                pids.extend([changed['pid'], reopened['pid']])
                atomic_json(edits/f'edit-{bend}.json', changed)
                atomic_json(edits/f'reopen-{bend}.json', reopened)
                shutil.copyfile(edits/'edited.FCStd', edits/'model.FCStd')
            assert len(set(pids)) == 4
            rejected = attacks(assembly, executable)
            resumed = workflow.execute(project(variant), root/'workflow', locations={'freecad': executable}, timeout=360, resume=True)
            assert all(job['reused'] for job in resumed['jobs'])
            report['checks'][name] = {'analyticVolumesAndCentres': True, 'nativeEditsAndFreshReopen': True,
                                     'refreshedDigestAttacks': rejected, 'verifiedReuse': True}
            atomic_json(directory/'qualification.json', report)
            print(name+' verified', flush=True)
        assert source_digest('freecad') == report['sourceDigest'], 'source changed during qualification'
        report['verified'] = True
        return report
    finally:
        atomic_json(directory/'qualification.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--executable', required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.directory.absolute(), args.executable), indent=2))
