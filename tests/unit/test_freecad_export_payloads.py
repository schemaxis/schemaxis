"""Host-only publication authority controls; no native application is started."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.freecad import export_payloads as E
from schemaxis.errors import SchemaxisError, fail


STEP = b"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('FreeCAD Model'),'2;1');
FILE_NAME('Open CASCADE Shape Model','2026-11-05T18:07:47',('FreeCAD'),
('FreeCAD'),'Open CASCADE STEP processor 7.8','FreeCAD','Unknown');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));
ENDSEC;
DATA;
#1 = CARTESIAN_POINT('point; ENDSEC;', (1.,-2.E+1,3.));
#2 = VERTEX_POINT('',#1);
#3 = ADVANCED_FACE('',(#2),#1,.T.);
ENDSEC;
END-ISO-10303-21;
"""
STL = b'Schemaxis deterministic binary header'.ljust(80, b' ') + b'\4\0\0\0' + bytes(200)
STAMP = b'2026-11-05T18:07:47'


class ExportPayloadTests(unittest.TestCase):
    def bind(self, step=STEP, stl=STL, **options):
        return E.bind(step, stl, expected_step=options.pop('expected_step', STEP),
                      expected_stl=options.pop('expected_stl', STL), **options)

    def refused(self, call, code='VERIFICATION_FAILED'):
        with self.assertRaises(SchemaxisError) as caught:
            call()
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def test_timestamp_only_change_and_immutable_snapshot_hashes(self):
        data = STEP.replace(STAMP, b'2028-02-29T23:59:59')
        result = self.bind(data)
        self.assertEqual(result['step'].data, data)
        self.assertEqual(result['step'].sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(result['step'].size, len(data))
        with self.assertRaises(AttributeError):
            result['step'].data = STEP
        self.assertEqual(E.capture(result['step']), result['step'])

    def test_snapshot_metadata_is_revalidated(self):
        for field, value in (('sha256', 'forged'), ('size', 0), ('data', STEP + b' '),
                             ('data', bytearray(STEP))):
            payload = E.capture(STEP)
            object.__setattr__(payload, field, value)
            self.refused(lambda: E.capture(payload))

    def test_only_insignificant_whitespace_and_comments_are_ignored(self):
        data = STEP.replace(b'#1 =', b'/* #999=evil; DATA; */ #1\n=')
        data = data.replace(b'END-ISO-10303-21;', b'END-ISO-10303-21; /* trailing comment */\n')
        self.bind(data)
        # A quoted whitespace or comment spelling is significant.
        self.refused(lambda: self.bind(STEP.replace(b'FreeCAD Model', b'FreeCAD  Model')))
        self.refused(lambda: self.bind(STEP.replace(b'FreeCAD Model', b'FreeCAD/*x*/Model')))

    def test_header_values_are_all_bound(self):
        mutations = [
            (b'FreeCAD Model', b'Other Model'),
            (b"'2;1'", b"'2;2'"),
            (b'Open CASCADE Shape Model', b'/tmp/elsewhere.step'),
            (b"('FreeCAD'),", b"('Another Author'),"),
            (b"('FreeCAD'),'Open", b"('Another Organisation'),'Open"),
            (b'processor 7.8', b'processor 7.9'),
            (b"7.8','FreeCAD'", b"7.8','Other System'"),
            (b"'Unknown'", b"'Other Authorisation'"),
            (b'AUTOMOTIVE_DESIGN', b'CONFIG_CONTROL_DESIGN'),
        ]
        for old, new in mutations:
            with self.subTest(old=old):
                self.assertIn(old, STEP)
                self.refused(lambda: self.bind(STEP.replace(old, new)))

    def test_complete_data_lexemes_not_numeric_or_reference_equivalence(self):
        mutations = [(b'1.,', b'1.0,'), (b'-2.E+1', b'-20.'),
                     (b'3.', b'3.00000000000001'), (b'#1);', b'#2);'),
                     (b'#1 =', b'#01 ='), (b'VERTEX_POINT', b'CARTESIAN_POINT'),
                     (b'.T.', b'.F.'),
                     (b'point; ENDSEC;', b'point; ENDSEC; changed')]
        for old, new in mutations:
            with self.subTest(old=old):
                self.refused(lambda: self.bind(STEP.replace(old, new)))
        self.refused(lambda: self.bind(STEP.replace(b'#2 =', b'#3 =')))
        self.refused(lambda: self.bind(STEP.replace(b'#2 = VERTEX_POINT', b'#9 = VERTEX_POINT')))

    def test_all_stl_bytes_including_header_are_bound(self):
        for offset in (0, 79, 80, 83, 84, len(STL)-1):
            changed = bytearray(STL)
            changed[offset] ^= 1
            self.refused(lambda: self.bind(stl=bytes(changed)))
        self.refused(lambda: self.bind(stl=STL + b'\0'))
        self.refused(lambda: self.bind(stl=STL[:-1]))

    def test_stl_binary_layout_and_existing_facet_bound(self):
        for data in (b'solid ascii\nendsolid\n', STL[:80] + bytes(4),
                     STL[:80] + b'\3\0\0\0' + bytes(150)):
            self.refused(lambda: self.bind(stl=data, expected_stl=data))
        with patch.object(E, 'MAX_FACETS', 3):
            self.refused(lambda: E.capture(STL, kind='stl'), 'RESOURCE_LIMIT')

    def test_timestamp_shape_and_calendar_checked_on_both_sides(self):
        invalid = [b'2027-02-29T12:00:00', b'2026-04-31T12:00:00',
                   b'0000-01-01T00:00:00', b'2026-01-01T24:00:00',
                   b'2026-01-01T00:60:00', b'2026-01-01T00:00:60',
                   b'2026-1-01T00:00:00', b'2026-01-01T00:00:00Z',
                   b'2026-01-01T00:00:00.0', b'2026-01-01 00:00:00']
        for stamp in invalid:
            bad = STEP.replace(STAMP, stamp)
            with self.subTest(stamp=stamp):
                self.refused(lambda: self.bind(bad, expected_step=bad))
                self.refused(lambda: self.bind(expected_step=bad))

    def test_closed_header_grammar_even_when_expected_is_identical(self):
        variants = [
            STEP.replace(b'FILE_NAME(', b'EXTRA();FILE_NAME('),
            STEP.replace(b'FILE_NAME(', b'FILE_DESCRIPTION((\'x\'),\'2;1\');FILE_NAME('),
            STEP.replace(b"('FreeCAD'),", b'(),'),
            STEP.replace(b"'Unknown'", b"'Unknown',$"),
            STEP.replace(b"FILE_SCHEMA((", b"FILE_SCHEMA((#1,"),
            STEP.replace(b"FILE_DESCRIPTION(('FreeCAD Model'),'2;1');", b''),
            STEP.replace(b'HEADER;', b'HEADER(\'x\');'),
        ]
        for bad in variants:
            with self.subTest(data=bad[:100]):
                self.refused(lambda: self.bind(bad, expected_step=bad))

    def test_sections_trailer_and_lexical_attacks(self):
        variants = [
            STEP + b'DATA;ENDSEC;', STEP + b'#9=POINT();', STEP + b'garbage',
            STEP + b'/* unterminated', STEP + b'\0',
            STEP.replace(b'DATA;', b'REFERENCE;'),
            STEP.replace(b'END-ISO-10303-21;', b'ENDSEC;END-ISO-10303-21;'),
            STEP.replace(b'DATA;', b'DATA;ENDSEC;DATA;'),
            STEP.replace(b'END-ISO-10303-21;', b''),
            STEP.replace(b'CARTESIAN_POINT', b'!USER_ENTITY'),
            STEP.replace(b"'point; ENDSEC;'", b"'unterminated"),
            STEP.replace(b'FreeCAD Model', 'FreeCAD Modèle'.encode()),
        ]
        for bad in variants:
            with self.subTest(data=bad[-65:]):
                self.refused(lambda: self.bind(bad, expected_step=bad))

    def test_header_full_file_and_token_bounds(self):
        bad = STEP.replace(b'HEADER;', b'HEADER;/*' + b'x' * E.MAX_HEADER_BYTES + b'*/')
        self.refused(lambda: self.bind(bad, expected_step=bad))
        bad = STEP.replace(b'CARTESIAN_POINT', b'A' * (E.step_source.MAX_TOKEN + 1))
        self.refused(lambda: self.bind(bad, expected_step=bad), 'RESOURCE_LIMIT')
        bad = STEP.replace(b'point; ENDSEC;', b'x' * E.step_source.MAX_STRING)
        self.refused(lambda: self.bind(bad, expected_step=bad), 'RESOURCE_LIMIT')
        with patch.object(E, 'MAX_BYTES', len(STEP) - 1):
            self.refused(lambda: E.capture(STEP), 'RESOURCE_LIMIT')

    def test_regular_paths_symlinks_directories_fifo_and_snapshot_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            step, stl = root/'model.step', root/'model.stl'
            step.write_bytes(STEP); stl.write_bytes(STL)
            captured = self.bind(step, stl)
            step.write_bytes(b'changed')
            self.bind(captured['step'], captured['stl'])
            self.refused(lambda: self.bind(step, stl))
            self.refused(lambda: E.capture(root))
            self.refused(lambda: E.capture(root/'missing'))
            (root/'link').symlink_to(stl)
            self.refused(lambda: E.capture(root/'link'))
            (root/'dirlink').symlink_to(root, target_is_directory=True)
            self.assertEqual(E.capture(root/'dirlink'/'model.stl').data, STL)
            self.refused(lambda: E.capture(root/'dirlink'/'..'/'model.stl'))
            os.mkfifo(root/'fifo')
            self.refused(lambda: E.capture(root/'fifo'))
            with patch.object(E, 'MAX_BYTES', len(STL)-1):
                self.refused(lambda: E.capture(stl), 'RESOURCE_LIMIT')

    def test_in_place_mutation_and_named_replacement_during_read_refused(self):
        for replace in (False, True):
            with self.subTest(replace=replace), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'model.step'
                path.write_bytes(STEP)
                original = E.os.read
                changed = False
                def read(descriptor, size):
                    nonlocal changed
                    data = original(descriptor, size)
                    if not changed:
                        changed = True
                        if replace:
                            replacement = path.with_suffix('.new')
                            replacement.write_bytes(STEP)
                            replacement.replace(path)
                        else:
                            path.write_bytes(STEP + b' ')
                    return data
                with patch.object(E.os, 'read', side_effect=read):
                    self.refused(lambda: E.capture(path))

    def test_cancellation_and_timeout_propagate_without_reclassification(self):
        for code in ('RUNNER_CANCELLED', 'RUNNER_TIMED_OUT'):
            with patch.object(E, 'checkpoint', side_effect=lambda: fail(code, 'test stop')):
                self.refused(lambda: self.bind(), code)
        # Stop during token processing after snapshots have already been captured.
        step, stl = E.capture(STEP), E.capture(STL)
        calls = 0
        def cancel_later():
            nonlocal calls
            calls += 1
            if calls == 6:
                fail('RUNNER_CANCELLED', 'test lexical stop')
        with patch.object(E, 'checkpoint', side_effect=cancel_later):
            self.refused(lambda: self.bind(step, stl, expected_step=step, expected_stl=stl), 'RUNNER_CANCELLED')
        self.assertEqual(calls, 6)


if __name__ == '__main__':
    unittest.main()
