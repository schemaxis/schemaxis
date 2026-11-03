# Copyright (C) 2026 David L F Gaden
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.job import plan, identities, schedule, verify_receipt
from schemaxis.pipeline import evaluate


def document():
    return {'version': 'schemaxis/1', 'nodes': [{'id': 's', 'filter': 'sphere'}],
            'scenes': [{'id': 'one', 'geometry': ['s'], 'visible': {'s': {}},
                        'appearances': [{}, {'s': {'colour': [1, 0, 0]}}],
                        'images': [{'id': 'a', 'cameras': [{}]},
                                   {'id': 'b', 'cameras': [{}, {'direction': [0, 1, 0]}]}]}]}


class PublicationTests(unittest.TestCase):
    def test_new_image_receipts_require_the_scheduled_render_time(self):
        value = {'version': 'schemaxis/1', 'times': [2],
                 'nodes': [{'id': 's', 'filter': 'sphere'}],
                 'scenes': [{'id': 's', 'visible': {'s': {}},
                             'images': [{'id': 'view', 'cameras': [{}]}]}]}
        master, scenes, _ = plan(value)
        scene, visit = next(schedule(master, scenes))
        expected = next(identities(scene, visit))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); path = directory/'image.png'
            path.write_bytes(b'host receipt fixture; native pixels tested separately')
            artifact = {'file': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'verified': True, 'identity': expected, 'viewTime': 2,
                        'effectiveAppearance': scene['appearances'][0],
                        'effectiveCamera': scene['images'][0]['cameras'][0]}
            receipt = {'status': 'succeeded', 'verified': True, 'renderTimeVersion': 1,
                       'planDigest': master.to_dict()['digest'], 'planVersion': master.to_dict()['version'],
                       'states': [{'scene': 's', 'visit': visit, 'proxyIds': {'s': '1'},
                                   'effective': {'s': master.nodes['s']['options']},
                                   'observations': {'s': {}}, 'updated': ['s']}],
                       'events': [{'event': 'create', 'node': 's'},
                                  {'event': 'update', 'node': 's', 'time': 2},
                                  {'event': 'delete', 'node': 's'}], 'artifacts': [artifact]}
            target = directory/'verification.json'
            target.write_text(json.dumps(receipt))
            self.assertTrue(verify_receipt(directory, master, scenes)['verified'])
            for wrong in (0, 1, None):
                artifact['viewTime'] = wrong
                target.write_text(json.dumps(receipt))
                with self.subTest(time=wrong):
                    self.fault('VERIFICATION_FAILED', lambda: verify_receipt(directory, master, scenes))

    def fault(self, code, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)

    def test_geometry_is_not_multiplied_by_appearance_or_writer(self):
        master, scenes, result = plan(document())
        self.assertEqual(result['expectedPublications'], 7)
        ordered = [i for s, v in schedule(master, scenes) for i in identities(s, v)]
        self.assertEqual([i['kind'] for i in ordered], ['geometry'] + ['image'] * 6)
        self.assertEqual([(i['writer'], i['camera']) for i in ordered[1:4]], [('a', 0), ('b', 0), ('b', 1)])

    def test_time_surrounds_scenes(self):
        value = document()
        value['times'] = [0, 1]
        value['scenes'].append({'id': 'two', 'geometry': ['s']})
        master, scenes, _ = plan(value)
        self.assertEqual([(v['time'], s['id']) for s, v in schedule(master, scenes)],
                         [(0, 'one'), (0, 'two'), (1, 'one'), (1, 'two')])

    def test_zero_and_parallel_camera_vectors_rejected(self):
        for direction in ([0, 0, 0], [0, 0, 1]):
            value = document()
            value['scenes'][0]['images'][0]['cameras'] = [{'direction': direction}]
            self.fault('INVALID_CAMERA', lambda: plan(value))

    def test_publication_budget_precedes_execution(self):
        value = document()
        value['maxPublications'] = 6
        self.fault('EXPANSION_TOO_LARGE', lambda: plan(value))

    def test_unknown_appearance_target_and_unknown_option_rejected(self):
        value = document()
        value['scenes'][0]['appearances'].append({'missing': {}})
        self.fault('UNKNOWN_ARGUMENT', lambda: plan(value))
        value = document()
        value['scenes'][0]['visible']['s'] = {'opactiy': 1}
        self.fault('UNKNOWN_ARGUMENT', lambda: plan(value))

    def test_invalid_range_and_empty_publication(self):
        value = document()
        value['scenes'][0]['visible']['s'] = {'range': [10, -10]}
        self.fault('INVALID_RANGE', lambda: plan(value))
        value['scenes'] = [{'id': 'none', 'visible': {'s': {}}}]
        self.fault('EMPTY_PUBLICATION', lambda: plan(value))

    def test_vector_arithmetic_and_bounds(self):
        calculate = lambda v: evaluate(v, {}, {}, 0, '$')
        self.assertEqual(calculate({'$calc': 'multiply', 'args': [[1, 2, 3], 2]}), [2, 4, 6])
        self.assertEqual(calculate({'$calc': 'add', 'args': [[1, 2, 3], [4, 5, 6]]}), [5, 7, 9])
        self.assertEqual(calculate({'$calc': 'boundsMax', 'args': [[-1, 1, -2, 2, -3, 3]]}), [1, 2, 3])
        self.fault('INVALID_EXPRESSION', lambda: calculate({'$calc': 'multiply', 'args': ['huge', 100000000]}))
        self.fault('INVALID_EXPRESSION', lambda: calculate({'$calc': 'divide', 'args': [1, 0]}))

    def test_data_dependent_camera_keeps_hidden_source(self):
        value = document()
        value['nodes'].append({'id': 'framing', 'filter': 'sphere', 'options': {'radius': 5}})
        value['scenes'][0]['images'][0]['cameras'] = [{'bounds': {'$observe': 'framing', 'path': ['bounds']}}]
        master, scenes, _ = plan(value)
        self.assertEqual(scenes[0]['selection']['order'], ['s', 'framing'])
        self.assertEqual(scenes[0]['publications'], 7)

    def test_presentation_changes_are_in_plan_digest(self):
        first = document()
        second = copy.deepcopy(first)
        second['scenes'][0]['images'][0]['cameras'][0]['scale'] = 5
        self.assertNotEqual(plan(first)[2]['pipeline']['digest'], plan(second)[2]['pipeline']['digest'])

    def test_presentation_only_axis_cannot_duplicate_geometry_silently(self):
        value = document()
        value['axes'] = [{'name': 'camera', 'values': [1, 2]}]
        value['scenes'][0]['images'][0]['cameras'][0]['scale'] = {'$axis': 'camera'}
        self.fault('PRESENTATION_AXIS_UNAVAILABLE', lambda: plan(value))

    def test_receipt_checks_membership_content_and_sidecars(self):
        value = {'version': 'schemaxis/1', 'nodes': [{'id': 's', 'filter': 'sphere'}],
                 'scenes': [{'id': 's', 'geometry': ['s']}]}
        master, scenes, _ = plan(value)
        expected = next(identities(*next(schedule(master, scenes))))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path, child = directory / 'surface.vtm', directory / 'leaf.vtp'
            path.write_text('master')
            child.write_text('leaf')
            hashes = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            receipt = {'status': 'succeeded', 'verified': True, 'planDigest': master.to_dict()['digest'],
                       'planVersion': master.to_dict()['version'],
                       'states': [{'scene': 's', 'visit': next(master.select(['s']).visits()),
                                   'proxyIds': {'s': '1'}, 'effective': {'s': master.nodes['s']['options']},
                                   'observations': {'s': {}}, 'updated': ['s']}],
                       'events': [{'event': 'create', 'node': 's'}, {'event': 'update', 'node': 's', 'time': 0.0},
                                  {'event': 'delete', 'node': 's'}],
                       'artifacts': [{'file': str(path), 'sha256': hashes(path), 'verified': True,
                                      'identity': expected, 'files': [{'file': str(child), 'sha256': hashes(child)}]}]}
            target = directory / 'verification.json'
            target.write_text(json.dumps(receipt))
            self.assertTrue(verify_receipt(directory, master, scenes)['verified'])
            child.write_text('tampered')
            self.fault('VERIFICATION_FAILED', lambda: verify_receipt(directory, master, scenes))
            receipt['artifacts'] = []
            target.write_text(json.dumps(receipt))
            self.fault('VERIFICATION_FAILED', lambda: verify_receipt(directory, master, scenes))
            receipt['status'] = 'incomplete'
            target.write_text(json.dumps(receipt))
            self.fault('INCOMPLETE_EXECUTION', lambda: verify_receipt(directory, master, scenes))


if __name__ == '__main__':
    unittest.main()
