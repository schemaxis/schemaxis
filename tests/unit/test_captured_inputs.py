import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from schemaxis import storage
from schemaxis.__main__ import main
from schemaxis.core.faults import SchemaxisError
from schemaxis.workflow import execute, inspect_plan, verify


TRIANGLE = '''<?xml version="1.0"?>
<VTKFile type="PolyData" version="0.1"><PolyData><Piece NumberOfPoints="3" NumberOfPolys="1">
<Points><DataArray type="Float64" NumberOfComponents="3" format="ascii">0 0 0 1 0 0 0 1 0</DataArray></Points>
<Polys><DataArray type="Int64" Name="connectivity" format="ascii">0 1 2</DataArray>
<DataArray type="Int64" Name="offsets" format="ascii">3</DataArray></Polys></Piece></PolyData></VTKFile>
'''
BLOCKS = '''<?xml version="1.0"?>
<VTKFile type="vtkMultiBlockDataSet" version="1.0"><vtkMultiBlockDataSet>
<DataSet index="0" file="pieces/a.vtp"/><DataSet index="1" file="pieces/b.vtp"/>
</vtkMultiBlockDataSet></VTKFile>
'''


def cli(*args):
    with mock.patch.object(sys, 'argv', ['schemaxis', *args]):
        return main()


def reader(filter_name, reference, option='files'):
    value = [reference] if option == 'files' else reference
    return {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'read', 'document': {
        'version': 'schemaxis/1', 'nodes': [{'id': 'data', 'filter': filter_name, 'options': {option: value}}],
        'scenes': [{'id': 'view', 'geometry': ['data']}]}}]}


class CapturedInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'saved').mkdir()
        (self.root / 'saved' / 'surface.vtp').write_text(TRIANGLE)
        case = self.root / 'saved' / 'case'
        (case / 'pieces').mkdir(parents=True)
        (case / 'pieces' / 'a.vtp').write_text(TRIANGLE)
        (case / 'pieces' / 'b.vtp').write_text(TRIANGLE.replace('1 0 0', '2 0 0'))
        (case / 'blocks.vtm').write_text(BLOCKS)
        (case / 'case.foam').write_text('')

    def fault(self, code, function, *args, **kwargs):
        with self.assertRaises(SchemaxisError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def adopt_file(self):
        return cli('input', 'adopt', str(self.root / 'saved' / 'surface.vtp'), str(self.root / 'snap' / 'surface'))

    def adopt_case(self, name='case'):
        return cli('input', 'adopt', str(self.root / 'saved' / 'case'), str(self.root / 'snap' / name),
                   '--kind', 'directory', '--max-files', '10')

    def test_adopted_file_plans_against_verified_snapshot_and_cli_checks_pinned_digest(self):
        adopted = self.adopt_file()
        reference = adopted['reference']
        self.assertEqual(reference['member'], 'surface.vtp')
        self.assertEqual((adopted['units'], adopted['frame']), ('unknown', 'unknown'))
        snapshot = Path(adopted['snapshot'])
        checked = cli('input', 'verify', str(snapshot), '--digest', adopted['digest'])
        self.assertTrue(checked['verified'])
        self.fault('INPUT_CHANGED', cli, 'input', 'verify', str(snapshot), '--digest', '0' * 64)
        plan = inspect_plan(reader('readSurface', {**reference, 'origin': 'saved checkpoint'}))
        evidence = plan['operations'][0]['provisionalPlan']['capturedInputs'][0]
        self.assertEqual(evidence['file'], str(snapshot / 'data' / 'surface.vtp'))
        self.assertEqual(evidence['policy'], {'reader': 'readSurface', 'scope': 'selected member only'})
        self.assertEqual(evidence['origin'], 'saved checkpoint')
        # The saved application file may keep changing; the snapshot does not.
        (self.root / 'saved' / 'surface.vtp').write_text('edited later')
        self.assertEqual(inspect_plan(reader('readSurface', reference))['operations'][0]['provisionalPlan']
                         ['capturedInputs'][0]['digest'], adopted['digest'])

    def test_tampered_or_reissued_snapshot_is_refused_by_pinned_digest(self):
        adopted = self.adopt_file()
        member = Path(adopted['snapshot']) / 'data' / 'surface.vtp'
        member.write_text(TRIANGLE.replace('0 1 0', '0 5 0'))
        self.fault('RESOURCE_MISMATCH', inspect_plan, reader('readSurface', adopted['reference']))
        # A consistently rewritten manifest self-verifies but is not the trusted capture.
        manifest_path = Path(adopted['snapshot']) / 'resource.json'
        manifest = json.loads(manifest_path.read_text())
        data = member.read_bytes()
        manifest['files'][0].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        manifest['totalBytes'] = len(data)
        manifest.pop('digest')
        manifest['digest'] = storage.digest(manifest)
        manifest_path.write_bytes(storage.encoded(manifest))
        fault = self.fault('INPUT_CHANGED', inspect_plan, reader('readSurface', adopted['reference']))
        self.assertEqual(fault.to_dict()['observed']['expected'], adopted['digest'])

    def test_directory_reader_policy_requires_closed_explicit_membership(self):
        adopted = self.adopt_case()
        reference = {**adopted['reference'], 'member': 'blocks.vtm'}
        policy = inspect_plan(reader('readMultiBlock', reference))['operations'][0]['provisionalPlan'][
            'capturedInputs'][0]['policy']
        self.assertEqual(policy['referencedMembers'], ['blocks.vtm', 'pieces/a.vtp', 'pieces/b.vtp'])
        foam = inspect_plan(reader('foam', {**adopted['reference'], 'member': 'case.foam'}, option='file'))
        self.assertEqual(foam['operations'][0]['provisionalPlan']['capturedInputs'][0]['kind'], 'directory')
        # A single file cannot carry companion pieces, and directories need a member.
        single = self.adopt_file()['reference']
        self.fault('UNSUPPORTED_RESOURCE', inspect_plan, reader('readMultiBlock', single))
        self.fault('UNSUPPORTED_RESOURCE', inspect_plan, reader('foam', single, option='file'))
        self.fault('UNSUPPORTED_RESOURCE', inspect_plan, reader('readMultiBlock', adopted['reference']))
        # Explicit file sets must include every referenced piece.
        partial = cli('input', 'adopt', str(self.root / 'saved' / 'case'), str(self.root / 'snap' / 'partial'),
                      '--kind', 'file-set', '--member', 'blocks.vtm', '--member', 'pieces/a.vtp')
        self.fault('UNSUPPORTED_RESOURCE', inspect_plan,
                   reader('readMultiBlock', {**partial['reference'], 'member': 'blocks.vtm'}))
        self.fault('RESOURCE_MISMATCH', inspect_plan,
                   reader('readMultiBlock', {**partial['reference'], 'member': 'pieces/b.vtp'}))

    def test_missing_unexpected_members_limits_and_relocation(self):
        adopted = self.adopt_case()
        reference = {**adopted['reference'], 'member': 'blocks.vtm'}
        data = Path(adopted['snapshot']) / 'data'
        self.fault('RESOURCE_LIMIT', inspect_plan, reader('readMultiBlock', {**reference, 'maxFiles': 2}))
        self.fault('RESOURCE_LIMIT', inspect_plan, reader('readMultiBlock', {**reference, 'maxBytes': 10}))
        relocated = self.root / 'moved' / 'case'
        relocated.parent.mkdir()
        Path(adopted['snapshot']).rename(relocated)
        self.fault('RESOURCE_MISMATCH', inspect_plan, reader('readMultiBlock', reference))
        moved = {**reference, '$resource': str(relocated)}
        plan = inspect_plan(reader('readMultiBlock', moved))['operations'][0]['provisionalPlan']
        self.assertEqual(plan['capturedInputs'][0]['digest'], adopted['digest'])
        (relocated / 'data' / 'extra.txt').write_text('unexpected')
        self.fault('RESOURCE_MISMATCH', inspect_plan, reader('readMultiBlock', moved))
        (relocated / 'data' / 'extra.txt').unlink()
        (relocated / 'data' / 'pieces' / 'b.vtp').unlink()
        self.fault('RESOURCE_MISMATCH', inspect_plan, reader('readMultiBlock', moved))
        self.assertFalse(data.exists())
        self.fault('RESOURCE_LIMIT', cli, 'input', 'adopt', str(self.root / 'saved' / 'case'),
                   str(self.root / 'snap' / 'small'), '--kind', 'directory', '--max-bytes', '10')

    def test_reference_shape_and_adaptor_without_policy_are_refused(self):
        adopted = self.adopt_file()
        self.fault('INVALID_RESOURCE', inspect_plan, reader('readSurface', {**adopted['reference'], '$resource': 'relative'}))
        self.fault('INVALID_RESOURCE', inspect_plan, reader('readSurface', {**adopted['reference'], 'digest': 'abc'}))
        self.fault('UNKNOWN_ARGUMENT', inspect_plan, reader('readSurface', {**adopted['reference'], 'trust': True}))
        self.fault('UNSUPPORTED_RESOURCE', inspect_plan, reader('transform', adopted['reference'], option='translate'))
        gmsh = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'mesh', 'document': {
            'version': 'schemaxis.gmsh/1', 'units': 'mm', 'nodes': [
                {'id': 'solid', 'filter': 'readSTEP', 'options': {'file': adopted['reference']}},
                {'id': 'mesh', 'filter': 'tetrahedral', 'inputs': {'input': 'solid'}, 'options': {'size': 1}}],
            'output': 'mesh'}}]}
        self.fault('UNSUPPORTED_RESOURCE', inspect_plan, gmsh)

    def test_serial_execution_consumes_snapshot_and_verification_rechecks_it(self):
        adopted = self.adopt_case()
        workflow = reader('readMultiBlock', {**adopted['reference'], 'member': 'blocks.vtm'})
        consumed = []

        def run(effective, target, **_):
            target.mkdir(parents=True)
            consumed.append(copy.deepcopy(effective))
            (target / 'verification.json').write_text(json.dumps({'artifacts': []}))
            (target / 'authored.json').write_text(json.dumps(effective))
            return {}
        with mock.patch('schemaxis.workflow.run', run), \
                mock.patch('schemaxis.publication_metadata.publish_artifacts'):
            result = execute(workflow, self.root / 'run')
        expected = str(Path(adopted['snapshot']) / 'data' / 'blocks.vtm')
        self.assertEqual(consumed[0]['nodes'][0]['options']['files'], [expected])
        self.assertEqual(result['handoffs'][0]['to'], 'read')
        self.assertEqual(result['handoffs'][0]['digest'], adopted['digest'])
        saved = json.loads((self.root / 'run' / 'result.json').read_text())
        self.assertEqual(saved['handoffs'], result['handoffs'])
        receipt = {'artifacts': []}
        with mock.patch('schemaxis.adaptors.paraview.integration.verifyLegacy', return_value=receipt), \
                mock.patch('schemaxis.publication_metadata.verify'):
            self.assertTrue(verify(self.root / 'run')['verified'])
            (Path(adopted['snapshot']) / 'data' / 'pieces' / 'a.vtp').write_text('changed')
            self.fault('RESOURCE_MISMATCH', verify, self.root / 'run')
        # A changed snapshot is refused before any native process is started.
        consumed.clear()
        with mock.patch('schemaxis.workflow.run', run):
            self.fault('RESOURCE_MISMATCH', execute, workflow, self.root / 'second')
        self.assertEqual(consumed, [])

    def test_scheduled_resume_rechecks_snapshot_and_paraview_reruns_conservatively(self):
        from schemaxis import parallel
        adopted = self.adopt_file()
        workflow = reader('readSurface', adopted['reference'])
        workflow['execution'] = {'maxWorkers': 1, 'cpus': 1, 'memoryMB': 1024, 'gpus': 0}
        runs = []

        def run(document, directory, *args, **kwargs):
            runs.append(document['nodes'][0]['options']['files'][0])
            directory.mkdir()
            (directory / 'authored.json').write_text(json.dumps(document))
            (directory / 'verification.json').write_text(json.dumps({'artifacts': []}))
            return {'verified': True}

        def verify_native(directory, expected):
            if json.loads((Path(directory) / 'authored.json').read_text()) != expected:
                raise ValueError('wrong input')
            return {'artifacts': []}
        target = self.root / 'scheduled'
        with mock.patch.object(parallel, 'run_native', side_effect=run), \
                mock.patch.object(parallel, 'verify_native', side_effect=verify_native), \
                mock.patch('schemaxis.publication_metadata.publish_artifacts'), \
                mock.patch('schemaxis.publication_metadata.verify'):
            result = execute(workflow, target)
            member = Path(adopted['snapshot']) / 'data' / 'surface.vtp'
            self.assertEqual(runs, [str(member)])
            self.assertEqual(result['jobs'][0]['handoffs'][0]['digest'], adopted['digest'])
            self.assertTrue(parallel.verify(target)['verified'])
            # ParaView declares no reusable provenance for file readers, so resume reruns.
            self.assertFalse(execute(workflow, target, resume=True)['jobs'][0]['reused'])
            # Under a policy that reports reusable provenance, an unchanged pinned
            # snapshot keeps the retained handoff equal and the attempt is reused.
            with mock.patch.object(parallel, 'reusable_inputs', return_value={}):
                self.assertFalse(execute(workflow, target, resume=True)['jobs'][0]['reused'])
                self.assertTrue(execute(workflow, target, resume=True)['jobs'][0]['reused'])
                member.write_text('changed')
                self.fault('RESOURCE_MISMATCH', parallel.verify, target)
                self.fault('RESOURCE_MISMATCH', execute, workflow, target, resume=True)
            self.assertEqual(len(runs), 3)

    def rewrite_manifest(self, snapshot, member, text):
        """Edit a member and consistently reissue the snapshot manifest."""
        path = Path(snapshot) / 'data' / member
        path.write_text(text)
        manifest_path = Path(snapshot) / 'resource.json'
        manifest = json.loads(manifest_path.read_text())
        data = path.read_bytes()
        record = next(item for item in manifest['files'] if item['path'] == member)
        manifest['totalBytes'] += len(data) - record['size']
        record.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        manifest.pop('digest')
        manifest['digest'] = storage.digest(manifest)
        manifest_path.write_bytes(storage.encoded(manifest))

    def test_serial_consumer_editing_its_snapshot_does_not_succeed(self):
        def consumer(edit):
            def run(effective, target, **_):
                target.mkdir(parents=True)
                (target / 'verification.json').write_text(json.dumps({'artifacts': []}))
                (target / 'authored.json').write_text(json.dumps(effective))
                edit()
                return {}
            return run
        for name, code, edit in (
                ('stable', None, lambda snapshot: None),
                ('edited', 'RESOURCE_MISMATCH',
                 lambda snapshot: (Path(snapshot) / 'data' / 'pieces' / 'a.vtp').write_text('edited')),
                ('reissued', 'INPUT_CHANGED',
                 lambda snapshot: self.rewrite_manifest(snapshot, 'pieces/a.vtp', TRIANGLE + ' '))):
            with self.subTest(name):
                adopted = self.adopt_case(name)
                workflow = reader('readMultiBlock', {**adopted['reference'], 'member': 'blocks.vtm'})
                target = self.root / ('run-' + name)
                run = consumer(lambda: edit(adopted['snapshot']))
                with mock.patch('schemaxis.workflow.run', run), \
                        mock.patch('schemaxis.publication_metadata.publish_artifacts'):
                    if code is None:
                        self.assertTrue(execute(workflow, target)['verified'])
                    else:
                        self.fault(code, execute, workflow, target)
                saved = json.loads((target / 'result.json').read_text())
                self.assertEqual((saved['status'], saved['verified']),
                                 ('succeeded', True) if code is None else ('failed', False))
                if code is not None:
                    self.assertEqual(saved['fault']['code'], code)
                    self.assertEqual(saved['operations'], [])

    def test_scheduled_consumer_editing_its_snapshot_does_not_succeed(self):
        from schemaxis import parallel

        def verify_native(directory, expected):
            if json.loads((Path(directory) / 'authored.json').read_text()) != expected:
                raise ValueError('wrong input')
            return {'artifacts': []}
        for name, code, edit in (
                ('stable', None, lambda member: None),
                ('edited', 'RESOURCE_MISMATCH', lambda member: member.write_text('edited')),
                ('reissued', 'INPUT_CHANGED',
                 lambda member: self.rewrite_manifest(member.parent.parent, member.name, TRIANGLE + ' '))):
            with self.subTest(name):
                adopted = cli('input', 'adopt', str(self.root / 'saved' / 'surface.vtp'),
                              str(self.root / 'snap' / ('surface-' + name)))
                workflow = reader('readSurface', adopted['reference'])
                workflow['execution'] = {'maxWorkers': 1, 'cpus': 1, 'memoryMB': 1024, 'gpus': 0}
                member = Path(adopted['snapshot']) / 'data' / 'surface.vtp'

                def run(document, directory, *args, **kwargs):
                    directory.mkdir()
                    (directory / 'authored.json').write_text(json.dumps(document))
                    (directory / 'verification.json').write_text(json.dumps({'artifacts': []}))
                    edit(member)
                    return {'verified': True}
                target = self.root / ('scheduled-' + name)
                with mock.patch.object(parallel, 'run_native', side_effect=run), \
                        mock.patch.object(parallel, 'verify_native', side_effect=verify_native), \
                        mock.patch('schemaxis.publication_metadata.publish_artifacts'):
                    if code is None:
                        self.assertTrue(execute(workflow, target)['verified'])
                    else:
                        self.fault(code, execute, workflow, target)
                saved = json.loads((target / 'result.json').read_text())
                self.assertEqual((saved['status'], saved['verified']),
                                 ('succeeded', True) if code is None else ('failed', False))
                self.assertEqual(saved['jobs'][0]['status'], 'succeeded' if code is None else 'failed')
                # A refused attempt never records a reusable successful job.
                self.assertEqual(any(target.glob('read/batch-*/attempt-*/job.json')), code is None)

    def composed(self, reference, filter_name='readSurface', scope='local'):
        """Author the reader file through settings or workflow definitions."""
        if scope == 'local':
            workflow = reader(filter_name, {'$document': '/settings/data'}, 'files' if filter_name != 'foam' else 'file')
            workflow['operations'][0]['document']['settings'] = {'data': reference}
        else:
            workflow = reader(filter_name, {'$document': '/definitions/data', 'scope': 'workflow'},
                              'files' if filter_name != 'foam' else 'file')
            workflow['definitions'] = {'data': reference}
        return workflow

    def test_composed_references_are_consumed_only_at_resolved_reader_fields(self):
        surface = self.adopt_file()
        case = self.adopt_case()
        for scope in ('local', 'workflow'):
            for filter_name, reference, pointer in (
                    ('readSurface', surface['reference'], '/nodes/0/options/files/0'),
                    ('readMultiBlock', {**case['reference'], 'member': 'blocks.vtm'}, '/nodes/0/options/files/0'),
                    ('foam', {**case['reference'], 'member': 'case.foam'}, '/nodes/0/options/file')):
                with self.subTest(scope=scope, reader=filter_name):
                    workflow = self.composed(reference, filter_name, scope)
                    evidence = inspect_plan(workflow)['operations'][0]['provisionalPlan']['capturedInputs']
                    self.assertEqual([(item['pointer'], item['policy']['reader']) for item in evidence],
                                     [(pointer, filter_name)])
                    self.assertEqual(evidence[0]['digest'], reference['digest'])
        # The parser-owned definition is never asked to be a reader itself.
        from schemaxis.adaptors.paraview import integration
        with mock.patch.object(integration, 'acceptResource', wraps=integration.acceptResource) as policy:
            inspect_plan(self.composed(surface['reference']))
        self.assertEqual([call.args[1] for call in policy.call_args_list], ['/nodes/0/options/files/0'])

    def test_composed_reference_at_unsupported_field_or_changed_content_is_refused(self):
        adopted = self.adopt_file()
        workflow = self.composed(adopted['reference'])
        node = workflow['operations'][0]['document']['nodes'][0]
        node['options'] = {'files': ['/data/surface.vtp'], 'label': {'$document': '/settings/data'}}
        fault = self.fault('UNSUPPORTED_RESOURCE', inspect_plan, workflow)
        self.assertIn('/nodes/0/options/label', fault.location)
        self.fault('INPUT_CHANGED', inspect_plan, self.composed({**adopted['reference'], 'digest': '0' * 64}))
        (Path(adopted['snapshot']) / 'data' / 'surface.vtp').write_text('changed')
        self.fault('RESOURCE_MISMATCH', inspect_plan, self.composed(adopted['reference'], scope='workflow'))

    def test_unused_metadata_reference_is_shape_checked_but_not_consumed(self):
        adopted = self.adopt_file()
        workflow = reader('readSurface', adopted['reference'])
        # An absent snapshot proves the unused definition is never opened.
        unused = {'$resource': str(self.root / 'absent'), 'digest': '0' * 64}
        workflow['operations'][0]['document']['settings'] = {'unused': unused}
        evidence = inspect_plan(workflow)['operations'][0]['provisionalPlan']['capturedInputs']
        self.assertEqual([item['pointer'] for item in evidence], ['/nodes/0/options/files/0'])
        workflow['operations'][0]['document']['settings'] = {'unused': {**unused, '$resource': 'relative'}}
        self.fault('INVALID_RESOURCE', inspect_plan, workflow)

    def test_serial_composed_consumer_keeps_metadata_and_rechecks_after_running(self):
        for name, code in (('stable', None), ('edited', 'RESOURCE_MISMATCH')):
            with self.subTest(name):
                adopted = self.adopt_case(name)
                reference = {**adopted['reference'], 'member': 'case.foam'}
                workflow = self.composed(reference, 'foam')
                consumed = []

                def run(effective, target, **_):
                    target.mkdir(parents=True)
                    consumed.append(copy.deepcopy(effective))
                    (target / 'verification.json').write_text(json.dumps({'artifacts': []}))
                    (target / 'authored.json').write_text(json.dumps(effective))
                    if code:
                        (Path(adopted['snapshot']) / 'data' / 'case.foam').write_text('edited')
                    return {}
                target = self.root / ('composed-' + name)
                with mock.patch('schemaxis.workflow.run', run), \
                        mock.patch('schemaxis.publication_metadata.publish_artifacts'):
                    if code is None:
                        result = execute(workflow, target)
                        self.assertEqual([item['pointer'] for item in result['handoffs']], ['/nodes/0/options/file'])
                    else:
                        self.fault(code, execute, workflow, target)
                self.assertEqual(consumed[0]['nodes'][0]['options']['file'],
                                 str(Path(adopted['snapshot']) / 'data' / 'case.foam'))
                # Authored metadata is retained unchanged; only the consumer field is substituted.
                self.assertEqual(consumed[0]['settings'], {'data': reference})
                if code is None:
                    with mock.patch('schemaxis.adaptors.paraview.integration.verifyLegacy',
                                    return_value={'artifacts': []}), \
                            mock.patch('schemaxis.publication_metadata.verify'):
                        self.assertTrue(verify(target)['verified'])
                        (Path(adopted['snapshot']) / 'data' / 'case.foam').write_text('later')
                        self.fault('RESOURCE_MISMATCH', verify, target)

    def test_scheduled_composed_consumer_rechecks_and_resume_compares_consumed_handoff(self):
        from schemaxis import parallel

        def verify_native(directory, expected):
            if json.loads((Path(directory) / 'authored.json').read_text()) != expected:
                raise ValueError('wrong input')
            return {'artifacts': []}
        for name, code in (('stable', None), ('edited', 'RESOURCE_MISMATCH')):
            with self.subTest(name):
                adopted = cli('input', 'adopt', str(self.root / 'saved' / 'surface.vtp'),
                              str(self.root / 'snap' / ('composed-' + name)))
                workflow = self.composed(adopted['reference'], scope='workflow')
                workflow['execution'] = {'maxWorkers': 1, 'cpus': 1, 'memoryMB': 1024, 'gpus': 0}
                member = Path(adopted['snapshot']) / 'data' / 'surface.vtp'
                runs = []

                def run(document, directory, *args, **kwargs):
                    runs.append(document['nodes'][0]['options']['files'][0])
                    directory.mkdir()
                    (directory / 'authored.json').write_text(json.dumps(document))
                    (directory / 'verification.json').write_text(json.dumps({'artifacts': []}))
                    if code:
                        member.write_text('edited')
                    return {'verified': True}
                target = self.root / ('scheduled-composed-' + name)
                with mock.patch.object(parallel, 'run_native', side_effect=run), \
                        mock.patch.object(parallel, 'verify_native', side_effect=verify_native), \
                        mock.patch('schemaxis.publication_metadata.publish_artifacts'), \
                        mock.patch('schemaxis.publication_metadata.verify'):
                    if code is not None:
                        self.fault(code, execute, workflow, target)
                        self.assertFalse(any(target.glob('read/batch-*/attempt-*/job.json')))
                        continue
                    result = execute(workflow, target)
                    self.assertEqual([item['pointer'] for item in result['jobs'][0]['handoffs']],
                                     ['/nodes/0/options/files/0'])
                    self.assertTrue(parallel.verify(target)['verified'])
                    with mock.patch.object(parallel, 'reusable_inputs', return_value={}):
                        execute(workflow, target, resume=True)
                        self.assertTrue(execute(workflow, target, resume=True)['jobs'][0]['reused'])
                        member.write_text('changed')
                        self.fault('RESOURCE_MISMATCH', parallel.verify, target)
                        self.fault('RESOURCE_MISMATCH', execute, workflow, target, resume=True)
                self.assertEqual(runs[0], str(member))

    def test_adopted_reference_retains_configured_limits_for_later_checks(self):
        from schemaxis import workflow_resources
        default = self.adopt_file()['reference']
        self.assertNotIn('maxFiles', default)
        self.assertNotIn('maxBytes', default)
        size = len(TRIANGLE.encode())
        adopted = cli('input', 'adopt', str(self.root / 'saved' / 'surface.vtp'), str(self.root / 'snap' / 'tight'),
                      '--max-files', '3', '--max-bytes', str(size))
        reference = adopted['reference']
        self.assertEqual((reference['maxFiles'], reference['maxBytes']), (3, size))
        with mock.patch.object(workflow_resources, 'verify', wraps=workflow_resources.verify) as checked:
            inspect_plan(reader('readSurface', reference))
        self.assertEqual(checked.call_args.kwargs, {'max_files': 3, 'max_bytes': size})
        # Growth beyond the adopted bound is a limit fault, not a silent default.
        (Path(adopted['snapshot']) / 'data' / 'surface.vtp').write_text(TRIANGLE + ' ')
        self.fault('RESOURCE_LIMIT', inspect_plan, reader('readSurface', reference))
        self.fault('INVALID_RESOURCE', cli, 'input', 'adopt', str(self.root / 'saved' / 'surface.vtp'),
                   str(self.root / 'snap' / 'invalid'), '--max-files', '0')


if __name__ == '__main__':
    unittest.main()
