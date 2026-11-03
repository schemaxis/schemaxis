# Copyright (C) 2026 David L F Gaden
"""Analytic geometry oracles and declared mesh acceptance contracts."""
import copy
import json
import math
from pathlib import Path
import unittest

from schemaxis.adaptors.gmsh import adaptor, quality
from schemaxis.adaptors.gmsh.refinement import Policy
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]


class QualityTests(unittest.TestCase):
    def test_analytic_requirements_resolve_before_feedback_policy(self):
        document = json.loads((ROOT/'examples/schemaxis/gmsh-analytic-refinement.json').read_text())
        prepared = adaptor.plan(document)
        self.assertEqual(prepared['states'], 2)
        for visit, edge in zip(prepared['visits'], (4.5, 3)):
            policy = Policy(visit['document'])
            self.assertEqual(policy.settings['requirements']['maximumEdgeLength'], edge)
            self.assertEqual(policy.propose([])['nodes'][1]['options']['size'], 3)

    def test_regular_tetrahedron_scale_translation_and_rotation_invariance(self):
        points = [(0,0,0), (1,0,0), (.5,math.sqrt(3)/2,0), (.5,math.sqrt(3)/6,math.sqrt(2/3))]
        result = quality.tetrahedron(points)
        self.assertAlmostEqual(result['meanRatio'], 1)
        self.assertAlmostEqual(result['volume'], math.sqrt(2)/12)
        transformed = [(7-2*y, 3+2*x, -9+2*z) for x,y,z in points]
        changed = quality.tetrahedron(transformed)
        self.assertAlmostEqual(changed['meanRatio'], 1)
        self.assertAlmostEqual(changed['maximumEdgeLength'], 2)
        self.assertAlmostEqual(changed['volume'], 8*result['volume'])

    def test_flattening_detected_and_orientation_reversal_rejected(self):
        points = [(0,0,0), (1,0,0), (0,1,0), (.2,.2,1e-8)]
        self.assertLess(quality.tetrahedron(points)['meanRatio'], 1e-4)
        points[0], points[1] = points[1], points[0]
        with self.assertRaises(SchemaxisError): quality.tetrahedron(points)

    def test_distribution_has_declared_linear_percentiles(self):
        result = quality.distribution([4,1,3,2])
        self.assertEqual(result['median'], 2.5)
        self.assertEqual(result['mean'], 2.5)
        self.assertAlmostEqual(result['p05'], 1.15)
        self.assertAlmostEqual(result['p95'], 3.85)

    def test_boundary_sizing_and_local_requirements_use_declared_names(self):
        document = json.loads((ROOT/'examples/schemaxis/gmsh-boundary-sizing.json').read_text())
        prepared = adaptor.plan(document)
        self.assertEqual(prepared['nodes'][1]['options']['nearBoundaries'][0]['boundary'], 'fixed')
        for key,value in [('boundary','missing'), ('size',4), ('distance',0), ('script','bad')]:
            bad = copy.deepcopy(document); bad['nodes'][1]['options']['nearBoundaries'][0][key] = value
            with self.subTest(key=key), self.assertRaises(SchemaxisError): adaptor.plan(bad)
        document['refinement'] = {'requirements': {'boundaryMaximumEdgeLength': [{'boundary':'fixed','maximum':1}]}}
        policy = Policy(document)
        candidate = policy.propose([])
        observed = {'tetrahedra': 100, 'capturedSource': {}, 'quality': {'boundaries': [
            {'name': 'fixed', 'maximumEdgeLength': {'maximum': .9}}]}}
        self.assertTrue(policy.judge(candidate, observed, [])['accepted'])
        second = policy.propose([{'document':candidate}])
        self.assertAlmostEqual(second['nodes'][1]['options']['nearBoundaries'][0]['size'], .75*.7)
        document['refinement']['requirements']['boundaryMaximumEdgeLength'][0]['boundary'] = 'missing'
        with self.assertRaises(SchemaxisError): adaptor.plan(document)

    def test_work_estimate_prevents_unbounded_refinement(self):
        document = json.loads((ROOT/'examples/schemaxis/gmsh-refinement.json').read_text())
        document['refinement']['minimumSize'] = .001
        policy = Policy(document)
        candidate = policy.propose([])
        observation = {'capturedSource': {}, 'tetrahedra': 100,
            'cadBounds': [0,0,0,100,100,100], 'quality': {'maximumEdgeLength': {'maximum': 4}, 'meanRatio': {'minimum': .5}}}
        self.assertEqual(policy.judge(candidate, observation, [])['stop'], 'work_estimate_limit')

    def test_refinement_bounds_and_meaningful_requirements(self):
        document = json.loads((ROOT/'examples/schemaxis/gmsh-refinement.json').read_text())
        for key, value in [('maxIterations', 0), ('reductionFactor', 1), ('minimumSize', 4),
                           ('maxTetrahedra', 0), ('requirements', {}),
                           ('requirements', {'minimumMeanRatio': 1.1}), ('requirements', {'script': 'anything'})]:
            bad = copy.deepcopy(document); bad['refinement'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(SchemaxisError): adaptor.plan(bad)
        policy = Policy(document)
        candidate = policy.propose([])
        observed = {'tetrahedra': 100, 'capturedSource': {}, 'quality': {
            'maximumEdgeLength': {'maximum': 3}, 'meanRatio': {'minimum': .5}}}
        self.assertTrue(policy.judge(candidate, observed, [])['accepted'])
        observed['tetrahedra'] = 20001
        result = policy.judge(candidate, observed, [])
        self.assertFalse(result['accepted']); self.assertEqual(result['stop'], 'cell_budget_exceeded')
        with self.assertRaises(SchemaxisError):
            policy.judge(candidate, observed, [{'observation': {**observed, 'capturedSource': {'sha256': 'changed'}}}])
