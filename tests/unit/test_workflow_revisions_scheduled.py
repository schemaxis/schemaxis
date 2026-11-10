"""Revisions of simple completed scheduled parents, with the native layer replaced.

FreeCAD and Gmsh routes are scheduled by their manifests, so even a two-operation
workflow with no authored execution, axes or studies is run by the scheduler and
retains its producer under ``<operation>/batch-0/attempt-NNNN``. Only the native
run and its provider verification are replaced; scheduling, path resolution,
handoff provenance and the revision checks are the real code.

Copyright (C) 2026 David L. F. Gaden
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from schemaxis import adaptor_runtime
from schemaxis import parallel
from schemaxis.adaptors import registry
from schemaxis import storage
from schemaxis import workflow_revisions as revisions
from schemaxis.__main__ import main
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail
from schemaxis.workflow import execute, verify


ROOT = Path(__file__).resolve().parents[2]
STEP = (ROOT / 'examples' / 'schemaxis' / 'freecad-import-step-bracket.step').read_bytes()
EDITED = STEP.replace(b'Schemaxis qualification part', b'Schemaxis qualification part, edited')
POINTER = '/nodes/0/options/file'
PRODUCED = 'batch-0/attempt-0001/body.step'
IMPORT = {'units': 'inch', 'orientation': {'z': '+Y', 'x': '+X'},
          'placement': {'position': [100, 50, 0], 'clocking': 90}, 'refine': True,
          'expect': {'volume': {'value': 10840.0, 'relativeTolerance': 1e-06},
                     'centreOfMass': {'value': [-0.808118, -0.243542, 5.0], 'tolerance': 0.01},
                     'bounds': {'value': [-20, 20, -15, 15, 0, 10], 'tolerance': 0.01},
                     'points': {'inside': [[0, 0, 5], [15, -6, 5]], 'outside': [[-9, -6, 5], [15, 6, 5]],
                                'guard': 0.5}}}


def cli(*args):
    with mock.patch.object(sys, 'argv', ['schemaxis', *args]):
        return main()


def box():
    return {'version': 'schemaxis.freecad/1', 'units': 'mm', 'output': 'body', 'nodes': [
        {'id': 'body', 'filter': 'box', 'options': {'length': 20, 'width': 10, 'height': 5}}]}


def workflow(consumer='freecad', index=0):
    """A producer followed by one consumer reading its artifact; both routes are scheduled."""
    reference = {'$artifact': 'cad', 'index': index}
    if consumer == 'freecad':
        document = {'version': 'schemaxis.freecad/1', 'units': 'mm', 'output': 'part', 'nodes': [
            {'id': 'part', 'filter': 'importSTEP', 'options': {**IMPORT, 'file': reference}}]}
    else:
        document = {'version': 'schemaxis.gmsh/1', 'units': 'mm', 'output': 'mesh', 'nodes': [
            {'id': 'solid', 'filter': 'readSTEP', 'options': {'file': reference}},
            {'id': 'mesh', 'filter': 'tetrahedral', 'inputs': {'input': 'solid'},
             'options': {'size': 2.5, 'volumeName': 'part', 'boundaryName': 'outside',
                         'volumeTolerance': 1e-06}}]}
    return {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'cad', 'document': box()}, {'id': 'reimport', 'document': document}]}


def swept(document, option, values):
    """The document with one option driven by a document-level axis, which makes it a native study."""
    result = copy.deepcopy(document)
    result['axes'] = [{'name': 'axis', 'values': list(values)}]
    result['nodes'][0]['options'][option] = {'$axis': 'axis'}
    return result


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(root):
    """Byte-for-byte inventory of a retained directory."""
    return {str(path.relative_to(root)): (path.read_bytes() if path.is_file() else None)
            for path in sorted(Path(root).rglob('*'))}


def load(path):
    return json.loads(Path(path).read_text())


def store(path, value):
    Path(path).write_text(json.dumps(value))


class Native:
    """Real artifact bytes and the verification semantics of a receipt, without an application."""

    def __init__(self):
        self.calls, self.consumed = [], []
        self.during = None
        self.extra = False
        self.fail_boxes = 0

    def run(self, effective, target, *_, **__):
        """Run through the shared adaptor runtime, as every registered route does."""
        route = registry.resolve(effective, legacy=True)[1]
        return adaptor_runtime.execute(effective, Path(target), route, self.state, self.check,
                                       lambda document: None, timeout=300)

    def state(self, effective, target, **_):
        target = Path(target)
        target.mkdir(parents=True)
        store(target / 'authored.json', effective)
        node = effective['nodes'][0]
        self.calls.append(node['filter'])
        if node['filter'] == 'box':
            if self.fail_boxes:
                self.fail_boxes -= 1
                fail('RUNNER_FAILED', 'simulated interruption', str(target))
            files = {'body.step': STEP}
            if self.extra:
                files['second.step'] = EDITED
        else:
            source = Path(node['options']['file'])
            self.consumed.append((str(source), source.read_bytes()))
            if self.during:
                self.during(source)
            files = {'part.step': source.read_bytes()}
        artifacts = []
        for name, payload in files.items():
            (target / name).write_bytes(payload)
            artifacts.append({'file': str(target / name), 'sha256': digest(target / name), 'kind': 'cad'})
        store(target / 'verification.json', {'artifacts': artifacts})
        return {'status': 'succeeded', 'verified': True}

    def verify(self, directory, expected):
        """Scheduler-level verification of one retained attempt, plain or multi-state."""
        if adaptor_runtime.is_common(directory):
            route = registry.resolve(expected, legacy=True)[1]
            adaptor_runtime.verify(directory, expected, route, self.check)
        else:
            self.check(directory, expected)
        return load(Path(directory) / 'verification.json')

    @staticmethod
    def check(directory, expected):
        directory = Path(directory)
        if load(directory / 'authored.json') != expected:
            fail('VERIFICATION_FAILED', 'attempt input differs from requested input', str(directory))
        receipt = load(directory / 'verification.json')
        for artifact in receipt['artifacts']:
            if digest(artifact['file']) != artifact['sha256']:
                fail('VERIFICATION_FAILED', 'artifact differs from its receipt', artifact['file'])
        return receipt


class ScheduledRevisionCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.native = Native()
        for patch in (mock.patch.object(parallel, 'run_native', self.native.run),
                      mock.patch.object(parallel, 'verify_native', self.native.verify),
                      mock.patch.object(parallel, 'retained_inputs', lambda directory, document: None),
                      mock.patch('schemaxis.publication_metadata.publish_artifacts'),
                      mock.patch('schemaxis.publication_metadata.finalise'),
                      mock.patch('schemaxis.publication_metadata.verify')):
            patch.start()
            self.addCleanup(patch.stop)

    def fault(self, code, function, *args, **kwargs):
        with self.assertRaises(SchemaxisError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def parent(self, document=None, name='parent'):
        result = execute(document or workflow(), self.root / name)
        self.assertEqual((result['status'], result['executionVersion']), ('succeeded', 2))
        return self.root / name

    def attempt(self, parent, operation='cad', number=1):
        return parent / operation / 'batch-0' / ('attempt-%04d' % number)

    def edited(self, parent, name='edit'):
        work = self.root / name / 'body.step'
        cli('revision', 'checkout', str(parent), '--consumer', 'reimport', '--pointer', POINTER,
            '--destination', str(work))
        work.write_bytes(EDITED)
        return work

    def prepared(self, parent, name='rev'):
        work = self.edited(parent, name + '-edit')
        output = self.root / name / 'revision.json'
        cli('revision', 'prepare', str(parent), '--consumer', 'reimport', '--pointer', POINTER,
            '--replacement', str(work), '--snapshot', str(self.root / name / 'snapshot'),
            '--reason', 'changed the saved STEP description', '--output', str(output))
        return load(output), output


class ScheduledParentWorkflowTests(ScheduledRevisionCase):
    def test_auto_scheduled_parent_is_edited_rerun_and_verified_without_touching_the_parent(self):
        parent = self.parent()
        authored = load(parent / 'authored.json')
        self.assertFalse({'execution', 'dimensions', 'definitions', 'settings', 'axes'} & set(authored))
        self.assertFalse(any('execution' in operation for operation in authored['operations']))
        self.assertTrue((parent / 'cad' / 'batch-0' / 'attempt-0001' / 'body.step').is_file())
        before = tree(parent)
        work = self.root / 'work' / 'body.step'
        checked = cli('revision', 'checkout', str(parent), '--consumer', 'reimport', '--pointer', POINTER,
                      '--destination', str(work))
        self.assertEqual(checked['selection'], {'producer': 'cad', 'index': 0, 'kind': 'cad', 'file': PRODUCED,
                                                'sha256': digest(parent / 'cad' / PRODUCED)})
        self.assertEqual(checked['original'], {'$artifact': 'cad', 'index': 0})
        self.assertEqual(work.read_bytes(), STEP)
        work.write_bytes(EDITED)
        output = self.root / 'rev' / 'revision.json'
        cli('revision', 'prepare', str(parent), '--consumer', 'reimport', '--pointer', POINTER,
            '--replacement', str(work), '--snapshot', str(self.root / 'rev' / 'snapshot'),
            '--reason', 'changed the saved STEP description', '--output', str(output))
        document = load(output)
        self.assertEqual(document['parent']['authoredDigest'], storage.digest(workflow()))
        self.assertEqual(document['selection'], checked['selection'])
        planned = cli('plan', str(output))
        self.assertEqual(planned['version'], 'schemaxis.revision.plan/1')
        self.assertEqual(planned['plan']['version'], 'schemaxis.workflow.plan/2')
        self.native.calls.clear()
        result = cli('run', str(output), '--backend', 'native', '--output-directory', str(self.root / 'child'))
        self.assertEqual(self.native.calls, ['box', 'importSTEP'])
        self.assertEqual((result['rerun'], result['reused']), (['cad', 'reimport'], []))
        source, payload = self.native.consumed[-1]
        self.assertEqual(Path(source), self.root / 'rev' / 'snapshot' / 'data' / 'body.step')
        self.assertEqual(payload, EDITED)
        child = self.root / 'child' / 'workflow'
        self.assertEqual(load(child / 'result.json')['executionVersion'], 2)
        self.assertEqual(load(child / 'authored.json')['operations'][1]['document']['nodes'][0]['options']['file'],
                         document['replacement'])
        self.assertEqual((child / 'reimport' / 'batch-0' / 'attempt-0001' / 'part.step').read_bytes(), EDITED)
        report = cli('verify', str(self.root / 'child'))
        self.assertTrue(report['verified'])
        self.assertEqual(report['replacementDigest'], document['replacement']['digest'])
        self.assertEqual(tree(parent), before)
        self.assertTrue(verify(parent)['verified'])

    def test_selection_binds_the_recorded_attempt_after_a_resumed_producer(self):
        self.native.fail_boxes = 1
        directory = self.root / 'resumed'
        with self.assertRaises(SchemaxisError):
            execute(workflow(), directory)
        result = execute(workflow(), directory, resume=True)
        self.assertEqual(result['status'], 'succeeded')
        self.assertTrue(self.attempt(directory).is_dir() and self.attempt(directory, number=2).is_dir())
        checked = revisions.checkout(directory, 'reimport', POINTER, self.root / 'resumed-edit.step')
        self.assertEqual(checked['selection']['file'], 'batch-0/attempt-0002/body.step')
        self.assertEqual(checked['selection']['sha256'], digest(self.attempt(directory, number=2) / 'body.step'))

    def test_second_artifact_of_the_one_visit_can_be_selected(self):
        self.native.extra = True
        parent = self.parent(workflow(index=1))
        checked = revisions.checkout(parent, 'reimport', POINTER, self.root / 'second.step')
        self.assertEqual(checked['selection']['index'], 1)
        self.assertEqual(checked['selection']['file'], 'batch-0/attempt-0001/second.step')
        self.assertEqual((self.root / 'second.step').read_bytes(), EDITED)
        document, _ = self.prepared(parent)
        self.assertEqual(revisions.execute(document, self.root / 'second-child')['status'], 'succeeded')
        self.assertEqual(revisions.verify(self.root / 'second-child')['revision'], revisions.VERSION)

    def test_gmsh_consumer_of_a_freecad_producer_is_selected_on_the_real_routes(self):
        parent = self.parent(workflow('gmsh'))
        self.assertEqual(load(parent / 'authored.json')['operations'][1]['document']['version'], 'schemaxis.gmsh/1')
        before = tree(parent)
        checked = revisions.checkout(parent, 'reimport', POINTER, self.root / 'gmsh-edit' / 'body.step')
        self.assertEqual(checked['selection']['kind'], 'cad')
        self.assertEqual(checked['selection']['file'], PRODUCED)
        self.assertEqual((self.root / 'gmsh-edit' / 'body.step').read_bytes(), STEP)
        self.assertEqual(tree(parent), before)

    def test_destinations_inside_scheduled_attempts_are_refused(self):
        parent = self.parent()
        before = tree(parent)
        for destination in (self.attempt(parent) / 'copy.step', parent / 'cad' / 'copy.step', parent / 'x.step'):
            with self.subTest(str(destination)):
                self.fault('REVISION_OVERLAP', revisions.checkout, parent, 'reimport', POINTER, destination)
        work = self.edited(parent)
        snapshot = self.attempt(parent) / 'snapshot'
        self.fault('REVISION_OVERLAP', revisions.prepare, parent, 'reimport', POINTER, work, snapshot, 'reason')
        self.assertFalse(snapshot.exists())
        document, _ = self.prepared(parent)
        self.fault('REVISION_OVERLAP', revisions.execute, document, self.attempt(parent) / 'child')
        self.assertEqual(tree(parent), before)


class ScheduledParentAdmissionTests(ScheduledRevisionCase):
    def test_authored_execution_composition_and_studies_are_still_refused(self):
        destination = self.root / 'unused.step'
        execution = {'maxWorkers': 1, 'cpus': 1, 'memoryMB': 2048, 'gpus': 0}
        cases = {'top-level execution': {'execution': execution},
                 'settings': {'settings': {'size': 2}},
                 'definitions': {'definitions': {'size': 2}},
                 'axes': {'axes': [{'name': 'size', 'values': [1, 2]}]}}
        for name, extra in cases.items():
            with self.subTest(name):
                parent = self.root / name.replace(' ', '-')
                (parent).mkdir()
                store(parent / 'authored.json', {**workflow(), **extra})
                store(parent / 'result.json', {'executionVersion': 2, 'status': 'succeeded', 'verified': True})
                self.fault('REVISION_UNSUPPORTED', revisions.checkout, parent, 'reimport', POINTER, destination)
        document = workflow()
        document['operations'][0]['execution'] = {'threads': 1}
        parent = self.parent(document, 'operation-execution')
        self.fault('REVISION_UNSUPPORTED', revisions.checkout, parent, 'reimport', POINTER, destination)
        self.assertFalse(destination.exists())

    def test_unrecognised_scheduler_versions_and_unfinished_parents_are_refused(self):
        parent = self.parent()
        saved = load(parent / 'result.json')
        destination = self.root / 'unused.step'
        try:
            store(parent / 'result.json', {**saved, 'executionVersion': 3})
            self.fault('REVISION_UNSUPPORTED', revisions.checkout, parent, 'reimport', POINTER, destination)
            for fields in ({'status': 'failed', 'verified': False}, {'status': 'incomplete', 'verified': False},
                           {'verified': False}):
                with self.subTest(fields=fields):
                    store(parent / 'result.json', {**saved, **fields})
                    self.fault('INCOMPLETE_EXECUTION', revisions.checkout, parent, 'reimport', POINTER,
                               destination)
        finally:
            store(parent / 'result.json', saved)
        self.assertFalse(destination.exists())
        self.assertEqual(revisions.checkout(parent, 'reimport', POINTER, destination)['selection']['file'],
                         PRODUCED)

    def test_failed_scheduled_parent_is_not_a_revision_parent(self):
        self.native.fail_boxes = 1
        with self.assertRaises(SchemaxisError):
            execute(workflow(), self.root / 'failed')
        self.assertEqual(load(self.root / 'failed' / 'result.json')['status'], 'failed')
        self.fault('INCOMPLETE_EXECUTION', revisions.checkout, self.root / 'failed', 'reimport', POINTER,
                   self.root / 'unused.step')

    def test_consumer_fields_that_are_not_direct_producer_references_are_refused(self):
        parent = self.parent()
        destination = self.root / 'unused.step'
        for pointer, code in (('/nodes/0/options/units', 'REVISION_UNSUPPORTED'),
                              ('/nodes/0/options', 'REVISION_UNSUPPORTED'),
                              ('/nodes/0/options/file/index', 'REVISION_UNSUPPORTED'),
                              ('/nodes/3', 'INVALID_REVISION')):
            with self.subTest(pointer):
                self.fault(code, revisions.checkout, parent, 'reimport', pointer, destination)
        self.fault('INVALID_REVISION', revisions.checkout, parent, 'absent', POINTER, destination)
        self.assertFalse(destination.exists())

    def test_adopted_consumer_field_is_not_a_producer_artifact(self):
        parent = self.parent()
        work = self.edited(parent)
        adopted = cli('input', 'adopt', str(work), str(self.root / 'adopted'))
        document = workflow()
        document['operations'][1]['document']['nodes'][0]['options']['file'] = adopted['reference']
        captured = self.parent(document, 'captured-parent')
        self.fault('REVISION_UNSUPPORTED', revisions.checkout, captured, 'reimport', POINTER,
                   self.root / 'unused.step')
        self.assertEqual(tree(captured)['authored.json'], (captured / 'authored.json').read_bytes())

    def test_revisions_cannot_be_parents_of_revisions(self):
        parent = self.parent()
        document, _ = self.prepared(parent)
        revisions.execute(document, self.root / 'child')
        self.assertEqual(load(self.root / 'child' / 'workflow' / 'result.json')['executionVersion'], 2)
        for candidate in (self.root / 'child', self.root / 'child' / 'workflow'):
            with self.subTest(str(candidate)):
                self.fault('REVISION_PARENT_UNSUPPORTED', revisions.checkout, candidate, 'reimport', POINTER,
                           self.root / 'unused.step')
                self.fault('REVISION_PARENT_UNSUPPORTED', revisions.prepare, candidate, 'reimport', POINTER,
                           self.root / 'unused.step', self.root / 'unused-snapshot', 'reason')
        self.assertFalse((self.root / 'unused-snapshot').exists())


class ScheduledEvidenceTests(ScheduledRevisionCase):
    """Rebound, duplicated or altered scheduler evidence is refused by the public path and by selection."""

    def select(self, parent, authored=None):
        document = authored or load(parent / 'authored.json')
        return revisions._select(parent, document, 'reimport', POINTER)

    def test_extra_missing_and_unfinished_visits_are_ambiguous(self):
        parent = self.parent()
        saved = load(parent / 'result.json')
        producer = next(job for job in saved['jobs'] if job['operation'] == 'cad')
        cases = {'extra producer visit': {**saved, 'jobs': [producer, *saved['jobs']]},
                 'missing consumer visit': {**saved, 'jobs': [producer]},
                 'extra batch': {**saved, 'jobs': [{**producer, 'batch': 1}, saved['jobs'][1]]},
                 'unfinished visit': {**saved, 'jobs': [{**producer, 'status': 'failed'}, saved['jobs'][1]]}}
        for name, changed in cases.items():
            with self.subTest(name):
                store(parent / 'result.json', changed)
                self.fault('REVISION_UNSUPPORTED', self.select, parent)
                self.assertRaises(SchemaxisError, revisions.checkout, parent, 'reimport', POINTER,
                                  self.root / ('unused-' + name.replace(' ', '-')))
        store(parent / 'result.json', saved)
        self.assertEqual(self.select(parent)[0]['file'], PRODUCED)

    def test_rebound_attempts_are_refused(self):
        parent = self.parent()
        saved = load(parent / 'result.json')
        producer = saved['jobs'][0]
        other = self.attempt(parent, number=2)
        other.mkdir()
        for name in ('authored.json', 'verification.json'):
            (other / name).write_bytes((self.attempt(parent) / name).read_bytes())
        (other / 'body.step').write_bytes(EDITED)
        receipt = load(other / 'verification.json')
        receipt['artifacts'][0].update(file=str(other / 'body.step'), sha256=digest(other / 'body.step'))
        store(other / 'verification.json', receipt)
        self.native.verify(other, producer['effective'])

        def rebind(**fields):
            store(parent / 'result.json', {**saved, 'jobs': [{**producer, **fields}, saved['jobs'][1]]})

        rebind(directory=str(other))
        self.fault('REVISION_PARENT_INVALID', self.select, parent)
        self.fault('VERIFICATION_FAILED', revisions.checkout, parent, 'reimport', POINTER, self.root / 'one.step')
        rebind(directory=str(parent / 'cad' / 'batch-0'))
        self.fault('REVISION_PARENT_INVALID', self.select, parent)
        rebind(directory=str(self.attempt(parent, 'reimport')))
        self.fault('REVISION_PARENT_INVALID', self.select, parent)
        rebind(directory=str(self.root))
        self.fault('REVISION_PARENT_INVALID', self.select, parent)
        rebind(directory=str(self.attempt(parent) / '..' / 'attempt-0002'))
        self.fault('REVISION_PARENT_INVALID', self.select, parent)
        store(parent / 'result.json', saved)
        original = self.select(parent)
        self.assertEqual(original[0]['file'], PRODUCED)
        moved = parent / 'cad' / 'batch-0' / 'moved'
        self.attempt(parent).rename(moved)
        self.attempt(parent).symlink_to(moved)
        self.fault('REVISION_PARENT_INVALID', self.select, parent)
        self.assertFalse((self.root / 'one.step').exists())

    def test_consumer_that_received_a_different_artifact_or_field_is_refused(self):
        parent = self.parent()
        saved = load(parent / 'result.json')
        consumer = saved['jobs'][1]
        cases = {'sha256': {**consumer, 'handoffs': [{**consumer['handoffs'][0], 'sha256': '0' * 64}]},
                 'file': {**consumer, 'handoffs': [{**consumer['handoffs'][0],
                                                    'file': str(self.attempt(parent) / 'other.step')}]},
                 'index': {**consumer, 'handoffs': [{**consumer['handoffs'][0], 'index': 1}]},
                 'producer': {**consumer, 'handoffs': [{**consumer['handoffs'][0], 'from': 'reimport'}]},
                 'no handoff': {**consumer, 'handoffs': []},
                 'other field': {**consumer, 'effective': {**consumer['effective'], 'nodes': [
                     {'id': 'part', 'filter': 'importSTEP', 'options': {**IMPORT, 'file': '/elsewhere'}}]}}}
        for name, changed in cases.items():
            with self.subTest(name):
                store(parent / 'result.json', {**saved, 'jobs': [saved['jobs'][0], changed]})
                self.fault('REVISION_PARENT_INVALID', self.select, parent)
                self.assertRaises(SchemaxisError, revisions.checkout, parent, 'reimport', POINTER,
                                  self.root / ('unused-' + name.replace(' ', '-')))
        store(parent / 'result.json', saved)

    def test_ambiguous_or_unsupported_artifacts_in_a_scheduled_attempt_are_refused(self):
        parent = self.parent()
        path = self.attempt(parent) / 'verification.json'
        original = load(path)
        artifact = original['artifacts'][0]
        cases = {'distributed': {'publicationMode': 'native-distributed'},
                 'two members': {'files': [{'file': artifact['file'], 'sha256': artifact['sha256']},
                                           {'file': 'piece.step', 'sha256': '0' * 64}]},
                 'companion': {'files': [{'file': str(self.attempt(parent) / 'piece.step'),
                                          'sha256': artifact['sha256']}]},
                 'wrong kind': {'kind': 'table'}}
        (self.attempt(parent) / 'piece.step').write_bytes(STEP)
        codes = {'wrong kind': 'TYPE_MISMATCH'}
        for name, fields in cases.items():
            with self.subTest(name):
                changed = copy.deepcopy(original)
                changed['artifacts'][0].update(fields)
                store(path, changed)
                self.fault(codes.get(name, 'REVISION_UNSUPPORTED'), self.select, parent)
        store(path, {**original, 'states': [{}, {}]})
        self.fault('REVISION_UNSUPPORTED', self.select, parent)
        store(path, original)
        document = load(parent / 'authored.json')
        document['operations'][1]['document']['nodes'][0]['options']['file']['index'] = 1
        self.fault('INVALID_SELECTION', self.select, parent, document)
        self.assertEqual(self.select(parent)[0]['file'], PRODUCED)

    def test_tampered_scheduled_parent_is_refused_publicly_before_and_after_preparation(self):
        parent = self.parent()
        destination = self.root / 'unused.step'
        step = self.attempt(parent) / 'body.step'
        step.write_bytes(STEP + b' ')
        self.fault('VERIFICATION_FAILED', revisions.checkout, parent, 'reimport', POINTER, destination)
        step.write_bytes(STEP)
        document, _ = self.prepared(parent)
        before = tree(parent)
        step.write_bytes(EDITED)
        for function, argument in ((revisions.execute, self.root / 'after-tamper'),
                                   (revisions.plan, None)):
            with self.subTest(function.__name__):
                self.fault('VERIFICATION_FAILED', function, *([document] + ([argument] if argument else [])))
        self.assertFalse((self.root / 'after-tamper').exists())
        step.write_bytes(STEP)
        authored = self.attempt(parent) / 'authored.json'
        original = authored.read_bytes()
        store(authored, {**load(authored), 'units': 'm'})
        self.fault('VERIFICATION_FAILED', revisions.plan, document)
        authored.write_bytes(original)
        job = parent / 'result.json'
        saved = load(job)
        store(job, {**saved, 'jobs': [{**saved['jobs'][0], 'effective': box() | {'units': 'm'}}, saved['jobs'][1]]})
        self.fault('VERIFICATION_FAILED', revisions.plan, document)
        job.write_text(json.dumps(saved))
        self.assertEqual(revisions.plan(document)['version'], 'schemaxis.revision.plan/1')
        self.assertEqual(tree(parent).keys(), before.keys())

    def test_revision_record_rebound_to_another_attempt_or_artifact_is_refused(self):
        parent = self.parent()
        document, _ = self.prepared(parent)
        cases = {'attempt': ('selection', {**document['selection'], 'file': 'batch-0/attempt-0002/body.step'}),
                 'file name': ('selection', {**document['selection'], 'file': 'batch-0/attempt-0001/second.step'}),
                 'legacy layout': ('selection', {**document['selection'], 'file': 'body.step'}),
                 'sha256': ('selection', {**document['selection'], 'sha256': '0' * 64}),
                 'producer': ('selection', {**document['selection'], 'producer': 'reimport'}),
                 'child': ('child', {'authoredDigest': '1' * 64})}
        for name, (field, value) in cases.items():
            with self.subTest(name):
                changed = {**copy.deepcopy(document), field: value}
                self.fault('REVISION_MISMATCH', revisions.execute, changed, self.root / ('rebound-' + name))
                self.assertFalse((self.root / ('rebound-' + name)).exists())

    def test_captured_replacement_changes_and_consumer_edits_fail_the_scheduled_child(self):
        parent = self.parent()
        before = tree(parent)
        document, _ = self.prepared(parent)
        snapshot = Path(document['replacement']['$resource'])
        member = snapshot / 'data' / 'body.step'
        stable = self.root / 'stable'
        self.assertEqual(revisions.execute(document, stable)['status'], 'succeeded')
        member.write_bytes(EDITED + b' ')
        self.fault('RESOURCE_MISMATCH', revisions.execute, document, self.root / 'changed')
        self.fault('RESOURCE_MISMATCH', revisions.verify, stable)
        self.assertFalse((self.root / 'changed').exists())
        member.unlink()
        self.fault('RESOURCE_MISMATCH', revisions.execute, document, self.root / 'missing')
        member.write_bytes(EDITED)
        self.assertEqual(revisions.verify(stable)['revision'], revisions.VERSION)
        self.native.during = lambda source: source.write_bytes(STEP)
        self.fault('RESOURCE_MISMATCH', revisions.execute, document, self.root / 'during')
        failed = load(self.root / 'during' / 'result.json')
        self.assertEqual((failed['status'], failed['verified']), ('failed', False))
        self.assertTrue((self.root / 'during' / 'workflow' / 'cad' / 'batch-0').is_dir())
        self.fault('RESOURCE_MISMATCH', revisions.verify, self.root / 'during')
        member.write_bytes(EDITED)
        self.assertEqual(tree(parent), before)
        self.assertTrue(verify(parent)['verified'])

    def test_cancelled_scheduled_child_keeps_both_histories(self):
        parent = self.parent()
        before = tree(parent)
        document, _ = self.prepared(parent)

        def interrupt(source):
            raise KeyboardInterrupt
        self.native.during = interrupt
        with self.assertRaises((KeyboardInterrupt, SchemaxisError)):
            revisions.execute(document, self.root / 'cancelled')
        saved = load(self.root / 'cancelled' / 'result.json')
        self.assertNotEqual(saved['status'], 'succeeded')
        self.assertFalse(saved['verified'])
        self.assertTrue((self.root / 'cancelled' / 'workflow' / 'cad' / 'batch-0').is_dir())
        self.fault('INCOMPLETE_EXECUTION', revisions.verify, self.root / 'cancelled')
        self.assertEqual(tree(parent), before)
        self.native.during = None
        self.assertEqual(revisions.execute(document, self.root / 'recovered')['status'], 'succeeded')


class ScheduledSingleVisitTests(ScheduledRevisionCase):
    """Every operation of a scheduled parent is one batch with one native visit.

    ``study_required`` only sees ``$analytic`` expressions and workflow-level
    axes, so a document-level ``axes`` list lets the scheduler run one batch
    holding several native states. Those parents are refused wherever the
    study sits; a study with a single state is not a second visit.
    """

    def three(self, **documents):
        document = workflow()
        document['operations'].append({'id': 'sweep', 'document': box()})
        for operation in document['operations']:
            if operation['id'] in documents:
                operation['document'] = documents[operation['id']]
        return document

    def assert_batches(self, document, parent, states):
        from schemaxis.parallel import work_items
        from schemaxis.workflow import study_required
        self.assertFalse(study_required(document))
        jobs = work_items(document)[2]
        self.assertEqual([(job['operation'], job['batch']) for job in jobs],
                         [('cad', 0), ('reimport', 0), ('sweep', 0)])
        saved = load(parent / 'result.json')
        self.assertEqual([(job['operation'], job['batch']) for job in saved['jobs']],
                         [(job['operation'], job['batch']) for job in jobs])
        for operation, count in states.items():
            receipt = load(self.attempt(parent, operation) / 'verification.json')
            self.assertEqual(len(receipt.get('states', [None])), count, operation)
        self.assertTrue(verify(parent)['verified'])

    def refused(self, document, operation, count):
        parent = self.parent(document)
        self.assert_batches(document, parent, {operation: count})
        before = tree(parent)
        work = self.root / 'unused' / 'body.step'
        fault = self.fault('REVISION_UNSUPPORTED', revisions.checkout, parent, 'reimport', POINTER, work)
        self.assertEqual(fault.to_dict()['observed']['operation'], operation)
        self.assertEqual(fault.to_dict()['observed']['states'], count)
        self.assertFalse(work.exists())
        edit = self.root / 'edit.step'
        edit.write_bytes(EDITED)
        snapshot = self.root / 'snapshot'
        self.fault('REVISION_UNSUPPORTED', revisions.prepare, parent, 'reimport', POINTER, edit, snapshot, 'r')
        self.assertFalse(snapshot.exists())
        self.assertEqual(tree(parent), before)

    def test_unrelated_multi_state_operation_is_refused(self):
        self.refused(self.three(sweep=swept(box(), 'width', [10, 20])), 'sweep', 2)

    def test_multi_state_consumer_is_refused(self):
        consumer = swept(workflow()['operations'][1]['document'], 'refine', [True, False])
        self.refused(self.three(reimport=consumer), 'reimport', 2)

    def test_multi_state_producer_is_refused(self):
        self.refused(self.three(cad=swept(box(), 'width', [10, 20])), 'cad', 2)

    def test_scheduler_records_for_other_operations_cannot_be_extended(self):
        document = self.three()
        parent = self.parent(document)
        saved = load(parent / 'result.json')
        for name, jobs in (('extra batch', [*saved['jobs'], {**saved['jobs'][2], 'batch': 1}]),
                           ('extra visit', [*saved['jobs'], saved['jobs'][2]]),
                           ('missing', saved['jobs'][:2])):
            with self.subTest(name):
                store(parent / 'result.json', {**saved, 'jobs': jobs})
                self.fault('VERIFICATION_FAILED', revisions.checkout, parent, 'reimport', POINTER,
                           self.root / 'unused.step')
        store(parent / 'result.json', saved)
        self.assertEqual(revisions.checkout(parent, 'reimport', POINTER,
                                            self.root / 'ok.step')['selection']['file'], PRODUCED)

    def test_single_state_studies_are_not_second_visits(self):
        document = self.three(cad=swept(box(), 'width', [10]),
                              reimport=swept(workflow()['operations'][1]['document'], 'refine', [True]),
                              sweep=swept(box(), 'width', [10]))
        parent = self.parent(document)
        self.assert_batches(document, parent, {'cad': 1, 'reimport': 1, 'sweep': 1})
        before = tree(parent)
        work = self.root / 'work' / 'body.step'
        checked = revisions.checkout(parent, 'reimport', POINTER, work)
        self.assertEqual(checked['selection']['file'], 'batch-0/attempt-0001/state-00000/body.step')
        work.write_bytes(EDITED)
        output = self.root / 'rev' / 'revision.json'
        prepared = revisions.prepare(parent, 'reimport', POINTER, work, self.root / 'rev' / 'snapshot', 'edit')
        self.assertEqual(revisions.execute(prepared, self.root / 'child')['status'], 'succeeded')
        self.assertEqual(self.native.consumed[-1][1], EDITED)
        self.assertTrue(revisions.verify(self.root / 'child')['verified'])
        self.assertEqual(tree(parent), before)

    def test_plain_scheduled_operations_remain_admitted(self):
        document = self.three()
        parent = self.parent(document)
        self.assert_batches(document, parent, {'cad': 1, 'reimport': 1, 'sweep': 1})
        self.assertEqual(revisions.checkout(parent, 'reimport', POINTER,
                                            self.root / 'plain.step')['selection']['file'], PRODUCED)


if __name__ == '__main__':
    unittest.main()
