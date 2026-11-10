"""muxReview host contracts: strict WAV/SRT parsing, exact duration policy, membership and command shape.

Native muxing, readback and tamper behaviour live in tools/qualify_ffmpeg_review.py."""
import copy
import hashlib
import json
import os
from fractions import Fraction
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from schemaxis.adaptors.ffmpeg import adaptor, review, video
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]


def document(**options):
    return {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'review', 'filter': 'muxReview', 'options': {
        'video': '/input/silent.mkv', 'audio': '/input/speech.wav', 'captions': '/input/captions.srt', **options}}]}


def wav(samples=16, channels=1, rate=16000, tag=1, bits=16):
    align = channels * bits // 8
    data = b''.join(struct.pack('<h', i - 8) for i in range(samples * channels))
    return (b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, tag, channels, rate, rate * align, align, bits)
            + b'data' + struct.pack('<I', len(data)) + data)


PCM_GUID = bytes.fromhex('0100000000001000800000aa00389b71')
FLOAT_GUID = bytes.fromhex('0300000000001000800000aa00389b71')


def native_wav(samples=16, channels=1, rate=96000, **fields):
    """FFmpeg's fmt-40 WAVE_FORMAT_EXTENSIBLE PCM16 layout; any field may be overridden to build a defect."""
    bits, align = fields.get('bits', 16), fields.get('align', channels * 2)
    data = fields.get('data') if 'data' in fields else b''.join(struct.pack('<h', (i * 977) % 2001 - 1000) for i in range(samples * channels))
    fmt = struct.pack('<IHHIIHHHHI', fields.get('size', 40), fields.get('tag', 0xFFFE), fields.get('declared', channels), rate,
                      fields.get('byte_rate', rate * channels * 2), align, bits, fields.get('extension', 22), fields.get('valid', 16),
                      fields.get('mask', {1: 4, 2: 3}.get(channels, 0))) + fields.get('guid', PCM_GUID)
    body = b'WAVEfmt ' + fmt + fields.get('chunk', b'data') + struct.pack('<I', len(data)) + data
    return b'RIFF' + struct.pack('<I', len(body)) + body


def srt(*cues):
    return ''.join(f'{i}\n{review_clock(s)} --> {review_clock(e)}\n{t}\n\n' for i, (s, e, t) in enumerate(cues, 1)).encode()


def review_clock(ms):
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


class ReviewTests(unittest.TestCase):
    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def test_plan_defaults_are_immutable_and_declare_status_and_losses(self):
        authored = document(); original = copy.deepcopy(authored)
        planned = adaptor.plan(authored)
        self.assertEqual(authored, original)
        options = planned['nodes'][0]['options']
        self.assertEqual((options['captionStatus'], options['threads']), ('machineDraft', 1))
        self.assertEqual(planned['output'], 'review.mkv')
        self.assertEqual(video.source_paths(planned['nodes'][0]), ['/input/silent.mkv', '/input/speech.wav', '/input/captions.srt'])
        self.assertTrue(any('machine-draft' in loss and 'not verified' in loss for loss in planned['losses']))
        self.assertIn('one video frame period', planned['policy'])

    def test_plan_rejects_extra_options_wrong_extensions_and_deliverable(self):
        for options, code in (({'codec': 'h264'}, 'UNKNOWN_ARGUMENT'), ({'fps': 25}, 'UNKNOWN_ARGUMENT'),
                              ({'vf': 'subtitles=x.srt'}, 'UNKNOWN_ARGUMENT'), ({'map': '0:a'}, 'UNKNOWN_ARGUMENT'),
                              ({'captionStatus': 'verifiedHuman'}, 'INVALID_ARGUMENT'),
                              ({'video': '/input/silent.mp4'}, 'UNSUPPORTED_VIDEO'), ({'audio': '/input/speech.mp3'}, 'UNSUPPORTED_AUDIO'),
                              ({'captions': '/input/captions.vtt'}, 'UNSUPPORTED_CAPTIONS'), ({'video': 'silent.mkv'}, 'INVALID_RESOURCE'),
                              ({'threads': 17}, 'INVALID_ARGUMENT')):
            with self.subTest(options=options):
                self.fault(lambda: adaptor.plan(document(**options)), code)
        missing = document(); del missing['nodes'][0]['options']['captions']
        self.fault(lambda: adaptor.plan(missing), 'MISSING_ARGUMENT')
        self.fault(lambda: adaptor.plan({**document(), 'deliverable': {'frames': 6}}), 'INVALID_ARGUMENT')

    def test_schema_requires_three_inputs_and_closes_options(self):
        import jsonschema
        validator = jsonschema.Draft202012Validator(adaptor.schema())
        self.assertTrue(validator.is_valid(document()))
        self.assertTrue(validator.is_valid(document(captionStatus='declaredHumanReviewed')))
        self.assertFalse(validator.is_valid(document(captionStatus='certified')))
        self.assertFalse(validator.is_valid(document(codec='aac')))
        authored = document(); del authored['nodes'][0]['options']['audio']
        self.assertFalse(validator.is_valid(authored))

    def test_route_accepts_video_and_file_artifacts_and_existing_operations_keep_their_options(self):
        manifest = json.loads((ROOT / 'src/schemaxis/adaptors/ffmpeg/adaptor.json').read_text())
        accepted = manifest['routes']['schemaxis.ffmpeg/1']['acceptedArtifacts']
        self.assertIn('video', accepted); self.assertIn('file', accepted)
        self.assertEqual(list(adaptor.DECLARATIONS['encodeVideo']['options']), ['fps', 'codec', 'threads', 'file', 'startFrame', 'endFrame'])
        self.assertEqual(list(adaptor.DECLARATIONS['muxReview']['options']), ['threads', 'video', 'audio', 'captions', 'captionStatus'])

    def test_wav_accepts_only_canonical_pcm16(self):
        mono = review.parse_wav(wav(16))
        self.assertEqual((mono['channels'], mono['sampleRate'], mono['samples'], mono['bytes']), (1, 16000, 16, 32))
        stereo = review.parse_wav(wav(8, 2, 48000))
        self.assertEqual((stereo['channels'], stereo['samples']), (2, 8))
        good = wav(16)
        cases = {'float': (wav(tag=3), 'UNSUPPORTED_AUDIO'), 'eight-bit': (wav(bits=8), 'UNSUPPORTED_AUDIO'),
                 'three channels': (wav(channels=3), 'UNSUPPORTED_AUDIO'), 'low rate': (wav(rate=4000), 'UNSUPPORTED_AUDIO'),
                 'extensible fmt': (good[:16] + struct.pack('<I', 40) + good[20:], 'UNSUPPORTED_AUDIO'),
                 'truncated': (good[:-2], 'INVALID_RESOURCE'), 'trailing bytes': (good + b'\0\0', 'INVALID_RESOURCE'),
                 'empty data': (wav(0), 'INVALID_RESOURCE'), 'garbage': (b'ID3' * 40, 'INVALID_RESOURCE'),
                 'list chunk': (good[:12] + good[12:36] + b'LIST' + struct.pack('<I', 4) + b'abcd' + good[36:], 'INVALID_RESOURCE'),
                 'bad alignment': (good[:32] + struct.pack('<H', 4) + good[34:], 'INVALID_RESOURCE')}
        riff_fixed = lambda data: data[:4] + struct.pack('<I', len(data) - 8) + data[8:]
        cases['list chunk fixed size'] = (riff_fixed(cases['list chunk'][0]), 'UNSUPPORTED_AUDIO')
        for label, (data, code) in cases.items():
            with self.subTest(label):
                self.fault(lambda: review.parse_wav(data), code)

    def test_native_readback_accepts_ffmpeg_extensible_pcm16_and_the_source_contract_does_not_widen(self):
        # Header bytes as captured from the trusted FFmpeg for 96 kHz mono (fmt 40, tag 65534, PCM sub-format, mask 4).
        captured = bytes.fromhex('524946460601000057415645666d742028000000feff01000077010000ee02000200100016001000'
                                 '040000000100000000001000800000aa00389b7164617461ca000000') + bytes(202)
        self.assertEqual(review.parse_native_wav(captured)['samples'], 101)
        self.assertEqual(captured[:68], native_wav(101, 1)[:68])
        for channels, rate, samples in ((1, 96000, 16385), (2, 96000, 8193), (1, 64000, 7), (2, 50000, 5), (1, 96000, 1)):
            with self.subTest(channels=channels, rate=rate, samples=samples):
                data = native_wav(samples, channels, rate)
                echo = review.parse_native_wav(data)
                self.assertEqual((echo['channels'], echo['sampleRate'], echo['samples'], echo['bytes']),
                                 (channels, rate, samples, samples * channels * 2))
                self.assertEqual(bytes(echo['pcm']), data[68:])
                # The canonical source contract still refuses every fmt-40 file, however well formed.
                self.fault(lambda: review.parse_wav(data), 'UNSUPPORTED_AUDIO')
        # Genuine canonical readbacks (8/16/22.05/48 kHz) take the same native parser unchanged.
        for rate, channels in ((8000, 1), (16000, 1), (22050, 1), (48000, 2)):
            data = wav(9, channels, rate)
            self.assertEqual(review.parse_native_wav(data)['samples'], 9)
            self.assertEqual(bytes(review.parse_native_wav(data)['pcm']), bytes(review.parse_wav(data)['pcm']))
        # Source WAV at 96 kHz is canonical and admitted; above 96 kHz stays UNSUPPORTED_AUDIO at input and at readback.
        self.assertEqual(review.parse_wav(wav(9, 1, 96000))['sampleRate'], 96000)
        self.fault(lambda: review.parse_wav(wav(9, 1, 192000)), 'UNSUPPORTED_AUDIO')
        self.assertEqual(self.fault(lambda: review.parse_native_wav(native_wav(9, 1, 192000)), 'VERIFICATION_FAILED').observed['cause'],
                         'UNSUPPORTED_AUDIO')

    def test_native_readback_refuses_every_extensible_defect_as_a_verification_fault(self):
        good = native_wav(8, 1)
        stereo = native_wav(8, 2)
        float_pcm = b''.join(struct.pack('<f', i / 10) for i in range(8))
        cases = {'float sub-format': native_wav(8, 1, guid=FLOAT_GUID), 'zeroed sub-format': native_wav(8, 1, guid=bytes(16)),
                 'last GUID byte': native_wav(8, 1, guid=PCM_GUID[:-1] + b'\x72'),
                 'float tag': native_wav(8, 1, tag=3), 'pcm tag with fmt 40': native_wav(8, 1, tag=1),
                 'valid bits 8': native_wav(8, 1, valid=8), 'valid bits 24': native_wav(8, 1, valid=24),
                 'valid bits 15': native_wav(8, 1, valid=15), 'extension 0': native_wav(8, 1, extension=0),
                 'extension 24': native_wav(8, 1, extension=24), 'bits 24': native_wav(8, 1, bits=24),
                 'bits 32 float data': native_wav(8, 1, bits=32, data=float_pcm),
                 'mono mask stereo': native_wav(8, 1, mask=3), 'mono mask zero': native_wav(8, 1, mask=0),
                 'stereo mask centre': native_wav(8, 2, mask=4), 'stereo mask swapped bit': native_wav(8, 2, mask=5),
                 'stereo mask 5.1': native_wav(8, 2, mask=0x3F), 'three channels': native_wav(8, 3, mask=7),
                 'zero channels': native_wav(8, 1, declared=0), 'rate 192000': native_wav(8, 1, 192000),
                 'rate 7999': native_wav(8, 1, 7999), 'byte rate': native_wav(8, 1, byte_rate=96000), 'align': native_wav(8, 1, align=4),
                 'stereo align': native_wav(8, 2, align=2),
                 'fmt 18': native_wav(8, 1, size=18), 'fmt 41': native_wav(8, 1, size=41), 'fmt 20': native_wav(8, 1, size=20),
                 'fact chunk': native_wav(8, 1, chunk=b'fact'), 'list chunk': native_wav(8, 1, chunk=b'LIST'),
                 'empty data': native_wav(0, 1), 'half sample': native_wav(8, 1, data=bytes(15)), 'stereo half frame': native_wav(8, 2, data=bytes(30)),
                 '48 kHz with the extensible fmt': native_wav(8, 1, 48000), '16 kHz stereo with the extensible fmt': native_wav(8, 2, 16000),
                 '96 kHz with the canonical fmt': wav(8, 1, 96000), '64 kHz stereo with the canonical fmt': wav(8, 2, 64000),
                 'truncated pcm': good[:-2], 'truncated in extension': good[:50], 'truncated before data': good[:62],
                 'trailing bytes': good + bytes(2), 'garbage': b'ID3' * 40, 'missing data size': good[:64]}
        for label, data in cases.items():
            with self.subTest(label):
                fault = self.fault(lambda: review.parse_native_wav(data), 'VERIFICATION_FAILED')
                self.assertEqual((fault.observed['stage'], fault.location), ('decode-audio', 'decoded-audio.wav'))
        riff_fixed = lambda data: data[:4] + struct.pack('<I', len(data) - 8) + data[8:]
        self.fault(lambda: review.parse_native_wav(riff_fixed(good[:-2])), 'VERIFICATION_FAILED')    # data size now disagrees
        self.fault(lambda: review.parse_native_wav(good[:4] + struct.pack('<I', len(good) - 4) + good[8:]), 'VERIFICATION_FAILED')
        self.assertEqual(review.parse_native_wav(stereo)['channels'], 2)

    def test_native_readback_layout_follows_the_rate_exactly_at_the_48_khz_boundary(self):
        for rate, channels in ((8000, 1), (22050, 1), (48000, 1), (48000, 2)):
            self.assertEqual(review.parse_native_wav(wav(9, channels, rate))['sampleRate'], rate)
            fault = self.fault(lambda: review.parse_native_wav(native_wav(9, channels, rate)), 'VERIFICATION_FAILED')
            self.assertEqual((fault.observed['cause'], fault.observed['stage']), ('UNSUPPORTED_AUDIO', 'decode-audio'))
        for rate, channels in ((48001, 1), (64000, 2), (96000, 1), (96000, 2)):
            self.assertEqual(review.parse_native_wav(native_wav(9, channels, rate))['sampleRate'], rate)
            self.fault(lambda: review.parse_native_wav(wav(9, channels, rate)), 'VERIFICATION_FAILED')

    def test_internal_readback_cap_adds_only_the_extensible_header_overhead(self):
        self.assertEqual((review.MAX_BYTES, review.NATIVE_WAV_OVERHEAD, review.MAX_READBACK_WAV),
                         (32 * 1024 * 1024, 24, 32 * 1024 * 1024 + 24))
        self.assertEqual(len(native_wav(1, 1, 96000)) - len(wav(1, 1, 96000)), review.NATIVE_WAV_OVERHEAD)
        frames = (review.MAX_BYTES - 44) // 2
        pcm = bytes(frames * 2)
        source = wav(0, 1, 96000)[:-4] + struct.pack('<I', len(pcm)) + pcm
        source = source[:4] + struct.pack('<I', len(source) - 8) + source[8:]
        self.assertEqual(len(source), review.MAX_BYTES)
        echo = native_wav(0, 1, 96000, data=pcm)
        self.assertEqual(len(echo), review.MAX_READBACK_WAV)
        with tempfile.TemporaryDirectory() as scratch, mock.patch.object(review, 'source_read', return_value=(1, 1, 6, 10, b'x' * 3)), \
                mock.patch.object(review, 'validate_probe'), mock.patch.object(review, 'check_video'), \
                mock.patch.object(review, 'alignment', return_value={}), mock.patch.object(review, 'cue_digest', return_value=''):
            observed = Path(scratch)
            (observed / 'probe.stdout').write_text('{}'); (observed / 'decoded.rgb').write_bytes(b'x' * 3)
            (observed / 'extracted.srt').write_bytes(srt((0, 500, 'a'))); (observed / 'decoded-audio.wav').write_bytes(echo)
            held = [b'video', source, srt((0, 500, 'a'))]
            facts = review.assess(held, observed, b'review')
            self.assertEqual((facts['audio']['sampleRate'], facts['audio']['bytes']), (96000, len(pcm)))
            self.assertEqual(facts['digests']['decodedPCM'], hashlib.sha256(pcm).hexdigest())
            # One byte beyond the internal cap is refused by size, before any parsing, and PCM is still compared exactly.
            (observed / 'decoded-audio.wav').write_bytes(echo + b'\0')
            fault = self.fault(lambda: review.assess(held, observed, b'review'), 'VERIFICATION_FAILED')
            self.assertEqual((fault.message, fault.location), ('required bounded native readback is absent or oversized', 'decoded-audio.wav'))
            changed = bytearray(echo); changed[-1] ^= 1
            (observed / 'decoded-audio.wav').write_bytes(bytes(changed))
            self.assertEqual(self.fault(lambda: review.assess(held, observed, b'review'), 'VERIFICATION_FAILED').observed['stage'], 'decode-audio')
        # The source budget itself is unchanged: native commands, launcher limits and the source cap in the shared reader.
        self.assertIn(str(review.MAX_BYTES + 1), review.commands('/ffmpeg', Path('/run'), {'threads': 1})['decode-audio'])
        self.assertNotIn(str(review.MAX_READBACK_WAV + 1), review.commands('/ffmpeg', Path('/run'), {'threads': 1})['decode-audio'])

    def test_retained_readback_comparison_uses_the_native_parser_and_refuses_changed_pcm(self):
        cues = [(0, 500, 'a')]
        for channels, rate in ((1, 96000), (2, 96000), (1, 48000)):
            source = wav(9, channels, rate)
            echo = native_wav(9, channels, rate, data=source[44:]) if rate > 48000 else source
            with tempfile.TemporaryDirectory() as scratch, mock.patch.object(review, 'source_read', return_value=(1, 1, 6, 10, b'x' * 3)), \
                    mock.patch.object(review, 'validate_probe'), mock.patch.object(review, 'check_video'), \
                    mock.patch.object(review, 'alignment', return_value={}):
                observed = Path(scratch)
                (observed / 'probe.stdout').write_text('{}'); (observed / 'decoded.rgb').write_bytes(b'x' * 3)
                (observed / 'extracted.srt').write_bytes(srt(*cues)); (observed / 'decoded-audio.wav').write_bytes(echo)
                held = [b'video', source, srt(*cues)]
                facts = review.assess(held, observed, b'review')
                self.assertEqual((facts['audio']['channels'], facts['audio']['sampleRate'], facts['audio']['samples']), (channels, rate, 9))
                self.assertEqual(facts['digests']['decodedPCM'], hashlib.sha256(source[44:]).hexdigest())
                changed = bytearray(echo); changed[-1] ^= 1
                (observed / 'decoded-audio.wav').write_bytes(bytes(changed))
                fault = self.fault(lambda: review.assess(held, observed, b'review'), 'VERIFICATION_FAILED')
                self.assertEqual(fault.observed['stage'], 'decode-audio')
                (observed / 'decoded-audio.wav').write_bytes(echo.replace(PCM_GUID, FLOAT_GUID) if rate > 48000 else echo[:-2])
                self.assertEqual(self.fault(lambda: review.assess(held, observed, b'review'), 'VERIFICATION_FAILED').observed['stage'], 'decode-audio')
                # A native echo at another rate or length than the captured WAV is also refused.
                other = native_wav(9, channels, 64000) if rate > 48000 else native_wav(9, channels, rate + 1)
                (observed / 'decoded-audio.wav').write_bytes(other)
                self.fault(lambda: review.assess(held, observed, b'review'), 'VERIFICATION_FAILED')

    def test_srt_accepts_strict_plain_text_and_crlf(self):
        cues = review.parse_srt(srt((0, 250, 'First, café & "quotes"'), (250, 600, 'Two\nlines')))
        self.assertEqual(cues, [(0, 250, 'First, café & "quotes"'), (250, 600, 'Two\nlines')])
        self.assertEqual(review.parse_srt(srt((0, 250, 'a')).replace(b'\n', b'\r\n')), [(0, 250, 'a')])
        self.assertEqual(review.parse_srt(srt((3723004, 3723999, 'late'))), [(3723004, 3723999, 'late')])
        self.assertEqual(review.parse_srt(srt((0, 5, 'a'))[:-1]), [(0, 5, 'a')])

    def test_srt_rejections_are_distinct(self):
        good = srt((0, 250, 'a'), (300, 600, 'b'))
        cases = {'markup': (good.replace(b'a', b'<i>a</i>'), 'UNSUPPORTED_CAPTIONS'),
                 'ass override': (good.replace(b'\na\n', b'\n{\\an8}a\n'), 'UNSUPPORTED_CAPTIONS'),
                 'bidi override': (good.replace(b'\nb\n', '\nb‮\n'.encode()), 'UNSUPPORTED_CAPTIONS'),
                 'zero width joiner': (good.replace(b'\nb\n', '\nb‍\n'.encode()), 'UNSUPPORTED_CAPTIONS'),
                 'control character': (good.replace(b'\nb\n', b'\nb\x07\n'), 'UNSUPPORTED_CAPTIONS'),
                 'nbsp': (good.replace(b'\nb\n', '\nb c\n'.encode()), 'UNSUPPORTED_CAPTIONS'),
                 'overlap': (srt((0, 400, 'a'), (399, 600, 'b')), 'INVALID_RESOURCE'),
                 'out of order': (srt((300, 600, 'a'), (0, 250, 'b')), 'INVALID_RESOURCE'),
                 'zero length': (srt((10, 10, 'a')), 'INVALID_RESOURCE'),
                 'negative length': (srt((20, 10, 'a')), 'INVALID_RESOURCE'),
                 'index gap': (good.replace(b'2\n', b'3\n', 1), 'INVALID_RESOURCE'),
                 'index from zero': (good.replace(b'1\n', b'0\n', 1), 'INVALID_RESOURCE'),
                 'leading zero index': (good.replace(b'1\n', b'01\n', 1), 'INVALID_RESOURCE'),
                 'position': (good.replace(b'250', b'250 X1:0'), 'INVALID_RESOURCE'),
                 'dot milliseconds': (good.replace(b'00:00:00,250', b'00:00:00.250'), 'INVALID_RESOURCE'),
                 'minutes 60': (good.replace(b'00:00:00,250', b'00:60:00,250'), 'INVALID_RESOURCE'),
                 'empty text': (b'1\n00:00:00,000 --> 00:00:00,250\n\n', 'INVALID_RESOURCE'),
                 'leading space': (good.replace(b'\na\n', b'\n a\n'), 'INVALID_RESOURCE'),
                 'trailing space': (good.replace(b'\na\n', b'\na \n'), 'INVALID_RESOURCE'),
                 'bom': (b'\xef\xbb\xbf' + good, 'INVALID_RESOURCE'), 'latin1': (good.replace(b'a', b'\xe9', 1), 'INVALID_RESOURCE'),
                 'no cues': (b'', 'INVALID_RESOURCE'), 'extra blank lines': (good + b'\n', 'INVALID_RESOURCE'),
                 'mixed line endings': (good.replace(b'\n', b'\r\n', 1), 'INVALID_RESOURCE'),
                 'no final newline in text': (b'1\n00:00:00,000 --> 00:00:00,250\na', 'INVALID_RESOURCE'),
                 'five lines': (srt((0, 5, 'a\nb\nc\nd\ne')), 'RESOURCE_LIMIT'),
                 'long text': (srt((0, 5, 'x' * 501)), 'RESOURCE_LIMIT'),
                 'cue count': (srt(*[(i * 10, i * 10 + 5, 'x') for i in range(review.MAX_CUES + 1)]), 'RESOURCE_LIMIT'),
                 'bytes': (b'1' * (review.MAX_CAPTION_BYTES + 1), 'RESOURCE_LIMIT')}
        for label, (data, code) in cases.items():
            with self.subTest(label):
                self.fault(lambda: review.parse_srt(data), code)
        self.assertEqual(len(review.parse_srt(srt(*[(i * 10, i * 10 + 5, 'x') for i in range(review.MAX_CUES)]))), review.MAX_CUES)

    def test_duration_policy_is_exact_rational_at_the_boundary(self):
        cues = [(0, 100, 'a')]
        # 10 fps, 6 frames = 0.6 s; one frame period is 0.1 s = 1600 samples at 16 kHz.
        self.assertEqual(review.alignment(9600, 16000, 6, 10, cues)['differenceSeconds'], '0/1')
        for samples in (8000, 11200):
            self.assertTrue(review.alignment(samples, 16000, 6, 10, cues)['accepted'])
        for samples, difference in ((7999, '1601/16000'), (11201, '1601/16000')):
            fault = self.fault(lambda: review.alignment(samples, 16000, 6, 10, cues), 'MEDIA_DURATION_MISMATCH')
            self.assertEqual(fault.observed['differenceSeconds'], difference)
            self.assertEqual(fault.observed['toleranceSeconds'], '1/10')
        # 44.1 kHz at 30 fps: three frames are 0.1 s; one frame is 1470 samples, a non-terminating binary fraction.
        self.assertTrue(review.alignment(4410 + 1470, 44100, 3, 30, cues)['accepted'])
        self.fault(lambda: review.alignment(4410 + 1471, 44100, 3, 30, cues), 'MEDIA_DURATION_MISMATCH')
        self.assertEqual(review.ratio(Fraction(2, 6)), '1/3')

    def test_captions_must_end_inside_the_video(self):
        self.assertTrue(review.alignment(9600, 16000, 6, 10, [(0, 600, 'a')])['accepted'])
        self.fault(lambda: review.alignment(9600, 16000, 6, 10, [(0, 601, 'a')]), 'CAPTIONS_OUT_OF_RANGE')

    def test_command_recipe_maps_exactly_three_streams_without_conversion_or_network(self):
        directory = Path('/run')
        options = adaptor.plan(document())['nodes'][0]['options']
        recipe = review.commands('/runtime/ffmpeg', directory, options)
        encode = recipe['encode']
        self.assertEqual(encode.count('-i'), 3)
        self.assertEqual([encode[i + 1] for i, v in enumerate(encode) if v == '-map'], ['0:v:0', '1:a:0', '2:s:0'])
        for pair in (['-c:v', 'copy'], ['-c:a', 'copy'], ['-c:s', 'copy'], ['-map_metadata', '-1'], ['-map_chapters', '-1'],
                     ['-protocol_whitelist', 'file'], ['-fflags', '+bitexact'], ['-f', 'srt'], ['-f', 'wav'], ['-f', 'matroska']):
            self.assertTrue(any(encode[i:i + 2] == pair for i in range(len(encode) - 1)), pair)
        for forbidden in ('-vf', '-af', '-filter_complex', '-attach', '-ar', '-ac', '-shortest', '-t', '-ss', '-c:v:0', 'libx264', 'aac'):
            self.assertNotIn(forbidden, encode)
        self.assertEqual(recipe['probe'][0], '/runtime/ffprobe')
        self.assertIn('0:a:0', recipe['decode-audio']); self.assertIn('0:s:0', recipe['extract-captions'])
        self.assertIn('pcm_s16le', recipe['decode-audio']); self.assertIn('srt', recipe['extract-captions'])
        self.assertEqual(recipe['decode'][recipe['decode'].index('-pix_fmt') + 1], 'rgb24')
        for stage, command in recipe.items():
            self.assertNotIn('http', ' '.join(command), stage)

    def probe(self):
        return {'streams': [
            {'index': 0, 'codec_type': 'video', 'codec_name': 'ffv1', 'pix_fmt': 'bgr0', 'width': 32, 'height': 24,
             'nb_read_frames': '6', 'avg_frame_rate': '10/1', 'start_time': '0.000000', 'tags': {'DURATION': '00:00:00.600000000'}},
            {'index': 1, 'codec_type': 'audio', 'codec_name': 'pcm_s16le', 'sample_fmt': 's16', 'bits_per_sample': 16,
             'sample_rate': '16000', 'channels': 1, 'start_time': '0.000000', 'tags': {'DURATION': '00:00:00.600000000'}},
            {'index': 2, 'codec_type': 'subtitle', 'codec_name': 'subrip', 'start_time': '0.000000', 'tags': {'DURATION': '00:00:00.600000000'}}],
            'chapters': [], 'format': {'format_name': 'matroska,webm', 'nb_streams': 3, 'nb_programs': 0, 'start_time': '0.000000',
                                       'duration': '0.600000', 'tags': {'encoder': 'Lavf'}}}

    def test_probe_membership_and_metadata(self):
        audio = {'sampleRate': 16000, 'channels': 1, 'samples': 9600}
        review.validate_probe(self.probe(), 32, 24, 6, Fraction(10), audio)
        def mutate(change):
            value = self.probe(); change(value); return value
        cases = {'missing subtitle': lambda v: v['streams'].pop(),
                 'extra attachment': lambda v: v['streams'].append({'index': 3, 'codec_type': 'attachment', 'codec_name': 'ttf'}),
                 'extra data': lambda v: v['streams'].append({'index': 3, 'codec_type': 'data', 'codec_name': 'bin_data'}),
                 'order': lambda v: v['streams'].reverse(),
                 'ass': lambda v: v['streams'][2].update(codec_name='ass'),
                 'aac': lambda v: v['streams'][1].update(codec_name='aac'),
                 'rate': lambda v: v['streams'][1].update(sample_rate='48000'),
                 'channels': lambda v: v['streams'][1].update(channels=2),
                 'h264': lambda v: v['streams'][0].update(codec_name='h264', pix_fmt='yuv420p'),
                 'pixel format': lambda v: v['streams'][0].update(pix_fmt='rgb24'),
                 'frames': lambda v: v['streams'][0].update(nb_read_frames='5'),
                 'size': lambda v: v['streams'][0].update(width=34),
                 'fps': lambda v: v['streams'][0].update(avg_frame_rate='12/1'),
                 'stream tag': lambda v: v['streams'][1].update(tags={'title': 'x'}),
                 'chapter': lambda v: v.update(chapters=[{'id': 1}]),
                 'format tag': lambda v: v['format'].update(tags={'title': 'x'}),
                 'container': lambda v: v['format'].update(format_name='mov,mp4,m4a,3gp,3g2,mj2'),
                 'program': lambda v: v['format'].update(nb_programs=1),
                 'audio starts late': lambda v: v['streams'][1].update(start_time='0.500000'),
                 'audio starts early': lambda v: v['streams'][1].update(start_time='-0.050000'),
                 'video starts late': lambda v: v['streams'][0].update(start_time='0.100000'),
                 'container starts late': lambda v: v['format'].update(start_time='0.050000'),
                 'start missing': lambda v: v['streams'][0].pop('start_time'),
                 'start not available': lambda v: v['streams'][1].update(start_time='N/A'),
                 'start not finite': lambda v: v['streams'][0].update(start_time='nan'),
                 'start exponent': lambda v: v['streams'][0].update(start_time='0e0'),
                 'start number type': lambda v: v['streams'][0].update(start_time=0.0),
                 'subtitle before zero': lambda v: v['streams'][2].update(start_time='-0.100000'),
                 'subtitle unparsable': lambda v: v['streams'][2].update(start_time='soon'),
                 'container shorter': lambda v: v['format'].update(duration='0.400000'),
                 'container longer by an audio offset': lambda v: v['format'].update(duration='1.100000'),
                 'container duration missing': lambda v: v['format'].pop('duration')}
        for label, change in cases.items():
            with self.subTest(label):
                self.fault(lambda: review.validate_probe(mutate(change), 32, 24, 6, Fraction(10), audio), 'VERIFICATION_FAILED')

    def test_subtitle_may_start_later_and_the_container_duration_has_a_one_frame_tolerance(self):
        audio = {'sampleRate': 16000, 'channels': 1, 'samples': 9600}
        value = self.probe(); value['streams'][2]['start_time'] = '0.300000'
        review.validate_probe(value, 32, 24, 6, Fraction(10), audio)
        for duration in ('0.500000', '0.700000', '0.6011', '0.5'):
            value = self.probe(); value['format']['duration'] = duration
            review.validate_probe(value, 32, 24, 6, Fraction(10), audio)
        # ms-rounded 24 and 30 fps clips: 0.5 s of audio, start zero, duration rounded to the millisecond.
        for fps, frames, duration in ((24, 12, '0.500000'), (30, 15, '0.501000'), (24, 12, '0.499000')):
            value = self.probe(); value['streams'][0].update(nb_read_frames=str(frames), avg_frame_rate=f'{fps}/1')
            value['format']['duration'] = duration
            review.validate_probe(value, 32, 24, frames, fps, {**audio, 'samples': 8000})

    def test_timeline_follows_index_over_fps_with_millisecond_quantisation_and_exact_count(self):
        def listing(*stamps):
            return {'frames': [{'best_effort_timestamp_time': stamp} for stamp in stamps]}
        review.check_timeline(listing('0.000000', '0.100000', '0.200000'), 3, 10)
        review.check_timeline(listing('0.000000', '0.042000', '0.083000', '0.125000'), 4, 24)      # 1/24 s, rounded to ms
        review.check_timeline(listing('0.000000', '0.033000', '0.067000', '0.100000'), 4, 30)
        review.check_timeline(listing('0.000000', '0.1010'), 2, 10)                                  # exactly at the .0011 s bound
        cases = {'offset start': listing('0.500000', '0.600000', '0.700000'), 'negative start': listing('-0.100000', '0.000000', '0.100000'),
                 'shifted middle': listing('0.000000', '0.150000', '0.200000'), 'too few': listing('0.000000', '0.100000'),
                 'too many': listing('0.000000', '0.100000', '0.200000', '0.300000'), 'beyond tolerance': listing('0.000000', '0.1012', '0.2'),
                 'out of order': listing('0.000000', '0.200000', '0.100000'), 'not available': listing('0.000000', 'N/A', '0.200000'),
                 'not finite': listing('0.000000', 'inf', '0.200000'), 'number type': listing('0.000000', 0.1, '0.200000'),
                 'missing timestamp': {'frames': [{}, {}, {}]}, 'no list': {'frames': {}}, 'no frames key': {}}
        for label, value in cases.items():
            with self.subTest(label):
                fault = self.fault(lambda: review.check_timeline(value, 3, 10), 'VERIFICATION_FAILED')
                self.assertEqual(fault.observed['stage'], 'timeline')
        self.fault(lambda: review.check_timeline(listing(*['0.000000'] * 601), 601, 10), 'VERIFICATION_FAILED')
        self.assertEqual(review.seconds('-0.000000'), 0)
        for text in ('1_0', ' 1', '1 ', '+1', '1e3', '١', '0x1', '', '.5', '1.', 'N/A', 'NaN', '1' * 10):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    review.seconds(text)

    def test_timeline_probe_is_a_bounded_video_only_fresh_stage_outside_the_retained_stages(self):
        recipe = review.commands('/runtime/ffmpeg', Path('/run'), adaptor.plan(document())['nodes'][0]['options'])
        command = recipe[review.TIMELINE]
        self.assertNotIn(review.TIMELINE, review.STAGES)
        self.assertEqual(command[0], '/runtime/ffprobe')
        self.assertEqual(command[command.index('-select_streams') + 1], 'v:0')
        self.assertEqual(command[command.index('-read_intervals') + 1], '%+#602')
        self.assertEqual(command[command.index('-show_entries') + 1], 'frame=best_effort_timestamp_time')
        self.assertNotIn('-show_streams', command); self.assertNotIn('-show_packets', command)
        self.assertEqual(command[-1], '/run/review.mkv')
        self.assertIn(str(Path('/run/review.mkv')), review.launcher(Path('/run'), review.TIMELINE, command))
        self.assertEqual(review.stage_inputs(Path('/run'), review.TIMELINE), [Path('/run/review.mkv')])

    def test_audio_packets_follow_the_cumulative_sample_clock_and_sum_to_the_captured_samples(self):
        audio = {'channels': 1, 'sampleRate': 16000, 'samples': 2000}
        def listing(*packets):
            return {'packets': [{'pts_time': stamp, 'duration_time': duration, 'size': size} for stamp, duration, size in packets]}
        good = (('0.000000', '0.064000', '2048'), ('0.064000', '0.061000', '1952'))
        review.check_audio_packets(listing(*good), audio)
        # Odd last packet at 22.05 kHz: 1024 + 1024 + 7 sample frames, timestamps rounded to the millisecond.
        review.check_audio_packets(listing(('0.000000', '0.046000', '2048'), ('0.046000', '0.046000', '2048'), ('0.093000', '0.000000', '14')),
                                   {'channels': 1, 'sampleRate': 22050, 'samples': 2055})
        review.check_audio_packets(listing(('0.000000', '0.021000', '4096'), ('0.021000', '0.021000', '4096')),
                                   {'channels': 2, 'sampleRate': 48000, 'samples': 2048})
        cases = {'gap': listing(('0.000000', '0.064000', '2048'), ('0.094000', '0.061000', '1952')),
                 'overlap': listing(('0.000000', '0.064000', '2048'), ('0.034000', '0.061000', '1952')),
                 'offset start': listing(('0.500000', '0.064000', '2048'), ('0.564000', '0.061000', '1952')),
                 'negative start': listing(('-0.050000', '0.064000', '2048'), ('0.014000', '0.061000', '1952')),
                 'missing samples': listing(good[0]), 'extra samples': listing(*good, ('0.125000', '0.001000', '32')),
                 'empty': {'packets': []}, 'no list': {'packets': {}}, 'no key': {},
                 'odd bytes': listing(('0.000000', '0.064000', '2047'), ('0.064000', '0.061000', '1953')),
                 'zero packet': listing(good[0], good[1], ('0.125000', '0.000000', '0')),
                 'duration lies': listing(('0.000000', '0.100000', '2048'), good[1]),
                 'not available': listing(('0.000000', '0.064000', '2048'), ('N/A', '0.061000', '1952')),
                 'size number': {'packets': [{'pts_time': '0.000000', 'size': 2048}, {'pts_time': '0.064000', 'size': 1952}]},
                 'size sign': listing(('0.000000', '0.064000', '+2048'), ('0.064000', '0.061000', '1952')),
                 'packet not object': {'packets': ['x']}}
        for label, value in cases.items():
            with self.subTest(label):
                fault = self.fault(lambda: review.check_audio_packets(value, audio), 'VERIFICATION_FAILED')
                self.assertEqual(fault.observed['stage'], 'audio-packets')
        # Stereo packets must hold whole four-byte frames.
        self.fault(lambda: review.check_audio_packets(listing(('0.000000', '0.021000', '4098')), {'channels': 2, 'sampleRate': 48000, 'samples': 1024}),
                   'VERIFICATION_FAILED')
        too_many = {'packets': [{'pts_time': '0.000000', 'size': '2'}] * (review.MAX_PACKETS + 1)}
        self.fault(lambda: review.check_audio_packets(too_many, audio), 'VERIFICATION_FAILED')

    def test_audio_packet_probe_is_a_bounded_audio_only_fresh_stage_outside_the_retained_stages(self):
        recipe = review.commands('/runtime/ffmpeg', Path('/run'), adaptor.plan(document())['nodes'][0]['options'])
        command = recipe[review.AUDIO_PACKETS]
        self.assertNotIn(review.AUDIO_PACKETS, review.STAGES)
        self.assertEqual(review.FRESH_ONLY, (review.TIMELINE, review.AUDIO_PACKETS))
        self.assertEqual(command[0], '/runtime/ffprobe')
        self.assertEqual(command[command.index('-select_streams') + 1], 'a:0')
        self.assertEqual(command[command.index('-show_entries') + 1], 'packet=pts_time,duration_time,size')
        self.assertNotIn('-show_frames', command); self.assertNotIn('-show_streams', command)
        self.assertEqual(command[-1], '/run/review.mkv')
        self.assertEqual(review.stage_inputs(Path('/run'), review.AUDIO_PACKETS), [Path('/run/review.mkv')])
        self.assertIn(str(review.MAX_PACKET_PROBE + 1), review.launcher(Path('/run'), review.AUDIO_PACKETS, command))
        self.assertGreater(review.MAX_PACKET_PROBE, review.MAX_PROBE)
        self.assertGreaterEqual(review.MAX_PACKETS, review.MAX_BYTES // 2 // 1024)

    def facts(self, **change):
        audio = {'channels': 1, 'sampleRate': 16000, 'samples': 9600, 'bytes': 19200, 'pcm': memoryview(b'\0' * 19200)}
        value = {'width': 32, 'height': 24, 'frames': 6, 'fps': 10, 'audio': audio, 'cues': [(0, 250, 'a'), (300, 600, 'b')],
                 'alignment': review.alignment(9600, 16000, 6, 10, [(0, 250, 'a'), (300, 600, 'b')]),
                 'digests': {'review': 'r', 'sourceDecoded': 's', 'decoded': 'd', 'decodedPCM': 'p', 'cues': 'c'}}
        value.update(change)
        return value

    def test_fresh_facts_must_equal_retained_facts_field_by_field_and_are_tagged_fresh(self):
        def rebuild(value):
            return {'frames': value['frames'], 'width': value['width']}
        receipt = {'frames': 6, 'width': 32, 'nativeReadback': {}, 'sourceReadback': {}}
        review.bind_fresh(self.facts(), self.facts(), receipt, rebuild)
        other_audio = lambda **change: {**self.facts()['audio'], **change}
        changes = {'width': 24, 'height': 32, 'frames': 7, 'fps': 24, 'cues': [(0, 250, 'a'), (300, 601, 'b')],
                   'alignment': {**self.facts()['alignment'], 'accepted': 1},
                   'audio': other_audio(channels=2), 'digests': {**self.facts()['digests'], 'decoded': 'x'}}
        for name, value in changes.items():
            with self.subTest(name):
                fault = self.fault(lambda: review.observed_fresh(
                    lambda: review.bind_fresh(self.facts(), self.facts(**{name: value}), receipt, rebuild)), 'VERIFICATION_FAILED')
                self.assertIs(fault.observed['fresh'], True)
                self.assertTrue(fault.observed['differing'])
        for key, value in (('sampleRate', 48000), ('samples', 9601), ('bytes', 19202)):
            with self.subTest(key):
                self.fault(lambda: review.bind_fresh(self.facts(), self.facts(audio=other_audio(**{key: value})), receipt, rebuild),
                           'VERIFICATION_FAILED')
        for key in ('review', 'sourceDecoded', 'decodedPCM', 'cues'):
            with self.subTest(key):
                self.fault(lambda: review.bind_fresh(self.facts(), self.facts(digests={**self.facts()['digests'], key: 'z'}), receipt, rebuild),
                           'VERIFICATION_FAILED')
        # Equality is typed: 6 is not 6.0 and 10 is not True.
        self.fault(lambda: review.bind_fresh(self.facts(), self.facts(frames=6.0), receipt, rebuild), 'VERIFICATION_FAILED')
        self.fault(lambda: review.bind_fresh(self.facts(fps=1), self.facts(fps=True), receipt, rebuild), 'VERIFICATION_FAILED')

    def test_fresh_facts_must_equal_the_receipt_even_when_retained_facts_agree_with_them(self):
        facts = self.facts()
        forged = {'frames': 7, 'width': 32, 'nativeReadback': {}}
        fault = self.fault(lambda: review.observed_fresh(
            lambda: review.bind_fresh(facts, facts, forged, lambda value: {'frames': value['frames'], 'width': value['width']})), 'VERIFICATION_FAILED')
        self.assertIs(fault.observed['fresh'], True); self.assertIn('receipt', fault.message)

    def test_observed_fresh_tags_every_fault_and_leaves_values_and_other_exceptions_alone(self):
        self.assertEqual(review.observed_fresh(lambda: 5), 5)
        for code in ('VERIFICATION_FAILED', 'RUNNER_CANCELLED', 'RUNNER_TIMED_OUT', 'RESOURCE_LIMIT'):
            def action():
                raise SchemaxisError(review.Fault(code, 'm', 'l', 'pipeline', observed={'stage': 'probe'}, recovery='r'))
            fault = self.fault(lambda: review.observed_fresh(action), code)
            self.assertEqual((fault.observed['fresh'], fault.observed['stage'], fault.recovery, fault.location), (True, 'probe', 'r', 'l'))
        with self.assertRaises(KeyError):
            review.observed_fresh(lambda: {}['x'])
        # A retained-pass fault is never tagged.
        self.assertNotIn('fresh', self.fault(lambda: review.check_video(b'ab', b'a', 1, 2), 'VERIFICATION_FAILED').observed)

    def test_all_three_captured_sources_are_held_once_and_the_originals_are_never_resolved(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            for index, data in enumerate((b'video', b'audio', b'captions')):
                (root / f'input-000{index}').write_bytes(data)
            prepared = adaptor.plan(document())
            records, held = review.hold_sources(root, prepared)
            self.assertEqual(held, [b'video', b'audio', b'captions'])
            self.assertEqual([record['file'] for record in records], ['/input/silent.mkv', '/input/speech.wav', '/input/captions.srt'])
            self.assertEqual([record['retained'] for record in records], ['input-0000', 'input-0001', 'input-0002'])
            self.assertEqual(records[1]['sha256'], hashlib.sha256(b'audio').hexdigest())
            (root / 'input-0002').unlink()
            self.fault(lambda: review.hold_sources(root, prepared), 'RESOURCE_NOT_FOUND')    # the authored path is not a fallback

    def test_decoded_video_must_equal_the_captured_source(self):
        source = bytes(range(60))
        review.check_video(source, source, 30, 2)
        changed = bytearray(source); changed[31] ^= 1
        fault = self.fault(lambda: review.check_video(source, bytes(changed), 30, 2), 'VERIFICATION_FAILED')
        self.assertEqual(fault.observed['frame'], 1)
        self.fault(lambda: review.check_video(source, source[:30], 30, 2), 'VERIFICATION_FAILED')

    def test_existing_operations_still_refuse_extra_streams_and_keep_their_location(self):
        probe = {'streams': [{'codec_type': 'video', 'codec_name': 'ffv1', 'pix_fmt': 'bgr0', 'width': 2, 'height': 1},
                             {'codec_type': 'audio', 'codec_name': 'pcm_s16le'}],
                 'format': {'format_name': 'matroska,webm'}, 'frames': []}
        self.assertEqual(self.fault(lambda: video.inspect(probe), 'UNSUPPORTED_VIDEO').location, '$.nodes[0].options.file')
        self.assertEqual(self.fault(lambda: video.inspect(probe, review.LOCATION + 'video'), 'UNSUPPORTED_VIDEO').location,
                         '$.nodes[0].options.video')
        probe['streams'][1] = {'codec_type': 'subtitle', 'codec_name': 'subrip'}
        self.fault(lambda: video.inspect(probe), 'UNSUPPORTED_VIDEO')

    def test_launcher_binds_every_mux_input_and_the_published_file(self):
        directory = Path('/run')
        encode = review.launcher(directory, 'encode', ['ffmpeg'])
        for name in ('input-0000', 'input-0001', 'input-0002'):
            self.assertIn(str(directory / name), encode)
        self.assertEqual(review.stage_inputs(directory, 'decode-audio'), [directory / 'review.mkv'])
        self.assertIn('encode-inputs.json', encode)
        self.assertEqual(review.cue_digest([(0, 1, 'a')]), review.cue_digest([(0, 1, 'a')]))
        self.assertNotEqual(review.cue_digest([(0, 1, 'a')]), review.cue_digest([(0, 2, 'a')]))

    def test_strict_json_refuses_duplicates_nonfinite_numbers_and_bom(self):
        self.assertEqual(review.strict_json(b'{"a": [1, 2.5, 1e-400]}', 'x'), {'a': [1, 2.5, 0.0]})
        for text in (b'{"a": 1, "a": 2}', b'{"a": NaN}', b'{"a": Infinity}', b'{"a": -Infinity}', b'{"a": 1e400}',
                     b'{"a": [1e999]}', b'\xef\xbb\xbf{}', b'\xff', b'[' * 100000):
            with self.subTest(text=text[:20]):
                self.fault(lambda: review.strict_json(text, 'result.json'), 'VERIFICATION_FAILED')

    def test_typed_comparison_distinguishes_booleans_and_numeric_types(self):
        self.assertTrue(review.same_json({'a': [1, 'x', None], 'b': 1.5}, {'b': 1.5, 'a': [1, 'x', None]}))
        for actual, expected in ((0, False), (1, True), (6, 6.0), ({'a': 1}, {'a': True}), ([1], [1.0]), ({'a': 1}, {'a': 1, 'b': 0})):
            with self.subTest(actual=actual):
                self.assertFalse(review.same_json(actual, expected))
        self.assertFalse(review.same_json(float('nan'), float('nan')))
        self.assertFalse(review.same_json({'a': float('inf')}, {'a': float('inf')}))

    def executables(self, root, probe=True):
        root = Path(root); root.mkdir(parents=True, exist_ok=True)
        for name in ('ffmpeg', 'ffprobe') if probe else ('ffmpeg',):
            (root / name).write_text('#!/bin/sh\nexit 0\n'); (root / name).chmod(0o755)
        return str(root / 'ffmpeg')

    def test_trusted_runtime_order_and_refusals(self):
        with tempfile.TemporaryDirectory() as scratch:
            explicit = self.executables(Path(scratch) / 'explicit')
            stored = self.executables(Path(scratch) / 'stored')
            environment = self.executables(Path(scratch) / 'environment')
            planted = self.executables(Path(scratch) / 'path')
            with mock.patch.dict(os.environ, {'FFMPEG_EXECUTABLE': environment, 'PATH': str(Path(planted).parent)}):
                with mock.patch.object(review, 'configured_executable', return_value=stored):
                    self.assertEqual(review.trusted(explicit), {'ffmpeg': explicit, 'ffprobe': str(Path(explicit).with_name('ffprobe'))})
                    self.assertEqual(review.trusted()['ffmpeg'], stored)
                with mock.patch.object(review, 'configured_executable', return_value=None):
                    self.assertEqual(review.trusted()['ffmpeg'], environment)
            with mock.patch.dict(os.environ, {'PATH': str(Path(planted).parent)}):
                os.environ.pop('FFMPEG_EXECUTABLE', None)
                with mock.patch.object(review, 'configured_executable', return_value=None):
                    fault = self.fault(review.trusted, 'INTERPRETER_NOT_FOUND')    # a PATH ffmpeg is never a fallback
                    self.assertIn('FFMPEG_EXECUTABLE', fault.recovery)
                    self.assertIn('bare `schemaxis verify`', fault.recovery)
                    self.fault(lambda: review.trusted('ffmpeg'), 'INTERPRETER_NOT_FOUND')
                    self.fault(lambda: review.trusted(str(Path(scratch) / 'absent')), 'INTERPRETER_NOT_FOUND')
                    lone = self.executables(Path(scratch) / 'lone', probe=False)
                    self.assertEqual(self.fault(lambda: review.trusted(lone), 'INTERPRETER_NOT_FOUND').location, '$.runtime.ffprobe')

    def retained(self, root, status='succeeded', receipt=True):
        root = Path(root); root.mkdir(parents=True, exist_ok=True)
        authored = document(); prepared = adaptor.plan(authored)
        (root / 'authored.json').write_text(json.dumps(authored)); (root / 'plan.json').write_text(json.dumps(prepared))
        (root / 'result.json').write_text(json.dumps({'status': status, 'verified': status == 'succeeded'}))
        if receipt:
            (root / 'verification.json').write_text('{}')
        return root

    def test_verify_needs_a_trusted_runtime_but_reports_incomplete_runs_first(self):
        with tempfile.TemporaryDirectory() as scratch, mock.patch.object(review, 'configured_executable', return_value=None), \
                mock.patch.dict(os.environ, {'PATH': ''}):
            os.environ.pop('FFMPEG_EXECUTABLE', None)
            self.fault(lambda: adaptor.verify(self.retained(Path(scratch) / 'a')), 'INTERPRETER_NOT_FOUND')
            self.fault(lambda: adaptor.verify(self.retained(Path(scratch) / 'b', 'failed')), 'INCOMPLETE_EXECUTION')
            self.fault(lambda: adaptor.verify(self.retained(Path(scratch) / 'c', receipt=False)), 'VERIFICATION_FAILED')

    def test_retained_json_is_read_strictly(self):
        with tempfile.TemporaryDirectory() as scratch, mock.patch.object(review, 'configured_executable', return_value=None):
            root = self.retained(Path(scratch) / 'a')
            prepared = adaptor.plan(document())
            for text in ('{"status": "succeeded", "status": "failed"}', '{"status": "succeeded", "verified": true, "x": 1e400}'):
                (root / 'result.json').write_text(text)
                self.fault(lambda: review.verify(root, prepared, {'ffmpeg': '/x', 'ffprobe': '/y'}), 'VERIFICATION_FAILED')

    def test_unverified_review_file_is_removed_when_publication_fails(self):
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            def partial(*_):
                (directory / review.OUTPUT).write_bytes(b'partial'); raise SchemaxisError(review.Fault('RUNNER_CANCELLED', 'cancelled', 'encode', 'pipeline'))
            with mock.patch.object(review, 'publish', partial):
                self.fault(lambda: review.run({}, directory, '/x', 0), 'RUNNER_CANCELLED')
            self.assertFalse((directory / review.OUTPUT).exists())

    def test_fresh_verification_uses_a_private_directory_and_removes_it_on_cancellation(self):
        with tempfile.TemporaryDirectory() as scratch:
            run = Path(scratch) / 'run'; run.mkdir()
            seen = []
            def cancelled(command, directory, stage, timeout, environment=None):
                seen.append((Path(directory), stage, list(command)))
                self.assertEqual((Path(directory) / 'input-0000').read_bytes(), b'video')
                self.assertEqual((Path(directory) / review.OUTPUT).read_bytes(), b'published')
                raise SchemaxisError(review.Fault('RUNNER_CANCELLED', 'cancelled', stage, 'pipeline'))
            prepared = adaptor.plan(document())
            paths = {'ffmpeg': '/trusted/ffmpeg', 'ffprobe': '/trusted/ffprobe'}
            with mock.patch.object(review, 'execute', cancelled):
                self.fault(lambda: review.fresh_observation(run, prepared, paths, [b'video', b'audio', b'captions'], b'published', None), 'RUNNER_CANCELLED')
            directory, stage, command = seen[0]
            self.assertEqual((stage, command), ('version', ['/trusted/ffmpeg', '-version']))
            self.assertNotIn(run, directory.parents); self.assertFalse(directory.exists())
            self.assertEqual(os.listdir(run), [])

    def test_budget_honours_run_deadline_cancellation_and_expiry(self):
        import threading, time
        from schemaxis.dispatch import allocation
        self.assertLessEqual(review.budget('probe', None), review.STAGE_TIMEOUT)
        self.assertLessEqual(review.budget('probe', time.monotonic() + 5), 5)
        self.fault(lambda: review.budget('probe', time.monotonic() - 1), 'RUNNER_TIMED_OUT')
        event = threading.Event(); event.set()
        with allocation({'threads': 1}, cancel=event):
            self.fault(lambda: review.budget('probe', None), 'RUNNER_CANCELLED')
            self.fault(lambda: review.budget('probe', time.monotonic() + 5), 'RUNNER_CANCELLED')


if __name__ == '__main__':
    unittest.main()
