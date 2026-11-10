import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from schemaxis import storage
from schemaxis.__main__ import main
from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow_revisions as revisions
from schemaxis.workflow import execute, verify


TRIANGLE = '''<?xml version="1.0"?>
<VTKFile type="PolyData" version="0.1"><PolyData><Piece NumberOfPoints="3" NumberOfPolys="1">
<Points><DataArray type="Float64" NumberOfComponents="3" format="ascii">0 0 0 1 0 0 0 1 0</DataArray></Points>
<Polys><DataArray type="Int64" Name="connectivity" format="ascii">0 1 2</DataArray>
<DataArray type="Int64" Name="offsets" format="ascii">3</DataArray></Polys></Piece></PolyData></VTKFile>
'''
POINTER = '/nodes/0/options/files/0'


def cli(*args):
    with mock.patch.object(sys, 'argv', ['schemaxis', *args]):
        return main()


def workflow(reader='readSurface'):
    return {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'produce', 'document': {'version': 'schemaxis/1',
                                       'nodes': [{'id': 'ball', 'filter': 'sphere', 'options': {'radius': 2}}],
                                       'scenes': [{'id': 'shape', 'geometry': ['ball']}]}},
        {'id': 'consume', 'document': {'version': 'schemaxis/1', 'nodes': [
            {'id': 'surface', 'filter': reader, 'options': {'files': [{'$artifact': 'produce', 'index': 0}]}},
            {'id': 'moved', 'filter': 'transform', 'inputs': {'input': 'surface'},
             'options': {'translate': [1, 2, 3]}}],
            'scenes': [{'id': 'shifted', 'geometry': ['moved']}]}}]}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(root):
    """Byte-for-byte inventory of a retained directory."""
    return {str(path.relative_to(root)): (path.read_bytes() if path.is_file() else None)
            for path in sorted(Path(root).rglob('*'))}


class FakeNative:
    """Host-only stand-in for subprocess native execution with real artifact bytes."""

    def __init__(self):
        self.calls, self.consumed, self.during = [], [], None

    def run(self, effective, target, **_):
        target.mkdir(parents=True)
        (target / 'authored.json').write_text(json.dumps(effective))
        reader = effective['nodes'][0]
        self.calls.append(target.name)
        if reader['filter'] == 'sphere':
            output = target / 'surface.vtp'
            output.write_text(TRIANGLE)
        else:
            source = Path(reader['options']['files'][0])
            self.consumed.append((str(source), source.read_text()))
            if self.during:
                self.during(source)
            output = target / 'moved.vtp'
            output.write_text(source.read_text())
        artifact = {'file': str(output), 'sha256': digest(output), 'kind': 'geometry'}
        (target / 'verification.json').write_text(json.dumps({'artifacts': [artifact]}))
        return {'status': 'succeeded', 'verified': True}

    @staticmethod
    def verify(target, effective, outcome, identity):
        receipt = json.loads((target / 'verification.json').read_text())
        for artifact in receipt['artifacts']:
            if digest(artifact['file']) != artifact['sha256']:
                from schemaxis.errors import fail
                fail('VERIFICATION_FAILED', 'artifact differs', artifact['file'])
        return receipt


class RevisionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.native = FakeNative()
        for patch in (mock.patch('schemaxis.workflow.run', self.native.run),
                      mock.patch('schemaxis.adaptors.paraview.integration.verifyLegacy', self.native.verify),
                      mock.patch('schemaxis.adaptors.paraview.integration.verifyAttempt',
                                 lambda target, effective: self.native.verify(target, effective, None, None)),
                      mock.patch('schemaxis.publication_metadata.publish_artifacts'),
                      mock.patch('schemaxis.publication_metadata.verify')):
            patch.start()
            self.addCleanup(patch.stop)

    def fault(self, code, function, *args, **kwargs):
        with self.assertRaises(SchemaxisError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def parent(self, document=None, name='parent'):
        execute(document or workflow(), self.root / name)
        return self.root / name

    def edited(self, parent, name='edit'):
        work = self.root / name / 'surface.vtp'
        cli('revision', 'checkout', str(parent), '--consumer', 'consume', '--pointer', POINTER,
            '--destination', str(work))
        work.write_text(work.read_text().replace('1 0 0', '3 0 0'))
        return work

    def prepared(self, parent, name='rev'):
        work = self.edited(parent, name + '-edit')
        output = self.root / name / 'revision.json'
        cli('revision', 'prepare', str(parent), '--consumer', 'consume', '--pointer', POINTER,
            '--replacement', str(work), '--snapshot', str(self.root / name / 'snapshot'),
            '--reason', 'moved a vertex by hand', '--output', str(output))
        return json.loads(output.read_text()), output

    def test_edit_adopt_and_rerun_child_while_parent_stays_unchanged(self):
        parent = self.parent()
        before = tree(parent)
        checked = cli('revision', 'checkout', str(parent), '--consumer', 'consume', '--pointer', POINTER,
                      '--destination', str(self.root / 'work' / 'surface.vtp'))
        self.assertEqual(checked['selection']['sha256'], digest(parent / 'produce' / 'surface.vtp'))
        self.assertEqual(checked['original'], {'$artifact': 'produce', 'index': 0})
        self.assertEqual(checked['selection']['file'], 'surface.vtp')
        work = Path(checked['workingCopy'])
        work.write_text(TRIANGLE.replace('1 0 0', '3 0 0'))
        output = self.root / 'rev' / 'revision.json'
        prepared = cli('revision', 'prepare', str(parent), '--consumer', 'consume', '--pointer', POINTER,
                       '--replacement', str(work), '--snapshot', str(self.root / 'rev' / 'snapshot'),
                       '--reason', 'moved a vertex by hand', '--output', str(output))
        document = json.loads(output.read_text())
        self.assertEqual(prepared['revision'], str(output))
        self.assertEqual(document['parent']['authoredDigest'], storage.digest(workflow()))
        self.assertEqual((document['units'], document['frame']), ('unknown', 'unknown'))
        planned = cli('plan', str(output))
        self.assertEqual(planned['version'], 'schemaxis.revision.plan/1')
        self.assertNotIn('paraview', sys.modules)
        self.native.calls.clear()
        result = cli('run', str(output), '--backend', 'native', '--output-directory', str(self.root / 'child'))
        # Both operations are rerun conservatively; nothing is reused.
        self.assertEqual(self.native.calls, ['produce', 'consume'])
        self.assertEqual((result['rerun'], result['reused']), (['produce', 'consume'], []))
        source, text = self.native.consumed[-1]
        self.assertEqual(Path(source), self.root / 'rev' / 'snapshot' / 'data' / 'surface.vtp')
        self.assertIn('3 0 0', text)
        child = json.loads((self.root / 'child' / 'workflow' / 'authored.json').read_text())
        self.assertEqual(child['operations'][1]['document']['nodes'][0]['options']['files'][0],
                         document['replacement'])
        report = cli('verify', str(self.root / 'child'))
        self.assertTrue(report['verified'])
        self.assertEqual(report['replacementDigest'], document['replacement']['digest'])
        self.assertEqual(tree(parent), before)
        self.assertTrue(verify(parent)['verified'])
        # The ordinary exact resume guard still refuses a different workflow.
        self.fault('RESUME_MISMATCH', execute, child, parent, resume=True)
        self.assertEqual(tree(parent), before)
        self.fault('UNSUPPORTED_REVISION', cli, 'run', str(output), '--output-directory',
                   str(self.root / 'child'), '--resume')
        self.fault('REVISION_OVERLAP', cli, 'run', str(output), '--output-directory', str(output.parent))
        # Output reuse is refused; the existing child is not overwritten.
        self.fault('OUTPUT_EXISTS', cli, 'run', str(output), '--output-directory', str(self.root / 'child'))

    def test_snapshot_and_working_copy_changes_are_refused(self):
        parent = self.parent()
        document, output = self.prepared(parent)
        snapshot = Path(document['replacement']['$resource'])
        stable = self.root / 'stable'
        self.assertEqual(revisions.execute(document, stable)['status'], 'succeeded')
        member = snapshot / 'data' / 'surface.vtp'
        original = member.read_text()
        member.write_text(original + ' ')
        self.fault('RESOURCE_MISMATCH', revisions.execute, document, self.root / 'changed')
        self.fault('RESOURCE_MISMATCH', revisions.verify, stable)
        # A consistently reissued manifest is still refused by the pinned digest.
        manifest = json.loads((snapshot / 'resource.json').read_text())
        manifest['files'][0].update(size=member.stat().st_size, sha256=digest(member))
        manifest['totalBytes'] = member.stat().st_size
        manifest['digest'] = storage.digest({k: v for k, v in manifest.items() if k != 'digest'})
        (snapshot / 'resource.json').write_text(json.dumps(manifest))
        self.fault('INPUT_CHANGED', revisions.execute, document, self.root / 'reissued')
        member.unlink()
        self.fault('RESOURCE_MISMATCH', revisions.execute, document, self.root / 'missing')
        self.assertFalse((self.root / 'missing').exists())

    def test_parent_and_record_tamper_fail_structured_checks(self):
        parent = self.parent()
        document, _ = self.prepared(parent)
        cases = {
            'index': ('selection', {**document['selection'], 'index': 1}, 'REVISION_MISMATCH'),
            'hash': ('selection', {**document['selection'], 'sha256': '0' * 64}, 'REVISION_MISMATCH'),
            'producer': ('consumer', {**document['consumer'], 'original': {'$artifact': 'other', 'index': 0}},
                         'REVISION_MISMATCH'),
            'child': ('child', {'authoredDigest': '1' * 64}, 'REVISION_MISMATCH'),
            'parent': ('parent', {**document['parent'], 'authoredDigest': '2' * 64}, 'REVISION_MISMATCH'),
            'reason': ('reason', ' ', 'INVALID_REVISION'),
            'units': ('units', 'm', 'INVALID_REVISION'),
            'pointer': ('consumer', {**document['consumer'], 'pointer': '/nodes/0/options/files/~2'},
                        'INVALID_REVISION'),
            'extra': ('signature', 'trusted', 'UNKNOWN_FIELD'),
        }
        for name, (field, value, code) in cases.items():
            with self.subTest(name):
                changed = {**copy.deepcopy(document), field: value}
                with self.assertRaises(SchemaxisError) as caught:
                    revisions.execute(changed, self.root / ('tamper-' + name))
                if name != 'extra':
                    self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
                self.assertFalse((self.root / ('tamper-' + name)).exists())
        good = self.root / 'good'
        revisions.execute(document, good)
        retained = json.loads((good / 'authored.json').read_text())
        retained['reason'] = 'a different explanation'
        (good / 'authored.json').write_text(json.dumps(retained))
        self.assertEqual(revisions.verify(good)['verified'], True)  # reason is provenance only
        # A changed child edit fails verification.
        child = good / 'workflow' / 'authored.json'
        edited = json.loads(child.read_text())
        edited['operations'][1]['document']['nodes'][1]['options']['translate'] = [0, 0, 0]
        child.write_text(json.dumps(edited))
        self.fault('VERIFICATION_FAILED', revisions.verify, good)
        # A tampered parent artifact refuses execution and later verification.
        (parent / 'produce' / 'surface.vtp').write_text('tampered')
        self.fault('VERIFICATION_FAILED', revisions.execute, document, self.root / 'after-tamper')

    def test_pointer_selection_and_parent_admission(self):
        parent = self.parent()
        destination = str(self.root / 'w' / 'x.vtp')
        for pointer, code in (('nodes/0', 'INVALID_REVISION'), ('/nodes/0/options/files/~2', 'INVALID_REVISION'),
                              ('/nodes/9', 'INVALID_REVISION'), ('/nodes/01', 'INVALID_REVISION'),
                              ('/nodes/1/options/translate', 'REVISION_UNSUPPORTED'),
                              ('/nodes/0/options/files', 'REVISION_UNSUPPORTED')):
            with self.subTest(pointer):
                self.fault(code, revisions.checkout, parent, 'consume', pointer, destination)
        self.fault('INVALID_REVISION', revisions.checkout, parent, 'missing', POINTER, destination)
        self.assertFalse(Path(destination).exists())
        result = json.loads((parent / 'result.json').read_text())
        (parent / 'result.json').write_text(json.dumps({**result, 'status': 'failed', 'verified': False}))
        self.fault('INCOMPLETE_EXECUTION', revisions.checkout, parent, 'consume', POINTER, destination)
        (parent / 'result.json').write_text(json.dumps(result))
        composed = {**workflow(), 'settings': {'radius': 2}}
        composed_parent = self.root / 'composed'
        execute(composed, composed_parent)
        self.fault('REVISION_UNSUPPORTED', revisions.checkout, composed_parent, 'consume', POINTER, destination)
        # Revisions are not admitted as parents, so ancestry is never chased.
        document, _ = self.prepared(parent)
        revisions.execute(document, self.root / 'child')
        for candidate in (self.root / 'child', self.root / 'child' / 'workflow'):
            self.fault('REVISION_PARENT_UNSUPPORTED', revisions.checkout, candidate, 'consume', POINTER,
                       destination)

    def test_destinations_must_be_disjoint_from_parent_and_edits(self):
        parent = self.parent()
        alias = self.root / 'alias'
        alias.symlink_to(parent)
        for destination in (parent / 'copy.vtp', parent / 'produce' / 'x.vtp', alias / 'copy.vtp',
                            self.root / 'parent'):
            with self.subTest(str(destination)):
                self.fault('REVISION_OVERLAP', revisions.checkout, parent, 'consume', POINTER, destination)
        before = tree(parent)
        document, output = self.prepared(parent)
        work = Path(document['workingCopy'])
        snapshot = Path(document['replacement']['$resource'])
        for name, target in (('inside parent', parent / 'child'), ('parent ancestor', self.root),
                             ('aliased parent', alias / 'child'), ('snapshot', snapshot / 'child'),
                             ('working copy ancestor', work.parent)):
            with self.subTest(name):
                self.fault('REVISION_OVERLAP', revisions.execute, document, target)
        self.fault('REVISION_OVERLAP', cli, 'revision', 'prepare', str(parent), '--consumer', 'consume',
                   '--pointer', POINTER, '--replacement', str(work), '--snapshot', str(parent / 'snap'),
                   '--reason', 'r', '--output', str(self.root / 'other.json'))
        self.fault('REVISION_OVERLAP', cli, 'revision', 'prepare', str(parent), '--consumer', 'consume',
                   '--pointer', POINTER, '--replacement', str(parent / 'produce' / 'surface.vtp'),
                   '--snapshot', str(self.root / 'snap2'), '--reason', 'r', '--output', str(self.root / 'o.json'))
        self.assertFalse((self.root / 'snap2').exists())
        self.assertEqual(tree(parent), before)

    def test_unsupported_reader_is_refused_before_adoption_completes(self):
        parent = self.parent(workflow('readMultiBlock'))
        work = self.edited(parent)
        snapshot = self.root / 'snap'
        self.fault('UNSUPPORTED_RESOURCE', revisions.prepare, parent, 'consume', POINTER, work, snapshot, 'r')
        self.assertFalse(snapshot.exists())

    def test_remaining_dependency_does_not_defer_revision_reader_policy(self):
        document = workflow('readMultiBlock')
        document['operations'][1]['document']['settings'] = {
            'unused': {'$artifact': 'produce', 'index': 0}}
        parent = self.parent(document)
        work = self.edited(parent)
        snapshot = self.root / 'deferred-snapshot'
        self.fault('UNSUPPORTED_RESOURCE', revisions.prepare, parent, 'consume', POINTER,
                   work, snapshot, 'edit the input')
        self.assertFalse(snapshot.exists())

    def test_long_reason_is_refused_without_claiming_snapshot(self):
        parent = self.parent()
        work = self.edited(parent)
        snapshot = self.root / 'long-reason-snapshot'
        self.fault('INVALID_REVISION', revisions.prepare, parent, 'consume', POINTER,
                   work, snapshot, 'x' * 4097)
        self.assertFalse(snapshot.exists())

    def test_multipart_artifact_is_not_checked_out_as_one_file(self):
        parent = self.parent()
        receipt_path = parent / 'produce' / 'verification.json'
        receipt = json.loads(receipt_path.read_text())
        original = copy.deepcopy(receipt)
        for index, fields in enumerate(({'publicationMode': 'native-distributed'},
                                       {'files': [{'file': original['artifacts'][0]['file'],
                                                   'sha256': original['artifacts'][0]['sha256']},
                                                  {'file': 'piece.vtp', 'sha256': '0' * 64}]})):
            changed = copy.deepcopy(original)
            changed['artifacts'][0].update(fields)
            receipt_path.write_text(json.dumps(changed))
            with self.subTest(fields=fields):
                destination = self.root / ('multipart-edit-' + str(index) + '.vtp')
                self.fault('REVISION_UNSUPPORTED', revisions.checkout, parent, 'consume', POINTER, destination)
                self.assertFalse(destination.exists())

    def test_single_primary_file_manifest_can_be_checked_out(self):
        parent = self.parent()
        receipt_path = parent / 'produce' / 'verification.json'
        receipt = json.loads(receipt_path.read_text())
        artifact = receipt['artifacts'][0]
        artifact['files'] = [{'file': artifact['file'], 'sha256': artifact['sha256']}]
        receipt_path.write_text(json.dumps(receipt))
        destination = self.root / 'single-edit.vtp'
        result = revisions.checkout(parent, 'consume', POINTER, destination)
        self.assertEqual(digest(destination), result['selection']['sha256'])

    def test_metadata_reference_is_not_a_reader_edit(self):
        document = workflow()
        document['operations'][1]['document']['settings'] = {
            'unused': {'$artifact': 'produce', 'index': 0}}
        parent = self.parent(document)
        work = self.edited(parent)
        self.fault('UNSUPPORTED_RESOURCE', revisions.prepare, parent, 'consume', '/settings/unused',
                   work, self.root / 'metadata-snapshot', 'edit the input')

    def test_revision_documents_are_reserved_framework_namespaces(self):
        from schemaxis.adaptors import registry
        for version in ('schemaxis.revision/1', 'schemaxis.revision.result/1'):
            with self.subTest(version), self.assertRaisesRegex(ValueError, 'reserved by the framework'):
                registry._reserved({'routes': {version: {}}}, 'plugin', set())

    def test_consumer_tamper_failure_and_cancellation_retain_both_histories(self):
        parent = self.parent()
        before = tree(parent)
        document, _ = self.prepared(parent)
        self.native.during = lambda source: source.write_text('edited during the run')
        self.fault('RESOURCE_MISMATCH', revisions.execute, document, self.root / 'tampered')
        saved = json.loads((self.root / 'tampered' / 'result.json').read_text())
        self.assertEqual(saved['status'], 'failed')
        self.assertTrue((self.root / 'tampered' / 'workflow' / 'consume' / 'authored.json').exists())
        self.fault('RESOURCE_MISMATCH', revisions.verify, self.root / 'tampered')
        document, _ = self.prepared(parent, 'second')

        def interrupt(source):
            raise KeyboardInterrupt
        self.native.during = interrupt
        with self.assertRaises(KeyboardInterrupt):
            revisions.execute(document, self.root / 'cancelled')
        saved = json.loads((self.root / 'cancelled' / 'result.json').read_text())
        self.assertEqual(saved['status'], 'cancelled')
        self.assertTrue((self.root / 'cancelled' / 'workflow' / 'produce' / 'verification.json').exists())
        self.assertEqual(tree(parent), before)
        self.assertTrue(verify(parent)['verified'])


class RevisionBoundaryTests(unittest.TestCase):
    """Malformed external records must fail before execution or copying."""

    def test_missing_revision_fields_are_structured_faults(self):
        for document in ({'version': revisions.VERSION},
                         {'version': revisions.VERSION, 'parent': {}}):
            with self.subTest(document=document), self.assertRaises(SchemaxisError):
                revisions.check(document)

    def test_malformed_replacement_is_rejected_without_filesystem_access(self):
        with tempfile.TemporaryDirectory() as root:
            document = {'version': revisions.VERSION,
                        'parent': {'directory': root, 'authoredDigest': '0' * 64},
                        'selection': {'producer': 'produce', 'index': 0, 'kind': 'geometry',
                                      'file': 'surface.vtp', 'sha256': '0' * 64},
                        'consumer': {'operation': 'consume', 'pointer': POINTER,
                                     'original': {'$artifact': 'produce', 'index': 0}},
                        'replacement': {'$resource': root, 'digest': '0' * 64, 'member': 'surface.vtp'},
                        'workingCopy': str(Path(root) / 'edit.vtp'), 'reason': 'edit the input',
                        'child': {'authoredDigest': '0' * 64}, 'units': 'unknown', 'frame': 'unknown',
                        'execution': revisions._EXECUTION, 'limitations': list(revisions._LIMITATIONS)}
            revisions.check(document)
            for replacement in ({}, {'member': 'surface.vtp'}, None):
                with self.subTest(replacement=replacement), self.assertRaises(SchemaxisError):
                    revisions.check({**document, 'replacement': replacement})

    def test_malformed_parent_records_are_structured_faults(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root) / 'parent'
            parent.mkdir()
            authored = parent / 'authored.json'
            result = parent / 'result.json'
            cases = [('null', '{}'), ('{}', '[]'),
                     (json.dumps(workflow()), '[]'),
                     (json.dumps(workflow()), '{broken')]
            for author_text, result_text in cases:
                authored.write_text(author_text)
                result.write_text(result_text)
                with self.subTest(authored=author_text, result=result_text):
                    with self.assertRaises(SchemaxisError):
                        revisions.checkout(parent, 'consume', POINTER, Path(root) / 'edit.vtp')
            child = parent / 'workflow'
            child.mkdir()
            (child / 'authored.json').write_text(json.dumps(workflow()))
            (child / 'result.json').write_text('{}')
            authored.write_text('null')
            with self.assertRaises(SchemaxisError):
                revisions.checkout(child, 'consume', POINTER, Path(root) / 'edit.vtp')


if __name__ == '__main__':
    unittest.main()
