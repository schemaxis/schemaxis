"""Host actions spatial_check, spatial_list, spatial_eval and spatial_load (specification appendix A)."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail
from schemaxis.filters import catalogue
from schemaxis.pipeline import DefinitionGraph
from schemaxis.spatial_actions import run, spatial_check, spatial_eval, spatial_list
from schemaxis.spatial_load import collect, spatial_load

BODY = [0, 4.5, -0.9, 0.9, 0.2, 1.4]
WHEELS = [0.5, 3.6, -1, 1, 0, 0.7]
SWEEP = 'sweep:/nodes/3/options/origin/$expr#0'


def expression(text):
    return {'$expr': text}


def car():
    """The fixture of specification section 13, with a reader and a swept slice."""
    return {'version': 'schemaxis/1', 'nodes': [
        {'id': 'bodySurface', 'filter': 'wavelet'},
        {'id': 'wheelSurface', 'filter': 'sphere'},
        {'id': 'reader', 'filter': 'foam', 'options': {'file': 'case.foam'}},
        {'id': 'cut', 'filter': 'slice', 'inputs': {'input': 'bodySurface'}, 'options': {
            'origin': expression('vector(car.mid.x, sweep(car.min.y, car.max.y, 5), car.max.z)')}}],
        'dimensions': {'wheelbase': 2.7}, 'settings': {'zoom': 0.52},
        'definitions': {'body': {'min': [0, -0.9, 0.2], 'max': [4.5, 0.9, 1.4]}, 'wheels': WHEELS,
                        'model': expression('union(body, wheels)'),
                        'car': expression('union(extents(bodySurface), extents(wheelSurface))'),
                        'probe': expression('lerp(model.min, model.max, t)'),
                        'label': expression("model.deltaX > model.deltaY ? 'x+' : 'y+'")},
        'sweeps': [{'name': 't', 'values': [0, 0.5, 1]}]}


def entry(key, section='definitions', scope='document'):
    return {'scope': scope, 'section': section, 'key': key}


def by_key(records):
    return {record['entry']['key']: record for record in records}


def loaded(digest, state=None, operation=None):
    result = {'inputDigest': digest, 'state': state or {'timeIndex': 0, 'indices': {}}, 'extents': [
        {'node': 'bodySurface', 'port': 0, 'status': 'ok', 'bounds': BODY},
        {'node': 'wheelSurface', 'port': 0, 'status': 'ok', 'bounds': WHEELS}]}
    if operation is not None:
        result['operation'] = operation
    return result


class Backend:
    """Host stand-in for an application: every node reports the extents named for it."""

    def __init__(self, extents, broken=()):
        self.reported = extents
        self.broken = broken

    def create(self, node, declaration, inputs, constructor):
        return {'node': node, 'values': dict(constructor)}

    def configure(self, handle, declaration, values):
        handle['values'].update(copy.deepcopy(values))

    def update(self, handle, time):
        if handle['node'] in self.broken:
            fail('READ_FAILED', 'the file cannot be read', handle['node'])

    def observe(self, handle):
        return {'points': 12}

    def extents(self, handle):
        return self.reported[handle['node']]

    def delete(self, handle):
        pass


class Loader:
    """Runs the native half of spatial_load on the host and keeps what it was given."""

    def __init__(self, backend):
        self.backend = backend
        self.calls = []

    def __call__(self, document, roots, state, locations, timeout, directory):
        self.calls.append({'document': document, 'roots': roots, 'state': state})
        return collect(DefinitionGraph(document, catalogue()), self.backend, roots, state)


class BlenderLoader(Loader):
    """The same, planned as the Blender adaptor plans its node graph."""

    def __call__(self, document, roots, state, locations, timeout, directory):
        from schemaxis.adaptors.blender.adaptor import graph_master
        self.calls.append({'document': document, 'roots': roots, 'state': state})
        return collect(graph_master(document), self.backend, roots, state)


class Unanswering:
    """A load whose application cannot be used at all."""

    def __init__(self, code):
        self.code, self.calls = code, 0

    def __call__(self, document, roots, state, locations, timeout, directory):
        self.calls += 1
        fail(self.code, 'the application gave no answer')


class Check(unittest.TestCase):
    def test_reports_type_phase_and_what_the_text_depends_on(self):
        result = spatial_check({'input': car(), 'expression': 'car.span', 'draft': {'identity': 'd', 'revision': 4}})
        self.assertEqual((result['ok'], result['type'], result['phase']), (True, 'scalar', 'observed'))
        self.assertEqual(result['dependsOn'], {
            'entries': [entry('car')], 'awaits': [], 'sweeps': [],
            'nodes': [{'node': 'bodySurface', 'port': 0}, {'node': 'wheelSurface', 'port': 0}]})
        self.assertEqual(result['draft'], {'identity': 'd', 'revision': 4})
        self.assertEqual(result['capabilities'], {'extents': True})
        self.assertEqual(len(result['inputDigest']), 64)

    def test_the_destination_decides_whether_a_late_value_is_accepted(self):
        request = {'input': car(), 'expression': 'car.span'}
        self.assertTrue(spatial_check({**request, 'destination': '/nodes/1/options/radius'})['ok'])
        refused = spatial_check({**request, 'destination': '/nodes/2/options/file'})
        self.assertEqual((refused['ok'], refused['type'], refused['phase']), (False, 'scalar', 'observed'))
        fault = refused['fault']
        self.assertEqual((fault['code'], fault['location']), ('DYNAMIC_CONSTRUCTOR', '$/nodes/2/options/file'))
        self.assertEqual((fault['observed']['variable'], fault['observed']['chain'], fault['observed']['phase']),
                         ('car', ['car', 'extents(bodySurface)'], 'observed'))
        self.assertIn('constructor option reader.file', fault['message'])
        self.assertIn('node `bodySurface`', fault['message'])

    def test_a_sweep_is_refused_in_a_scene_and_a_late_value_in_an_axis(self):
        request = {'input': car()}
        scene = spatial_check({**request, 'expression': 'sweep(0, 1, 3)',
                               'destination': '/scenes/0/images/0/cameras/0/distance'})
        self.assertEqual((scene['ok'], scene['fault']['code']), (False, 'SWEEP_PLACEMENT'))
        accepted = spatial_check({**request, 'expression': 't + extents(bodySurface).min.x',
                                  'destination': '/scenes/0/images/0/cameras/0/distance'})
        self.assertEqual((accepted['ok'], accepted['phase']), (True, 'observed'))
        axis = spatial_check({**request, 'expression': 'time * 2', 'destination': '/sweeps/0/values/1'})
        self.assertEqual((axis['fault']['code'], axis['fault']['observed']['chain']), ('EXPR_PHASE', ['time']))

    def test_the_destination_supplies_the_expected_type(self):
        request = {'input': car(), 'destination': '/nodes/3/options/origin'}
        self.assertTrue(spatial_check({**request, 'expression': 'model.mid'})['ok'])
        wrong = spatial_check({**request, 'expression': 'model.span'})
        self.assertEqual((wrong['fault']['code'], wrong['fault']['observed']['expected'],
                          wrong['fault']['observed']['actual']), ('EXPR_TYPE', ['vector'], 'scalar'))

    def test_a_text_that_does_not_parse_is_a_fault_with_its_position(self):
        result = spatial_check({'input': car(), 'expression': 'model.push(\'x+\', 2'})
        self.assertEqual((result['ok'], result['fault']['code'], result['fault']['observed']['position']),
                         (False, 'EXPR_SYNTAX', 18))
        self.assertNotIn('type', result)

    def test_sweeps_are_named_from_the_destination(self):
        result = spatial_check({'input': car(), 'expression': 'vector(sweep(0, 1, 2), sweep(0, 1, 2, \'s\'), 0)',
                                'destination': '/nodes/3/options/origin'})
        self.assertEqual(result['dependsOn']['sweeps'], ['sweep:/nodes/3/options/origin/$expr#0', 'sync:s'])
        count = spatial_check({'input': car(), 'expression': 'sweep(0, 1, t)'})
        self.assertEqual(count['fault']['code'], 'SWEEP_COUNT')


class Destinations(unittest.TestCase):
    def refused(self, draft, text, destination):
        checked = spatial_check({'input': draft, 'expression': text, 'destination': destination})
        self.assertFalse(checked['ok'], checked)
        return checked['fault']

    def test_the_fixed_keys_of_an_analytic_take_constants_only(self):
        draft = car()
        draft['nodes'][1]['options'] = {'radius': {'$analytic': {'type': 'linear', 'start': 1, 'end': 2, 'count': 3}}}
        inside = '/nodes/1/options/radius/$analytic/'
        fault = self.refused(draft, 'time + 2', inside + 'count')
        self.assertEqual((fault['code'], fault['observed']['chain']), ('EXPR_PHASE', ['time']))
        for key in ('start', 'end'):
            self.assertTrue(spatial_check({'input': draft, 'expression': 'time + 2', 'destination': inside + key})['ok'])
        self.assertTrue(spatial_check({'input': draft, 'expression': '1 + 2', 'destination': inside + 'count'})['ok'])
        draft['nodes'][1]['options']['radius']['$analytic']['type'] = 'orbit'
        self.assertEqual(self.refused(draft, 'time + 2', inside + 'start')['code'], 'EXPR_PHASE')

    def test_an_adaptor_without_a_graph_takes_only_what_a_study_can_compute(self):
        draft = {'version': 'schemaxis.gmsh/1', 'x': 1, 'sweeps': [{'name': 't', 'values': [0, 1]}]}
        fault = self.refused(draft, 'time + 2', '/x')
        self.assertEqual((fault['code'], fault['observed']['chain']), ('EXPR_PHASE', ['time']))
        self.assertTrue(spatial_check({'input': draft, 'expression': 't + 2', 'destination': '/x'})['ok'])
        self.assertTrue(spatial_check({'input': draft, 'expression': 'time + 2', 'destination': '/definitions/x'})['ok'])


class Listing(unittest.TestCase):
    def test_entries_are_listed_unevaluated_except_constants(self):
        result = spatial_list({'input': car()})
        records = by_key(result['entries'])
        self.assertEqual(list(records), ['wheelbase', 'zoom', 'body', 'wheels', 'model', 'car', 'probe'])
        self.assertEqual(records['wheels']['value'], {'min': [0.5, -1, 0], 'max': [3.6, 1, 0.7]})
        self.assertEqual((records['body']['source']['kind'], records['model']['source']['kind']),
                         ('literal', 'constant'))
        self.assertEqual((records['model']['state'], records['model']['valid'], records['model']['expression']),
                         ('resolved', True, 'union(body, wheels)'))
        self.assertEqual((records['probe']['phase'], records['probe']['state'], records['probe']['reason']),
                         ('visit', 'unresolved', 'needs-state'))
        self.assertEqual((records['car']['phase'], records['car']['state'], records['car']['reason']),
                         ('observed', 'unresolved', 'needs-data'))
        self.assertNotIn('value', records['car'])
        self.assertNotIn('expression', records['body'])
        self.assertEqual(records['model']['source']['inputDigest'], result['inputDigest'])

    def test_axes_are_listed_fastest_first_with_the_number_of_visits(self):
        result = spatial_list({'input': car()})
        self.assertEqual(result['sweeps'], [{'id': 't', 'kind': 'declared', 'count': 3},
                                          {'id': SWEEP, 'kind': 'sweep', 'count': 5}])
        self.assertEqual(result['states'], 5)

    def test_member_analytics_are_named_as_a_plan_names_them(self):
        draft = car()
        draft['nodes'][1]['options'] = {'radius': {'$analytic': {'type': 'linear', 'start': 1, 'end': 2, 'count': 4}}}
        draft['nodes'][0]['options'] = {'wholeExtent': {'$analytic': {
            'type': 'linear', 'start': expression('vector(t, 0, 0)'), 'end': [1, 1, 1], 'count': 2}}}
        result = spatial_list({'input': draft})
        self.assertEqual([(axis['id'], axis['kind'], axis['count']) for axis in result['sweeps']], [
            ('t', 'declared', 3), ('sweep:/nodes/0/options/wholeExtent/$analytic#0', 'analytic', 2),
            ('analytic0', 'analytic', 4), (SWEEP, 'sweep', 5)])

    def test_functions_are_listed_for_completion(self):
        functions = {item['name']: item for item in spatial_list({'input': car()})['functions']}
        self.assertEqual((functions['union']['kind'], functions['fitCamera']['kind']), ('builtin', 'catalogue'))
        self.assertIn('bounds', functions['fitCamera']['parameters'])
        self.assertEqual(functions['sweep']['parameters'][1], ['value', 'value', 'count', 'sync'])
        self.assertEqual(functions['extents']['result'], ['box'])

    def test_a_broken_part_of_a_draft_does_not_fail_the_listing(self):
        draft = car()
        draft['definitions']['broken'] = expression('model.mid +')
        draft['nodes'].append({'id': 'unfinished'})
        draft['scenes'] = 'not written yet'
        records = by_key(spatial_list({'input': draft})['entries'])
        self.assertEqual(records['model']['state'], 'resolved')
        self.assertEqual((records['broken']['state'], records['broken']['fault']['code'],
                          records['broken']['fault']['location']), ('fault', 'EXPR_SYNTAX', '$/definitions/broken'))

    def test_an_entry_that_refers_to_another_has_its_type_and_value(self):
        draft = car()
        draft['definitions'].update(alias={'$document': '/definitions/model'},
                                    seen={'$document': '/definitions/car'},
                                    deep={'$document': '/definitions/body/min'})
        records = by_key(spatial_list({'input': draft})['entries'])
        self.assertEqual((records['alias']['type'], records['alias']['value'], records['alias']['source']['kind']),
                         ('box', {'min': [0, -1, 0], 'max': [4.5, 1, 1.4]}, 'constant'))
        self.assertEqual((records['seen']['phase'], records['seen']['dependsOn']['entries'][0]),
                         ('observed', entry('car')))
        self.assertNotIn('deep', records)
        workflow = {'version': 'schemaxis.workflow/1', 'settings': {'gap': 7}, 'operations': [
            {'id': 'one', 'document': {'version': 'schemaxis/1', 'definitions': {
                'gap': {'$document': '/settings/gap', 'scope': 'workflow'}}}}]}
        record = spatial_eval({'input': workflow, 'operation': 'one'})['records'][0]
        self.assertEqual((record['value'], record['dependsOn']['entries']), (7, [entry('gap', 'settings', 'workflow')]))

    def test_an_adaptor_without_the_capability_reports_it(self):
        document = {'version': 'schemaxis.gmsh/1', 'definitions': {'size': expression('2 * 3'),
                                                                 'seen': expression('dataExtents.span')}}
        result = spatial_list({'input': document})
        records = by_key(result['entries'])
        self.assertEqual(result['capabilities'], {'extents': False})
        self.assertEqual((records['size']['value'], records['seen']['fault']['code']), (6, 'EXTENTS_UNSUPPORTED'))


class Evaluation(unittest.TestCase):
    def test_visit_entries_resolve_for_the_given_state(self):
        result = spatial_eval({'input': car(), 'state': {'timeIndex': 0, 'indices': {'t': 2}},
                               'entries': [entry('probe')]})
        record = result['records'][0]
        self.assertEqual((record['state'], record['value']), ('resolved', [4.5, 1, 1.4]))
        self.assertEqual(record['source'], {'kind': 'constant', 'inputDigest': result['inputDigest'],
                                            'state': {'timeIndex': 0, 'indices': {'t': 2}}})
        first = spatial_eval({'input': car(), 'entries': [entry('probe')]})['records'][0]
        self.assertEqual(first['value'], [0, -1, 0])

    def test_observed_entries_resolve_only_from_matching_observations(self):
        draft = car()
        digest = spatial_list({'input': draft})['inputDigest']
        request = {'input': draft, 'entries': [entry('car')]}
        self.assertEqual(spatial_eval(request)['records'][0]['reason'], 'needs-data')
        fresh = spatial_eval({**request, 'observations': loaded(digest)})['records'][0]
        self.assertEqual((fresh['state'], fresh['value'], fresh['valid'], fresh['source']['kind']),
                         ('resolved', {'min': [0, -1, 0], 'max': [4.5, 1, 1.4]}, True, 'live'))
        edited = copy.deepcopy(draft)
        edited['settings']['zoom'] = 0.6
        for stale in ({'input': edited, 'entries': [entry('car')], 'observations': loaded(digest)},
                      {**request, 'state': {'timeIndex': 0, 'indices': {'t': 1}}, 'observations': loaded(digest)},
                      {**request, 'observations': loaded(digest, operation='render')}):
            record = spatial_eval(stale)['records'][0]
            self.assertEqual((record['state'], record['reason']), ('unresolved', 'stale-data'))
            self.assertNotIn('value', record)

    def test_empty_not_spatial_and_failed_outputs(self):
        draft = car()
        draft['definitions'].update(empty=expression('extents(wheelSurface)'),
                                    table=expression('extents(wheelSurface, 1)'),
                                    lost=expression('extents(bodySurface).mid'))
        observations = {'inputDigest': spatial_list({'input': draft})['inputDigest'],
                        'state': {'timeIndex': 0, 'indices': {}}, 'extents': [
            {'node': 'bodySurface', 'port': 0, 'status': 'fault',
             'fault': {'code': 'READ_FAILED', 'message': 'the file cannot be read'}},
            {'node': 'wheelSurface', 'port': 0, 'status': 'empty'},
            {'node': 'wheelSurface', 'port': 1, 'status': 'notSpatial'}]}
        records = by_key(spatial_eval({'input': draft, 'observations': observations})['records'])
        self.assertEqual((records['empty']['value'], records['empty']['valid']),
                         ({'min': [1, 1, 1], 'max': [-1, -1, -1]}, False))
        self.assertEqual(records['table']['fault']['code'], 'EXTENTS_UNAVAILABLE')
        self.assertEqual((records['lost']['state'], records['lost']['fault']['code']), ('fault', 'READ_FAILED'))

    def test_an_expression_is_evaluated_without_being_an_entry(self):
        result = spatial_eval({'input': car(), 'expression': 'model.inflate(zoom).size'})
        record = result['records'][0]
        self.assertNotIn('entry', record)
        self.assertEqual((record['type'], record['phase'], record['state']), ('vector', 'constant', 'resolved'))
        for actual, expected in zip(record['value'], [6.84, 3.04, 2.128]):
            self.assertAlmostEqual(actual, expected, places=12)
        faulted = spatial_eval({'input': car(), 'expression': 'intersect(body, box()).mid'})['records'][0]
        self.assertEqual((faulted['state'], faulted['fault']['code']), ('fault', 'EXPR_INVALID_BOX'))

    def test_a_named_entry_of_another_type_is_still_evaluated(self):
        record = spatial_eval({'input': car(), 'entries': [entry('label')]})['records'][0]
        self.assertEqual((record['type'], record['value']), ('string', 'x+'))
        missing = spatial_eval({'input': car(), 'entries': [entry('nothing')]})['records'][0]
        self.assertEqual((missing['state'], missing['fault']['code']), ('fault', 'UNKNOWN_ENTRY'))

    def test_an_entry_waiting_for_another_operation_is_not_resolved(self):
        workflow = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'measure', 'document': car()},
            {'id': 'render', 'document': {'version': 'schemaxis/1', 'definitions': {
                'upstream': {'$value': 'measure', 'path': '/spatial/entries/definitions/model/values/0'},
                'framed': expression('box(upstream).inflate(0.1)')}}}]}
        record = by_key(spatial_eval({'input': workflow, 'operation': 'render'})['records'])['framed']
        self.assertEqual((record['phase'], record['state'], record['reason'], record['dependsOn']['awaits']),
                         ('constant', 'unresolved', 'awaits-producer', ['measure']))


class PlannedAxes(unittest.TestCase):
    def test_constant_expressions_in_axes_and_times_are_read_as_a_plan_reads_them(self):
        for axis in ({'name': 't', 'values': [expression('2'), 3]},
                     {'name': 't', 'series': {'start': expression('2'), 'end': 3, 'count': 2}}):
            draft = {'version': 'schemaxis/1', 'nodes': [{'id': 'ball', 'filter': 'sphere',
                                                           'options': {'radius': expression('v')}}],
                     'definitions': {'v': expression('t + 1')}, 'sweeps': [axis]}
            with self.subTest(axis=axis):
                self.assertEqual(DefinitionGraph(draft, catalogue()).select(['ball']).count, 2)
                first = spatial_eval({'input': draft})['records'][0]
                second = spatial_eval({'input': draft, 'state': {'indices': {'t': 1}}})['records'][0]
                self.assertEqual((first['state'], first['value'], second['value']), ('resolved', 3, 4))
        draft = {'version': 'schemaxis/1', 'nodes': [{'id': 'ball', 'filter': 'sphere'}],
                 'definitions': {'v': expression('time + 1')}, 'times': [expression('2')]}
        record = spatial_eval({'input': draft})['records'][0]
        self.assertEqual((record['state'], record['value']), ('resolved', 3))


class Workflows(unittest.TestCase):
    def test_an_ad_hoc_record_of_a_workflow_names_its_operation(self):
        workflow = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'render', 'document': car()}]}
        record = spatial_eval({'input': workflow, 'operation': 'render', 'expression': '1 + 2'})['records'][0]
        self.assertEqual((record['operation'], record['value']), ('render', 3))
        self.assertNotIn('operation', spatial_eval({'input': car(), 'expression': '1 + 2'})['records'][0])

    def workflow(self):
        return {'version': 'schemaxis.workflow/1', 'settings': {'gap': 7}, 'definitions': {
            'room': {'min': [0, 0, 0], 'max': [1, 1, 1]}}, 'operations': [
            {'id': 'one', 'document': {'version': 'schemaxis/1', 'settings': {'gap': 2},
                                       'definitions': {'wide': expression('workflow.settings.gap + gap')},
                                       'sweeps': [{'name': 't', 'values': [0, 1]}]}},
            {'id': 'two', 'document': {'version': 'schemaxis/1', 'definitions': {
                'late': expression('workflow.definitions.room.inflate(t)')}, 'sweeps': [{'name': 't', 'values': [1, 2]}]}}]}

    def test_an_operation_is_its_own_namespace_and_reaches_the_envelope(self):
        result = spatial_eval({'input': self.workflow(), 'operation': 'one'})
        records = by_key(result['records'])
        self.assertEqual((records['wide']['value'], records['wide']['operation'], records['gap']['value']),
                         (9, 'one', 2))
        self.assertEqual(records['wide']['dependsOn']['entries'],
                         [entry('gap', 'settings'), entry('gap', 'settings', 'workflow')])
        late = spatial_eval({'input': self.workflow(), 'operation': 'two',
                             'state': {'indices': {'t': 1}}, 'entries': [entry('late')]})['records'][0]
        self.assertEqual(late['value'], {'min': [-1, -1, -1], 'max': [2, 2, 2]})
        envelope = spatial_eval({'input': self.workflow(), 'operation': 'two',
                                 'entries': [entry('room', scope='workflow')]})['records'][0]
        self.assertEqual((envelope['entry']['scope'], envelope['valid']), ('workflow', True))

    def test_without_an_operation_every_operation_and_the_envelope_are_listed(self):
        result = spatial_list({'input': self.workflow()})
        found = [(record.get('operation'), record['entry']['scope'], record['entry']['key'])
                 for record in result['entries']]
        self.assertEqual(found, [(None, 'workflow', 'gap'), (None, 'workflow', 'room'), ('one', 'document', 'gap'),
                                 ('one', 'document', 'wide'), ('two', 'document', 'late')])
        self.assertEqual([axis.get('operation') for axis in result['sweeps']], ['one', 'two'])
        with self.assertRaises(SchemaxisError) as caught:
            spatial_list({'input': self.workflow(), 'operation': 'three'})
        self.assertEqual(caught.exception.fault.code, 'UNKNOWN_OPERATION')


class Loading(unittest.TestCase):
    def test_direct_data_extents_load_needs_no_saved_expression(self):
        draft = car()
        del draft['definitions']
        draft['nodes'].append({'id': 'unfinished', 'filter': 'choose later'})
        draft['scenes'] = 'unfinished'
        loader = Loader(Backend({'reader': [{'status': 'ok', 'bounds': BODY}]}))
        result = spatial_load({'input': draft, 'expression': 'dataExtents'}, load=loader)
        self.assertEqual(loader.calls[0]['roots'], ['reader'])
        self.assertEqual([n['id'] for n in loader.calls[0]['document']['nodes']], ['reader'])
        self.assertEqual(result['records'][0]['value'], {'min': [0, -0.9, 0.2], 'max': [4.5, 0.9, 1.4]})
        self.assertEqual(result['records'], spatial_eval({'input': draft, 'expression': 'dataExtents',
                          'observations': result['observations']})['records'])
        self.assertNotIn('definitions', draft)

    def test_direct_node_recipe_loads_only_its_dependency(self):
        loader = self.backend()
        result_loader = Loader(loader)
        result = spatial_load({'input': self.draft(), 'expression': 'translate(extents(wheelSurface), vector(1,2,3))'}, load=result_loader)
        self.assertEqual(result_loader.calls[0]['roots'], ['wheelSurface'])
        self.assertEqual(result['records'][0]['value'], {'min': [1.5, 1, 3], 'max': [4.6, 3, 3.7]})

    def test_bad_and_constant_ad_hoc_expressions_start_no_native_loader(self):
        loader = Loader(Backend({}))
        for text, state in [('data.extents', 'fault'), ('box(0,1,0,1,0,1)', 'resolved')]:
            result = spatial_load({'input': self.draft(), 'expression': text}, load=loader)
            self.assertEqual(result['records'][0]['state'], state)
        self.assertEqual(loader.calls, [])

    def test_direct_load_keeps_workflow_operation_provenance(self):
        root = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'car', 'document': car()}]}
        loader = Loader(Backend({'reader': [{'status': 'ok', 'bounds': BODY}]}))
        result = spatial_load({'input': root, 'operation': 'car', 'expression': 'dataExtents'}, load=loader)
        self.assertEqual(result['records'][0]['operation'], 'car')
        self.assertEqual(result['observations']['operation'], 'car')

    def draft(self):
        draft = car()
        draft['nodes'].extend([
            {'id': 'unfinished', 'filter': 'not chosen yet', 'options': {'value': expression('1 +')}},
            {'id': 'damaged', 'filter': 'wavelet'},
            {'id': 'beyond', 'filter': 'slice', 'inputs': {'input': 'damaged'}}])
        draft['definitions'].update(lost=expression('extents(beyond).mid'), junk=expression('1 +'))
        draft['scenes'] = 'not written yet'
        return draft

    def backend(self):
        return Backend({'bodySurface': [{'status': 'ok', 'bounds': BODY}],
                        'wheelSurface': [{'status': 'ok', 'bounds': WHEELS}, {'status': 'notSpatial'}]},
                       broken=('damaged',))

    def test_only_what_the_entries_read_is_planned_and_run(self):
        loader = Loader(self.backend())
        result = spatial_load({'input': self.draft(), 'draft': 7}, load=loader)
        call = loader.calls[0]
        self.assertEqual([node['id'] for node in call['document']['nodes']],
                         ['bodySurface', 'wheelSurface', 'damaged', 'beyond'])
        self.assertEqual(call['roots'], ['bodySurface', 'wheelSurface', 'beyond'])
        self.assertNotIn('scenes', call['document'])
        self.assertNotIn('definitions', call['document'])
        self.assertEqual(result['draft'], 7)
        observations = result['observations']
        self.assertEqual((observations['inputDigest'], observations['state']),
                         (result['inputDigest'], {'timeIndex': 0, 'indices': {}}))
        self.assertNotIn('operation', observations)

    def test_a_node_that_fails_faults_only_what_reads_it(self):
        result = spatial_load({'input': self.draft()}, load=Loader(self.backend()))
        extents = {(item['node'], item['port']): item for item in result['observations']['extents']}
        self.assertEqual(extents[('bodySurface', 0)], {'node': 'bodySurface', 'port': 0, 'status': 'ok',
                                                     'bounds': BODY})
        self.assertEqual(extents[('wheelSurface', 1)]['status'], 'notSpatial')
        self.assertEqual((extents[('beyond', 0)]['status'], extents[('beyond', 0)]['fault']['code']),
                         ('fault', 'READ_FAILED'))
        records = by_key(result['records'])
        self.assertEqual((records['car']['state'], records['car']['value']),
                         ('resolved', {'min': [0, -1, 0], 'max': [4.5, 1, 1.4]}))
        self.assertEqual((records['lost']['state'], records['lost']['fault']['code']), ('fault', 'READ_FAILED'))
        self.assertEqual(records['junk']['fault']['code'], 'EXPR_SYNTAX')
        again = spatial_eval({'input': self.draft(), 'observations': result['observations']})
        self.assertEqual(again['records'], result['records'])

    def test_a_node_that_cannot_be_planned_faults_only_what_reads_it(self):
        draft = self.draft()
        draft['nodes'].append({'id': 'misset', 'filter': 'sphere', 'options': {'radius': 'wide'}})
        draft['definitions']['odd'] = expression('extents(misset).span')
        loader = Loader(self.backend())
        result = spatial_load({'input': draft}, load=loader)
        self.assertEqual([call['roots'] for call in loader.calls],
                         [['bodySurface', 'wheelSurface', 'beyond', 'misset'], ['bodySurface'], ['wheelSurface'],
                          ['beyond'], ['misset']])
        records = by_key(result['records'])
        failed = next(item for item in result['observations']['extents'] if item['node'] == 'misset')
        self.assertEqual((failed['status'], failed['fault']['location']), ('fault', 'misset.radius'))
        self.assertEqual((records['car']['state'], records['odd']['state'], records['odd']['fault']['code']),
                         ('resolved', 'fault', failed['fault']['code']))
        only = {'version': 'schemaxis/1', 'nodes': draft['nodes'][-1:], 'definitions': {'odd': draft['definitions']['odd']}}
        alone = spatial_load({'input': only}, load=loader)
        self.assertEqual([(item['node'], item['status'], item['fault']['location'])
                          for item in alone['observations']['extents']], [('misset', 'fault', 'misset.radius')])
        self.assertEqual((alone['records'][0]['state'], alone['records'][0]['fault']['code']),
                         ('fault', failed['fault']['code']))

    def test_nodes_that_all_fail_are_fault_records_and_the_action_still_answers(self):
        draft = {'version': 'schemaxis/1', 'nodes': [
            {'id': 'first', 'filter': 'sphere', 'options': {'radius': 'wide'}},
            {'id': 'second', 'filter': 'sphere', 'options': {'radius': 'narrow'}}],
            'definitions': {'a': expression('extents(first)'), 'b': expression('extents(second)')}}
        result = spatial_load({'input': draft}, load=Loader(Backend({})))
        self.assertEqual([(item['node'], item['status'], item['fault']['location'])
                          for item in result['observations']['extents']],
                         [('first', 'fault', 'first.radius'), ('second', 'fault', 'second.radius')])
        self.assertEqual({record['state'] for record in result['records']}, {'fault'})

    def test_data_extents_of_a_document_without_readers_is_the_invalid_box(self):
        draft = {'version': 'schemaxis/1', 'nodes': [{'id': 'ball', 'filter': 'sphere'}],
                 'definitions': {'model': expression('dataExtents'), 'ball': expression('extents(ball)')}}
        loader = Loader(Backend({}))
        result = spatial_load({'input': draft, 'entries': [entry('model')]}, load=loader)
        self.assertEqual((loader.calls, result['observations']['extents']), ([], []))
        record = result['records'][0]
        self.assertEqual((record['state'], record['valid'], record['value']),
                         ('resolved', False, {'min': [1, 1, 1], 'max': [-1, -1, -1]}))
        again = by_key(spatial_eval({'input': draft, 'observations': result['observations']})['records'])
        self.assertEqual((again['model']['state'], again['ball']['state'], again['ball']['reason']),
                         ('resolved', 'unresolved', 'needs-data'))
        self.assertEqual(by_key(spatial_eval({'input': draft})['records'])['model']['reason'], 'needs-data')

    def test_a_cancelled_job_stops_the_load_before_the_application_starts(self):
        import sys
        import threading
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        from schemaxis import spatial_load as module
        from schemaxis.dispatch import allocation
        draft = {'version': 'schemaxis/1', 'nodes': [{'id': 'ball', 'filter': 'sphere'}]}
        setup = MagicMock(return_value=(DefinitionGraph(draft, catalogue()),
                                        SimpleNamespace(executable=sys.executable, kind='paraview'), ()))
        cancelled = threading.Event()
        cancelled.set()
        with patch('schemaxis.adaptors.registry.binding', return_value=setup), allocation({}, cancelled), \
                tempfile.TemporaryDirectory() as root, self.assertRaises(SchemaxisError) as caught:
            module.native_extents(draft, ['ball'], {'timeIndex': 0, 'indices': {}}, {}, 30, Path(root) / 'load')
        self.assertEqual(caught.exception.fault.code, 'RUNNER_CANCELLED')

    def test_entries_and_state_select_what_is_loaded(self):
        draft = self.draft()
        draft['definitions']['swept'] = expression('extents(cut).min')
        loader = Loader(Backend({'bodySurface': [{'status': 'ok', 'bounds': BODY}],
                                 'wheelSurface': [{'status': 'ok', 'bounds': WHEELS}],
                                 'cut': [{'status': 'empty'}]}))
        result = spatial_load({'input': draft, 'entries': [entry('swept')], 'state': {'indices': {SWEEP: 4}}},
                              load=loader)
        call = loader.calls[0]
        self.assertEqual((call['roots'], [node['id'] for node in call['document']['nodes']]),
                         (['cut'], ['bodySurface', 'wheelSurface', 'cut']))
        self.assertEqual(call['state']['indices'], {'sweep:/nodes/2/options/origin/$expr#0': 4})
        self.assertEqual(sorted(call['document']['definitions']), ['car'])
        record = result['records'][0]
        self.assertEqual((record['state'], record['fault']['code']), ('fault', 'EXPR_INVALID_BOX'))
        self.assertEqual(result['observations']['state'], {'timeIndex': 0, 'indices': {SWEEP: 4}})

    def test_an_operation_is_loaded_with_the_envelope_entries_it_reads(self):
        operation = {'version': 'schemaxis/1', 'nodes': [
            {'id': 'ball', 'filter': 'sphere', 'options': {'radius': expression('workflow.settings.gap + t')}}],
            'sweeps': [{'name': 't', 'values': [0, 1]}], 'definitions': {'seen': expression('extents(ball)')}}
        workflow = {'version': 'schemaxis.workflow/1', 'settings': {'gap': 7, 'other': expression('1 +')},
                    'operations': [{'id': 'render', 'document': operation}]}
        loader = Loader(Backend({'ball': [{'status': 'ok', 'bounds': BODY}]}))
        result = spatial_load({'input': workflow, 'operation': 'render', 'state': {'indices': {'t': 1}}},
                              load=loader)
        call = loader.calls[0]
        self.assertEqual(call['document']['%%workflowScope%%'], {'settings': {'gap': 7}})
        self.assertEqual(call['state'], {'timeIndex': 0, 'indices': {'t': 1}})
        self.assertEqual((result['observations']['operation'], result['records'][0]['operation'],
                          result['records'][0]['valid']), ('render', 'render', True))
        with self.assertRaises(SchemaxisError) as caught:
            spatial_load({'input': workflow}, load=loader)
        self.assertEqual(caught.exception.fault.code, 'EXTENTS_UNSUPPORTED')

    def test_a_typed_or_inline_input_is_loaded_with_the_node_that_takes_it(self):
        draft = {'version': 'schemaxis.blender/1', 'nodes': [
            {'id': 'paint', 'filter': 'material'},
            {'id': 'box', 'filter': 'cube', 'inputs': {'material': {'$object': 'paint'}}},
            {'id': 'crate', 'filter': 'cube',
             'inputs': {'material': {'$create': {'id': 'gloss', 'filter': 'material'}}}},
            {'id': 'spare', 'filter': 'cube', 'inputs': {'material': 'paint'}}],
            'definitions': {'held': expression('union(extents(box), extents(crate))')}}
        resource = [{'status': 'notSpatial'}]
        loader = BlenderLoader(Backend({'paint': resource, 'gloss': resource,
                                        'box': [{'status': 'ok', 'bounds': BODY}],
                                        'crate': [{'status': 'ok', 'bounds': WHEELS}]}))
        result = spatial_load({'input': draft}, load=loader)
        call = loader.calls[0]
        self.assertEqual(([node['id'] for node in call['document']['nodes']], call['roots'], len(loader.calls)),
                         (['paint', 'box', 'crate', 'gloss'], ['box', 'crate'], 1))
        self.assertEqual([node.get('inputs') for node in call['document']['nodes']],
                         [None, {'material': 'paint'}, {'material': 'gloss'}, None])
        held = by_key(result['records'])['held']
        self.assertEqual((held['state'], held['value']), ('resolved', {'min': [0, -1, 0], 'max': [4.5, 1, 1.4]}))

    def test_a_fault_of_the_application_itself_is_not_retried_node_by_node(self):
        for code in ('RUNNER_TIMED_OUT', 'UNSUPPORTED_RUNTIME', 'INTERPRETER_NOT_FOUND', 'INTERPRETER_UNUSABLE',
                     'RUNNER_CANCELLED'):
            loader = Unanswering(code)
            with self.subTest(code=code), self.assertRaises(SchemaxisError) as caught:
                spatial_load({'input': car()}, load=loader)
            self.assertEqual((caught.exception.fault.code, loader.calls), (code, 1))

    def test_without_the_capability_nothing_is_started(self):
        loader = Loader(self.backend())
        with self.assertRaises(SchemaxisError) as caught:
            spatial_load({'input': {'version': 'schemaxis.gmsh/1', 'definitions': {'size': 1}}}, load=loader)
        self.assertEqual((caught.exception.fault.code, loader.calls), ('EXTENTS_UNSUPPORTED', []))


class Frontends(unittest.TestCase):
    def test_the_actions_are_dispatched_by_name(self):
        self.assertEqual(run('spatial_check', {'input': car(), 'expression': '1 + 1'})['type'], 'scalar')
        with self.assertRaises(SchemaxisError) as caught:
            run('spatial_guess', {'input': car()})
        self.assertEqual(caught.exception.fault.code, 'UNKNOWN_ACTION')
        with self.assertRaises(SchemaxisError) as caught:
            run('spatial_list', {'input': 'text'})
        self.assertEqual(caught.exception.fault.code, 'INVALID_REQUEST')

    def command(self, *arguments):
        from schemaxis.__main__ import authored_input, build_parser
        from schemaxis.spatial_actions import command
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'car.json'
            path.write_text(json.dumps(car()))
            args = build_parser().parse_args(['spatial', arguments[0], str(path), *arguments[1:]])
            return command(args, authored_input(args.input, args.input_format))

    def test_the_command_line_lists_evaluates_and_explains(self):
        listed = self.command('list')
        self.assertNotIn('functions', listed)
        self.assertEqual(by_key(listed['entries'])['model']['state'], 'resolved')
        evaluated = self.command('eval', '--entry', 'definitions.probe', '--index', 't=1')
        self.assertEqual(evaluated['records'][0]['value'], [2.25, 0, 0.7])
        adhoc = self.command('eval', '--expression', 'car.span', '--destination', '/nodes/2/options/file')
        self.assertEqual(adhoc['records'][0]['fault']['code'], 'DYNAMIC_CONSTRUCTOR')
        explained = by_key(self.command('explain')['entries'])
        self.assertEqual(explained['car']['chains'], [['extents(bodySurface)'], ['extents(wheelSurface)']])
        self.assertEqual(explained['probe']['chains'], [['t']])
        self.assertEqual(explained['model']['chains'], [])

    def test_the_agent_service_offers_the_same_actions(self):
        from schemaxis.execution_service import ExecutionService
        from schemaxis.service_contracts import ToolCatalogue
        with tempfile.TemporaryDirectory() as root, ExecutionService(Path(root) / 'workspace') as service:
            result = service.spatial('spatial_eval', car(), entries=[entry('model')], draft={'revision': 2})
            self.assertEqual((result['records'][0]['valid'], result['draft']), (True, {'revision': 2}))
            specification = ToolCatalogue(service).specs['spatial']
            self.assertEqual((specification.effect, specification.input_schema['required']),
                             ('read', ['action', 'input']))
            self.assertEqual(specification.input_schema['properties']['entries']['type'], ['array', 'null'])

    def test_strict_mcp_admits_the_host_actions_and_refuses_to_start_an_application(self):
        from schemaxis import mcp
        self.assertIn('spatial', mcp.STRICT_METHODS)

        class Admission:
            checked = []

            def check(self, document):
                self.checked.append(document)

        dispatcher = mcp.McpDispatcher.__new__(mcp.McpDispatcher)
        dispatcher.profile, dispatcher.admission = 'declared-documents', Admission()
        dispatcher._admit('spatial', {'action': 'spatial_list', 'input': {'version': 'schemaxis/1'}})
        self.assertEqual(Admission.checked, [{'version': 'schemaxis/1'}])
        with self.assertRaises(SchemaxisError) as caught:
            dispatcher._admit('spatial', {'action': 'spatial_load', 'input': {'version': 'schemaxis/1'}})
        self.assertEqual(caught.exception.fault.code, 'MCP_POLICY_DENIED')



class CarExample(unittest.TestCase):
    """The worked car example reads its model from loaded data and derives every other box and position from it."""

    SEEDS = 'sweep:/definitions/seedY/$expr#0'

    def draft(self):
        return json.loads((Path(__file__).parents[2] / 'examples' / 'paraview-car' / 'input.json').read_text())

    def observed(self, digest, position):
        return {'inputDigest': digest, 'state': {'timeIndex': 0, 'indices': {self.SEEDS: position}}, 'extents': [
            {'node': 'body', 'port': 0, 'status': 'ok', 'bounds': BODY},
            {'node': 'wheels', 'port': 0, 'status': 'ok', 'bounds': WHEELS}]}

    def test_every_derived_entry_waits_for_the_body_and_the_wheels(self):
        listed = spatial_list({'input': self.draft()})
        records = by_key(listed['entries'])
        self.assertEqual({key: (records[key]['type'], records[key]['phase']) for key in ('model', 'wake', 'seedX', 'seedY')},
                         {'model': ('box', 'observed'), 'wake': ('box', 'observed'),
                          'seedX': ('scalar', 'observed'), 'seedY': ('scalar', 'observed')})
        for key in ('model', 'wake', 'seedX', 'seedY'):
            self.assertEqual(records[key]['dependsOn']['nodes'], [{'node': 'body', 'port': 0}, {'node': 'wheels', 'port': 0}])
            self.assertEqual((records[key]['state'], records[key]['reason']), ('unresolved', 'needs-data'))
        self.assertEqual(records['seedY']['dependsOn']['sweeps'], [self.SEEDS])

    def test_the_model_the_wake_and_the_seed_line_follow_the_loaded_extents(self):
        draft = self.draft()
        digest = spatial_list({'input': draft})['inputDigest']
        found = []
        for position in range(5):
            request = {'input': draft, 'state': {'timeIndex': 0, 'indices': {self.SEEDS: position}},
                       'observations': self.observed(digest, position)}
            records = by_key(spatial_eval(request)['records'])
            self.assertEqual(records['model']['value'], {'min': [0, -1, 0], 'max': [4.5, 1, 1.4]})
            wake = records['wake']['value']
            for found_corner, expected in ((wake['min'], [-1.125, -2, 0]), (wake['max'], [15.75, 2, 2.1])):
                for value, wanted in zip(found_corner, expected):
                    self.assertAlmostEqual(value, wanted, places=12)
            self.assertAlmostEqual(records['seedX']['value'], -0.45, places=12)
            found.append(records['seedY']['value'])
        self.assertEqual(found, [-1, -0.5, 0, 0.5, 1])
        camera = spatial_eval({'input': draft, 'observations': self.observed(digest, 0),
                               'state': {'timeIndex': 0, 'indices': {self.SEEDS: 0}},
                               'expression': draft['scenes'][0]['images'][0]['cameras'][0]['$expr'],
                               'destination': '/scenes/0/images/0/cameras/0'})['records'][0]
        self.assertEqual((camera['state'], camera['value']['focalPoint']), ('resolved', [2.25, 0, 0.7]))


if __name__ == '__main__':
    unittest.main()
