# Copyright (C) 2026 David L F Gaden
"""Host checks for bounded PrusaSlicer slicing; native acceptance is separate."""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

from schemaxis.adaptors import registry
from schemaxis.adaptors.prusaslicer import adaptor, gcode, profile, stl
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
BOX = ROOT/'examples/schemaxis/prusaslicer-box.stl'
INCH_BOX = ROOT/'examples/schemaxis/prusaslicer-box-inch.stl'


def example(name='pla', model=BOX):
    document = json.loads((ROOT/f'examples/schemaxis/prusaslicer-{name}.json').read_text())
    document['model']['file'] = str(model)
    return document


def problem(message, **observed):
    raise ValueError(message)


def triangles(data):
    return stl.read(data, problem)


def binary(mesh_triangles):
    payload = bytearray(b'schemaxis binary test'.ljust(80, b' '))
    payload += struct.pack('<I', len(mesh_triangles))
    for triangle in mesh_triangles:
        payload += struct.pack('<12fH', 0, 0, 0, *[c for vertex in triangle for c in vertex], 0)
    return bytes(payload)


def box_triangles(sx=24, sy=16, sz=10):
    quads = [[(0,0,0),(0,1,0),(1,1,0),(1,0,0)], [(0,0,1),(1,0,1),(1,1,1),(0,1,1)],
             [(0,0,0),(1,0,0),(1,0,1),(0,0,1)], [(0,1,0),(0,1,1),(1,1,1),(1,1,0)],
             [(0,0,0),(0,0,1),(0,1,1),(0,1,0)], [(1,0,0),(1,1,0),(1,1,1),(1,0,1)]]
    scale = lambda p: (p[0]*sx, p[1]*sy, p[2]*sz)
    return [tuple(map(scale, tri)) for q in quads for tri in ((q[0], q[1], q[2]), (q[0], q[2], q[3]))]


class PlanTests(unittest.TestCase):
    def assertFault(self, code, action, location=None):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        if location is not None:
            self.assertEqual(caught.exception.fault.location, location)
        return caught.exception.fault

    def test_examples_plan_deterministically_without_mutation(self):
        for name in ('pla', 'petg', 'inch'):
            document = example(name, INCH_BOX if name == 'inch' else BOX)
            original = copy.deepcopy(document)
            first, second = registry.plan(document), registry.plan(document)
            self.assertEqual(first, second)
            self.assertEqual(document, original)
            self.assertEqual(json.loads(json.dumps(first)), first)

    def test_profile_is_complete_fixed_and_contains_no_authored_text(self):
        prepared = adaptor.plan(example())
        config = dict(prepared['config'])
        self.assertEqual(len(config), len(prepared['config']))
        self.assertEqual(config['post_process'], '')
        self.assertEqual(config['gcode_substitutions'], '')
        self.assertEqual(config['binary_gcode'], '0')
        self.assertEqual(config['arc_fitting'], 'disabled')
        self.assertEqual(config['start_gcode'], 'G21\\nG90\\nM83\\nG28\\nG92 E0')
        self.assertEqual(config['bed_shape'], '0x0,250x0,250x210,0x210')
        self.assertEqual(config['first_layer_temperature'], '215')
        self.assertEqual(config['temperature'], '210')
        self.assertEqual(config['fill_density'], '20%')
        self.assertEqual(config['external_perimeter_extrusion_width'], '0.45')
        self.assertEqual(prepared['placement'], {'centre_mm': [125, 105]})
        self.assertEqual(prepared['scale'], 1)
        self.assertEqual(adaptor.plan(example('inch', INCH_BOX))['scale'], 25.4)
        rendered = profile.ini(prepared['config']).decode('ascii')
        self.assertNotIn(str(BOX), rendered)
        self.assertTrue(rendered.endswith('gap_fill_enabled = 1\n'))

    def test_semantic_rejections_are_located_before_native_work(self):
        cases = [
            ('/model/file', 'relative/part.stl', 'INVALID_RESOURCE', '$.model.file'),
            ('/model/file', '/models/part.obj', 'INVALID_RESOURCE', '$.model.file'),
            ('/model/sha256', 'A'*64, 'INVALID_RESOURCE', '$.model.sha256'),
            ('/print/layerHeight_mm', 0.33, 'INVALID_PROFILE', '$.print.layerHeight_mm'),
            ('/print/firstLayerHeight_mm', 0.4, 'INVALID_PROFILE', '$.print.firstLayerHeight_mm'),
            ('/print/extrusionWidth_mm', 0.35, 'INVALID_PROFILE', '$.print.extrusionWidth_mm'),
            ('/print/extrusionWidth_mm', 0.81, 'INVALID_PROFILE', '$.print.extrusionWidth_mm'),
        ]
        for pointer, value, code, location in cases:
            document = example()
            _, section, key = pointer.split('/')
            document[section][key] = value
            self.assertFault(code, lambda: adaptor.plan(document), location)
        document = example()
        document['print'].update(infillDensity_percent=100, infillPattern='gyroid')
        self.assertFault('INVALID_PROFILE', lambda: adaptor.plan(document), '$.print.infillPattern')
        document = example()
        document['placement'] = {'centre_mm': [260, 100]}
        self.assertFault('MODEL_OUT_OF_BOUNDS', lambda: adaptor.plan(document), '$.placement.centre_mm')
        document = example('petg')
        document['requirements'].append(dict(document['requirements'][0]))
        self.assertFault('INVALID_REQUIREMENT', lambda: adaptor.plan(document), '$.requirements[1].name')

    def test_schema_bounds_and_unknown_keys_fail_with_structured_faults(self):
        for mutate in (lambda d: d['material'].update(nozzleTemperature_C=400),
                       lambda d: d['printer'].update(gcodeFlavour='klipper'),
                       lambda d: d['material'].update(type='Nylon'),
                       lambda d: d['print'].update(perimeters=1.5),
                       lambda d: d['printer'].update(bedSize_mm=[250])):
            document = example()
            mutate(document)
            self.assertFault('INVALID_ARGUMENT', lambda: adaptor.plan(document))
        document = example()
        document['print']['startGcode'] = 'G28'
        self.assertFault('UNKNOWN_ARGUMENT', lambda: adaptor.plan(document))
        document = example()
        document['postProcess'] = 'script'
        self.assertFault('UNKNOWN_ARGUMENT', lambda: adaptor.plan(document))
        del document['postProcess']
        del document['material']
        self.assertFault('MISSING_ARGUMENT', lambda: adaptor.plan(document))

    def test_schema_matches_planner_contract(self):
        schema = registry.schema('schemaxis.prusaslicer/1') if hasattr(registry, 'schema') else adaptor.schema()
        text = json.dumps(schema)
        for key in ('bedSize_mm', 'firstLayerNozzleTemperature_C', 'infillPattern', 'centre_mm', 'sha256'):
            self.assertIn(key, text)
        self.assertEqual(adaptor.schema()['properties']['operation'], {'const': 'sliceModel'})

    def test_hooks_bind_reuse_digest_and_single_thread(self):
        digest = hashlib.sha256(BOX.read_bytes()).hexdigest()
        self.assertEqual(adaptor.reusableInputs(example()), {str(BOX): digest})
        document = example()
        document['model']['sha256'] = '0'*64
        self.assertFault('INPUT_DIGEST_MISMATCH', lambda: adaptor.reusableInputs(document), '$.model.sha256')
        self.assertEqual(adaptor.resources(example(), {}, 'node'), {'threads': 1})
        self.assertFault('INVALID_EXECUTION', lambda: adaptor.resources(example(), {'threads': 4}, 'node'))
        self.assertEqual(adaptor.query(example()), (['sliceModel'], {}))


class ModelTests(unittest.TestCase):
    def test_native_info_accounts_for_six_decimal_rounding_in_raw_stl_units(self):
        def output(mesh, **changes):
            values = {**{'size_'+a: format(v, '.6f') for a, v in zip('xyz', mesh['size'])},
                      **{'min_'+a: format(v, '.6f') for a, v in zip('xyz', mesh['minimum'])},
                      'volume': format(mesh['volume'], '.6f'), 'number_of_facets': mesh['triangles'],
                      'manifold': 'yes', 'number_of_parts': 1, **changes}
            return '\n'.join(f'{key} = {value}' for key, value in values.items()).encode()

        # A physical 5 x 5 x 1 mm box authored in inches has a raw volume near
        # 0.0015255936 in^3; native --info prints 0.001526 (beyond relative 1e-4).
        inch = triangles(binary(box_triangles(5/25.4, 5/25.4, 1/25.4)))
        self.assertAlmostEqual(adaptor.native_info(output(inch), inch)['volume'], 0.001526)
        self.assertGreater(abs(0.001526-inch['volume']), 1e-4*inch['volume'])
        with self.assertRaises(SchemaxisError):
            adaptor.native_info(output(inch, volume='0.001527'), inch)

        # At smaller raw extents the same six-decimal floor applies to both
        # size and minimum coordinates, even when translated away from zero.
        moved = [tuple(tuple(v+0.00000049 for v in vertex) for vertex in tri)
                 for tri in box_triangles(0.01000049, 0.01100049, 0.01200049)]
        small = triangles(binary(moved))
        adaptor.native_info(output(small), small)
        for field in ('size_x', 'min_x', 'volume'):
            value = small['size'][0] if field == 'size_x' else small['minimum'][0] if field == 'min_x' else small['volume']
            allowance = (1e-4*small['volume'] if field == 'volume' else 1e-5*max(small['size'])) + 0.5e-6
            with self.subTest(field=field), self.assertRaises(SchemaxisError):
                adaptor.native_info(output(small, **{field: repr(value+1.01*allowance)}), small)
            for nonfinite in ('nan', 'inf', '-inf'):
                with self.subTest(field=field, value=nonfinite), self.assertRaises(SchemaxisError):
                    adaptor.native_info(output(small, **{field: nonfinite}), small)

    def test_analytic_fixtures(self):
        mesh = triangles(BOX.read_bytes())
        self.assertEqual((mesh['encoding'], mesh['triangles'], mesh['vertices']), ('ascii', 12, 8))
        self.assertEqual(mesh['size'], [24, 16, 10])
        self.assertAlmostEqual(mesh['volume'], 3840, places=9)
        self.assertAlmostEqual(mesh['area'], 2*(24*16 + 24*10 + 16*10), places=9)
        inch = adaptor.analyse_model(adaptor.plan(example('inch', INCH_BOX)), INCH_BOX.read_bytes())
        self.assertAlmostEqual(inch['volume'], 0.24, places=9)
        self.assertAlmostEqual(inch['volume_mm3'], 0.24*25.4**3, places=6)
        for actual, expected in zip(inch['size_mm'], (25.4, 15.24, 10.16)):
            self.assertAlmostEqual(actual, expected, places=5)

    def test_binary_matches_ascii_and_defects_are_rejected(self):
        tris = box_triangles()
        mesh = triangles(binary(tris))
        self.assertEqual(mesh['encoding'], 'binary')
        self.assertAlmostEqual(mesh['volume'], 3840, places=3)
        defects = {'open': tris[:-1], 'inverted': [(t[0], t[2], t[1]) for t in tris],
                   'duplicate': tris + [tris[0]], 'degenerate': tris + [((0, 0, 0), (1, 1, 1), (2, 2, 2))]}
        for name, mesh_triangles in defects.items():
            with self.subTest(name), self.assertRaises(ValueError):
                triangles(binary(mesh_triangles))
        for text in (b'solid x\nendsolid x\n', b'not an stl', b'solid x\n facet normal 0 0 1\n outer loop\n vertex 0 0 nan\n'):
            with self.assertRaises(ValueError):
                triangles(text)

    def test_ascii_trailing_geometry_shells_and_translation(self):
        text = BOX.read_bytes()
        self.assertEqual(triangles(text.replace(b'endsolid schemaxis_box_24x16x10_mm', b'endsolid'))['triangles'], 12)
        # A second solid or facets after endsolid would be ignored geometry.
        for suffix in (text, b'solid second\n', text.split(b'  endfacet\n', 1)[0] + b'  endfacet\n'):
            with self.subTest(suffix[:20]), self.assertRaises(ValueError):
                triangles(text + suffix)
        moved = [tuple(tuple(c + 30 for c in v) for v in tri) for tri in box_triangles()]
        with self.assertRaises(ValueError):
            triangles(binary(box_triangles() + moved))
        far = text.decode('ascii')
        import re
        shifted = re.sub(r'vertex (\S+) (\S+) (\S+)', lambda m: 'vertex ' + ' '.join(repr(float(v) + 999000.123456) for v in m.groups()), far)
        mesh = triangles(shifted.encode('ascii'))
        self.assertAlmostEqual(mesh['volume'], 3840, delta=1e-3)
        for actual, expected in zip(mesh['size'], (24, 16, 10)):
            self.assertAlmostEqual(actual, expected, delta=1e-6)

    def test_prelaunch_model_faults_do_not_create_attempts(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary)/'prusa-slicer'
            executable.write_text('#!/bin/sh\nexit 99\n')
            executable.chmod(0o755)
            cases = []
            document = example()
            document['placement'] = {'centre_mm': [5, 105]}
            cases.append(('MODEL_OUT_OF_BOUNDS', document))
            document = example('inch', INCH_BOX)
            document['printer']['maxPrintHeight_mm'] = 10
            cases.append(('MODEL_OUT_OF_BOUNDS', document))
            document = example()
            document['model']['sha256'] = '1'*64
            cases.append(('INPUT_DIGEST_MISMATCH', document))
            document = example()
            document['model']['file'] = str(Path(temporary)/'missing.stl')
            cases.append(('INVALID_RESOURCE', document))
            broken = Path(temporary)/'open.stl'
            broken.write_bytes(binary(box_triangles()[:-1]))
            document = example()
            document['model']['file'] = str(broken)
            cases.append(('INVALID_MODEL', document))
            for index, (code, document) in enumerate(cases):
                target = Path(temporary)/f'run-{index}'
                with self.subTest(code), self.assertRaises(SchemaxisError) as caught:
                    adaptor.run(document, target, executable=str(executable), timeout=30)
                self.assertEqual(caught.exception.fault.code, code)
                self.assertFalse(target.exists())
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.run(example(), Path(temporary)/'none', executable='relative/prusa-slicer')
            self.assertEqual(caught.exception.fault.code, 'INTERPRETER_NOT_FOUND')


GCODE = b"""; generated by PrusaSlicer 2.9.6+test on 2026-10-16 at 00:00:00 UTC
G21
G90
M83
G28
G92 E0
M140 S65
M190 S65
M109 S215
M107
G1 Z.2 F720
G1 X10 Y10 F9000
G1 E.8 F2100
G1 X20 Y10 E1 F1200
G1 X20 Y20 E1
G1 E-.8 F2100
;LAYER_CHANGE
;Z:.4
M104 S210
M140 S60
M106 S255
G1 Z.4 F720
G1 X10 Y10 F9000
G1 E.8 F2100
G1 X20 Y10 E.5 F2400
M104 S0
M140 S0
M107
M84
; filament used [mm] = 2.50
; filament used [cm3] = 0.01
; filament used [g] = 0.01
; estimated printing time (normal mode) = 1m 2s
; estimated first layer printing time (normal mode) = 30s

; prusaslicer_config = begin
; layer_height = 0.2
; start_gcode = G21\\nG90
; prusaslicer_config = end
"""
LIMITS = {'x': 200, 'y': 200, 'z': 12, 'e': 120, 'acceleration': 1000}


class GcodeTests(unittest.TestCase):
    def test_replay_layers_setpoints_statistics_and_configuration(self):
        replay = gcode.interpret(GCODE, LIMITS)
        self.assertEqual([layer['z_mm'] for layer in replay['layers']], [0.2, 0.4])
        first, second = replay['layers']
        self.assertEqual((first['nozzle'], first['bed'], first['fan']), ([215], [65], [0.0]))
        self.assertEqual((second['nozzle'], second['bed'], second['fan']), ([210], [60], [100.0]))
        self.assertEqual((first['min'], first['max']), ([10, 10], [20, 20]))
        self.assertEqual(first['maxFeed_mm_s'], 20)
        self.assertEqual(second['maxFeed_mm_s'], 40)
        self.assertAlmostEqual(replay['totals']['extrudedLength_mm'], 2.5)
        self.assertEqual(replay['totals']['retractions'], 1)
        self.assertEqual(replay['totals']['deretractions'], 2)
        self.assertEqual(replay['statistics']['printTime_s'], 62)
        self.assertEqual(replay['statistics']['firstLayerPrintTime_s'], 30)
        self.assertEqual(replay['config'], {'layer_height': '0.2', 'start_gcode': 'G21\\nG90'})
        self.assertEqual(replay['annotations'], [0.4])
        self.assertTrue(all(entry['beforeFirstExtrusion'] for entry in replay['waits']))
        self.assertLess(replay['totals']['kinematicLowerBound_s'], replay['totals']['accelerationUpperBound_s'])

    def test_kinematic_bounds_are_analytic(self):
        data = b'G1 F6000\nG1 X100\n'
        totals = gcode.interpret(data + b'G1 X101 E1\n', LIMITS)['totals']
        # 100 mm at 100 mm/s, then 1 mm at 100 mm/s with a=1000 mm/s^2.
        self.assertAlmostEqual(totals['kinematicLowerBound_s'], 1.01)
        self.assertAlmostEqual(totals['accelerationUpperBound_s'], 1.1 + 2*(1/1000)**0.5)
        capped = gcode.interpret(b'G1 F60000\nG1 X100\nG1 X101 E1\n', {**LIMITS, 'x': 50})['totals']
        self.assertAlmostEqual(capped['kinematicLowerBound_s'], 101/50)

    def test_policy_violations_are_rejected(self):
        for text in (b'G2 X1 Y1 I1 J0 F100\n', b'G20\n', b'T1\n', b'G1 F100\nG1 X1 Z1 E1\n',
                     b'G1 X1 Y1\n', b'M104 S900\n', b'G1 F100 F200\n', b'; prusaslicer_config = begin\n',
                     b'G1 F100\nG1 Z1\nG1 X1 E1\nG1 Z.5\nG1 X2 E2\n', b'\xff\n', b'G1 F100\nG1 X1 E-1\n',
                     b'M106 S300\n', b'G1 F100\nG1 X1\nG28\n', b'G92 X0\n', b'G28\nG28\n', b'G28 X0\n',
                     b'M201 X1000\n', b'M84 S10\n', b'M83 E1\n', b'M107 P1\n'):
            with self.subTest(text), self.assertRaises(gcode.GcodeError):
                gcode.interpret(text + b'G1 F100\nG1 Z.2\nG1 X5 E1\n', LIMITS)
        with self.assertRaises(gcode.GcodeError):
            gcode.interpret(b'G1 F100\nG1 X5\n', LIMITS)
        with self.assertRaises(gcode.GcodeError):
            gcode.seconds('1 hour')

    def test_configuration_comparison(self):
        self.assertTrue(profile.same('0.2', '0.2'))
        self.assertTrue(profile.same('20%', '20%'))
        self.assertTrue(profile.same('215', '215.0'))
        self.assertFalse(profile.same('20%', '20'))
        self.assertFalse(profile.same('marlin2', 'klipper'))
        self.assertEqual(profile.number(-0.0), '0')
        with self.assertRaises(ValueError):
            profile.number(float('nan'))


class MetadataTests(unittest.TestCase):
    def test_capabilities_cases_and_readiness_examples(self):
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        catalogue = CapabilityCatalogue()
        report = check_cases(catalogue, 'prusaslicer')
        self.assertTrue(report['complete'], report)
        bundle = json.loads((ROOT/'src/schemaxis/adaptors/prusaslicer/readiness.json').read_text())
        route = bundle['routes']['schemaxis.prusaslicer/1']
        for item in route['examples']:
            document = item.get('document') or json.loads((ROOT/item['reference']).read_text())
            if item.get('expect') == 'invalid':
                with self.assertRaises(SchemaxisError) as caught:
                    registry.plan(document)
                self.assertEqual(caught.exception.fault.code, item['fault'])
            else:
                registry.plan(document)
        self.assertGreaterEqual(len(route['development']['cases']), 2)
        for case in route['development']['cases']:
            for resource in case.get('resources', {}).values():
                self.assertTrue((ROOT/resource).is_file())


@unittest.skipUnless(os.environ.get('PRUSASLICER_EXECUTABLE'), 'native PrusaSlicer acceptance runs in tools/qualify_prusaslicer.py')
class NativeTests(unittest.TestCase):
    def test_run_verify_and_tamper(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)/'run'
            adaptor.run(example(), target, executable=os.environ['PRUSASLICER_EXECUTABLE'], timeout=300)
            verified = adaptor.verify(target)
            self.assertEqual(verified['native']['layers']['count'], 50)
            gcode_path = target/'model.gcode'
            original = gcode_path.read_bytes()
            gcode_path.write_bytes(original.replace(b'M109 S215', b'M109 S230', 1))
            with self.assertRaises(SchemaxisError):
                adaptor.verify(target)
            gcode_path.write_bytes(original)
            adaptor.verify(target)


if __name__ == '__main__':
    unittest.main()
