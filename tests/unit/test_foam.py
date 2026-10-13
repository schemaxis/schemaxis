from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.core.catalogue import Catalogue
from schemaxis.core.documents import load_document, resolve_document
from schemaxis.core.executor import Executor
from schemaxis.core.extensions import validate_config
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.core.iteration import Axis, expand
from schemaxis.core.planner import Planner
from schemaxis.core.runners import Interpreter
from schemaxis.adaptors.paraview.mvp.foam_export import embedded_helpers, verify_complete
from schemaxis.adaptors.paraview.mvp.slice_export import SliceExport

ROOT = Path(__file__).resolve().parents[2]


def receipt():
    visits = [v.to_dict() for v in expand([Axis.of('time', [0.8, 1]), Axis.of('position', [0.25, 0.5, 0.75])])]
    config = {'fractions': [0.25, 0.5, 0.75], 'maxPublications': 1000, 'appearances': ['p', 'Umag'], 'writers': [
        {'name': 'a', 'size': [100, 80], 'cameras': [0, 1, 2]}, {'name': 'b', 'size': [80, 60], 'cameras': [0]}]}
    result = {'verified': True, 'status': 'succeeded', 'visits': visits, 'proxyIds': {'slice': '10'},
              'config': config, 'timeSelection': {'times': [{'value': 0.8}, {'value': 1}]}, 'states': [], 'events': [], 'images': []}
    for visit in visits:
        n = visit['ordinal']
        result['states'].append({'file': f'geometry-{n}.vtp', 'visit': visit, 'proxyIds': {'slice': '10'}, 'live': {'cells': 2}, 'reopened': {'cells': 2}})
        result['events'] += [{'kind': 'update', 'state': n, 'changed': visit['changed']}, {'kind': 'geometry', 'state': n}]
        for field in config['appearances']:
            result['events'].append({'kind': 'appearance', 'state': n, 'field': field, 'colours': {'slice': field, 'context': field, 'outline': [0, 0, 0]}})
            for writer in config['writers']:
                for camera in range(len(writer['cameras'])):
                    event = {'kind': 'image', 'state': n, 'field': field, 'writer': writer['name'], 'camera': camera}
                    result['events'].append(event)
                    result['images'].append({'event': event, 'verified': True, 'file': f'{n}-{field}-{writer["name"]}-{camera}.png', 'dimensions': writer['size']+[1]})
    return result


class FoamTests(unittest.TestCase):
    def test_complete_ordered_receipt_with_unequal_writer_camera_counts(self):
        value = receipt()
        verify_complete(value)
        self.assertEqual(len(value['states']), 6)
        self.assertEqual(len(value['images']), 48)
        self.assertEqual(value['visits'][3]['changed'], ['time', 'position'])

    def test_counts_do_not_hide_wrong_order_colour_reuse_or_camera_ownership(self):
        for mutation in ['order', 'colour', 'reuse', 'camera', 'reopen', 'partial', 'empty', 'axis', 'dimensions', 'destination']:
            value = receipt()
            if mutation == 'order':
                value['events'][0], value['events'][1] = value['events'][1], value['events'][0]
            elif mutation == 'colour':
                value['events'][2]['colours']['outline'] = 'p'
            elif mutation == 'reuse':
                value['states'][1]['proxyIds']['slice'] = '11'
            elif mutation == 'camera':
                value['images'][0]['event'] = {**value['images'][0]['event'], 'writer': 'b'}
            elif mutation == 'reopen':
                value['states'][0]['reopened']['cells'] = 3
            elif mutation == 'partial':
                value['status'] = 'running'
            elif mutation == 'axis':
                value['config']['fractions'] = [0.25, 0.5]
            elif mutation == 'dimensions':
                value['images'][0]['dimensions'] = [80, 60, 1]
            elif mutation == 'destination':
                value['images'][0]['file'] = value['images'][1]['file']
            else:
                value['states'] = []
            with self.subTest(mutation=mutation), self.assertRaises(SchemaxisError):
                verify_complete(value)

    def test_embedded_helpers_use_the_retained_implementation(self):
        # Execute in a subprocess so the private replay package cannot affect tests.
        import subprocess, sys
        subprocess.run([sys.executable, '-c', embedded_helpers() + '\nfrom _schemaxis_replay.times import resolve_times\nassert resolve_times({"values": [0.8], "tolerance": 0}, [0, 0.8, 1]).values == (0.8,)'], check=True)

    def execute(self, directory, **case):
        catalogue = Catalogue.from_roots([ROOT / 'src/schemaxis/adaptors/paraview/mvp'])
        plan = Planner(catalogue).resolve({'documentVersion': 'schemaxis.workflow/0.1', 'steps': [{
            'id': 'case', 'use': 'paraview.slice_export', 'arguments': {
                'case': {'file': str(ROOT / 'examples/paraview-foam/geometry.json'), **case},
                'outputDirectory': str(directory)}}]})
        return Executor(catalogue).execute(plan.to_dict())

    def test_example_resolves_through_shared_input_and_planner(self):
        document, evidence = resolve_document(load_document((ROOT / 'examples/paraview-foam/mvp.json').read_text()))
        catalogue = Catalogue.from_roots([ROOT / 'src/schemaxis/adaptors/paraview/mvp'])
        plan = Planner(catalogue).resolve(document).to_dict()
        case = plan['nodes'][0]['arguments']['case']
        self.assertEqual(case['fractions'], [0.25, 0.5, 0.75])
        self.assertEqual(case['geometryOrder'], 'positionFastest')
        self.assertEqual(len(case['writers'][0]['cameras']), 4)
        self.assertTrue(any(item.get('operation') == 'overlay' for item in evidence))

    def test_invalid_camera_duplicate_appearance_and_expansion_fail_before_native(self):
        with tempfile.TemporaryDirectory() as temp, patch('schemaxis.adaptors.paraview.mvp.foam_export.require_paraview') as native:
            for values, code in [({'writers': [{'name': 'x', 'cameras': [{'direction': [0, 0, 1]}]}]}, 'INVALID_CAMERA'),
                                 ({'appearances': ['p', 'p']}, 'INVALID_CASE_OPTIONS'),
                                 ({'fractions': [0]*1001}, 'EXPANSION_TOO_LARGE')]:
                result = self.execute(Path(temp)/'output', **values)
                self.assertEqual(result.faults[0].code, code)
            native.assert_not_called()

    def test_existing_output_and_missing_case(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(self.execute(temp).faults[0].code, 'OUTPUT_EXISTS')
            self.assertEqual(self.execute(Path(temp)/'out', file=str(Path(temp)/'missing.foam')).faults[0].code, 'INVALID_CASE')

    def test_interrupted_run_retains_incomplete_receipt_and_fault(self):
        with tempfile.TemporaryDirectory() as temp, patch('schemaxis.adaptors.paraview.mvp.foam_export.require_paraview', return_value=Interpreter('paraview', '/unused')), patch('schemaxis.adaptors.paraview.mvp.foam_export.SubprocessRunner') as runner:
            runner.return_value.side_effect = SchemaxisError(Fault('RUNNER_TIMED_OUT', 'interrupted', 'script', 'submission'))
            directory = Path(temp)/'out'
            result = self.execute(directory)
            self.assertEqual(result.state.value, 'failed')
            self.assertEqual(result.faults[0].code, 'RUNNER_TIMED_OUT')
            self.assertFalse(json.loads((directory/'verification.json').read_text())['verified'])
            self.assertTrue((directory/'submission-fault.json').is_file())


if __name__ == '__main__':
    unittest.main()
