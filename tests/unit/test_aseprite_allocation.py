"""Evidence relocation and malformed-receipt boundaries; host-only, no native process.

The fixture reproduces the layout of a verified run from the independent raster
oracle and a tiny PNG encoder, so these tests never depend on an Aseprite install.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import zlib

from schemaxis.adaptors.aseprite import plan, run, verify
from schemaxis.adaptors.aseprite.adaptor import FILES, expected
from schemaxis.adaptors.aseprite.native_source import WORKER
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise
from schemaxis.run_paths import MANIFEST, export_manifest

ROOT = Path(__file__).resolve().parents[2]


def png(image):
    width, height, pixels = image['width'], image['height'], bytes.fromhex(image['pixels'])
    raw = b''.join(b'\0' + pixels[y*width*4:(y+1)*width*4] for y in range(height))
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind+body))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value))


def build_evidence(directory, label='icon'):
    """Write a coherent verified-run directory as a successful native run leaves it."""
    directory = Path(directory)
    directory.mkdir(parents=True)
    document = json.loads((ROOT/'examples'/'schemaxis'/f'aseprite-{label}.json').read_text())
    prepared = plan(document)
    native, preview, sheet, metadata = expected(prepared)
    write_json(directory/'authored.json', document)
    write_json(directory/'plan.json', prepared)
    (directory/'worker.lua').write_text(WORKER)
    write_json(directory/'input-manifest.json', {'version': 'schemaxis.aseprite.inputs/1', 'images': []})
    (directory/'sprite.aseprite').write_bytes(b'synthetic editable sprite bytes')
    (directory/'preview.png').write_bytes(png(preview))
    (directory/'sheet.png').write_bytes(png(sheet))
    write_json(directory/'sheet.json', metadata)
    artifacts = [{'file': str(directory/name), 'kind': kind, 'sha256': sha(directory/name)}
                 for name, kind in [('sprite.aseprite', 'sprite'), ('preview.png', 'image'),
                                    ('sheet.png', 'spriteSheet'), ('sheet.json', 'spriteMetadata')]]
    write_json(directory/'verification.json', {'freshProcess': True, 'runtime': 'host-fixture',
        'native': native, 'preview': preview, 'sheet': sheet, 'artifacts': artifacts})
    names = (*FILES, 'verification.json', 'worker.lua', 'input-manifest.json')
    write_json(directory/'result.json', {'status': 'succeeded', 'verified': True,
                                         'sha256': {name: sha(directory/name) for name in names}})
    finalise(directory)
    return directory


def export(source, target):
    """Copy a run as `schemaxis` export does: only the shared manifest gains the origin."""
    shutil.copytree(source, target)
    manifest = export_manifest(source)
    (Path(target)/MANIFEST).write_text(json.dumps(manifest))


class RelocatedEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.original = build_evidence(self.root/'original')

    def relocate(self, name='moved'):
        target = self.root/name
        export(self.original, target)
        return target

    def rewrite_receipt(self, directory, change):
        receipt = json.loads((directory/'verification.json').read_text())
        change(receipt)
        write_json(directory/'verification.json', receipt)
        result = json.loads((directory/'result.json').read_text())
        result['sha256']['verification.json'] = sha(directory/'verification.json')
        write_json(directory/'result.json', result)

    def rejected(self, directory, **expect):
        with self.assertRaises(SchemaxisError) as caught:
            verify(directory)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        return caught.exception.fault

    def test_control_in_place_verifies(self):
        self.assertTrue(verify(self.original)['verified'])

    def test_exported_evidence_verifies_with_receipt_unchanged(self):
        moved = self.relocate()
        before = (moved/'verification.json').read_bytes()
        self.assertEqual(before, (self.original/'verification.json').read_bytes())
        self.assertTrue(verify(moved)['verified'])
        self.assertEqual((moved/'verification.json').read_bytes(), before)  # evidence never rewritten
        # The original stays verifiable and a second hop keeps the first origin.
        self.assertTrue(verify(self.original)['verified'])
        again = self.root/'again'
        export(moved, again)
        self.assertTrue(verify(again)['verified'])

    def test_plain_copy_without_export_origin_is_rejected_with_recovery(self):
        copied = self.root/'plain'
        shutil.copytree(self.original, copied)
        fault = self.rejected(copied)
        self.assertIn('schemaxis export', fault.recovery)

    def test_relocation_does_not_hide_publication_tampering(self):
        for name in ('preview.png', 'sheet.png', 'sprite.aseprite', 'sheet.json'):
            moved = self.relocate('tamper-' + name)
            (moved/name).write_bytes((moved/name).read_bytes() + b'x')
            self.rejected(moved)
        moved = self.relocate('escape')
        outside = self.root/'outside'
        outside.mkdir()
        shutil.copy(moved/'preview.png', outside/'preview.png')
        self.rewrite_receipt(moved, lambda r: r['artifacts'][1].update(file=str(outside/'preview.png')))
        self.rejected(moved)
        moved = self.relocate('linked')
        (moved/'preview.png').rename(outside/'real.png')
        (moved/'preview.png').symlink_to(outside/'real.png')
        self.rejected(moved)
        moved = self.relocate('pixels')
        image = json.loads((self.original/'verification.json').read_text())['preview']
        image['pixels'] = '00' * (len(image['pixels'])//2 - 4) + 'ff0000ff'
        (moved/'preview.png').write_bytes(png(image))
        self.rejected(moved)

    def test_relocated_receipt_membership_must_still_match_exactly(self):
        mutations = {
            'digest': lambda r: r['artifacts'][1].update(sha256='0'*64),
            'kind': lambda r: r['artifacts'][1].update(kind='sprite'),
            'name': lambda r: r['artifacts'][1].update(file=str(Path(r['artifacts'][1]['file']).parent/'other.png')),
            'traversal': lambda r: r['artifacts'][1].update(file='sub/../preview.png'),
            'other-run-name': lambda r: r['artifacts'][1].update(file='sheet.png'),
            'missing': lambda r: r['artifacts'].pop(),
            'extra': lambda r: r['artifacts'].append(copy.deepcopy(r['artifacts'][0])),
            'reordered': lambda r: r['artifacts'].reverse(),
            'extra-key': lambda r: r['artifacts'][0].update(note='x'),
            'file-type': lambda r: r['artifacts'][0].update(file=7),
            'entry-type': lambda r: r['artifacts'].__setitem__(0, 'sprite.aseprite'),
            'list-type': lambda r: r.update(artifacts={}),
        }
        for label, change in mutations.items():
            moved = self.relocate('mut-' + label)
            self.rewrite_receipt(moved, change)
            with self.subTest(label):
                self.rejected(moved)

    def test_run_relative_names_follow_the_shared_portable_receipt_rule(self):
        moved = self.relocate('relative')
        self.rewrite_receipt(moved, lambda r: [a.update(file=Path(a['file']).name) for a in r['artifacts']])
        # The shared publication layer maps run-relative names the same way.
        finalise(moved)
        self.assertTrue(verify(moved)['verified'])

    def test_in_place_manifest_difference_is_still_rejected(self):
        self.rewrite_receipt(self.original, lambda r: r['artifacts'][1].update(sha256='f'*64))
        self.rejected(self.original)

    def test_malformed_result_digest_shapes_are_structured_faults(self):
        for label, value in {'list': [], 'string': 'abc', 'number': 3, 'null': None}.items():
            moved = self.relocate('result-' + label)
            result = json.loads((moved/'result.json').read_text())
            result['sha256'] = value
            write_json(moved/'result.json', result)
            with self.subTest(label):
                fault = self.rejected(moved)
                self.assertEqual(fault.location, 'result.json')
        moved = self.relocate('result-entry')
        result = json.loads((moved/'result.json').read_text())
        result['sha256']['preview.png'] = ['x']
        write_json(moved/'result.json', result)
        self.rejected(moved)

    def test_truncated_and_nonutf8_result_are_structured(self):
        for label, data in {'truncated': b'{"status": ', 'nonutf8': b'\xff\xfe\x00'}.items():
            moved = self.relocate('raw-' + label)
            (moved/'result.json').write_bytes(data)
            with self.subTest(label):
                self.rejected(moved)


@unittest.skipUnless(os.environ.get('ASEPRITE_EXE'), 'set ASEPRITE_EXE for the native relocation check')
class NativeRelocationTests(unittest.TestCase):
    def test_native_run_survives_export(self):
        document = json.loads((ROOT/'examples'/'schemaxis'/'aseprite-icon.json').read_text())
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp)/'first'
            run(document, first, executable=os.environ['ASEPRITE_EXE'], timeout=60)
            moved = Path(temp)/'moved'
            export(first, moved)
            self.assertTrue(verify(first)['verified'])
            self.assertTrue(verify(moved)['verified'])


if __name__ == '__main__':
    unittest.main()
