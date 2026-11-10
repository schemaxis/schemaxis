"""Metadata-first semantic mutants of real E5 runs (genuine ExifTool 13.55 through SCHEMAXIS_EXIFTOOL).

Every mutant edits a copy of a retained editMetadata run over a TIFF, DNG, PNG, WebP or HEIF capture, then refreshes every ordinary binding (launcher input digests, receipt evidence and
artifact records, publication metadata) so that ``publication_metadata.verify`` PASSES, and only then asks the public adaptor ``verify``, which must refuse it with exactly the
semantic code and location of the mutated fact and a non-empty message. Each mutant changes one protected byte or one requested value of the produced file; the expected code, the exact location and the structured fact of the first reported problem (the protected
fingerprint path of a changed byte, the destination of a wrong value) are literals written here, never taken from the output of the run. These are synthetic edits of retained records, kept apart from real native observations in the qualifier report.
"""
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools'), str(ROOT / 'tests/unit')]

import exiftool_e5_fixtures as f  # noqa: E402
from schemaxis import publication_metadata  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from test_exiftool_write_complete import refresh  # noqa: E402

EXIFTOOL = os.environ.get('SCHEMAXIS_EXIFTOOL')
RESULTS = {}
EDIT = {'title': {'set': 'Quarry gate north'}, 'creator': {'set': ['B. Mason']}}
GAMA_CHANGED = f.chunk(b'gAMA', struct.pack('>I', 45456))          # a different value with a valid CRC
VP8 = f.ck(b'VP8 ', f.vp8())
HEIC_IMAGE = b'OPAQUE-HVC1-IMAGE-24BYTES'[:24]       # the opaque image item of f.heic_basic


def doc(path):
    return {'version': 'schemaxis.exiftool/1', 'operation': 'editMetadata', 'media': {'items': [{'id': 'live', 'path': str(path)}]}, 'edits': EDIT}


def replace_once(needle, replacement):
    def change(data):
        assert data.count(needle) >= 1, needle[:12]
        return data.replace(needle, replacement, 1)
    return change


# (suffix, fixture, mutation of the published bytes, exact expected code, exact expected public location)
CASES = {
    'tiff_strip': ('.tif', lambda: f.plain_tiff('<'), replace_once(f.STRIP, bytes([f.STRIP[0] ^ 1]) + f.STRIP[1:]), 'PRESERVATION_MISMATCH', '$.items[0].image'),
    'tiff_title_in_xmp': ('.tif', lambda: f.plain_tiff('<'), replace_once(b'Quarry gate north', b'Quarry gate south'), 'READBACK_MISMATCH', '$.items[0].fields.title.xmp'),
    'dng_private_data': ('.dng', lambda: f.dng()[0], replace_once(b'VendorPrivate-0123', b'VendorPrivate-0124'), 'PRESERVATION_MISMATCH', '$.items[0].image'),
    'png_gamma': ('.png', f.basic_png, replace_once(f.GAMA, GAMA_CHANGED), 'PRESERVATION_MISMATCH', '$.items[0].image'),
    'webp_bitstream': ('.webp', lambda: f.riff(f.ck(b'VP8 ', f.vp8())), replace_once(VP8, VP8[:20] + b'\x11' + VP8[21:]), 'PRESERVATION_MISMATCH', '$.items[0].image'),
    'webp_alpha_flag': ('.webp', lambda: f.riff(f.ck(b'VP8 ', f.vp8())), replace_once(b'VP8X\x0a\x00\x00\x00\x04', b'VP8X\x0a\x00\x00\x00\x14'), 'PRESERVATION_MISMATCH', '$.items[0].image'),
    'heif_image_item': ('.heic', lambda: f.heic_basic(with_metadata=True), replace_once(HEIC_IMAGE, HEIC_IMAGE[:-1] + b'X'), 'PRESERVATION_MISMATCH', '$.items[0].image'),
}

# the first problem of the public refusal, by hand: the exact protected fingerprint path of the byte that is changed (TIFF strip 0 of IFD0; the DNGPrivateData entry 0xC634 of IFD0; the PNG gAMA chunk, first of its kind;
# the WebP VP8 chunk; the created VP8X layout; the HEIF image item 1) and, for the wrong title, the XMP destination that was written
PROBLEMS = {
    'tiff_strip': {'path': 'tiff/extent[IFD0:strip[0]]'},
    'tiff_title_in_xmp': {'destination': 'XMP-dc:Title'},
    'dng_private_data': {'path': 'tiff/entry[IFD0:0xc634]'},
    'png_gamma': {'path': 'png/ancillary[gAMA#0]'},
    'webp_bitstream': {'path': 'riff/chunk[VP8 #0]'},
    'webp_alpha_flag': {'path': 'riff/layout'},
    'heif_image_item': {'path': 'heif/item[1]'},
}


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class MetadataFirst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='e5-metadata-first-'))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.mains = {}
        for label, (suffix, make, _, _, _) in CASES.items():
            source = cls.tmp / ('src-' + label + suffix)
            source.write_bytes(make())
            main = cls.tmp / ('main-' + label)
            result = adaptor.run(doc(source), main, executable=EXIFTOOL, timeout=300)
            assert result['verified'] and result['written'] == 1, (label, result)
            cls.mains[label] = (main, suffix)

    def check(self, label):
        suffix, _, change, code, where = CASES[label]
        problem = PROBLEMS[label]
        main, _ = self.mains[label]
        target = self.tmp / ('mf-' + label)
        shutil.copytree(main, target, symlinks=True)
        published = target / 'photos' / ('live' + suffix)
        published.write_bytes(change(published.read_bytes()))
        refresh(target, main)
        self.assertTrue(publication_metadata.verify(target)['verified'], 'the publication metadata must verify before the public route is asked')
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.verify(target, executable=EXIFTOOL)
        fault = caught.exception.fault
        cause = fault.observed.get('cause', {})
        found, location = cause.get('code', fault.code), cause.get('location', fault.location)
        message = cause.get('message') or fault.message
        self.assertTrue(isinstance(message, str) and message.strip(), 'a refusal states why')
        self.assertEqual(found, code, (label, cause))
        self.assertEqual(location, where, label)
        first = cause['observed']['problems'][0]
        self.assertEqual((first['code'], first['location']), (code, where), label)
        self.assertEqual({k: first.get(k) for k in problem}, problem, (label, first))
        RESULTS[label] = {'id': 'e5:' + label, 'operation': 'editMetadata', 'container': {'.tif': 'tiff', '.dng': 'dng', '.png': 'png', '.webp': 'webp', '.heic': 'heif'}[suffix], 'publicationMetadataVerified': True,
                          'code': found, 'location': location, 'problem': problem, 'message': message, 'route': 'public adaptor.verify after the full refresh', 'independentlyVerified': True}


for _label in CASES:
    setattr(MetadataFirst, 'test_%s' % _label, (lambda label: lambda self: self.check(label))(_label))


if __name__ == '__main__':
    unittest.main()
