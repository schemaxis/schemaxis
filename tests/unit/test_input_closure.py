import gzip
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from schemaxis.adaptors.paraview import input_closure
from schemaxis.adaptors.paraview.input_closure import foam_closure, xml_closure
from schemaxis.adaptors.paraview.parallel_files import members
from schemaxis.core.faults import SchemaxisError


LEAF = b'<?xml version="1.0"?>\n<VTKFile type="PolyData" version="1.0"><PolyData/></VTKFile>\n'
RAW = (b'<?xml version="1.0"?>\n<!-- raw payload -->\n<VTKFile type="UnstructuredGrid" version="1.0">'
       b'<UnstructuredGrid/><AppendedData encoding="raw">_\x00\x01<\xff&\x02</VTKFile>')


def blocks(*files, kind='vtkMultiBlockDataSet'):
    sets = ''.join('<DataSet index="%d" file="%s"/>' % item for item in enumerate(files))
    return ('<?xml version="1.0"?>\n<VTKFile type="%s" version="1.0"><%s>%s</%s></VTKFile>'
            % (kind, kind, sets, kind)).encode()


def ppoly(*files):
    pieces = ''.join('<Piece Source="%s"/>' % name for name in files)
    return ('<VTKFile type="PPolyData" version="1.0"><PPolyData>%s</PPolyData></VTKFile>' % pieces).encode()


HEADER = b'''/*--------------------------------*- C++ -*----------------------------------*\\
| \\\\      /  F ield | # not a directive in a comment                           |
\\*---------------------------------------------------------------------------*/
FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }
'''


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name) / 'data'
        self.data.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, files):
        for name, content in files.items():
            path = self.data / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return sorted(files)

    def refused(self, function, *args):
        with self.assertRaises(SchemaxisError) as caught:
            function(*args)
        self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_RESOURCE')
        return caught.exception.fault


class XmlClosureTests(Fixture):
    def closure(self, reader, member, files):
        return xml_closure(reader, self.data / member, self.data, files)

    def test_valid_nested_multiblock_and_parallel_closure_with_raw_leaf(self):
        files = self.write({'top.VTM': blocks('inner/blocks.vtm', 'raw.vtu'), 'raw.vtu': RAW,
                            'inner/blocks.vtm': blocks('../p/all.pvtp'),
                            'p/all.pvtp': ppoly('a.vtp', 'b.VTP'), 'p/a.vtp': LEAF, 'p/b.VTP': LEAF})
        self.assertEqual(self.closure('readMultiBlock', 'top.VTM', files), files)
        self.assertEqual(self.closure('readParallelPolyData', 'p/all.pvtp', files),
                         ['p/a.vtp', 'p/all.pvtp', 'p/b.VTP'])

    def test_uppercase_root_with_missing_or_escaping_reference_is_refused(self):
        files = self.write({'case.VTM': blocks('gone.vtp'), 'out.VTM': blocks('../outside.vtp')})
        (self.data.parent / 'outside.vtp').write_bytes(LEAF)
        self.assertIn('not a captured member', self.refused(self.closure, 'readMultiBlock', 'case.VTM', files).message)
        self.assertIn('escapes', self.refused(self.closure, 'readMultiBlock', 'out.VTM', files).message)
        # Present on disk but excluded from the captured membership is still refused.
        files = self.write({'set.vtm': blocks('extra.vtp'), 'extra.vtp': LEAF})
        self.refused(self.closure, 'readMultiBlock', 'set.vtm', ['set.vtm'])

    def test_unsupported_root_names_are_refused(self):
        for name in ('blocks.dat', 'blocks.vtm.txt', 'blocks.vtp'):
            files = self.write({name: blocks('gone.vtp')})
            self.refused(self.closure, 'readMultiBlock', name, files)
        files = self.write({'p.pvtu': ppoly()})
        self.refused(self.closure, 'readParallelUnstructuredGrid', 'p.pvtu', files)

    def test_metadata_renamed_as_leaf_cannot_hide_references(self):
        files = self.write({'top.vtm': blocks('hidden.vtp'), 'hidden.vtp': blocks('../escape.vtp')})
        fault = self.refused(self.closure, 'readMultiBlock', 'top.vtm', files)
        self.assertEqual(fault.observed['declared'], 'vtkMultiBlockDataSet')
        files = self.write({'pp.pvtp': ppoly('piece.vtp'), 'piece.vtp': blocks('missing.vtp')})
        self.refused(self.closure, 'readParallelPolyData', 'pp.pvtp', files)
        # A parallel piece must be the matching leaf type.
        files = self.write({'mixed.pvtp': ppoly('raw.vtu'), 'raw.vtu': RAW})
        self.refused(self.closure, 'readParallelPolyData', 'mixed.pvtp', files)

    def test_unrecognised_headers_and_cycles(self):
        files = self.write({'top.vtm': blocks('junk.vtp'), 'junk.vtp': b'\x00binary'})
        self.refused(self.closure, 'readMultiBlock', 'top.vtm', files)
        files = self.write({'doc.vtm': b'<!DOCTYPE x [<!ENTITY a "b">]><VTKFile type="vtkMultiBlockDataSet"/>'})
        self.refused(self.closure, 'readMultiBlock', 'doc.vtm', files)
        files = self.write({'a.vtm': blocks('b.vtm'), 'b.vtm': blocks('a.vtm', 'leaf.vtp'), 'leaf.vtp': LEAF})
        self.assertEqual(self.closure('readMultiBlock', 'a.vtm', files), files)

    def test_publication_members_helper_is_unchanged(self):
        files = self.write({'p.pvtp': ppoly('a.vtp'), 'a.vtp': LEAF, 'UP.VTM': blocks('gone.vtp')})
        self.assertEqual([path.name for path in members(self.data / 'p.pvtp')], ['a.vtp', 'p.pvtp'])
        self.assertEqual([path.name for path in members(self.data / 'UP.VTM')], ['UP.VTM'])

    def test_duplicate_references_read_each_header_once(self):
        files = self.write({'all.vtm': blocks(*(['a.vtp'] * 5000)), 'a.vtp': LEAF})
        with mock.patch.object(input_closure, 'document_type', wraps=input_closure.document_type) as read:
            self.assertEqual(self.closure('readMultiBlock', 'all.vtm', files), files)
        self.assertEqual(read.call_count, 2)

    def test_cached_leaf_still_checks_each_parallel_piece_type(self):
        for order in (('bad.pvtu', 'good.pvtp'), ('good.pvtp', 'bad.pvtu')):
            with self.subTest(order=order):
                files = self.write({'all.vtm': blocks(*order), 'good.pvtp': ppoly('a.vtp'),
                                    'bad.pvtu': ppoly('a.vtp').replace(b'PPolyData', b'PUnstructuredGrid'),
                                    'a.vtp': LEAF})
                fault = self.refused(self.closure, 'readMultiBlock', 'all.vtm', files)
                self.assertEqual(fault.observed['expected'], 'UnstructuredGrid')

    def test_reference_budget_counts_duplicates_across_containers(self):
        files = self.write({'all.vtm': blocks('inner.vtm'), 'inner.vtm': blocks('a.vtp', 'a.vtp'),
                            'a.vtp': LEAF})
        with mock.patch.object(input_closure, 'XML_MAX_REFERENCES', 3):
            self.assertEqual(self.closure('readMultiBlock', 'all.vtm', files), files)
        with mock.patch.object(input_closure, 'XML_MAX_REFERENCES', 2):
            fault = self.refused(self.closure, 'readMultiBlock', 'all.vtm', files)
            self.assertIn('reference count limit', fault.message)

    def test_container_byte_limits_apply_to_streamed_bytes(self):
        outer, inner = blocks('inner.vtm'), blocks('a.vtp')
        files = self.write({'all.vtm': outer, 'inner.vtm': inner, 'a.vtp': LEAF})
        total = len(outer) + len(inner)
        with mock.patch.object(input_closure, 'XML_CHUNK', 17):
            with mock.patch.object(input_closure, 'XML_MAX_TOTAL_BYTES', total):
                self.assertEqual(self.closure('readMultiBlock', 'all.vtm', files), files)
            with mock.patch.object(input_closure, 'XML_MAX_TOTAL_BYTES', total - 1):
                fault = self.refused(self.closure, 'readMultiBlock', 'all.vtm', files)
                self.assertIn('scan byte limit', fault.message)
            with mock.patch.object(input_closure, 'XML_MAX_CONTAINER_BYTES', len(outer) - 1):
                self.refused(self.closure, 'readMultiBlock', 'all.vtm', files)

    def test_element_depth_is_bounded_and_malformed_tail_is_refused(self):
        nested = (b'<VTKFile type="vtkMultiBlockDataSet"><vtkMultiBlockDataSet>'
                  b'<Block><DataSet file="a.vtp"/></Block></vtkMultiBlockDataSet></VTKFile>')
        files = self.write({'all.vtm': nested, 'a.vtp': LEAF})
        with mock.patch.object(input_closure, 'XML_MAX_DEPTH', 4):
            self.assertEqual(self.closure('readMultiBlock', 'all.vtm', files), files)
        with mock.patch.object(input_closure, 'XML_MAX_DEPTH', 3):
            fault = self.refused(self.closure, 'readMultiBlock', 'all.vtm', files)
            self.assertIn('element depth limit', fault.message)
        for invalid in (nested[:-5], nested + b'<extra/>'):
            self.write({'all.vtm': invalid})
            self.assertIn('not well-formed', self.refused(self.closure, 'readMultiBlock', 'all.vtm', files).message)


class FoamClosureTests(Fixture):
    def case(self, files):
        return self.write({'case.foam': b'', 'system/controlDict': HEADER + b'application x;\n', **files})

    def closure(self, files):
        return foam_closure('case.foam', self.data, files)

    def test_include_free_ascii_case_with_comments_and_quoted_hash_is_accepted(self):
        files = self.case({
            'constant/polyMesh/points': HEADER + b'3\n(\n(0 0 0)\n(1 0 0)\n(0 1 0)\n)\n',
            '0/U': HEADER + b'internalField uniform (0 0 0); // #include "x"\n/* #include "y" */\n'
                            b'libs ("lib#a.so" "b//c" "/*d*/");\nvalue $internalField;\n',
            '0/p.gz': gzip.compress(HEADER + b'p uniform 0;\n'),
            'postProcessing/sets/a.dat': b'# Time p\n', 'log.solve': b'#include anything\n',
            'Allrun': b'#!/bin/sh\n'})
        evidence = self.closure(files)
        self.assertEqual(evidence['scannedMembers'], 5)
        self.assertEqual(evidence['unscannedMembers'], 3)
        self.assertTrue(any('#include' in text for text in evidence['supportedSubset']))

    def test_include_directive_variants_and_evasions_are_refused(self):
        variants = [b'#include "/etc/passwd"\n', b'#sinclude "x"\n', b'#includeIfPresent "x"\n',
                    b'#includeEtc "x"\n', b'#includeFunc x\n', b'value 1; #include "x"\n',
                    b'#  include "x"\n', b'# /* gap */ include "x"\n', b'#"include" "x"\n',
                    b'#inc\\lude "x"\n', b'#{ code #}\n', b'a { #remove b; }\n',
                    b'/* c */#include "x"\n', b'"str"#include "x"\n', b'x 1;\n#\ninclude "x"\n']
        for text in variants:
            with self.subTest(text=text):
                files = self.case({'0/U': HEADER + text})
                self.assertIn('"#"', self.refused(self.closure, files).message)

    def test_ambiguous_or_malformed_lexical_constructs_are_refused(self):
        for text in [b'a"#include x"\n', b'1.0//c\n#x', b'x 1;\r#include', b'"multi\nline"', b'"esc\\" #include "',
                     b'/* unterminated', b'"unterminated', b'/* /* nested */ */', b'// cont \\\n#include "x"',
                     b'format binary;\n', b'data \x00\x01\x02;']:
            with self.subTest(text=text):
                self.refused(self.closure, self.case({'constant/x': HEADER + text}))

    def test_member_and_processor_and_numeric_time_scope(self):
        for name in ('case.foam', 'processor0/0/U', '1e-05/U', 'inf/U', '.5/U', 'constant/U'):
            with self.subTest(name=name):
                files = self.case({name: b'#include "/outside"\n'})
                self.refused(self.closure, files)

    def test_gzip_include_bomb_truncation_and_trailing_data(self):
        self.refused(self.closure, self.case({'0/U': gzip.compress(b'x 1;\n#include "y"\n')}))
        self.refused(self.closure, self.case({'0/U': gzip.compress(HEADER)[:-9]}))
        self.refused(self.closure, self.case({'0/U': gzip.compress(HEADER) + b'trailing'}))
        self.closure(self.case({'0/U': gzip.compress(HEADER) + gzip.compress(b'a 1;\n')}))
        self.refused(self.closure, self.case({'0/U': gzip.compress(HEADER) + gzip.compress(b'#include "x"\n')}))
        bomb = gzip.compress(b' ' * (8 << 20))
        with mock.patch.object(input_closure, 'FOAM_MAX_FILE_BYTES', 4 << 20):
            self.assertIn('scan limit', self.refused(self.closure, self.case({'0/U': bomb})).message)
        with mock.patch.object(input_closure, 'FOAM_MAX_TOTAL_BYTES', 6 << 20):
            self.refused(self.closure, self.case({'0/U': gzip.compress(b' ' * (4 << 20)),
                                                  '0/p': gzip.compress(b' ' * (4 << 20))}))

    def test_chunk_boundaries_do_not_hide_directives(self):
        for offset in range(0, 8):
            with mock.patch.object(input_closure, 'FOAM_CHUNK', 700 + offset):
                text = HEADER + b' ' * 1500 + b'"' + b'a' * 30 + b'"' + b'// c\n' * 40 + b'#include "x"\n'
                self.refused(self.closure, self.case({'0/U': text}))
                self.closure(self.case({'0/U': text[:-13] + b'/* long ' + b'*' * 2000 + b' */\n'}))

    def test_external_sentinel_is_never_opened(self):
        sentinel = Path(self.temp.name) / 'sentinel'
        sentinel.write_text('outside')
        files = self.case({'0/U': b'#include "' + str(sentinel).encode() + b'"\n'})
        real = open

        def guarded(path, *args, **kwargs):
            self.assertNotEqual(Path(path).resolve(), sentinel.resolve())
            return real(path, *args, **kwargs)
        with mock.patch('builtins.open', guarded):
            self.refused(self.closure, files)

    def test_controldict_member_is_refused(self):
        files = self.case({})
        self.refused(foam_closure, 'system/controlDict', self.data, files)

    def test_names_beginning_with_controldict_are_refused_wherever_selected(self):
        # The native root would be the selected file's parent's parent: outside
        # the snapshot at top level, or above the scanned subtree when nested.
        # Contents are benign, so only the selection rule can refuse them.
        for name in ('controlDict.gz', 'controlDict.foam', 'controlDictX', 'ControlDict.foam',
                     'case/system/controlDict.gz', 'case/system/controlDict.anything',
                     'case/constant/controlDict.foam'):
            with self.subTest(name=name):
                files = self.case({name: gzip.compress(HEADER) if name.endswith('.gz') else HEADER,
                                   'case/constant/x': HEADER, 'case/0/U': HEADER})
                fault = self.refused(foam_closure, name, self.data, files)
                self.assertIn('controlDict', fault.message)
        files = self.case({'case/case.foam': b'', 'case/system/controlDict': HEADER})
        self.assertEqual(foam_closure('case/case.foam', self.data, files)['scannedMembers'], 2)

    def test_scope_scans_every_suffix_and_skips_only_letter_named_top_level_entries(self):
        hidden = b'#include "/outside"\n'
        for name in ('system/fvSchemes.orig', 'System/x', 'constant/region/polyMesh/faces.bak',
                     'processor0/constant/polyMesh/boundary', 'Processor1/0/U.old', '+1/U', '-1/U',
                     '0.orig/U', '_tmp/U', 'nan/U', 'constant/x.sh'):
            with self.subTest(name=name):
                self.refused(self.closure, self.case({name: hidden}))
                self.refused(self.closure, self.case({name: gzip.compress(hidden)}))
        evidence = self.closure(self.case({'postProcessing/x': hidden, 'logs/x': hidden, 'README': hidden,
                                           'scripts/run.sh': hidden}))
        self.assertEqual((evidence['scannedMembers'], evidence['unscannedMembers']), (2, 4))
        self.assertTrue(any('5.13.3' in text for text in evidence['scanScope']))

    def test_quoted_strings_are_bounded_below_the_native_token_cap(self):
        limit = input_closure.FOAM_MAX_STRING_BYTES
        self.assertLess(limit + 2, 1024)
        hidden = b'key "' + b'a' * 1025 + b' #include system/../../outside "\n'
        for chunk in (64, 700, 997, 1000, 1001, 1024, 1 << 20):
            with self.subTest(chunk=chunk), mock.patch.object(input_closure, 'FOAM_CHUNK', chunk):
                self.closure(self.case({'0/U': HEADER + b'note "short # hash";\n'}))
                # Several boundary-length strings: retained history is not counted twice.
                self.closure(self.case({'0/U': HEADER + (b'a "' + b'b' * limit + b'";\n') * 3}))
                fault = self.refused(self.closure, self.case({'0/U': HEADER + b'a "' + b'b' * (limit + 1) + b'";\n'}))
                self.assertIn('longer than', fault.message)
                self.refused(self.closure, self.case({'0/U': HEADER + hidden}))
                self.refused(self.closure, self.case({'0/U': gzip.compress(HEADER + hidden)}))
                # Escaped and multi-line strings remain refused independently of length.
                self.refused(self.closure, self.case({'0/U': HEADER + b'a "x\\"y";\n'}))
                self.refused(self.closure, self.case({'0/U': HEADER + b'a "x\ny";\n'}))


if __name__ == '__main__':
    unittest.main()
