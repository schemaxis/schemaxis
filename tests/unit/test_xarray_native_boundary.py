"""Native boundary of the xarray adaptor: real xarray engine='scipy' execution and independent verification.

These tests need the isolated qualified runtime (SCHEMAXIS_XARRAY, an absolute interpreter). Without it they are
reported as skipped and the adaptor stays unqualified; tools/qualify_xarray.py fails, never skips, in that case.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from schemaxis.adaptors.xarray import adaptor as a, cdf, oracle as o
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import xarray_fixtures as fx  # noqa: E402

EXECUTABLE = os.environ.get('SCHEMAXIS_XARRAY')
EXAMPLES = ROOT / 'examples/schemaxis'


@unittest.skipUnless(EXECUTABLE and os.access(EXECUTABLE, os.X_OK),
                     'UNQUALIFIED: set SCHEMAXIS_XARRAY to the isolated xarray 2026.9.0 interpreter')
class NativeBoundaryTests(unittest.TestCase):
    def run_doc(self, doc, name='run'):
        directory = Path(self.tmp.name) / name
        return directory, a.run(doc, directory, executable=EXECUTABLE, timeout=60)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'cube.nc'
        self.source.write_bytes(fx.build())
        self.doc = json.loads((EXAMPLES / 'xarray-profile.json').read_text())
        self.doc['source'] = str(self.source)

    def test_native_xarray_reduces_and_independent_reader_agrees(self):
        directory, result = self.run_doc(self.doc)
        self.assertTrue(result['verified'])
        parsed = cdf.parse((directory / 'profile.nc').read_bytes())
        got = {v['name']: v['values'] for v in parsed['vars']}
        self.assertEqual(got['temperature'], [280.625, 285.625, 290.625, 295.625])
        self.assertEqual(got['depth'], [0.0, 10.0, 20.0, 30.0])
        self.assertEqual(got['validCount'], [6, 6, 6, 6])
        native = json.loads((directory / 'native-result.json').read_text())
        self.assertEqual((native['engine'], native['runtime']['xarray'], native['runtime']['scipy']), ('scipy', '2026.9.0', '1.18.1'))
        self.assertEqual(json.loads((directory / 'readback.json').read_text())['ok'], True)

    def test_permuted_storage_native_result_equals_named_result(self):
        self.source.write_bytes(fx.build(order=('depth', 'time', 'station')))
        names = {c['name']: c for c in self.doc['coordinates']}
        self.doc['coordinates'] = [names[k] for k in ('depth', 'time', 'station')]
        directory, _ = self.run_doc(self.doc)
        self.assertIn('280.625', (directory / 'profile.csv').read_text())

    def test_preserved_text_attributes_and_absent_title(self):
        self.source.write_bytes(fx.build(extra_attrs=[('long_name', 'char', 'Air temperature')]))
        directory, _ = self.run_doc(self.doc, 'with-names')
        parsed = cdf.parse((directory / 'profile.nc').read_bytes())
        by_name = {v['name']: v for v in parsed['vars']}
        self.assertEqual(by_name['temperature']['attrs']['long_name'], ('char', 'Air temperature'))
        self.assertEqual(parsed['attrs']['title'], ('char', 'Analytic measurement cube'))
        self.assertEqual(by_name['depth']['attrs'], {'units': ('char', 'm')})
        self.source.write_bytes(fx.build(title=None))
        directory, _ = self.run_doc(self.doc, 'without-title')
        self.assertNotIn('title', cdf.parse((directory / 'profile.nc').read_bytes())['attrs'])

    def test_refusal_precedes_native_launch(self):
        self.source.write_bytes(fx.build(units={'depth': 'cm'}))
        with self.assertRaises(SchemaxisError) as caught:
            self.run_doc(self.doc)
        self.assertEqual(caught.exception.fault.code, 'XR_UNITS_MISMATCH')
        self.assertFalse((Path(self.tmp.name) / 'run' / 'compute-submission.json').exists())

    def test_altered_publication_fails_saved_verification(self):
        directory, _ = self.run_doc(self.doc)
        path = directory / 'profile.csv'
        path.write_text(path.read_text().replace('285.625', '285.5'))
        with self.assertRaises(SchemaxisError) as caught:
            a.verify(directory)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')


if __name__ == '__main__':
    unittest.main()
