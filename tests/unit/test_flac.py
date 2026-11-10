"""Lossless FLAC contract: planning, independent WAV reader, FLAC framing checks, discovery and guidance (host only).

Nothing here starts a native process. ``build_flac`` writes a correctly framed FLAC prefix (STREAMINFO, metadata, first
frame header with CRC-8) whose body is raw PCM, so the host checks can be exercised without libFLAC; the fake native
boundary is test_flac_native_boundary.py and real FLAC acceptance is tools/qualify_flac.py.
"""
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import wave

from schemaxis.adaptors import registry
from schemaxis.adaptors.flac import adaptor
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_flac_fakes import (MARKER, RATE_CODE, build_flac, chunk_list, frame_header, metadata_stream, streaminfo, vorbis, wav_bytes)   # noqa: E402
import test_flac_fakes   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/flac'


@contextlib.contextmanager
def private_configuration(locations=None):
    """A private SCHEMAXIS_CONFIG with SCHEMAXIS_FLAC cleared.

    ``location_context({'flac': None})`` drops None values and so does not clear stored settings: a machine with a stored
    flac would otherwise leak into these tests.
    """
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
        path = Path(tmp) / 'private-config.json'
        path.write_text(json.dumps({'version': 1, 'locations': locations or {}}))
        os.environ['SCHEMAXIS_CONFIG'] = str(path)
        os.environ.pop('SCHEMAXIS_FLAC', None)
        yield


class FlacContract(unittest.TestCase):
    def document(self, name='baseline'):
        return json.loads((ROOT / f'examples/schemaxis/flac-{name}.json').read_text())

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    # ------------------------------------------------------------ registration, planning
    def test_registered_with_one_native_option_and_no_framework_branch(self):
        item = registry.ADAPTORS['flac']
        self.assertEqual([o['dest'] for o in item['cliOptions']], ['flac'])
        self.assertEqual(item['executables'], ['flac'])
        self.assertNotIn('runOptions', item['routes']['schemaxis.flac/1'])
        self.assertEqual(item['routes']['schemaxis.flac/1']['acceptedArtifacts'], ['file'])
        self.assertEqual(registry.query(self.document())['adaptors'][0]['operations'], ['encodeLossless'])
        self.assertEqual(registry.query(self.document('decode'))['adaptors'][0]['operations'], ['decodePCM16'])

    def test_declared_native_strings_name_every_fixed_flag_of_the_actual_arguments(self):
        # the user-visible reference strings must not drift from the argv that actually runs
        encode = adaptor.DECLARATIONS['encodeLossless']['native']
        decode = adaptor.DECLARATIONS['decodePCM16']['native']
        for flag in adaptor.ENCODE_ARGUMENTS:
            self.assertIn(flag, encode.split(';')[0].split(), 'encode declaration omits ' + flag)
        self.assertIn('--no-preserve-modtime', encode.split(';')[1].split())     # the encode readback decode
        for flag in adaptor.DECODE_ARGUMENTS:
            self.assertIn(flag, decode.split(';')[0].split(), 'decode declaration omits ' + flag)
        self.assertEqual(encode.count('--no-preserve-modtime'), 2)
        self.assertEqual(decode.count('--no-preserve-modtime'), 1)

    def test_host_contract_guidance_and_curated_search(self):
        from schemaxis.adaptor_conformance import host
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        from schemaxis.studio_guidance import audit
        self.assertTrue(host(adaptor.VERSION)['verified'])
        self.assertTrue(audit('flac')['complete'])
        self.assertTrue(check_cases(CapabilityCatalogue(providers=['flac']), 'flac')['complete'])

    def test_planning_is_immutable_deterministic_and_closed(self):
        for name, operation, arguments in (('baseline', 'encodeLossless', adaptor.ENCODE_ARGUMENTS), ('decode', 'decodePCM16', adaptor.DECODE_ARGUMENTS)):
            document = self.document(name)
            before = copy.deepcopy(document)
            prepared = adaptor.plan(document)
            self.assertEqual(before, document)
            self.assertEqual(prepared, adaptor.plan(document))
            self.assertEqual((prepared['operation'], prepared['native']['arguments']), (operation, arguments))
            self.assertEqual(prepared['budget']['maxPcmBytes'], 32 * 1024 * 1024 - 44)
            for key in ('compression', 'level', 'flags', 'tags', 'resample', 'channels', 'verify', 'decodeThroughErrors', 'command'):
                bad = copy.deepcopy(document)
                bad[key] = 1
                self.fault(lambda: adaptor.plan(bad), 'UNKNOWN_ARGUMENT')
        for bad_operation in ('encodeLossy', 'decode', '', None, 7, ['encodeLossless'], {'a': 1}):
            bad = self.document()
            bad['operation'] = bad_operation
            self.assertEqual(self.fault(lambda: adaptor.plan(bad), 'UNKNOWN_FILTER').location, '$.operation')
        bad = self.document()
        bad['version'] = 'schemaxis.flac/2'
        self.fault(lambda: adaptor.plan(bad), 'UNSUPPORTED_VERSION')
        self.fault(lambda: adaptor.resources(self.document(), {'threads': 2}, 'op'), 'INVALID_EXECUTION')

    def test_source_names_must_match_the_operation(self):
        for operation, good, bad_names in (('encodeLossless', '/tmp/a.WAV', ('relative.wav', 'https://example.org/a.wav', 'WAV:/tmp/a.wav', '/tmp/a.flac', '/tmp/a.mp3', '/tmp/a\0.wav', '/tmp/a')),
                                           ('decodePCM16', '/tmp/a.FLAC', ('relative.flac', 'file:///tmp/a.flac', '/tmp/a.wav', '/tmp/a.ogg', '/tmp/a.flac\0', '/tmp/a.oga'))):
            document = {'version': 'schemaxis.flac/1', 'operation': operation, 'source': good}
            self.assertEqual(adaptor.plan(document)['source'], good)
            for source in bad_names:
                self.assertEqual(self.fault(lambda: adaptor.plan({**document, 'source': source}), 'INVALID_FLAC_SOURCE').location, '$.source', source)
        self.assertEqual(self.fault(lambda: adaptor.plan(self.document('invalid-source')), 'INVALID_FLAC_SOURCE').location, '$.source')
        for value in (1, True, None, ['/tmp/a.wav'], ''):
            bad = self.document()
            bad['source'] = value
            with self.assertRaises(SchemaxisError):
                adaptor.plan(bad)

    # ------------------------------------------------------------ WAV reader
    def test_wav_reader_accepts_the_documented_subset_with_literal_samples(self):
        mono = adaptor.parse_wav((FIXTURES / 'mono-8000.wav').read_bytes())
        self.assertEqual((mono['rate'], mono['channels'], mono['frames'], mono['droppedChunks']), (8000, 1, 1001, ['LIST']))
        self.assertEqual(struct.unpack('<5h', mono['pcm'][:10]), (-32768, 32767, 0, 1, -1))
        self.assertEqual(struct.unpack('<h', mono['pcm'][-2:]), (-32768,))
        stereo = adaptor.parse_wav((FIXTURES / 'stereo-48000.wav').read_bytes())
        self.assertEqual((stereo['rate'], stereo['channels'], stereo['frames'], len(stereo['pcm']), stereo['droppedChunks']), (48000, 2, 4099, 16396, []))
        self.assertEqual(struct.unpack('<2h', stereo['pcm'][:4]), (1, -32768))                   # frame 0: pinned left 1, right -32768
        self.assertEqual(struct.unpack_from('<h', stereo['pcm'], 4 * 4096)[0], 32767)            # first frame of the second FLAC block
        self.assertEqual(struct.unpack_from('<2h', stereo['pcm'], 4 * 4098), (-32768, -1))       # odd final frame
        self.assertEqual(adaptor.pcm_peaks(stereo['pcm'], 2), ([-32768, -32768], [32767, 20000]))
        self.assertEqual(adaptor.pcm_peaks(mono['pcm'], 1), ([-32768], [32767]))
        both = adaptor.parse_wav(wav_bytes(extra=chunk_list() + b'JUNK' + struct.pack('<I', 3) + b'xyz\0'))
        self.assertEqual(both['droppedChunks'], ['LIST', 'JUNK'])
        for rate in (8000, 44100, 192000):
            self.assertEqual(adaptor.parse_wav(wav_bytes(rate=rate))['rate'], rate)

    def test_wav_refusals_are_distinct_and_located(self):
        good = wav_bytes()
        cases = [good[:-1], good + b'\0', good[:4] + b'\xff\xff\xff\x7f' + good[8:], good.replace(b'RIFF', b'RIFX'), good.replace(b'WAVE', b'AVI '),
                 wav_bytes(extra=b'fact' + struct.pack('<I', 4) + bytes(4)), wav_bytes(fmt_size=18), wav_bytes(fmt_size=40), wav_bytes(bits=24, pcm=bytes(12)),
                 wav_bytes(encoding=3, bits=32, pcm=bytes(16)), wav_bytes(channels=3, pcm=bytes(12)), wav_bytes(channels=0), wav_bytes(rate=7999), wav_bytes(rate=192001), wav_bytes(rate=0),
                 wav_bytes(pcm=bytes(7)), wav_bytes(pcm=b''), wav_bytes(data_first=True), wav_bytes(extra=chunk_list() + chunk_list()), b'', b'RIFF', b'x' * 64,
                 wav_bytes(extra=b'LIST' + struct.pack('<I', 3) + b'abc\x01'), wav_bytes(riff_delta=2), wav_bytes(tail=b'\0\0\0\0')]
        for index, bad in enumerate(cases):
            fault = self.fault(lambda: adaptor.parse_wav(bad), 'INVALID_FLAC_WAV')
            self.assertEqual(fault.location, '$.source', index)
        self.assertEqual(self.fault(lambda: adaptor.parse_wav(bad), 'INVALID_FLAC_WAV').location, '$.source')
        self.assertEqual(self.fault(lambda: adaptor.parse_wav(good[:-1], 'captured.wav'), 'INVALID_FLAC_WAV').location, 'captured.wav')

    def test_wav_budgets_are_judged_before_any_native_work(self):
        # 600 s at 8000 Hz mono is 9,600,000 bytes; one more frame is over the duration budget
        limit = 600 * 8000
        self.assertEqual(adaptor.parse_wav(wav_bytes(rate=8000, channels=1, pcm=bytes(2 * limit)))['frames'], limit)
        fault = self.fault(lambda: adaptor.parse_wav(wav_bytes(rate=8000, channels=1, pcm=bytes(2 * limit + 2))), 'FLAC_BUDGET')
        self.assertIn('600', fault.message)
        # 48 kHz stereo is bounded by the 32 MiB canonical WAV, well below 600 s
        frames = adaptor.MAX_PCM_BYTES // 4
        self.assertEqual(adaptor.parse_wav(wav_bytes(rate=48000, pcm=bytes(4 * frames)))['frames'], frames)
        self.fault(lambda: adaptor.parse_wav(wav_bytes(rate=48000, pcm=bytes(4 * frames + 4))), 'FLAC_BUDGET')
        self.fault(lambda: adaptor.parse_wav(bytes(adaptor.MAX_WAV_BYTES + 1)), 'FLAC_BUDGET')

    def test_canonical_wav_is_exactly_the_44_byte_pcm16_layout_and_readable_back(self):
        pcm = struct.pack('<4h', -32768, 32767, 0, 1)
        data = adaptor.canonical_wav(16000, 2, pcm)
        self.assertEqual(data[:4] + data[8:16], b'RIFFWAVEfmt ')
        self.assertEqual(len(data), 44 + len(pcm))
        self.assertEqual(struct.unpack('<IHHIIHH', data[16:36]), (16, 1, 2, 16000, 64000, 4, 16))
        self.assertEqual(adaptor.parse_wav(data)['pcm'], pcm)
        with wave.open(__import__('io').BytesIO(data)) as stream:
            self.assertEqual((stream.getnchannels(), stream.getframerate(), stream.getnframes(), stream.readframes(2)), (2, 16000, 2, pcm))
        self.assertEqual(adaptor.canonical_wav(8000, 1, struct.pack('<h', 5)), wav_bytes(8000, 1, struct.pack('<h', 5)))

    def test_first_difference_names_frame_and_channel(self):
        self.assertEqual(adaptor.first_difference(b'\0\0\0\0\0\0\1\0', bytes(8), 2), 'first difference at frame 1 channel 1')
        self.assertIn('lengths differ', adaptor.first_difference(bytes(4), bytes(8), 2))

    # ------------------------------------------------------------ FLAC framing
    def test_real_fixtures_parse_to_literal_streaminfo(self):
        wav = adaptor.parse_wav((FIXTURES / 'stereo-16000.wav').read_bytes())
        for name in ('stereo-16000.flac', 'tagged-stereo-16000.flac'):
            parsed = adaptor.parse_flac((FIXTURES / name).read_bytes())
            info = parsed['streaminfo']
            self.assertEqual((info['sampleRate'], info['channels'], info['bitsPerSample'], info['totalSamples']), (16000, 2, 16, 2049), name)
            self.assertEqual(info['md5'], hashlib.md5(wav['pcm']).hexdigest(), name)
            self.assertEqual(info['minBlockSize'], 4096)
        plain = adaptor.parse_flac((FIXTURES / 'stereo-16000.flac').read_bytes(), encoder_output=True)
        self.assertEqual([b['type'] for b in plain['metadata']], ['STREAMINFO', 'VORBIS_COMMENT'])
        self.assertTrue(plain['vendor'].startswith('reference libFLAC 1.5.'))
        tagged = adaptor.parse_flac((FIXTURES / 'tagged-stereo-16000.flac').read_bytes())
        self.assertEqual([b['type'] for b in tagged['metadata']], ['STREAMINFO', 'SEEKTABLE', 'VORBIS_COMMENT', 'PADDING'])
        self.fault(lambda: adaptor.parse_flac((FIXTURES / 'tagged-stereo-16000.flac').read_bytes(), encoder_output=True), 'INVALID_FLAC_STREAM')
        mono = adaptor.parse_flac((FIXTURES / 'mono-8000.flac').read_bytes())['streaminfo']
        self.assertEqual((mono['sampleRate'], mono['channels'], mono['totalSamples']), (8000, 1, 1001))
        wide = adaptor.parse_flac((FIXTURES / 'stereo-48000.flac').read_bytes())['streaminfo']
        self.assertEqual((wide['sampleRate'], wide['totalSamples']), (48000, 4099))

    def test_synthetic_streams_accept_the_supported_matrix(self):
        for rate in (8000, 16000, 22050, 44100, 48000, 96000, 192000, 12000, 11025):
            for channels in (1, 2):
                parsed = adaptor.parse_flac(build_flac(rate, channels, bytes(2 * channels * 5)))
                self.assertEqual((parsed['streaminfo']['sampleRate'], parsed['streaminfo']['channels'], parsed['streaminfo']['totalSamples']), (rate, channels, 5))
        decorrelated = (1, 8, 9, 10)
        for code in decorrelated:
            adaptor.parse_flac(build_flac(header=frame_header(channel_code=code)))
        # a first frame of a long stream uses the 4096 block size code; a fixed block of 4096 samples fits a stream of 5000
        self.assertEqual(adaptor.parse_flac(build_flac(total=5000, pcm=bytes(4)))['streaminfo']['totalSamples'], 5000)

    def test_container_prefixes_and_unsupported_formats_are_distinct(self):
        good = build_flac()
        self.assertEqual(self.fault(lambda: adaptor.parse_flac(b'OggS' + good[4:]), 'UNSUPPORTED_FLAC_FORMAT').location, '$.source')
        self.assertIn('Ogg', self.fault(lambda: adaptor.parse_flac(b'OggS\0\x02' + bytes(60)), 'UNSUPPORTED_FLAC_FORMAT').message)
        self.assertIn('ID3', self.fault(lambda: adaptor.parse_flac(b'ID3\x04\0\0\0\0\0\0' + good), 'UNSUPPORTED_FLAC_FORMAT').message)
        for label, stream in (('24-bit', build_flac(info=streaminfo(bits=24))), ('8-bit', build_flac(info=streaminfo(bits=8))), ('three channels', build_flac(info=streaminfo(channels=3))),
                              ('eight channels', build_flac(info=streaminfo(channels=8))), ('rate 7999', build_flac(info=streaminfo(rate=7999))), ('rate 192001', build_flac(info=streaminfo(rate=192001))),
                              ('rate 655350', build_flac(info=streaminfo(rate=655350))), ('unknown total', build_flac(info=streaminfo(total=0))), ('no md5', build_flac(info=streaminfo(md5=bytes(16))))):
            self.fault(lambda: adaptor.parse_flac(stream), 'UNSUPPORTED_FLAC_FORMAT')

    def test_structural_defects_are_invalid_streams(self):
        info = (0, streaminfo())
        comment = (4, vorbis())
        swap = lambda blocks: [blocks[1], blocks[0]]
        cases = {
            'no marker': b'RIFF' + bytes(60), 'empty': b'', 'marker only': b'fLaC', 'truncated header': b'fLaC\x00\x00',
            'streaminfo not first': build_flac(order=swap), 'streaminfo twice': build_flac(extra_blocks=[info]),
            'streaminfo short': metadata_stream([(0, streaminfo()[:33])]) + frame_header() + MARKER,
            'streaminfo long': metadata_stream([(0, streaminfo() + b'\0')]) + frame_header() + MARKER,
            'forbidden 127': build_flac(extra_blocks=[(127, b'')]), 'reserved 7': build_flac(extra_blocks=[(7, b'x')]), 'reserved 126': build_flac(extra_blocks=[(126, b'x')]),
            'two vorbis': build_flac(extra_blocks=[comment]), 'two seektables': build_flac(extra_blocks=[(3, bytes(18)), (3, bytes(18))]),
            'block past end': metadata_stream([info])[:-4] + b'', 'zero blocksize min': build_flac(info=streaminfo(min_block=15)), 'reversed blocksize': build_flac(info=streaminfo(min_block=4096, max_block=1024)),
            'frame sizes reversed': build_flac(info=streaminfo(min_frame=9, max_frame=2)),
            'rate zero': build_flac(info=streaminfo(rate=0)), 'no frame': metadata_stream([info, comment]), 'frame sync wrong': build_flac(header=frame_header(sync=0xfa)),
            'frame crc': build_flac(header=frame_header(corrupt_crc=True)), 'frame reserved bit': build_flac(header=frame_header(reserved=1)),
            'frame size reserved': build_flac(header=bytes([0xff, 0xf8, 0x05, 0x18, 0x00, 0])), 'frame rate forbidden': build_flac(header=frame_header(rate_code=15)),
            'frame rate differs': build_flac(header=frame_header(rate_code=RATE_CODE[16000])), 'frame channels differ': build_flac(header=frame_header(channel_code=0)),
            'frame channels reserved': build_flac(header=frame_header(channel_code=11)), 'frame depth 24': build_flac(header=frame_header(depth_code=6)), 'frame depth reserved': build_flac(header=frame_header(depth_code=3)),
            'frame number nonzero': build_flac(header=frame_header(number=1)), 'frame block over max': build_flac(total=5000, pcm=bytes(4), header=frame_header(total=5000, size=4608)),
            'frame block over total': build_flac(total=5, pcm=bytes(4), header=frame_header(total=5, size=6)), 'frame truncated': metadata_stream([info, comment]) + b'\xff\xf8\xa1',
        }
        cases['max block below the minimum'] = build_flac(info=streaminfo(max_block=0, min_block=16))
        for label, stream in cases.items():
            with self.subTest(label):
                self.fault(lambda: adaptor.parse_flac(stream), 'INVALID_FLAC_STREAM')

    def test_stream_budgets_come_from_streaminfo_not_from_the_body(self):
        limit_frames = adaptor.MAX_PCM_BYTES // 4
        ok = build_flac(48000, 2, bytes(8), total=limit_frames, info=streaminfo(48000, 2, 16, limit_frames))
        self.assertEqual(adaptor.parse_flac(ok)['streaminfo']['totalSamples'], limit_frames)
        for label, info in (('too many bytes', streaminfo(48000, 2, 16, limit_frames + 1)), ('too long', streaminfo(8000, 1, 16, 600 * 8000 + 1)),
                            ('36-bit count', streaminfo(48000, 2, 16, (1 << 36) - 1))):
            self.fault(lambda: adaptor.parse_flac(build_flac(8000, 1, bytes(2), info=info)), 'FLAC_BUDGET')
        self.fault(lambda: adaptor.parse_flac(bytes(adaptor.MAX_FLAC_BYTES + 1)), 'FLAC_BUDGET')
        big = build_flac(extra_blocks=[(6, bytes(adaptor.MAX_METADATA_BYTES + 8))])
        self.fault(lambda: adaptor.parse_flac(big), 'FLAC_BUDGET')

    def test_encoder_output_must_have_exactly_the_published_metadata(self):
        self.assertEqual(adaptor.parse_flac(build_flac(), encoder_output=True)['vendor'], 'reference libFLAC 1.5.0 20250211')
        for label, stream in (('padding', build_flac(extra_blocks=[(1, bytes(8))])), ('no comment', build_flac(vendor=False)),
                              ('tag', build_flac(order=lambda b: [b[0], (4, vorbis(count=1) + struct.pack('<I', 3) + b'a=b')])),
                              ('vendor', build_flac(order=lambda b: [b[0], (4, vorbis(b'other encoder'))])),
                              ('trailing comment bytes', build_flac(order=lambda b: [b[0], (4, vorbis() + b'x')])),
                              ('picture', build_flac(extra_blocks=[(6, bytes(8))]))):
            self.fault(lambda: adaptor.parse_flac(stream, encoder_output=True), 'INVALID_FLAC_STREAM')

    def test_audio_facts_dispatch_by_operation(self):
        wav = (FIXTURES / 'mono-8000.wav').read_bytes()
        facts = adaptor.audio_facts('encodeLossless', wav)
        self.assertEqual((facts['rate'], facts['channels'], facts['frames'], len(facts['pcm']), facts['dropped']), (8000, 1, 1001, 2002, ['LIST']))
        facts = adaptor.audio_facts('decodePCM16', (FIXTURES / 'mono-8000.flac').read_bytes())
        self.assertEqual((facts['rate'], facts['channels'], facts['frames']), (8000, 1, 1001))
        self.fault(lambda: adaptor.audio_facts('encodeLossless', (FIXTURES / 'mono-8000.flac').read_bytes()), 'INVALID_FLAC_WAV')
        self.fault(lambda: adaptor.audio_facts('decodePCM16', wav), 'INVALID_FLAC_STREAM')

    def test_crc8_matches_the_flac_polynomial(self):
        for sample in (b'', b'\xff\xf8\xc9\x18\x00', bytes(range(40))):
            self.assertEqual(adaptor.crc8(sample), test_flac_fakes.crc8(sample))     # two independent implementations
        self.assertEqual(adaptor.crc8(b''), 0)
        self.assertEqual(adaptor.crc8(b'123456789'), 0xf4)      # CRC-8 poly 0x07, init 0 (CRC-8/SMBUS check value)
        real = (FIXTURES / 'stereo-48000.flac').read_bytes()
        offset = adaptor.parse_flac(real)['audioOffset']
        self.assertEqual(adaptor.crc8(real[offset:offset + 5]), real[offset + 5])    # fixed 4096-sample block, common rate: five header bytes

    # ------------------------------------------------------------ sources
    def test_sources_are_regular_bounded_and_byte_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.wav'
            document = {'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(path)}
            path.write_bytes((FIXTURES / 'mono-8000.wav').read_bytes())
            first = adaptor.reusableInputs(document)
            path.write_bytes((FIXTURES / 'stereo-16000.wav').read_bytes())
            self.assertNotEqual(first, adaptor.reusableInputs(document))
            link = Path(tmp) / 'link.wav'
            link.symlink_to(path)
            self.fault(lambda: adaptor.bounded(link, 'INVALID_FLAC_SOURCE'), 'INVALID_FLAC_SOURCE')
            if hasattr(os, 'mkfifo'):
                fifo = Path(tmp) / 'fifo.wav'
                os.mkfifo(fifo)
                self.fault(lambda: adaptor.bounded(fifo, 'INVALID_FLAC_SOURCE'), 'INVALID_FLAC_SOURCE')
            path.write_bytes(bytes(adaptor.MAX_WAV_BYTES + 1))
            self.fault(lambda: adaptor.reusableInputs(document), 'INVALID_FLAC_SOURCE')
            path.write_bytes(b'not audio')
            self.fault(lambda: adaptor.reusableInputs(document), 'INVALID_FLAC_WAV')
            decode = Path(tmp) / 'a.flac'
            decode.write_bytes(b'OggS' + bytes(50))
            self.fault(lambda: adaptor.reusableInputs({**document, 'operation': 'decodePCM16', 'source': str(decode)}), 'UNSUPPORTED_FLAC_FORMAT')
            decode.write_bytes((FIXTURES / 'mono-8000.flac').read_bytes())
            self.assertIn(str(decode), adaptor.reusableInputs({**document, 'operation': 'decodePCM16', 'source': str(decode)}))

    # ------------------------------------------------------------ trusted runtime
    def test_runtime_never_comes_from_receipts_path_or_relative_names(self):
        with private_configuration():
            fault = self.fault(lambda: adaptor.runtime(), 'INTERPRETER_NOT_FOUND')
            self.assertIn('no host FLAC decoder', fault.message)
            self.assertEqual(fault.location, '$.runtime.flac')
            with mock.patch.dict(os.environ, {'PATH': '/bin:/usr/bin'}):
                self.fault(lambda: adaptor.runtime(), 'INTERPRETER_NOT_FOUND')          # PATH is never searched
            for bad in ('flac', '/nonexistent/flac', str(FIXTURES), str(FIXTURES / 'mono-8000.wav'), 3, ['/bin/true']):
                self.fault(lambda: adaptor.runtime(bad), 'INTERPRETER_NOT_FOUND')

    def test_explicit_stored_and_environment_routes_are_ordered(self):
        with private_configuration({'flac': '/bin/true'}):
            self.assertEqual(adaptor.runtime(), {'flac': '/bin/true'})
            self.assertEqual(adaptor.runtime('/bin/false'), {'flac': '/bin/false'})
        with private_configuration():
            with mock.patch.dict(os.environ, {'SCHEMAXIS_FLAC': '/bin/true'}):
                self.assertEqual(adaptor.runtime(), {'flac': '/bin/true'})
        with private_configuration():
            recovery = self.fault(lambda: adaptor.runtime(), 'INTERPRETER_NOT_FOUND').observed['recovery']
            self.assertIn('SCHEMAXIS_FLAC', recovery)
            self.assertIn('no --flac flag', recovery)

    def test_help_readiness_and_docs_do_not_claim_the_run_flag_reaches_bare_verify(self):
        help_text = registry.ADAPTORS['flac']['cliOptions'][0]['help']
        self.assertIn('schemaxis verify has no such flag', help_text)
        self.assertIn('SCHEMAXIS_FLAC', help_text)
        docs = (ROOT / 'docs/flac.md').read_text()
        self.assertIn('SCHEMAXIS_FLAC=/path/to/flac schemaxis verify output/decode', docs)
        self.assertIn('no independent host FLAC decoder', docs)
        self.assertIn('does not claim host-independent', docs)
        self.assertIn('does not certify', docs)
        readiness = (ROOT / 'src/schemaxis/adaptors/flac/readiness.json').read_text()
        self.assertIn('SCHEMAXIS_FLAC', readiness)
        self.assertNotIn('also for verify', readiness + docs)

    # ------------------------------------------------------------ strict JSON and typed comparison
    def test_retained_json_is_read_strictly(self):
        good = b'{"a": [1, 2.5, true, null, "x"]}'
        self.assertEqual(adaptor.strict_json(good, 'x.json'), {'a': [1, 2.5, True, None, 'x']})
        deep = b'[' * 100000 + b']' * 100000
        for label, bad in (('duplicate', b'{"a": 1, "a": 2}'), ('nested duplicate', b'{"a": {"b": 1, "b": 1}}'), ('NaN', b'{"a": NaN}'),
                           ('Infinity', b'{"a": Infinity}'), ('-Infinity', b'{"a": -Infinity}'), ('overflow', b'{"a": 1e400}'),
                           ('negative overflow', b'{"a": -1e400}'), ('byte-order mark', b'\xef\xbb\xbf' + good),
                           ('UTF-16', good.decode().encode('utf-16')), ('invalid UTF-8', b'{"a": "\xff"}'), ('deep', deep), ('truncated', b'{"a":')):
            fault = self.fault(lambda: adaptor.strict_json(bad, 'x.json'), 'VERIFICATION_FAILED')
            self.assertIn('x.json', fault.message, label)

    def test_typed_comparison_does_not_collapse_booleans_numbers_or_member_order(self):
        self.assertTrue(adaptor.same_json({'b': 1, 'a': [True, 66]}, {'a': [True, 66], 'b': 1}))
        for actual, expected in ((1, True), (True, 1), (66.0, 66), (66, 66.0), (0, False), (0.0, 0), ([1], [True]), ({'a': 1}, {'a': 1.0}),
                                 ({'a': 1}, {'a': 1, 'b': 2}), ('1', 1), (float('nan'), float('nan')), (float('inf'), float('inf')), (None, 0)):
            self.assertFalse(adaptor.same_json(actual, expected), (actual, expected))
        nest = []
        for _ in range(100000):
            nest = [nest]
        self.assertFalse(adaptor.same_json(nest, nest))    # excess depth is a refusal, not a crash

    def test_result_claims_are_closed_typed_and_exclude_only_the_fresh_decoder_text(self):
        verified = {'verified': True, 'operation': 'encodeLossless', 'artifacts': 2, 'audio': {'sampleRate': 8000, 'channels': 1, 'frames': 3},
                    'bytes': {'flac': 9, 'wav': 8}, 'pcmSha256': 'ab', 'runtime': {'flac': 'flac 1.5.0', 'freshDecoder': 'flac 1.5.1'}}
        other = copy.deepcopy(verified)
        other['runtime']['freshDecoder'] = 'flac 1.5.2'
        self.assertTrue(adaptor.same_json(adaptor.result_claims(verified), adaptor.result_claims(other)))
        for label, mutate in (('bool', lambda r: r.update(verified=1)), ('float', lambda r: r.update(artifacts=2.0)), ('frames', lambda r: r['audio'].update(frames=3.0)),
                              ('decoder', lambda r: r['runtime'].update(flac='flac 1.5.1')), ('hash', lambda r: r.update(pcmSha256='cd')), ('operation', lambda r: r.update(operation='decodePCM16')),
                              ('extra field', lambda r: r.update(authenticityVerified=True)), ('extra runtime', lambda r: r['runtime'].update(accuracyCertified=True)),
                              ('missing fresh decoder', lambda r: r['runtime'].pop('freshDecoder')), ('fresh decoder type', lambda r: r['runtime'].update(freshDecoder=['flac 1.5.0'])),
                              ('fresh decoder text', lambda r: r['runtime'].update(freshDecoder='other 9')), ('runtime type', lambda r: r.update(runtime='flac 1.5.0')),
                              ('missing claim', lambda r: r.pop('pcmSha256'))):
            changed = copy.deepcopy(verified)
            mutate(changed)
            self.assertFalse(adaptor.same_json(adaptor.result_claims(verified), adaptor.result_claims(changed)), label)

    def test_identity_probe_pins_flac_1_5(self):
        self.assertEqual(adaptor.check_identity('flac 1.5.0\n'), 'flac 1.5.0')
        self.assertEqual(adaptor.check_identity('flac 1.5.12'), 'flac 1.5.12')
        for text in ('flac 1.4.3\n', 'flac 1.6.0\n', 'flac 1.5\n', 'flac 1.5.0\nextra\n', 'metaflac 1.5.0\n', 'FLAC 1.5.0\n', ' flac 1.5.0', ''):
            self.fault(lambda: adaptor.check_identity(text), 'UNSUPPORTED_RUNTIME')

    # ------------------------------------------------------------ launcher
    def test_launcher_is_fixed_bounded_and_clean_environment(self):
        text = adaptor.launcher('encode', ['source.pcm'], ['/x/flac', '-8'], 5000)
        self.assertIn('RLIMIT_FSIZE,(5000,5000)', text)
        self.assertIn('RLIMIT_AS', text)
        self.assertIn('{"LANG":"C","LC_ALL":"C"}', text)
        self.assertNotIn('shell', text)
        commands = adaptor.stage_commands(adaptor.plan(self.document()), '/x/flac', 48000, 2, 16396)
        self.assertEqual(list(commands), ['version', 'encode', 'decode'])
        argv = commands['encode'][0]
        self.assertEqual(argv[0], '/x/flac')
        self.assertEqual(argv[-5:], ['--channels=2', '--sample-rate=48000', '-o', 'audio.flac', 'source.pcm'])
        self.assertEqual(commands['encode'][1:], (['source.pcm'], 16396 + adaptor.OUTPUT_SLACK))
        self.assertEqual(commands['decode'][0], ['/x/flac', *adaptor.DECODE_ARGUMENTS, '-o', 'reopened.pcm', 'audio.flac'])
        decode = adaptor.stage_commands(adaptor.plan(self.document('decode')), '/x/flac', 16000, 2, 8196)
        self.assertEqual(list(decode), ['version', 'decode'])
        self.assertEqual(decode['decode'][0][-3:], ['-o', 'decoded.pcm', 'captured.flac'])
        for forbidden in ('--decode-through-errors', '--force', '-f', '--keep-foreign-metadata', '--no-md5-sum', '--lax', '-F'):
            self.assertNotIn(forbidden, adaptor.ENCODE_ARGUMENTS + adaptor.DECODE_ARGUMENTS)


if __name__ == '__main__':
    unittest.main()
