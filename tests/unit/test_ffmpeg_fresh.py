"""Fresh native verification of encodeFrames, encodeSheet and encodeVideo.

Host contracts always run. The native cases need a configured FFmpeg (stored configuration, SCHEMAXIS_CONFIG or
FFMPEG_EXECUTABLE) with ffprobe beside it, and skip otherwise. Each forgery changes the real published bytes with the real
encoder and rewrites the retained bindings, receipt and publication metadata so the retained evidence stays self-consistent;
only the fresh decode of the held bytes can refuse them."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import zlib

from schemaxis.adaptors.ffmpeg import adaptor, fresh, review, video
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.configuration import executable as configured_executable
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation, execution_deadline
from schemaxis.native_command import execute
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


def png(width, height, seed, smooth=False):
    """Busy colours are exact in FFV1; smooth gradients stay inside the H.264 chroma-subsampling budget."""
    def pixel(x, y):
        if smooth:
            return bytes((60 + x * 3 + seed * 20, 80 + y * 4 + seed * 15, 110 + seed * 8, 255))
        return bytes(((x * 40 + seed * 70) % 256, (y * 50 + seed * 30) % 256, (x * y + seed * 90) % 256, 255))
    rows = b''.join(b'\x00' + b''.join(pixel(x, y) for x in range(width)) for y in range(height))
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def frames_document(files, **options):
    return {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'clip', 'filter': 'encodeFrames',
        'options': {'files': [str(f) for f in files], 'fps': 25, 'codec': 'ffv1', **options}}]}


def sheet_document(sheet, metadata, **options):
    return {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'clip', 'filter': 'encodeSheet',
        'options': {'file': str(sheet), 'metadata': str(metadata), 'fps': 25, 'codec': 'ffv1', **options}}]}


def video_document(source, **options):
    return {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'clip', 'filter': 'encodeVideo',
        'options': {'file': str(source), 'startFrame': 1, 'endFrame': 4, 'codec': 'ffv1', **options}}]}


class FreshCase(unittest.TestCase):
    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault.to_dict()


class HostTests(FreshCase):
    def test_fresh_recipe_is_local_forced_and_bounded(self):
        prepared = adaptor.plan(frames_document(['/in/a.png']))
        paths = {'ffmpeg': '/tools/ffmpeg', 'ffprobe': '/tools/ffprobe'}
        for codec, demuxer in (('ffv1', 'matroska'), ('h264', 'mov')):
            prepared = adaptor.plan(frames_document(['/in/a.png'], codec=codec, threads=2))
            recipe = fresh.fresh_commands(paths, Path('/scratch'), prepared, 8, 6)
            for stage in ('decode', 'probe', review.TIMELINE):
                command = recipe[stage]
                self.assertIn(['-protocol_whitelist', 'file', '-f', demuxer], [command[i:i + 4] for i in range(len(command))])
                self.assertEqual(command[-1].rsplit('/', 1)[0], '/scratch')
            self.assertEqual(recipe['probe'][0], '/tools/ffprobe')
            self.assertEqual(recipe['decode'][recipe['decode'].index('-threads') + 1], '2')
            self.assertIn(str(fresh.MAX_RGB + 1), recipe['decode'])
            self.assertEqual(recipe['encode'], adaptor.native_commands('/tools/ffmpeg', Path('/scratch'), prepared, 8, 6)['encode'])

    def test_missing_runtime_is_refused_without_path_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            empty = Path(temporary) / 'empty.json'
            atomic_json(empty, {'version': 1, 'locations': {}})
            environment = {'SCHEMAXIS_CONFIG': str(empty), 'PATH': os.path.dirname(EXECUTABLE) if EXECUTABLE else '/usr/bin'}
            with mock.patch.dict(os.environ, environment):
                os.environ.pop('FFMPEG_EXECUTABLE', None)
                fault = self.fault(lambda: fresh.trusted(), 'INTERPRETER_NOT_FOUND')
            self.assertIn('encodeFrames, encodeSheet or encodeVideo', fault['message'])
            self.assertIn('Paths in receipts and PATH are never used', fault['recovery'])
            self.assertIn('FFMPEG_EXECUTABLE', fault['recovery'])

    def test_ffprobe_must_sit_beside_ffmpeg_and_be_absolute(self):
        with tempfile.TemporaryDirectory() as temporary:
            alone = Path(temporary) / 'ffmpeg'
            alone.write_text('#!/bin/sh\n'); alone.chmod(0o755)
            self.fault(lambda: fresh.trusted(str(alone)), 'INTERPRETER_NOT_FOUND')
            self.fault(lambda: fresh.trusted('ffmpeg'), 'INTERPRETER_NOT_FOUND')

    def test_compare_frames_orders_counts_and_budgets(self):
        first, second = bytes(range(12)), bytes(range(12, 24))
        self.assertEqual(fresh.compare_frames([first, second], first + second, 'ffv1'), [0.0, 0.0])
        self.assertEqual(fresh.compare_frames([first, second], first + second[:-1] + bytes([second[-1] + 3]), 'h264'), [0.0, 0.25])
        for expected, raw, codec in (([first, second], second + first, 'ffv1'), ([first, second], first, 'ffv1'),
                                     ([first, second], first + second + first, 'ffv1'),
                                     ([first], bytes(b ^ 0xff for b in first), 'h264'),
                                     ([first], first[:-1] + bytes([first[-1] ^ 1]), 'ffv1')):
            with self.subTest(codec=codec, length=len(raw)):
                self.fault(lambda: fresh.compare_frames(expected, raw, codec), 'VERIFICATION_FAILED')

    def test_bind_requires_exact_facts_from_the_same_build_and_tolerates_last_bit_drift_from_another(self):
        probe = {'streams': [{'codec_name': 'h264', 'pix_fmt': 'yuv420p', 'width': 2, 'height': 2, 'nb_read_frames': '1',
                              'avg_frame_rate': '25/1', 'color_space': 'smpte170m', 'color_range': 'tv'}], 'format': {'format_name': 'mov', 'nb_streams': 1}}
        facts = {'runtime': 'ffmpeg version 9.0.2', 'width': 2, 'height': 2, 'frames': 1, 'fps': 25, 'codec': 'h264', 'publication': 'a',
                 'duration': 0.04, 'errors': [1.0], 'decodedSHA256': 'd', 'framesSHA256': 'f', 'probe': fresh.probe_view(probe)}
        fresh.bind(dict(facts), dict(facts), probe, True)
        for key, value in (('frames', 1.0), ('width', True), ('publication', 'b'), ('errors', [1.5]), ('decodedSHA256', 'x'), ('duration', 0.5)):
            with self.subTest(key=key):
                self.fault(lambda: fresh.bind({**facts, key: value}, dict(facts), probe, True), 'VERIFICATION_FAILED')
        other = {**facts, 'runtime': 'ffmpeg version 9.1', 'errors': [1.4], 'decodedSHA256': 'y'}
        fresh.bind(dict(facts), other, probe, True)
        self.fault(lambda: fresh.bind(dict(facts), {**other, 'errors': [3.0]}, probe, True), 'VERIFICATION_FAILED')
        changed = json.loads(json.dumps(probe)); changed['streams'][0]['color_space'] = 'bt709'
        self.fault(lambda: fresh.bind(dict(facts), {**facts, 'probe': fresh.probe_view(changed)}, probe, True), 'VERIFICATION_FAILED')
        fresh.bind(dict(facts), {**facts, 'probe': fresh.probe_view(changed)}, probe, False)


def stub_runtime(directory, name):
    """A planted ffmpeg and ffprobe pair; running either records its name in ``ran-<name>``."""
    directory.mkdir()
    for tool in ('ffmpeg', 'ffprobe'):
        script = directory / tool
        script.write_text(f'#!/bin/sh\necho {tool} >> "{directory.parent / ("ran-" + name)}"\nexit 1\n')
        script.chmod(0o755)
    return str(directory / 'ffmpeg')


class EarlyTrustTests(FreshCase):
    """run resolves FFmpeg exactly as verify does (explicit, stored configuration, FFMPEG_EXECUTABLE; never PATH) and
    refuses before creating the output directory or starting any native process."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sources = []
        for index in range(2):
            path = self.root / f'frame{index}.png'
            path.write_bytes(png(8, 6, index)); self.sources.append(path)
        self.sheet = self.root / 'sheet.png'; self.sheet.write_bytes(png(16, 6, 9))
        self.metadata = self.root / 'sheet.json'
        self.metadata.write_text(json.dumps({'version': 'schemaxis.aseprite.sheet/1', 'width': 16, 'height': 6, 'tags': [],
            'frames': [{'x': 0, 'y': 0, 'width': 8, 'height': 6, 'durationMS': 40},
                       {'x': 8, 'y': 0, 'width': 8, 'height': 6, 'durationMS': 80}]}))
        self.video = self.root / 'source.mkv'; self.video.write_bytes(b'\x1a\x45\xdf\xa3 declared Matroska; never decoded')
        self.empty = self.root / 'empty.json'
        atomic_json(self.empty, {'version': 1, 'locations': {}})
        patch = mock.patch.dict(os.environ, {'SCHEMAXIS_CONFIG': str(self.empty)})
        patch.start(); self.addCleanup(patch.stop)
        os.environ.pop('FFMPEG_EXECUTABLE', None)

    def documents(self):
        return {'encodeFrames': frames_document(self.sources), 'encodeSheet': sheet_document(self.sheet, self.metadata),
                'encodeVideo': video_document(self.video),
                'muxReview': {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'review', 'filter': 'muxReview', 'options': {
                    'video': str(self.video), 'audio': str(self.root / 'speech.wav'), 'captions': str(self.root / 'captions.srt')}}]}}

    def configure(self, executable):
        config = self.root / 'config.json'
        atomic_json(config, {'version': 1, 'locations': {'ffmpeg': executable}})
        return mock.patch.dict(os.environ, {'SCHEMAXIS_CONFIG': str(config)})

    def ran(self, name):
        return (self.root / ('ran-' + name)).exists()

    def test_path_only_runs_are_refused_before_any_output_or_native_process(self):
        planted = Path(self.root / 'path-bin')
        stub_runtime(planted, 'path')
        with mock.patch.dict(os.environ, {'PATH': str(planted) + os.pathsep + os.environ.get('PATH', '')}):
            self.assertEqual(shutil.which('ffmpeg'), str(planted / 'ffmpeg'))
            for entry in ('public', 'native'):
                run = adaptor.run if entry == 'public' else adaptor._native_run
                for label, document in self.documents().items():
                    with self.subTest(entry=entry, operation=label):
                        output = self.root / f'out-{entry}-{label}'
                        fault = self.fault(lambda: run(document, output, timeout=30), 'INTERPRETER_NOT_FOUND')
                        self.assertIn('Paths in receipts and PATH are never used', fault['recovery'])
                        self.assertIn('--executable', fault['recovery'])
                        self.assertFalse(output.exists() or output.is_symlink())
                        self.assertFalse(self.ran('path'))

    def test_run_and_verify_share_one_precedence_and_never_consult_path(self):
        explicit, stored, environment = (stub_runtime(self.root / name, name) for name in ('explicit', 'stored', 'environment'))
        with mock.patch.dict(os.environ, {'FFMPEG_EXECUTABLE': environment}), self.configure(stored):
            for label in ('encodeFrames', 'encodeSheet', 'encodeVideo'):
                document = self.documents()[label]
                for entry, keywords, winner in (('native', {'executable': explicit}, 'explicit'), ('native', {}, 'stored'),
                                                ('public', {'executable': explicit}, 'explicit'), ('public', {}, 'stored')):
                    run = adaptor.run if entry == 'public' else adaptor._native_run
                    with self.subTest(label=label, entry=entry, winner=winner):
                        for name in ('explicit', 'stored', 'environment'):
                            (self.root / ('ran-' + name)).unlink(missing_ok=True)
                        with self.assertRaises(SchemaxisError):
                            run(document, self.root / f'p-{label}-{entry}-{winner}', timeout=30, **keywords)
                        self.assertEqual([name for name in ('explicit', 'stored', 'environment') if self.ran(name)], [winner])
        with mock.patch.dict(os.environ, {'FFMPEG_EXECUTABLE': environment}):
            for entry in ('native', 'public'):
                run = adaptor.run if entry == 'public' else adaptor._native_run
                with self.subTest(entry=entry, winner='environment'):
                    for name in ('explicit', 'stored', 'environment'):
                        (self.root / ('ran-' + name)).unlink(missing_ok=True)
                    with self.assertRaises(SchemaxisError):
                        run(self.documents()['encodeFrames'], self.root / f'p-env-{entry}', timeout=30)
                    self.assertEqual([name for name in ('explicit', 'stored', 'environment') if self.ran(name)], ['environment'])

    def test_mux_review_run_receives_the_same_trusted_choice(self):
        explicit, stored, environment = (stub_runtime(self.root / name, name) for name in ('explicit', 'stored', 'environment'))
        document = self.documents()['muxReview']
        seen = []
        def recorder(prepared, directory, executable, deadline):
            seen.append(executable); return {}
        with mock.patch.object(review, 'run', recorder), mock.patch.dict(os.environ, {'FFMPEG_EXECUTABLE': environment}):
            adaptor._native_run(document, self.root / 'm1', executable=explicit)
            with self.configure(stored):
                adaptor._native_run(document, self.root / 'm2', executable=explicit)
                adaptor._native_run(document, self.root / 'm3')
            adaptor._native_run(document, self.root / 'm4')
        self.assertEqual(seen, [explicit, explicit, stored, environment])


@native
class NativeTests(FreshCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='schemaxis-fresh-test-'))
        cls.files = []
        for index in range(3):
            path = cls.root / f'frame{index}.png'
            path.write_bytes(png(8, 6, index)); cls.files.append(path)
        cls.even = [cls.root / f'even{index}.png' for index in range(3)]
        for index, path in enumerate(cls.even):
            path.write_bytes(png(16, 12, index + 5, True))
        cls.sheet = cls.root / 'sheet.png'; cls.sheet.write_bytes(png(16, 6, 9))
        cls.metadata = cls.root / 'sheet.json'
        cls.metadata.write_text(json.dumps({'version': 'schemaxis.aseprite.sheet/1', 'width': 16, 'height': 6, 'tags': [],
            'frames': [{'x': 0, 'y': 0, 'width': 8, 'height': 6, 'durationMS': 40},
                       {'x': 8, 'y': 0, 'width': 8, 'height': 6, 'durationMS': 80}]}))
        cls.counter = 0
        source_run = cls.run_document(frames_document([*cls.files, *cls.files[:2]]))
        cls.source = cls.root / 'source.mkv'
        shutil.copyfile(source_run / 'video.mkv', cls.source)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    @classmethod
    def run_document(cls, document):
        cls.counter += 1
        directory = cls.root / f'run-{cls.counter}'
        adaptor.run(document, directory, executable=EXECUTABLE)
        return directory

    def documents(self):
        return {'frames': frames_document(self.files), 'frames-h264': frames_document(self.even, codec='h264'),
                'sheet': sheet_document(self.sheet, self.metadata), 'video': video_document(self.source)}

    def kernel(self, directory, **options):
        return adaptor._native_verify(directory, **options)

    # --- helpers that forge coherent evidence -------------------------------------------------------------------------
    def rebind(self, directory):
        """Rewrite every retained digest for a replaced publication while keeping the retained decode and probe unchanged."""
        directory = Path(directory)
        prepared = adaptor.plan(json.loads((directory / 'authored.json').read_text()))
        published = directory / prepared['output']
        receipt = json.loads((directory / 'verification.json').read_text())
        for stage in ('decode', 'probe'):
            binding = directory / (stage + '-inputs.json')
            binding.write_text(json.dumps({str(published): file_digest(published)}, sort_keys=True))
            receipt['nativeReadback'][stage]['inputBindingSHA256'] = file_digest(binding)
        receipt['artifacts'][0]['sha256'] = file_digest(published)
        atomic_json(directory / 'verification.json', receipt)
        finalise(directory)

    def reencode(self, directory, frames, command=None):
        """The real trusted encoder over altered frames; returns the forged published bytes without touching the run."""
        directory = Path(directory)
        prepared = adaptor.plan(json.loads((directory / 'authored.json').read_text()))
        probe = json.loads((directory / 'probe.stdout').read_text())['streams'][0]
        width, height = probe['width'], probe['height']
        scratch = Path(tempfile.mkdtemp(prefix='forgery-', dir=self.root))
        (scratch / 'frames.rgb').write_bytes(frames)
        commands = adaptor.native_commands(EXECUTABLE, scratch, prepared, width, height)
        execute(command(commands) if command else commands['encode'], scratch, 'encode', 60)
        return (scratch / prepared['output']).read_bytes()

    def rebuild(self, directory, source_raw=None, published=None):
        """Full rewrite: every retained readback, binding, receipt and result is regenerated from the altered inputs."""
        directory = Path(directory)
        prepared = adaptor.plan(json.loads((directory / 'authored.json').read_text()))
        options = prepared['nodes'][0]['options']
        output = directory / prepared['output']
        if source_raw is not None:
            (directory / 'source-decoded.rgb').write_bytes(source_raw)
        sources, payloads = adaptor.read_sources(directory, prepared)
        width, height, pixels = adaptor.frames(prepared, payloads, directory)
        (directory / 'frames.rgb').write_bytes(b''.join(pixels))
        commands = adaptor.native_commands(EXECUTABLE, directory, prepared, width, height)
        execute(commands['encode'], directory, 'encode', 60)
        if published is not None:
            output.write_bytes(published)
        for stage in ('decode', 'probe'):
            script = directory / (stage + '-launcher.py')
            script.write_text(adaptor.readback_launcher(directory, prepared, stage, commands[stage]))
            execute([sys.executable, str(script)], directory, stage, 60)
        execute(commands['version'], directory, 'version', 60)
        errors = adaptor.compare(pixels, (directory / 'decoded.rgb').read_bytes(), options['codec'])
        receipt = {'artifacts': [{'file': str(output), 'kind': 'video', 'sha256': file_digest(output), 'frames': len(pixels),
            'duration': len(pixels) / options['fps'], 'dimensions': [width, height]}],
            'sources': sources, 'width': width, 'height': height, 'frames': len(pixels), 'fps': options['fps'],
            'duration': len(pixels) / options['fps'], 'codec': options['codec'], 'meanErrors': errors,
            'decodedSHA256': file_digest(directory / 'decoded.rgb'), 'framesSHA256': file_digest(directory / 'frames.rgb'),
            'runtime': (directory / 'version.stdout').read_text().splitlines()[0], 'losses': prepared['losses']}
        submissions = {stage: json.loads((directory / (stage + '-submission.json')).read_text()) for stage in ('decode', 'probe')}
        receipt['nativeReadback'] = adaptor.readback_evidence(directory, prepared, commands, submissions)
        if prepared['nodes'][0]['filter'] == 'encodeVideo':
            source_commands = video.commands(EXECUTABLE, directory, prepared)
            source_submissions = {stage: json.loads((directory / (stage + '-submission.json')).read_text()) for stage in source_commands}
            receipt['sourceReadback'] = adaptor.readback_evidence(directory, prepared, source_commands, source_submissions, tuple(source_commands))
        atomic_json(directory / 'verification.json', receipt)
        finalise(directory)

    def refused_fresh(self, directory, stage=None):
        fault = self.fault(lambda: adaptor.verify(directory), 'VERIFICATION_FAILED')
        self.assertIs(fault['observed'].get('fresh'), True, fault)
        if stage:
            self.assertEqual(fault['observed'].get('stage'), stage, fault)
        return fault

    # --- genuine publications -------------------------------------------------------------------------------------------
    def test_fresh_good_runs_report_fresh_native_verification(self):
        for label, document in self.documents().items():
            with self.subTest(label=label):
                directory = self.run_document(document)
                answer = adaptor.verify(directory)
                self.assertIs(answer['freshNativeVerification'], True)
                self.assertTrue(answer['freshRuntime'].startswith('ffmpeg version '))
                self.assertIs(answer['colourTagged'], True)
                self.assertEqual(json.loads((directory / 'result.json').read_text())['verified'], True)

    def test_same_run_verifies_without_the_run_executable_when_configured(self):
        directory = self.run_document(self.documents()['frames'])
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / 'config.json'
            atomic_json(config, {'version': 1, 'locations': {'ffmpeg': EXECUTABLE}})
            with mock.patch.dict(os.environ, {'SCHEMAXIS_CONFIG': str(config)}):
                os.environ.pop('FFMPEG_EXECUTABLE', None)
                self.assertIs(adaptor.verify(directory)['freshNativeVerification'], True)
            with mock.patch.dict(os.environ, {'SCHEMAXIS_CONFIG': str(Path(temporary) / 'absent.json')}):
                os.environ.pop('FFMPEG_EXECUTABLE', None)
                self.fault(lambda: adaptor.verify(directory), 'INVALID_CONFIGURATION')
        self.assertIs(adaptor.verify(directory, executable=EXECUTABLE)['freshNativeVerification'], True)

    def test_genuine_runs_and_standalone_verify_follow_explicit_then_stored_then_environment(self):
        document = self.documents()['frames']
        planted = stub_runtime(self.root / f'planted-{self.counter}', f'planted-{self.counter}')
        marker = self.root / f'ran-planted-{self.counter}'
        def configured(location):
            config = self.root / 'precedence.json'
            atomic_json(config, {'version': 1, 'locations': {'ffmpeg': location}})
            return mock.patch.dict(os.environ, {'SCHEMAXIS_CONFIG': str(config)})
        empty = self.root / 'precedence-empty.json'
        atomic_json(empty, {'version': 1, 'locations': {}})
        with mock.patch.dict(os.environ, {'FFMPEG_EXECUTABLE': planted}), configured(EXECUTABLE):
            for label, run, verify in (('public', adaptor.run, adaptor.verify), ('native', adaptor._native_run, adaptor._native_verify)):
                with self.subTest(run=label, chosen='stored over environment'):
                    self.counter += 1
                    directory = self.root / f'precedence-{self.counter}'
                    run(document, directory)
                    self.assertIs(verify(directory)['freshNativeVerification'], True)
            self.assertFalse(marker.exists())
            self.counter += 1
            directory = self.root / f'precedence-{self.counter}'
            adaptor.run(document, directory, executable=EXECUTABLE)
            self.assertIs(adaptor.verify(directory, executable=EXECUTABLE)['freshNativeVerification'], True)
            self.assertFalse(marker.exists())
        with mock.patch.dict(os.environ, {'FFMPEG_EXECUTABLE': EXECUTABLE}), configured(planted):
            with self.subTest(chosen='stored (planted) over environment (genuine)'):
                self.fault(lambda: adaptor.verify(directory), 'RUNNER_FAILED')
                self.assertTrue(marker.exists())
                marker.unlink()
            with self.subTest(chosen='explicit (genuine) over stored (planted)'):
                self.assertIs(adaptor.verify(directory, executable=EXECUTABLE)['freshNativeVerification'], True)
                self.assertFalse(marker.exists())
        with mock.patch.dict(os.environ, {'FFMPEG_EXECUTABLE': EXECUTABLE}), configured(EXECUTABLE):
            with self.subTest(chosen='explicit (planted) over stored and environment (genuine)'):
                self.fault(lambda: adaptor.verify(directory, executable=planted), 'RUNNER_FAILED')
                self.assertTrue(marker.exists())
        marker.unlink()
        with mock.patch.dict(os.environ, {'SCHEMAXIS_CONFIG': str(empty), 'FFMPEG_EXECUTABLE': planted}):
            with self.subTest(chosen='environment alone'):
                self.fault(lambda: adaptor.verify(directory), 'RUNNER_FAILED')
                self.assertTrue(marker.exists())

    def test_genuine_runtime_on_path_alone_is_refused_for_run_and_leaves_nothing(self):
        empty = self.root / 'path-empty.json'
        atomic_json(empty, {'version': 1, 'locations': {}})
        environment = {'SCHEMAXIS_CONFIG': str(empty), 'PATH': os.path.dirname(EXECUTABLE) + os.pathsep + os.environ.get('PATH', '')}
        with mock.patch.dict(os.environ, environment):
            os.environ.pop('FFMPEG_EXECUTABLE', None)
            self.assertTrue(shutil.which('ffmpeg') and shutil.which('ffprobe'))
            for label, run in (('public', adaptor.run), ('native', adaptor._native_run)):
                for document_label, document in self.documents().items():
                    with self.subTest(run=label, document=document_label):
                        directory = self.root / f'path-only-{label}-{document_label}'
                        self.fault(lambda: run(document, directory), 'INTERPRETER_NOT_FOUND')
                        self.assertFalse(directory.exists())

    # --- coherent forgeries of the published bytes --------------------------------------------------------------------
    def test_forged_publication_with_unchanged_retained_readbacks_is_refused_for_all_operations(self):
        for label in ('frames', 'sheet', 'video'):
            with self.subTest(label=label):
                directory = self.run_document(self.documents()[label])
                frames = bytearray((directory / 'frames.rgb').read_bytes())
                frames[5] ^= 0x55
                forged = self.reencode(directory, bytes(frames))
                (directory / adaptor.plan(json.loads((directory / 'authored.json').read_text()))['output']).write_bytes(forged)
                self.rebind(directory)
                # The retained evidence is coherent: the genuine decode still equals the captured pixels and every binding agrees.
                self.assertEqual(self.retained_coherent(directory), 0.0)
                fault = self.refused_fresh(directory, 'decode')
                self.assertIn('differs', fault['message'])

    def test_forged_frame_count_and_order_are_refused(self):
        directory = self.run_document(self.documents()['frames'])
        raw = (directory / 'frames.rgb').read_bytes(); stride = len(raw) // 3
        for label, changed in (('dropped', raw[:-stride]), ('reordered', raw[stride:2 * stride] + raw[:stride] + raw[2 * stride:])):
            with self.subTest(label=label):
                run = self.run_document(self.documents()['frames'])
                (run / 'video.mkv').write_bytes(self.reencode(run, changed))
                self.rebind(run)
                self.refused_fresh(run)

    def test_untagged_h264_is_refused_for_the_current_recipe_and_reported_for_legacy_evidence(self):
        directory = self.run_document(self.documents()['frames-h264'])
        def without_tags(commands):
            command = list(commands['encode']); index = command.index('-colorspace')
            del command[index:index + 4]
            return command
        untagged = self.reencode(directory, (directory / 'frames.rgb').read_bytes(), without_tags)
        (directory / 'video.mp4').write_bytes(untagged)
        self.rebind(directory)
        self.assertIn('colour', self.refused_fresh(directory)['message'])
        # Legacy untagged evidence: an honest untagged recipe record is accepted and reported as such, never as tagged.
        legacy = self.run_document(self.documents()['frames-h264'])
        submission = json.loads((legacy / 'encode-submission.json').read_text())
        command = submission['nativeCommand']; index = command.index('-colorspace')
        submission['nativeCommand'] = command[:index] + command[index + 4:]
        atomic_json(legacy / 'encode-submission.json', submission)
        self.assertIs(adaptor.verify(legacy)['colourTagged'], False)

    def test_equivalent_in_budget_reencode_with_fully_rewritten_evidence_verifies(self):
        directory = self.run_document(self.documents()['frames-h264'])
        original = (directory / 'video.mp4').read_bytes()
        frames = (directory / 'frames.rgb').read_bytes()
        def softer(commands):
            command = list(commands['encode']); command[command.index('-crf') + 1] = '20'
            return command
        equivalent = self.reencode(directory, frames, softer)
        self.assertNotEqual(equivalent, original)
        self.rebuild(directory, published=equivalent)
        answer = adaptor.verify(directory)
        self.assertIs(answer['freshNativeVerification'], True)

    def test_source_video_forgery_for_encode_video_is_refused_against_the_captured_video(self):
        directory = self.run_document(self.documents()['video'])
        raw = bytearray((directory / 'source-decoded.rgb').read_bytes())
        stride = 8 * 6 * 3
        for offset in range(stride, 4 * stride, 7):
            raw[offset] ^= 0x33
        self.rebuild(directory, source_raw=bytes(raw))
        # Every retained readback now agrees with a source the captured video does not decode to.
        self.assertEqual(self.retained_coherent(directory), 0.0)
        fault = self.refused_fresh(directory)
        self.assertTrue(fault['observed']['stage'] in ('decode', 'facts'), fault)

    def retained_coherent(self, directory):
        """The retained half alone: frames derived from the retained inputs compare cleanly with the retained decode."""
        prepared = adaptor.plan(json.loads((directory / 'authored.json').read_text()))
        sources, payloads = adaptor.read_sources(directory, prepared)
        return max(adaptor.compare(adaptor.frames(prepared, payloads, directory)[2], (directory / 'decoded.rgb').read_bytes(),
                                   prepared['nodes'][0]['options']['codec']))

    # --- strict retained evidence and claims --------------------------------------------------------------------------
    def test_retained_json_must_be_strict_typed_and_closed(self):
        directory = self.run_document(self.documents()['frames'])

        def typed(change):
            def edit(text):
                value = json.loads(text); change(value)
                return json.dumps(value)
            return edit
        cases = (('probe.stdout', 'duplicate key', lambda text: text.replace('{', '{"streams": [], ', 1)),
                 ('verification.json', 'integer as float', typed(lambda v: v.__setitem__('frames', 3.0))),
                 ('verification.json', 'integer as boolean', typed(lambda v: v.__setitem__('frames', True))),
                 ('verification.json', 'NaN', typed(lambda v: v.__setitem__('duration', float('nan')))),
                 ('verification.json', 'overflow', lambda text: text.replace('"width": 8', '"width": 1e400', 1)),
                 ('verification.json', 'width as float', typed(lambda v: v.__setitem__('width', 8.0))),
                 ('result.json', 'artifacts boolean', typed(lambda v: v.__setitem__('artifacts', True))),
                 ('result.json', 'extra claim', typed(lambda v: v.__setitem__('recognitionAccuracyCertified', False))),
                 ('result.json', 'verified integer', typed(lambda v: v.__setitem__('verified', 1)), 'INCOMPLETE_EXECUTION'),
                 ('result.json', 'other video', typed(lambda v: v.__setitem__('video', '/elsewhere/video.mkv'))),
                 ('plan.json', 'fps as float', typed(lambda v: v['nodes'][0]['options'].__setitem__('fps', 25.0))))
        for name, label, edit, *code in cases:
            with self.subTest(name=name, label=label):
                path = directory / name
                saved = path.read_bytes()
                changed = edit(saved.decode())
                self.assertNotEqual(changed.encode(), saved)
                path.write_text(changed)
                try:
                    fault = self.fault(lambda: self.kernel(directory), code[0] if code else 'VERIFICATION_FAILED')
                    self.assertNotIn('fresh', fault['observed'], fault)
                finally:
                    path.write_bytes(saved)
        self.assertIs(self.kernel(directory)['verified'], True)

    def test_deep_json_nesting_is_a_verification_fault(self):
        directory = self.run_document(self.documents()['frames'])
        path = directory / 'probe.stdout'; saved = path.read_bytes()
        path.write_text('[' * 100000 + ']' * 100000)
        try:
            self.fault(lambda: adaptor.verify(directory), 'VERIFICATION_FAILED')
        finally:
            path.write_bytes(saved)

    # --- runtime, bounds, cleanup -------------------------------------------------------------------------------------
    def test_wrong_and_planted_runtimes_never_decide(self):
        directory = self.run_document(self.documents()['frames'])
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'ran'
            planted = Path(temporary) / 'ffmpeg'
            planted.write_text(f'#!/bin/sh\necho planted > {marker}\necho "not ffmpeg"\n'); planted.chmod(0o755)
            (Path(temporary) / 'ffprobe').write_text(f'#!/bin/sh\necho planted > {marker}\nexit 1\n'); (Path(temporary) / 'ffprobe').chmod(0o755)
            self.fault(lambda: adaptor.verify(directory, executable=str(planted)), 'UNSUPPORTED_RUNTIME')
            alone = Path(temporary) / 'alone'; alone.mkdir()
            (alone / 'ffmpeg').symlink_to(EXECUTABLE)
            self.fault(lambda: adaptor.verify(directory, executable=str(alone / 'ffmpeg')), 'INTERPRETER_NOT_FOUND')
            # A receipt or submission naming a planted executable is inert data and is never launched.
            submission_path = directory / 'encode-submission.json'
            saved = submission_path.read_bytes()
            marker.unlink()
            submission = json.loads(saved); submission['nativeCommand'][0] = str(planted)
            atomic_json(submission_path, submission)
            try:
                self.fault(lambda: adaptor.verify(directory, executable=EXECUTABLE), 'VERIFICATION_FAILED')
            finally:
                submission_path.write_bytes(saved)
            self.assertFalse(marker.exists())
        self.assertIs(adaptor.verify(directory, executable=EXECUTABLE)['verified'], True)

    def test_deadline_cancellation_byte_budget_and_cleanup(self):
        directory = self.run_document(self.documents()['frames'])
        scratch = Path(tempfile.mkdtemp(prefix='schemaxis-fresh-tmp-'))
        try:
            with mock.patch.object(tempfile, 'tempdir', str(scratch)):
                with execution_deadline(1e-9):
                    time.sleep(0.01)
                    self.assertIn(self.fault(lambda: adaptor.verify(directory), 'RUNNER_TIMED_OUT')['code'], ('RUNNER_TIMED_OUT',))
                cancel = threading.Event(); cancel.set()
                with allocation({}, cancel):
                    self.fault(lambda: adaptor.verify(directory), 'RUNNER_CANCELLED')
                with mock.patch.object(fresh, 'MAX_PUBLICATION', 16):
                    self.fault(lambda: adaptor.verify(directory), 'VERIFICATION_FAILED')
                with mock.patch.object(fresh, 'MAX_RGB', 10):
                    self.refused_fresh(directory)
                forged = self.run_document(self.documents()['frames'])
                (forged / 'video.mkv').write_bytes(self.reencode(forged, (forged / 'frames.rgb').read_bytes()[:-8 * 6 * 3]))
                self.rebind(forged)
                self.refused_fresh(forged)
            self.assertEqual(list(scratch.iterdir()), [], 'private verification directories must be removed')
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        self.assertIs(adaptor.verify(directory)['verified'], True)

    def test_publication_or_source_changed_during_verification_is_refused(self):
        directory = self.run_document(self.documents()['frames'])
        real = fresh.observe

        def swapping(*arguments, **keywords):
            found = real(*arguments, **keywords)
            data = (directory / 'input-0000').read_bytes()
            (directory / 'input-0000').write_bytes(data[:-5] + b'\x00' * 5)
            return found
        saved = (directory / 'input-0000').read_bytes()
        try:
            with mock.patch.object(fresh, 'observe', swapping):
                fault = self.fault(lambda: adaptor.verify(directory), 'VERIFICATION_FAILED')
            self.assertIn('changed while it was being verified', fault['message'])
        finally:
            (directory / 'input-0000').write_bytes(saved)


if __name__ == '__main__':
    unittest.main()
