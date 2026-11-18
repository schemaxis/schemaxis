# Copyright (C) 2026 David L. F. Gaden.
"""Host contracts for early case-layout selection; native reading is separate."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from schemaxis.adaptors.paraview.filters import catalogue
from schemaxis.adaptors.paraview.catalogue_import import compile_catalogue
from schemaxis.adaptors.paraview.native import ParaViewBackend
from schemaxis.core.faults import SchemaxisError
from schemaxis.pipeline import DefinitionGraph


class OpenFOAMConstructor(unittest.TestCase):
    def test_catalogue_recapture_keeps_case_type_at_construction(self):
        identity = 'sources/OpenFOAMReader'
        snapshot = {'version': '5.13.3', 'source': 'host fixture', 'groups': {'sources': ['OpenFOAMReader']},
                    'roots': [identity], 'proxies': {identity: {
                        'native': 'OpenFOAMReader', 'name': 'OpenFOAMReader', 'group': 'sources',
                        'constructorAvailable': True, 'outputPorts': 1,
                        'properties': {'CaseType': {
                            'class': 'vtkSMIntVectorProperty', 'informationOnly': False,
                            'numberOfElements': 1, 'observedDefault': 1,
                            'definition': {'attributes': {'command': 'SetCaseType'}},
                            'domains': [{'class': 'vtkSMEnumerationDomain',
                                         'entries': ['Decomposed Case', 'Reconstructed Case']}]}}}}}
        declaration = compile_catalogue(snapshot)['declarations']['pvOpenFOAMReader']
        self.assertEqual(declaration['options']['CaseType'],
                         catalogue()['pvOpenFOAMReader']['options']['CaseType'])

    def test_full_reader_case_type_is_constant_and_precedes_filename(self):
        declarations = catalogue()
        declaration = declarations['pvOpenFOAMReader']
        self.assertTrue(declaration['options']['CaseType']['constructor'])
        self.assertNotIn('default', declaration['options']['CaseType']['value'])
        for operation, constructor in (
            ('pvOpenFOAMReader', {'FileName': 'case.foam', 'CaseType': 'Decomposed Case'}),
            ('foam', {'file': 'case.foam', 'caseType': 'Decomposed Case'}),
            ('pvOpenFOAMReader', {'FileName': 'case.foam'}),
        ):
            with self.subTest(operation=operation, constructor=constructor):
                calls = []
                proxy = SimpleNamespace(
                    SMProxy=SimpleNamespace(GetVTKClassName=lambda: 'vtkPOpenFOAMReader'),
                    ListProperties=lambda: [], GetXMLGroup=lambda: 'sources',
                    GetXMLName=lambda: 'OpenFOAMReader')
                def factory(**kwargs):
                    calls.append(kwargs)
                    return proxy
                backend = ParaViewBackend.__new__(ParaViewBackend)
                backend.pv = SimpleNamespace(OpenFOAMReader=factory)
                backend.records = {}
                backend.construct('case', declarations[operation], {}, constructor)
                keys = list(calls[0])
                if 'CaseType' in keys:
                    self.assertLess(keys.index('CaseType'), keys.index('FileName'))
                    self.assertEqual(calls[0]['CaseType'], 'Decomposed Case')
                else:
                    self.assertEqual(keys, ['registrationName', 'FileName'])

        document = {'version': 'schemaxis/1', 'nodes': [{'id': 'case',
                    'filter': 'pvOpenFOAMReader', 'options': {
                        'FileName': 'case.foam', 'CaseType': {'$time': True}}}]}
        with self.assertRaises(SchemaxisError) as caught:
            DefinitionGraph(document, declarations)
        self.assertEqual(caught.exception.fault.code, 'DYNAMIC_CONSTRUCTOR')

    def test_time_listing_options_request_refresh_after_configuration(self):
        declaration = catalogue()['pvOpenFOAMReader']
        for key in ('SkipZeroTime', 'ListtimestepsaccordingtocontrolDict', 'CaseType'):
            calls = []
            proxy = SimpleNamespace(Refresh=lambda: calls.append('refresh'))
            backend = ParaViewBackend.__new__(ParaViewBackend)
            backend.records = {id(proxy): {'node': 'case', 'options': {}}}
            value = 'Decomposed Case' if key == 'CaseType' else False
            with patch('schemaxis.adaptors.paraview.native.configure_binding',
                       side_effect=lambda *args: calls.append('configure')), patch(
                       'schemaxis.adaptors.paraview.native.retained_value', return_value=value):
                backend.configure(proxy, declaration, {key: value})
            self.assertEqual(calls[-1], 'refresh')


if __name__ == '__main__':
    unittest.main()
