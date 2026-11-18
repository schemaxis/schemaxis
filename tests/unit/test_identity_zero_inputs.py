# Copyright (C) 2026 David L. F. Gaden.
"""Checked identity previews for closed zero-input source nodes, qualified on Calc.

Host-only: nothing here starts LibreOffice or reads an authored CSV source.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.errors import SchemaxisError
from schemaxis.identity_policy import accepts_name, for_route, validate
from schemaxis.identity_rename import rename_identity
from schemaxis.identity_transition import checked_transition, proof, replay, stored, verify
from schemaxis.storage import digest

ROOT = Path(__file__).resolve().parents[2]
MISSING_CSV = '/nonexistent-schemaxis-zero-input/data.csv'

# Each source carries the old node name as literal workbook data that must survive.
SOURCES = {
    'fromRows': {'filter': 'fromRows', 'options': {'columns': ['data', 'Force'], 'rows': [[0, 2], [1, 5], [2, 8]]}},
    'readCSV': {'filter': 'readCSV', 'options': {'file': MISSING_CSV}},
    'fromTypedRows': {'filter': 'fromTypedRows', 'options': {
        'columns': [{'name': 'data', 'kind': 'text'}, {'name': 'Mass', 'kind': 'number', 'nullable': True}],
        'rows': [['data', 1.5], ['=data', None], ['@data', 2.5]]}},
    'readTypedCSV': {'filter': 'readTypedCSV', 'options': {
        'file': MISSING_CSV, 'columns': [{'name': 'data', 'kind': 'text'}, {'name': 'Mass', 'kind': 'number'}]}},
}
REQUIREMENTS = [
    {'name': 'data', 'type': 'cellBounds', 'cell': {'sheet': 'Data', 'cell': 'B2'}, 'minimum': 0},
    {'name': 'Summary', 'type': 'reconcile', 'absoluteTolerance': 1e-9, 'target': 0,
     'terms': [{'sheet': 'Data', 'cell': 'B2', 'coefficient': 1}, {'sheet': 'Data', 'cell': 'B4', 'coefficient': -1}]}]


def calc(node, **sections):
    return {'version': 'schemaxis.calc/1', 'nodes': [{'id': 'data', **copy.deepcopy(node)}], **copy.deepcopy(sections)}


def example(name):
    return json.loads((ROOT / 'examples/schemaxis' / name).read_text())


def host_plan(value):
    """Compile on the host; an attempt to read the CSV source fails the test."""
    with patch('schemaxis.adaptors.calc.adaptor.source_bytes', side_effect=AssertionError('CSV source was read')):
        return registry.plan(value)


class Preview(unittest.TestCase):
    def preview(self, value, new, path='/nodes/0/id'):
        before = copy.deepcopy(value)
        result = rename_identity(value, path, new, digest(value))
        self.assertEqual(before, value)
        self.assertEqual(digest(before), result['inputDigest'])
        self.assertEqual(digest(result['input']), result['outputDigest'])
        return result

    def refuses(self, value, code, new='table2', path='/nodes/0/id', location=None):
        before = copy.deepcopy(value)
        with self.assertRaises(SchemaxisError) as caught:
            rename_identity(value, path, new, digest(value))
        self.assertEqual(code, caught.exception.fault.code, caught.exception.fault)
        if location is not None:
            self.assertEqual(location, caught.exception.fault.location)
        self.assertEqual(before, value)
        return caught.exception.fault


class CalcSourceRename(Preview):
    def test_all_four_sources_change_only_the_identity_and_compile_identically(self):
        for operation, node in SOURCES.items():
            with self.subTest(operation=operation):
                value = calc(node, requirements=REQUIREMENTS, settings={'data': 3})
                result = self.preview(value, 'table2')
                expected = copy.deepcopy(value)
                expected['nodes'][0]['id'] = 'table2'
                self.assertEqual(expected, result['input'])
                self.assertEqual(list(value['nodes'][0]), list(result['input']['nodes'][0]))
                self.assertNotIn('inputs', result['input']['nodes'][0])
                self.assertEqual(['/nodes/0/id'], result['changedPointers'])
                self.assertEqual([{'identity': 'node', 'scope': '', 'pointer': '/nodes/0/id', 'old': 'data',
                                   'new': 'table2', 'route': 'schemaxis.calc/1', 'provider': 'calc'}],
                                 result['identityChanges'])
                before, after = host_plan(value), host_plan(result['input'])
                self.assertEqual('table2', after['nodes'][0]['id'])
                self.assertEqual(['Data', 'Summary'], after['sheets'])
                after['nodes'][0]['id'] = 'data'
                self.assertEqual(before, after)

    def test_names_follow_the_actual_calc_identifier_rule(self):
        value = calc(SOURCES['fromRows'])
        for name in ('2data', '2-left', 'a-b', 'a b', 'café', 'a' * 65, ''):
            with self.subTest(name=name):
                self.refuses(value, 'INVALID_IDENTITY', name, location='$newName')
                rejected = copy.deepcopy(value)
                rejected['nodes'][0]['id'] = name
                with self.assertRaises(SchemaxisError):
                    host_plan(rejected)
        for name in ('a' * 64, 'Z_9', 'x'):
            with self.subTest(name=name):
                self.assertEqual(name, host_plan(self.preview(value, name)['input'])['nodes'][0]['id'])
        invalid = calc(SOURCES['fromRows'])
        invalid['nodes'][0]['id'] = '9lives'
        self.refuses(invalid, 'INVALID_IDENTITY', 'lives', location='$/nodes/0/id')

    def test_noop_stale_collision_and_non_identity_pointers(self):
        value = calc(SOURCES['fromTypedRows'], requirements=REQUIREMENTS)
        same = self.preview(value, 'data')
        self.assertEqual(value, same['input'])
        self.assertEqual(([], []), (same['changedPointers'], same['identityChanges']))
        self.assertEqual(same['inputDigest'], same['outputDigest'])
        with self.assertRaises(SchemaxisError) as caught:
            checked_transition({'input': value}, '/nodes/0/id', 'data', digest(value))
        self.assertEqual('IDENTITY_TRANSITION_NOOP', caught.exception.fault.code)
        with self.assertRaises(SchemaxisError) as caught:
            rename_identity(value, '/nodes/0/id', 'table2', digest(calc(SOURCES['fromRows'])))
        self.assertEqual('STALE_IDENTITY_INPUT', caught.exception.fault.code)
        pair = calc(SOURCES['fromRows'])
        pair['nodes'].append({**copy.deepcopy(SOURCES['fromRows']), 'id': 'other'})
        self.refuses(pair, 'IDENTITY_COLLISION', 'other', location='$newName')
        pair['nodes'][1]['id'] = 'data'
        self.refuses(pair, 'AMBIGUOUS_IDENTITY_SCOPE')
        for path in ('/nodes/0/filter', '/nodes/0/options/columns/0/name', '/requirements/0/name', '/nodes/0'):
            with self.subTest(path=path):
                self.refuses(value, 'UNSUPPORTED_IDENTITY', path=path)

    def test_no_input_container_or_undeclared_node_property_is_accepted(self):
        cases = [({'inputs': {}}, '$/nodes/0/inputs'), ({'inputs': {'source': 'data'}}, '$/nodes/0/inputs'),
                 ({'label': 'data'}, '$/nodes/0/label')]
        for extra, location in cases:
            value = calc(SOURCES['readCSV'])
            value['nodes'][0].update(extra)
            for new in ('table2', 'data'):
                with self.subTest(extra=extra, new=new):
                    self.refuses(value, 'UNSUPPORTED_IDENTITY_REFERENCE', new, location=location)
        for discriminator in ('readXLSX', {'$fill': 'source'}, None):
            value = calc(SOURCES['readCSV'])
            value['nodes'][0]['filter'] = discriminator
            with self.subTest(discriminator=discriminator):
                self.refuses(value, 'UNSUPPORTED_IDENTITY_REFERENCE', location='$/nodes/0/filter')

    def test_undeclared_graph_markers_refuse_where_they_could_name_the_identity(self):
        refused = [{'$observe': 'data', 'path': ['bounds']}, {'$object': 'data'},
                   {'$sample': 'table2', 'association': 'points', 'field': 'p', 'index': 0},
                   {'$observe': {'$document': '/nodes/0/id'}}]
        for cell in refused:
            value = calc(SOURCES['fromTypedRows'])
            value['nodes'][0]['options']['rows'][0][1] = cell
            marker = next(key for key in cell if key in ('$observe', '$object', '$sample'))
            with self.subTest(cell=cell):
                self.refuses(value, 'UNSUPPORTED_IDENTITY_REFERENCE', location='$/nodes/0/options/rows/0/1/' + marker)
        unrelated = calc(SOURCES['fromTypedRows'])
        unrelated['nodes'][0]['options']['rows'][0][1] = {'$observe': 'other', 'path': ['bounds']}
        self.assertEqual(unrelated['nodes'][0]['options'], self.preview(unrelated, 'table2')['input']['nodes'][0]['options'])

    def test_document_and_expression_references_bind_by_their_own_rules(self):
        value = calc({'filter': 'fromTypedRows', 'options': {
            'columns': [{'name': 'Label', 'kind': 'text'}, {'name': 'Mass', 'kind': 'number'}],
            'rows': [[{'$document': '/nodes/0/id'}, {'$expr': 'data * 2'}], ['data', {'$document': '/settings/gain'}]]}},
            settings={'data': 3, 'gain': 2})
        result = self.preview(value, 'table2')
        expected = copy.deepcopy(value)
        expected['nodes'][0]['id'] = 'table2'
        self.assertEqual(expected, result['input'])
        self.assertEqual(['/nodes/0/id'], result['changedPointers'])
        self.assertEqual([['data', 6], ['data', 2]], host_plan(value)['nodes'][0]['options']['rows'])
        self.assertEqual([['table2', 6], ['data', 2]], host_plan(result['input'])['nodes'][0]['options']['rows'])
        broken = copy.deepcopy(value)
        broken['settings']['bad'] = {'$expr': '1 +'}
        self.refuses(broken, 'UNRESOLVED_IDENTITY_EXPRESSION', location='$/settings/bad/$expr')

    def test_studio_snippet_drafts_keep_placeholders_and_unfilled_identities_refuse(self):
        snippets = {item['id']: item for item in json.loads(
            (ROOT / 'src/schemaxis/adaptors/calc/studio.json').read_text())['snippets']}
        draft = snippets['csv-workbook']['inserts'][0]['values'][0]
        result = self.preview(draft, 'results')
        self.assertEqual({'$fill': 'file'}, result['input']['nodes'][0]['options']['file'])
        self.assertEqual(['/nodes/0/id'], result['changedPointers'])
        unnamed = {'version': 'schemaxis.calc/1', 'nodes': snippets['sample-table']['inserts'][0]['values'][0]}
        self.refuses(unnamed, 'INVALID_IDENTITY', 'measurements', location='$/nodes/0/id')


class CalcWorkflowRename(Preview):
    def test_workflow_operation_scope_keeps_peers_and_upstream_artifacts(self):
        from schemaxis.workflow import validate as validate_workflow
        value = example('imagej-to-calc.json')
        result = self.preview(value, 'regions', '/operations/1/document/nodes/0/id')
        self.assertEqual(['/operations/1/document/nodes/0/id'], result['changedPointers'])
        self.assertEqual('/operations/1/document', result['identityChanges'][0]['scope'])
        self.assertEqual({'$artifact': 'particles', 'index': 0},
                         result['input']['operations'][1]['document']['nodes'][0]['options']['file'])
        validate_workflow(result['input'])
        peers = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'first', 'document': calc(SOURCES['fromRows'])}, {'id': 'second', 'document': calc(SOURCES['fromRows'])}]}
        result = self.preview(peers, 'table2', '/operations/0/document/nodes/0/id')
        self.assertEqual('table2', result['input']['operations'][0]['document']['nodes'][0]['id'])
        self.assertEqual(peers['operations'][1], result['input']['operations'][1])

    def test_producer_outputs_and_borrowed_identities_refuse_at_their_consumers(self):
        value = example('calc-typed-handoff.json')
        self.refuses(value, 'UNSUPPORTED_IDENTITY_OUTPUT_REFERENCE', 'made', '/operations/0/document/nodes/0/id',
                     location='$/operations/1/document/nodes/0/options/file')
        received = self.preview(value, 'received', '/operations/1/document/nodes/0/id')
        self.assertEqual(['/operations/1/document/nodes/0/id'], received['changedPointers'])
        self.assertEqual(value['operations'][0], received['input']['operations'][0])
        borrowed = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'first', 'document': calc(SOURCES['fromRows'])}, {'id': 'second', 'document': calc(SOURCES['fromRows'])}]}
        borrowed['operations'][1]['document']['nodes'][0]['id'] = {'$document': '/nodes/0/id', 'operation': 'first'}
        self.refuses(borrowed, 'UNSUPPORTED_IDENTITY_COMPOSITION', 'table2', '/operations/0/document/nodes/0/id',
                     location='$/operations/1/document/nodes/0/id')

    def test_design_envelope_scope(self):
        from schemaxis import workflow_design
        value = workflow_design.create(example('calc-typed-handoff.json'))
        result = self.preview(value, 'received', '/workflow/operations/1/document/nodes/0/id')
        self.assertEqual(['/workflow/operations/1/document/nodes/0/id'], result['changedPointers'])
        workflow_design.validate(result['input'])


class CalcTransition(Preview):
    def test_proof_verify_replay_round_trip_is_bound_to_the_admitted_policy(self):
        value = calc(SOURCES['fromTypedRows'], requirements=REQUIREMENTS)
        evidence = proof(value, '/nodes/0/id', 'table2')
        bound = evidence['binding']
        self.assertEqual(digest(for_route(*registry.resolve(value))), bound['policyDigest'])
        self.assertEqual(('', None, 'calc', 'schemaxis.calc/1'),
                         (bound['scope'], bound['operation'], bound['provider'], bound['route']))
        self.assertEqual((value, evidence['after'], [['data', 'table2']]), verify(evidence))
        self.assertEqual((evidence['after'], value, [['table2', 'data']]), verify(evidence, reverse=True))
        self.assertEqual(evidence['after'], stored(evidence))
        self.assertEqual(evidence['after'], replay(value, [('data', 'table2')]))
        self.assertEqual(value, replay(evidence['after'], [('table2', 'data')]))
        with self.assertRaises(SchemaxisError) as caught:
            replay(value, [('missing', 'table2')])
        self.assertEqual('IDENTITY_TRANSITION_MISMATCH', caught.exception.fault.code)
        tampered = copy.deepcopy(evidence)
        tampered['after']['nodes'][0]['options']['rows'][0][0] = 'changed'
        with self.assertRaises(SchemaxisError) as caught:
            verify(tampered)
        self.assertEqual('STALE_IDENTITY_TRANSITION', caught.exception.fault.code)
        changed = {**for_route(*registry.resolve(value)), 'note': 'different authority'}
        with patch('schemaxis.identity_rename.for_route', return_value=changed), self.assertRaises(SchemaxisError) as caught:
            verify(evidence)
        self.assertEqual('STALE_IDENTITY_TRANSITION', caught.exception.fault.code)

    def test_transition_scope_must_match_the_selected_operation(self):
        value = example('calc-typed-handoff.json')
        evidence = proof(value, '/operations/1/document/nodes/0/id', 'received', operation='consumer')
        self.assertEqual(('/operations/1/document', 'consumer'), (evidence['binding']['scope'], evidence['binding']['operation']))
        with self.assertRaises(SchemaxisError) as caught:
            proof(value, '/operations/1/document/nodes/0/id', 'received', operation='producer')
        self.assertEqual('IDENTITY_SCOPE_MISMATCH', caught.exception.fault.code)

    def test_preview_reads_no_source_writes_nothing_and_starts_no_process(self):
        script = '''
import os, sys
from schemaxis.identity_rename import rename_identity
from schemaxis.identity_transition import proof, verify, replay
from schemaxis.storage import digest
CSV = sys.argv[1]
def hook(event, args):
    if event == 'open':
        path, mode, flags = args
        if str(path) == CSV or (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)):
            raise AssertionError('forbidden open %r' % (args,))
    if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.fork'):
        raise AssertionError('forbidden process ' + event)
sys.addaudithook(hook)
for node in ({'filter': 'readCSV', 'options': {'file': CSV}},
             {'filter': 'readTypedCSV', 'options': {'file': CSV, 'columns': [{'name': 'x', 'kind': 'number'}]}}):
    value = {'version': 'schemaxis.calc/1', 'nodes': [{'id': 'data', **node}]}
    result = rename_identity(value, '/nodes/0/id', 'table2', digest(value))
    verify(proof(value, '/nodes/0/id', 'table2'), reverse=True)
    assert replay(value, [('data', 'table2')]) == result['input']
print('guarded')
'''
        environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'}
        completed = subprocess.run([sys.executable, '-B', '-c', script, MISSING_CSV], cwd=ROOT, env=environment,
                                   capture_output=True, text=True, timeout=300)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual('guarded', completed.stdout.strip())


class ZeroInputAdmission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider, cls.route = registry.resolve(calc(SOURCES['fromRows']))
        cls.data = registry.binding(cls.route['authoringReferences'])()
        cls.schema = registry.binding(cls.route['schema'])()
        cls.declarations = registry.declarations(cls.provider)

    def variants(self, schema):
        return schema['properties']['nodes']['items']['oneOf']

    def refuses(self, data=None, schema=None, declarations=None, graph_route=False, location=None):
        with self.assertRaises(SchemaxisError) as caught:
            validate(self.data if data is None else data, self.schema if schema is None else schema,
                     self.declarations if declarations is None else declarations, graph_route=graph_route)
        self.assertEqual('INVALID_REFERENCE_POLICY', caught.exception.fault.code)
        if location is not None:
            self.assertEqual(location, caught.exception.fault.location)
        return caught.exception.fault

    def test_actual_policy_projects_closed_zero_input_sources(self):
        self.assertFalse(self.route['graph'])
        admitted = for_route(self.provider, self.route)
        projection = admitted['projection']['node']
        self.assertEqual({operation: {} for operation in SOURCES}, projection['operations'])
        self.assertEqual({}, projection['writers'])
        self.assertEqual({operation: ['filter', 'id', 'options'] for operation in SOURCES}, projection['properties'])
        self.assertIsNone(admitted['identities'][0]['graph']['inputs'])
        self.assertEqual(([], [], {}), (admitted['references'], admitted['markers'], admitted['expressions']))
        self.assertEqual(admitted, validate(self.data, self.schema, self.declarations, graph_route=False))
        json.dumps(admitted, allow_nan=False)

    def test_no_container_spelling_needs_an_explicit_non_graph_route(self):
        for graph_route in (None, True):
            with self.subTest(graph_route=graph_route):
                self.refuses(graph_route=graph_route, location='$policy.identities/0/graph')
        with self.assertRaises(SchemaxisError) as caught:
            for_route(self.provider, {**self.route, 'graph': True})
        self.assertEqual('INVALID_REFERENCE_POLICY', caught.exception.fault.code)

    def test_graph_spelling_or_an_invented_container_is_refused(self):
        copied = copy.deepcopy(self.data)
        copied['identities'][0]['graph']['inputs'] = 'inputs'
        self.refuses(copied, location='$policy.identities/0/graph')
        container = {'type': 'object', 'properties': {}, 'additionalProperties': False}
        everywhere, mixed = copy.deepcopy(self.schema), copy.deepcopy(self.schema)
        for variant in self.variants(everywhere):
            variant['properties']['inputs'] = copy.deepcopy(container)
        self.variants(mixed)[1]['properties']['inputs'] = copy.deepcopy(container)
        for schema in (everywhere, mixed):
            self.refuses(schema=schema, location='$policy.identities/0/graph')

    def test_malformed_no_container_policy_data_refuses(self):
        graphs = [{'discriminator': 'filter'}, {'discriminator': 'filter', 'inputs': ''},
                  {'discriminator': 'filter', 'inputs': False}, {'discriminator': 'filter', 'inputs': 0},
                  {'discriminator': 'filter', 'inputs': []}, {'discriminator': 'filter', 'inputs': {}},
                  {'discriminator': None, 'inputs': None}, {'discriminator': '', 'inputs': None},
                  {'discriminator': 'filter', 'inputs': None, 'container': 'none'},
                  {'discriminator': 'kind', 'inputs': None}]
        for graph in graphs:
            data = copy.deepcopy(self.data)
            data['identities'][0]['graph'] = graph
            with self.subTest(graph=graph):
                self.refuses(data)

    def test_nonzero_undeclared_or_writer_declarations_refuse(self):
        mutations = [lambda d: d['readCSV'].update(inputs={'source': {'multiple': False}}),
                     lambda d: d['readCSV'].pop('inputs'),
                     lambda d: d['readCSV'].update(inputs=None),
                     lambda d: d.update(exportTable={'role': 'writer', 'inputs': {}}),
                     lambda d: d.update(readXLSX={'inputs': {}}),
                     lambda d: d.pop('readCSV')]
        for index, mutate in enumerate(mutations):
            declarations = copy.deepcopy(self.declarations)
            mutate(declarations)
            with self.subTest(mutation=index):
                self.refuses(declarations=declarations)

    def test_open_or_ambiguous_source_schemas_refuse(self):
        def variant(index, change):
            def mutate(schema):
                change(self.variants(schema)[index])
            return mutate
        mutations = [variant(0, lambda v: v.pop('additionalProperties')),
                     variant(1, lambda v: v.update(additionalProperties=True)),
                     variant(2, lambda v: v.update(additionalProperties={})),
                     variant(3, lambda v: v.update(patternProperties={'^x': {}})),
                     variant(0, lambda v: v.pop('type')),
                     variant(1, lambda v: v['properties']['id'].update(pattern='^[A-Za-z0-9_]{1,64}$')),
                     variant(2, lambda v: v['properties']['filter'].update(const='fromRows'))]
        for index, mutate in enumerate(mutations):
            schema = copy.deepcopy(self.schema)
            mutate(schema)
            with self.subTest(mutation=index):
                self.refuses(schema=schema)


LINE_BREAK_NAMES = ('fresh\n', 'x' * 64 + '\n')
BOUNDARY_NAMES = ('fresh', 'x' * 64, 'Z_9')
CANDIDATES = ('fresh', 'fresh\n', 'fresh\r', 'fresh\r\n', '\nfresh', 'a\nb', 'fresh\n\n', 'x' * 64,
              'x' * 64 + '\n', 'x' * 65, '2data', 'caf\u00e9', '', 'Z_9', 'a-b')


def planner_fault(name):
    """The actual Calc host planner's verdict on one node id, or None when it accepts."""
    value = calc(SOURCES['fromRows'])
    value['nodes'][0]['id'] = name
    try:
        host_plan(value)
    except SchemaxisError as error:
        return error.fault.code
    return None


class CalcNameIsTheWholeString(Preview):
    def test_line_break_names_refuse_in_preview_and_proof_like_the_planner(self):
        for operation, node in SOURCES.items():
            for name in LINE_BREAK_NAMES:
                with self.subTest(operation=operation, name=name):
                    value = calc(node, requirements=REQUIREMENTS)
                    before = copy.deepcopy(value)
                    self.refuses(value, 'INVALID_IDENTITY', name, location='$newName')
                    with self.assertRaises(SchemaxisError) as caught:
                        proof(value, '/nodes/0/id', name)
                    self.assertEqual('INVALID_IDENTITY', caught.exception.fault.code)
                    self.assertEqual(before, value)
                    rejected = copy.deepcopy(value)
                    rejected['nodes'][0]['id'] = name
                    with self.assertRaises(SchemaxisError) as caught:
                        host_plan(rejected)
                    self.assertEqual('INVALID_NAME', caught.exception.fault.code)

    def test_boundary_names_round_trip_through_preview_proof_and_planner(self):
        for operation, node in SOURCES.items():
            for name in BOUNDARY_NAMES:
                with self.subTest(operation=operation, name=name):
                    value = calc(node, requirements=REQUIREMENTS)
                    result = self.preview(value, name)
                    evidence = proof(value, '/nodes/0/id', name)
                    self.assertEqual(result['input'], evidence['after'])
                    self.assertEqual((value, evidence['after'], [['data', name]]), verify(evidence))
                    self.assertEqual(name, host_plan(result['input'])['nodes'][0]['id'])

    def test_existing_line_break_identity_is_refused_without_change(self):
        for operation, node in SOURCES.items():
            for old in LINE_BREAK_NAMES:
                with self.subTest(operation=operation, old=old):
                    value = calc(node)
                    value['nodes'][0]['id'] = old
                    with self.assertRaises(SchemaxisError) as caught:
                        host_plan(value)
                    self.assertEqual('INVALID_NAME', caught.exception.fault.code)
                    for new in ('fresh', old):
                        self.refuses(value, 'INVALID_IDENTITY', new, location='$/nodes/0/id')
                    before = copy.deepcopy(value)
                    for attempt in (lambda: proof(value, '/nodes/0/id', 'fresh'),
                                    lambda: replay(value, [(old, 'fresh')])):
                        with self.assertRaises(SchemaxisError) as caught:
                            attempt()
                        self.assertEqual('INVALID_IDENTITY', caught.exception.fault.code)
                    self.assertEqual(before, value)

    def test_admitted_name_rule_and_literal_schema_agree_with_the_planner(self):
        provider, route = registry.resolve(calc(SOURCES['fromRows']))
        name_schema = for_route(provider, route)['identities'][0]['nameSchema']
        for variant in registry.binding(route['schema'])()['properties']['nodes']['items']['oneOf']:
            self.assertEqual(name_schema['pattern'], variant['properties']['id']['pattern'])
        for name in CANDIDATES:
            with self.subTest(name=name):
                verdict = planner_fault(name)
                self.assertIn(verdict, (None, 'INVALID_NAME'))
                self.assertEqual(verdict is None, accepts_name(name, name_schema))

    @unittest.skipIf(shutil.which('node') is None, 'Node.js is unavailable for the Studio RegExp check')
    def test_studio_regexp_reads_the_literal_pattern_like_the_planner(self):
        provider, route = registry.resolve(calc(SOURCES['fromRows']))
        pattern = registry.binding(route['schema'])()['properties']['nodes']['items']['oneOf'][0]['properties']['id']['pattern']
        script = ("const data = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
                  "console.log(JSON.stringify(data.names.map((name) => ["
                  "new RegExp(data.pattern, 'u').test(name), new RegExp(data.pattern).test(name)])));")
        completed = subprocess.run(['node', '-e', script], input=json.dumps({'pattern': pattern, 'names': CANDIDATES}),
                                   capture_output=True, text=True, timeout=60)
        self.assertEqual(0, completed.returncode, completed.stderr)
        expected = [[planner_fault(name) is None] * 2 for name in CANDIDATES]
        self.assertEqual(expected, json.loads(completed.stdout))


class GraphPoliciesUnchanged(unittest.TestCase):
    def test_graph_routes_keep_the_literal_input_container_contract(self):
        provider, route = registry.resolve({'version': 'schemaxis/1', 'nodes': []})
        self.assertTrue(route['graph'])
        admitted = for_route(provider, route)
        self.assertEqual('inputs', admitted['identities'][0]['graph']['inputs'])
        self.assertNotIn('properties', admitted['projection']['node'])
        data = registry.binding(route['authoringReferences'])()
        schema = registry.binding(route['schema'])()
        declarations = registry.declarations(provider)
        spelled = copy.deepcopy(data)
        spelled['identities'][0]['graph']['inputs'] = None
        with self.assertRaises(SchemaxisError) as caught:
            validate(spelled, schema, declarations, graph_route=True)
        self.assertEqual('$policy.identities/0/graph', caught.exception.fault.location)
        self.assertEqual({}, declarations['sphere']['inputs'])
        for variant in schema['properties']['nodes']['items']['oneOf']:
            if variant['properties']['filter'].get('const') == 'sphere':
                del variant['properties']['inputs']
        with self.assertRaises(SchemaxisError) as caught:
            validate(data, schema, declarations)
        self.assertEqual('INVALID_REFERENCE_POLICY', caught.exception.fault.code)

    def test_blender_routes_remain_unpolicied(self):
        for version, route in registry.metadata('blender')['routes'].items():
            with self.subTest(version=version):
                self.assertNotIn('authoringReferences', route)


if __name__ == '__main__':
    unittest.main()
