"""Spatial entries in receipts: recorded with their inputs, replayed without the application, read by other operations."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from schemaxis import spatial_results
from schemaxis.core.faults import SchemaxisError
from schemaxis.filters import catalogue
from schemaxis.pipeline import DefinitionGraph, RuntimeClosure

BODY = [0, 4.5, -0.9, 0.9, 0.2, 1.4]
WHEELS = [0.5, 3.6, -1, 1, 0, 0.7]


def expression(text):
    return {'$expr': text}


class Backend:
    """Host stand-in for an application whose nodes report fixed extents, points and samples."""

    def __init__(self):
        self.extents_of = {'body': [{'status': 'ok', 'bounds': BODY}],
                           'wheels': [{'status': 'ok', 'bounds': WHEELS}, {'status': 'empty'}],
                           'table': [{'status': 'notSpatial'}]}

    def create(self, node, declaration, inputs, constructor):
        return {'node': node, 'values': dict(constructor)}

    def configure(self, handle, declaration, values):
        handle['values'].update(copy.deepcopy(values))

    def update(self, handle, time):
        pass

    def observe(self, handle):
        return {'points': 12, 'bounds': BODY}

    def extents(self, handle):
        return self.extents_of.get(handle['node'], [{'status': 'ok', 'bounds': BODY}])

    def sample(self, handle, association, field, index, component, block):
        return 10.0 + index

    def delete(self, handle):
        pass


def document(**definitions):
    return {'version': 'schemaxis/1', 'nodes': [
        {'id': 'body', 'filter': 'wavelet'}, {'id': 'wheels', 'filter': 'wavelet'},
        {'id': 'table', 'filter': 'wavelet'}, {'id': 'aside', 'filter': 'wavelet'},
        {'id': 'cut', 'filter': 'slice', 'inputs': {'input': 'body'},
         'options': {'origin': expression('lerp(car.min, car.max, t)')}}],
        'settings': {'model': {'min': [0, 0, 0], 'max': [1, 1, 1]}},
        'definitions': {'model': expression('union(extents(body), extents(wheels))'),
                        'car': expression('definitions.model.inflate(0.5)'),
                        'probe': expression('lerp(settings.model.min, settings.model.max, t)'),
                        'fixed': expression('settings.model.span * 2'), **definitions},
        'sweeps': [{'name': 't', 'values': [0, 1]}]}


def run(value, roots=('cut', 'wheels')):
    """Plan and visit on the host; the states are what a receipt would hold."""
    master = DefinitionGraph(value, catalogue())
    active = RuntimeClosure(master, Backend())
    states = [active.apply(visit) for visit in active.activate(list(roots)).visits()]
    return master, states


def receipt(master, states):
    return {'spatialVersion': spatial_results.VERSION, 'spatial': spatial_results.record(master, states),
            'states': states}


class Recording(unittest.TestCase):
    def test_every_spatial_entry_is_recorded_at_every_visit_with_what_it_read(self):
        master, states = run(document())
        block = spatial_results.record(master, states)
        self.assertEqual(block['sweepsFastestFirst'], ['t'])
        definitions = block['entries']['definitions']
        self.assertEqual(definitions['model'], {'type': 'box', 'phase': 'observed', 'values': [
            {'min': [0, -1, 0], 'max': [4.5, 1, 1.4]}] * 2})
        self.assertEqual((definitions['probe']['phase'], definitions['probe']['values']),
                         ('visit', [[0, 0, 0], [1, 1, 1]]))
        self.assertEqual((definitions['fixed']['phase'], len(definitions['fixed']['values'])), ('constant', 2))
        self.assertEqual(block['entries']['settings']['model'], {'type': 'box', 'phase': 'constant', 'values': [
            {'min': [0, 0, 0], 'max': [1, 1, 1]}] * 2})
        self.assertEqual(block['inputs']['extents'], [{'node': 'body', 'port': 0, 'values': [BODY, BODY]},
                                                      {'node': 'wheels', 'port': 0, 'values': [WHEELS, WHEELS]}])
        self.assertEqual(block['inputs']['updated'], [{'node': 'body', 'values': [True, True]},
                                                      {'node': 'wheels', 'values': [True, True]}])
        self.assertEqual((block['inputs']['observations'], block['inputs']['samples'], block['inputs']['upstream']),
                         ([], [], []))

    def test_same_named_entries_of_different_sections_stay_distinct(self):
        master, states = run(document())
        entries = spatial_results.record(master, states)['entries']
        self.assertNotEqual(entries['settings']['model']['values'], entries['definitions']['model']['values'])

    def test_an_entry_nothing_active_reads_is_null_and_does_not_fail_the_run(self):
        master, states = run(document(aside=expression('extents(aside).mid'),
                                      empty=expression('extents(wheels, 1)'),
                                      flat=expression('extents(table)')), roots=('cut', 'wheels', 'table'))
        block = spatial_results.record(master, states)
        definitions = block['entries']['definitions']
        self.assertEqual(definitions['aside']['values'], [None, None])
        self.assertEqual(definitions['empty']['values'], [{'min': [1, 1, 1], 'max': [-1, -1, -1]}] * 2)
        self.assertEqual(definitions['flat']['values'], [None, None])
        recorded = {(item['node'], item['port']): item['values'] for item in block['inputs']['extents']}
        self.assertEqual((recorded[('aside', 0)], recorded[('wheels', 1)], recorded[('table', 0)]),
                         ([None, None], [[1, -1, 1, -1, 1, -1]] * 2, [None, None]))
        updated = {item['node']: item['values'] for item in block['inputs']['updated']}
        self.assertEqual((updated['aside'], updated['table']), ([False, False], [True, True]))
        spatial_results.verify(master, receipt(master, states), 'run')

    def test_observations_and_samples_are_recorded_and_replayed(self):
        value = document(seen={'$observe': 'body', 'path': ['bounds']},
                         count={'$observe': 'body', 'path': ['points']},
                         wide=expression('box(seen).deltaX + scalar(count)'),
                         picked={'$sample': 'body', 'association': 'POINTS', 'field': 'p',
                                 'index': expression('t + 2')},
                         scaled=expression('scalar(picked) * 2'))
        value['nodes'][4]['options']['origin'] = expression('vector(scaled, 0, 0)')
        master, states = run(value)
        block = spatial_results.record(master, states)
        self.assertEqual(block['inputs']['observations'], [
            {'node': 'body', 'path': ['bounds'], 'values': [BODY, BODY]},
            {'node': 'body', 'path': ['points'], 'values': [12, 12]}])
        self.assertEqual(block['inputs']['samples'], [{'pointer': '/definitions/picked', 'values': [12.0, 13.0]}])
        definitions = block['entries']['definitions']
        self.assertEqual((definitions['wide']['values'], definitions['scaled']['values']),
                         ([16.5, 16.5], [24.0, 26.0]))
        spatial_results.verify(master, receipt(master, states), 'run')


class Verification(unittest.TestCase):
    def refused(self, master, changed):
        with self.assertRaises(SchemaxisError) as caught:
            spatial_results.verify(master, changed, 'run')
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        return caught.exception.fault

    def test_the_record_is_replayed_from_its_inputs_alone(self):
        master, states = run(document())
        recorded = receipt(master, states)
        spatial_results.verify(master, recorded, 'run')
        replayed = copy.deepcopy(recorded)
        for state in replayed['states']:
            state['observations'] = {node: {'extents': observation['extents']}
                                     for node, observation in state['observations'].items()}
        spatial_results.verify(master, replayed, 'run')

    def test_a_changed_value_input_or_membership_is_refused(self):
        master, states = run(document())
        recorded = receipt(master, states)
        value = copy.deepcopy(recorded)
        value['spatial']['entries']['definitions']['car']['values'][1]['max'][0] += 0.001
        fault = self.refused(master, value)
        self.assertEqual((fault.location, fault.observed['visit']), ('definitions.car', 1))
        inputs = copy.deepcopy(recorded)
        inputs['spatial']['inputs']['extents'][0]['values'][0][1] = 9
        self.assertIn('inputs', self.refused(master, inputs).message)
        missing = copy.deepcopy(recorded)
        del missing['spatial']['entries']['definitions']['probe']
        self.assertIn('differ from the plan', self.refused(master, missing).message)
        absent = {key: value for key, value in recorded.items() if key != 'spatial'}
        self.assertIn('missing', self.refused(master, absent).message)

    def test_an_indexed_observation_is_replayed_from_its_record(self):
        value = {'version': 'schemaxis/1', 'nodes': [{'id': 'body', 'filter': 'wavelet'}],
                 'definitions': {'seen': {'$observe': 'body', 'path': ['bounds', 2]}, 'low': expression('scalar(seen)'),
                                 'whole': {'$observe': 'body', 'path': ['bounds']}}}
        master, states = run(value, ('body',))
        recorded = receipt(master, states)
        self.assertEqual(recorded['spatial']['entries']['definitions']['low']['values'], [BODY[2]])
        spatial_results.verify(master, recorded, 'run')
        changed = copy.deepcopy(recorded)
        changed['spatial']['entries']['definitions']['low']['values'] = [0]
        self.assertEqual(self.refused(master, changed).location, 'definitions.low')

    def test_a_receipt_without_a_record_is_accepted_only_when_there_is_nothing_to_record(self):
        master, states = run({'version': 'schemaxis/1', 'nodes': [{'id': 'body', 'filter': 'wavelet'}]}, ('body',))
        spatial_results.verify(master, {'states': states}, 'run')
        master, states = run(document())
        stripped = {key: value for key, value in receipt(master, states).items()
                    if key not in ('spatial', 'spatialVersion')}
        self.assertIn('missing', self.refused(master, stripped).message)


class RunRecords(unittest.TestCase):
    def test_a_verified_run_gives_records_of_its_first_visit(self):
        import json
        import tempfile
        value = document(aside=expression('extents(aside).mid'))
        master, states = run(value)
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'verification.json').write_text(json.dumps(receipt(master, states)))
            result = spatial_results.run_records(value, root)
            workflow = {'version': 'schemaxis.workflow/1', 'settings': {'gap': 2},
                        'operations': [{'id': 'measure', 'document': value}]}
            (Path(root) / 'measure').mkdir()
            (Path(root) / 'measure' / 'verification.json').write_text(json.dumps(receipt(master, states)))
            nested = spatial_results.run_records(workflow, root)
            missing = spatial_results.run_records(value, Path(root) / 'nothing')
        records = {record['entry']['key']: record for record in result['records']
                   if record['entry']['section'] == 'definitions'}
        self.assertEqual((records['model']['state'], records['model']['value'], records['model']['valid']),
                         ('resolved', {'min': [0, -1, 0], 'max': [4.5, 1, 1.4]}, True))
        self.assertEqual(records['model']['source'], {'kind': 'run', 'inputDigest': result['inputDigest'],
                                                      'state': {'timeIndex': 0, 'indices': {'t': 0}}})
        self.assertEqual((records['probe']['value'], records['probe']['source']['kind']), ([0, 0, 0], 'run'))
        self.assertEqual((records['fixed']['state'], records['fixed']['source']['kind']), ('resolved', 'constant'))
        settings = {record['entry']['key']: record for record in result['records']
                    if record['entry']['section'] == 'settings'}
        self.assertEqual(settings['model']['source']['kind'], 'literal')
        self.assertEqual((records['aside']['state'], records['aside']['reason']), ('unresolved', 'needs-data'))
        self.assertEqual(result['capabilities'], {'extents': True})
        found = [(record.get('operation'), record['entry']['key'], record['source']['kind'])
                 for record in nested['records'] if record['state'] == 'resolved']
        self.assertIn(('measure', 'car', 'run'), found)
        self.assertIn((None, 'gap', 'literal'), found)
        self.assertEqual({record['state'] for record in missing['records']
                          if record['entry']['section'] == 'definitions'
                          and record['entry']['key'] in ('model', 'probe')}, {'unresolved'})


class Handoff(unittest.TestCase):
    def test_a_box_of_one_operation_is_read_by_another_adaptors_operation(self):
        from schemaxis import parallel
        from schemaxis.adaptors.blender.adaptor import plan
        master, states = run(document())
        produced = {**receipt(master, states), 'artifacts': []}
        consumer = {'version': 'schemaxis.blender/1',
                    'definitions': {'upstream': {'$value': 'measure',
                                                 'path': '/spatial/entries/definitions/model/values/1'},
                                    'framed': expression('box(upstream).inflate(0.1)')},
                    'nodes': [{'id': 'paint', 'filter': 'material'},
                              {'id': 'block', 'filter': 'cube', 'inputs': {'material': 'paint'},
                               'options': {'centre': expression('framed.mid'), 'size': expression('framed.deltaX')}}],
                    'scenes': [{'id': 'view', 'visible': ['block'],
                                'images': [{'id': 'image', 'size': [64, 64], 'cameras': [{}]}]}]}
        completed = {'measure': [{'directory': 'measure', 'effective': {}}]}
        with patch.object(parallel, 'verify_native', return_value=produced):
            resolved = parallel.resolve(consumer, completed)
        effective, handoffs = resolved[0], resolved[1]
        self.assertEqual(effective['definitions']['upstream'], {'min': [0, -1, 0], 'max': [4.5, 1, 1.4]})
        self.assertEqual((handoffs[0]['from'], handoffs[0]['path']),
                         ('measure', '/spatial/entries/definitions/model/values/1'))
        graph = plan(effective)[0]
        options = graph.nodes['block']['options']
        for actual, expected in zip(options['centre'], [2.25, 0, 0.7]):
            self.assertAlmostEqual(actual, expected, places=12)
        self.assertAlmostEqual(options['size'], 4.95, places=12)


if __name__ == '__main__':
    unittest.main()
