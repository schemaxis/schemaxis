"""Metadata-first semantic mutants of real E5 time, location, transfer and minimise runs (genuine ExifTool 13.55 through SCHEMAXIS_EXIFTOOL).

Each mutant edits one fact of the PUBLISHED OUTPUT of a retained real run (a requested value, a protected byte, an untouched value), refreshes every ordinary binding (launcher input digests,
receipt evidence, artifact records, publication metadata) so that ``publication_metadata.verify`` PASSES, and only then asks the public ``adaptor.verify``, which must refuse the run with
the exact semantic code and location of the mutated fact and with the structured fact of its first problem (the protected fingerprint path, the entry, the written source or the stored letter). The expected code, location and fact are literals written here, taken from the E3/E4 JPEG mutant contract (a wrong requested value
is a read-back or transfer mismatch at the field, a changed untouched value is unrequested metadata, a changed protected byte is a preservation mismatch); synthetic edits of retained
records are never counted as native observations.
"""
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import zlib
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools'), str(ROOT / 'tests/unit')]

import exiftool_e4_fixtures as f4  # noqa: E402
import exiftool_e5_fixtures as f  # noqa: E402
import exiftool_e5_time_fixtures as t  # noqa: E402
from schemaxis import publication_metadata  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from exiftool_e4_fixtures import refresh  # noqa: E402

EXIFTOOL = os.environ.get('SCHEMAXIS_EXIFTOOL')
V = 'schemaxis.exiftool/1'
RESULTS = {}
GAMA_CHANGED = f.chunk(b'gAMA', struct.pack('>I', 45456))
HEIC_IMAGE = b'OPAQUE-HVC1-IMAGE-24BYTES'[:24]


def swap(needle, replacement, nth=0):
    def change(data):
        at = -1
        for _ in range(nth + 1):
            at = data.index(needle, at + 1)
        return data[:at] + replacement + data[at + len(needle):]
    return change


def reseal(change):
    """A PNG mutant keeps every chunk CRC valid, so only the semantic fact (not the checksum) is wrong."""
    def go(data):
        out = bytearray(change(data))
        at = 8
        while at + 12 <= len(out):
            length = struct.unpack('>I', out[at:at + 4])[0]
            out[at + 8 + length:at + 12 + length] = struct.pack('>I', zlib.crc32(bytes(out[at + 4:at + 8 + length])) & 0xFFFFFFFF)
            at += 12 + length
        return bytes(out)
    return go


def item(path, ident='live'):
    return {'id': ident, 'path': str(path)}


def correct_time(path, media):
    return {'operation': 'correctTime', 'media': {'items': [item(path)]}, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '3600'}}]}


def set_location(path, media):
    return {'operation': 'setLocation', 'media': {'items': [item(path)]}, 'default': {'latitude': '35.658581', 'longitude': '139.745433'}}


def copy_all(path, media):
    return {'operation': 'copyMetadata', 'media': {'items': [item(media / 'src.jpg', 'src'), item(path)]}, 'source': {'item': 'src'},
            'transfer': {'groups': ['descriptive', 'camera']}, 'policies': {'existing': 'replace'}}


def minimise(path, media):
    return {'operation': 'removeMetadata', 'media': {'items': [item(path)]}, 'categories': ['minimise']}


# label: (container, fixture, document, mutated published bytes, expected code, exact expected public location)
CASES = {
    'time_tiff_exif_value': ('tiff', lambda: t.full_time('tiff'), correct_time, swap(b'2026:03:01 13:00:00', b'2026:03:01 13:00:01'), 'READBACK_MISMATCH', '$.items[0].fields.capturedLocalE3.exif'),
    'time_png_xmp_value': ('png', lambda: t.full_time('png'), correct_time, reseal(swap(b'2026-03-01T13:00:00.12+01:00', b'2026-03-01T13:00:01.12+01:00')), 'READBACK_MISMATCH', '$.items[0].fields.capturedLocalE3.xmp'),
    'time_webp_untouched_make': ('webp', lambda: t.full_time('webp'), correct_time, swap(b'A\x00', b'Z\x00'), 'UNREQUESTED_METADATA_CHANGED', '$.items[0].exif'),
    'time_dng_private_data': ('dng', lambda: t.container('dng', dto='2026:03:01 12:00:00', ifd0_extra=[__import__('author_exiftool_fixtures').entry(0xC634, 7, b'VendorPrivate-0123')]), correct_time,
                              swap(b'VendorPrivate-0123', b'VendorPrivate-0124'), 'PRESERVATION_MISMATCH', '$.items[0].image'),
    'time_heif_image_item': ('heif', lambda: t.full_time('heif'), correct_time, swap(HEIC_IMAGE, HEIC_IMAGE[:-1] + b'X'), 'PRESERVATION_MISMATCH', '$.items[0].image'),
    'location_tiff_latitude_reference': ('tiff', lambda: t.full_time('tiff'), set_location, swap(b'N\x00', b'S\x00'), 'READBACK_MISMATCH', '$.items[0].location.latitude'),
    'location_png_longitude_reference': ('png', lambda: t.full_time('png'), set_location, reseal(swap(b'E\x00', b'W\x00')), 'READBACK_MISMATCH', '$.items[0].location.longitude'),
    'location_png_gamma': ('png', lambda: t.full_time('png'), set_location, swap(f.GAMA, GAMA_CHANGED), 'PRESERVATION_MISMATCH', '$.items[0].image'),
    'copy_tiff_title': ('tiff', lambda: t.full_time('tiff'), copy_all, swap(b'>Harbour<', b'>Xarbour<'), 'TRANSFER_READBACK_MISMATCH', '$.items[1].fields.title'),
    'copy_png_camera_make': ('png', lambda: t.full_time('png'), copy_all, reseal(swap(b'Canon\x00', b'Xanon\x00')), 'TRANSFER_READBACK_MISMATCH', '$.items[1].fields.cameraMake'),
    'copy_webp_bitstream': ('webp', lambda: t.full_time('webp'), copy_all, swap(f.ck(b'VP8 ', f.vp8()), f.ck(b'VP8 ', f.vp8()[:20] + b'\x11' + f.vp8()[21:])), 'PRESERVATION_MISMATCH', '$.items[1].image'),
    'minimise_png_gamma': ('png', t.png_g6, minimise, swap(f.GAMA, GAMA_CHANGED), 'PRESERVATION_MISMATCH', '$.items[0].image'),
    'minimise_png_orientation_changed': ('png', t.png_g6, minimise, reseal(swap(b'\x12\x01\x03\x00\x01\x00\x00\x00\x06\x00', b'\x12\x01\x03\x00\x01\x00\x00\x00\x03\x00')), 'MINIMISE_PRESERVED_CHANGED', '$.items[0].exif'),
    'minimise_webp_vp8_bitstream': ('webp', lambda: t.container('webp', xmp=None), minimise, None, 'PRESERVATION_MISMATCH', '$.items[0].image'),
}

# the first problem of the public refusal, written by hand from the mutated fact: the protected fingerprint path of the changed byte (DNGPrivateData is the IFD0 entry 0xC634; the HEIF image item is item 1; gAMA is
# the first gAMA chunk; VP8 is the first VP8 chunk), the Exif entry of the changed Make (IFD0 0x010F), the written time source with the hand-calculated planned and mutated wall times (12:00:00 + 3600 s = 13:00:00,
# mutated to 13:00:01), the stored reference letter against the requested one, the raw source literal against the mutated literal, and the Exif entry of a changed Orientation (IFD0 0x0112)
PROBLEMS = {
    'time_tiff_exif_value': {'source': 'ExifIFD:0x9003', 'expected': '2026-03-01T13:00:00', 'found': '2026-03-01T13:00:01'},
    'time_png_xmp_value': {'source': 'photoshop:DateCreated', 'expected': '2026-03-01T13:00:00', 'found': '2026-03-01T13:00:01'},
    'time_webp_untouched_make': {'entry': 'IFD0:0x010F'},
    'time_dng_private_data': {'path': 'tiff/entry[IFD0:0xc634]'},
    'time_heif_image_item': {'path': 'heif/item[1]'},
    'location_tiff_latitude_reference': {'expected': 'N', 'stored': 'S'},
    'location_png_longitude_reference': {'expected': 'E', 'stored': 'W'},
    'location_png_gamma': {'path': 'png/ancillary[gAMA#0]'},
    'copy_tiff_title': {'state': 'ambiguous'},
    'copy_png_camera_make': {'expected': 'Canon', 'found': 'Xanon'},
    'copy_webp_bitstream': {'path': 'riff/chunk[VP8 #0]'},
    'minimise_png_gamma': {'path': 'png/ancillary[gAMA#0]'},
    'minimise_png_orientation_changed': {'unexpected': ['IFD0:0x0112 value']},
    'minimise_webp_vp8_bitstream': {'path': 'riff/chunk[VP8 #0]'},
}


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class MetadataFirst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='e5-ops-mutants-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.media = cls.tmp / 'media'
        cls.media.mkdir()
        (cls.media / 'src.jpg').write_bytes(f4.master())
        cls.mains = {}
        for label, (container, make, build, _, _, _) in CASES.items():
            suffix = t.EXTENSIONS[container]
            path = cls.media / (label + suffix)
            path.write_bytes(make())
            main = cls.tmp / ('main-' + label)
            document = {'version': V, **build(path, cls.media)}
            result = adaptor.run(document, main, executable=EXIFTOOL, timeout=300)
            assert result['verified'] and result['written'] == 1, (label, result)
            cls.mains[label] = (main, suffix, document['operation'])

    def check(self, label):
        container, _, _, change, code, where = CASES[label]
        main, suffix, operation = self.mains[label]
        if change is None:                                                    # a WebP bitstream byte of the minimised output
            bitstream = f.ck(b'VP8 ', f.vp8())
            change = swap(bitstream, f.ck(b'VP8 ', f.vp8()[:20] + b'\x11' + f.vp8()[21:]))
        target = self.tmp / ('mf-' + label)
        shutil.copytree(main, target, symlinks=True)
        published = next(p for p in sorted((target / 'photos').glob('live.*')) if not p.name.endswith('.metadata.json'))
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
        problem = PROBLEMS[label]
        self.assertEqual((first['code'], first['location']), (code, where), label)
        self.assertEqual({k: first.get(k) for k in problem}, problem, (label, first))
        RESULTS[label] = {'id': 'e5ops:' + label, 'operation': operation, 'container': container, 'publicationMetadataVerified': True, 'code': found, 'location': location, 'problem': problem, 'message': message,
                          'route': 'public adaptor.verify after the full refresh', 'independentlyVerified': True}


for _label in CASES:
    setattr(MetadataFirst, 'test_%s' % _label, (lambda label: lambda self: self.check(label))(_label))


if __name__ == '__main__':
    unittest.main()
