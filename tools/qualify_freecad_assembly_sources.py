#!/usr/bin/env python3
"""Qualify assemblies of verified phase-one parts at named mounts on native FreeCAD 1.1.x.

PYTHONPATH=src python3 tools/qualify_freecad_assembly_sources.py --directory DIR --executable FREECADCMD

One normal workflow builds five phase-one producers (two with colliding native
names, a corner-removing pocket, a circle Pad and a literal Body) and two
assemblies that take each producer's FCStd publication through $artifact index 2.
The qualifier then proves resume reuse and standalone invalidation, a literal
analytic oracle for captured geometry, exact versus containment bounds, a
shared-source native edit with a fresh reopen, a relocated copy with all inputs
unavailable, deliberate convention changes, saved-file tamper and malformed-archive
negatives, and native reopening of tampered copies. Use a fresh directory; earlier
evidence is never overwritten. The GUI check is tools/qualify_freecad_assembly_sources_gui.py.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import shutil
import time
import zipfile

from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import assembly_sources as sources
from schemaxis.adaptors.freecad.assembly_sources_saved import verify_saved
from schemaxis.adaptors.freecad.parameters import evaluate
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import SubprocessRunner

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ fixtures

def part(width, height, thickness, bore, centre, *, bounds=None):
    doc = json.loads((ROOT/'examples/schemaxis/freecad-part-design.json').read_text())
    doc.pop('measurements', None)
    low, high = bounds or (2, 50)
    doc['parameters'] = {'width': {'kind': 'length', 'value': width, 'minimum': width/2, 'maximum': width*2},
                         'thickness': {'kind': 'length', 'value': thickness, 'minimum': low, 'maximum': high},
                         'boreRadius': {'kind': 'length', 'value': bore, 'minimum': bore/2, 'maximum': bore*2}}
    doc['nodes'][1]['options']['height'] = height
    doc['nodes'][3]['options']['centre'] = centre
    return doc


def disc():
    return {'version': 'schemaxis.freecad/1',
            'parameters': {'thickness': {'kind': 'length', 'value': 4, 'minimum': 2, 'maximum': 10}},
            'nodes': [{'id': 'part', 'filter': 'body'},
                      {'id': 'outline', 'filter': 'circle', 'inputs': {'body': 'part'}, 'options': {'radius': 15, 'plane': 'XY'}},
                      {'id': 'slab', 'filter': 'pad', 'inputs': {'body': 'part', 'profile': 'outline'},
                       'drive': {'length': {'terms': {'thickness': 1}}}},
                      {'id': 'hole', 'filter': 'rectangle', 'inputs': {'body': 'part'}, 'options': {'width': 6, 'height': 6, 'plane': 'XY'}},
                      {'id': 'finished', 'filter': 'pocket', 'inputs': {'base': 'slab', 'profile': 'hole'}, 'options': {'extent': 'throughAll'}}],
            'output': 'finished'}


def literal():
    return {'version': 'schemaxis.freecad/1',
            'nodes': [{'id': 'part', 'filter': 'body'},
                      {'id': 'outline', 'filter': 'rectangle', 'inputs': {'body': 'part'}, 'options': {'width': 50, 'height': 30, 'plane': 'XY'}},
                      {'id': 'slab', 'filter': 'pad', 'inputs': {'body': 'part', 'profile': 'outline'}, 'options': {'length': 8}},
                      {'id': 'bore', 'filter': 'circle', 'inputs': {'body': 'part'}, 'options': {'radius': 2, 'plane': 'XY'}},
                      {'id': 'finished', 'filter': 'pocket', 'inputs': {'base': 'slab', 'profile': 'bore'}, 'options': {'extent': 'throughAll'}}],
            'output': 'finished'}


PRODUCERS = {'plate': part(80, 50, 5, 3, [15, 10]), 'spacer': part(60, 40, 12, 4, [-10, 5]),
             'corner': part(60, 40, 6, 12, [30, 20]), 'disc': disc(), 'block': literal()}


def literal_geometry(name, thickness=None):
    """Closed-form local volume, area, bounds and centre of mass of each fixture."""
    pi = math.pi
    if name == 'disc':
        r, t, s = 15, thickness or 4, 6
        return {'volume': (pi*r*r-s*s)*t, 'area': 2*(pi*r*r-s*s)+(2*pi*r+4*s)*t,
                'bounds': [-r, r, -r, r, 0, t], 'centreOfMass': [0, 0, t/2]}
    if name == 'block':
        w, h, t, r = 50, 30, 8, 2
        return {'volume': (w*h-pi*r*r)*t, 'area': 2*(w*h-pi*r*r)+2*(w+h)*t+2*pi*r*t,
                'bounds': [-w/2, w/2, -h/2, h/2, 0, t], 'centreOfMass': [0, 0, t/2]}
    doc = PRODUCERS[name]
    w, t, r = doc['parameters']['width']['value'], thickness or doc['parameters']['thickness']['value'], doc['parameters']['boreRadius']['value']
    h, (cx, cy) = doc['nodes'][1]['options']['height'], doc['nodes'][3]['options']['centre']
    if name == 'corner':  # the bore centre sits on the (+x, +y) corner: a quarter disc is removed
        hole, k = pi*r*r/4, 4*r/(3*pi)
        hx, hy = cx-k, cy-k
        area = 2*(w*h-hole)+(2*(w+h)-2*r+pi*r/2)*t
    else:
        hole, (hx, hy) = pi*r*r, (cx, cy)
        area = 2*(w*h-hole)+2*(w+h)*t+2*pi*r*t
    face = w*h-hole
    return {'volume': face*t, 'area': area, 'bounds': [-w/2, w/2, -h/2, h/2, 0, t],
            'centreOfMass': [-hole*hx/face, -hole*hy/face, t/2]}


def assembly_document(rotation):
    def src(name):
        return {'$artifact': name, 'index': 2}
    up = {'position': [0, 0, {'terms': {'thickness': 1}}]}
    if rotation == 90:
        return {'version': 'schemaxis.freecad.assembly/1', 'units': 'mm',
                'parts': [{'id': 'plate', 'source': src('plate'), 'mounts': {'top': up}},
                          {'id': 'corner', 'source': src('corner'), 'mounts': {'bottom': {}}}],
                'components': [{'id': 'base', 'part': 'plate', 'position': [5, -5, 0], 'rotation': 90},
                               {'id': 'notched', 'part': 'corner'}],
                'grounded': 'base',
                'joints': [{'id': 'notch', 'type': 'fixed', 'parent': {'component': 'base', 'mount': 'top'},
                            'child': {'component': 'notched', 'mount': 'bottom'}, 'offset': [10, 5, 0], 'clocking': -90}]}
    return {'version': 'schemaxis.freecad.assembly/1', 'units': 'mm',
            'parts': [{'id': 'plate', 'source': src('plate'), 'mounts': {
                          'top': up, 'side': {'position': [{'terms': {'width': 0.5}}, 0, {'terms': {'thickness': 0.5}}], 'z': '+X', 'x': '-Z'},
                          'under': {'z': '-Z', 'x': '+X'}}},
                      {'id': 'spacer', 'source': src('spacer'), 'mounts': {'bottom': {}, 'top': up}},
                      {'id': 'corner', 'source': src('corner'), 'mounts': {'bottom': {}, 'top': up}},
                      {'id': 'disc', 'source': src('disc'), 'mounts': {'bottom': {}}},
                      {'id': 'block', 'source': src('block'), 'mounts': {'top': {'position': [0, 0, 8], 'z': '-Z', 'x': '+X'}}}],
            'components': [{'id': 'base', 'part': 'plate', 'position': [10, 20, 0], 'rotation': 30},
                           {'id': 'spacer', 'part': 'spacer'}, {'id': 'cover', 'part': 'plate'},
                           {'id': 'notched', 'part': 'corner'}, {'id': 'washer', 'part': 'disc'},
                           {'id': 'hanger', 'part': 'block'}],
            'grounded': 'base',
            'joints': [{'id': 'baseToSpacer', 'type': 'fixed', 'parent': {'component': 'base', 'mount': 'top'},
                        'child': {'component': 'spacer', 'mount': 'bottom'}, 'offset': [5, 0, 0], 'clocking': 90},
                       {'id': 'spacerToCover', 'type': 'fixed', 'parent': {'component': 'spacer', 'mount': 'top'},
                        'child': {'component': 'cover', 'mount': 'side'}, 'offset': [0, 0, 2]},
                       {'id': 'baseToNotched', 'type': 'fixed', 'parent': {'component': 'base', 'mount': 'top'},
                        'child': {'component': 'notched', 'mount': 'bottom'}, 'offset': [-20, 10, 0], 'clocking': 45},
                       {'id': 'notchedToWasher', 'type': 'fixed', 'parent': {'component': 'notched', 'mount': 'top'},
                        'child': {'component': 'washer', 'mount': 'bottom'}, 'offset': [0, 0, 1]},
                       {'id': 'baseToHanger', 'type': 'fixed', 'parent': {'component': 'base', 'mount': 'under'},
                        'child': {'component': 'hanger', 'mount': 'top'}}]}


def workflow():
    return {'version': 'schemaxis.workflow/1',
            'operations': [*({'id': name, 'document': doc} for name, doc in PRODUCERS.items()),
                           {'id': 'assembly', 'document': assembly_document(30)},
                           {'id': 'quarter', 'document': assembly_document(90)}]}


# -------------------------------------------------------------------- helpers

class Qualification:
    def __init__(self, directory, executable):
        self.directory, self.executable = directory, executable
        self.report = {'verified': False, 'sourceDigest': source_digest('freecad'), 'started': time.time(), 'checks': {}}

    def save(self):
        atomic_json(self.directory/'report.json', self.report)

    def check(self, name, value):
        self.report['checks'][name] = value
        self.save()
        print(name, 'ok', flush=True)

    def native(self, target, stage, request=None):
        if request is not None:
            name, data = request
            atomic_json(target/name, data)
        runner = SubprocessRunner(Interpreter('freecad', self.executable), target, timeout=90)
        source = ('import sys\nsys.path.insert(0,'+repr(str(target/'runtime.zip'))+')\n'
                  'from schemaxis.adaptors.freecad.assembly_sources_native import '+stage+'\n'
                  'from schemaxis.native_boundary import execute_guarded\n'
                  'execute_guarded('+stage+','+repr(str(target))+')\n')
        report = runner(source)
        atomic_json(target/(stage+'-'+str(int(time.time()*1000))+'-submission.json'), report.to_dict())
        if (target/'native-fault.json').exists():
            raise SchemaxisError(Fault(**json.loads((target/'native-fault.json').read_text())))


def failures(callable_):
    try:
        callable_()
    except SchemaxisError as error:
        return error.fault.code
    return None


def rejected(prepared, snapshot, renames, centres, label):
    def require(ok, message, **detail):
        if not ok:
            raise SchemaxisError(Fault('VERIFICATION_FAILED', message, label, 'pipeline', observed=detail))
    try:
        sources.check_snapshot(prepared, snapshot, renames, centres, require, label)
    except SchemaxisError as error:
        return error.fault.message
    return None


def edited_plan(prepared, part_id, parameter, value, geometry):
    result = copy.deepcopy(prepared)
    target = next(p for p in result['parts'] if p['id'] == part_id)
    target['source']['parameters'][parameter]['value'] = value
    target['source'].update({k: geometry[k] for k in ('volume', 'area', 'bounds')})
    values = {k: v['value'] for k, v in target['source']['parameters'].items()}
    for mount in target['mounts']:
        for coordinate in mount['position']:
            if 'terms' in coordinate:
                coordinate['value'] = evaluate(coordinate, values)
        mount['value'] = [c['value'] if 'terms' in c else c['literal'] for c in mount['position']]
    result['expected'] = sources.analytic(result)
    return result


def rezip(source, target, edit=None, extra=()):
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(target, 'w') as new:
        for info in old.infolist():
            data = old.read(info)
            if edit and info.filename in edit:
                data = edit[info.filename](data.decode()).encode()
            new.writestr(info, data)
        for name, data in extra:
            new.writestr(name, data)


def in_property(text, name, prop, old, new):
    start = text.index('<Object name="%s"' % name, text.index('<ObjectData'))
    start = text.index('<Property name="%s"' % prop, start)
    stop = text.index('</Property>', start)
    block = text[start:stop]
    if old not in block:
        raise AssertionError('tamper anchor absent: '+name+'.'+prop+' '+old)
    return text[:start]+block.replace(old, new, 1)+text[stop:]


def in_object(text, name, old, new, count=1):
    start = text.index('<Object name="%s"' % name, text.index('<ObjectData'))
    stop = text.index('</Object>', start)
    block = text[start:stop]
    if block.count(old) < count:
        raise AssertionError('tamper anchor absent: '+name+' '+old)
    return text[:start]+block.replace(old, new, count)+text[stop:]


def native_launches(directory):
    """Native launcher PIDs recorded by the evidence wrapper, when one is in use."""
    log = Path(directory).parent/'native-pids.jsonl'
    return sum(1 for _ in log.open()) if log.exists() else None


def refresh_receipt(run, artifact_index):
    """What an attacker can do: re-digest a changed publication and regenerate its metadata."""
    from schemaxis.publication_metadata import finalise
    receipt = json.loads((run/'verification.json').read_text())
    path = Path(receipt['artifacts'][artifact_index]['file'])
    receipt['artifacts'][artifact_index]['sha256'] = sources.digest(path)
    if receipt.get('artifact', {}).get('file') == str(path):
        receipt['artifact']['sha256'] = sources.digest(path)
    (run/'verification.json').write_text(json.dumps(receipt, indent=2)+'\n')
    finalise(run)


def inert_document_edit(data, edit):
    import io
    source, target = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
    with zipfile.ZipFile(target, 'w') as archive:
        for info in source.infolist():
            content = source.read(info)
            name = info.filename
            if name in edit:
                content = edit[name](content)
                if content is None:
                    continue
            archive.writestr(name, content)
        for name, content in edit.get('+', lambda b: [])(b''):
            archive.writestr(name, content)
    return target.getvalue()


def refreshed_hash_cases(directory, doc, producer, stack, executable):
    """Inert mutants with refreshed receipts/metadata: producers refused at planning, assemblies at verify."""
    results = {'producer': {}, 'assembly': {}}
    body = b'<Properties Count="12" TransientCount="2">'
    python = (b'<Property name="UnqualifiedState" type="App::PropertyPythonObject" status="1"><Python value="bnVsbA==" '
              b'encoded="yes" module="not_an_importable_module" class="Inert"/></Property>')
    xlink = b'<Property name="External" type="App::PropertyXLink"><XLink file="elsewhere.FCStd" stamp="" name="Body"/></Property>'
    def document(change):
        return lambda b: b.replace(body, body+change, 1)
    producer_cases = {
        'inertPythonProperty': {'Document.xml': document(python)},
        'externalFileLink': {'Document.xml': document(xlink)},
        'doctypeEntity': {'Document.xml': lambda b: b.replace(b"?>\n", b"?>\n<!DOCTYPE Document [<!ENTITY inert \"x\">]>\n", 1)},
        'extraMember': {'+': lambda b: [('inert-note.txt', b'inert')]},
        'missingMember': {'N2.Shape.brp': lambda b: None},
        'corruptShape': {'N0.Shape.brp': lambda b: b'not a BREP payload\n'},
        'corruptElementMap': {'N4.Shape.Map.txt': lambda b: b.replace(b'EndMap', b'Endmap', 1)},
    }
    model = producer/'model.FCStd'
    original = model.read_bytes()
    with zipfile.ZipFile(model) as archive:
        valid_other_shape = archive.read('N4.Shape.brp')
    try:
        for label, edit in producer_cases.items():
            model.write_bytes(inert_document_edit(original, edit))
            refresh_receipt(producer, 2)
            before = native_launches(directory)
            results['producer'][label] = {'plan': failures(lambda: registry.plan(doc, legacy=True)),
                                          'run': failures(lambda: registry.run(doc, directory/'refused'/label, timeout=60,
                                                                               locations={'freecad': '/bin/false'}))}
            results['producer'][label]['nativeLaunchesAdded'] = (native_launches(directory) or 0) - (before or 0)
            assert results['producer'][label]['plan'] == 'UNSUPPORTED_SOURCE', (label, results['producer'][label])
            assert results['producer'][label]['run'] == 'UNSUPPORTED_SOURCE', (label, results['producer'][label])
            assert results['producer'][label]['nativeLaunchesAdded'] == 0, label
        # A syntactically valid but substituted history shape passes the envelope by design;
        # the native capture recompute must refuse it before any build stage starts.
        model.write_bytes(inert_document_edit(original, {'N2.Shape.brp': lambda b: valid_other_shape}))
        refresh_receipt(producer, 2)
        plan_fault = failures(lambda: registry.plan(doc, legacy=True))
        before = native_launches(directory)
        target = directory/'refused'/'substitutedValidShape'
        run_fault = failures(lambda: registry.run(doc, target, timeout=120, locations={'freecad': executable}))
        added = (native_launches(directory) or 0) - (before or 0)
        record = {'plan': plan_fault, 'run': run_fault, 'nativeLaunchesAdded': added,
                  'captureOnly': (target/'capture.json').exists() and not (target/'built.json').exists()
                                 and not (target/'model.FCStd').exists()}
        results['producer']['substitutedValidShape'] = record
        assert plan_fault is None and run_fault == 'VERIFICATION_FAILED' and record['captureOnly'], record
        assert added in (None, 1) or before is None, record
    finally:
        model.write_bytes(original)
        refresh_receipt(producer, 2)
    assert registry.verify(producer)['verified']
    saved = stack/'model.FCStd'
    original = saved.read_bytes()
    with zipfile.ZipFile(saved) as archive:
        swap = archive.read('N4.Shape.brp')
    assembly_cases = {
        'corruptShape': {'N0.Shape.brp': lambda b: b'not a BREP payload'},
        'substitutedHistoryShape': {'N2.Shape.brp': lambda b: swap},
        'nearEqualNumber': {'N4.Shape.brp': lambda b: b.replace(b'1.000000000000000', b'1.000000000000001', 1)},
        'missingMember': {'N0.Shape.brp': lambda b: None},
        'extraMember': {'+': lambda b: [('inert-note.txt', b'inert')]},
        'corruptElementMap': {'N0.Shape.Map.txt': lambda b: b'garbage'},
        'elementMapChildRecord': {'N0.Shape.Map.txt': lambda b: b.replace(b'ChildCount 1\n1 0 ', b'ChildCount 1\n1 1 ', 1)},
        'mountDatumMoved': {'Mount0_0.Shape.brp': lambda b: b.replace(b'0.000000000000000 \n', b'1.000000000000000 \n', 1)},
    }
    try:
        for label, edit in assembly_cases.items():
            saved.write_bytes(inert_document_edit(original, edit))
            refresh_receipt(stack, 0)
            results['assembly'][label] = failures(lambda: registry.verify(stack))
            assert results['assembly'][label] == 'VERIFICATION_FAILED', (label, results['assembly'][label])
    finally:
        saved.write_bytes(original)
        refresh_receipt(stack, 0)
    assert registry.verify(stack)['verified']
    results['restoredBaselinesVerify'] = True
    return results


# ---------------------------------------------------------------- qualification

def qualify(directory, executable):
    directory = Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=False)
    q = Qualification(directory, executable)
    from schemaxis.workflow import execute, verify as verify_workflow
    document = workflow()
    atomic_json(directory/'workflow.json', document)
    result = execute(document, directory/'workflow', freecad=executable, timeout=300)
    verified = verify_workflow(directory/'workflow')
    jobs = {job['operation']: Path(job['directory']) for job in result['jobs']}
    q.check('workflow', {'result': {k: result[k] for k in ('status', 'verified')}, 'verified': verified,
                         'jobs': {k: str(v) for k, v in jobs.items()},
                         'handoffs': [job.get('handoffs') for job in result['jobs'] if job['operation'] in ('assembly', 'quarter')]})
    resumed = execute(document, directory/'workflow', freecad=executable, timeout=300, resume=True)
    assert all(job.get('reused') is True for job in resumed['jobs']), 'unchanged resume must reuse every verified job'
    q.check('resumeReuse', {'reused': [job['operation'] for job in resumed['jobs'] if job.get('reused')]})

    target = jobs['assembly']
    prepared = json.loads((target/'plan.json').read_text())
    built = json.loads((target/'built.json').read_text())
    receipt = json.loads((target/'verification.json').read_text())
    captured = json.loads((target/'capture.json').read_text())
    renames = built['renames']
    retained = {p['id']: target/prepared['native']['retained'][p['id']] for p in prepared['parts']}
    centres = {k: v['shape']['centreOfMass'] for k, v in captured['parts'].items()}

    # Literal analytic oracle for captured geometry (independent of producer receipts).
    oracle = {}
    for part_id in centres:
        geometry = literal_geometry(part_id)
        shape = captured['parts'][part_id]['shape']
        for measure in ('volume', 'area', 'bounds', 'centreOfMass'):
            assert sources.close(shape[measure], geometry[measure]), (part_id, measure, shape[measure], geometry[measure])
        oracle[part_id] = geometry
    q.check('literalGeometryOracle', oracle)

    # Two definitions with colliding producer names were renamed; repeated instances share one source.
    plate, spacer = renames['plate'], renames['spacer']
    assert set(plate) == set(spacer) and set(plate.values()).isdisjoint(spacer.values())
    links = {c: s['linked'] for c, s in receipt['snapshots']['solved']['components'].items()}
    assert links['base'] == links['cover'] != links['spacer']
    q.check('sourcesAndInstances', {'renames': renames, 'links': links})

    # Bounds: rotated corner-removing pocket is strictly inside the naive rotated box.
    expected = prepared['expected']['components']['notched']
    observed = receipt['snapshots']['solved']['components']['notched']['shape']['bounds']
    gap = max(max(observed[2*i]-expected['bounds'][2*i] for i in range(3)),
              max(expected['bounds'][2*i+1]-observed[2*i+1] for i in range(3)))
    assert expected['boundsMode'] == 'containment' and gap > 1, ('naive rotated bounds must not be exact here', gap)
    quarter = json.loads((jobs['quarter']/'verification.json').read_text())
    quarter_plan = json.loads((jobs['quarter']/'plan.json').read_text())
    exact = quarter_plan['expected']['components']['notched']
    assert exact['boundsMode'] == 'exact' and sources.close(quarter['snapshots']['solved']['components']['notched']['shape']['bounds'], exact['bounds'])
    q.check('boundsDiscriminator', {'rotatedCornerPocketNaiveBox': expected['bounds'], 'rotatedCornerPocketNative': observed,
                                    'naiveExcessMm': gap, 'quarterTurnExact': exact['bounds']})

    # Deliberate convention changes are rejected by the oracle against the native result.
    solved = receipt['snapshots']['solved']
    discriminators = {}
    for label, change in (('clockingSign', lambda d: d['joints'][0].update(clocking=-90)),
                          ('clockingIgnored', lambda d: d['joints'][0].update(clocking=0)),
                          ('offsetChanged', lambda d: d['joints'][1].update(offset=[0, 0, 3])),
                          ('placementGuessOnGround', lambda d: d['components'][0].update(position=[10, 21, 0])),
                          ('mountAxisFlip', lambda d: next(m for m in next(p for p in d['parts'] if p['id'] == 'plate')['mounts']
                                                            if m['id'] == 'side').update(rotation=[[0, 0, -1], [0, 1, 0], [1, 0, 0]]))):
        changed = copy.deepcopy(prepared)
        change(changed)
        changed['expected'] = sources.analytic(changed)
        message = rejected(changed, solved, renames, centres, label)
        assert message, label
        discriminators[label] = message
    q.check('conventionDiscriminators', discriminators)

    # Qualification-only native stages work on a copy; the verified workflow attempt stays untouched.
    checks = directory/'native-checks'
    checks.mkdir()
    for name in ('plan.json', 'built.json', 'runtime.zip', 'model.FCStd'):
        shutil.copyfile(target/name, checks/name)
    workflow_attempt = target
    target = checks

    # Shared-source native edit (qualification-only stage), then a fresh reopen of the saved copy.
    q.native(target, 'edit_probe', ('edit-request.json', {'part': 'plate', 'parameter': 'thickness', 'value': 7, 'output': 'edited.FCStd'}))
    edit = json.loads((target/'edit.json').read_text())
    after = edited_plan(prepared, 'plate', 'thickness', 7, literal_geometry('plate', 7))
    edit_centres = {**centres, 'plate': literal_geometry('plate', 7)['centreOfMass']}
    assert rejected(prepared, edit['snapshots']['before'], renames, centres, 'before') is None
    for label in ('recomputed', 'solved', 'probed'):
        assert rejected(after, edit['snapshots'][label], renames, edit_centres, label) is None, label
        assert rejected(prepared, edit['snapshots'][label], renames, centres, label), 'edit must be discriminated'
    sources.check_solver(after, edit['solver'], lambda ok, message, **d: None if ok else (_ for _ in ()).throw(AssertionError(message)))
    assert edit['solveReturnCode'] == 0
    for label in ('before', 'probed'):
        assert edit['snapshots'][label]['sources']['spacer'] == edit['snapshots']['before']['sources']['spacer']
    assert edit['snapshots']['probed']['sources']['plate']['parameters']['dim_thickness'] == 7
    q.native(target, 'inspect_copy', ('inspect-request.json', {'file': str(target/'edited.FCStd'), 'receipt': 'edited-reopen.json'}))
    reopened = json.loads((target/'edited-reopen.json').read_text())
    assert reopened['pid'] != edit['pid']
    for label in ('persisted', 'solved'):
        assert rejected(after, reopened['snapshots'][label], renames, edit_centres, label) is None, label
    q.check('sharedEditReopen', {'editPid': edit['pid'], 'reopenPid': reopened['pid'],
        'plateVolumes': {c: edit['snapshots']['probed']['components'][c]['shape']['volume'] for c in ('base', 'cover')},
        'spacerUnchanged': edit['snapshots']['probed']['sources']['spacer'],
        'recomputeAloneResolved': rejected(after, edit['snapshots']['recomputed'], renames, edit_centres, 'r') is None})

    # Relocated copy with every original input and the run directory unavailable.
    moved = directory/'moved'/'elsewhere'
    moved.mkdir(parents=True)
    shutil.copyfile(target/'model.FCStd', moved/'relocated.FCStd')
    for name in ('plan.json', 'built.json', 'runtime.zip'):
        shutil.copyfile(target/name, moved/name)
    hidden = directory/'workflow-unavailable'
    (directory/'workflow').rename(hidden)
    try:
        q.native(moved, 'inspect_copy', ('inspect-request.json', {'file': str(moved/'relocated.FCStd'), 'receipt': 'relocated.json'}))
    finally:
        hidden.rename(directory/'workflow')
    relocated = json.loads((moved/'relocated.json').read_text())
    for label in ('persisted', 'solved'):
        assert relocated['snapshots'][label]['documents'] == ['relocated']
        assert rejected(prepared, relocated['snapshots'][label], renames, centres, label) is None, label
    q.check('relocatedWithoutInputs', {'pid': relocated['pid'], 'documents': relocated['snapshots']['persisted']['documents']})

    # Saved-file tamper and malformed-archive negatives on copies.
    text = zipfile.ZipFile(workflow_attempt/'model.FCStd').read('Document.xml').decode()
    native = prepared['native']
    plate_varset, spacer_varset = plate['SchemaxisParameters'], spacer['SchemaxisParameters']
    top = native['mounts']['plate.top']
    tampers = {
        'sameValueMountExpressionRemoved': lambda t: in_object(in_object(t, top, '<ExpressionEngine count="1">', '<ExpressionEngine count="0">'),
                                                               top, '<Expression path=".AttachmentOffset.Base.z" expression="1 * %s.dim_thickness + 0 mm"/>' % plate_varset, ''),
        'unitlessMountExpression': lambda t: in_object(t, top, 'expression="1 * %s.dim_thickness + 0 mm"' % plate_varset, 'expression="1 * %s.dim_thickness"' % plate_varset),
        'coverLinksSpacer': lambda t: in_object(t, native['components']['cover'], 'name="%s"' % plate['N0'], 'name="%s"' % spacer['N0']),
        'spacerPadReadsPlate': lambda t: in_object(t, spacer['N2'], spacer_varset+'.dim_thickness', plate_varset+'.dim_thickness'),
        'spacerProfileReadsPlateSketch': lambda t: in_object(t, spacer['N2'], 'value="%s"' % spacer['N1'], 'value="%s"' % plate['N1']),
        'jointWrongMount': lambda t: in_object(t, native['joints']['spacerToCover'], native['mounts']['plate.side']+'.', native['mounts']['plate.top']+'.', 2),
        'clockingChanged': lambda t: in_property(in_property(t, native['joints']['baseToSpacer'], 'Offset1', 'Q2="0.70710678118654', 'Q2="0.00000000000000'),
                                                 native['joints']['baseToSpacer'], 'Offset1', 'Q3="0.70710678118654', 'Q3="1.00000000000000'),
        'offsetChanged': lambda t: in_object(t, native['joints']['spacerToCover'], 'Pz="2.0000000000000000"', 'Pz="2.5000000000000000"'),
        'componentMoved': lambda t: in_object(t, native['components']['spacer'], 'Pz="5.0000000000000000"', 'Pz="5.5000000000000000"'),
        'externalFileLink': lambda t: in_object(t, native['components']['spacer'], '<XLink file="" stamp="" name="%s"/>' % spacer['N0'], '<XLink file="../producer/model.FCStd" stamp="" name="N0"/>'),
        'groundMoved': lambda t: in_object(t, 'Ground', 'value="%s"' % native['components']['base'], 'value="%s"' % native['components']['spacer']),
        'jointDetached': lambda t: in_property(t, native['joints']['baseToSpacer'], 'Detach1', '<Bool value="false"', '<Bool value="true"'),
        'spacerParameterChanged': lambda t: in_object(t, spacer_varset, '<Float value="12.0000000000000000"/>', '<Float value="13.0000000000000000"/>'),
    }
    negatives = {}
    tampered = directory/'tampered'
    tampered.mkdir()
    for label, edit_text in tampers.items():
        path = tampered/(label+'.FCStd')
        try:
            rezip(target/'model.FCStd', path, {'Document.xml': edit_text})
        except AssertionError as error:
            negatives[label] = {'applied': False, 'anchor': str(error)}
            continue
        changed = zipfile.ZipFile(path).read('Document.xml') != zipfile.ZipFile(target/'model.FCStd').read('Document.xml')
        code = failures(lambda: verify_saved(prepared, path, renames, retained)) if changed else None
        negatives[label] = {'applied': changed, 'rejected': code}
    gui = zipfile.ZipFile(target/'model.FCStd').read('GuiDocument.xml').decode()
    gui_tampers = {'guiVisibilityFlipped': gui.replace('name="%s" expanded="0"><Properties Count="1" TransientCount="0"><Property name="Visibility" type="App::PropertyBool" status="1"><Bool value="true"' % native['components']['cover'],
                                                       'name="%s" expanded="0"><Properties Count="1" TransientCount="0"><Property name="Visibility" type="App::PropertyBool" status="1"><Bool value="false"' % native['components']['cover'], 1),
                   'guiProxyClassChanged': gui.replace('class="ViewProviderGroundedJoint"', 'class="ViewProviderJoint"', 1),
                   'guiForeignProxy': gui.replace('module="JointObject"', 'module="os"', 1)}
    for label, content in gui_tampers.items():
        path = tampered/(label+'.FCStd')
        rezip(target/'model.FCStd', path, {'GuiDocument.xml': lambda _t, c=content: c})
        negatives[label] = {'applied': content != gui, 'rejected': failures(lambda: verify_saved(prepared, path, renames, retained))}
    malformed = {'truncated': lambda p: p.write_bytes((target/'model.FCStd').read_bytes()[:4096]),
                 'notZip': lambda p: p.write_bytes(b'FreeCAD? no'),
                 'duplicateDocument': lambda p: rezip(target/'model.FCStd', p, extra=[('Document.xml', '<Document/>')]),
                 'escapingMember': lambda p: rezip(target/'model.FCStd', p, extra=[('../escape.txt', 'x')]),
                 'oversizedDeclared': lambda p: rezip(target/'model.FCStd', p, extra=[('padding.bin', b'\0'*(sources.SOURCE_BYTES+1))])}
    for label, make in malformed.items():
        path = tampered/(label+'.FCStd')
        make(path)
        negatives[label] = {'applied': True, 'rejected': failures(lambda: verify_saved(prepared, path, renames, retained))}
        if label == 'oversizedDeclared':
            path.unlink()  # keep the evidence bounded; the refusal is recorded
    link = tampered/'symlink.FCStd'
    link.symlink_to(target/'model.FCStd')
    negatives['symlinkedArtifact'] = {'applied': True, 'rejected': failures(lambda: verify_saved(prepared, link, renames, retained))}
    assert all(v['applied'] and v['rejected'] for v in negatives.values()), negatives
    q.check('savedNegatives', negatives)

    # Native reopening of tampered copies: the native observation must be rejected too.
    native_negatives = {}
    for label in ('sameValueMountExpressionRemoved', 'coverLinksSpacer', 'offsetChanged', 'spacerPadReadsPlate'):
        q.native(target, 'inspect_copy', ('inspect-request.json', {'file': str(tampered/(label+'.FCStd')), 'receipt': 'tampered-'+label+'.json'}))
        observed = json.loads((target/('tampered-'+label+'.json')).read_text())
        message = rejected(prepared, observed['snapshots']['persisted'], renames, centres, label)
        if label == 'spacerPadReadsPlate':
            # Native geometry may coincide; the saved-file oracle is the authority for history isolation.
            message = message or negatives[label]['rejected']
        assert message, label
        native_negatives[label] = message
    q.check('nativeTamperNegatives', native_negatives)

    # Standalone run: changed source bytes invalidate reuse and verification.
    standalone = directory/'standalone'
    producer = standalone/'plate'
    registry.run(PRODUCERS['plate'], producer, locations={'freecad': executable}, timeout=120)
    doc = {'version': 'schemaxis.freecad.assembly/1', 'units': 'mm',
           'parts': [{'id': 'plate', 'source': str(producer/'model.FCStd'),
                      'mounts': {'top': {'position': [0, 0, {'terms': {'thickness': 1}}]}, 'bottom': {}}}],
           'components': [{'id': 'lower', 'part': 'plate'}, {'id': 'upper', 'part': 'plate'}], 'grounded': 'lower',
           'joints': [{'id': 'stack', 'type': 'fixed', 'parent': {'component': 'lower', 'mount': 'top'},
                       'child': {'component': 'upper', 'mount': 'bottom'}, 'clocking': 180}]}
    registry.run(doc, standalone/'stack', locations={'freecad': executable}, timeout=120)
    first = registry.verify(standalone/'stack')
    hashes = registry.route_hook(doc, 'reusableInputs', legacy=True)(doc)
    # The optional GUI capture stage is refused for sourced assemblies (before any native stage).
    refused = failures(lambda: registry.run(doc, standalone/'gui-refused', locations={'freecad': executable, 'freecad_gui': executable}, timeout=60))
    assert refused == 'UNSUPPORTED_STAGE' and not (standalone/'gui-refused'/'model.FCStd').exists(), refused
    q.check('guiStageRefused', {'fault': refused})
    q.check('refreshedHashEndToEnd', refreshed_hash_cases(directory, doc, producer, standalone/'stack', executable))
    with zipfile.ZipFile(producer/'model.FCStd', 'a') as archive:
        archive.writestr('appended.txt', 'changed after the assembly was verified')
    after_hashes = {k: sources.digest(k) for k in hashes}
    invalidated = {'verify': failures(lambda: registry.verify(standalone/'stack')),
                   'plan': failures(lambda: registry.plan(doc, legacy=True))}
    assert hashes != after_hashes and invalidated['verify'] in ('INPUT_CHANGED', 'VERIFICATION_FAILED') and invalidated['plan'] == 'INPUT_CHANGED'
    q.check('standaloneInvalidation', {'verified': first['verified'], 'before': hashes, 'after': after_hashes, 'faults': invalidated})

    q.report['sourceDigestAtEnd'] = source_digest('freecad')
    q.report['sourceUnchangedDuringRun'] = q.report['sourceDigestAtEnd'] == q.report['sourceDigest']
    q.report.update(verified=q.report['sourceUnchangedDuringRun'], seconds=time.time()-q.report['started'])
    q.save()
    return q.report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--executable', required=True, help='absolute FreeCAD command-line launcher')
    arguments = parser.parse_args()
    print(json.dumps(qualify(arguments.directory, arguments.executable)['checks'].keys().__repr__()))
