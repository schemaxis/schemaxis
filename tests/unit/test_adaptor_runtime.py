"""Framework-wide authored inputs, changing states and verified value handoffs."""
import copy
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptor_runtime import InputProgram, AdaptorSession, workflow_inputs
from schemaxis.adaptors import registry
from schemaxis.adaptor_delivery import route_materials, case_document
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail
from schemaxis import workflow, parallel

ROOT = Path(__file__).resolve().parents[2]


def gmsh():
    return json.loads((ROOT/'examples/schemaxis/gmsh-minimal.json').read_text())


def source_study():
    document = gmsh()
    document['dimensions'] = {
        'size': {'$analytic': {'type': 'values', 'values': [2, 4, 8], 'sync': 'mesh'}},
        'extent': {'$analytic': {'type': 'values', 'values': [10, 20, 40], 'sync': 'mesh'}},
        'derived': {'$expr': {'op': 'divide', 'args': [{'$document': '/dimensions/size'}, 2]}}}
    document['nodes'][0]['options']['size'][0] = {'$document': '/dimensions/extent'}
    document['nodes'][1]['options']['size'] = {'$value': 'rangeCentre', 'args': {
        'range': [{'$document': '/dimensions/derived'}, {'$document': '/dimensions/derived'}]}}
    return document


def fake_run(document, target, **kwargs):
    target = Path(target); target.mkdir()
    value = document['nodes'][1]['options']['size']
    atomic_json(target/'authored.json', document)
    atomic_json(target/'measurement.json', {'value': value})
    atomic_json(target/'verification.json', {'artifacts': [
        {'file': str(target/'measurement.json'), 'kind': 'text', 'sha256': file_digest(target/'measurement.json')}],
        'value': value})
    atomic_json(target/'result.json', {'status': 'succeeded', 'verified': True})
    return {'verified': True}


def fake_verify(target):
    target = Path(target)
    document = json.loads((target/'authored.json').read_text())
    data = json.loads((target/'measurement.json').read_text())
    receipt = json.loads((target/'verification.json').read_text())
    if data['value'] != document['nodes'][1]['options']['size'] or receipt['artifacts'][0]['sha256'] != file_digest(target/'measurement.json'):
        fail('VERIFICATION_FAILED', 'changed native measurement')
    return {'verified': True}


class AdaptorRuntimeTests(unittest.TestCase):
    def test_exported_workflow_value_handoffs_and_studies_use_retained_copy(self):
        from schemaxis.schema_snapshots import export_run
        for study in (False, True):
            first = source_study() if study else gmsh()
            second = gmsh()
            # A workflow-wide study executes one synchronised producer visit in
            # each outer state; its consumer selects that visit (index zero).
            second['nodes'][1]['options']['size'] = {'$value': 'first', 'visit': 0,
                                                    'artifact': 0, 'path': '/value'}
            document = {'version': 'schemaxis.workflow/1', 'operations': [
                {'id': 'first', 'document': first}, {'id': 'second', 'document': second}]}
            with self.subTest(study=study), tempfile.TemporaryDirectory() as tmp, \
                    patch('schemaxis.adaptors.gmsh.adaptor._native_run', side_effect=fake_run), \
                    patch('schemaxis.adaptors.gmsh.adaptor._native_verify', side_effect=fake_verify):
                base = Path(tmp); source = base/'run'
                workflow.execute(document, source)
                original = workflow.publication_receipt(source)
                exported = base/'exported'; export_run(source, exported)
                source.rename(base/'unavailable-original')
                self.assertTrue(workflow.verify(exported)['verified'])
                self.assertEqual(workflow.publication_receipt(exported), original)
                again = base/'again'; export_run(exported, again)
                exported.rename(base/'unavailable-export')
                self.assertTrue(workflow.verify(again)['verified'])
                producer = next(path for path in again.rglob('measurement.json') if 'first' in path.parts)
                atomic_json(producer, {'value': 77})
                with self.assertRaises(SchemaxisError): workflow.verify(again)

    def test_every_route_has_shared_inputs_without_native_imports(self):
        for version, (_, route) in registry.routes().items():
            _, _, entry = route_materials(version)
            document = case_document(entry, entry['development']['cases'][0], ROOT)
            baseline = registry.plan(document)
            # Move the native body behind a document reference. Whole-document
            # fields work as well as node options, including the non-node routes.
            field = next(k for k in document if k not in ('version', 'dimensions', 'settings', 'definitions'))
            value = document[field]
            document.setdefault('definitions', {})['sharedInput'] = value
            document[field] = {'$document': '/definitions/sharedInput'}
            document.setdefault('settings', {})['resolvedValue'] = {'$value': 'rangeCentre', 'args': {'range': [2, 6]}}
            with self.subTest(version=version):
                actual = registry.plan(document)
                if route.get('graph'):
                    self.assertEqual(actual['pipeline']['nodes'], baseline['pipeline']['nodes'])
                else:
                    self.assertEqual(actual, baseline)
                # Shared input preparation applies even when a route does not
                # advertise the separate optional composition profile.
                self.assertIs(type(route['compose']), bool)
                # Every route receives shared analytic context, including
                # native documents without a node collection.
                document.setdefault('dimensions', {})['shared'] = {'$analytic': {'type': 'values', 'values': [1, 2]}}
                prepared = registry.plan(document)
                self.assertEqual(prepared['states'], 2)
                module = importlib.import_module(route['module'])
                self.assertEqual(module.plan(document)['states'], 2)

    def test_routes_without_workflow_support_reject_workflow_entrypoint(self):
        for version, (_, route) in registry.routes().items():
            if route.get('workflow'): continue
            _, _, entry = route_materials(version)
            document = case_document(entry, entry['development']['cases'][0], ROOT)
            with self.subTest(version=version):
                with self.assertRaises(SchemaxisError) as caught:
                    workflow.validate({'version': 'schemaxis.workflow/1', 'operations': [{'id': 'unsupported', 'document': document}]})
                self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_PROVIDER')

    def test_derived_values_follow_synchronized_analytics_at_definition_site(self):
        prepared = registry.plan(source_study())
        self.assertEqual(prepared['states'], 3)
        self.assertEqual([v['plan']['nodes'][1]['options']['size'] for v in prepared['visits']], [1, 2, 4])
        self.assertEqual([v['plan']['nodes'][0]['options']['size'][0] for v in prepared['visits']], [10, 20, 40])
        self.assertEqual(len(prepared['bindings']), 2)

    def test_independent_axes_fastest_first_and_budgets(self):
        document = source_study()
        del document['dimensions']['extent']['$analytic']['sync']
        prepared = registry.plan(document)
        self.assertEqual(prepared['states'], 9)
        self.assertEqual([v['plan']['nodes'][1]['options']['size'] for v in prepared['visits'][:3]], [1, 1, 1])
        self.assertEqual([v['plan']['nodes'][0]['options']['size'][0] for v in prepared['visits'][:3]], [10, 20, 40])
        document['maxStates'] = 8
        with self.assertRaises(SchemaxisError) as caught: registry.plan(document)
        self.assertEqual(caught.exception.fault.code, 'EXPANSION_TOO_LARGE')

    def test_all_states_validated_before_native_execution(self):
        document = source_study()
        document['dimensions']['size']['$analytic']['values'][-1] = -1
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.adaptors.gmsh.adaptor._native_run') as native:
            with self.assertRaises(SchemaxisError): registry.run(document, Path(tmp)/'run')
            native.assert_not_called()
            self.assertFalse((Path(tmp)/'run').exists())

    def test_receipts_bind_every_visit_and_detect_tampering(self):
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.adaptors.gmsh.adaptor._native_run', side_effect=fake_run), patch('schemaxis.adaptors.gmsh.adaptor._native_verify', side_effect=fake_verify):
            target = Path(tmp)/'run'
            registry.run(source_study(), target)
            self.assertEqual(registry.verify(target)['states'], 3)
            state = target/'state-00001'
            atomic_json(state/'measurement.json', {'value': 999})
            with self.assertRaises(SchemaxisError): registry.verify(target)

    def test_run_and_study_verify_shared_schema_dependencies(self):
        from schemaxis.schema_snapshots import read
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.adaptors.gmsh.adaptor._native_run', side_effect=fake_run), patch('schemaxis.adaptors.gmsh.adaptor._native_verify', side_effect=fake_verify):
            root = Path(tmp)
            single, study = root/'single', root/'study'
            registry.run(gmsh(), single)
            registry.run(source_study(), study)
            captures = [single/'schema.snapshot.json', study/'schema.snapshot.json',
                        *sorted(study.glob('state-*/schema.snapshot.json'))]
            self.assertEqual(len(captures), 5)
            schemas = [read(path) for path in captures]
            self.assertTrue(all(payload == schemas[0] for payload in schemas))
            index = json.loads((root/'schemas/index.json').read_text())
            self.assertEqual(len(index['objects']), 1)
            manifest = json.loads(captures[0].read_text())
            (root/manifest['schema']).unlink()
            for target in (single, study):
                with self.subTest(target=target), self.assertRaises(SchemaxisError) as caught:
                    registry.verify(target)
                self.assertEqual(caught.exception.fault.code, 'INVALID_SCHEMA_SNAPSHOT')

    def test_document_cycles_and_sync_length_mismatches(self):
        document = source_study()
        document['dimensions']['size'] = {'$document': '/dimensions/derived'}
        with self.assertRaises(SchemaxisError) as caught: registry.plan(document)
        self.assertEqual(caught.exception.fault.code, 'DOCUMENT_CYCLE')
        document = source_study()
        document['dimensions']['extent']['$analytic']['values'].pop()
        with self.assertRaises(SchemaxisError) as caught: registry.plan(document)
        self.assertEqual(caught.exception.fault.code, 'ANALYTIC_LENGTH_MISMATCH')

    def test_cross_document_scope_is_definition_site_and_cycles_fail(self):
        first, second = gmsh(), gmsh()
        first['dimensions'] = {'h': 3, 'alias': {'$document': './h'}, 'derived': {'$expr': {'op': 'multiply', 'args': [{'$document': '/dimensions/alias'}, 2]}}}
        second['nodes'][1]['options']['size'] = {'$document': '/dimensions/derived', 'operation': 'first'}
        document = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'first', 'document': first}, {'id': 'second', 'document': second}]}
        self.assertEqual(workflow.validate(document)[1]['document']['nodes'][1]['options']['size'], 6)
        first['dimensions']['h'] = {'$document': '/nodes/1/options/size', 'operation': 'second'}
        with self.assertRaises(SchemaxisError) as caught: workflow.validate(document)
        self.assertEqual(caught.exception.fault.code, 'DOCUMENT_CYCLE')

    def test_verified_values_become_dependencies_and_resolve_before_validation(self):
        first, second = gmsh(), gmsh()
        second['nodes'][1]['options']['size'] = {'$expr': {'op': 'multiply', 'args': [
            {'$value': 'first', 'artifact': 0, 'path': '/value'}, 2]}}
        document = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'first', 'document': first}, {'id': 'second', 'document': second}]}
        self.assertEqual(workflow.inspect_plan(document)['operations'][1]['provisionalPlan']['status'], 'deferred')
        self.assertEqual(parallel.work_items(document)[2][1]['dependencies'], ['first'])
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.adaptors.gmsh.adaptor._native_run', side_effect=fake_run), patch('schemaxis.adaptors.gmsh.adaptor._native_verify', side_effect=fake_verify):
            target = Path(tmp)/'run'
            workflow.execute(document, target)
            self.assertTrue(workflow.verify(target)['verified'])
            saved = json.loads((target/'result.json').read_text())
            second_target = Path(saved['jobs'][1]['directory'])/'state-00000'
            self.assertEqual(json.loads((second_target/'measurement.json').read_text())['value'], 6)
            resumed = workflow.execute(document, target, resume=True)
            self.assertTrue(all(job['reused'] for job in resumed['jobs']))
            atomic_json(Path(saved['jobs'][0]['directory'])/'measurement.json', {'value': 77})
            with self.assertRaises(SchemaxisError): workflow.verify(target)

    def test_global_workflow_study_keeps_cross_document_values_synchronized(self):
        first, second = gmsh(), gmsh()
        first['dimensions'] = {'h': {'$analytic': {'type': 'values', 'values': [3, 4]}}}
        first['nodes'][1]['options']['size'] = {'$document': '/dimensions/h'}
        second['nodes'][1]['options']['size'] = {'$document': '/dimensions/h', 'operation': 'first'}
        document = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'first', 'document': first}, {'id': 'second', 'document': second}]}
        prepared = workflow.inspect_plan(document)
        self.assertEqual(prepared['states'], 2)
        for index, visit in enumerate(prepared['visits']):
            self.assertEqual([o['document']['nodes'][1]['options']['size'] for o in visit['document']['operations']], [index+3]*2)
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.adaptors.gmsh.adaptor._native_run', side_effect=fake_run), patch('schemaxis.adaptors.gmsh.adaptor._native_verify', side_effect=fake_verify):
            target = Path(tmp)/'run'
            workflow.execute(document, target)
            self.assertEqual(workflow.verify(target)['states'], 2)
            workflow.execute(document, target, resume=True)
            self.assertEqual(workflow.verify(target)['states'], 2)

    def test_failed_transition_poisoning_and_closure(self):
        def broken(*args, **kwargs): fail('NATIVE_EXECUTION_FAILED', 'fixture')
        with tempfile.TemporaryDirectory() as tmp:
            session = AdaptorSession(tmp, broken, lambda *a: None, timeout=10, options={})
            with self.assertRaises(SchemaxisError): session.apply({'index': 0, 'document': gmsh()})
            with self.assertRaises(SchemaxisError) as caught: session.apply({'index': 1, 'document': gmsh()})
            self.assertEqual(caught.exception.fault.code, 'CLOSED_SESSION')
            session.close()

    def test_explicit_axes_keep_local_scopes_in_a_workflow_study(self):
        first, second = gmsh(), gmsh()
        for doc, sizes in ((first, [2, 3]), (second, [4, 5])):
            doc['axes'] = [{'name': 'h', 'values': sizes}]
            doc['nodes'][1]['options']['size'] = {'$axis': 'h'}
        document = {'version': 'schemaxis.workflow/1',
                    'axes': [{'name': 'h', 'values': [10, 20]}],
                    'dimensions': {'extent': {'$axis': 'h'}},
                    'operations': [{'id': 'a', 'document': first}, {'id': 'b', 'document': second}]}
        second['nodes'][0]['options']['size'][0] = {'$document': '/dimensions/extent', 'scope': 'workflow'}
        prepared = workflow.inspect_plan(document)
        self.assertEqual(prepared['states'], 8)
        states = [v['document']['operations'] for v in prepared['visits']]
        self.assertEqual([s[1]['document']['nodes'][0]['options']['size'][0] for s in states], [10,20]*4)
        self.assertEqual([s[0]['document']['nodes'][1]['options']['size'] for s in states], [2,2,3,3]*2)
        self.assertEqual([s[1]['document']['nodes'][1]['options']['size'] for s in states], [4]*4+[5]*4)
        self.assertTrue(all('axes' not in op['document'] for state in states for op in state))

    def test_analytic_sequence_can_depend_on_a_verified_producer_value(self):
        first, second = gmsh(), gmsh()
        second['nodes'][1]['options']['size'] = {'$analytic': {'type': 'linear',
            'start': {'$value': 'a', 'artifact': 0, 'path': '/value'}, 'end': 6, 'count': 2}}
        document = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'a', 'document': first}, {'id': 'b', 'document': second}]}
        self.assertEqual(workflow.inspect_plan(document)['operations'][1]['provisionalPlan']['status'], 'deferred')
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.adaptors.gmsh.adaptor._native_run', side_effect=fake_run), patch('schemaxis.adaptors.gmsh.adaptor._native_verify', side_effect=fake_verify):
            target = Path(tmp)/'run'
            saved = workflow.execute(document, target)
            self.assertTrue(workflow.verify(target)['verified'])
            consumer = Path(saved['jobs'][1]['directory'])
            receipt = json.loads((consumer/'verification.json').read_text())
            self.assertEqual([state['document']['nodes'][1]['options']['size'] for state in receipt['states']], [3,6])

    def test_value_bytes_are_bound_to_verified_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'producer'
            fake_run(gmsh(), target)
            receipt = json.loads((target/'verification.json').read_text())
            atomic_json(target/'measurement.json', {'value': 100})
            with patch('schemaxis.parallel.verify_native', return_value=receipt):
                with self.assertRaises(SchemaxisError) as caught:
                    parallel.resolve({'$value': 'a', 'artifact': 0, 'path': '/value'},
                                     {'a': [{'directory': str(target), 'effective': gmsh()}]})
            self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')

    def test_study_protocol_and_resume_lock_are_verified(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.adaptors.gmsh.adaptor._native_run', side_effect=fake_run), patch('schemaxis.adaptors.gmsh.adaptor._native_verify', side_effect=fake_verify):
            target = Path(tmp)/'run'
            registry.run(source_study(), target)
            original = (target/'verification.json').read_bytes()
            receipt = json.loads(original); receipt['executionMode'] = 'unverified'
            atomic_json(target/'verification.json', receipt)
            with self.assertRaises(SchemaxisError): registry.verify(target)
            (target/'verification.json').write_bytes(original)
            from schemaxis.adaptor_runtime import execute
            with (target/'.coordinator.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(SchemaxisError) as caught:
                    execute(source_study(), target, registry.resolve(gmsh())[1], fake_run,
                            registry._verify_native, registry.plan, resume=True)
            self.assertEqual(caught.exception.fault.code, 'WORKFLOW_BUSY')
            self.assertTrue(registry.verify(target)['verified'])

    def test_source_time_selection_reaches_the_native_run(self):
        # Selecting "latest" needs native source inspection, so pre-launch
        # planning must defer to the run instead of rejecting the document.
        document = {'version': 'schemaxis/1', 'times': {'source': 'case', 'select': {'latest': 1}},
                    'nodes': [{'id': 'case', 'filter': 'foam', 'options': {'file': '/absent/case.foam'}}],
                    'scenes': [{'id': 'mesh', 'geometry': ['case']}]}
        with self.assertRaises(SchemaxisError) as planned: registry.plan(document)
        self.assertEqual(planned.exception.fault.code, 'TIME_INSPECTION_REQUIRED')
        def reached(*args, **kwargs): fail('NATIVE_REACHED', 'native run was reached')
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.adaptors.paraview.job._native_run', side_effect=reached):
            with self.assertRaises(SchemaxisError) as caught: registry.run(document, Path(tmp)/'run')
        self.assertEqual(caught.exception.fault.code, 'NATIVE_REACHED')
