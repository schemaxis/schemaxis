# Copyright (C) 2026 David L. F. Gaden
"""Numbered case names survive schema, graph references and runtime observations."""
import copy
import unittest

from schemaxis.adaptors.paraview.console import validate
from schemaxis.adaptors.paraview.schema import document_schema
from schemaxis.admission_schema import validate as validate_schema
from schemaxis.core.faults import SchemaxisError
from schemaxis.filters import catalogue
from schemaxis.pipeline import DefinitionGraph, RuntimeClosure
from test_schemaxis_pipeline import Backend


class PortBackend(Backend):
    def output_port(self, handle, port):
        if port != 0:
            raise AssertionError('only the tested default port is available')
        return handle


class NodeInstanceNamesTests(unittest.TestCase):
    def document(self):
        return {'version': 'schemaxis/1', 'nodes': [
            {'id': '004_031_9d_case', 'filter': 'wavelet'},
            {'id': 'cut', 'filter': 'slice', 'inputs': {'input': {'node': '004_031_9d_case', 'port': 0}},
             'options': {'origin': {'$calc': 'midpoint', 'args': [
                 {'$observe': '004_031_9d_case', 'path': ['bounds']}]}}}],
            'scenes': [{'id': 'view', 'visible': {'cut': {}}, 'geometry': ['004_031_9d_case'],
                        'measurements': [{'node': '004_031_9d_case'}]}]}

    def test_numeric_case_name_schema_and_planning_agree(self):
        value = self.document()
        validate_schema(value, document_schema())
        planned, _, _ = validate(value, draft=False)
        self.assertIn('004_031_9d_case', planned.nodes)
        graph = DefinitionGraph(value, catalogue())
        active = RuntimeClosure(graph, PortBackend())
        active.apply(next(active.activate(['cut']).visits()))
        self.assertEqual(active.values['cut']['origin'], [0, 0, 0])
        self.assertIn('004_031_9d_case', active.handles)

    def test_quoted_expression_can_observe_numeric_case_name(self):
        value = self.document()
        value['nodes'][1]['options']['origin'] = {'$expr': 'extents(`004_031_9d_case`).mid'}
        active = RuntimeClosure(DefinitionGraph(value, catalogue()), PortBackend())
        active.apply(next(active.activate(['cut']).visits()))
        self.assertEqual(active.values['cut']['origin'], [0, 0, 0])

    def test_path_like_and_empty_names_are_still_refused(self):
        for invalid in ('', '../case', 'case.foam', '_case', 'case name'):
            with self.subTest(name=invalid):
                value = copy.deepcopy(self.document())
                value['nodes'][0]['id'] = invalid
                with self.assertRaises(SchemaxisError):
                    DefinitionGraph(value, catalogue())
