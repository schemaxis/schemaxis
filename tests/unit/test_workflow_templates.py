# Copyright (C) 2026 David L F Gaden
"""Template binding uses captured, validated JSON and preserves failure atomicity."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis import storage, workflow
from schemaxis.core.faults import SchemaxisError
from schemaxis.workflow_templates import bind_values, load_template, prepare_template


EXAMPLE = Path(__file__).resolve().parents[2] / 'docs/design/workflow-templates/examples/reentrant'


class WorkflowTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / 'template.json'
        self.body = {'version': 'schemaxis.workflow/1',
                     'dimensions': {'height': 5, 'count': 2, 'enabled': True, 'label': 'body',
                                    'mode': 'fine', 'direction': [1, 0, 0]},
                     'operations': [{'id': 'design', 'document': {
                         'version': 'schemaxis.freecad/1', 'units': 'mm',
                         'nodes': [{'id': 'body', 'filter': 'box', 'options': {
                             'height': {'$document': '/dimensions/height', 'scope': 'workflow'},
                             'length': 20, 'width': 10}}], 'output': 'body'}}]}
        self.manifest = {'version': 'schemaxis.workflow-template/1', 'id': 'example.box',
                         'revision': 1, 'title': 'Box height', 'workflow': 'workflow.json',
                         'parameters': {'height': self.parameter('height', 'number',
                             constraints={'minimum': 1, 'maximum': 20}, default=5, units='mm')},
                         'outputs': {'shape': {'operation': 'design', 'artifact': 0, 'kind': 'geometry'}},
                         'requirements': {'providers': ['freecad'], 'qualification': 'host only'}}

    def parameter(self, target, kind, **extra):
        return {'label': target, 'kind': kind, 'target': {'scope': 'workflow',
                'pointer': '/dimensions/' + target}, **extra}

    def capture(self):
        self.path.write_bytes(storage.encoded(self.manifest))
        (self.directory / 'workflow.json').write_bytes(storage.encoded(self.body))
        return load_template(self.path)

    def case(self, bundle, **values):
        return {'version': 'schemaxis.workflow-values/1',
                'template': {'id': bundle['template']['id'], 'revision': bundle['template']['revision'],
                             'digest': bundle['digest']}, 'values': values}

    def fault(self, code, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)
        self.assertTrue(caught.exception.fault.location)

    def test_supplied_value_defaults_and_source_map(self):
        bundle = self.capture()
        case = self.case(bundle, height=7)
        old_bundle, old_case = copy.deepcopy(bundle), copy.deepcopy(case)
        result = bind_values(bundle, case)
        self.assertEqual(result['document']['dimensions']['height'], 7)
        self.assertEqual(workflow.validate(result['document'])[0]['document']['nodes'][0]['options']['height'], 7)
        self.assertEqual(result['digest'], storage.digest(result['document']))
        self.assertEqual(result['values'], {'height': 7})
        self.assertEqual(result['bindings'], [{'parameter': 'height', 'target': {
            'scope': 'workflow', 'pointer': '/dimensions/height'}, 'source': 'case', 'previous': 5, 'value': 7}])
        defaulted = bind_values(bundle, self.case(bundle))
        self.assertEqual(defaulted['values'], {'height': 5})
        self.assertEqual(defaulted['bindings'][0]['source'], 'default')
        result['document']['dimensions']['height'] = 99
        result['bindings'][0]['target']['pointer'] = 'changed'
        self.assertEqual(bundle, old_bundle)
        self.assertEqual(case, old_case)

    def test_existing_small_and_tall_examples_match_explicit_materialisation(self):
        bundle = load_template(EXAMPLE / 'template.json')
        for filename in ('values-small.json', 'values-tall.json'):
            with self.subTest(filename=filename):
                case = storage.load((EXAMPLE / filename).read_text())
                expected = copy.deepcopy(bundle['workflow'])
                expected['dimensions'].update(case['values'])
                result = bind_values(bundle, case)
                self.assertEqual(result['document'], expected)
                self.assertEqual([op['id'] for op in workflow.validate(result['document'])],
                                 ['design', 'mesh', 'table', 'revise'])
                self.assertEqual(result['template'], case['template'])

    def test_prepare_plans_without_native_processes_or_modules(self):
        bundle = self.capture()
        before = set(sys.modules)
        with patch('subprocess.Popen', side_effect=AssertionError('native launch prohibited')) as launch:
            plain = prepare_template(self.path, self.case(bundle, height=8))
            planned = prepare_template(self.path, self.case(bundle, height=8), planning=True)
        self.assertEqual(planned.pop('plan'), workflow.inspect_plan(plain['document']))
        self.assertEqual(planned, plain)
        launch.assert_not_called()
        self.assertFalse({name.split('.')[0] for name in set(sys.modules) - before} & {'FreeCAD', 'paraview', 'gmsh', 'bpy'})

    def test_capture_is_independent_of_later_file_edits(self):
        bundle = self.capture()
        self.path.write_text('{}')
        (self.directory / 'workflow.json').write_text('{}')
        self.assertEqual(bind_values(bundle, self.case(bundle, height=9))['values']['height'], 9)

    def test_required_parameter_is_not_silently_taken_from_body(self):
        del self.manifest['parameters']['height']['default']
        bundle = self.capture()
        self.fault('MISSING_PARAMETER', lambda: bind_values(bundle, self.case(bundle)))

    def test_stale_case_identity_revision_or_digest(self):
        bundle = self.capture()
        for key, value in [('id', 'different'), ('revision', 2), ('revision', True), ('digest', '0' * 64)]:
            with self.subTest(key=key, value=value):
                case = self.case(bundle)
                case['template'][key] = value
                self.fault('STALE_TEMPLATE', lambda: bind_values(bundle, case))

    def test_changed_bundle_cannot_reuse_captured_digest(self):
        bundle = self.capture()
        case = self.case(bundle)
        bundle['workflow']['dimensions']['height'] = 7
        self.fault('STALE_TEMPLATE', lambda: bind_values(bundle, case))

    def test_unknown_fields_and_unsupported_extensions_are_explicit(self):
        for field in ('assets', 'selectors', 'study', 'ui', 'unexpected'):
            with self.subTest(field=field):
                self.manifest[field] = {}
                self.fault('UNKNOWN_ARGUMENT', self.capture)
                del self.manifest[field]
        bundle = self.capture()
        for modify in (lambda c: c.update(resources={}), lambda c: c['values'].update(extra=1),
                       lambda c: c['template'].update(extra=1)):
            case = self.case(bundle)
            modify(case)
            self.fault('UNKNOWN_ARGUMENT', lambda: bind_values(bundle, case))

    def test_scalar_vector_and_enum_subset(self):
        additions = {
            'count': self.parameter('count', 'integer', constraints={'minimum': 0, 'maximum': 5}),
            'enabled': self.parameter('enabled', 'boolean'),
            'label': self.parameter('label', 'string', constraints={'minLength': 1, 'maxLength': 8}),
            'mode': self.parameter('mode', 'enum', constraints={'enum': ['fine', 'coarse']}),
            'direction': self.parameter('direction', 'vector', constraints={'length': 3, 'minimum': -1, 'maximum': 1})}
        self.manifest['parameters'].update(additions)
        bundle = self.capture()
        supplied = {'count': 3, 'enabled': False, 'label': 'new', 'mode': 'coarse', 'direction': [0, 1, -1]}
        result = bind_values(bundle, self.case(bundle, **supplied))
        self.assertEqual(result['values'], {'height': 5, **supplied})
        for name, value in [('count', True), ('count', 2.0), ('enabled', 1), ('label', ''),
                            ('mode', 'medium'), ('direction', [1, 0]), ('direction', [0, 0, True]),
                            ('direction', [2, 0, 0])]:
            with self.subTest(name=name, value=value):
                case = self.case(bundle, **{**supplied, name: value})
                self.fault('INVALID_PARAMETER', lambda: bind_values(bundle, case))

    def test_enum_preserves_boolean_numeric_distinction(self):
        self.manifest['parameters']['count'] = self.parameter('count', 'enum', constraints={'enum': [1, 2]})
        bundle = self.capture()
        self.fault('INVALID_PARAMETER', lambda: bind_values(bundle, self.case(bundle, count=True)))
        self.assertEqual(bind_values(bundle, self.case(bundle, count=2.0))['values']['count'], 2.0)

    def test_defaults_and_original_targets_must_satisfy_parameter_contract(self):
        self.manifest['parameters']['height']['default'] = 0
        self.fault('INVALID_PARAMETER', self.capture)
        self.manifest['parameters']['height']['default'] = 5
        self.body['dimensions']['height'] = '5'
        self.fault('INVALID_PARAMETER', self.capture)

    def test_invalid_constraint_definitions(self):
        for kind, constraints in [('number', {'minimum': True}), ('number', {'minimum': 3, 'maximum': 2}),
                                  ('string', {'minLength': 3, 'maxLength': 2}), ('vector', {}),
                                  ('vector', {'length': True}), ('vector', {'length': 1025}),
                                  ('enum', {'enum': []}), ('enum', {'enum': [1, 1.0]}),
                                  ('enum', {'enum': [1, True]}), ('enum', {'enum': [{}]})]:
            with self.subTest(kind=kind, constraints=constraints):
                self.manifest['parameters']['height'] = self.parameter('height', kind, constraints=constraints)
                self.fault('INVALID_TEMPLATE', self.capture)

    def test_unsupported_constraints_kinds_and_scopes(self):
        self.manifest['parameters']['height']['constraints']['pattern'] = '.*'
        self.fault('UNKNOWN_ARGUMENT', self.capture)
        del self.manifest['parameters']['height']['constraints']['pattern']
        for kind in ('resource', 'selection', 'analytic', 'unknown'):
            self.manifest['parameters']['height']['kind'] = kind
            self.fault('UNSUPPORTED_PARAMETER_KIND', self.capture)
        self.manifest['parameters']['height']['kind'] = 'number'
        self.manifest['parameters']['height']['target']['scope'] = 'operation'
        self.fault('UNSUPPORTED_BINDING', self.capture)

    def test_nonfinite_and_non_json_inputs_fail(self):
        bundle = self.capture()
        for value in (float('nan'), float('inf'), (1, 2), {1: 'bad key'}):
            with self.subTest(value=value):
                self.fault('INVALID_DOCUMENT', lambda: bind_values(bundle, self.case(bundle, height=value)))

    def test_plain_units_only_and_no_expression_substitution(self):
        bundle = self.capture()
        for value in ({'value': 0.007, 'units': 'm'}, {'$analytic': {'type': 'values', 'values': [5, 7]}},
                      {'$expr': {'op': 'add', 'args': [2, 3]}}, True):
            with self.subTest(value=value):
                self.fault('INVALID_PARAMETER', lambda: bind_values(bundle, self.case(bundle, height=value)))

    def test_late_parameter_failure_does_not_apply_earlier_binding(self):
        self.manifest['parameters']['count'] = self.parameter('count', 'integer')
        bundle = self.capture()
        case = self.case(bundle, height=8, count='bad')
        before_bundle, before_case = copy.deepcopy(bundle), copy.deepcopy(case)
        self.fault('INVALID_PARAMETER', lambda: bind_values(bundle, case))
        self.assertEqual(bundle, before_bundle)
        self.assertEqual(case, before_case)

    def test_downstream_host_validation_cannot_be_weakened_by_parameter_bounds(self):
        self.manifest['parameters']['height']['constraints']['minimum'] = -10
        bundle = self.capture()
        case = self.case(bundle, height=-1)
        before = copy.deepcopy(bundle)
        with self.assertRaises(SchemaxisError):
            bind_values(bundle, case)
        self.assertEqual(bundle, before)

    def test_deleted_target_and_unsupported_target_roots(self):
        target = self.manifest['parameters']['height']['target']
        target['pointer'] = '/dimensions/missing'
        self.fault('INVALID_BINDING', self.capture)
        for pointer in ('', '/dimensions', '/operations/0/document/nodes/0/options/height'):
            target['pointer'] = pointer
            self.fault('UNSUPPORTED_BINDING', self.capture)

    def test_duplicate_and_ancestor_binding_targets_fail(self):
        self.manifest['parameters']['duplicate'] = copy.deepcopy(self.manifest['parameters']['height'])
        self.fault('OVERLAPPING_BINDINGS', self.capture)
        del self.manifest['parameters']['duplicate']
        self.manifest['parameters']['direction'] = self.parameter('direction', 'vector', constraints={'length': 3})
        self.manifest['parameters']['component'] = self.parameter('direction/0', 'number')
        self.fault('OVERLAPPING_BINDINGS', self.capture)

    def test_json_pointer_escapes_and_array_indices(self):
        self.body['dimensions']['slash/~key'] = 4
        self.manifest['parameters']['escaped'] = self.parameter('slash~1~0key', 'integer')
        self.manifest['parameters']['component'] = self.parameter('direction/0', 'number')
        bundle = self.capture()
        result = bind_values(bundle, self.case(bundle, escaped=6, component=0.5))
        self.assertEqual(result['document']['dimensions']['slash/~key'], 6)
        self.assertEqual(result['document']['dimensions']['direction'], [0.5, 0, 0])
        for pointer in ('/dimensions/bad~', '/dimensions/bad~2', 'dimensions/height',
                        '/dimensions/direction/01', '/dimensions/direction/-', '/dimensions/direction/3',
                        '/dimensions/direction/' + '9' * 5000):
            self.manifest['parameters']['component']['target']['pointer'] = pointer
            self.fault('INVALID_BINDING', self.capture)

    def test_output_alias_contract_does_not_claim_artifact_existence(self):
        self.manifest['outputs']['shape']['artifact'] = 999
        bundle = self.capture()
        self.assertEqual(bundle['template']['outputs']['shape']['artifact'], 999)
        for key, value in [('operation', 'absent'), ('artifact', -1), ('artifact', True)]:
            self.manifest['outputs']['shape'] = {'operation': 'design', 'artifact': 0, 'kind': 'geometry', key: value}
            self.fault('INVALID_OUTPUT_ALIAS', self.capture)
        self.manifest['outputs']['shape'] = {'operation': 'design', 'artifact': 0, 'kind': 'geometry', 'pointer': '/bad~3'}
        self.fault('INVALID_BINDING', self.capture)

    def test_requirements_derive_from_actual_workflow(self):
        for providers in (['gmsh'], ['freecad', 'freecad'], 'freecad'):
            self.manifest['requirements']['providers'] = providers
            self.fault('INVALID_REQUIREMENTS', self.capture)

    def test_workflow_order_and_identity_validation_are_preserved(self):
        self.body['operations'].append(copy.deepcopy(self.body['operations'][0]))
        self.fault('DUPLICATE_OPERATION', self.capture)

    def test_workflow_paths_are_confined_and_regular(self):
        for value in ('../workflow.json', '/workflow.json', './workflow.json', 'sub/../workflow.json',
                      'sub//workflow.json', 'C:\\workflow.json', 'workflow.json\x00'):
            with self.subTest(value=value):
                self.manifest['workflow'] = value
                self.fault('INVALID_TEMPLATE_PATH', self.capture)
        self.manifest['workflow'] = 'workflow.json'
        self.capture()
        (self.directory / 'workflow.json').unlink()
        (self.directory / 'workflow.json').symlink_to(self.path)
        self.fault('INVALID_TEMPLATE_PATH', lambda: load_template(self.path))
        (self.directory / 'workflow.json').unlink()
        (self.directory / 'workflow.json').mkdir()
        self.fault('INVALID_TEMPLATE_PATH', lambda: load_template(self.path))

    def test_workflow_cannot_cross_symlinked_directory(self):
        self.capture()
        (self.directory / 'link').symlink_to(self.directory, target_is_directory=True)
        self.manifest['workflow'] = 'link/workflow.json'
        self.path.write_bytes(storage.encoded(self.manifest))
        self.fault('INVALID_TEMPLATE_PATH', lambda: load_template(self.path))

    def test_duplicate_json_keys_and_symlinked_manifest_fail(self):
        self.capture()
        self.path.write_text('{"version": "a", "version": "b"}')
        self.fault('INVALID_DOCUMENT', lambda: load_template(self.path))
        self.path.unlink()
        self.path.symlink_to(self.directory / 'workflow.json')
        self.fault('INVALID_TEMPLATE_PATH', lambda: load_template(self.path))

    def test_manifest_symlink_ancestor_and_parent_alias_are_rejected(self):
        self.capture()
        nested = self.directory / 'other' / 'nested'
        nested.mkdir(parents=True)
        (self.directory / 'other' / 'template.json').write_text('{}')
        link = self.directory / 'link'
        link.symlink_to(nested, target_is_directory=True)
        alias = link / '..' / 'template.json'
        # OS traversal selects other/template.json, whereas collapsing link/..
        # selects the valid template in self.directory. Neither may be guessed.
        self.assertEqual(alias.read_text(), '{}')
        self.fault('INVALID_TEMPLATE_PATH', lambda: load_template(alias))
        root_link = self.directory / 'root-link'
        root_link.symlink_to(self.directory, target_is_directory=True)
        self.fault('INVALID_TEMPLATE_PATH', lambda: load_template(root_link / 'template.json'))

    def test_deep_file_json_has_structured_depth_fault(self):
        self.capture()
        for depth in (100, 2000):
            for path in (self.path, self.directory / 'workflow.json'):
                with self.subTest(depth=depth, path=path.name):
                    self.capture()
                    path.write_text('[' * depth + '0' + ']' * depth)
                    self.fault('INVALID_DOCUMENT', lambda: load_template(self.path))

    def test_deep_or_cyclic_memory_json_is_rejected_without_mutation(self):
        bundle = self.capture()
        deep = 0
        for _ in range(100):
            deep = [deep]
        case = self.case(bundle, height=deep)
        self.fault('INVALID_DOCUMENT', lambda: bind_values(bundle, case))
        self.assertIs(case['values']['height'], deep)
        cyclic_bundle = dict(bundle)
        cyclic_bundle['cycle'] = cyclic_bundle
        self.fault('INVALID_DOCUMENT', lambda: bind_values(cyclic_bundle, self.case(bundle)))
        self.assertIs(cyclic_bundle['cycle'], cyclic_bundle)
        cyclic_case = self.case(bundle)
        cyclic_case['values']['height'] = cyclic_case
        self.fault('INVALID_DOCUMENT', lambda: bind_values(bundle, cyclic_case))
        self.assertIs(cyclic_case['values']['height'], cyclic_case)


if __name__ == '__main__':
    unittest.main()
