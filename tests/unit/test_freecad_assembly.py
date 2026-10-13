"""Bounded assembly graph contracts and independent analytic receipt checks."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from schemaxis.core.faults import SchemaxisError
from schemaxis.artifacts import atomic_json
from schemaxis.adaptors.freecad.assembly import plan, run, schema, verify


def declaration():
    return {'version': 'schemaxis.freecad.assembly/1', 'parts': [{'id': 'plate', 'type': 'box',
        'options': {'length': 20, 'width': 10, 'height': 5}}], 'components': [
        {'id': 'base', 'part': 'plate', 'position': [1, 2, 3], 'rotation': 90},
        {'id': 'lid', 'part': 'plate', 'position': [100, 30, 50]}], 'grounded': 'base',
        'joints': [{'id': 'mount', 'type': 'fixed', 'parent': {'component': 'base', 'face': 'top'},
                    'child': {'component': 'lid', 'face': 'bottom'}, 'offset': [2, 0, 1]}]}


class AssemblyContractTests(unittest.TestCase):
    def test_imports_and_planning_are_host_safe(self):
        subprocess.run([sys.executable, '-c', 'import sys; from schemaxis.adaptors.freecad import assembly, assembly_native; '
            'assert not any(n in sys.modules for n in ("FreeCAD","Part","AssemblyApp","JointObject","FreeCADGui"))'], check=True)

    def test_analytic_offsets_and_rotation(self):
        doc = declaration()
        original = copy.deepcopy(doc)
        result = plan(doc)
        expected = result['expected']['lid']
        for a, b in zip(expected['position'], [1, 4, 9]):
            self.assertAlmostEqual(a, b)
        for a, b in zip(expected['bounds'], [-9, 1, 4, 24, 9, 14]):
            self.assertAlmostEqual(a, b)
        self.assertEqual(expected['volume'], 1000)
        self.assertEqual(doc, original)

    def test_authoring_references_and_joint_order(self):
        doc = declaration()
        doc['dimensions'] = {'height': 7}
        doc['parts'][0]['options']['height'] = {'$document': '/dimensions/height'}
        doc['components'].append({'id': 'cap', 'part': 'plate'})
        doc['joints'].insert(0, {'id': 'last', 'type': 'fixed', 'parent': {'component': 'lid', 'face': 'top'},
                                'child': {'component': 'cap', 'face': 'bottom'}})
        result = plan(doc)
        self.assertEqual([j['id'] for j in result['joints']], ['mount', 'last'])
        self.assertEqual(result['expected']['cap']['position'][2], 18)

    def test_bad_parts_and_unbounded_options(self):
        for change in ({'version': 'wrong'}, {'units': 'm'}, {'parts': []}, {'components': []}, {'code': 'pass'},
                       {'parts': [{'id': 'plate', 'type': 'readSTEP'}]},
                       {'parts': [{'id': 'plate', 'type': 'box', 'options': {'length': 0}}]},
                       {'parts': [{'id': 'plate', 'type': 'cylinder', 'options': {'radius': float('inf')}}]},
                       {'parts': [{'id': 'plate', 'type': 'box', 'options': {'length': True}}]},
                       {'components': [{'id': 'base', 'part': 'absent'}, {'id': 'lid', 'part': 'plate'}]},
                       {'parts': declaration()['parts']*2}, {'components': declaration()['components']*17}):
            with self.subTest(change=change), self.assertRaises(SchemaxisError):
                plan({**declaration(), **change})

    def test_rejects_underconstrained_overconstrained_and_cyclic_graphs(self):
        cases = []
        for ground in (None, ['base'], 'unknown'):
            cases.append({**declaration(), 'grounded': ground})
        for joint_change in ({'type': 'revolute'}, {'type': 'python'}, {'offset': [0, 0]},
                             {'child': {'component': 'base', 'face': 'bottom'}},
                             {'parent': {'component': 'lid', 'face': 'top'}},
                             {'parent': {'component': 'base', 'face': 'Face6'}},
                             {'child': {'component': 'missing', 'face': 'top'}}):
            doc = declaration(); doc['joints'][0].update(joint_change); cases.append(doc)
        doc = declaration(); doc['joints'] *= 2; cases.append(doc)
        doc = declaration(); doc['components'].append({'id': 'unattached', 'part': 'plate'}); cases.append(doc)
        doc = declaration(); doc['components'].append({'id': 'cycle', 'part': 'plate'})
        doc['joints'][0]['parent']['component'] = 'cycle'
        doc['joints'].append({'id': 'loop', 'type': 'fixed', 'parent': {'component': 'lid', 'face': 'top'},
                              'child': {'component': 'cycle', 'face': 'bottom'}})
        cases.append(doc)
        for doc in cases:
            with self.subTest(doc=doc), self.assertRaises(SchemaxisError):
                plan(doc)

    def test_schema_and_example_are_bounded(self):
        contract = schema()
        self.assertEqual(contract['properties']['version']['const'], 'schemaxis.freecad.assembly/1')
        self.assertEqual(contract['properties']['components']['maxItems'], 32)
        self.assertFalse(contract['additionalProperties'])
        result = plan(json.loads(Path('examples/schemaxis/freecad-assembly.json').read_text()))
        self.assertEqual(len(result['components']), 4)
        self.assertEqual(len(result['parts']), 2)
        self.assertEqual(result['expectedDegreesOfFreedom'], 0)

    def test_existing_output_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp)/'keep'
            file.write_text('owned')
            with self.assertRaises(SchemaxisError):
                run(declaration(), tmp, executable='/bin/true')
            self.assertEqual(file.read_text(), 'owned')

    def fixture(self, directory):
        doc = declaration(); prepared = plan(doc)
        atomic_json(directory/'authored.json', doc)
        atomic_json(directory/'plan.json', prepared)
        path = directory/'model.FCStd'; path.write_text('synthetic receipt fixture, not native qualification')
        atomic_json(directory/'result.json', {'verified': True})
        poses = {k: {m: v[m] for m in ('position', 'xAxis', 'zAxis')} for k, v in prepared['expected'].items()}
        perturbed = copy.deepcopy(poses); perturbed['lid']['position'][0] += 10
        receipt = {'definition': prepared, 'runtime': ['1', '1', '3'], 'assemblyType': 'Assembly::AssemblyObject',
            'jointGroupType': 'Assembly::JointGroup', 'grounded': 'base', 'groundCount': 1, 'jointCount': 1,
            'parts': prepared['parts'], 'components': [{'id': c['id'], 'part': c['part'], 'type': 'App::Link',
                **prepared['expected'][c['id']], 'valid': True, 'solids': 1} for c in prepared['components']],
            'joints': [{**j, 'nativeType': 'Fixed', 'suppressed': False, 'detached': [False, False],
                        'translationResidual': 0, 'rotationResidual': 0} for j in prepared['joints']],
            'solver': {'returnCode': 0, 'displaced': True, 'restored': True, 'displacedComponents': ['lid'],
                       'before': poses, 'perturbed': perturbed, 'after': poses}}
        atomic_json(directory/'built.json', {**receipt, 'stage': 'build', 'pid': 1})
        reopened = {**receipt, 'stage': 'reopen', 'pid': 2, 'artifact': {'file': str(path), 'units': 'mm',
                    'kind': 'cadScene', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}
        atomic_json(directory/'verification.json', reopened)
        from schemaxis.publication_metadata import finalise
        finalise(directory)
        return reopened

    def test_independent_receipt_checks_reject_false_solver_or_geometry(self):
        mutations = [lambda r: r.update(pid=1), lambda r: r.update(assemblyType='App::Part'),
            lambda r: r.update(groundCount=2), lambda r: r['components'].pop(),
            lambda r: r['components'][1].update(type='Part::Feature'),
            lambda r: r['components'][1].update(volume=999),
            lambda r: r['components'][1].update(position=[0, 0, 0]),
            lambda r: r['solver'].update(returnCode=-4), lambda r: r['solver'].update(returnCode=False),
            lambda r: r['solver'].update(restored=False), lambda r: r['solver'].update(after={}),
            lambda r: r['solver']['perturbed']['lid'].update(position=r['solver']['before']['lid']['position']),
            lambda r: r['joints'][0].update(suppressed=True), lambda r: r['joints'][0].update(rotationResidual=.1),
            lambda r: r['artifact'].update(units='m')]
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); receipt = self.fixture(directory)
            self.assertTrue(verify(directory)['verified'])
            for mutation in mutations:
                changed = copy.deepcopy(receipt); mutation(changed)
                atomic_json(directory/'verification.json', changed)
                with self.subTest(mutation=mutation), self.assertRaises(SchemaxisError):
                    verify(directory)

    def test_altered_native_file_rejects_stale_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); self.fixture(directory)
            (directory/'model.FCStd').write_text('changed')
            with self.assertRaises(SchemaxisError):
                verify(directory)
