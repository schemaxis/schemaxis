"""Stable native-boundary faults for Gmsh, exercised with the real worker and a stub module.

The stub `gmsh` package only answers the few calls made before each deliberate
failure; no native Gmsh is needed or implied.
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from schemaxis.adaptors.gmsh import adaptor
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
STUB = '''
__version__ = {version!r}
def initialize(*a, **k): pass
def finalize(): pass
class option:
    setNumber = staticmethod(lambda *a: None)
    setString = staticmethod(lambda *a: None)
class model:
    add = staticmethod(lambda name: None)
    getEntities = staticmethod(lambda dim: [(3, 1)])
    getBoundingBox = staticmethod(lambda dim, tag: {bounds!r})
    getBoundary = staticmethod(lambda *a, **k: {boundary!r})
    getEntityType = staticmethod(lambda dim, tag: {kind!r})
    getEntityProperties = staticmethod(lambda dim, tag: ([], [tag+0.5, 0.0, 0.0, 1.0, 0.0, 0.0, float(tag)]) if {kind!r} == 'Cylinder' else ([], [1.0, 0.0, 0.0, 0.0]))
    getParametrizationBounds = staticmethod(lambda dim, tag: ([0.0, 0.0], [1.0, 1.0]))
    getValue = staticmethod(lambda dim, tag, uv: [0.0, float(tag), 0.0])
    isInside = staticmethod(lambda dim, tag, xyz, parametric=False: 1 if parametric else {inside})
    addPhysicalGroup = staticmethod(lambda *a, **k: 1)
    class occ:
        importShapes = staticmethod(lambda *a, **k: {imported!r})
        addBox = staticmethod(lambda *a: 1)
        synchronize = staticmethod(lambda: None)
        getMass = staticmethod(lambda dim, tag: {mass!r})
'''


def document():
    return json.loads((ROOT/'examples/schemaxis/gmsh-minimal.json').read_text())


class NativeFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def interpreter(self, **stub):
        """An absolute launcher whose Python sees a stub gmsh (or none)."""
        path = self.root/'python'
        lines = ['#!/bin/sh']
        if stub:
            package = self.root/'stub'/'gmsh'; package.mkdir(parents=True)
            values = {'version': '4.15.2', 'bounds': [0, 0, 0, 10, 10, 10], 'imported': [(3, 1)], 'mass': 1000.0,
                      'boundary': [(2, 1), (2, 2)], 'kind': 'Plane', 'inside': '(1 if xyz[1] < round(xyz[1]) else 0)', **stub}
            (package/'__init__.py').write_text(STUB.format(**values))
            lines.append(f'PYTHONPATH={self.root/"stub"} exec {sys.executable} "$@"')
        else:
            lines.append(f'exec {sys.executable} "$@"')
        path.write_text('\n'.join(lines)+'\n'); path.chmod(0o755)
        return str(path)

    def fault(self, doc, executable):
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(doc, self.root/('run'+str(len(list(self.root.glob('run*'))))), executable=executable, timeout=60)
        return caught.exception.fault

    def step(self):
        path = self.root/'part.step'; path.write_bytes(b'ISO-10303-21;\nEND-ISO-10303-21;\n')
        doc = document()
        doc['nodes'][0] = {'id': 'solid', 'filter': 'readSTEP', 'options': {'file': str(path)}}
        return doc

    def assertActionable(self, fault, code, location=None):
        self.assertEqual(fault.code, code, fault.to_dict())
        self.assertTrue(fault.recovery and len(fault.recovery) > 20, fault.to_dict())
        if location: self.assertEqual(fault.location, location)
        self.assertEqual(fault.phase, 'native')

    def test_missing_gmsh_module_is_unavailable_not_execution_failure(self):
        fault = self.fault(document(), self.interpreter())
        self.assertActionable(fault, 'NATIVE_UNAVAILABLE')
        self.assertEqual(fault.observed['module'], 'gmsh')

    def test_other_gmsh_version_is_unsupported_not_execution_failure(self):
        fault = self.fault(document(), self.interpreter(version='4.14.0'))
        self.assertActionable(fault, 'UNSUPPORTED_RUNTIME')
        self.assertEqual(fault.observed['version'], '4.14.0')

    def test_multiple_solids_are_unsupported_resource_at_the_source_node(self):
        fault = self.fault(self.step(), self.interpreter(imported=[(3, 1), (3, 2)]))
        self.assertActionable(fault, 'UNSUPPORTED_RESOURCE', 'solid.options.file')
        self.assertIn('exactly one solid', fault.message)
        self.assertEqual(fault.observed['volumes'], 2)

    def test_step_work_estimate_is_a_resource_limit_with_size_recovery(self):
        fault = self.fault(self.step(), self.interpreter(bounds=[0, 0, 0, 5000, 5000, 5000], mass=1.25e11))
        self.assertActionable(fault, 'RESOURCE_LIMIT', 'mesh.options.size')
        self.assertIn('200000-cell work estimate', fault.message)

    def test_unmatched_cylinder_selector_fault_stays_trustworthy_with_many_candidates(self):
        doc = self.step()
        doc['nodes'][1]['options']['cylinderGroups'] = [
            {'name': 'bore', 'axis': 'x', 'centre': [0, 0, 0], 'radius': 999, 'side': 'inner'}]
        fault = self.fault(doc, self.interpreter(boundary=[(2, t) for t in range(1, 80)], kind='Cylinder'))
        self.assertActionable(fault, 'INVALID_SELECTION', 'mesh.options.cylinderGroups[0]')
        self.assertTrue(fault.observed['candidates'])
        self.assertLessEqual(len(json.dumps(dict(fault.observed))), 2000)
        self.assertEqual(fault.observed['matched'], 0)

    def test_undeterminable_wall_side_is_a_distinct_refusal_and_not_selectable(self):
        doc = self.step()
        doc['nodes'][1]['options']['cylinderGroups'] = [
            {'name': 'bore', 'axis': 'x', 'centre': [0, 0, 0], 'radius': 5, 'side': 'inner'}]
        fault = self.fault(doc, self.interpreter(boundary=[(2, 5), (2, 6)], kind='Cylinder', inside='1'))
        self.assertActionable(fault, 'INVALID_SELECTION', 'mesh.options.cylinderGroups[0]')
        self.assertIn('could not be determined', fault.message)
        self.assertEqual(fault.observed['unknownSide'], 1)
        self.assertEqual(fault.observed['candidates'], [])

    def test_unmatched_selector_reports_other_curved_surfaces_with_distinct_wording(self):
        doc = self.step()
        doc['nodes'][1]['options']['cylinderGroups'] = [
            {'name': 'bore', 'axis': 'x', 'centre': [0, 0, 0], 'radius': 5, 'side': 'inner'}]
        fault = self.fault(doc, self.interpreter(boundary=[(2, 1), (2, 2)], kind='Cone'))
        self.assertActionable(fault, 'INVALID_SELECTION', 'mesh.options.cylinderGroups[0]')
        self.assertIn('matches no whole analytic cylinder', fault.message)
        self.assertEqual(dict(fault.observed['otherCurved']), {'Cone': 2})
        self.assertEqual(fault.observed['obliqueCylinders'], 0)

    def test_empty_face_selector_is_invalid_selection(self):
        doc = document()
        doc['nodes'][1]['options']['faceGroups'] = [{'name': 'absent', 'axis': 'x', 'coordinate': 5}]
        stub = self.interpreter(bounds=[0, 0, 0, 10, 10, 0])
        fault = self.fault(doc, stub)
        self.assertActionable(fault, 'INVALID_SELECTION', 'mesh.options.faceGroups[0]')
        self.assertIn('empty', fault.message)

    def test_unexpected_native_exception_keeps_generic_code_with_type_and_recovery(self):
        fault = self.fault(self.step(), self.interpreter(imported=None))
        self.assertActionable(fault, 'NATIVE_EXECUTION_FAILED')
        self.assertIn('exceptionType', fault.observed)

    def test_host_does_not_trust_forged_or_malformed_native_fault_files(self):
        for payload in ('{"code":"VERIFICATION_FAILED","message":"forged"}', '[1]', 'not json',
                        '{"code":"NATIVE_UNAVAILABLE","message":""}'):
            def forged(command, directory, stage, timeout, payload=payload):
                (Path(directory)/'native-fault.json').write_text(payload)
                raise SchemaxisError(adaptor.Fault('RUNNER_FAILED', 'worker exited 1', stage, 'pipeline'))
            with self.subTest(payload=payload), patch.object(adaptor, 'execute', forged):
                fault = self.fault(document(), '/bin/true')
                self.assertEqual(fault.code, 'NATIVE_EXECUTION_FAILED', fault.to_dict())
                self.assertNotEqual(fault.message, 'forged')

    def test_oversized_fault_fields_are_not_trusted(self):
        for key in ('message', 'location', 'recovery', 'observed'):
            record = {'code':'NATIVE_UNAVAILABLE', 'message':'missing module', 'observed':{}}
            record[key] = {'detail':'x'*2001} if key == 'observed' else 'x'*2001
            path = self.root / 'native-fault.json'
            path.write_text(json.dumps(record))
            with self.subTest(key=key):
                self.assertEqual(adaptor.native_fault(path).code, 'NATIVE_EXECUTION_FAILED')

    def test_failed_run_records_the_structured_fault_and_never_publishes(self):
        fault = self.fault(document(), self.interpreter())
        directory = next(self.root.glob('run*'))
        record = json.loads((directory/'result.json').read_text())
        self.assertEqual((record['status'], record['verified']), ('failed', False))
        self.assertEqual(record['fault'], fault.to_dict())
        self.assertFalse((directory/'verification.json').exists())


if __name__ == '__main__': unittest.main()
