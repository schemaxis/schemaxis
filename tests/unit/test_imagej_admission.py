"""ImageJ particle contracts, independent reference model and verifier falsification."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptor_conformance import host
from schemaxis.adaptors import registry
from schemaxis.adaptors.imagej import adaptor, images
from schemaxis.capabilities import CapabilityCatalogue
from schemaxis.core.faults import SchemaxisError
from schemaxis.search_acceptance import check_cases
from schemaxis.studio_library import instantiate_item, load_library
from schemaxis.tabular import read_csv

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT/'examples/schemaxis/fixtures/imagej'


def document(name='particles', image='particles-8bit.pgm'):
    value = json.loads((ROOT/f'examples/schemaxis/imagej-{name}.json').read_text())
    value['image'] = str(FIXTURES/image)
    return value


def fault(action):
    try:
        action()
    except SchemaxisError as error:
        return error.fault
    raise AssertionError('expected a structured fault')


def analysis(edits=None, image='particles-8bit.pgm'):
    d = document(image=image)
    d.update(edits or {})
    prepared = adaptor.plan(d)
    return prepared, adaptor.reference(prepared, (FIXTURES/image).read_bytes())


class FakeNative:
    """Offline double of the fixed program's files, built from the reference model."""
    def __init__(self, mutate=None):
        self.mutate = mutate or (lambda stage, directory: None)

    def __call__(self, command, directory, stage, timeout, environment=None):
        directory = Path(directory)
        if stage == 'java-version':
            (directory/'java-version.stderr').write_text('openjdk version "21.0.1" 2026-01-01\n')
            (directory/'java-version.stdout').write_text('')
        else:
            prepared = adaptor.plan(json.loads((directory/'authored.json').read_text()))
            data = (directory/('input'+prepared['extension'])).read_bytes()
            image, result = adaptor.reference(prepared, data)
            calibration = prepared['calibration']
            unit = ','.join(str(ord(c)) for c in prepared['nativeUnit'])
            lines = [('stage', stage), ('imagej', '1.54t'), ('java', '21.0.1'), ('inputSha256', hashlib.sha256(data).hexdigest()),
                     ('width', image['width']), ('height', image['height']), ('bitDepth', image['bitDepth']), ('stackSize', 1),
                     ('invertedLut', 'false'), ('densityCalibrated', 'false'), ('pixelWidth', repr(float(calibration['pixelWidth']))),
                     ('pixelHeight', repr(float(calibration['pixelHeight']))), ('unit', unit), ('yUnit', unit), ('origin', '0.0,0.0')]
            rows = ['Area,Mean,Min,Max,X,Y,BX,BY,Width,Height'] + [
                ','.join(repr(float(v)) for v in adaptor.expected_row(prepared, image, p)) for p in result['particles']]
            count = len(result['particles'])
            if stage == 'analyse':
                header = b'P5\n%d %d\n65535\n' % (image['width'], image['height'])
                (directory/'count-mask.pgm').write_bytes(header + struct.pack(f'>{len(result["labels"])}H', *result['labels']))
                maximum = 'Infinity' if prepared['maximumPixels'] is None else repr(float(prepared['maximumPixels']))
                lines += [('lowerThreshold', repr(float(prepared['threshold']['lower']))), ('upperThreshold', repr(float(prepared['threshold']['upper']))),
                          ('options', adaptor.native_options(prepared)), ('minimumPixels', repr(float(prepared['minimumPixels']))),
                          ('maximumPixels', maximum), ('particles', count), ('maskBitDepth', 16)]
                (directory/'native-particles.csv').write_text('\n'.join(rows)+'\n')
            else:
                lines += [('maskSha256', hashlib.sha256((directory/'count-mask.pgm').read_bytes()).hexdigest()),
                          ('maskBitDepth', 16), ('particles', count)]
                (directory/'reopen-particles.csv').write_text('\n'.join(rows)+'\n')
            (directory/(stage+'-readback.txt')).write_text(''.join(f'{k}={v}\n' for k, v in lines))
            for suffix in ('.stdout', '.stderr'): (directory/(stage+suffix)).write_text('')
        (directory/(stage+'-submission.json')).write_text(json.dumps({'exitCode': 0, 'nativeCommand': list(map(str, command))}))
        self.mutate(stage, directory)


def temporary(test):
    holder = tempfile.TemporaryDirectory()
    test.addCleanup(holder.cleanup)
    return Path(holder.name)


def fake_run(test, name='particles', edits=None, mutate=None):
    temp = temporary(test)
    jar = temp/'ij.jar'; jar.write_bytes(b'not executed by the double')
    d = document(name); d.update(edits or {})
    with patch.object(adaptor, 'execute', FakeNative(mutate)):
        result = adaptor.run(d, temp/'run', executable='/bin/true', jar=str(jar))
    return temp/'run', result


class ImageJAdmissionTests(unittest.TestCase):
    def test_host_conformance(self):
        self.assertTrue(host(adaptor.VERSION)['verified'])

    def test_fixtures_are_reproducible_synthetic_targets(self):
        import subprocess, sys
        result = subprocess.run([sys.executable, str(ROOT/'tools/qualify_imagej_fixtures.py'), '--check'],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_immutable_deterministic_plans_and_bounded_rejections(self):
        d = document(); before = copy.deepcopy(d)
        self.assertEqual(adaptor.plan(d), adaptor.plan(d)); self.assertEqual(d, before)
        cases = [({'macro': 'run("Quit");'}, 'UNKNOWN_ARGUMENT', '$'),
                 ({'image': 'relative.pgm'}, 'INVALID_RESOURCE', '$.image'),
                 ({'image': '/data/image\n.pgm'}, 'INVALID_RESOURCE', '$.image'),
                 ({'image': '/data/image.png'}, 'UNSUPPORTED_IMAGE', '$.image'),
                 ({'threshold': {'lower': 200, 'upper': 100}}, 'INVALID_THRESHOLD', '$.threshold'),
                 ({'threshold': {'lower': -1, 'upper': 100}}, None, None),
                 ({'threshold': {'lower': 1.5, 'upper': 100}}, None, None),
                 ({'threshold': {'lower': True, 'upper': 100}}, None, None),
                 ({'connectivity': 'four'}, 'UNSUPPORTED_OPTION', '$.includeHoles'),
                 ({'connectivity': 'six'}, None, None),
                 ({'calibration': {'pixelWidth': 0, 'pixelHeight': 1, 'unit': 'um'}}, None, None),
                 ({'calibration': {'pixelWidth': float('nan'), 'pixelHeight': 1, 'unit': 'um'}}, None, None),
                 ({'calibration': {'pixelWidth': 1, 'pixelHeight': 1, 'unit': 'pixel'}}, None, None),
                 ({'calibration': {'pixelWidth': 1, 'pixelHeight': 1}}, None, None),
                 ({'minimumArea': 10, 'maximumArea': 5}, 'INVALID_SIZE_FILTER', '$.maximumArea'),
                 ({'minimumArea': 0.3, 'maximumArea': 0.4}, 'INVALID_SIZE_FILTER', '$.maximumArea'),
                 ({'minimumArea': -1}, None, None)]
        for edits, code, location in cases:
            bad = copy.deepcopy(d); bad.update(edits)
            with self.subTest(edits=edits):
                observed = fault(lambda: adaptor.plan(bad))
                if code: self.assertEqual((observed.code, observed.location), (code, location))

    def test_area_window_becomes_inclusive_whole_pixel_counts(self):
        d = document()
        for minimum, maximum, expected in [(0.5, None, (2, None)), (0.25, 0.25, (1, 1)), (0.3, 1.0, (2, 4)),
                                           (0.1+0.2+0.2, 0.75, (2, 3))]:
            d.update(minimumArea=minimum); d.pop('maximumArea', None)
            if maximum is not None: d['maximumArea'] = maximum
            p = adaptor.plan(d)
            self.assertEqual((p['minimumPixels'], p['maximumPixels']), expected)

    def test_reference_model_matches_analytic_geometry(self):
        prepared, (image, result) = analysis()
        counts = [p['pixelCount'] for p in result['particles']]
        self.assertEqual(counts, [20, 60, 64, 1, 72, 108, 4, 18])
        self.assertEqual(sum(counts)*prepared['pixelArea'], 86.75)
        rows = [adaptor.expected_row(prepared, image, p) for p in result['particles']]
        self.assertAlmostEqual(rows[4][4], (588/72+.5)*.5, places=14)
        self.assertEqual(rows[5][6:], [20, 13, 6, 6])
        _, (_, filled) = analysis({'includeHoles': True, 'excludeEdges': True, 'minimumArea': 0.5})
        self.assertEqual([p['pixelCount'] for p in filled['particles']], [60, 64, 72, 144, 18])
        self.assertEqual(filled['rejected'], {'edge': 1, 'size': 1})
        ring = filled['particles'][3]
        self.assertEqual((ring['sum'], ring['minimum'], ring['maximum']), (108*160+32*20+4*230, 20, 230))
        _, (_, four) = analysis({'connectivity': 'four', 'includeHoles': True})
        self.assertEqual([p['pixelCount'] for p in four['particles']][-2:], [9, 9])
        _, (_, boundary) = analysis({'threshold': {'lower': 180, 'upper': 255}})
        self.assertEqual([p['pixelCount'] for p in boundary['particles']], [20, 60, 64, 72, 4, 18])
        _, (_, above) = analysis({'threshold': {'lower': 181, 'upper': 255}})
        self.assertNotIn(64, [p['pixelCount'] for p in above['particles']])
        prepared16, (image16, sixteen) = analysis({'threshold': {'lower': 10000, 'upper': 65535}}, 'particles-16bit.tif')
        self.assertEqual((image16['bitDepth'], image16['byteOrder']), (16, 'big'))
        self.assertEqual(sixteen['labels'], analysis()[1][1]['labels'])

    def test_hole_fill_uses_complementary_connectivity(self):
        # A diamond of four 8-connected pixels encloses its centre; a 4-connected
        # background cannot escape it, so includeHoles counts five pixels.
        values = [0]*9
        for x, y in ((1, 0), (0, 1), (2, 1), (1, 2)): values[y*3+x] = 9
        image = {'width': 3, 'height': 3, 'values': values}
        base = {'lower': 1, 'upper': 9, 'connectivity': 'eight', 'includeHoles': True, 'excludeEdges': False,
                'minimumPixels': 0, 'maximumPixels': None}
        self.assertEqual([p['pixelCount'] for p in images.analyse(image, base)['particles']], [5])
        self.assertEqual([p['pixelCount'] for p in images.analyse(image, {**base, 'includeHoles': False})['particles']], [4])
        self.assertEqual([p['pixelCount'] for p in images.analyse(image, {**base, 'connectivity': 'four'})['particles']], [1, 1, 1, 1])

    def test_image_content_rejected_before_native_launch(self):
        prepared = adaptor.plan(document())
        pgm = (FIXTURES/'particles-8bit.pgm').read_bytes()
        for data, code in [(pgm+b'\0', 'INVALID_IMAGE'), (pgm.replace(b'\n255\n', b'\n1000\n'), 'UNSUPPORTED_IMAGE'),
                           (b'P2\n1 1\n255\n0\n', 'INVALID_IMAGE'), (b'P5\n4096 4096\n255\n', 'RESOURCE_LIMIT')]:
            with self.subTest(code=code):
                self.assertEqual(fault(lambda: adaptor.reference(prepared, data)).code, code)
        for edits, code, location in [({'threshold': {'lower': 100, 'upper': 300}}, 'INVALID_THRESHOLD', '$.threshold.upper'),
                                      ({'threshold': {'lower': 0, 'upper': 255}}, 'INVALID_THRESHOLD', '$.threshold'),
                                      ({'threshold': {'lower': 250, 'upper': 254}}, 'NO_PARTICLES', '$.threshold')]:
            d = document(); d.update(edits)
            observed = fault(lambda: adaptor.reference(adaptor.plan(d), pgm))
            self.assertEqual((observed.code, observed.location), (code, location))

    def test_tiff_subset_rejects_unsupported_structure(self):
        tif = bytearray((FIXTURES/'particles-16bit.tif').read_bytes())
        prepared = adaptor.plan(document('particles-16bit', 'particles-16bit.tif'))
        self.assertEqual(adaptor.reference(prepared, bytes(tif))[0]['bitDepth'], 16)
        def entry(tag):
            count = struct.unpack_from('>H', tif, 8)[0]
            return next(10+12*i for i in range(count) if struct.unpack_from('>H', tif, 10+12*i)[0] == tag)
        for tag, value, code in [(259, 5, 'UNSUPPORTED_IMAGE'), (262, 0, 'UNSUPPORTED_IMAGE'), (258, 12, 'UNSUPPORTED_IMAGE')]:
            bad = bytearray(tif); struct.pack_into('>H', bad, entry(tag)+8, value)
            with self.subTest(tag=tag):
                self.assertEqual(fault(lambda: adaptor.reference(prepared, bytes(bad))).code, code)
        bad = bytearray(tif); struct.pack_into('>H', bad, entry(277), 320)  # unknown colour-map tag replaces SamplesPerPixel
        self.assertEqual(fault(lambda: adaptor.reference(prepared, bytes(bad))).code, 'UNSUPPORTED_IMAGE')
        bad = bytearray(tif); count = struct.unpack_from('>H', bad, 8)[0]
        struct.pack_into('>I', bad, 10+12*count, 8)  # second IFD
        self.assertEqual(fault(lambda: adaptor.reference(prepared, bytes(bad))).code, 'UNSUPPORTED_IMAGE')
        self.assertEqual(fault(lambda: adaptor.reference(prepared, bytes(tif[:-2]))).code, 'INVALID_IMAGE')

    def test_fixed_program_and_commands_do_not_embed_authored_values(self):
        from schemaxis.adaptors.imagej.program import PROGRAM
        self.assertNotIn('runMacro', PROGRAM); self.assertNotIn('eval(', PROGRAM)
        d = document(); prepared = adaptor.plan(d)
        directory = Path('/run')
        commands = adaptor.commands('/usr/bin/java', '/opt/ij.jar', directory, prepared, 8)
        self.assertEqual(commands, adaptor.commands('/usr/bin/java', '/opt/ij.jar', directory, prepared, 8))
        self.assertNotIn(d['image'], commands['analyse'])
        self.assertIn('/run/input.pgm', commands['analyse'])
        self.assertIn('-Djava.awt.headless=true', commands['analyse'])
        self.assertEqual(adaptor.native_options(prepared), 16)
        self.assertEqual(adaptor.native_options(adaptor.plan({**d, 'connectivity': 'four', 'includeHoles': True})), 16 | 8192 | 1024)

    def test_runtime_identities(self):
        self.assertEqual(adaptor.runtime_identity('1.54t'), '1.54t')
        for value in ('1.53v', '2.0.0', '1.54t;rm'):
            self.assertEqual(fault(lambda: adaptor.runtime_identity(value)).code, 'UNSUPPORTED_RUNTIME')
        self.assertEqual(adaptor.java_identity('openjdk version "21.0.12.1" 2026-08-18'), 21)
        self.assertEqual(fault(lambda: adaptor.java_identity('java version "1.8.0_402"')).code, 'UNSUPPORTED_RUNTIME')

    def test_missing_runtime_and_false_success(self):
        with tempfile.TemporaryDirectory() as temp:
            observed = fault(lambda: adaptor.run(document(), Path(temp)/'a', executable='/missing-java', jar='/missing/ij.jar'))
            self.assertEqual(observed.code, 'INTERPRETER_NOT_FOUND')
            observed = fault(lambda: adaptor.run(document(), Path(temp)/'b', executable='/bin/true', jar=None))
            self.assertEqual(observed.code, 'INTERPRETER_NOT_FOUND')
            jar = Path(temp)/'ij.jar'; jar.write_bytes(b'')
            directory = Path(temp)/'c'
            with patch.object(adaptor, 'execute'):
                self.assertIsInstance(fault(lambda: adaptor.run(document(), directory, executable='/bin/true', jar=str(jar))), object)
            self.assertEqual(json.loads((directory/'result.json').read_text())['status'], 'failed')
            directory = Path(temp)/'d'; d = document(); d['threshold'] = {'lower': 250, 'upper': 254}
            with patch.object(adaptor, 'execute') as native:
                self.assertEqual(fault(lambda: adaptor.run(d, directory, executable='/bin/true', jar=str(jar))).code, 'NO_PARTICLES')
            native.assert_not_called()

    def test_offline_double_verifies_and_publishes_units(self):
        directory, result = fake_run(self)
        self.assertTrue(result['verified']); self.assertEqual(result['particles'], 8)
        table = read_csv(directory/'particles.csv')
        self.assertEqual(table['columns'][2:4], ['area_um2', 'centroidX_um'])
        self.assertEqual(table['rows'][5][:3], [6, 108, 27])
        summary = json.loads((directory/'particle-summary.json').read_text())
        self.assertEqual((summary['calibration']['nativeUnit'], summary['totalArea']), ('µm', 86.75))
        self.assertTrue(adaptor.verify(directory)['verified'])
        directory, _ = fake_run(self, edits={'calibration': {'pixelWidth': 0.25, 'pixelHeight': 0.5, 'unit': 'mm'}})
        self.assertEqual(read_csv(directory/'particles.csv')['columns'][2], 'area_mm2')

    def test_verifier_rejects_native_and_publication_disagreement(self):
        def replace(name, old, new, count=1):
            def mutate(stage, directory):
                path = directory/name
                if stage == ('reopen' if name.startswith('reopen') else 'analyse'):
                    text = path.read_bytes(); self.assertIn(old, text); path.write_bytes(text.replace(old, new, count))
            return mutate
        def relabel(stage, directory):
            if stage == 'analyse':
                data = bytearray((directory/'count-mask.pgm').read_bytes()); data[-1] = 7
                (directory/'count-mask.pgm').write_bytes(bytes(data))
        cases = {'native area': replace('native-particles.csv', b'27.0,', b'27.000001,'),
                 'reopen mean': replace('reopen-particles.csv', b'160.0', b'161.0'),
                 'native unit': replace('analyse-readback.txt', b'unit=181,109', b'unit=117,109'),
                 'native options': replace('analyse-readback.txt', b'options=16', b'options=8208'),
                 'native runtime': replace('analyse-readback.txt', b'imagej=1.54t', b'imagej=1.53v'),
                 'consumed input': replace('reopen-readback.txt', b'inputSha256=', b'inputSha256=0'),
                 'stack': replace('analyse-readback.txt', b'stackSize=1', b'stackSize=2'),
                 'density calibration': replace('reopen-readback.txt', b'densityCalibrated=false', b'densityCalibrated=true'),
                 'count mask': relabel}
        for label, mutate in cases.items():
            with self.subTest(label=label), patch.object(adaptor, 'execute', FakeNative(mutate)):
                temp = temporary(self)
                jar = temp/'ij.jar'; jar.write_bytes(b'')
                observed = fault(lambda: adaptor.run(document(), temp/'run', executable='/bin/true', jar=str(jar)))
                self.assertIn(observed.code, {'VERIFICATION_FAILED', 'UNSUPPORTED_RUNTIME', 'UNSUPPORTED_IMAGE'})
        directory, _ = fake_run(self)
        for name, change in [('particles.csv', lambda t: t.replace(b',27,', b',27.5,')),
                             ('particle-summary.json', lambda t: t.replace(b'"particleCount": 8', b'"particleCount": 9')),
                             ('SchemaxisImageJParticles.java', lambda t: t.replace(b'INCLUDE_HOLES', b'EXCLUDE_EDGE_PARTICLES')),
                             ('input.pgm', lambda t: t[:-1]+b'\xff')]:
            path = directory/name; saved = path.read_bytes()
            try:
                changed = change(saved); self.assertNotEqual(changed, saved); path.write_bytes(changed)
                # Refreshing the evidence digests cannot hide the semantic disagreement.
                receipt = json.loads((directory/'verification.json').read_text()); saved_receipt = json.dumps(receipt)
                for record in receipt['artifacts']:
                    if Path(record['file']).name == name: record['sha256'] = hashlib.sha256(changed).hexdigest()
                if name in receipt['evidence']: receipt['evidence'][name] = hashlib.sha256(changed).hexdigest()
                (directory/'verification.json').write_text(json.dumps(receipt))
                with self.subTest(name=name):
                    self.assertEqual(fault(lambda: adaptor.verify(directory)).code, 'VERIFICATION_FAILED')
            finally:
                path.write_bytes(saved); (directory/'verification.json').write_text(saved_receipt)
        self.assertTrue(adaptor.verify(directory)['verified'])

    def test_registry_routing_reuse_and_resources(self):
        d = document()
        self.assertEqual(registry.plan(d)['operation'], 'analyzeParticles')
        self.assertEqual(adaptor.query(d), (['analyzeParticles'], {}))
        self.assertEqual(adaptor.reusableInputs(d), {d['image']: hashlib.sha256((FIXTURES/'particles-8bit.pgm').read_bytes()).hexdigest()})
        self.assertIsNone(adaptor.reusableInputs({**d, 'image': '/missing/particles.pgm'}))
        self.assertEqual(adaptor.resources(d, {}, 'particles'), {'threads': 1})
        self.assertEqual(fault(lambda: adaptor.resources(d, {'threads': 2}, 'particles')).code, 'INVALID_EXECUTION')
        workflow = json.loads((ROOT/'examples/schemaxis/imagej-to-calc.json').read_text())
        self.assertEqual(workflow['operations'][1]['document']['nodes'][0]['options']['file'], {'$artifact': 'particles', 'index': 0})

    def test_studio_recipes_plan_and_search_cases_complete(self):
        library = load_library('imagej')
        for group in ('templates', 'snippets'):
            for item in library[group]:
                with self.subTest(item=item['id']):
                    self.assertEqual(registry.plan(instantiate_item(library, item, provider='imagej'))['operation'], 'analyzeParticles')
                    with self.assertRaises(SchemaxisError):
                        registry.plan(instantiate_item(library, item, provider='imagej', filled=False))
        report = check_cases(CapabilityCatalogue(['imagej']), 'imagej')
        self.assertTrue(report['complete'], report)

    def test_studio_templates_bind_both_sixteen_bit_threshold_bounds(self):
        library = load_library('imagej')
        for template in library['templates']:
            item = copy.deepcopy(template)
            item['testValues'].update(image=str(FIXTURES/'particles-16bit.tif'), lower=18000, upper=65535)
            with self.subTest(template=item['id']):
                authored = instantiate_item(library, item, provider='imagej')
                prepared = registry.plan(authored)
                self.assertEqual(prepared['threshold'], {'lower': 18000, 'upper': 65535})
                image, measured = adaptor.reference(prepared, (FIXTURES/'particles-16bit.tif').read_bytes())
                self.assertEqual(image['bitDepth'], 16)
                self.assertGreater(len(measured['particles']), 0)


if __name__ == '__main__':
    unittest.main()
