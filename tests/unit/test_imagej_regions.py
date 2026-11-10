"""ImageJ measureRegions: host planning, exact oracle, refusals before native assignment and native-boundary tamper."""
import copy
import hashlib
import json
import math
from pathlib import Path
import os
import struct
import sys
import tempfile
import threading
import unittest
from fractions import Fraction
from unittest import mock

from schemaxis.adaptors import registry
from schemaxis.adaptors.imagej import adaptor, images, regions
from schemaxis import dispatch
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail

ROOT = Path(__file__).resolve().parents[2]
SERIES = ROOT/'examples/schemaxis/fixtures/imagej/series'
JAVA_STAND_IN = sys.executable  # never reached: every refusal below precedes native assignment
JAR_STAND_IN = None


def fault(action):
    try:
        action()
    except SchemaxisError as error:
        return error.fault
    raise AssertionError('expected a structured fault')


def pgm(width, height, value=0, maximum=255):
    if maximum == 255: raster = bytes([value])*(width*height)
    else: raster = struct.pack(f'>{width*height}H', *([value]*(width*height)))
    return b'P5\n%d %d\n%d\n' % (width, height, maximum)+raster


def document(directory=SERIES, count=4, **changes):
    result = {'version': 'schemaxis.imagej/1', 'operation': 'measureRegions',
              'frames': [{'id': 'T%d' % i, 'image': str(Path(directory)/('ramp8-t%d.pgm' % i)), 'timeSeconds': 30.0*i} for i in range(count)],
              'regions': [{'id': 'core', 'x': 2, 'y': 1, 'width': 4, 'height': 3}, {'id': 'edge', 'x': 8, 'y': 5, 'width': 4, 'height': 3},
                          {'id': 'nested', 'x': 3, 'y': 2, 'width': 2, 'height': 1}],
              'calibration': {'pixelWidth': 0.5, 'pixelHeight': 2, 'unit': 'um'}}
    result.update(changes)
    return result


def decoded(frames=4, name='ramp8-t%d.pgm'):
    return [images.decode((SERIES/(name % i)).read_bytes(), Path(name % i).suffix) for i in range(frames)]


def native_lines(prepared, measured):
    """Honest native measurement rows (ImageJ column order) built from an exact enumeration."""
    width, height = prepared['calibration']['pixelWidth'], prepared['calibration']['pixelHeight']
    lines = [regions.NATIVE_COLUMNS]
    for frame, row in enumerate(measured):
        for index, (facts, region) in enumerate(zip(row, prepared['regions'])):
            count = facts['pixelCount']
            lines.append(','.join([str(frame), str(index), repr(float(region['x']*width)), repr(float(region['y']*height)), repr(float(region['width']*width)),
                                   repr(float(region['height']*height)), str(count), repr(float(Fraction(count)*Fraction(width)*Fraction(height))),
                                   repr(float(Fraction(facts['sum'], count))), repr(float(facts['minimum'])), repr(float(facts['maximum']))]))
    return lines


class FakeNative:
    """Stands in for the shared native runner: writes the files a faithful ImageJ run would, from the exact enumeration."""
    def __init__(self, prepared, captured, jar, hook=None):
        self.prepared, self.hook, self.stages = prepared, hook, []
        self.decoded = regions.decode(prepared, captured)
        self.measured = regions.oracle(prepared, self.decoded)
        self.captured, self.jar = captured, hashlib.sha256(Path(jar).read_bytes()).hexdigest()

    def readback(self, stage):
        prepared, calibration = self.prepared, self.prepared['calibration']
        unit = ','.join(str(ord(char)) for char in prepared['nativeUnit'])
        lines = [('stage', stage), ('imagej', '1.54t'), ('java', '25.0.4.1'), ('jarSha256', self.jar), ('frames', len(prepared['frames'])),
                 ('regions', len(prepared['regions'])), ('stackSize', len(prepared['frames'])), ('pixelWidth', float(calibration['pixelWidth'])),
                 ('pixelHeight', float(calibration['pixelHeight'])), ('unit', unit), ('yUnit', unit), ('origin', '0.0,0.0')]
        for index, (image, data) in enumerate(zip(self.decoded, self.captured)):
            lines += [(f'frame.{index}.{key}', value) for key, value in
                      (('sha256', hashlib.sha256(data).hexdigest()), ('width', image['width']), ('height', image['height']), ('bitDepth', image['bitDepth']),
                       ('stackSize', 1), ('invertedLut', 'false'), ('densityCalibrated', 'false'), ('fileCalibration', '1.0,1.0,112,105,120,101,108'))]
        lines += [(f'label.{index}', frame['id']) for index, frame in enumerate(prepared['frames'])]
        lines += [(f'region.{index}', f"{r['id']},{r['x']},{r['y']},{r['width']},{r['height']},Rectangle") for index, r in enumerate(prepared['regions'])]
        return ''.join(f'{key}={value}\n' for key, value in lines)

    def __call__(self, command, directory, stage, timeout, environment=None):
        directory = Path(directory)
        if dispatch.cancellation_requested(): fail('RUNNER_CANCELLED', 'execution cancelled before dispatch')
        if timeout <= 0: fail('RUNNER_TIMED_OUT', 'native job exhausted its total timeout', stage)
        self.stages.append(stage)
        if self.hook: self.hook('before', stage)
        (directory/(stage+'.stdout')).write_text(''); (directory/(stage+'.stderr')).write_text('')
        if stage == 'java-version': (directory/'java-version.stderr').write_text('openjdk version "25.0.4.1" 2026-01-01\n')
        else:
            name = 'native' if stage == 'measure' else 'reopen'
            (directory/(name+'-measurements.csv')).write_text('\n'.join(native_lines(self.prepared, self.measured))+'\n')
            (directory/(stage+'-readback.txt')).write_text(self.readback(stage))
        atomic_json(directory/(stage+'-submission.json'), {'exitCode': 0, 'nativeCommand': list(map(str, command))})
        if self.hook: self.hook('after', stage)
        return None


class FakeRun(unittest.TestCase):
    """Complete host-only region runs through the real regions.run with the native runner replaced."""
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(); self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.jar = self.root/'ij.jar'; self.jar.write_bytes(b'not a jar')
        self.document = document()
        self.prepared = regions.plan(self.document)
        self.captured = [(SERIES/('ramp8-t%d.pgm' % i)).read_bytes() for i in range(4)]
        self.skew, self.cancel = [0.0], threading.Event()

    def run_with(self, name, hook=None, timeout=60):
        fake = FakeNative(self.prepared, self.captured, self.jar, hook)
        clock = mock.Mock(); clock.monotonic = lambda: __import__('time').monotonic()+self.skew[0]
        target = self.root/name
        with mock.patch.object(regions, 'execute', fake), mock.patch.object(regions, 'time', clock), dispatch.allocation({'threads': 1, 'ranks': 1}, self.cancel):
            try: result = regions.run(self.document, target, executable=sys.executable, jar=str(self.jar), timeout=timeout)
            except SchemaxisError as error: return target, fake, error.fault
        return target, fake, result

    def failed(self, target):
        stored = json.loads((target/'result.json').read_text())
        self.assertEqual((stored['status'], stored['verified']), ('failed', False))
        found = fault(lambda: regions.verify(target))
        self.assertEqual((found.code, found.location), ('INCOMPLETE_EXECUTION', 'result.json'))
        return stored['fault']


class RegionsLifecycleHostTests(FakeRun):
    """measureRegions has its own deadline and cancellation checks; drive them here, not the particle kit."""
    def test_honest_fake_run_verifies_and_pins_the_stage_order(self):
        target, fake, result = self.run_with('honest')
        self.assertEqual((result['status'], result['verified'], result['records']), ('succeeded', True, 12))
        self.assertEqual(fake.stages, ['java-version', 'measure', 'reopen'])
        self.assertTrue(regions.verify(target)['verified'])

    def test_exhausted_deadline_before_launch_and_before_the_measure_stage(self):
        target, fake, found = self.run_with('t0', timeout=1e-9)
        self.assertEqual((found.code, found.location, fake.stages), ('RUNNER_TIMED_OUT', 'java-version', []))
        self.assertEqual(self.failed(target)['code'], 'RUNNER_TIMED_OUT')
        target, fake, found = self.run_with('t1', hook=lambda when, stage: self.skew.__setitem__(0, 1000.0) if (when, stage) == ('after', 'java-version') else None)
        self.assertEqual((found.code, found.message, found.location, fake.stages), ('RUNNER_TIMED_OUT', 'native job exhausted its total timeout', 'measure', ['java-version']))
        self.assertEqual(self.failed(target)['location'], 'measure')

    def test_runner_timeout_during_measure_and_reopen_leaves_no_publication(self):
        for stage, started in (('measure', ['java-version', 'measure']), ('reopen', ['java-version', 'measure', 'reopen'])):
            def hook(when, current, stage=stage):
                if (when, current) == ('before', stage): fail('RUNNER_TIMED_OUT', 'native execution did not complete', '/work/.dispatch/%s/replay.py' % stage)
            target, fake, found = self.run_with('during-'+stage, hook)
            self.assertEqual((found.code, fake.stages), ('RUNNER_TIMED_OUT', started))
            self.assertEqual(self.failed(target)['code'], 'RUNNER_TIMED_OUT')
            self.assertFalse((target/'region-measurements.csv').exists()); self.assertFalse((target/'region-measurements.json').exists())

    def test_deadline_exhausted_after_verification_is_not_a_success(self):
        target, fake, found = self.run_with('late', hook=lambda when, stage: self.skew.__setitem__(0, 1000.0) if (when, stage) == ('after', 'reopen') else None)
        self.assertEqual((found.code, found.message, found.location), ('RUNNER_TIMED_OUT', 'region verification exhausted the total timeout', 'verification.json'))
        self.assertEqual(self.failed(target)['code'], 'RUNNER_TIMED_OUT')
        self.assertEqual(fake.stages, ['java-version', 'measure', 'reopen'])

    def test_cancellation_before_launch_before_measure_and_before_publication(self):
        self.cancel.set()
        target, fake, found = self.run_with('c0')
        self.assertEqual((found.code, fake.stages), ('RUNNER_CANCELLED', [])); self.failed(target)
        self.cancel.clear()
        target, fake, found = self.run_with('c1', hook=lambda when, stage: self.cancel.set() if (when, stage) == ('after', 'java-version') else None)
        self.assertEqual((found.code, found.message, found.location, fake.stages),
                         ('RUNNER_CANCELLED', 'region measurement cancelled before the measure stage', 'measure', ['java-version']))
        self.failed(target); self.cancel.clear()
        target, fake, found = self.run_with('c2', hook=lambda when, stage: self.cancel.set() if (when, stage) == ('after', 'reopen') else None)
        self.assertEqual((found.code, found.message, found.location), ('RUNNER_CANCELLED', 'region publication cancelled', 'verification.json'))
        self.assertEqual(self.failed(target)['code'], 'RUNNER_CANCELLED')


class PreciseLocationTests(FakeRun):
    """Config, table, summary, receipt and stage-readback faults name the retained file and field, never the generic root."""
    def setUp(self):
        super().setUp()
        self.target, _, result = self.run_with('honest'); self.assertTrue(result['verified'])

    def mutate(self, name, old, new):
        """Change one retained file, refresh every ordinary digest (so only a semantic check can object), verify, then restore."""
        saved = {path: path.read_bytes() for path in self.target.iterdir() if path.is_file()}
        try: return self._mutate(name, old, new)
        finally:
            for path, data in saved.items(): path.write_bytes(data)

    def _mutate(self, name, old, new):
        path = self.target/name; text = path.read_text(); self.assertIn(old, text); path.write_text(text.replace(old, new, 1))
        receipt = json.loads((self.target/'verification.json').read_text())
        prepared = regions.plan(json.loads((self.target/'authored.json').read_text()))
        receipt['evidence'] = {n: hashlib.sha256((self.target/n).read_bytes()).hexdigest() for n in regions.evidence_names(prepared)}
        receipt['artifacts'] = [{**a, 'sha256': hashlib.sha256((self.target/Path(a['file']).name).read_bytes()).hexdigest()} for a in receipt['artifacts']]
        (self.target/'verification.json').write_text(json.dumps(receipt))
        return fault(lambda: regions.verify(self.target))

    def expect(self, found, message, location):
        self.assertEqual((found.code, found.message, found.location), ('VERIFICATION_FAILED', message, location), found.to_dict())
        self.assertNotEqual(found.location, '$')

    def test_configuration_table_summary_and_receipt(self):
        self.expect(self.mutate('series.spec', 'region core 2 1 4 3', 'region core 2 1 4 2'),
                    'series specification differs from the authored frames and regions', 'series.spec')
        self.expect(self.mutate('region-measurements.csv', 'T0,core,0.0,12,12,', 'T0,core,0.0,13,12,'),
                    'published region table differs from verified native measurements', 'region-measurements.csv')
        self.expect(self.mutate('region-measurements.json', '"pixelCount": 12', '"pixelCount": 13'),
                    'summary differs from independently checked measurements', 'region-measurements.json')

    def test_stage_readback_names_its_file(self):
        self.expect(self.mutate('measure-readback.txt', 'region.1=edge,8,5,4,3,Rectangle', 'region.1=edge,8,5,4,4,Rectangle'),
                    'native rectangle readback differs from the declared region in the measure stage', 'measure-readback.txt/region.1')
        self.expect(self.mutate('reopen-readback.txt', 'label.2=T2', 'label.2=T7'),
                    'native frame label differs from the declared frame identifier in the reopen stage', 'reopen-readback.txt/label.2')
        self.expect(self.mutate('reopen-readback.txt', 'frame.3.sha256=', 'frame.3.sha256=f'), 'native stage consumed different frame bytes', 'reopen-readback.txt/frame.3.sha256')

    def test_jar_hash_and_file_calibration_are_cross_checked(self):
        self.expect(self.mutate('measure-readback.txt', 'jarSha256=', 'jarSha256=0'),
                    'the ImageJ jar the native process loaded differs from the jarSha256 recorded in runtime.json', 'measure-readback.txt/jarSha256')
        self.expect(self.mutate('reopen-readback.txt', 'frame.0.fileCalibration=1.0,', 'frame.0.fileCalibration=2.0,'),
                    'ImageJ reports a calibration stored in a file that carries none', 'reopen-readback.txt/frame.0.fileCalibration')

    def test_receipt_membership_and_digest_paths(self):
        receipt = json.loads((self.target/'verification.json').read_text()); original = json.dumps(receipt)
        receipt['artifacts'].pop(); (self.target/'verification.json').write_text(json.dumps(receipt))
        self.expect(fault(lambda: regions.verify(self.target)), 'verification receipt publication membership or digests differ from the retained publications', 'verification.json/artifacts')
        (self.target/'verification.json').write_text(original)
        (self.target/'verification.json').write_text(original)
        (self.target/'measure.stdout').write_text('x')
        self.expect(fault(lambda: regions.verify(self.target)), 'retained evidence digest differs from the verification receipt', 'verification.json/evidence/measure.stdout')


class PlanningTests(unittest.TestCase):
    def test_plan_is_deterministic_and_complete(self):
        prepared = regions.plan(document())
        self.assertEqual(prepared, regions.plan(copy.deepcopy(document())))
        self.assertEqual((prepared['records'], prepared['nativeUnit'], prepared['pixelArea']), (12, 'µm', 1.0))
        self.assertEqual(prepared['columns'][:5], ['frame', 'region', 'timeSeconds', 'pixelCount', 'area_um2'])
        self.assertEqual([f['file'] for f in prepared['frames']], ['frame-01.pgm', 'frame-02.pgm', 'frame-03.pgm', 'frame-04.pgm'])
        self.assertEqual(registry.plan(document())['operation'], 'measureRegions')
        self.assertEqual(adaptor.query(document()), (['measureRegions'], {}))
        self.assertEqual(adaptor.resources(document(), {}, 'series'), {'threads': 1})
        self.assertEqual(fault(lambda: adaptor.resources(document(), {'threads': 2}, 'series')).code, 'INVALID_EXECUTION')

    def test_legacy_particle_plan_is_unchanged(self):
        prepared = adaptor.plan({'version': 'schemaxis.imagej/1', 'operation': 'analyzeParticles', 'image': '/x/a.pgm',
                                 'calibration': {'pixelWidth': 1, 'pixelHeight': 1, 'unit': 'um'}, 'threshold': {'lower': 1, 'upper': 9}})
        self.assertEqual(prepared['operation'], 'analyzeParticles')
        self.assertEqual(fault(lambda: adaptor.plan({'version': 'schemaxis.imagej/1', 'operation': 'macro'})).code, 'UNKNOWN_FILTER')

    def refused(self, code, mutate, location=None):
        value = document(); mutate(value)
        found = fault(lambda: regions.plan(value))
        self.assertEqual(found.code, code, found.to_dict())
        if location: self.assertEqual(found.location, location)

    def test_identifiers_times_and_shape_are_refused_with_locations(self):
        self.refused('DUPLICATE_FRAME_ID', lambda d: d['frames'][1].update(id='T0'), '$.frames[1].id')
        self.refused('DUPLICATE_REGION_ID', lambda d: d['regions'][2].update(id='core'), '$.regions[2].id')
        for bad in ('1a', 'a b', 'a.b', '', 'é', 'x'*33, '../x', 'a;b'):
            value = document(); value['frames'][0]['id'] = bad
            found = fault(lambda: regions.plan(value))
            self.assertIn(found.code, ('INVALID_IDENTIFIER', 'INVALID_ARGUMENT', 'INVALID_VALUE'), (bad, found.to_dict()))
        self.refused('NON_INCREASING_TIME', lambda d: d['frames'][1].update(timeSeconds=0.0), '$.frames[1].timeSeconds')
        self.refused('NON_INCREASING_TIME', lambda d: d['frames'][2].update(timeSeconds=10.0), '$.frames[2].timeSeconds')
        self.refused('DUPLICATE_FRAME_SOURCE', lambda d: d['frames'][1].update(image=d['frames'][0]['image']))
        self.refused('UNSUPPORTED_IMAGE', lambda d: d['frames'][0].update(image='/x/a.png'))
        self.refused('INVALID_RESOURCE', lambda d: d['frames'][0].update(image='relative.pgm'))
        self.refused('UNKNOWN_ARGUMENT', lambda d: d.update(macro='run("Measure");'))
        self.refused('UNKNOWN_ARGUMENT', lambda d: d['regions'][0].update(angle=3))
        self.refused('UNKNOWN_ARGUMENT', lambda d: d['frames'][0].update(threshold=3))

    def test_counts_values_and_calibration_are_bounded_by_the_schema(self):
        eight = lambda d: [{**d['frames'][0], 'id': 'F%d' % i, 'image': '/x/%d.pgm' % i, 'timeSeconds': float(i)} for i in range(9)]
        for name, mutate in (('one frame', lambda d: d.update(frames=d['frames'][:1])),
                             ('nine frames', lambda d: d.update(frames=eight(d))),
                             ('no regions', lambda d: d.update(regions=[])),
                             ('seventeen regions', lambda d: d.update(regions=[{'id': 'r%d' % i, 'x': 0, 'y': 0, 'width': 1, 'height': 1} for i in range(17)])),
                             ('zero width', lambda d: d['regions'][0].update(width=0)), ('negative x', lambda d: d['regions'][0].update(x=-1)),
                             ('fractional height', lambda d: d['regions'][0].update(height=2.5)), ('boolean width', lambda d: d['regions'][0].update(width=True)),
                             ('negative time', lambda d: d['frames'][0].update(timeSeconds=-1)), ('nan time', lambda d: d['frames'][0].update(timeSeconds=math.nan)),
                             ('infinite time', lambda d: d['frames'][1].update(timeSeconds=math.inf)), ('time too large', lambda d: d['frames'][1].update(timeSeconds=2e9)),
                             ('bad unit', lambda d: d['calibration'].update(unit='in')), ('zero pixel', lambda d: d['calibration'].update(pixelWidth=0)),
                             ('nan pixel', lambda d: d['calibration'].update(pixelHeight=math.nan)), ('negative pixel', lambda d: d['calibration'].update(pixelWidth=-1)),
                             ('missing calibration', lambda d: d.pop('calibration')), ('missing frames', lambda d: d.pop('frames'))):
            value = document(); mutate(value)
            with self.subTest(name=name): fault(lambda: regions.plan(value))
        eight_frames = document(count=8)
        self.assertEqual(len(regions.plan(eight_frames)['frames']), 8)
        sixteen = document(regions=[{'id': 'r%d' % i, 'x': 0, 'y': 0, 'width': 1, 'height': 1} for i in range(16)])
        self.assertEqual(regions.plan(sixteen)['records'], 64)

    def test_schema_is_a_union_of_both_operations(self):
        schema = adaptor.schema()
        self.assertEqual(len(schema['oneOf']), 2)
        self.assertEqual(schema['properties']['operation']['enum'], ['analyzeParticles', 'measureRegions'])


class OracleTests(unittest.TestCase):
    def test_analytic_ramp_rectangles_match_closed_forms(self):
        frames = decoded()
        for frame, image in enumerate(frames):
            for region, (x, y, w, h) in {'core': (2, 1, 4, 3), 'edge': (8, 5, 4, 3), 'nested': (3, 2, 2, 1), 'pixel': (11, 7, 1, 1), 'whole': (0, 0, 12, 8)}.items():
                found = regions.enumerate_region(image, {'x': x, 'y': y, 'width': w, 'height': h})
                values = [10+8*i+12*j+20*frame for j in range(y, y+h) for i in range(x, x+w)]
                self.assertEqual(found, {'pixelCount': w*h, 'sum': sum(values), 'minimum': min(values), 'maximum': max(values)}, region)
        core = regions.enumerate_region(frames[0], {'x': 2, 'y': 1, 'width': 4, 'height': 3})
        self.assertEqual((core['sum'], core['minimum'], core['maximum']), (62*12, 38, 86))

    def test_sixteen_bit_tiff_and_exclusive_edges(self):
        image = images.decode((SERIES/'ramp16-t1.tif').read_bytes(), '.tif')
        self.assertEqual(image['bitDepth'], 16)
        whole = regions.enumerate_region(image, {'x': 0, 'y': 0, 'width': 12, 'height': 8})
        self.assertEqual((whole['pixelCount'], whole['minimum'], whole['maximum']), (96, 4000, 25800))
        self.assertEqual(whole['sum'], 96*(11900+3000))
        last = regions.enumerate_region(image, {'x': 11, 'y': 7, 'width': 1, 'height': 1})
        self.assertEqual(last['sum'], 1000+900*11+1700*7+3000)

    def test_changed_pixel_changes_only_regions_containing_it(self):
        image = decoded()[0]
        changed = {**image, 'values': image['values'][:]}
        changed['values'][2*12+3] = 255  # (3, 2): inside core and nested, outside edge
        before = [regions.enumerate_region(image, r) for r in regions.plan(document())['regions']]
        after = [regions.enumerate_region(changed, r) for r in regions.plan(document())['regions']]
        self.assertNotEqual(before[0], after[0]); self.assertNotEqual(before[2], after[2]); self.assertEqual(before[1], after[1])
        self.assertEqual(after[2]['maximum'], 255)


class RefusalBeforeNativeTests(unittest.TestCase):
    """Every refusal precedes native assignment: the stand-in executable is never launched."""
    def attempt(self, value, **extra):
        with tempfile.TemporaryDirectory() as scratch:
            jar = Path(scratch)/'ij.jar'; jar.write_bytes(b'not a jar')
            target = Path(scratch)/'run'
            found = fault(lambda: regions.run(value, target, executable=JAVA_STAND_IN, jar=str(jar), timeout=30, **extra))
            self.assertFalse((target/'java-version-submission.json').exists(), 'native process was launched')
            self.assertFalse((target/'frame-01.pgm').exists(), 'native inputs were assigned')
            self.assertEqual(json.loads((target/'result.json').read_text())['status'], 'failed')
            return found

    def test_series_agreement_bounds_and_budgets(self):
        found = self.attempt(document(regions=[{'id': 'wide', 'x': 8, 'y': 0, 'width': 5, 'height': 1}]))
        self.assertEqual((found.code, found.location), ('REGION_OUT_OF_BOUNDS', '$.regions[0]'))
        found = self.attempt(document(regions=[{'id': 'tall', 'x': 0, 'y': 4, 'width': 1, 'height': 5}]))
        self.assertEqual(found.code, 'REGION_OUT_OF_BOUNDS')
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            (folder/'a.pgm').write_bytes(pgm(6, 4)); (folder/'b.pgm').write_bytes(pgm(6, 5)); (folder/'c.pgm').write_bytes(pgm(6, 4, maximum=65535))
            pair = lambda a, b: {'frames': [{'id': 'A', 'image': str(folder/a), 'timeSeconds': 0}, {'id': 'B', 'image': str(folder/b), 'timeSeconds': 1}],
                                 'regions': [{'id': 'r', 'x': 0, 'y': 0, 'width': 2, 'height': 2}]}
            found = self.attempt(document(**pair('a.pgm', 'b.pgm')))
            self.assertEqual((found.code, found.location), ('SERIES_MISMATCH', '$.frames[1].image'))
            found = self.attempt(document(**pair('a.pgm', 'c.pgm')))
            self.assertEqual((found.code, found.observed['expected'], found.observed['observed']), ('SERIES_MISMATCH', [6, 4, 8], [6, 4, 16]))
            (folder/'bad.pgm').write_bytes(b'P5\n6 4\n255\nshort')
            self.assertEqual(self.attempt(document(**pair('a.pgm', 'bad.pgm'))).code, 'INVALID_IMAGE')
            self.assertEqual(self.attempt(document(**pair('a.pgm', 'missing.pgm'))).code, 'RESOURCE_NOT_FOUND')
            # Aggregate pixel budget: 5 planes of 1000x1000 pass the per-image limit but exceed 4194304 pixels together.
            for index in range(5): (folder/('big%d.pgm' % index)).write_bytes(pgm(1000, 1000, index))
            big = {'frames': [{'id': 'B%d' % i, 'image': str(folder/('big%d.pgm' % i)), 'timeSeconds': float(i)} for i in range(5)],
                   'regions': [{'id': 'r', 'x': 0, 'y': 0, 'width': 10, 'height': 10}]}
            found = self.attempt(document(**big))
            self.assertEqual((found.code, found.location), ('RESOURCE_LIMIT', '$.frames'))
            self.assertEqual(found.observed['observedPixels'], 5000000)
            # Region-pixel visit budget: 8 frames x 16 rectangles of 500x500 = 32M visits.
            for index in range(8): (folder/('m%d.pgm' % index)).write_bytes(pgm(500, 500, index))
            many = {'frames': [{'id': 'M%d' % i, 'image': str(folder/('m%d.pgm' % i)), 'timeSeconds': float(i)} for i in range(8)],
                    'regions': [{'id': 'r%d' % i, 'x': 0, 'y': 0, 'width': 500, 'height': 500} for i in range(16)]}
            found = self.attempt(document(**many))
            self.assertEqual((found.code, found.location, found.observed['observedVisits']), ('RESOURCE_LIMIT', '$.regions', 32000000))

    def test_density_calibrated_or_unreadable_inputs_are_refused_by_the_shared_reader(self):
        with tempfile.TemporaryDirectory() as scratch:
            link = Path(scratch)/'link.pgm'; link.symlink_to(SERIES/'ramp8-t0.pgm')
            value = document(); value['frames'][0]['image'] = str(link)
            self.assertEqual(self.attempt(value).code, 'INVALID_RESOURCE')

    def test_reuse_is_bound_to_every_frame_digest(self):
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            for index in range(2): (folder/('t%d.pgm' % index)).write_bytes((SERIES/('ramp8-t%d.pgm' % index)).read_bytes())
            value = document()
            value['frames'] = [{'id': 'A', 'image': str(folder/'t0.pgm'), 'timeSeconds': 0}, {'id': 'B', 'image': str(folder/'t1.pgm'), 'timeSeconds': 5}]
            before = adaptor.reusableInputs(value)
            self.assertEqual(before, {str(folder/'t0.pgm'): hashlib.sha256((SERIES/'ramp8-t0.pgm').read_bytes()).hexdigest(),
                                      str(folder/'t1.pgm'): hashlib.sha256((SERIES/'ramp8-t1.pgm').read_bytes()).hexdigest()})
            data = bytearray((folder/'t1.pgm').read_bytes()); data[-1] ^= 1; (folder/'t1.pgm').write_bytes(bytes(data))
            after = adaptor.reusableInputs(value)
            self.assertEqual(after[str(folder/'t0.pgm')], before[str(folder/'t0.pgm')]); self.assertNotEqual(after[str(folder/'t1.pgm')], before[str(folder/'t1.pgm')])
            (folder/'t0.pgm').unlink()
            self.assertIsNone(adaptor.reusableInputs(value))


class NativeBoundaryTests(unittest.TestCase):
    """Native tables are parsed and compared with exact enumeration; a refreshed digest cannot hide a semantic error."""
    def setUp(self):
        self.prepared = regions.plan(document())
        self.measured = regions.oracle(self.prepared, decoded())
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        lines = native_lines(self.prepared, self.measured)
        self.lines = lines
        self.write()

    def write(self, lines=None):
        (self.path/'native-measurements.csv').write_text('\n'.join(lines or self.lines)+'\n')

    def rows(self):
        return regions.native_rows(self.path, 'native-measurements.csv', self.prepared, self.measured)

    def test_honest_native_output_is_accepted(self):
        self.assertEqual(len(self.rows()), 12)

    def mutate(self, row, field, value):
        lines = self.lines[:]; parts = lines[row].split(','); parts[field] = value; lines[row] = ','.join(parts); self.write(lines)

    def test_every_tampered_native_statistic_is_refused(self):
        for field, value, name in ((6, '13', 'count'), (7, '12.5', 'area'), (8, '62.5', 'mean'), (9, '39.0', 'minimum'), (10, '87.0', 'maximum'),
                                   (2, '2.0', 'left'), (3, '3.0', 'top'), (4, '2.5', 'width'), (5, '6.5', 'height')):
            with self.subTest(name=name):
                self.mutate(1, field, value)
                found = fault(self.rows); self.assertEqual(found.code, 'VERIFICATION_FAILED'); self.assertIn('rows/0', found.location)
        self.write()
        self.assertEqual(len(self.rows()), 12)

    def test_row_identity_order_and_count_are_refused(self):
        swapped = self.lines[:]; swapped[1], swapped[2] = swapped[2], swapped[1]; self.write(swapped)
        self.assertEqual(fault(self.rows).code, 'VERIFICATION_FAILED')
        self.write(self.lines[:-1]); self.assertEqual(fault(self.rows).code, 'VERIFICATION_FAILED')
        self.write([self.lines[0].replace('Mean', 'Median')]+self.lines[1:]); self.assertEqual(fault(self.rows).code, 'VERIFICATION_FAILED')
        self.mutate(2, 0, '1'); self.assertEqual(fault(self.rows).code, 'VERIFICATION_FAILED')

    def test_published_csv_carries_identity_time_and_native_values(self):
        text = regions.csv_bytes(self.prepared, self.rows()).decode()
        lines = text.splitlines()
        self.assertEqual(lines[0], 'frame,region,timeSeconds,pixelCount,area_um2,meanIntensity,minimumIntensity,maximumIntensity')
        self.assertEqual(lines[1], 'T0,core,0.0,12,12,62,38,86')
        self.assertEqual(lines[5], 'T1,edge,30.0,12,12,178,154,202')
        self.assertEqual(len(lines), 13)

    def test_semantic_faults_keep_their_message_and_a_location(self):
        with self.assertRaises(TypeError): regions.check(False, 'a location is required, never the generic root')
        found = fault(lambda: regions.check(False, 'precise semantic message', 'native-measurements.csv/rows/0', native=1))
        self.assertEqual((found.location, found.observed), ('native-measurements.csv/rows/0', {'native': 1}))

    def test_readback_requires_the_exact_fixed_field_order(self):
        names = [*regions.READBACK_FIXED, *[f'frame.{i}.{f}' for i in range(4) for f in regions.FRAME_FIELDS], *[f'label.{i}' for i in range(4)], *[f'region.{j}' for j in range(3)]]
        (self.path/'measure-readback.txt').write_text(''.join(f'{name}=x\n' for name in names))
        self.assertEqual(len(regions.readback(self.path, 'measure-readback.txt', self.prepared)), len(names))
        (self.path/'measure-readback.txt').write_text(''.join(f'{name}=x\n' for name in reversed(names)))
        self.assertEqual(fault(lambda: regions.readback(self.path, 'measure-readback.txt', self.prepared)).code, 'VERIFICATION_FAILED')
        (self.path/'measure-readback.txt').write_text(''.join(f'{name}=x\n' for name in names[:-1]))
        self.assertEqual(fault(lambda: regions.readback(self.path, 'measure-readback.txt', self.prepared)).code, 'VERIFICATION_FAILED')


class ProgramBoundaryTests(unittest.TestCase):
    def test_fixed_program_is_trusted_public_api_only(self):
        text = regions.PROGRAM
        for required in ('ImageStack', 'ImagePlus', 'new Roi(', 'ImageStatistics.getStatistics', 'Calibration'):
            self.assertIn(required, text)
        for forbidden in ('RoiManager', 'IJ.run', 'IJ.runMacro', 'Macro', 'forName', 'getMethod', 'setThreshold', 'Plugin', 'ScriptEngine', 'GUI'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(regions.commands('/j', '/ij.jar', Path('/d'), regions.plan(document()))['reopen'][-4:],
                         ['/d/series.spec', '0.5', '2.0', 'um'])

    def test_specification_contains_only_validated_literals(self):
        spec = regions.specification(regions.plan(document()))
        self.assertEqual(spec.splitlines()[0], 'frame T0 0.0 frame-01.pgm pgm')
        self.assertEqual(spec.splitlines()[4], 'region core 2 1 4 3')


class CaptureBoundaryTests(unittest.TestCase):
    """Duplicate sources are found by (device, inode) before capture; aggregate budgets bind before reading and before decoding."""
    def pair(self, folder, first, second):
        return {'frames': [{'id': 'A', 'image': str(first), 'timeSeconds': 0}, {'id': 'B', 'image': str(second), 'timeSeconds': 1}],
                'regions': [{'id': 'r', 'x': 0, 'y': 0, 'width': 2, 'height': 2}]}

    def test_aliases_and_hard_links_are_one_source_but_distinct_identical_files_are_not(self):
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch); (folder/'sub').mkdir()
            (folder/'a.pgm').write_bytes(pgm(6, 4, 7)); os.link(folder/'a.pgm', folder/'hard.pgm')
            (folder/'copy.pgm').write_bytes((folder/'a.pgm').read_bytes())
            for second, name in ((folder/'sub'/'..'/'a.pgm', 'dot-dot alias'), (str(folder)+'/./a.pgm', 'dot alias'), (folder/'hard.pgm', 'hard link')):
                with self.subTest(name=name):
                    prepared = regions.plan(document(**self.pair(folder, folder/'a.pgm', second)))
                    found = fault(lambda: regions.capture_series(prepared))
                    self.assertEqual((found.code, found.location, found.observed['first']), ('DUPLICATE_FRAME_SOURCE', '$.frames[1].image', 0))
            prepared = regions.plan(document(**self.pair(folder, folder/'a.pgm', folder/'copy.pgm')))
            captured = regions.capture_series(prepared)  # an unchanged scene in two distinct files is meaningful
            self.assertEqual(captured[0], captured[1])
            self.assertEqual(len(regions.decode(prepared, captured)), 2)

    def test_aggregate_bytes_are_refused_from_fstat_before_any_read(self):
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            for index in range(3):
                with open(folder/('big%d.pgm' % index), 'wb') as stream: stream.truncate(12*1024*1024)  # sparse, under the 16 MiB per-image limit
            value = {'frames': [{'id': 'B%d' % i, 'image': str(folder/('big%d.pgm' % i)), 'timeSeconds': float(i)} for i in range(3)],
                     'regions': [{'id': 'r', 'x': 0, 'y': 0, 'width': 1, 'height': 1}]}
            prepared = regions.plan(document(**value))
            with mock.patch.object(regions, 'read_frame', side_effect=AssertionError('a frame was read before the aggregate budget')):
                found = fault(lambda: regions.capture_series(prepared))
            self.assertEqual((found.code, found.location, found.observed['observedBytes']), ('RESOURCE_LIMIT', '$.frames', 36*1024*1024))

    def test_aggregate_pixels_and_visits_are_refused_from_headers_before_decoding(self):
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            for index in range(5): (folder/('big%d.pgm' % index)).write_bytes(pgm(1000, 1000, index))
            prepared = regions.plan(document(frames=[{'id': 'B%d' % i, 'image': str(folder/('big%d.pgm' % i)), 'timeSeconds': float(i)} for i in range(5)],
                                             regions=[{'id': 'r', 'x': 0, 'y': 0, 'width': 10, 'height': 10}]))
            captured = [(folder/('big%d.pgm' % i)).read_bytes() for i in range(5)]
            with mock.patch.object(images, 'decode', side_effect=AssertionError('decoded before the aggregate budget')):
                found = fault(lambda: regions.decode(prepared, captured))
                self.assertEqual((found.code, found.location, found.observed['observedPixels']), ('RESOURCE_LIMIT', '$.frames', 5000000))
                for index in range(8): (folder/('m%d.pgm' % index)).write_bytes(pgm(500, 500, index))
                prepared = regions.plan(document(frames=[{'id': 'M%d' % i, 'image': str(folder/('m%d.pgm' % i)), 'timeSeconds': float(i)} for i in range(8)],
                                                 regions=[{'id': 'r%d' % i, 'x': 0, 'y': 0, 'width': 500, 'height': 500} for i in range(16)]))
                found = fault(lambda: regions.decode(prepared, [(folder/('m%d.pgm' % i)).read_bytes() for i in range(8)]))
                self.assertEqual((found.code, found.location), ('RESOURCE_LIMIT', '$.regions'))
                # Series disagreement and out-of-bounds rectangles are also decided from headers alone.
                (folder/'a.pgm').write_bytes(pgm(6, 4)); (folder/'b.pgm').write_bytes(pgm(6, 5))
                prepared = regions.plan(document(**{'frames': [{'id': 'A', 'image': str(folder/'a.pgm'), 'timeSeconds': 0}, {'id': 'B', 'image': str(folder/'b.pgm'), 'timeSeconds': 1}],
                                                    'regions': [{'id': 'r', 'x': 0, 'y': 0, 'width': 2, 'height': 2}]}))
                self.assertEqual(fault(lambda: regions.decode(prepared, [(folder/'a.pgm').read_bytes(), (folder/'b.pgm').read_bytes()])).code, 'SERIES_MISMATCH')

    def test_headers_agree_with_the_full_decoders_for_every_fixture(self):
        for path in sorted(SERIES.iterdir()):
            image = images.decode(path.read_bytes(), path.suffix)
            self.assertEqual(regions.header(path.read_bytes(), path.suffix)[:3], (image['width'], image['height'], image['bitDepth']), path.name)
        self.assertIsNone(regions.header(b'P6\n1 1\n255\nx', '.pgm')); self.assertIsNone(regions.header(b'II*\x00\xff\xff\xff\xff', '.tif'))


class FractionalMeanTests(unittest.TestCase):
    """Native-style 8/16-bit planes whose rectangle means are non-terminating fractions, checked against closed-form Fractions."""
    F8 = staticmethod(lambda x, y, t: (29*x+53*y+17*t+11*x*y) % 256)
    F16 = staticmethod(lambda x, y, t: (4099*x+7919*y+1013*t+977*x*y) % 65536)

    def closed_form(self, formula, frame, rect):
        x, y, w, h = rect
        values = [formula(i, j, frame) for j in range(y, y+h) for i in range(x, x+w)]
        return {'pixelCount': len(values), 'sum': sum(values), 'minimum': min(values), 'maximum': max(values)}

    def test_odd_sum_three_pixel_rectangles_have_one_third_means(self):
        for name, formula, rect, frame_sums in (('frac8-t%d.pgm', self.F8, (1, 2, 3, 1), (368, 419, 470)),
                                                ('frac16-t%d.tif', self.F16, (4, 3, 3, 1), (111185, 114224, 117263))):
            for frame in range(3):
                data = (SERIES/(name % frame)).read_bytes()
                image = images.decode(data, Path(name).suffix)
                found = regions.enumerate_region(image, dict(zip(('x', 'y', 'width', 'height'), rect)))
                self.assertEqual(found, self.closed_form(formula, frame, rect))
                self.assertEqual(found['sum'], frame_sums[frame]); self.assertNotEqual(found['sum'] % 3, 0)
                mean = Fraction(found['sum'], found['pixelCount'])
                self.assertEqual(mean.denominator, 3)  # 1/3 or 2/3 beyond an integer: not exactly representable in binary or decimal
                self.assertNotEqual(Fraction(float(mean)), mean)

    def test_every_fractional_fixture_rectangle_matches_its_formula(self):
        rects = {'third': (1, 2, 3, 1), 'sevenths': (0, 2, 7, 1), 'corner': (6, 3, 3, 3), 'pixel': (8, 5, 1, 1), 'whole': (0, 0, 9, 6)}
        nonintegral = 0
        for name, formula in (('frac8-t%d.pgm', self.F8), ('frac16-t%d.tif', self.F16)):
            for frame in range(3):
                image = images.decode((SERIES/(name % frame)).read_bytes(), Path(name).suffix)
                self.assertEqual((image['width'], image['height']), (9, 6))
                for rect in rects.values():
                    found = regions.enumerate_region(image, dict(zip(('x', 'y', 'width', 'height'), rect)))
                    self.assertEqual(found, self.closed_form(formula, frame, rect))
                    nonintegral += Fraction(found['sum'], found['pixelCount']).denominator != 1
        self.assertGreaterEqual(nonintegral, 12)

    def test_native_boundary_checks_a_fractional_mean_with_exact_fractions(self):
        value = document(directory=SERIES)
        value['frames'] = [{'id': 'F%d' % t, 'image': str(SERIES/('frac8-t%d.pgm' % t)), 'timeSeconds': 5.0*t} for t in range(3)]
        value['regions'] = [{'id': 'third', 'x': 1, 'y': 2, 'width': 3, 'height': 1}, {'id': 'whole', 'x': 0, 'y': 0, 'width': 9, 'height': 6}]
        value['calibration'] = {'pixelWidth': 0.5, 'pixelHeight': 1.5, 'unit': 'um'}
        prepared = regions.plan(value)
        self.assertEqual(prepared['pixelArea'], 0.75)
        captured = [(SERIES/('frac8-t%d.pgm' % t)).read_bytes() for t in range(3)]
        measured = regions.oracle(prepared, regions.decode(prepared, captured))
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch); lines = native_lines(prepared, measured)
            (path/'n.csv').write_text('\n'.join(lines)+'\n')
            rows = regions.native_rows(path, 'n.csv', prepared, measured)
            self.assertEqual(rows[0]['mean'], 368/3); self.assertEqual(rows[0]['area'], 2.25); self.assertNotEqual(rows[0]['area'], rows[0]['pixelCount'])
            self.assertEqual(rows[1]['area'], 40.5)
            parts = lines[1].split(','); parts[8] = repr(368/3+1e-9); lines[1] = ','.join(parts)  # a 1e-9 drift is far outside the 1e-12 tolerance
            (path/'n.csv').write_text('\n'.join(lines)+'\n')
            found = fault(lambda: regions.native_rows(path, 'n.csv', prepared, measured))
            self.assertEqual((found.message, found.location), ('native measurement differs from the independent enumeration', 'n.csv/rows/0/Mean'))
            parts[8] = repr(float(Fraction(368, 3)) * (1+5e-13)); lines[1] = ','.join(parts)  # within the justified tolerance
            (path/'n.csv').write_text('\n'.join(lines)+'\n')
            self.assertEqual(len(regions.native_rows(path, 'n.csv', prepared, measured)), 6)


class StaleFixtureTests(unittest.TestCase):
    def test_generator_refuses_a_stale_or_missing_fixture(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('series_fixtures', ROOT/'tools/qualify_imagej_series_fixtures.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            for name, data in module.fixtures().items(): (folder/name).write_bytes(data)
            (folder/'frac8-t1.pgm').write_bytes(b'stale'); (folder/'ramp16-t0.tif').unlink()
            with mock.patch.object(module, 'FOLDER', folder), mock.patch.object(sys, 'argv', ['x', '--check']), \
                    mock.patch('sys.stderr') as stderr:
                self.assertEqual(module.main(), 1)
            self.assertIn('frac8-t1.pgm', ''.join(call.args[0] for call in stderr.write.call_args_list))
            self.assertIn('ramp16-t0.tif', ''.join(call.args[0] for call in stderr.write.call_args_list))


class QualifierDispatchTests(unittest.TestCase):
    """The primary qualifier must not assume one operation shape, and the committed fixtures must be the generated bytes."""
    def load(self, name):
        import importlib.util
        sys.path.insert(0, str(ROOT/'tools'))
        try:
            spec = importlib.util.spec_from_file_location(name, ROOT/'tools'/(name+'.py')); module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        finally:
            sys.path.remove(str(ROOT/'tools'))

    def test_primary_qualifier_routes_region_evidence_to_the_region_probes(self):
        primary = self.load('qualify_imagej')
        calls = []
        primary.regionsq.tamper = lambda target, report: calls.append(('regions', Path(target).name))
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch)/'regions-baseline-8bit'; target.mkdir(); (target/'region-measurements.json').write_text('{}')
            primary.tamper(target, {'negative': []})
        self.assertEqual(calls, [('regions', 'regions-baseline-8bit')])
        self.assertEqual(primary.regionsq.CASE, 'regions-baseline-8bit')

    def test_public_inspection_walks_bounded_members_and_pins_revision(self):
        primary = self.load('qualify_imagej')
        document = {'records': [{'region': 'r%d' % i, 'mean': i+1/3, 'pad': 'x'*400} for i in range(15)], 'unit': 'um^2'}

        class Client:
            def __init__(self): self.calls = []

            def call(self, method, **params):
                self.calls.append(params)
                assert method == 'inspect_resource' and params['resource_id'] == 'res'
                pointer = params.get('pointer', ''); value = document
                for token in pointer.split('/')[1:]: value = value[int(token)] if isinstance(value, list) else value[token]
                if params.get('revision') not in (None, 'rev'): raise AssertionError('revision not pinned')
                if len(json.dumps(value)) <= 600 and not params.get('offset'): return {'mode': 'value', 'value': value, 'revision': 'rev'}
                keys = sorted(value) if isinstance(value, dict) else range(len(value)); keys = list(keys); offset = params.get('offset', 0)
                items = [{'key': k, 'pointer': pointer+'/'+str(k), 'kind': 'x', **({'value': value[k]} if len(json.dumps(value[k])) <= 256 else {})}
                         for k in keys[offset:offset+12]]
                end = offset+len(items)
                return {'mode': 'members', 'container': 'object' if isinstance(value, dict) else 'array', 'items': items, 'revision': 'rev',
                        'page': {'offset': offset, 'returned': len(items), 'total': len(keys), 'nextOffset': end if end < len(keys) else None}}
        client = Client()
        walked, revision = primary.inspect_walk(client, 'res', '/records')
        self.assertEqual(walked, document['records']); self.assertEqual(revision, 'rev')
        self.assertTrue(any(call.get('offset') == 12 for call in client.calls), 'second page not followed')
        client = Client()
        checks = [{'pointer': '/records/14/mean'}, {'pointer': '/records/3/region'}, {'pointer': '/unit'}]
        observed, revision = primary.inspect_checks(client, 'res', checks)
        self.assertEqual(observed, {'/records/14/mean': 14+1/3, '/records/3/region': 'r3', '/unit': 'um^2'})
        self.assertEqual([call['pointer'] for call in client.calls], ['/records/14', '/records/3', '/unit'])  # exact bounded queries, no whole-document walk

    def test_series_fixtures_match_their_generator(self):
        generator = self.load('qualify_imagej_series_fixtures')
        for name, data in generator.fixtures().items():
            self.assertEqual((SERIES/name).read_bytes(), data, name)
        self.assertEqual(sorted(path.name for path in SERIES.iterdir()), sorted(generator.fixtures()))


if __name__ == '__main__':
    unittest.main()
