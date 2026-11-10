"""Catalogue breadth and pre-I/O closure across generated adaptor profiles."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.core.faults import SchemaxisError
from schemaxis.execution_inputs import CapturedInput, InputBindings, bind_document
from schemaxis.mcp_admission import FileAdmission


class CatalogueAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.admission = FileAdmission()

    def context(self, document):
        slots = self.admission.input_slots(document)
        captures, links = {}, []
        from schemaxis.observations import at_pointer
        for index, slot in enumerate(slots):
            identity = at_pointer(document, slot.pointer)
            captures.setdefault(identity, CapturedInput(identity,
                Path('/unmounted-captures/task/'+identity+slot.suffixes[0]),
                'sha256:'+'a'*64, 20, 1, index+1))
            links.append((slot.pointer, identity))
        return InputBindings('task', tuple(captures.values()), tuple(links)) if links else None

    def admit(self, document):
        context = self.context(document)
        result = self.admission.check(document, context)
        if context:
            self.assertEqual(result, self.admission.check(bind_document(document, context), context, bound=True))
        return result

    def deny(self, document):
        with self.assertRaises(SchemaxisError) as error:
            self.admission.input_slots(document)
        self.assertEqual(error.exception.fault.code, 'MCP_POLICY_DENIED')

    def test_generated_four_catalogues_are_complete_and_schemas_are_canonical(self):
        for app in ('sympy', 'numpy', 'exiftool', 'ffmpeg'):
            version = registry.metadata(app)['version']
            policy = self.admission.policies[version]
            self.assertEqual(set(policy['operations']), set(registry.declarations(app)))
            self.assertEqual(policy['schema'], registry.binding(policy['route']['schema'])())
            self.assertTrue(policy['catalogueGenerated'])
            self.assertTrue(any(name.endswith('/admission.json') for name in policy['files']))
            self.assertIn('admission_schema.py', policy['files'])

    def test_all_six_ffmpeg_operations_have_pure_complete_file_closure(self):
        options = {
            'encodeFrames': {'files': ['first', 'second']},
            'encodeSheet': {'file': 'sheet', 'metadata': 'timing'},
            'encodeVideo': {'file': 'video', 'endFrame': 10},
            'muxReview': {'video': 'video', 'audio': 'audio', 'captions': 'captions'},
            'extractAudio': {'file': 'recording', 'streamIndex': 0},
            'encodeAudio': {'file': 'audio', 'bitrateKbps': 96, 'maxBytes': 131072, 'maxMeanPCMError': 1200},
        }
        with patch.object(registry, 'plan', side_effect=AssertionError('planner ran')), \
             patch.object(registry, 'binding', side_effect=AssertionError('hook imported')):
            for operation, fields in options.items():
                document = {'version': 'schemaxis.ffmpeg/1', 'nodes': [
                    {'id': 'result', 'filter': operation, 'options': fields}]}
                with self.subTest(operation=operation):
                    self.admit(document)
                    self.deny({**document, 'executable': '/private/secret'})
                    altered = copy.deepcopy(document)
                    altered['nodes'][0]['options']['filter_complex'] = 'movie=/private/secret'
                    self.deny(altered)

    def test_conditional_file_slots_correlate_each_candidate_node(self):
        audio = {'id': 'audio', 'filter': 'encodeAudio', 'options': {'file': 'wav'}}
        video = {'id': 'video', 'filter': 'encodeVideo', 'options': {'file': 'mp4'}}
        policy = {'catalogueGenerated': True, 'operations': ['encodeAudio', 'encodeVideo'],
            'operationSelectors': ['/nodes/*/filter'], 'fileSlots': [
                {'pointer': '/nodes/*/options/file', 'suffixes': [suffix], 'maxBytes': 1024,
                 'when': {'/nodes/*/filter': operation}}
                for suffix, operation in (('.wav', 'encodeAudio'), ('.mp4', 'encodeVideo'))]}
        for nodes in ([audio, video], [video, audio]):
            document = {'version': 'schemaxis.ffmpeg/1', 'nodes': nodes}
            slots = self.admission._slots(document, policy)
            self.assertEqual({pointer: slot['suffixes'] for pointer, slot in slots.items()},
                {'/nodes/'+str(index)+'/options/file': ['.wav' if node['filter'] == 'encodeAudio' else '.mp4']
                 for index, node in enumerate(nodes)})
            # The current FFmpeg route separately requires exactly one node.
            self.deny(document)
        policy['fileSlots'][0]['when'] = {'/unbound/*/nested/*/filter': 'encodeAudio'}
        with self.assertRaises(SchemaxisError):
            self.admission._slots({'nodes': [audio]}, policy)

    def test_all_sixteen_exiftool_operations_accept_their_declared_option_grammar(self):
        # Declarations supply actual variants; these are grammar fixtures, not
        # substitutes for the adaptor's independent native verification cases.
        root = Path(__file__).resolve().parents[2]
        records = json.loads((root/'src/schemaxis/adaptors/exiftool/readiness.json').read_text())
        examples = records['routes']['schemaxis.exiftool/1']['examples']
        exercised = set()
        for example in examples:
            if example.get('expect', 'valid') != 'valid' or 'reference' not in example:
                continue
            document = json.loads((root/example['reference']).read_text())
            if document.get('version') != 'schemaxis.exiftool/1':
                continue
            operation = document['operation']
            if 'plan' in document:
                continue
            if 'folder' in document.get('media', {}):
                document['media'] = {'items': [{'id': 'photo', 'path': 'capture-photo'}]}
            # Replace only declared file slots; never infer a file by its name.
            policy = self.admission.policies[document['version']]
            for index, (pointer, _) in enumerate(self.admission._slots(document, policy).items()):
                from schemaxis.execution_inputs import _slot
                parent, leaf, _ = _slot(document, pointer)
                parent[leaf] = 'capture-'+str(index)
            with self.subTest(operation=operation, example=example['reference']):
                with patch.object(registry, 'plan', side_effect=AssertionError('planner ran')), \
                     patch.object(registry, 'binding', side_effect=AssertionError('hook imported')):
                    self.admit(document)
                    self.deny({**document, 'command': '/private/secret'})
                    for pointer in self.admission._slots(document, policy):
                        altered = copy.deepcopy(document)
                        parent, leaf, _ = _slot(altered, pointer)
                        parent[leaf] = '/private/secret'
                        self.deny(altered)
            exercised.add(operation)
        self.assertEqual(exercised, set(registry.declarations('exiftool')))

    def test_paraview_qualification_and_canonical_graph_are_not_registration(self):
        policy = self.admission.policies['schemaxis/1']
        self.assertIn('pvSphere', policy['operations'])
        self.assertIn('pvSlice', policy['operations'])
        self.assertIn('pvWriteXMLPolyDataWriter', policy['operations'])
        self.assertGreater(len(policy['unqualifiedOperations']), 0)
        document = {'version': 'schemaxis/1', 'nodes': [{'id': 'ball', 'filter': 'pvSphere'}],
                    'scenes': [{'id': 'view', 'geometry': ['ball']}]}
        self.admit(document)
        self.assertEqual(self.admission.operations(document), (('paraview', 'pvSphere'),))
        for operation in ('pvPythonCalculator', 'pvOpenFOAMReader', 'pvNetworkImageSource',
                          *policy['unqualifiedOperations'][:3]):
            self.deny({**document, 'nodes': [{'id': 'bad', 'filter': operation}]})
        self.deny({**document, 'nodes': [{'id': 'ball', 'filter': 'pvSphere',
                                        'options': {'FileName': '/private/secret'}}]})

    def test_paraview_passed_fixture_and_writer_operations_are_callable_with_canonical_shapes(self):
        root = Path(__file__).resolve().parents[2]
        evidence = json.loads((root/'verification/2026-09-16-catalogue-expansion.json').read_text())
        for case in evidence['filterQualification']['results']:
            if case['status'] != 'passed':
                continue
            document = {'version': 'schemaxis/1', 'nodes': case['fixture']['nodes'],
                        'scenes': [{'id': 'view', 'geometry': ['result']}]}
            with self.subTest(fixture=case['id']):
                self.admit(document)
                self.assertEqual(set(self.admission.operations(document)),
                    {('paraview', node['filter']) for node in document['nodes']})
        for case in evidence['writerQualification']['results']:
            document = {'version': 'schemaxis/1', 'nodes': [{'id': 'data', 'filter': 'pvSphere'}],
                        'scenes': [{'id': 'view', 'exports': [{'id': 'exported', 'node': 'data',
                                                            'writer': case['operation']}]}]}
            with self.subTest(writer=case['operation']):
                if case['status'] == 'passed':
                    self.admit(document)
                else:
                    self.deny(document)

    def test_closed_reader_graphs_and_managed_readback_have_exact_pure_contracts(self):
        root = Path(__file__).resolve().parents[2]
        record = json.loads((root/'verification/2026-10-30-paraview-closed-inputs.json').read_text())
        selected = set()
        for row in record['cases']:
            if 'example' not in row:
                continue
            document = json.loads((root/row['example']).read_text())
            policy = self.admission.policies[document['version']]
            from schemaxis.execution_inputs import _slot
            for index, pointer in enumerate(self.admission._slots(document, policy)):
                parent, leaf, _ = _slot(document, pointer)
                parent[leaf] = 'closed-input-'+str(index)
            with self.subTest(case=row['id']), \
                 patch.object(registry, 'plan', side_effect=AssertionError('planner ran')), \
                 patch.object(registry, 'binding', side_effect=AssertionError('content hook imported')):
                self.admit(document)
                selected.update(operation for provider, operation in self.admission.operations(document))
        self.assertTrue({'pvGroupDatasets', 'pvXMLRectilinearGridReader', 'pvXMLStructuredGridReader',
            'pvXMLTableReader', 'pvGenericIOMultiBlockReader'} <= selected)
        document = {'version': 'schemaxis/1', 'nodes': [{'id': 'data',
            'filter': 'pvGenericIOMultiBlockReader', 'options': {'FileName': ['capture']}}],
            'scenes': [{'id': 'view', 'geometry': ['data']}]}
        self.deny(document)
        document = json.loads((root/'examples/schemaxis/paraview-closed-inputs/genericio-tessellate.json').read_text())
        document['scenes'][0]['exports'][0]['readback']['options']['FileName'] = ['capture']
        self.deny(document)

    def test_qualified_texture_inputs_have_explicit_png_slots_and_raw_paths_refuse(self):
        document = {'version': 'schemaxis/1', 'nodes': [
            {'id': 'texture', 'filter': 'pvResourceImageTexture', 'options': {'FileName': 'image'}},
            {'id': 'logo', 'filter': 'pvLogo', 'inputs': {'Texture': 'texture'}}],
            'scenes': [{'id': 'view', 'geometry': ['logo']}]}
        self.assertEqual(self.admission.input_slots(document)[0].pointer, '/nodes/0/options/FileName')
        self.admit(document)
        document['nodes'][0]['options']['FileName'] = '/private/secret.png'
        self.deny(document)

    def test_auxiliary_writer_paths_and_unknown_nested_native_proxies_refuse(self):
        document = {'version': 'schemaxis/1', 'nodes': [{'id': 'ball', 'filter': 'pvSphere'}],
                    'scenes': [{'id': 'view', 'exports': [{'id': 'mesh', 'node': 'ball',
                        'writer': 'pvWritePOBJWriter', 'options': {'TextureFileName': '/private/secret.png'}}]}]}
        self.deny(document)
        document['scenes'] = [{'id': 'view', 'geometry': ['cut']}]
        document['nodes'].append({'id': 'cut', 'filter': 'pvClip', 'inputs': {'Input': 'ball'},
            'options': {'ClipType': {'type': 'ProgrammableImplicitFunction', 'options': {'Script': 'arbitrary()'}}}})
        self.deny(document)

    def test_generator_does_not_grant_external_plugin_core_implementation_pins(self):
        import importlib.util
        path = Path(__file__).resolve().parents[2]/'tools/mcp_admission.py'
        spec = importlib.util.spec_from_file_location('admission_generator', path)
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        manifest = {'source': 'plugin', 'routes': {'schemaxis.external/1': {}}}
        with patch.object(registry, 'ADAPTORS', {'external': manifest}), \
             patch.object(registry, 'metadata', return_value=manifest), \
             patch.object(registry, 'adaptor_files', side_effect=AssertionError('plugin resources opened')), \
             patch.object(registry, 'binding', side_effect=AssertionError('plugin hook imported')):
            self.assertEqual(set(generator.generate()), {'schemaxis.workflow/1'})
            missing = self.admission.coverage()['missing']
            self.assertEqual(len(missing), 1)
            self.assertIn('implementation-package pins', missing[0]['reason'])

    def test_workflow_prefixes_bind_only_literal_file_slots(self):
        polynomial = {'version': 'schemaxis.sympy/1', 'operation': 'isolateRealRoots', 'coefficients': ['1', '0', '-2']}
        pca = {'version': 'schemaxis.numpy/1', 'operation': 'principalComponents', 'source': 'csv',
               'channels': [{'name': 'a', 'unit': 'm'}, {'name': 'b', 'unit': 'm'}],
               'scaling': 'none', 'retention': {'components': 1}}
        document = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'roots', 'document': polynomial}, {'id': 'pca', 'document': pca}]}
        self.assertEqual(self.admission.input_slots(document)[0].pointer, '/operations/1/document/source')
        self.admit(document)
        self.deny({**pca, 'source': '/private/secret.csv'})

    def test_coverage_keeps_missing_contracts_visible(self):
        report = self.admission.coverage()
        self.assertEqual({row['provider'] for row in report['routes']},
                         {'sympy', 'numpy', 'ffmpeg', 'exiftool', 'paraview'})
        self.assertTrue(report['missing'])
        self.assertTrue(all(row['reason'] for row in report['missing']))

    def test_recomputed_declaration_cannot_hide_source_drift_or_unknown_schema_assertions(self):
        document = {'version': 'schemaxis.sympy/1', 'operation': 'isolateRealRoots',
                    'coefficients': ['1', '0', '-2']}
        for changed in ('source', 'schema'):
            policies = copy.deepcopy(self.admission.policies)
            policy = policies[document['version']]
            if changed == 'source':
                policy['files']['admission_schema.py'] = '0'*64
            else:
                policy['schema']['unevaluatedProperties'] = True
            declared = {k: v for k, v in policy.items() if k != 'contractDigest'}
            policy['contractDigest'] = 'sha256:'+hashlib.sha256(json.dumps(declared,
                sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            with self.subTest(changed=changed), self.assertRaises(SchemaxisError) as error:
                FileAdmission(policies).check(document)
            self.assertEqual(error.exception.fault.code, 'MCP_POLICY_DENIED')

    def test_schema_negation_and_alternatives_cannot_swallow_fatal_policy_errors(self):
        from schemaxis import admission_schema
        recursive = {'$defs': {'loop': {'$ref': '#/$defs/loop'}},
                     'not': {'$ref': '#/$defs/loop'}}
        for bound, value in (('MAX_DEPTH', 8), ('MAX_WORK', 8)):
            with self.subTest(bound=bound), patch.object(admission_schema, bound, value), \
                 self.assertRaises(SchemaxisError) as error:
                admission_schema.validate({}, recursive)
            self.assertIn('budget', error.exception.fault.message)
        for wrapper in ('not', 'anyOf', 'oneOf'):
            for invalid in ({'unevaluatedProperties': False}, {'$ref': '#/$defs/absent'},
                            {'$ref': 'https://invalid.example/schema'}):
                schema = ({wrapper: invalid} if wrapper == 'not' else {wrapper: [invalid, True]})
                with self.subTest(wrapper=wrapper, invalid=invalid), self.assertRaises(SchemaxisError):
                    admission_schema.validate({}, schema)
        # Ordinary value mismatch is still correctly negated or tried elsewhere.
        admission_schema.validate('text', {'not': {'type': 'integer'}})
        admission_schema.validate('text', {'anyOf': [{'type': 'integer'}, {'type': 'string'}]})


if __name__ == '__main__':
    unittest.main()
