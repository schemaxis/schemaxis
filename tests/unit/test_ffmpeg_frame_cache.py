"""Per-call reuse of decoded and matted PNG frames in the FFmpeg frame preparation.

`adaptor.frames` decodes each distinct held PNG once per call for encodeFrames. The host tests count real decoder calls and judge
the frames against literal RGB expectations (alpha matted over black, written independently of the implementation). The native
cases run the trusted FFmpeg over repeated A/B/A sequences, compare every decoded frame, and show that forgeries of the
repeated shape are still refused by the fresh native verification. They skip when no FFmpeg with ffprobe is configured."""
import hashlib
import json
from fractions import Fraction
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_ffmpeg_fresh as base   # noqa: E402
from schemaxis.adaptors.ffmpeg import adaptor   # noqa: E402
from schemaxis.core.faults import SchemaxisError   # noqa: E402


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def make_png(width, height, pixels, colour=6, extra=b'', level=6):
    """A literal PNG from (r, g, b, a) tuples (alpha dropped for colour type 2); `extra` is an ancillary chunk that changes the
    bytes without changing a pixel."""
    assert len(pixels) == width * height
    step = 4 if colour == 6 else 3
    rows = b''.join(b'\x00' + b''.join(bytes(pixel[:step]) for pixel in pixels[y * width:(y + 1) * width]) for y in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, colour, 0, 0, 0))
            + extra + chunk(b'IDAT', zlib.compress(rows, level)) + chunk(b'IEND', b''))


def over_black(pixel):
    """The expected RGB of an RGBA pixel, from exact rational arithmetic rather than the implementation's integer form."""
    r, g, b, a = pixel
    return tuple(int(Fraction(c * a, 255) + Fraction(1, 2)) for c in (r, g, b))


def rgb_bytes(pixels):
    return b''.join(bytes(over_black(pixel)) for pixel in pixels)


# Asymmetric channels and a spread of alphas: a swapped channel, a dropped alpha or an unmatted frame cannot match.
PIXELS_A = [(200, 100, 50, 128), (10, 20, 30, 0), (255, 1, 90, 255), (7, 250, 33, 1),
            (90, 180, 45, 254), (1, 2, 3, 64), (250, 60, 120, 200), (13, 77, 201, 255)]
PIXELS_B = [(0, 0, 0, 255), (255, 255, 255, 128), (40, 240, 140, 77), (99, 3, 199, 255),
            (5, 6, 7, 8), (222, 111, 55, 99), (17, 34, 68, 136), (128, 64, 32, 16)]
PIXELS_C = [(9, 8, 7, 255), (70, 80, 90, 255), (1, 255, 2, 255), (3, 4, 5, 255),
            (250, 249, 248, 255), (11, 22, 33, 255), (44, 55, 66, 255), (77, 88, 99, 255)]
A = make_png(4, 2, PIXELS_A)
B = make_png(4, 2, PIXELS_B)
C = make_png(4, 2, PIXELS_C, colour=2)
A_SAME_PIXELS = make_png(4, 2, PIXELS_A, extra=chunk(b'tEXt', b'k\x00v'), level=0)
WIDE = make_png(6, 2, (PIXELS_A + PIXELS_B)[:12])
ODD = make_png(3, 2, PIXELS_B[:6])
EXPECTED = {'A': rgb_bytes(PIXELS_A), 'B': rgb_bytes(PIXELS_B), 'C': rgb_bytes(PIXELS_C)}
PAYLOAD = {'A': A, 'B': B, 'C': C, 'a': A_SAME_PIXELS}
EXPECTED['a'] = EXPECTED['A']


def frames_node(count, **options):
    return adaptor.plan(base.frames_document([f'/in/{i}.png' for i in range(count)], **options))


class Counted:
    """Counts real decoder calls and `frames` invocations without replacing either."""
    def __init__(self):
        self.decodes = 0
        self.calls = 0

    def __enter__(self):
        real_decode, real_frames = adaptor.decode, adaptor.frames
        def decode(data):
            self.decodes += 1
            return real_decode(data)
        def frames(*args, **keywords):
            self.calls += 1
            return real_frames(*args, **keywords)
        self.patches = [mock.patch.object(adaptor, 'decode', decode), mock.patch.object(adaptor, 'frames', frames)]
        for patch in self.patches: patch.start()
        return self

    def __exit__(self, *error):
        for patch in self.patches: patch.stop()


class HostTests(base.FreshCase):
    def prepare(self, letters, **options):
        return frames_node(len(letters), **options), [PAYLOAD[letter] for letter in letters]

    def test_repeated_bytes_decode_once_and_the_frames_keep_their_order_and_pixels(self):
        letters = 'ABACBAAa'
        prepared, payloads = self.prepare(letters)
        with Counted() as counted:
            width, height, pixels = adaptor.frames(prepared, payloads)
        self.assertEqual((width, height), (4, 2))
        self.assertEqual(counted.decodes, 4)           # the bytes of A, B, C and A-with-another-chunk; eight frames
        self.assertEqual(pixels, [EXPECTED[letter] for letter in letters])
        self.assertTrue(all(len(frame) == 4 * 2 * 3 for frame in pixels))
        # Repeats share one immutable RGB buffer; nothing else is retained per frame.
        self.assertIs(pixels[0], pixels[2]); self.assertIs(pixels[0], pixels[5]); self.assertIs(pixels[1], pixels[4])
        self.assertIsNot(pixels[0], pixels[7])         # equal pixels from different bytes are decoded on their own

    def test_one_unique_frame_decodes_once_even_when_the_sequence_is_long(self):
        prepared, payloads = self.prepare('A' * 80)
        with Counted() as counted:
            width, height, pixels = adaptor.frames(prepared, payloads)
        self.assertEqual((counted.decodes, len(pixels)), (1, 80))
        self.assertEqual(b''.join(pixels), EXPECTED['A'] * 80)

    def test_alpha_is_matted_over_black_per_channel_with_literal_values(self):
        prepared, payloads = self.prepare('A')
        _, _, pixels = adaptor.frames(prepared, payloads)
        literal = bytes([100, 50, 25,   0, 0, 0,   255, 1, 90,   0, 1, 0,
                         90, 179, 45,   0, 1, 1,   196, 47, 94,   13, 77, 201])
        self.assertEqual(pixels, [literal])
        self.assertEqual(pixels[0], EXPECTED['A'])
        # An RGB (colour type 2) PNG is fully opaque; its bytes pass through untouched.
        _, _, opaque = adaptor.frames(*self.prepare('C'))
        self.assertEqual(opaque, [b''.join(bytes(pixel[:3]) for pixel in PIXELS_C)])

    def test_cache_never_outlives_a_call_or_follows_a_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'frame.png'
            prepared = adaptor.plan(base.frames_document([source, source]))
            outcomes = []
            with Counted() as counted:
                for letter in ('A', 'B', 'A'):
                    source.write_bytes(PAYLOAD[letter])
                    directory = root / ('run-' + str(len(outcomes)))
                    directory.mkdir()
                    records, payloads = adaptor.read_sources(directory, prepared, True)
                    outcomes.append(adaptor.frames(prepared, payloads)[2])
                    self.assertEqual([r['sha256'] for r in records], [hashlib.sha256(PAYLOAD[letter]).hexdigest()] * 2)
                    self.assertEqual([(directory / r['retained']).read_bytes() for r in records], [PAYLOAD[letter]] * 2)
            self.assertEqual(outcomes, [[EXPECTED[l]] * 2 for l in 'ABA'])
            self.assertEqual((counted.decodes, counted.calls), (3, 3))   # one per call, none carried between calls

    def test_identical_bytes_at_different_paths_are_each_captured_but_decoded_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [root / name for name in ('one.png', 'two.png', 'three.png', 'one.png')]
            for path, letter in zip(paths, 'AABA'):
                path.write_bytes(PAYLOAD[letter])
            prepared = adaptor.plan(base.frames_document(paths))
            records, payloads = adaptor.read_sources(root, prepared, True)
            self.assertEqual(len(records), 4)
            self.assertEqual([record['file'] for record in records], [str(p) for p in paths])
            self.assertEqual([(root / r['retained']).read_bytes() for r in records], [PAYLOAD[l] for l in 'AABA'])
            with Counted() as counted:
                pixels = adaptor.frames(prepared, payloads)[2]
            self.assertEqual((counted.decodes, pixels), (2, [EXPECTED[l] for l in 'AABA']))

    def test_first_bad_source_is_refused_strictly_and_never_cached(self):
        bad = A[:-5]
        for letters, payloads, decodes in (('A,A,bad,A', [A, A, bad, A], 2), ('bad,A', [bad, A], 1),
                                           ('A,bad,bad', [A, bad, bad], 2), ('B,A,A,flipped', [B, A, A, A[:30] + bytes([A[30] ^ 1]) + A[31:]], 3)):
            with self.subTest(letters=letters), Counted() as counted:
                self.fault(lambda: adaptor.frames(frames_node(len(payloads)), payloads), 'INVALID_IMAGE')
                self.assertEqual(counted.decodes, decodes)

    def test_dimension_budget_and_h264_refusals_are_unchanged_for_repeated_frames(self):
        for payloads in ([A, WIDE, A], [A, A, WIDE], [WIDE, A, A]):
            self.fault(lambda: adaptor.frames(frames_node(3), payloads), 'INVALID_IMAGE')
        # Repeats count against the same decoded-frame budget as distinct frames: two 4x2 RGBA frames fit, a third does not.
        with mock.patch.object(adaptor, 'MAX_RGB', 2 * 4 * 2 * 4):
            self.assertEqual(len(adaptor.frames(frames_node(2), [A, A])[2]), 2)
            fault = self.fault(lambda: adaptor.frames(frames_node(3), [A, A, A]), 'RESOURCE_LIMIT')
            self.assertIn('decoded frame budget', fault['message'])
        self.fault(lambda: adaptor.frames(frames_node(2, codec='h264'), [ODD, ODD]), 'INVALID_IMAGE')
        self.assertEqual(adaptor.frames(frames_node(2, codec='ffv1'), [ODD, ODD])[:2], (3, 2))
        self.assertEqual(adaptor.frames(frames_node(2, codec='h264'), [A, A])[:2], (4, 2))

    def test_held_buffers_are_read_once_and_a_mutable_payload_is_not_aliased(self):
        prepared = frames_node(2)
        held = bytearray(A)
        pixels = adaptor.frames(prepared, [held, bytes(held)])[2]
        held[:] = B
        self.assertEqual(pixels, [EXPECTED['A']] * 2)

    def test_encode_sheet_is_unchanged(self):
        sheet = make_png(4, 2, PIXELS_A)
        metadata = json.dumps({'version': 'schemaxis.aseprite.sheet/1', 'width': 4, 'height': 2, 'tags': [],
            'frames': [{'x': 0, 'y': 0, 'width': 2, 'height': 2, 'durationMS': 80},
                       {'x': 2, 'y': 0, 'width': 2, 'height': 2, 'durationMS': 40}]}).encode()
        prepared = adaptor.plan(base.sheet_document('/in/s.png', '/in/s.json', fps=25))
        with Counted() as counted:
            width, height, pixels = adaptor.frames(prepared, [sheet, metadata])
        left = rgb_bytes([PIXELS_A[0], PIXELS_A[1], PIXELS_A[4], PIXELS_A[5]])
        right = rgb_bytes([PIXELS_A[2], PIXELS_A[3], PIXELS_A[6], PIXELS_A[7]])
        self.assertEqual((width, height, counted.decodes), (2, 2, 1))
        self.assertEqual(pixels, [left, left, right])


NATIVE_SEQUENCE = 'ABAABA'


def smooth(seed, alpha=255):
    return [(60 + x * 5 + seed * 20, 80 + y * 6 + seed * 15, 110 + seed * 8, alpha) for y in range(12) for x in range(16)]


def busy(seed, alpha):
    return [((x * 40 + seed * 70) % 256, (y * 50 + seed * 30) % 256, (x * y + seed * 90) % 256, alpha) for y in range(6) for x in range(8)]


@base.native
class NativeTests(base.FreshCase):
    rebind = base.NativeTests.rebind
    reencode = base.NativeTests.reencode
    retained_coherent = base.NativeTests.retained_coherent
    refused_fresh = base.NativeTests.refused_fresh

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='schemaxis-frame-cache-test-'))
        cls.counter = 0
        translucent, opaque = busy(1, 150), busy(2, 255)
        cls.cases = {
            'ffv1': ('ffv1', {'A': make_png(8, 6, translucent), 'B': make_png(8, 6, opaque)},
                     {'A': rgb_bytes(translucent), 'B': rgb_bytes(opaque)}),
            'h264': ('h264', {'A': make_png(16, 12, smooth(1)), 'B': make_png(16, 12, smooth(2))},
                     {'A': rgb_bytes(smooth(1)), 'B': rgb_bytes(smooth(2))})}
        cls.paths = {}
        for label, (codec, pngs, _) in cls.cases.items():
            cls.paths[label] = {}
            for letter, data in pngs.items():
                path = cls.root / f'{label}-{letter}.png'
                path.write_bytes(data)
                cls.paths[label][letter] = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def document(self, label, sequence=NATIVE_SEQUENCE):
        return base.frames_document([self.paths[label][letter] for letter in sequence], codec=self.cases[label][0])

    def run_document(self, document):
        type(self).counter += 1
        directory = self.root / f'run-{self.counter}'
        adaptor.run(document, directory, executable=base.EXECUTABLE)
        return directory

    def test_repeated_sequences_run_verify_and_every_decoded_frame_matches_literal_pixels(self):
        for label, (codec, pngs, expected) in self.cases.items():
            with self.subTest(codec=codec), Counted() as counted:
                directory = self.run_document(self.document(label))
                answer = adaptor.verify(directory)
                self.assertIs(answer['verified'], True)
                self.assertIs(answer['freshNativeVerification'], True)
                self.assertEqual(answer['frames'], len(NATIVE_SEQUENCE))
                # Each frames() invocation (run, its own verify, the fresh pass, then the standalone verify) decodes two
                # distinct PNGs rather than six: nothing is shared between invocations.
                self.assertGreaterEqual(counted.calls, 4)
                self.assertEqual(counted.decodes, 2 * counted.calls)
                literal = b''.join(expected[letter] for letter in NATIVE_SEQUENCE)
                self.assertEqual((directory / 'frames.rgb').read_bytes(), literal)
                decoded = (directory / 'decoded.rgb').read_bytes()
                size = len(expected['A'])
                self.assertEqual(len(decoded), len(literal))
                for index, letter in enumerate(NATIVE_SEQUENCE):
                    got, want = decoded[index * size:(index + 1) * size], expected[letter]
                    error = sum(abs(a - b) for a, b in zip(got, want)) / size
                    self.assertLessEqual(error, 0 if codec == 'ffv1' else 16, (index, letter))
                    if codec == 'ffv1':
                        self.assertEqual(got, want)

    def test_native_input_and_decode_equal_those_of_the_one_file_per_frame_run(self):
        """Distinct files with the same bytes and one repeated file give the encoder identical input (Matroska bytes carry
        per-run identifiers, so the encoder input and its decode are compared)."""
        directory = self.run_document(self.document('ffv1'))
        distinct = []
        for index, letter in enumerate(NATIVE_SEQUENCE):
            path = self.root / f'copy-{index}-{letter}.png'
            path.write_bytes(self.cases['ffv1'][1][letter])
            distinct.append(path)
        other = self.run_document(base.frames_document(distinct, codec='ffv1'))
        self.assertEqual((directory / 'frames.rgb').read_bytes(), (other / 'frames.rgb').read_bytes())
        self.assertEqual((directory / 'decoded.rgb').read_bytes(), (other / 'decoded.rgb').read_bytes())

    def test_a_forged_order_or_one_wrong_frame_in_the_repeated_shape_is_refused_fresh(self):
        for label in ('ffv1', 'h264'):
            raw_expected = self.cases[label][2]
            size = len(raw_expected['A'])
            for name, letters in (('swapped', 'BAAABA'), ('one-wrong', 'ABABBA'), ('dropped', 'ABAAB'), ('extra', 'ABAABAB')):
                with self.subTest(codec=label, forgery=name):
                    directory = self.run_document(self.document(label))
                    forged = self.reencode(directory, b''.join(raw_expected[letter] for letter in letters))
                    output = adaptor.plan(json.loads((directory / 'authored.json').read_text()))['output']
                    (directory / output).write_bytes(forged)
                    self.rebind(directory)
                    if label == 'ffv1': self.assertEqual(self.retained_coherent(directory), 0.0)   # retained evidence is coherent
                    self.refused_fresh(directory)

    def test_a_retained_source_changed_after_the_run_is_refused(self):
        directory = self.run_document(self.document('ffv1'))
        retained = directory / 'input-0002'
        self.assertEqual(retained.read_bytes(), self.cases['ffv1'][1]['A'])
        retained.write_bytes(self.cases['ffv1'][1]['B'])
        with self.assertRaises(SchemaxisError):
            adaptor.verify(directory)


if __name__ == '__main__':
    unittest.main()
