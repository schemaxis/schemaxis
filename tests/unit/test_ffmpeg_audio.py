"""extractAudio: AAC in MP4/M4A to a canonical PCM16 WAV, verified by a fresh native decode.

Host contracts always run. The native cases need a configured FFmpeg (stored configuration, SCHEMAXIS_CONFIG or
FFMPEG_EXECUTABLE) with ffprobe beside it and skip otherwise. Fixtures are deterministic generated PCM encoded by the real
native AAC encoder with an explicit ``-f mp4`` muxer; no speech or third-party recording is used. Forgeries rewrite the retained
digests, receipt and metadata so the retained evidence stays self-consistent: only the fresh decode of the held capture refuses them."""
import json
import math
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock
import wave

from schemaxis.adaptors.ffmpeg import adaptor, audio, review
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.configuration import executable as configured_executable
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation, execution_deadline
from schemaxis.errors import fail
from schemaxis.publication_metadata import finalise


def runtime():
    try:
        path = configured_executable('ffmpeg') or os.environ.get('FFMPEG_EXECUTABLE')
    except SchemaxisError:
        return None
    probe = os.path.join(os.path.dirname(path), 'ffprobe') if path else None
    return path if path and os.access(path, os.X_OK) and os.access(probe, os.X_OK) else None


EXECUTABLE = runtime()
native = unittest.skipUnless(EXECUTABLE, 'a configured FFmpeg with ffprobe beside it is required')


def document(source, index=0, **options):
    return {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'speech', 'filter': 'extractAudio',
        'options': {'file': str(source), 'streamIndex': index, **options}}]}


def box(kind, payload=b''):
    return struct.pack('>I4s', 8 + len(payload), kind) + payload


def ftyp(brand=b'isom'):
    return box(b'ftyp', brand + b'\0\0\2\0' + b'isomiso2')


def moov(*children):
    return box(b'moov', b''.join(children))


def dref(flags):
    entry = box(b'url ', struct.pack('>I', flags))
    return box(b'trak', box(b'mdia', box(b'minf', box(b'dinf', box(b'dref', struct.pack('>II', 0, 1) + entry)))))


def probe(streams, **extra):
    return {'streams': streams, 'format': {'nb_streams': len(streams), 'format_name': 'mov,mp4,m4a,3gp,3g2,mj2'}, 'chapters': [],
            'programs': [], **extra}


def aac(index=0, rate=16000, channels=1, **changes):
    return {'index': index, 'codec_type': 'audio', 'codec_name': 'aac', 'profile': 'LC', 'codec_tag_string': 'mp4a',
            'sample_rate': str(rate), 'channels': channels, 'time_base': '1/%d' % rate, 'start_pts': 0, 'nb_frames': '3', **changes}


def h264(index=0):
    return {'index': index, 'codec_type': 'video', 'codec_name': 'h264', 'disposition': {'attached_pic': 0}}


def listing(*samples, start=0):
    frames, position = [], start
    for count in samples:
        frames.append({'pts': position, 'nb_samples': count})
        position += count
    return {'frames': frames}


class Case(unittest.TestCase):
    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault.to_dict()


class HostTests(Case):
    def test_declaration_schema_and_plan_are_closed(self):
        declaration = adaptor.DECLARATIONS['extractAudio']
        self.assertEqual(sorted(declaration['options']), ['file', 'streamIndex', 'threads'])
        self.assertTrue(declaration['options']['streamIndex']['value']['required'])
        variant = [v for v in adaptor.schema()['properties']['nodes']['items']['oneOf'] if v['properties']['filter']['const'] == 'extractAudio'][0]
        self.assertEqual(variant['properties']['options']['required'], ['file', 'streamIndex'])
        prepared = adaptor.plan(document('/in/a.m4a', 3))
        self.assertEqual((prepared['output'], prepared['summary']), ('audio.wav', 'audio-summary.json'))
        self.assertEqual(prepared['nodes'][0]['options'], {'file': '/in/a.m4a', 'streamIndex': 3, 'threads': 1})
        self.assertIn('machine draft', ' '.join(prepared['losses']))
        for bad, code in ((document('/in/a.m4a', 16), 'INVALID_ARGUMENT'), (document('/in/a.m4a', -1), 'INVALID_ARGUMENT'),
                          (document('/in/a.m4a', True), 'INVALID_ARGUMENT'), (document('relative.m4a'), 'INVALID_RESOURCE'),
                          (document('/in/a.wav'), 'UNSUPPORTED_AUDIO'), (document('/in/a\0.m4a'), 'INVALID_RESOURCE')):
            self.fault(lambda bad=bad: adaptor.plan(bad), code)
        missing = document('/in/a.m4a'); del missing['nodes'][0]['options']['streamIndex']
        self.fault(lambda: adaptor.plan(missing), 'MISSING_ARGUMENT')
        unknown = document('/in/a.m4a', codec='aac')
        self.fault(lambda: adaptor.plan(unknown), 'UNKNOWN_ARGUMENT')
        extra = document('/in/a.m4a'); extra['deliverable'] = {'frames': 1}
        self.fault(lambda: adaptor.plan(extra), 'INVALID_ARGUMENT')

    def test_existing_operations_keep_their_options(self):
        for name, options in (('encodeFrames', ['codec', 'files', 'fps', 'threads']), ('muxReview', ['audio', 'captionStatus', 'captions', 'threads', 'video'])):
            self.assertEqual(sorted(adaptor.DECLARATIONS[name]['options']), options)

    def test_recipe_is_forced_local_fixed_and_unbounded_by_nothing(self):
        recipe = audio.commands('/tools/ffmpeg', Path('/run'), {'streamIndex': 2, 'threads': 3})
        for stage in audio.STAGES:
            command = recipe[stage]
            self.assertEqual(command[-1].rsplit('/', 1)[0], '/run')
            joined = ' '.join(command)
            for fixed in ('-protocol_whitelist file -f mov', '-enable_drefs 0 -use_absolute_path 0'):
                self.assertIn(fixed, joined if stage != 'decode' else joined.replace('-i /run/input-0000', ''))
        self.assertEqual(recipe['source-probe'][0], '/tools/ffprobe')
        self.assertIn('-select_streams 2', ' '.join(recipe['source-frames']))
        self.assertIn('%%+#%d' % audio.MAX_PACKETS, ' '.join(recipe['source-frames']).replace('%+#', '%%+#'))
        decode = recipe['decode']
        self.assertIn('0:2', decode)
        self.assertIn('pcm_s16le', decode)
        self.assertEqual(decode[decode.index('-threads') + 1], '3')
        for forbidden in ('-fs', '-t', '-ss', '-ar', '-ac', '-af', '-filter_complex', '-frames:a'):
            self.assertNotIn(forbidden, decode, forbidden + ' would trim, resample, mix or truncate silently')

    def test_launcher_binds_the_input_and_caps_the_child(self):
        text = audio.launcher(Path('/run'), 'decode', ['/tools/ffmpeg'], 1234)
        for needle in ('RLIMIT_AS', 'RLIMIT_FSIZE, (1234,)', 'RLIMIT_CPU', 'RLIMIT_CORE', 'S_ISREG', 'is_symlink', 'decode-inputs.json', 'execvpe'):
            self.assertIn(needle, text)
        self.assertEqual(audio.limit_for('decode', {'frames': 10, 'channels': 2}), 40 + audio.OUTPUT_SLACK)

    def test_probe_file_size_cap_is_the_host_reader_cap_plus_one_byte(self):
        # One byte over MAX_PROBE: output of exactly MAX_PROBE bytes completes, and a file that reaches the cap is over budget.
        for stage in ('source-probe', 'source-frames'):
            self.assertEqual(audio.limit_for(stage), audio.MAX_PROBE + 1)
            self.assertIn('RLIMIT_FSIZE, (%d,)' % (audio.MAX_PROBE + 1), audio.launcher(Path('/run'), stage, ['/tools/ffprobe'], audio.limit_for(stage)))

    def test_canonical_wav_is_44_bytes_of_header(self):
        wav = audio.canonical_wav(16000, 2, b'\1\0\2\0\3\0\4\0')
        self.assertEqual(len(wav), 44 + 8)
        parsed = review.parse_wav(wav)
        self.assertEqual((parsed['channels'], parsed['sampleRate'], parsed['samples']), (2, 16000, 2))
        self.assertEqual(audio.peaks(b'\1\0\2\0\3\0\4\0', 2), ([1, 2], [3, 4]))

    def test_mp4_structure_is_checked_before_any_native_process(self):
        good = ftyp() + moov(dref(1)) + box(b'mdat', b'x' * 16)
        self.assertEqual(audio.check_structure(good)['brand'], 'isom')
        cases = [(b'', 'INVALID_RESOURCE'), (b'RIFF' + b'\0' * 40, 'INVALID_RESOURCE'),
                 (good[:-5], 'INVALID_RESOURCE'), (ftyp() + moov() , 'INVALID_RESOURCE'),
                 (ftyp(b'qt  ') + moov() + box(b'mdat'), 'UNSUPPORTED_AUDIO'),
                 (ftyp() + moov() + moov() + box(b'mdat'), 'INVALID_RESOURCE'),
                 (ftyp() + moov() + box(b'moof') + box(b'mdat'), 'UNSUPPORTED_AUDIO'),
                 (ftyp() + moov(dref(0)) + box(b'mdat'), 'UNSUPPORTED_AUDIO'),
                 (box(b'moov') + ftyp() + box(b'mdat'), 'INVALID_RESOURCE'),
                 (ftyp() + struct.pack('>I4s', 4, b'free'), 'INVALID_RESOURCE')]
        for data, code in cases:
            self.fault(lambda data=data: audio.check_structure(data), code)

    def test_stream_set_and_timeline_are_validated_before_decode(self):
        facts = audio.inspect(probe([aac()]), listing(1024, 1024, 57), 0)
        self.assertEqual((facts['sampleRate'], facts['channels'], facts['frames']), (16000, 1, 2105))
        facts = audio.inspect(probe([h264(0), aac(1, 44100, 2)]), listing(1024, 3), 1)
        self.assertEqual((facts['channels'], facts['frames'], [s['type'] for s in facts['streams']]), (2, 1027, ['video', 'audio']))
        edge = audio.inspect(probe([aac(rate=32000, nb_frames=str(audio.MAX_PACKETS))]), listing(*[960] * 17476), 0)
        self.assertEqual(edge['frames'], 960 * 17476, 'a full mono 32 MiB stream of 960-sample AAC-LC frames fits the probe bounds')
        refused = [
            (probe([aac()]), listing(1024), 1, 'INVALID_ARGUMENT'),
            (probe([h264(0), aac(1)]), listing(1024), 0, 'INVALID_ARGUMENT'),
            (probe([aac(0), aac(1)]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac(0), {'index': 1, 'codec_type': 'subtitle', 'codec_name': 'mov_text'}]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac(0), {'index': 1, 'codec_type': 'data', 'codec_name': 'bin_data'}]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac(0), {**h264(1), 'disposition': {'attached_pic': 1}}]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac(profile='HE-AAC')]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac(profile='LC', codec_name='mp3')]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac(channels=6)]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac(rate=7350)]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac(rate=192000)]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac(start_pts=1024)]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac(time_base='1/90000')]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac()], chapters=[{'id': 1}]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac()]), {'frames': []}, 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac()]), listing(1024, start=1), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac()]), {'frames': [{'pts': 0, 'nb_samples': 1024}, {'pts': 2048, 'nb_samples': 1024}]}, 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac()]), {'frames': [{'pts': 0, 'nb_samples': '1024'}]}, 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac()]), {'frames': [{'pts': 0, 'nb_samples': 0}]}, 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac()]), listing(*[1024] * (audio.MAX_FRAMES + 1)), 0, 'RESOURCE_LIMIT'),
            (probe([aac(rate=8000)]), listing(*[1024] * 4700), 0, 'RESOURCE_LIMIT'),
            (probe([aac(rate=96000, channels=2)]), listing(*[1024] * 8200), 0, 'RESOURCE_LIMIT'),
            (probe([aac(nb_frames=str(audio.MAX_PACKETS + 1))]), listing(1024), 0, 'RESOURCE_LIMIT'),
            (probe([aac(nb_frames='many')]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac(nb_frames=None)]), listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            (probe([aac(rate=32000)]), listing(*[960] * 17477), 0, 'RESOURCE_LIMIT'),
            ({'streams': [], 'format': {'nb_streams': 0, 'format_name': 'mov,mp4'}}, listing(1024), 0, 'UNSUPPORTED_AUDIO'),
            ({**probe([aac()]), 'format': {'nb_streams': 1, 'format_name': 'matroska,webm'}}, listing(1024), 0, 'UNSUPPORTED_AUDIO'),
        ]
        for value, frames, index, code in refused:
            self.fault(lambda value=value, frames=frames, index=index: audio.inspect(value, frames, index), code)

    def test_limits_are_those_of_the_downstream_audio_adaptors(self):
        self.assertEqual((audio.MAX_SECONDS, audio.MAX_WAV, audio.MAX_SOURCE), (600, 32 << 20, 64 << 20))
        self.assertGreaterEqual(audio.MAX_FRAMES * 1024, audio.MAX_PCM // 2)
        # The smallest AAC-LC frame is 960 samples: the listing bound must cover every 960-sample mono stream a 32 MiB WAV holds,
        # and the packet bound must leave room for packets the edit list trims to no frame.
        self.assertGreaterEqual(audio.MAX_FRAMES * 960, audio.MAX_PCM // 2)
        self.assertGreater(audio.MAX_PACKETS, audio.MAX_FRAMES)

    def test_missing_runtime_is_refused_without_path_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            empty = Path(temporary) / 'empty.json'
            atomic_json(empty, {'version': 1, 'locations': {}})
            source = Path(temporary) / 'a.m4a'
            source.write_bytes(ftyp())
            planted = Path(temporary) / 'bin'
            planted.mkdir()
            for name in ('ffmpeg', 'ffprobe'):
                (planted / name).write_text('#!/bin/sh\necho planted > %s/ran\n' % temporary)
                (planted / name).chmod(0o755)
            with mock.patch.dict(os.environ, {'SCHEMAXIS_CONFIG': str(empty), 'PATH': str(planted)}):
                os.environ.pop('FFMPEG_EXECUTABLE', None)
                fault = self.fault(lambda: adaptor.run(document(source), Path(temporary) / 'out'), 'INTERPRETER_NOT_FOUND')
                self.assertIn('extractAudio', fault['message'])
                self.assertIn('PATH are never used', fault['recovery'])
                self.assertFalse((Path(temporary) / 'ran').exists())
                self.assertFalse((Path(temporary) / 'out').exists(), 'no run directory before a trusted runtime is known')
                self.fault(lambda: audio.trusted('ffmpeg'), 'INTERPRETER_NOT_FOUND')

    def test_reusable_inputs_hash_the_captured_compressed_bytes_and_refuse_bad_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'a.m4a'
            path.write_bytes(ftyp() + moov() + box(b'mdat', b'abc'))
            self.assertEqual(list(adaptor.reusableInputs(document(path))), [str(path)])
            path.write_bytes(b'not an mp4 file')
            self.fault(lambda: adaptor.reusableInputs(document(path)), 'INVALID_RESOURCE')
            folder = Path(temporary) / 'folder.m4a'
            folder.mkdir()
            self.fault(lambda: adaptor.reusableInputs(document(folder)), 'INVALID_RESOURCE')
            fifo = Path(temporary) / 'pipe.m4a'
            os.mkfifo(fifo)
            self.fault(lambda: adaptor.reusableInputs(document(fifo)), 'INVALID_RESOURCE')
            with mock.patch.object(audio, 'MAX_SOURCE', 8):
                path.write_bytes(ftyp() + moov() + box(b'mdat', b'abc'))
                self.fault(lambda: audio.read_source(path), 'RESOURCE_LIMIT')

    def test_resources_follow_the_authored_threads(self):
        self.assertEqual(adaptor.resources(document('/in/a.m4a', threads=2), {}, 'speech'), {'threads': 2})


class LaunchTests(Case):
    """Fault classification of one native stage with the runner replaced: only the stage logs and exit status are staged."""
    LOADER = 'ffprobe: error while loading shared libraries: libavcodec.so.62: cannot open shared object file: No such file or directory'
    DEMUX = '[mov,mp4,m4a,3gp,3g2,mj2 @ 0x55d5a8d1c0] moov atom not found\n<run>/input-0000: Invalid data found when processing input'

    @staticmethod
    def staged(exit_code=0, stderr='', stdout=b'{}', decoded=None):
        """Write the logs as ``native_command.execute`` does; a nonzero exit raises RUNNER_FAILED before any diagnostics are read."""
        def execute(command, directory, stage, timeout, environment=None):
            directory = Path(directory)
            (directory / (stage + '.stdout')).write_bytes(stdout)
            (directory / (stage + '.stderr')).write_text(stderr.replace('<run>', str(directory)))
            if decoded is not None:
                (directory / 'decoded.wav').write_bytes(decoded)
            if exit_code:
                fail('RUNNER_FAILED', 'native execution did not complete', str(directory), exitCode=exit_code, stdout='', stderr=stderr[-4000:])
        return execute

    def launched(self, execute, stage='source-probe', verifying=False, limit=None):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(audio, 'execute', execute):
            limit = audio.limit_for(stage, {'frames': 100, 'channels': 1}) if limit is None else limit
            return audio.launch(Path(temporary), stage, ['/tools/ffprobe'], limit, None, verifying)

    def refused(self, code, verifying=False, stage='source-probe', limit=None, **staged):
        fault = self.fault(lambda: self.launched(self.staged(**staged), stage, verifying, limit), code)
        return fault

    def test_nonzero_loader_allocation_and_unclassified_failures_are_not_source_faults(self):
        for label, text in (('loader', self.LOADER), ('allocation', 'ffprobe: Cannot allocate memory'),
                            ('native-looking allocation', '[aac @ 0x5581] Failed to allocate memory'),
                            ('unclassified', 'ffprobe: unexpected helper output')):
            for stage in audio.STAGES:
                with self.subTest(label, stage=stage):
                    fault = self.refused('RUNNER_FAILED', stage=stage, exit_code=127, stderr=text)
                    self.assertIn('source validity was not established', fault['recovery'])
                    self.assertEqual(fault['observed']['stage'], stage)
                    self.assertEqual(fault['location'], audio.LOCATION + 'file')

    def test_nonzero_native_source_diagnostics_are_input_faults(self):
        for stage in audio.STAGES:
            with self.subTest(stage):
                fault = self.refused('INVALID_RESOURCE', stage=stage, exit_code=1, stderr=self.DEMUX)
                self.assertEqual(fault['location'], audio.LOCATION + 'file')
                self.assertIn('moov atom not found', fault['observed']['diagnostics'])
                self.assertIn('<run>/input-0000', fault['observed']['diagnostics'])

    def test_nonzero_exit_without_diagnostics_keeps_the_original_runner_fault(self):
        for text in ('', ' \n'):
            with self.subTest(repr(text)):
                fault = self.refused('RUNNER_FAILED', exit_code=1, stderr=text)
                self.assertEqual((fault['message'], fault['observed']['exitCode']), ('native execution did not complete', 1))

    def test_zero_exit_diagnostics_keep_their_classification(self):
        self.refused('INVALID_RESOURCE', stderr=self.DEMUX)
        self.refused('RUNNER_FAILED', stderr=self.LOADER)
        self.assertIsNone(self.launched(self.staged()))

    def test_zero_exit_that_produced_nothing_established_nothing_about_the_source(self):
        fault = self.refused('RUNNER_FAILED', stdout=b'')
        self.assertIn('source validity was not established', fault['recovery'])
        self.refused('RUNNER_FAILED', stage='source-frames', stdout=b'')
        self.refused('RUNNER_FAILED', stage='decode', decoded=b'')
        self.assertIsNone(self.launched(self.staged(decoded=b'RIFF'), stage='decode'))
        self.refused('VERIFICATION_FAILED', verifying=True, stdout=b'')

    def test_timeouts_cancellation_and_unavailable_runtimes_keep_their_own_codes(self):
        for code in ('RUNNER_TIMED_OUT', 'RUNNER_CANCELLED', 'UNSUPPORTED_RUNTIME', 'INTERPRETER_UNUSABLE'):
            for verifying in (False, True):
                def execute(command, directory, stage, timeout, environment=None, code=code):
                    fail(code, 'stage stopped', stage)
                with self.subTest(code, verifying=verifying):
                    self.fault(lambda: self.launched(execute, verifying=verifying), code)

    def test_fresh_verification_turns_every_stage_failure_into_a_verification_failure_with_its_cause(self):
        for cause, kwargs in (('RUNNER_FAILED', dict(exit_code=127, stderr=self.LOADER)), ('INVALID_RESOURCE', dict(exit_code=1, stderr=self.DEMUX)),
                              ('RUNNER_FAILED', dict(exit_code=1)), ('RESOURCE_LIMIT', dict(exit_code=-signal.SIGXFSZ))):
            with self.subTest(cause, **kwargs):
                fault = self.refused('VERIFICATION_FAILED', verifying=True, **kwargs)
                self.assertEqual(fault['observed']['cause']['code'], cause)
                self.assertEqual(fault['location'], 'source-probe')

    def test_probe_output_over_the_cap_is_a_resource_limit_whatever_the_stderr_says(self):
        over = b'x' * (audio.MAX_PROBE + 1)
        for label, kwargs in (('killed by the file-size signal', dict(exit_code=-signal.SIGXFSZ, stdout=over)),
                              ('signal without a visible file', dict(exit_code=-signal.SIGXFSZ, stdout=b'')),
                              ('source-looking stderr', dict(exit_code=-signal.SIGXFSZ, stdout=over, stderr=self.DEMUX)),
                              ('loader-looking stderr', dict(exit_code=-signal.SIGXFSZ, stdout=over, stderr=self.LOADER)),
                              ('write cut at the cap, exit zero', dict(stdout=over))):
            for stage in ('source-probe', 'source-frames'):
                with self.subTest(label, stage=stage):
                    fault = self.refused('RESOURCE_LIMIT', stage=stage, **kwargs)
                    self.assertEqual((fault['location'], fault['observed']['stage']), (audio.LOCATION + 'file', stage))
                    self.assertIn('not evidence that the source is invalid', fault['recovery'])

    def test_probe_output_of_exactly_the_budget_is_still_accepted(self):
        self.assertIsNone(self.launched(self.staged(stdout=b'x' * audio.MAX_PROBE)))

    def test_decode_that_reaches_the_counted_size_cap_is_a_resource_limit_not_a_source_fault(self):
        limit = audio.limit_for('decode', {'frames': 100, 'channels': 1})
        fault = self.refused('RESOURCE_LIMIT', stage='decode', limit=limit, exit_code=-signal.SIGXFSZ, decoded=b'\0' * limit, stderr=self.DEMUX)
        self.assertIn('counted', fault['message'])
        self.refused('RESOURCE_LIMIT', stage='decode', limit=limit, exit_code=1, decoded=b'\0' * limit, stderr=self.DEMUX)

    def test_cap_hits_are_verification_failures_while_verifying(self):
        fault = self.refused('VERIFICATION_FAILED', verifying=True, exit_code=-signal.SIGXFSZ, stdout=b'x' * (audio.MAX_PROBE + 1))
        self.assertEqual(fault['observed']['cause']['code'], 'RESOURCE_LIMIT')


@native
class NativeTests(Case):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='schemaxis-audio-test-'))
        cls.counter = 0
        cls.clips = {}
        for name, frames, channels, rate, with_video in (('mono-odd', 12345, 1, 8000, False), ('stereo-odd', 30001, 2, 44100, False),
                                                         ('av', 33333, 1, 22050, True), ('one', 1, 1, 16000, False)):
            cls.clips[name] = cls.encode(name, frames, channels, rate, with_video)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    @classmethod
    def native(cls, args):
        completed = subprocess.run(args, capture_output=True, timeout=60)
        if completed.returncode:
            raise AssertionError(completed.stderr[-300:])

    @classmethod
    def encode(cls, name, frames, channels, rate, with_video=False, extra_audio=False, suffix='.mp4', seed=0):
        pcm = bytearray()
        for i in range(frames):
            for c in range(channels):
                pcm += struct.pack('<h', int(9000 * math.sin(2 * math.pi * (200 + seed * 40 + 90 * c) * i / rate) * (0.4 + 0.6 * math.sin(i / 811 + seed))))
        wav = cls.root / (name + '.wav')
        with wave.open(str(wav), 'wb') as handle:
            handle.setnchannels(channels); handle.setsampwidth(2); handle.setframerate(rate); handle.writeframes(bytes(pcm))
        out = cls.root / (name + suffix)
        command = [EXECUTABLE, '-nostdin', '-v', 'error', '-f', 'wav', '-i', str(wav)]
        if with_video:
            raw = cls.root / (name + '.rgb')
            raw.write_bytes(bytes((x * 7 + y * 3 + f * 11) & 255 for f in range(25) for y in range(16) for x in range(16) for _ in range(3)))
            command += ['-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', '16x16', '-framerate', '25', '-i', str(raw),
                        '-map', '1:v:0', '-map', '0:a:0', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-shortest']
        elif extra_audio:
            command += ['-f', 'wav', '-i', str(wav), '-map', '0:a:0', '-map', '1:a:0']
        else:
            command += ['-map', '0:a:0', '-vn']
        cls.native(command + ['-c:a', 'aac', '-b:a', '64k', '-threads', '1', '-f', 'mp4', str(out)])
        return out, frames

    @classmethod
    def run_document(cls, value):
        cls.counter += 1
        directory = cls.root / f'run-{cls.counter}'
        adaptor.run(value, directory, executable=EXECUTABLE)
        return directory

    def independent_count(self, source, index):
        """Decoded PCM frames from a second, separate native decode parsed by ``wave``; the ``-shortest`` video mux trims the audio."""
        target = self.root / ('independent-%s-%d.wav' % (source.stem, index))
        self.native([EXECUTABLE, '-nostdin', '-v', 'error', '-y', '-i', str(source), '-map', '0:%d' % index, '-c:a', 'pcm_s16le', str(target)])
        with wave.open(str(target), 'rb') as handle:
            return handle.getnframes()

    def test_shipped_audio_plus_video_fixture_decodes_the_literal_expected_frame_count(self):
        fixture = Path(__file__).resolve().parents[2] / 'examples' / 'schemaxis' / 'fixtures' / 'ffmpeg' / 'extract-audio-video.mp4'
        directory = self.run_document(document(fixture, 1))
        summary = json.loads((directory / 'audio-summary.json').read_text())
        self.assertEqual((summary['audio']['frames'], summary['audio']['sampleRate'], summary['audio']['channels']), (24000, 16000, 1))
        self.assertEqual(review.parse_wav((directory / 'audio.wav').read_bytes())['samples'], 24000)
        self.assertEqual(self.independent_count(fixture, 1), 24000)

    def good(self, name='mono-odd', index=0):
        return self.run_document(document(self.clips[name][0], index))

    def refused_fresh(self, directory):
        fault = self.fault(lambda: adaptor.verify(directory, executable=EXECUTABLE), 'VERIFICATION_FAILED')
        self.assertIs(fault['observed'].get('fresh'), True, fault)
        return fault

    def rebind(self, directory, published=None, capture=None):
        """Rewrite the retained digests, receipt and sidecars for altered bytes while keeping every retained readback."""
        directory = Path(directory)
        if published is not None:
            (directory / 'audio.wav').write_bytes(published)
        if capture is not None:
            (directory / 'input-0000').write_bytes(capture)
        for stage in audio.STAGES:
            (directory / (stage + '-inputs.json')).write_text(json.dumps({str(directory / 'input-0000'): file_digest(directory / 'input-0000')}, sort_keys=True))
        receipt = json.loads((directory / 'verification.json').read_text())
        receipt['artifacts'] = audio.publications(directory)
        receipt['evidence'] = {name: file_digest(directory / name) for name in sorted(audio.evidence_names())}
        atomic_json(directory / 'verification.json', receipt)
        finalise(directory)

    def test_good_runs_publish_a_canonical_wav_with_the_probed_frame_count(self):
        for name, index in (('mono-odd', 0), ('stereo-odd', 0), ('av', 1), ('one', 0)):
            with self.subTest(name):
                directory = self.good(name, index)
                frames = self.clips[name][1]
                summary = json.loads((directory / 'audio-summary.json').read_text())
                wav = review.parse_wav((directory / 'audio.wav').read_bytes())
                self.assertEqual(summary['audio']['frames'], wav['samples'])
                self.assertEqual(wav['samples'], frames if name != 'av' else self.independent_count(self.clips[name][0], index))
                self.assertEqual(len((directory / 'audio.wav').read_bytes()), 44 + wav['samples'] * wav['channels'] * 2)
                self.assertIs(summary['equalityToOriginalClaimed'], False)
                self.assertEqual((summary['status'], summary['capturedAudio']['codec'], summary['capturedAudio']['streamIndex']), ('machineDraft', 'aac', index))
                answer = adaptor.verify(directory, executable=EXECUTABLE)
                self.assertIs(answer['freshNativeVerification'], True)
                self.assertEqual(answer['audio']['frames'], wav['samples'])
                self.assertEqual(json.loads((directory / 'result.json').read_text())['sampleRate'], summary['audio']['sampleRate'])

    def tagged(self, name, size):
        """The ``av``-free mono clip with one very large ``udta`` text tag added to its moov box (the media is unchanged)."""
        data = self.clips['mono-odd'][0].read_bytes()
        pieces, position = [], 0
        while position < len(data):
            length, kind = struct.unpack('>I4s', data[position:position + 8])
            pieces.append((kind, data[position:position + length]))
            position += length
        item = box(b'\xa9lyr', box(b'data', struct.pack('>II', 1, 0) + b'a' * size))
        udta = box(b'udta', box(b'meta', struct.pack('>I', 0) + box(b'hdlr', b'\0' * 8 + b'mdir' + b'\0' * 13) + box(b'ilst', item)))
        out = b''
        for kind, piece in pieces:
            out += struct.pack('>I', len(piece) + len(udta)) + piece[4:] + udta if kind == b'moov' else piece
        path = self.root / (name + '.m4a')
        path.write_bytes(out)
        return path

    def test_a_large_but_budgeted_metadata_tag_is_still_extracted_and_verified(self):
        directory = self.run_document(document(self.tagged('tag-3m', 3 * 1024 * 1024)))
        self.assertEqual(json.loads((directory / 'audio-summary.json').read_text())['audio']['frames'], 12345)
        self.assertGreater((directory / 'source-probe.stdout').stat().st_size, 3 * 1024 * 1024)
        self.assertLessEqual((directory / 'source-probe.stdout').stat().st_size, audio.MAX_PROBE)
        self.assertIs(adaptor.verify(directory, executable=EXECUTABLE)['verified'], True)

    def test_metadata_beyond_the_probe_budget_is_a_resource_limit_never_a_source_fault_or_truncation(self):
        for label, size in (('over-budget', 5 * 1024 * 1024), ('over-twice-budget', 9 * 1024 * 1024)):
            with self.subTest(label):
                directory = self.root / ('run-' + label)
                fault = self.fault(lambda: adaptor.run(document(self.tagged(label, size)), directory, executable=EXECUTABLE), 'RESOURCE_LIMIT')
                self.assertEqual((fault['observed']['stage'], fault['location']), ('source-probe', audio.LOCATION + 'file'))
                self.assertIn('not evidence that the source is invalid', fault['recovery'])
                self.assertFalse((directory / 'audio.wav').exists())
                self.assertEqual(json.loads((directory / 'result.json').read_text())['fault']['code'], 'RESOURCE_LIMIT')
                self.assertEqual((directory / 'source-probe.stdout').stat().st_size, audio.MAX_PROBE + 1, 'the cap, not a silent truncation, ended the probe')

    def test_a_decode_larger_than_the_counted_frames_is_refused_not_truncated(self):
        small = lambda stage, facts=None: 1000 if stage == 'decode' else audio.MAX_PROBE + 1
        with mock.patch.object(audio, 'limit_for', small):
            directory = self.root / 'run-small-decode'
            fault = self.fault(lambda: adaptor.run(document(self.clips['mono-odd'][0]), directory, executable=EXECUTABLE), 'RESOURCE_LIMIT')
        self.assertEqual(fault['observed']['stage'], 'decode')
        self.assertFalse((directory / 'audio.wav').exists())

    def test_a_runtime_whose_probe_cannot_load_is_not_blamed_on_the_valid_source(self):
        bin_dir = self.root / 'broken-probe'
        bin_dir.mkdir()
        (bin_dir / 'ffmpeg').write_text('#!/bin/sh\nexec %s "$@"\n' % EXECUTABLE)
        (bin_dir / 'ffprobe').write_text('#!/bin/sh\necho "ffprobe: error while loading shared libraries: libavcodec.so.62: cannot open shared object file" >&2\nexit 127\n')
        for name in ('ffmpeg', 'ffprobe'):
            (bin_dir / name).chmod(0o755)
        directory = self.root / 'run-broken-probe'
        fault = self.fault(lambda: adaptor.run(document(self.clips['mono-odd'][0]), directory, executable=str(bin_dir / 'ffmpeg')), 'RUNNER_FAILED')
        self.assertIn('source validity was not established', fault['recovery'])
        self.assertIn('shared libraries', fault['observed']['diagnostics'])
        self.assertFalse((directory / 'audio.wav').exists())

    def test_priming_and_padding_are_counted_not_assumed(self):
        directory = self.good('mono-odd')
        probed = json.loads((directory / 'source-probe.stdout').read_text())['streams'][0]
        packets = int(probed['nb_frames'])
        frames = json.loads((directory / 'audio-summary.json').read_text())['audio']['frames']
        self.assertEqual(frames, 12345)
        self.assertNotEqual(packets * 1024, frames, 'packet count times 1024 is not the decoded count')

    def test_stream_selection_errors_name_the_audio_stream(self):
        fault = self.fault(lambda: adaptor.run(document(self.clips['av'][0], 0), self.root / 'wrong-index', executable=EXECUTABLE), 'INVALID_ARGUMENT')
        self.assertEqual(fault['observed']['audioIndex'], [1])
        self.fault(lambda: adaptor.run(document(self.clips['mono-odd'][0], 5), self.root / 'absent-index', executable=EXECUTABLE), 'INVALID_ARGUMENT')
        self.assertEqual(json.loads((self.root / 'wrong-index' / 'result.json').read_text())['status'], 'failed')
        self.assertFalse((self.root / 'wrong-index' / 'audio.wav').exists())

    def test_extra_audio_streams_are_refused_rather_than_selected(self):
        two = self.encode('two-audio', 4000, 1, 16000, extra_audio=True)[0]
        fault = self.fault(lambda: adaptor.run(document(two, 0), self.root / 'two-audio-run', executable=EXECUTABLE), 'UNSUPPORTED_AUDIO')
        self.assertIn('extra audio', fault['message'])

    def test_damaged_and_truncated_sources_never_reach_the_decoder_as_partial_audio(self):
        data = self.clips['stereo-odd'][0].read_bytes()
        for label, damaged, code in (('truncated', data[:len(data) // 2], 'INVALID_RESOURCE'), ('prefix', b'\0' * 64 + data, 'INVALID_RESOURCE'),
                                     ('empty', b'', 'INVALID_RESOURCE')):
            with self.subTest(label):
                path = self.root / (label + '.m4a')
                path.write_bytes(damaged)
                self.fault(lambda path=path: adaptor.run(document(path), self.root / ('run-' + label), executable=EXECUTABLE), code)
        # A damaged payload inside an intact box structure is the decoder's to reject; nothing partial is published.
        corrupt = bytearray(data)
        mdat = bytes(corrupt).find(b'mdat') + 4
        corrupt[mdat + 200:mdat + 1200] = os.urandom(1000)
        path = self.root / 'corrupt.m4a'
        path.write_bytes(bytes(corrupt))
        try:
            adaptor.run(document(path), self.root / 'run-corrupt', executable=EXECUTABLE)
        except SchemaxisError:
            self.assertFalse((self.root / 'run-corrupt' / 'audio.wav').exists())
        else:
            summary = json.loads((self.root / 'run-corrupt' / 'audio-summary.json').read_text())
            self.assertEqual(summary['audio']['frames'], 30001, 'a run that succeeds must have decoded every probed frame')

    def test_forged_publication_with_rewritten_evidence_is_refused_by_the_fresh_decode(self):
        directory = self.good('stereo-odd')
        wav = bytearray((directory / 'audio.wav').read_bytes())
        for offset in (44, 44 + 4000, len(wav) - 1):
            forged = self.good('stereo-odd')
            changed = bytearray(wav)
            changed[offset] ^= 1
            self.rebind(forged, bytes(changed))
            summary = json.loads((forged / 'audio-summary.json').read_text())
            summary['wav']['sha256'] = __import__('hashlib').sha256(bytes(changed)).hexdigest()
            atomic_json(forged / 'audio-summary.json', summary)
            self.rebind(forged)
            fault = self.refused_fresh(forged)
            self.assertEqual(fault['location'], 'audio.wav')
        shorter = self.good('stereo-odd')
        self.rebind(shorter, audio.canonical_wav(44100, 2, bytes(wav[44:-4])))
        self.refused_fresh(shorter)

    def test_swapped_capture_is_refused_and_a_coherent_rewrite_is_not_authenticated(self):
        directory = self.good('mono-odd')
        other, _ = self.encode('other', 12345, 1, 8000, seed=3)
        saved = (directory / 'input-0000').read_bytes()
        (directory / 'input-0000').write_bytes(other.read_bytes())
        self.fault(lambda: adaptor.verify(directory, executable=EXECUTABLE), 'VERIFICATION_FAILED')
        (directory / 'input-0000').write_bytes(saved)
        self.assertIs(adaptor.verify(directory, executable=EXECUTABLE)['verified'], True)
        # Documented limit: replacing the capture AND the published audio coherently describes a different but valid recording.
        forged = self.run_document(document(other, 0))
        self.assertIs(adaptor.verify(forged, executable=EXECUTABLE)['verified'], True)

    def test_retained_evidence_is_strict_typed_and_closed(self):
        directory = self.good('mono-odd')
        for name, change in (('result.json', lambda v: v.update(extra=True)), ('result.json', lambda v: v.update(frames=float(v['frames']))),
                             ('result.json', lambda v: v.update(lossy=1)), ('verification.json', lambda v: v.update(extra=1)),
                             ('captures.json', lambda v: v.update(bytes=v['bytes'] + 1)),
                             ('audio-summary.json', lambda v: v['audio'].update(frames=v['audio']['frames'] + 1))):
            path = directory / name
            saved = path.read_bytes()
            value = json.loads(saved)
            change(value)
            atomic_json(path, value)
            try:
                self.fault(lambda: adaptor.verify(directory, executable=EXECUTABLE), 'VERIFICATION_FAILED')
            finally:
                path.write_bytes(saved)
        path = directory / 'result.json'
        saved = path.read_bytes()
        path.write_text(saved.decode().replace('"status": "succeeded"', '"status": "succeeded", "status": "failed"'))
        try:
            self.fault(lambda: adaptor.verify(directory, executable=EXECUTABLE), 'VERIFICATION_FAILED')
        finally:
            path.write_bytes(saved)
        (directory / 'stray.txt').write_text('x')
        self.fault(lambda: adaptor.verify(directory, executable=EXECUTABLE), 'VERIFICATION_FAILED')
        (directory / 'stray.txt').unlink()
        self.assertIs(adaptor.verify(directory, executable=EXECUTABLE)['verified'], True)

    def test_planted_runtime_and_receipt_paths_never_decide(self):
        directory = self.good('mono-odd')
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'ran'
            for name in ('ffmpeg', 'ffprobe'):
                (Path(temporary) / name).write_text(f'#!/bin/sh\necho planted > {marker}\necho "not ffmpeg"\n')
                (Path(temporary) / name).chmod(0o755)
            self.fault(lambda: adaptor.verify(directory, executable=str(Path(temporary) / 'ffmpeg')), 'UNSUPPORTED_RUNTIME')
            receipt = json.loads((directory / 'verification.json').read_text())
            marker.unlink()
            receipt['executables'] = {'ffmpeg': str(Path(temporary) / 'ffmpeg'), 'ffprobe': str(Path(temporary) / 'ffprobe')}
            atomic_json(directory / 'verification.json', receipt)
            self.fault(lambda: adaptor.verify(directory, executable=EXECUTABLE), 'VERIFICATION_FAILED')
            self.assertFalse(marker.exists())

    def test_deadline_cancellation_and_cleanup(self):
        directory = self.good('mono-odd')
        scratch = Path(tempfile.mkdtemp(prefix='schemaxis-audio-tmp-'))
        try:
            with mock.patch.object(tempfile, 'tempdir', str(scratch)):
                with execution_deadline(1e-9):
                    time.sleep(0.01)
                    self.fault(lambda: adaptor.verify(directory, executable=EXECUTABLE), 'RUNNER_TIMED_OUT')
                cancel = threading.Event(); cancel.set()
                with allocation({}, cancel):
                    self.fault(lambda: adaptor.verify(directory, executable=EXECUTABLE), 'RUNNER_CANCELLED')
                    self.fault(lambda: adaptor.run(document(self.clips['mono-odd'][0]), self.root / 'cancelled', executable=EXECUTABLE), 'RUNNER_CANCELLED')
                self.fault(lambda: adaptor.run(document(self.clips['mono-odd'][0]), self.root / 'timed-out', executable=EXECUTABLE, timeout=1e-6), 'RUNNER_TIMED_OUT')
            self.assertEqual(list(scratch.iterdir()), [], 'private verification directories must be removed')
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        self.assertFalse((self.root / 'cancelled' / 'audio.wav').exists())

    def test_output_size_and_duration_bounds_apply_before_publication(self):
        with mock.patch.object(audio, 'MAX_PCM', 1000):
            fault = self.fault(lambda: adaptor.run(document(self.clips['mono-odd'][0]), self.root / 'too-big', executable=EXECUTABLE), 'RESOURCE_LIMIT')
        self.assertIn('32 MiB', fault['message'])
        with mock.patch.object(audio, 'MAX_SECONDS', 1):
            self.fault(lambda: adaptor.run(document(self.clips['mono-odd'][0]), self.root / 'too-long', executable=EXECUTABLE), 'RESOURCE_LIMIT')
        self.assertFalse((self.root / 'too-big' / 'audio.wav').exists())

    def test_old_operation_evidence_still_verifies_through_the_existing_path(self):
        """The dispatch added for extractAudio leaves an existing muxReview or video verification path untouched."""
        self.assertIs(adaptor.plan({'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'v', 'filter': 'encodeVideo',
            'options': {'file': '/in/a.mkv', 'endFrame': 2}}]})['nodes'][0]['filter'], 'encodeVideo')


if __name__ == '__main__':
    unittest.main()
