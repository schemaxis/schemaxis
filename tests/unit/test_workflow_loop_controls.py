"""Loop settings remain strict and cannot claim unqualified native execution."""

import copy
import json
import unittest
from unittest.mock import patch

from schemaxis.core.faults import SchemaxisError
from schemaxis.workflow_loop_controls import catalogue, validate_config


class WorkflowLoopControlTests(unittest.TestCase):
    def setUp(self):
        self.fixed = {'algorithm': 'fixed-point', 'maxIterations': 50,
                      'absoluteTolerance': 1e-6, 'relativeTolerance': 1e-4}
        self.relaxed = {**self.fixed, 'algorithm': 'constant-relaxation', 'relaxation': 0.5}

    def fault(self, value, code='INVALID_FEEDBACK_CONFIG', suffix=None):
        with self.assertRaises(SchemaxisError) as caught:
            validate_config(value, '$.controllers.loop')
        result = caught.exception.fault
        self.assertEqual(result.code, code)
        self.assertTrue(result.recovery)
        self.assertEqual(result.phase, 'validation')
        if suffix is not None:
            self.assertEqual(result.location, '$.controllers.loop' + suffix)
        json.dumps(caught.exception.to_dict(), allow_nan=False)

    def test_available_settings_round_trip_without_mutation_or_execution(self):
        for original in (self.fixed, self.relaxed):
            before = copy.deepcopy(original)
            with patch('subprocess.Popen', side_effect=AssertionError('native launch prohibited')):
                result = validate_config(original)
            self.assertEqual(result, original)
            self.assertIsNot(result, original)
            result['maxIterations'] = 1
            self.assertEqual(original, before)
            self.assertEqual(json.loads(json.dumps(original)), before)

    def test_catalogue_distinguishes_configuration_from_execution(self):
        records = catalogue()
        self.assertEqual(len(records), len({record['id'] for record in records}))
        configurable = {record['id'] for record in records if record['configurable']}
        self.assertEqual(configurable, {'fixed-point', 'constant-relaxation'})
        for record in records:
            self.assertFalse(record['executionAvailable'])
            self.assertTrue(record['requires'])
            self.assertTrue(record['reason'])
            if record['configurable']:
                self.assertEqual(record['status'], 'configuration-only')
                self.assertEqual(record['convergence'], 'raw-residual')
                self.assertEqual(validate_config(record['defaults']), record['defaults'])
        by_id = {record['id']: record for record in records}
        self.assertEqual(by_id['step-doubling']['kind'], 'time-step-control')
        self.assertIn('not a generic algebraic-loop solver', by_id['step-doubling']['reason'])
        self.assertEqual(by_id['stsc']['kind'], 'source-coupling')
        self.assertIn('source-contribution', by_id['stsc']['reason'])
        json.dumps(records, allow_nan=False)

    def test_catalogue_edits_do_not_change_other_records_or_future_validation(self):
        records = catalogue()
        baseline = catalogue()
        records[0]['requires'].clear()
        records[0]['defaults']['algorithm'] = 'stsc'
        records[0]['configurable'] = False
        records[-1]['configurable'] = True
        self.assertEqual(records[1]['requires'], baseline[1]['requires'])
        self.assertEqual(catalogue(), baseline)
        self.assertEqual(validate_config(self.fixed), self.fixed)
        self.fault({**self.fixed, 'algorithm': 'stsc'}, 'FEEDBACK_ALGORITHM_UNAVAILABLE', '.algorithm')

    def test_reserved_algorithms_fail_with_unavailable_not_valid_config(self):
        for algorithm in ('aitken', 'quasi-newton', 'step-doubling', 'stsc'):
            with self.subTest(algorithm=algorithm):
                self.fault({**self.fixed, 'algorithm': algorithm},
                           'FEEDBACK_ALGORITHM_UNAVAILABLE', '.algorithm')

    def test_unknown_or_non_string_algorithm_is_invalid(self):
        for algorithm in ('unknown', '', 'FIXED-POINT', None, 3, [], {}):
            with self.subTest(algorithm=algorithm):
                self.fault({**self.fixed, 'algorithm': algorithm}, suffix='.algorithm')

    def test_configuration_requires_an_object_and_all_fields(self):
        for value in (None, [], '', 1, False):
            with self.subTest(value=value):
                self.fault(value, suffix='')
        for field in self.relaxed:
            value = self.relaxed.copy()
            del value[field]
            with self.subTest(missing=field):
                self.fault(value, suffix='.' + field)

    def test_extra_fields_and_relaxation_on_fixed_point_are_rejected(self):
        for extra in ({'relaxation': 0.5}, {'run': True}, {'absoluteTolerence': 1e-6}, {1: 'x'}):
            with self.subTest(extra=extra):
                self.fault({**self.fixed, **extra}, suffix='')

    def test_iteration_limits_are_bounded_integers(self):
        for value in (True, False, 0, -1, 1001, 1.0, '50', float('inf'), 10**400):
            with self.subTest(value=value):
                self.fault({**self.fixed, 'maxIterations': value}, suffix='.maxIterations')
        for value in (1, 1000):
            with self.subTest(value=value):
                self.assertEqual(validate_config({**self.fixed, 'maxIterations': value})['maxIterations'], value)

    def test_tolerances_reject_nonfinite_booleans_and_wrong_sign(self):
        invalid = (True, False, '0.1', None, [], {}, -1, float('nan'),
                   float('inf'), float('-inf'), 10**400)
        for field in ('absoluteTolerance', 'relativeTolerance'):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    self.fault({**self.fixed, field: value}, suffix='.' + field)
        self.fault({**self.fixed, 'absoluteTolerance': 0}, suffix='.absoluteTolerance')
        self.assertEqual(validate_config({**self.fixed, 'relativeTolerance': 0})['relativeTolerance'], 0)
        self.assertEqual(validate_config({**self.fixed, 'absoluteTolerance': 1})['absoluteTolerance'], 1)

    def test_relaxation_factor_cannot_disable_updates_or_extrapolate(self):
        for value in (True, False, 0, -0.5, 1.1, '0.5', None, [], float('nan'), float('inf'), 10**400):
            with self.subTest(value=value):
                self.fault({**self.relaxed, 'relaxation': value}, suffix='.relaxation')
        for value in (1, 0.5, 1e-12):
            with self.subTest(value=value):
                self.assertEqual(validate_config({**self.relaxed, 'relaxation': value})['relaxation'], value)


if __name__ == '__main__':
    unittest.main()
