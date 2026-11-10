"""encodeAudio: a prepared PCM16 WAV to a verified AAC-LC/M4A with an exact numeric error budget.

Host contracts always run, with every native entry point replaced by one that fails the test if it is reached. The native cases need a
configured FFmpeg (stored configuration, SCHEMAXIS_CONFIG or FFMPEG_EXECUTABLE) with ffprobe beside it and skip otherwise. Sources are
deterministic generated tones (never speech); the bundled M4A fixture was published by this adaptor from the bundled WAV. Forgeries
rewrite digests, bindings, receipt and sidecars so the retained evidence stays self-consistent: only the fresh native decode refuses them.
The numeric budget is a waveform error measure; nothing here asserts listening quality."""
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import shutil
import stat
import struct
import tempfile
import unittest
from unittest import mock
import wave

from schemaxis.adaptors.ffmpeg import adaptor, audio, publish_audio as pub, review
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.configuration import executable as configured_executable
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise

FIXTURES = Path(__file__).resolve().parents[2] / 'examples' / 'schemaxis' / 'fixtures' / 'ffmpeg'


def runtime():
    try:
        path = configured_executable('ffmpeg') or os.environ.get('FFMPEG_EXECUTABLE')
    except SchemaxisError:
        return None
    probe = os.path.join(os.path.dirname(path), 'ffprobe') if path else None
    return path if path and os.access(path, os.X_OK) and os.access(probe, os.X_OK) else None


EXECUTABLE = runtime()
native = unittest.skipUnless(EXECUTABLE, 'a configured FFmpeg with ffprobe beside it is required')


def document(source, **options):
    values = {'file': str(source), 'bitrateKbps': 64, 'maxBytes': 4 << 20, 'maxMeanPCMError': 20000, **options}
    return {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'shareable', 'filter': 'encodeAudio', 'options': values}]}


def tone(frames, channels, rate, seed=0, silent=False):
    data = bytearray()
    for i in range(frames):
        for c in range(channels):
            value = 0 if silent else int(9000 * math.sin(2 * math.pi * (200 + 40 * seed + 90 * c) * i / rate) * (0.4 + 0.6 * math.sin(i / 811 + seed)))
            data += struct.pack('<h', value)
    return bytes(data)


def write_wav(path, frames, channels, rate, seed=0, silent=False):
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(tone(frames, channels, rate, seed, silent))
    return path


def chunk_count(data):
    """The number of chunk offsets (stco entries) the published M4A declares."""
    found = {}

    def walk(start, end):
        for kind, payload, stop in audio.boxes(data, start, end):
            found.setdefault(kind, payload)
            if kind in (b'moov', b'trak', b'mdia', b'minf', b'stbl'):
                walk(payload, stop)

    walk(0, len(data))
    return struct.unpack('>I', data[found[b'stco'] + 4:found[b'stco'] + 8])[0]


class Case(unittest.TestCase):
    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault.to_dict()


class NoNative:
    """Every route that could start a native process fails the test if it is reached."""
    def __enter__(self):
        def refuse(*args, **kwargs):
            raise AssertionError('a native process was started: %r' % (args[:1],))
        self.patches = [mock.patch.object(pub, 'execute', refuse), mock.patch.object(pub, 'launch', refuse)]
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in self.patches:
            patch.stop()


class HostTests(Case):
    def test_declaration_schema_and_plan_are_closed(self):
        declaration = adaptor.DECLARATIONS['encodeAudio']
        self.assertEqual(sorted(declaration['options']), ['bitrateKbps', 'file', 'maxBytes', 'maxMeanPCMError', 'threads'])
        variant = [v for v in adaptor.schema()['properties']['nodes']['items']['oneOf'] if v['properties']['filter']['const'] == 'encodeAudio'][0]
        self.assertEqual(variant['properties']['options']['required'], ['file', 'bitrateKbps', 'maxBytes', 'maxMeanPCMError'])
        prepared = adaptor.plan(document('/in/a.wav', bitrateKbps=128, maxMeanPCMError=1.5))
        self.assertEqual((prepared['output'], prepared['summary']), ('audio.m4a', 'audio-publish-summary.json'))
        self.assertEqual(prepared['nodes'][0]['options'], {'threads': 1, 'file': '/in/a.wav', 'bitrateKbps': 128, 'maxBytes': 4 << 20, 'maxMeanPCMError': 1.5})
        text = ' '.join(prepared['losses'] + [prepared['policy']])
        for needle in ('lossy', 'never labelled lossless or high quality', 'does not measure or certify listening', 'clip at full scale',
                       'no resampling, channel mixing, normalising, trimming or padding'):
            self.assertIn(needle, text)

    def test_every_authored_value_is_refused_before_any_native_process(self):
        cases = [('bitrateKbps', 100, 'INVALID_ARGUMENT'), ('bitrateKbps', 63, 'INVALID_ARGUMENT'), ('bitrateKbps', True, 'INVALID_ARGUMENT'),
                 ('bitrateKbps', '64', 'INVALID_ARGUMENT'), ('bitrateKbps', 64.0, 'INVALID_ARGUMENT'),
                 ('maxBytes', 0, 'INVALID_ARGUMENT'), ('maxBytes', (32 << 20) + 1, 'INVALID_ARGUMENT'), ('maxBytes', True, 'INVALID_ARGUMENT'),
                 ('maxBytes', 10.0, 'INVALID_ARGUMENT'), ('maxMeanPCMError', -0.001, 'INVALID_ARGUMENT'), ('maxMeanPCMError', -1, 'INVALID_ARGUMENT'),
                 ('maxMeanPCMError', 65535.0001, 'INVALID_ARGUMENT'), ('maxMeanPCMError', float('nan'), 'INVALID_ARGUMENT'),
                 ('maxMeanPCMError', float('inf'), 'INVALID_ARGUMENT'), ('maxMeanPCMError', True, 'INVALID_ARGUMENT'),
                 ('maxMeanPCMError', '1', 'INVALID_ARGUMENT'), ('threads', 17, 'INVALID_ARGUMENT'), ('file', 'relative.wav', 'INVALID_RESOURCE'),
                 ('file', '/in/a.m4a', 'UNSUPPORTED_AUDIO'), ('file', '/in/a\0.wav', 'INVALID_RESOURCE'), ('codec', 'aac', 'UNKNOWN_ARGUMENT'),
                 ('filters', 'volume=2', 'UNKNOWN_ARGUMENT')]
        with tempfile.TemporaryDirectory() as temporary, NoNative():
            for name, value, code in cases:
                with self.subTest(name, value=value):
                    out = Path(temporary) / ('out-%s' % name)
                    self.fault(lambda: adaptor.run(document('/in/a.wav', **{name: value}), out, executable='/nowhere/ffmpeg'), code)
                    self.assertFalse(out.exists(), 'no output directory for an invalid authored value')
            for name in ('bitrateKbps', 'maxBytes', 'maxMeanPCMError', 'file'):
                missing = document('/in/a.wav')
                del missing['nodes'][0]['options'][name]
                self.fault(lambda: adaptor.plan(missing), 'MISSING_ARGUMENT')
            extra = document('/in/a.wav')
            extra['deliverable'] = {'frames': 1}
            self.fault(lambda: adaptor.plan(extra), 'INVALID_ARGUMENT')

    def test_legacy_operations_keep_their_declarations_and_plans(self):
        expected = {'encodeFrames': ['codec', 'files', 'fps', 'threads'], 'encodeSheet': ['codec', 'file', 'fps', 'metadata', 'threads'],
                    'encodeVideo': ['codec', 'endFrame', 'file', 'fps', 'startFrame', 'threads'],
                    'muxReview': ['audio', 'captionStatus', 'captions', 'threads', 'video'], 'extractAudio': ['file', 'streamIndex', 'threads']}
        for name, options in expected.items():
            self.assertEqual(sorted(adaptor.DECLARATIONS[name]['options']), options, name)
        plan = adaptor.plan({'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 's', 'filter': 'extractAudio', 'options': {'file': '/in/a.m4a', 'streamIndex': 1}}]})
        self.assertEqual((plan['output'], plan['summary'], plan['policy']), ('audio.wav', 'audio-summary.json', audio.POLICY))
        self.assertEqual(adaptor.plan({'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'v', 'filter': 'encodeVideo',
            'options': {'file': '/in/a.mkv', 'endFrame': 2}}]})['output'], 'video.mp4')

    def test_budget_comparison_is_exact_rational_arithmetic_with_inclusive_endpoints(self):
        def accepted(error_sum, samples, budget):
            measured = {'errorSum': error_sum, 'samples': samples}
            return pub.assess({'maxMeanPCMError': budget, 'maxBytes': 10}, measured, 10)['checks'][0]['passed']
        self.assertTrue(accepted(0, 5, 0))
        self.assertTrue(accepted(0, 5, -0.0))
        self.assertFalse(accepted(1, 5, 0))
        self.assertTrue(accepted(1, 5, 0.2), 'the decimal 0.2 is exactly 1/5, not the nearest binary float')
        self.assertFalse(accepted(7, 5, 1.2))
        self.assertTrue(accepted(6, 5, 1.2))
        self.assertTrue(accepted(3, 2, 1.5))
        self.assertFalse(accepted(4, 2, 1.9999999999999998))
        self.assertTrue(accepted(4, 2, 2))
        self.assertTrue(accepted(4, 2, 2.0))
        # 1/3 lies strictly between neighbouring decimals: no float epsilon decides it.
        self.assertFalse(accepted(1, 3, 0.3333333333333333))
        self.assertTrue(accepted(1, 3, 0.33333333333333337))
        self.assertTrue(accepted(65535 * 7, 7, 65535))
        self.assertFalse(accepted(65535 * 7 + 1, 7, 65535))
        self.assertTrue(accepted(1, 100000, 1e-05))
        self.assertFalse(accepted(2, 100000, 1e-05))
        self.assertEqual(pub.budget({'maxMeanPCMError': 0.1}), Fraction(1, 10))
        for bytes_, limit, ok in ((10, 10, True), (11, 10, False), (9, 10, True)):
            self.assertIs(pub.assess({'maxMeanPCMError': 1, 'maxBytes': limit}, {'errorSum': 0, 'samples': 1}, bytes_)['checks'][1]['passed'], ok)

    def test_every_interleaved_sample_is_compared(self):
        source = tone(5000, 2, 44100)
        same = pub.compare(source, source, 2)
        self.assertEqual((same['errorSum'], same['maxAbsError'], same['samples']), (0, 0, 10000))
        for index in (0, 1, 4999 * 2, 9999, 7777):
            samples = bytearray(source)
            samples[index * 2:index * 2 + 2] = struct.pack('<h', struct.unpack('<h', source[index * 2:index * 2 + 2])[0] + 3)
            found = pub.compare(source, bytes(samples), 2)
            self.assertEqual((found['errorSum'], found['maxAbsError']), (3, 3), index)
            self.assertEqual(found['channelErrorSums'][index % 2], 3)
        rails = pub.compare(struct.pack('<hhhh', 32767, -32768, 5, 5), struct.pack('<hhhh', 32767, -32767, 32767, 5), 2)
        self.assertEqual((rails['sourceFullScale'], rails['decodedFullScale'], rails['errorSum']), (2, 2, 1 + 32762))
        self.fault(lambda: pub.compare(source, source[:-2], 2), 'VERIFICATION_FAILED')
        many = tone(pub.CHUNK + 7, 2, 16000)
        shifted = bytearray(many)
        shifted[-2:] = struct.pack('<h', 1 + struct.unpack('<h', many[-2:])[0])
        self.assertEqual(pub.compare(many, bytes(shifted), 2)['errorSum'], 1, 'the tail beyond the first chunk is compared too')

    def test_source_subset_is_checked_on_the_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            facts = pub.source_facts(write_wav(temporary / 'ok.wav', 100, 2, 48000).read_bytes())
            self.assertEqual((facts['sampleRate'], facts['channels'], facts['frames']), (48000, 2, 100))
            for rate in (8000, 11025, 24000, 32000, 96000):
                self.fault(lambda: pub.source_facts(write_wav(temporary / 'r.wav', 10, 1, rate).read_bytes()), 'UNSUPPORTED_AUDIO')
            good = write_wav(temporary / 'g.wav', 10, 1, 16000).read_bytes()
            for label, data, code in (('empty', b'', 'INVALID_RESOURCE'), ('truncated', good[:-3], 'INVALID_RESOURCE'),
                                      ('trailing', good + b'\0', 'INVALID_RESOURCE'), ('header-only', good[:44], 'INVALID_RESOURCE'),
                                      ('LIST chunk', good[:36] + b'LIST' + struct.pack('<I', 0) + good[36:], 'INVALID_RESOURCE')):
                with self.subTest(label):
                    self.fault(lambda: pub.source_facts(data), code)
            eight = bytearray(good)
            eight[34:36] = struct.pack('<H', 8)
            self.fault(lambda: pub.source_facts(bytes(eight)), 'UNSUPPORTED_AUDIO')
            six = bytearray(good)
            six[22:24] = struct.pack('<H', 6)
            self.fault(lambda: pub.source_facts(bytes(six)), 'UNSUPPORTED_AUDIO')
            with mock.patch.object(pub, 'MAX_SECONDS', 0):
                self.fault(lambda: pub.source_facts(good), 'RESOURCE_LIMIT')
            path = temporary / 'size.wav'
            path.write_bytes(good)
            with mock.patch.object(pub, 'MAX_WAV', 20):
                self.fault(lambda: pub.read_source(path), 'RESOURCE_LIMIT')
            folder = temporary / 'folder.wav'
            folder.mkdir()
            self.fault(lambda: adaptor.reusableInputs(document(folder)), 'INVALID_RESOURCE')
            fifo = temporary / 'pipe.wav'
            os.mkfifo(fifo)
            self.fault(lambda: adaptor.reusableInputs(document(fifo)), 'INVALID_RESOURCE')
            self.assertEqual(adaptor.reusableInputs(document(path)), {str(path): hashlib.sha256(good).hexdigest()})

    def test_the_real_duration_and_size_limits_are_decided_exactly_and_classified_not_clamped(self):
        def silence(frames, channels, rate):
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as handle:
                handle.setnchannels(channels)
                handle.setsampwidth(2)
                handle.setframerate(rate)
                handle.writeframes(bytes(2 * channels * frames))
            return buffer.getvalue()

        exact = silence(600 * 16000, 1, 16000)
        self.assertEqual(pub.source_facts(exact)['frames'], 600 * 16000)
        self.assertLess(len(exact), pub.MAX_WAV)
        fault = self.fault(lambda: pub.source_facts(silence(600 * 16000 + 1, 1, 16000)), 'RESOURCE_LIMIT')
        self.assertIn('600 seconds', fault['message'])
        full = silence((pub.MAX_WAV - 44) // 4, 2, 48000)  # exactly 32 MiB at 48 kHz stereo (about 175 s)
        self.assertEqual(len(full), pub.MAX_WAV)
        self.assertEqual(pub.source_facts(full)['frames'], (pub.MAX_WAV - 44) // 4)
        fault = self.fault(lambda: pub.source_facts(silence((pub.MAX_WAV - 44) // 4 + 1, 2, 48000)), 'RESOURCE_LIMIT')
        self.assertIn('32 MiB', fault['message'])

    def test_unsupported_source_and_missing_runtime_start_nothing(self):
        with tempfile.TemporaryDirectory() as temporary, NoNative():
            temporary = Path(temporary)
            fake = temporary / 'bin'
            fake.mkdir()
            for name in ('ffmpeg', 'ffprobe'):
                (fake / name).write_text('#!/bin/sh\ntouch %s/ran\n' % temporary)
                (fake / name).chmod(0o755)
            source = write_wav(temporary / 'rate.wav', 10, 1, 8000)
            fault = self.fault(lambda: adaptor.run(document(source), temporary / 'out', executable=str(fake / 'ffmpeg')), 'UNSUPPORTED_AUDIO')
            self.assertEqual(fault['location'], pub.LOCATION + 'file')
            self.assertFalse((temporary / 'out').exists() or (temporary / 'ran').exists())
            empty = temporary / 'empty.json'
            atomic_json(empty, {'version': 1, 'locations': {}})
            ok = write_wav(temporary / 'ok.wav', 10, 1, 16000)
            with mock.patch.dict(os.environ, {'SCHEMAXIS_CONFIG': str(empty), 'PATH': str(fake)}):
                os.environ.pop('FFMPEG_EXECUTABLE', None)
                fault = self.fault(lambda: adaptor.run(document(ok), temporary / 'out2'), 'INTERPRETER_NOT_FOUND')
                self.assertIn('encodeAudio', fault['message'])
                self.assertFalse((temporary / 'out2').exists() or (temporary / 'ran').exists())

    def test_recipe_is_fixed_local_and_without_authored_flags(self):
        options = {'bitrateKbps': 96, 'threads': 2, 'maxBytes': 1000}
        recipe = pub.commands('/tools/ffmpeg', Path('/run'), options, 22050)
        encode = ' '.join(recipe['encode'])
        for needle in ('-protocol_whitelist file -f wav', '-c:a aac -profile:a aac_low -b:a 96k', '-flags:a +bitexact -fflags +bitexact',
                       '-movflags +faststart -movie_timescale 22050 -f mp4 /run/audio.m4a', '-map_metadata -1', '-map_chapters -1'):
            self.assertIn(needle, encode)
        for forbidden in ('-ar', '-ac', '-af', '-filter_complex', '-ss', '-t', '-to', '-shortest', '-vol', '-apad', '-atrim', 'loudnorm'):
            self.assertNotIn(forbidden, recipe['encode'] + recipe['decode'], forbidden + ' would resample, mix, trim, pad or normalise')
        for stage in ('probe', 'frames', 'decode'):
            joined = ' '.join(recipe[stage])
            self.assertIn('-protocol_whitelist file -f mov', joined)
            self.assertIn('-enable_drefs 0 -use_absolute_path 0', joined)
        self.assertEqual((recipe['probe'][0], recipe['frames'][0]), ('/tools/ffprobe', '/tools/ffprobe'))
        self.assertIn('pcm_s16le', recipe['decode'])
        self.assertEqual(pub.limit_for('encode', options), 1000 + pub.OUTPUT_SLACK)
        self.assertEqual(pub.limit_for('decode', options, 10, 2), 40 + pub.OUTPUT_SLACK)
        self.assertEqual(pub.limit_for('probe', options), pub.MAX_PROBE + 1)
        text = pub.launcher(Path('/run'), 'probe', ['/tools/ffprobe'], 77)
        for needle in ('RLIMIT_AS', 'RLIMIT_FSIZE, (77,)', 'RLIMIT_CPU', 'RLIMIT_CORE', 'S_ISREG', 'is_symlink', 'probe-inputs.json', 'audio.m4a', 'execvpe'):
            self.assertIn(needle, text)
        self.assertIn('input-0000', pub.launcher(Path('/run'), 'encode', ['/tools/ffmpeg'], 77))


class ContainerTests(Case):
    """The closed container parser on the shipped, adaptor-published fixture and on byte-level mutations of it."""
    data = (FIXTURES / 'audio-publish-mono-16k.m4a').read_bytes()
    FRAMES, RATE = 1025, 16000

    def parse(self, data=None):
        return pub.container(self.data if data is None else data, self.RATE, 1, self.FRAMES)

    def patched(self, marker, offset, replacement):
        position = self.data.index(marker)
        out = bytearray(self.data)
        out[position + offset:position + offset + len(replacement)] = replacement
        return bytes(out)

    def test_fixture_geometry_is_byte_accounted(self):
        geometry = self.parse()
        self.assertEqual((geometry['packets'], geometry['primingFrames'], geometry['editList']['segmentDuration']), (3, 1024, 1025))
        self.assertEqual((geometry['movieTimescale'], geometry['mediaTimescale'], geometry['metadataItems']), (16000, 16000, 0))

    def test_every_geometry_claim_is_refused_when_wrong(self):
        cases = {'rate': lambda: pub.container(self.data, 22050, 1, self.FRAMES), 'channels': lambda: pub.container(self.data, self.RATE, 2, self.FRAMES),
                 'frames': lambda: pub.container(self.data, self.RATE, 1, self.FRAMES + 1),
                 'trailing byte': lambda: self.parse(self.data + b'\0'), 'truncated': lambda: self.parse(self.data[:-9]),
                 'elst segment': lambda: self.parse(self.patched(b'elst', 12, struct.pack('>I', 1024))),
                 'elst media time': lambda: self.parse(self.patched(b'elst', 16, struct.pack('>i', 1000))),
                 'elst rate': lambda: self.parse(self.patched(b'elst', 20, struct.pack('>H', 2))),
                 'two entries': lambda: self.parse(self.patched(b'elst', 8, struct.pack('>I', 2))),
                 'mvhd timescale': lambda: self.parse(self.patched(b'mvhd', 16, struct.pack('>I', 1000))),
                 'mdhd duration': lambda: self.parse(self.patched(b'mdhd', 16, struct.pack('>I', 99))),
                 'stco offset': lambda: self.parse(self.patched(b'stco', 12, struct.pack('>I', 800))),
                 'stsz entry': lambda: self.parse(self.patched(b'stsz', 16, struct.pack('>I', 1))),
                 'brand': lambda: self.parse(self.patched(b'ftyp', 4, b'M4A ')),
                 'mp4a channels': lambda: self.parse(self.patched(b'mp4a', 20, struct.pack('>H', 2))),
                 'mp4a rate': lambda: self.parse(self.patched(b'mp4a', 28, struct.pack('>I', 22050 << 16))),
                 'handler': lambda: self.parse(self.patched(b'hdlr', 12, b'vide')),
                 'extra top box': lambda: self.parse(self.data + struct.pack('>I4s', 8, b'free')),
                 'external reference': lambda: self.parse(self.patched(b'url ', 4, b'\0\0\0\0'))}
        for label, action in cases.items():
            with self.subTest(label):
                self.fault(action, 'VERIFICATION_FAILED')

    def test_metadata_items_and_foreign_boxes_are_refused(self):
        position = self.data.index(b'ilst') - 4
        tagged = bytearray(self.data)
        item = struct.pack('>I4s', 8, b'\xa9nam')
        tagged[position:position + 4] = struct.pack('>I', 8 + len(item))
        tagged = bytes(tagged[:position + 8]) + item + bytes(tagged[position + 8:])
        self.fault(lambda: self.parse(tagged), 'VERIFICATION_FAILED')


class ChunkTableTests(Case):
    """Multi-chunk layouts: the muxer starts a new chunk before one would reach 1 MiB, so the chunk tables are accounted physically.

    Valid multi-chunk files are the shipped fixture with its two chunk tables rewritten (same payload bytes, enclosing sizes and absolute
    offsets repaired); every invalid file is one precise mutation of such a layout."""
    data = (FIXTURES / 'audio-publish-mono-16k.m4a').read_bytes()
    FRAMES, RATE = 1025, 16000

    def setUp(self):
        top = list(audio.boxes(self.data, 0, len(self.data)))
        self.where = {}

        def walk(start, end):
            for kind, payload, stop in audio.boxes(self.data, start, end):
                self.where.setdefault(kind, (payload - 8, payload, stop))
                if kind in (b'moov', b'trak', b'mdia', b'minf', b'stbl'):
                    walk(payload, stop)

        walk(0, len(self.data))
        stsz = self.where[b'stsz']
        self.sizes = list(struct.unpack('>3I', self.data[stsz[1] + 12:stsz[2]]))
        self.assertEqual(len(top), 4)

    def build(self, runs, relative=None, chunks=None, runs_declared=None, chunks_declared=None, flags=bytes(4), extra=b''):
        """The fixture with ``runs`` (first_chunk, samples, description) and chunk offsets relative to the mdat payload start."""
        if relative is None:
            # Derived layout only: its geometry is bounded by the fixture's packet count. Run indexes are otherwise just table values
            # (a hostile 2**32-1 index must never be expanded into per-chunk lists).
            counts = []
            for index, (first, samples, _) in enumerate(runs):
                span = (runs[index + 1][0] if index + 1 < len(runs) else (chunks or len(runs)) + 1) - first
                self.assertLessEqual(span, len(self.sizes), 'derived fixture geometry must stay within the fixture packet count')
                counts += [samples] * span
            position, relative, sample = 0, [], 0
            for count in counts:
                relative.append(position)
                position += sum(self.sizes[sample:sample + count])
                sample += count
        stsc = flags + struct.pack('>I', len(runs) if runs_declared is None else runs_declared) + b''.join(struct.pack('>III', *run) for run in runs)
        stco_head = bytes(4) + struct.pack('>I', len(relative) if chunks_declared is None else chunks_declared)
        old_stsc, old_stco, mdat = self.where[b'stsc'], self.where[b'stco'], self.where[b'mdat']
        growth = (len(stsc) - (old_stsc[2] - old_stsc[1])) + (len(relative) * 4 - (old_stco[2] - old_stco[1] - 8))
        payload_start = mdat[1] + growth
        stco = stco_head + b''.join(struct.pack('>I', payload_start + value) for value in relative)
        out = bytearray(self.data[:old_stsc[1]] + stsc + self.data[old_stsc[2]:old_stco[1]] + stco + self.data[old_stco[2]:])
        for kind in (b'moov', b'trak', b'mdia', b'minf', b'stbl'):
            header = self.where[kind][0]
            out[header:header + 4] = struct.pack('>I', struct.unpack('>I', self.data[header:header + 4])[0] + growth)
        out[old_stsc[0]:old_stsc[0] + 4] = struct.pack('>I', 8 + len(stsc))
        position = old_stco[0] + len(stsc) - (old_stsc[2] - old_stsc[1])
        out[position:position + 4] = struct.pack('>I', 8 + len(stco))
        return bytes(out) + extra

    def slack(self, data):
        """One unaccounted byte inside the mdat payload (its box size repaired), after the last chunk."""
        mdat = list(audio.boxes(data, 0, len(data)))[-1]
        out = bytearray(data + b'\0')
        out[mdat[1] - 8:mdat[1] - 4] = struct.pack('>I', struct.unpack('>I', data[mdat[1] - 8:mdat[1] - 4])[0] + 1)
        return bytes(out)

    def parse(self, data):
        return pub.container(data, self.RATE, 1, self.FRAMES)

    def test_the_rebuilt_single_chunk_layout_is_the_shipped_fixture(self):
        self.assertEqual(self.build([(1, 3, 1)]), self.data)

    def test_valid_multi_chunk_layouts_are_accepted_and_keep_the_packet_count(self):
        for label, runs in (('two chunks, two runs', [(1, 2, 1), (2, 1, 1)]), ('three one-packet chunks', [(1, 1, 1)]),
                            ('redundant runs', [(1, 1, 1), (2, 1, 1), (3, 1, 1)]), ('one packet then two', [(1, 1, 1), (2, 2, 1)])):
            with self.subTest(label):
                chunks = {'three one-packet chunks': 3, 'redundant runs': 3}.get(label)
                geometry = self.parse(self.build(runs, chunks=chunks))
                self.assertEqual((geometry['packets'], geometry['primingFrames'], geometry['bytes']), (3, 1024, len(self.build(runs, chunks=chunks))))

    def test_every_chunk_table_inconsistency_is_refused(self):
        a, b, c = self.sizes
        two = [(1, 2, 1), (2, 1, 1)]
        cases = {
            'second offset gap': lambda: self.build(two, relative=[0, a + b + 1]),
            'second offset overlap': lambda: self.build(two, relative=[0, a + b - 1]),
            'offsets out of order': lambda: self.build([(1, 1, 1), (2, 2, 1)], relative=[a, 0]),
            'duplicate offset': lambda: self.build(two, relative=[0, 0]),
            'first offset not the payload start': lambda: self.build(two, relative=[1, a + b + 1]),
            'chunks place only two of the three packets': lambda: self.build([(1, 1, 1), (2, 1, 1)], relative=[0, a], chunks=2),
            'last chunk ends one byte short of the payload end': lambda: self.slack(self.build(two)),
            'chunks two and three swapped': lambda: self.build([(1, 1, 1)], relative=[0, a + b, a], chunks=3),
            'stray second mdat': lambda: self.build(two) + struct.pack('>I4s', 8, b'mdat'),
            'trailing mdat with a payload': lambda: self.build(two) + struct.pack('>I4s', 12, b'mdat') + bytes(4),
            'placed one packet too many': lambda: self.build([(1, 2, 1), (2, 2, 1)]),
            'placed one packet too few': lambda: self.build([(1, 1, 1), (2, 1, 1)]),
            'first chunk is 2': lambda: self.build([(2, 3, 1)], relative=[0]),
            'first chunk is 0': lambda: self.build([(0, 3, 1)], relative=[0]),
            'segment starts past the last chunk': lambda: self.build([(1, 2, 1), (3, 1, 1)], relative=[0, a + b]),
            'segment starts far past the last chunk': lambda: self.build([(1, 2, 1), (2 ** 32 - 1, 1, 1)], relative=[0, a + b]),
            'sample description 2': lambda: self.build([(1, 2, 2), (2, 1, 1)]),
            'sample description 0': lambda: self.build([(1, 3, 0)], relative=[0]),
            'zero samples in a run': lambda: self.build([(1, 0, 1), (2, 3, 1)]),
            'duplicate run entries': lambda: self.build([(1, 2, 1), (1, 1, 1)]),
            'decreasing run entries': lambda: self.build([(2, 1, 1), (1, 2, 1)]),
            'stsc declares one run more than it holds': lambda: self.build(two, runs_declared=3),
            'stsc declares one run fewer than it holds': lambda: self.build(two, runs_declared=1),
            'stco declares one chunk more than it holds': lambda: self.build(two, chunks_declared=3),
            'stco declares one chunk fewer than it holds': lambda: self.build(two, chunks_declared=1),
            'stco declares no chunk': lambda: self.build([(1, 3, 1)], relative=[0], chunks_declared=0),
            'stco declares 2**32-1 chunks in a small box': lambda: self.build([(1, 3, 1)], relative=[0], chunks_declared=2 ** 32 - 1),
            'stsc declares 2**32-1 runs in a small box': lambda: self.build([(1, 3, 1)], relative=[0], runs_declared=2 ** 32 - 1),
            'more chunks than packets': lambda: self.build([(1, 1, 1)], relative=[0, a, a + b, a + b + c], chunks=4),
            'more runs than chunks': lambda: self.build([(1, 1, 1), (2, 1, 1), (3, 1, 1)], relative=[0, a + b], chunks_declared=2),
            'sample counts that skip a chunk': lambda: self.build([(1, 2, 1), (3, 1, 1)], relative=[0, a + b, a + b], chunks=3),
            'stsc flags set': lambda: self.build([(1, 3, 1)], relative=[0], flags=b'\0\0\0\1'),
        }
        reasons = {
            'does not start where the previous chunk ended': (
                'second offset gap', 'second offset overlap', 'offsets out of order', 'duplicate offset',
                'first offset not the payload start', 'chunks two and three swapped'),
            'must place exactly the listed packets': (
                'chunks place only two of the three packets', 'placed one packet too many',
                'placed one packet too few', 'sample counts that skip a chunk'),
            'mdat payload must be exactly the listed packets': ('last chunk ends one byte short of the payload end',),
            'top-level boxes must be ftyp, moov, optional empty free, mdat in that order': (
                'stray second mdat', 'trailing mdat with a payload'),
            'runs must start at chunk 1, strictly increase and stay within the chunk offset table': (
                'first chunk is 2', 'first chunk is 0', 'segment starts past the last chunk',
                'segment starts far past the last chunk', 'duplicate run entries', 'decreasing run entries'),
            'every chunk run must hold at least one sample of sample description 1': (
                'sample description 2', 'sample description 0', 'zero samples in a run'),
            'sample-to-chunk table must hold between one and one entry per chunk': (
                'stsc declares one run more than it holds', 'stsc declares one run fewer than it holds',
                'stsc declares 2**32-1 runs in a small box', 'more runs than chunks'),
            'chunk offset table must hold one entry per chunk': (
                'stco declares one chunk more than it holds', 'stco declares one chunk fewer than it holds',
                'stco declares no chunk', 'stco declares 2**32-1 chunks in a small box', 'more chunks than packets'),
            'chunk tables must be version 0 with no flags': ('stsc flags set',),
        }
        expected = {label: reason for reason, labels in reasons.items() for label in labels}
        self.assertEqual(set(expected), set(cases))
        for label, make in cases.items():
            with self.subTest(label):
                data = make()
                self.assertNotEqual(data, self.data)
                fault = self.fault(lambda: self.parse(data), 'VERIFICATION_FAILED')
                self.assertIn(expected[label], fault['message'])

    def test_the_accounting_is_decided_by_the_tables_not_by_the_trailing_chunk_count(self):
        # The same bytes with the two chunk tables disagreeing about where chunk two begins must not pass as one chunk plus slack.
        a, b, c = self.sizes
        self.fault(lambda: self.parse(self.build([(1, 2, 1), (2, 1, 1)], relative=[0, a + b + c])), 'VERIFICATION_FAILED')

    def synthetic(self, runs, offsets, packets, payload_end, sizes=None):
        stsc = bytes(4) + struct.pack('>I', len(runs)) + b''.join(struct.pack('>III', *run) for run in runs)
        stco = bytes(4) + struct.pack('>I', len(offsets)) + struct.pack('>%dI' % len(offsets), *offsets)
        blob = b'\0' * 8 + stsc + stco
        sizes = sizes or [100 + (i % 7) for i in range(packets)]
        return (blob, ('stsc', 8, 8 + len(stsc)), ('stco', 8 + len(stsc), 8 + len(stsc) + len(stco)), sizes,
                ('mdat', 1000, payload_end if payload_end is not None else 1000 + sum(sizes)))

    def test_the_largest_packet_count_is_accounted_in_linear_time_with_arbitrary_run_shapes(self):
        import time
        packets = pub.MAX_PACKETS
        sizes = [100 + (i % 7) for i in range(packets)]
        # one packet per chunk
        offsets, position = [], 1000
        for size in sizes:
            offsets.append(position)
            position += size
        started = time.monotonic()
        self.assertEqual(pub.chunk_layout(*self.synthetic([(1, 1, 1)], offsets, packets, None, sizes)), packets)
        # runs of alternating length: chunks of 1 and 2 packets, a new run at every chunk
        runs, offsets, position, sample, chunk = [], [], 1000, 0, 1
        while sample < packets:
            count = min(1 + chunk % 2, packets - sample)
            runs.append((chunk, count, 1))
            offsets.append(position)
            position += sum(sizes[sample:sample + count])
            sample += count
            chunk += 1
        self.assertEqual(pub.chunk_layout(*self.synthetic(runs, offsets, packets, None, sizes)), len(offsets))
        # a single chunk holding every packet
        self.assertEqual(pub.chunk_layout(*self.synthetic([(1, packets, 1)], [1000], packets, None, sizes)), 1)
        self.assertLess(time.monotonic() - started, 5, 'accounting must stay linear in the packet count')

    def test_synthetic_tables_end_exactly_at_the_payload_end(self):
        sizes = [10, 20, 30, 40]
        good = self.synthetic([(1, 2, 1), (2, 2, 1)], [1000, 1030], 4, None, sizes)
        self.assertEqual(pub.chunk_layout(*good), 2)
        for label, end in (('short', 1099), ('long', 1101)):
            with self.subTest(label):
                data, stsc, stco, packet_sizes, mdat = self.synthetic([(1, 2, 1), (2, 2, 1)], [1000, 1030], 4, end, sizes)
                self.fault(lambda: pub.chunk_layout(data, stsc, stco, packet_sizes, mdat), 'VERIFICATION_FAILED')
        data, stsc, stco, packet_sizes, mdat = self.synthetic([(1, 4, 1)], [1000], 4, None, sizes)
        self.assertEqual(pub.chunk_layout(data, stsc, stco, packet_sizes, mdat), 1)
        for label, offsets in (('late second chunk', [1000, 1031]), ('early second chunk', [1000, 1029]), ('second chunk first', [1030, 1000])):
            with self.subTest(label):
                data, stsc, stco, packet_sizes, mdat = self.synthetic([(1, 2, 1), (2, 2, 1)], offsets, 4, None, sizes)
                self.fault(lambda: pub.chunk_layout(data, stsc, stco, packet_sizes, mdat), 'VERIFICATION_FAILED')


class ProbeTests(Case):
    """Probe and decoded-frame reports are judged against the source and the container; every drift is a refusal."""
    SOURCE = {'sampleRate': 16000, 'channels': 1, 'frames': 1025}

    def good(self):
        stream = {'index': 0, 'codec_type': 'audio', 'codec_name': 'aac', 'profile': 'LC', 'codec_tag_string': 'mp4a', 'sample_rate': '16000',
                  'channels': 1, 'time_base': '1/16000', 'start_pts': 0, 'start_time': '0.000000', 'duration_ts': 1025, 'initial_padding': 1024,
                  'nb_frames': '3'}
        probe = {'streams': [stream], 'format': {'nb_streams': 1, 'format_name': 'mov,mp4,m4a,3gp,3g2,mj2', 'size': '1667'}, 'chapters': [], 'programs': []}
        listing = {'frames': [{'pts': 0, 'nb_samples': 1024}, {'pts': 1024, 'nb_samples': 1}]}
        return probe, listing

    def inspect(self, probe, listing):
        geometry = {'packets': 3, 'primingFrames': 1024}
        return pub.inspect(probe, listing, self.SOURCE, geometry, 1667)

    def test_accepts_the_matching_report_and_refuses_each_drift(self):
        probe, listing = self.good()
        self.assertEqual(self.inspect(probe, listing)['frames'], 1025)
        mutations = [('duration', lambda p, l: p['streams'][0].update(duration_ts=1026)), ('start', lambda p, l: p['streams'][0].update(start_pts=1)),
                     ('start time', lambda p, l: p['streams'][0].update(start_time='0.010000')),
                     ('profile', lambda p, l: p['streams'][0].update(profile='HE-AAC')), ('codec', lambda p, l: p['streams'][0].update(codec_name='mp3')),
                     ('rate', lambda p, l: p['streams'][0].update(sample_rate='22050')), ('channels', lambda p, l: p['streams'][0].update(channels=2)),
                     ('time base', lambda p, l: p['streams'][0].update(time_base='1/1000')),
                     ('padding', lambda p, l: p['streams'][0].update(initial_padding=0)), ('packets', lambda p, l: p['streams'][0].update(nb_frames='4')),
                     ('size', lambda p, l: p['format'].update(size='1')), ('second stream', lambda p, l: p['streams'].append(dict(p['streams'][0], index=1))),
                     ('chapters', lambda p, l: p.update(chapters=[{'id': 1}])), ('format', lambda p, l: p['format'].update(format_name='matroska,webm')),
                     ('gap', lambda p, l: l['frames'][1].update(pts=1030)), ('offset', lambda p, l: l['frames'][0].update(pts=5)),
                     ('short', lambda p, l: l['frames'][1].update(nb_samples=0)), ('long', lambda p, l: l['frames'][1].update(nb_samples=2)),
                     ('type', lambda p, l: l['frames'][1].update(nb_samples='1')), ('empty', lambda p, l: l.update(frames=[])),
                     ('missing', lambda p, l: p['streams'][0].pop('duration_ts')), ('no frames key', lambda p, l: l.pop('frames'))]
        for label, mutate in mutations:
            with self.subTest(label):
                probe, listing = self.good()
                mutate(probe, listing)
                self.fault(lambda: self.inspect(probe, listing), 'VERIFICATION_FAILED')


class FakeRuntimeTests(Case):
    """Stage failure classification with the runner replaced: staged logs only, no native process."""
    def test_cap_and_failure_classification(self):
        options = {'maxBytes': 100, 'bitrateKbps': 64, 'threads': 1}
        def staged(exit_code=0, stderr='', produced=b'x'):
            def execute(command, directory, stage, timeout, environment=None):
                directory = Path(directory)
                (directory / (stage + '.stderr')).write_text(stderr)
                (directory / (stage + '.stdout')).write_bytes(b'{}')
                (directory / pub.PRODUCED[stage]).write_bytes(produced)
                if exit_code:
                    from schemaxis.errors import fail
                    fail('RUNNER_FAILED', 'native execution did not complete', str(directory), exitCode=exit_code)
            return execute
        def launched(stage, limit, verifying=False, **kwargs):
            with tempfile.TemporaryDirectory() as temporary, mock.patch.object(pub, 'execute', staged(**kwargs)):
                pub.launch(Path(temporary), stage, ['/t/x'], limit, None, verifying, options)
        fault = self.fault(lambda: launched('encode', 104, produced=b'x' * 104), 'DELIVERABLE_NOT_MET')
        self.assertIn('refused, not truncated', fault['message'])
        self.fault(lambda: launched('decode', 50, produced=b'x' * 50), 'RESOURCE_LIMIT')
        self.fault(lambda: launched('probe', pub.MAX_PROBE + 1, produced=b'x' * (pub.MAX_PROBE + 1)), 'RESOURCE_LIMIT')
        self.fault(lambda: launched('probe', 100, exit_code=1), 'RUNNER_FAILED')
        self.fault(lambda: launched('probe', 100, stderr='warning'), 'RUNNER_FAILED')
        self.fault(lambda: launched('probe', 100, produced=b''), 'RUNNER_FAILED')
        fault = self.fault(lambda: launched('probe', 100, verifying=True, exit_code=1), 'VERIFICATION_FAILED')
        self.assertEqual(fault['observed']['cause']['code'], 'RUNNER_FAILED')
        launched('probe', 100)


@native
class NativeTests(Case):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='schemaxis-publish-test-'))
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def source(self, frames, channels, rate, **kwargs):
        type(self).counter += 1
        return write_wav(self.root / ('src-%d.wav' % self.counter), frames, channels, rate, **kwargs)

    def publish(self, source, **options):
        type(self).counter += 1
        directory = self.root / ('run-%d' % self.counter)
        adaptor.run(document(source, **options), directory, executable=EXECUTABLE)
        return directory

    def summary(self, directory):
        return json.loads((directory / 'audio-publish-summary.json').read_text())

    def test_every_rate_and_channel_count_publishes_the_exact_frame_count_and_verifies_fresh(self):
        for rate, channels, frames in ((16000, 1, 1), (16000, 2, 4097), (22050, 1, 2049), (22050, 2, 17), (44100, 1, 1025), (44100, 2, 30001),
                                       (48000, 1, 12345), (48000, 2, 999)):
            with self.subTest(rate=rate, channels=channels, frames=frames):
                directory = self.publish(self.source(frames, channels, rate))
                summary = self.summary(directory)
                self.assertEqual((summary['source']['frames'], summary['geometry']['editList']['segmentDuration']), (frames, frames))
                with wave.open(str(directory / 'decoded.wav')) as handle:
                    self.assertEqual((handle.getnframes(), handle.getframerate(), handle.getnchannels()), (frames, rate, channels))
                self.assertEqual(summary['comparison']['samples'], frames * channels)
                self.assertEqual(summary['geometry']['primingFrames'], 1024)
                first = adaptor.verify(directory, executable=EXECUTABLE)
                second = adaptor.verify(directory, executable=EXECUTABLE)
                self.assertIs(first['freshNativeVerification'], True)
                self.assertEqual(first, second, 'repeat fresh verification by the same trusted runtime agrees')
                self.assertEqual(sorted(p['file'].rsplit('/', 1)[1] for p in json.loads((directory / 'verification.json').read_text())['artifacts']),
                                 ['audio-publish-summary.json', 'audio.m4a'])
                for claim in ('losslessClaimed', 'highQualityClaimed', 'perceptualQualityCertified', 'recognitionAccuracyCertified', 'humanReviewVerified'):
                    self.assertIs(summary[claim], False)

    def test_error_budget_boundary_is_decided_exactly_on_published_bytes(self):
        source = self.source(8001, 1, 16000, seed=2)
        loose = self.publish(source, maxMeanPCMError=65535)
        measured = self.summary(loose)['comparison']
        mean = Fraction(measured['absoluteErrorSum'], measured['samples'])
        self.assertEqual(review.ratio(mean), measured['meanAbsPCMError'])
        above, below = math.nextafter(float(mean), math.inf), math.nextafter(float(mean), 0)
        self.assertGreater(Fraction(str(above)), mean)
        self.assertLess(Fraction(str(below)), mean)
        self.assertIs(self.summary(self.publish(source, maxMeanPCMError=above))['budgets']['accepted'], True)
        out = self.root / 'under-budget'
        fault = self.fault(lambda: adaptor.run(document(source, maxMeanPCMError=below), out, executable=EXECUTABLE), 'DELIVERABLE_NOT_MET')
        self.assertEqual(fault['observed']['assessment']['checks'][0]['passed'], False)
        self.assertFalse((out / 'audio.m4a').exists() or (out / 'audio-publish-summary.json').exists(), 'nothing is published for an unmet budget')
        self.assertEqual(json.loads((out / 'result.json').read_text())['status'], 'failed')
        silent = self.source(4000, 2, 48000, silent=True)
        self.assertEqual(self.summary(self.publish(silent, maxMeanPCMError=0))['comparison']['meanAbsPCMError'], '0/1', 'endpoint zero error accepted at budget 0')

    def test_byte_budget_endpoint_and_one_byte_under(self):
        source = self.source(6000, 2, 22050, seed=1)
        size = self.summary(self.publish(source, maxBytes=1 << 20))['published']['bytes']
        self.assertEqual(self.summary(self.publish(source, maxBytes=size))['published']['bytes'], size, 'the encoding is deterministic and the endpoint passes')
        out = self.root / 'under-bytes'
        fault = self.fault(lambda: adaptor.run(document(source, maxBytes=size - 1), out, executable=EXECUTABLE), 'DELIVERABLE_NOT_MET')
        self.assertIn('maxBytes', fault['location'])
        self.assertFalse((out / 'audio.m4a').exists())
        tiny = self.root / 'tiny-bytes'
        self.fault(lambda: adaptor.run(document(source, maxBytes=1), tiny, executable=EXECUTABLE), 'DELIVERABLE_NOT_MET')
        self.assertFalse((tiny / 'audio.m4a').exists())

    def test_bitrate_is_an_encoder_target_not_a_measured_claim(self):
        # The native encoder clamps by sample rate (16 kHz mono gave identical bytes at 96, 128 and 192 kbps) and output size is not
        # monotonic in the request, so the bitrate is recorded as a target and never as a measurement.
        source = self.source(24000, 1, 16000, seed=3)
        for rate in pub.BITRATES:
            summary = self.summary(self.publish(source, bitrateKbps=rate))
            self.assertEqual((summary['encoding']['bitrateKbps'], summary['encoding']['bitrateBasis']), (rate, 'encoder target (-b:a); not measured'))
            self.assertGreater(summary['published']['bytes'], 0)

    def test_shipped_fixture_source_publishes_and_the_bundled_m4a_matches_the_geometry(self):
        directory = self.publish(FIXTURES / 'audio-publish-mono-16k.wav', maxBytes=4096, maxMeanPCMError=2000)
        self.assertEqual((directory / 'audio.m4a').read_bytes(), (FIXTURES / 'audio-publish-mono-16k.m4a').read_bytes())

    def rebind(self, directory):
        """Refresh every digest, binding and sidecar to the altered bytes while keeping the retained readbacks."""
        directory = Path(directory)
        for stage in pub.STAGES:
            bound = directory / pub.bound_name(stage)
            (directory / (stage + '-inputs.json')).write_text(json.dumps({str(bound): file_digest(bound)}, sort_keys=True))
        receipt = json.loads((directory / 'verification.json').read_text())
        receipt['artifacts'] = pub.publications(directory)
        receipt['evidence'] = {name: file_digest(directory / name) for name in sorted(pub.evidence_names())}
        atomic_json(directory / 'verification.json', receipt)
        finalise(directory)

    def refused(self, directory, code='VERIFICATION_FAILED'):
        return self.fault(lambda: adaptor.verify(directory, executable=EXECUTABLE), code)

    def test_forged_publications_with_refreshed_evidence_are_refused(self):
        source = self.source(9001, 2, 44100, seed=4)
        other = self.publish(self.source(9001, 2, 44100, seed=9))
        base = self.publish(source)
        data = (base / 'audio.m4a').read_bytes()
        for label, offset in (('first payload byte', len(data) - 40), ('middle', len(data) // 2), ('container header', 30)):
            with self.subTest(label):
                forged = self.publish(source)
                changed = bytearray(data)
                changed[offset] ^= 0x55
                (forged / 'audio.m4a').write_bytes(bytes(changed))
                self.rebind(forged)
                self.refused(forged)
        swapped = self.publish(source)
        (swapped / 'audio.m4a').write_bytes((other / 'audio.m4a').read_bytes())
        self.rebind(swapped)
        self.refused(swapped)
        shorter = self.publish(source)
        (shorter / 'audio.m4a').write_bytes(data[:-100])
        self.rebind(shorter)
        self.refused(shorter)
        self.assertIs(adaptor.verify(base, executable=EXECUTABLE)['verified'], True)

    def test_output_beyond_one_mebibyte_spans_chunks_and_still_verifies_fresh(self):
        # The muxer starts a new chunk before one would reach 1 MiB; 46 s of 48 kHz stereo at 192 kbit/s is just over that.
        frames = 46 * 48000
        path = self.root / 'noise-46s.wav'
        with wave.open(str(path), 'wb') as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(48000)
            handle.writeframes(random.Random(7).randbytes(4 * frames))  # deterministic full-scale noise: only the container is asserted
        directory = self.publish(path, bitrateKbps=192, maxBytes=32 << 20, maxMeanPCMError=65535)
        published = (directory / 'audio.m4a').read_bytes()
        self.assertGreater(len(published), 1 << 20)
        self.assertGreater(chunk_count(published), 1)
        self.assertEqual(self.summary(directory)['published']['bytes'], len(published))
        geometry = self.summary(directory)['geometry']
        self.assertGreaterEqual(geometry['packets'] * 1024, frames + geometry['primingFrames'])
        self.assertIs(adaptor.verify(directory, executable=EXECUTABLE)['verified'], True)

    def test_a_recorded_ffprobe_that_is_not_the_sibling_of_the_recorded_ffmpeg_is_refused_without_running_it(self):
        source = self.source(2000, 1, 16000, seed=12)
        genuine = json.loads((self.publish(source) / 'verification.json').read_text())['executables']
        self.assertEqual(genuine['ffprobe'], os.path.join(os.path.dirname(genuine['ffmpeg']), 'ffprobe'))
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'ran'
            planted = Path(temporary) / 'ffprobe'
            planted.write_text('#!/bin/sh\necho planted > %s\n' % marker)
            planted.chmod(0o755)
            for label, change in (('ffprobe in another directory', {'ffprobe': str(planted)}),
                                  ('ffprobe under another name', {'ffprobe': genuine['ffprobe'] + '2'}),
                                  ('ffmpeg in another directory', {'ffmpeg': str(Path(temporary) / 'ffmpeg')})):
                with self.subTest(label):
                    trial = self.publish(source)
                    receipt = json.loads((trial / 'verification.json').read_text())
                    receipt['executables'].update(change)
                    atomic_json(trial / 'verification.json', receipt)
                    self.rebind(trial)  # every digest and sidecar now matches the altered receipt
                    self.assertIn('sibling', self.refused(trial)['message'])
            self.assertFalse(marker.exists())

    def test_forged_source_summary_result_receipt_and_launchers_are_refused(self):
        source = self.source(5001, 1, 22050, seed=5)
        directory = self.publish(source)
        capture = (directory / 'input-0000').read_bytes()
        forged = self.publish(source)
        altered = bytearray(capture)
        altered[100] ^= 0x7f
        (forged / 'input-0000').write_bytes(bytes(altered))
        atomic_json(forged / 'captures.json', {'source': str(source), 'bytes': len(altered), 'sha256': hashlib.sha256(altered).hexdigest()})
        self.rebind(forged)
        self.refused(forged)
        for label, name, change in (
                ('lossless claim', 'audio-publish-summary.json', lambda v: v.update(losslessClaimed=True)),
                ('quality claim', 'audio-publish-summary.json', lambda v: v.update(perceptualQualityCertified=True)),
                ('error figure', 'audio-publish-summary.json', lambda v: v['comparison'].update(meanAbsPCMError='1/1')),
                ('max error', 'audio-publish-summary.json', lambda v: v['comparison'].update(maxAbsPCMError=0)),
                ('budget check', 'audio-publish-summary.json', lambda v: v['budgets']['checks'][0].update(passed=False)),
                ('result float', 'result.json', lambda v: v.update(frames=float(v['frames']))),
                ('result bool', 'result.json', lambda v: v.update(lossy=1)),
                ('result extra', 'result.json', lambda v: v.update(extra=True)),
                ('receipt extra', 'verification.json', lambda v: v.update(extra=1)),
                ('receipt runtime', 'verification.json', lambda v: v.update(runtime='ffmpeg version 1')),
                ('receipt executable', 'verification.json', lambda v: v['executables'].update(ffmpeg='relative')),
                ('capture record', 'captures.json', lambda v: v.update(bytes=v['bytes'] + 1))):
            with self.subTest(label):
                trial = self.publish(source)
                path = trial / name
                value = json.loads(path.read_text())
                change(value)
                atomic_json(path, value)
                if name != 'verification.json':
                    receipt = json.loads((trial / 'verification.json').read_text())
                    receipt['artifacts'] = pub.publications(trial)
                    receipt['evidence'] = {n: file_digest(trial / n) for n in sorted(pub.evidence_names())}
                    atomic_json(trial / 'verification.json', receipt)
                    finalise(trial)
                self.refused(trial)
        for name in ('encode-launcher.py', 'decode-launcher.py'):
            trial = self.publish(source)
            (trial / name).write_text((trial / name).read_text().replace('RLIMIT_CORE', 'RLIMIT_NICE'))
            self.rebind(trial)
            self.refused(trial)
        trial = self.publish(source)
        (trial / 'stray.txt').write_text('x')
        self.refused(trial)
        trial = self.publish(source)
        path = trial / 'result.json'
        path.write_text(path.read_text().replace('"status": "succeeded"', '"status": "succeeded", "status": "failed"'))
        self.refused(trial)

    def test_corrupt_native_reports_are_refused(self):
        source = self.source(3001, 2, 48000, seed=6)
        real = os.path.join(os.path.dirname(EXECUTABLE), 'ffprobe')
        mutations = {'duration': "d['streams'][0]['duration_ts']+=1", 'start': "d['streams'][0]['start_pts']=1", 'profile': "d['streams'][0]['profile']='HE-AAC'",
                     'channels': "d['streams'][0]['channels']=1", 'extra stream': "d['streams'].append(dict(d['streams'][0], index=1))",
                     'gap': "d['frames'][1]['pts']+=1", 'long frame': "d['frames'][-1]['nb_samples']+=1"}
        for label, code in mutations.items():
            with self.subTest(label):
                bin_dir = self.root / ('fake-' + label.replace(' ', '-'))
                bin_dir.mkdir()
                (bin_dir / 'ffmpeg').write_text('#!/bin/sh\nexec %s "$@"\n' % EXECUTABLE)
                (bin_dir / 'mutate.py').write_text('import json, sys\nd = json.load(sys.stdin)\nif %r in d:\n    %s\njson.dump(d, sys.stdout)\n' % (code.split("'")[1], code))
                (bin_dir / 'ffprobe').write_text('#!/bin/sh\n%s "$@" | python3 %s\n' % (real, bin_dir / 'mutate.py'))
                for name in ('ffmpeg', 'ffprobe'):
                    (bin_dir / name).chmod(0o755)
                out = self.root / ('run-fake-' + label.replace(' ', '-'))
                fault = self.fault(lambda: adaptor.run(document(source), out, executable=str(bin_dir / 'ffmpeg')), 'VERIFICATION_FAILED')
                self.assertFalse((out / 'audio.m4a').exists(), 'nothing is published for a corrupt native report')
                self.assertEqual(json.loads((out / 'result.json').read_text())['status'], 'failed')

    def test_wrong_decoded_count_rate_or_channels_are_refused_not_trimmed(self):
        source = self.source(2001, 1, 16000, seed=7)
        real = review.parse_native_wav
        for label, change in (('count', lambda w: dict(w, bytes=w['bytes'] - 2, samples=w['samples'] - 1)), ('rate', lambda w: dict(w, sampleRate=44100)),
                              ('channels', lambda w: dict(w, channels=2))):
            with self.subTest(label), mock.patch.object(review, 'parse_native_wav', lambda data, location='x': change(real(data, location))):
                out = self.root / ('run-wrong-' + label)
                self.fault(lambda: adaptor.run(document(source), out, executable=EXECUTABLE), 'VERIFICATION_FAILED')
                self.assertFalse((out / 'audio.m4a').exists())

    def test_source_changed_after_capture_is_refused(self):
        source = self.source(3000, 1, 16000, seed=8)
        original = pub.launch
        def mutate(directory, stage, *args, **kwargs):
            if stage == 'encode':
                altered = bytearray(source.read_bytes())
                altered[200] ^= 1
                source.write_bytes(bytes(altered))
            return original(directory, stage, *args, **kwargs)
        out = self.root / 'run-changed-source'
        with mock.patch.object(pub, 'launch', mutate):
            fault = self.fault(lambda: adaptor.run(document(source), out, executable=EXECUTABLE), 'INVALID_RESOURCE')
        self.assertIn('changed after it was captured', fault['message'])
        self.assertFalse((out / 'audio.m4a').exists())
        bound = self.source(3000, 1, 16000, seed=8)
        def swap(directory, stage, *args, **kwargs):
            if stage == 'encode':
                (directory / 'input-0000').write_bytes(bound.read_bytes()[:-2] + b'\x01\x01')
            return original(directory, stage, *args, **kwargs)
        with mock.patch.object(pub, 'launch', swap):
            self.fault(lambda: adaptor.run(document(bound), self.root / 'run-swapped-capture', executable=EXECUTABLE), 'VERIFICATION_FAILED')

    def test_planted_runtime_and_receipt_paths_never_decide_and_scratch_is_cleaned(self):
        directory = self.publish(self.source(2000, 1, 16000, seed=10))
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'ran'
            for name in ('ffmpeg', 'ffprobe'):
                (Path(temporary) / name).write_text('#!/bin/sh\necho planted > %s\necho "not ffmpeg"\n' % marker)
                (Path(temporary) / name).chmod(0o755)
            self.fault(lambda: adaptor.verify(directory, executable=str(Path(temporary) / 'ffmpeg')), 'UNSUPPORTED_RUNTIME')
            marker.unlink()
            receipt = json.loads((directory / 'verification.json').read_text())
            receipt['executables'] = {'ffmpeg': str(Path(temporary) / 'ffmpeg'), 'ffprobe': str(Path(temporary) / 'ffprobe')}
            atomic_json(directory / 'verification.json', receipt)
            self.refused(directory)
            self.assertFalse(marker.exists())
        scratch = Path(tempfile.mkdtemp(prefix='schemaxis-publish-tmp-'))
        try:
            with mock.patch.object(tempfile, 'tempdir', str(scratch)):
                good = self.publish(self.source(1000, 1, 16000, seed=11))
                self.assertIs(adaptor.verify(good, executable=EXECUTABLE)['verified'], True)
                (good / 'stray.txt').write_text('x')
                self.refused(good)
            self.assertEqual(list(scratch.iterdir()), [], 'private verification directories must be removed')
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


@native
class ExtractAudioProvenanceTests(Case):
    """The earlier extractAudio route records the same receipt and applies the same sibling-ffprobe predicate to it."""
    VIDEO = FIXTURES / 'extract-audio-video.mp4'

    def run_extract(self, root, name):
        directory = Path(root) / name
        value = {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'speech', 'filter': 'extractAudio', 'options': {'file': str(self.VIDEO), 'streamIndex': 1}}]}
        adaptor.run(value, directory, executable=EXECUTABLE)
        return directory

    def rebind(self, directory):
        """Refresh every digest, binding and sidecar for the altered receipt while keeping the retained readbacks."""
        for stage in audio.STAGES:
            (directory / (stage + '-inputs.json')).write_text(json.dumps({str(directory / 'input-0000'): file_digest(directory / 'input-0000')}, sort_keys=True))
        receipt = json.loads((directory / 'verification.json').read_text())
        receipt['artifacts'] = audio.publications(directory)
        receipt['evidence'] = {name: file_digest(directory / name) for name in sorted(audio.evidence_names())}
        atomic_json(directory / 'verification.json', receipt)
        finalise(directory)

    def test_genuine_receipts_match_and_a_non_sibling_ffprobe_is_refused_without_running_it(self):
        with tempfile.TemporaryDirectory(prefix='schemaxis-extract-provenance-') as temporary:
            genuine = self.run_extract(temporary, 'genuine')
            executables = json.loads((genuine / 'verification.json').read_text())['executables']
            self.assertEqual(executables['ffprobe'], os.path.join(os.path.dirname(executables['ffmpeg']), 'ffprobe'))
            self.assertIs(adaptor.verify(genuine, executable=EXECUTABLE)['verified'], True)
            marker = Path(temporary) / 'ran'
            planted = Path(temporary) / 'ffprobe'
            planted.write_text('#!/bin/sh\necho planted > %s\n' % marker)
            planted.chmod(0o755)
            for label, change in (('ffprobe in another directory', {'ffprobe': str(planted)}),
                                  ('ffprobe under another name', {'ffprobe': executables['ffprobe'] + '2'}),
                                  ('ffmpeg in another directory', {'ffmpeg': str(Path(temporary) / 'ffmpeg')})):
                with self.subTest(label):
                    trial = self.run_extract(temporary, 'trial-' + label.replace(' ', '-'))
                    receipt = json.loads((trial / 'verification.json').read_text())
                    receipt['executables'].update(change)
                    atomic_json(trial / 'verification.json', receipt)
                    self.rebind(trial)
                    fault = self.fault(lambda: adaptor.verify(trial, executable=EXECUTABLE), 'VERIFICATION_FAILED')
                    self.assertIn('sibling', fault['message'])
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
