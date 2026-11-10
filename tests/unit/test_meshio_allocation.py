"""Strict ASCII number/separator grammar for the meshio reference readers.

Python's int()/float()/str.split() accept syntax that is not VTK/VTU ASCII
(digit-group underscores, FS/GS/RS/US separators). The independent oracle must
not give such bytes a meaning, and the route must refuse them before launching
native code with a stable malformed-content fault.
"""
import json
from pathlib import Path
import stat
import tempfile
import unittest

from schemaxis.adaptors.meshio import adaptor, reference
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT/'examples/schemaxis/fixtures/meshio'
VTU = (FIXTURES/'mixed.vtu').read_bytes()
VTK = (FIXTURES/'mixed.vtk').read_bytes()

VTU_BAD = {
    'underscore count': (b'NumberOfPoints="5"', b'NumberOfPoints="0_5"'),
    'underscore coordinate': (b'10 20 30', b'1_0 20 30'),
    'underscore integer array': (b'101 203', b'1_01 203'),
    'underscore components': (b'NumberOfComponents="3" format="ascii">1 2 3', b'NumberOfComponents="0_3" format="ascii">1 2 3'),
    'hex integer': (b'3 7 10', b'3 0x7 10'),
    'exponent-only float': (b'10 20 30', b'e5 20 30'),
    'infinity word': (b'10 20 30', b'infinity 20 30'),
    'plus-only': (b'10 20 30', b'+ 20 30'),
}
VTK_BAD = {
    'underscore coordinate': (b'0.01 0.02 0.03', b'0.0_1 0.02 0.03'),
    'underscore count': (b'POINTS 5 double', b'POINTS 0_5 double'),
    'underscore connectivity': (b'4 0 1 2 3', b'4 0 1_ 2 3'),
    'underscore cell type': (b'CELL_TYPES 3\n5 10 5', b'CELL_TYPES 3\n5 1_0 5'),
    'group separator between values': (b'0.01 0.02 0.03', b'0.01\x1d0.02 0.03'),
    'vertical tab line break': (b'3 0 1 2\n4 0 1 2 3', b'3 0 1 2\x0b4 0 1 2 3'),
    'unit separator in count line': (b'POINTS 5 double', b'POINTS\x1f5 double'),
}


class StrictGrammarTests(unittest.TestCase):
    def test_literal_fixtures_and_writer_style_numbers_still_parse(self):
        self.assertEqual(len(reference.vtu(VTU)['cells']), 3)
        self.assertEqual(len(reference.vtk(VTK)['cells']), 3)
        self.assertEqual(reference.numbers('1e-05 -0.5 .5 5. +3 1.25E+2 0\t7\r\n8', 'Float64'), [1e-05, -0.5, .5, 5., 3., 125., 0., 7., 8.])
        self.assertEqual(reference.numbers(' 0 -12\n+7 ', 'Int32'), [0, -12, 7])
        # XML attribute whitespace is formatting, not a value change.
        padded = VTU.replace(b'NumberOfPoints="5"', b'NumberOfPoints=" 5 "')
        self.assertEqual(reference.vtu(padded), reference.vtu(VTU))

    def test_reference_refuses_python_only_number_and_separator_syntax(self):
        for name, (old, new) in VTU_BAD.items():
            with self.subTest(format='vtu', case=name):
                self.assertIn(old, VTU)
                with self.assertRaises(ValueError):
                    reference.vtu(VTU.replace(old, new, 1))
        for name, (old, new) in VTK_BAD.items():
            with self.subTest(format='vtk', case=name):
                self.assertIn(old, VTK)
                with self.assertRaises(ValueError):
                    reference.vtk(VTK.replace(old, new, 1))
        for text, dtype in [('1_0', 'Int32'), ('1_0', 'Float64'), ('1\x1c2', 'Float64'), ('1\x0b2', 'Int32'), ('1\x852', 'Int32')]:
            with self.subTest(text=text, dtype=dtype), self.assertRaises(ValueError):
                reference.numbers(text, dtype)

    def test_run_refuses_before_native_launch_with_stable_fault(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            marker = folder/'launched'
            stub = folder/'python'
            stub.write_text('#!/bin/sh\ntouch "%s"\nexit 3\n' % marker)
            stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
            cases = [('vtu', VTU.replace(b'10 20 30', b'1_0 20 30', 1)), ('vtk', VTK.replace(b'0.01\x20', b'0.0_1 ', 1))]
            for number, (kind, data) in enumerate(cases):
                with self.subTest(format=kind):
                    source = folder/('bad.'+kind)
                    source.write_bytes(data)
                    document = json.loads((ROOT/'examples/schemaxis/meshio-convert.json').read_text())
                    document.update(source=str(source), sourceFormat=kind, targetFormat='vtu' if kind == 'vtk' else 'vtk')
                    output = folder/('out%d' % number)
                    with self.assertRaises(SchemaxisError) as caught:
                        adaptor.run(document, output, executable=str(stub), timeout=30)
                    fault = caught.exception.fault.to_dict()
                    self.assertEqual(fault['code'], 'INVALID_MESH_CONTENT')
                    self.assertEqual(fault['location'], '$.source')
                    self.assertFalse(marker.exists(), 'native interpreter must not launch')
                    self.assertFalse(list(output.glob('mesh*')))
                    self.assertFalse((output/('source.'+kind)).exists())
                    result = json.loads((output/'result.json').read_text())
                    self.assertEqual((result['status'], result['verified']), ('failed', False))
                    self.assertEqual(result['fault']['code'], 'INVALID_MESH_CONTENT')


if __name__ == '__main__':
    unittest.main()
