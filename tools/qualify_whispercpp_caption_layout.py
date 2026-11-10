#!/usr/bin/env python3
"""Acceptance of the FFmpeg review-movie handoff of schemaxis.whispercpp.captions/1 (explicit caption line layout) with real FFmpeg.

This is a PUBLISHING handoff check, not speech-recognition requalification and not native qualification of the layout route, which is
host-only. An explicitly illustrative two-cue timed transcript (no recognition ran; its model and native digests are digests of placeholder text)
is laid out into at most three lines of at most 20 code points, then the published captions.srt is handed through one verified workflow to the
FFmpeg muxReview operation together with an FFV1 video and a PCM16 WAV of exactly two seconds each, prepared natively from literal pixels and
literal samples. The Matroska file is read back by separate FFmpeg and FFprobe invocations and compared with hand-written expectations: every
word, every line break and every time of the SubRip stream, every pixel and every audio sample. The WebVTT is parsed by an independent host
parser and, as a recorded probe that is not a certification, read by FFmpeg's own WebVTT demuxer.

Controls: the same layout through a literal path and through the workflow artifact yield byte-identical movies; a resumed workflow reuses the
verified layout job; a changed source file with the old pin is refused (LAYOUT_SOURCE_STALE) both fresh and on resume; a new source with a new pin
runs and is read back against its own hand-written lines. The layout runs under a Popen that raises, proving no process is launched by it.

Every native process is recorded by PID, argv, exit status and, when it could be seen, the executable and working directory /proc showed and a
selected part of its environment. Processes the workflow executor launches are launched by the harness (dispatch.SubprocessRunner) through a Python replay script that changes
directory into the working directory of its stage (a job directory, or for a fresh verification a temporary directory under TMPDIR) and then execs
the native command with this process's environment plus the harness's thread variables, so a native process shares this process's TMPDIR and variables; it is
not a minimal or private environment. Each is observed for up to 0.3 s after it starts and at every poll, so a process that ends first is recorded without an
observed executable, and an environment read taken during the exec can be empty (counted separately). No child is inferred from a process tree. Only the selected FFmpeg and FFprobe binaries are fingerprinted
before and after. The declarations are automated illustrative fixtures; no person listened to or reviewed anything. The tool refuses to start under
python -O or PYTHONOPTIMIZE because its checks are assert statements.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import wave

if not __debug__:
    sys.exit('refused: this qualifier uses assert statements; run without python -O / PYTHONOPTIMIZE. No acceptance work, native process or output was started.')

from schemaxis import workflow  # noqa: E402
from schemaxis.adaptors.ffmpeg import adaptor as ffmpeg_adaptor  # noqa: E402
from schemaxis.adaptors.whispercpp import caption_layout as layout  # noqa: E402
from schemaxis.artifacts import atomic_json, file_digest  # noqa: E402
from schemaxis.configuration import location_context  # noqa: E402
from schemaxis.core import timed_text  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FPS, FRAMES, WIDTH, HEIGHT, RATE, SAMPLES = 10, 20, 32, 24, 16000, 32000
PLACEHOLDER = b'illustrative fixture: no recognition model and no native whisper.cpp run exist for this document'
ASR_NOTE = 'illustrative fixture; no recognition ran and nobody reviewed it'
BOUNDS = (20, 3)
# Hand-written expectations. They are not derived from any schemaxis code; the hand-checked tie in cue 1 (16/15 against 12/16 evenness) is the documented earliest-break rule.
CUES = [(0, 900, 'The quick brown fox jumps over the lazy dog today'), (1000, 1950, 'Fish & chips and café au lait at noon, please')]
LINES = [['The quick brown', 'fox jumps over', 'the lazy dog today'], ['Fish & chips', 'and café au lait', 'at noon, please']]
EXPECTED_SRT = ('1\n00:00:00,000 --> 00:00:00,900\nThe quick brown\nfox jumps over\nthe lazy dog today\n\n'
                '2\n00:00:01,000 --> 00:00:01,950\nFish & chips\nand café au lait\nat noon, please\n\n')
EXPECTED_VTT = ('WEBVTT\n\n00:00:00.000 --> 00:00:00.900\nThe quick brown\nfox jumps over\nthe lazy dog today\n\n'
                '00:00:01.000 --> 00:00:01.950\nFish &amp; chips\nand café au lait\nat noon, please\n\n')
SECOND = [(0, 900, 'Different words for the second source fixture'), (1000, 1950, 'and one short end')]
SECOND_SRT = ('1\n00:00:00,000 --> 00:00:00,900\nDifferent words\nfor the second\nsource fixture\n\n'
              '2\n00:00:01,000 --> 00:00:01,950\nand one short end\n\n')
PROCESSES = []
OBSERVED_ENVIRONMENT = ('TMPDIR', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'LANG', 'PYTHONPATH', 'FFMPEG_EXECUTABLE')


def sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(binary):
    """Read-only fingerprint of one selected binary (symlinks resolved): size, mtime and SHA-256."""
    resolved = Path(binary).resolve(strict=True); status = resolved.stat()
    return {'path': str(resolved), 'bytes': status.st_size, 'mtimeNs': status.st_mtime_ns, 'sha256': sha256(resolved)}


def observe(pid, record):
    """What /proc shows of a live process right now: executable, working directory and a selected part of the environment."""
    try:
        executable, cwd = os.readlink(f'/proc/{pid}/exe'), os.readlink(f'/proc/{pid}/cwd')
        environment = dict(item.split(b'=', 1) for item in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0') if b'=' in item)
    except OSError:
        return
    entry = {'exe': executable, 'cwd': cwd, 'environ': {k: environment[k.encode()].decode('utf-8', 'replace') for k in OBSERVED_ENVIRONMENT if k.encode() in environment},
             'environCount': len(environment)}
    seen = record['observations']
    if not seen or seen[-1]['exe'] != executable: seen.append(entry)
    elif seen[-1]['environCount'] == 0 and environment: seen[-1] = entry  # an environment read during exec can be empty; keep the first complete one


class RecordingPopen(subprocess.Popen):
    """Records every process this tool or the harness starts while it is installed; observes through poll/wait, with no thread."""

    def __init__(self, args, *positional, **keywords):
        super().__init__(args, *positional, **keywords)
        self.record = {'pid': self.pid, 'parentPid': os.getpid(), 'argv': [str(item) for item in (args if isinstance(args, (list, tuple)) else [args])],
                       'cwdArgument': str(keywords.get('cwd')) if keywords.get('cwd') else None, 'startNewSession': bool(keywords.get('start_new_session')),
                       'observations': [], 'exit': None, 'source': 'harness-or-adaptor Popen'}
        script = next((str(item) for item in self.record['argv'] if str(item).endswith('.py')), None)
        if script: self.record['stage'] = Path(script).parent.name  # the harness names each replay script directory after its native stage
        PROCESSES.append(self.record)
        # A harness replay interpreter changes directory and execs the native command within tens of milliseconds, so look for the
        # exec for at most 0.3 s; a process that never changes executable is recorded as the interpreter it stayed.
        own = os.path.realpath(sys.executable); deadline = time.monotonic() + 0.3
        while True:
            observe(self.pid, self.record)
            seen = self.record['observations']
            if (seen and os.path.realpath(seen[-1]['exe']) != own and seen[-1]['environCount']) or super().poll() is not None or time.monotonic() >= deadline: break
            time.sleep(0.002)

    def poll(self):
        if self.returncode is None: observe(self.pid, self.record)
        code = super().poll(); self.record['exit'] = self.returncode; return code

    def wait(self, timeout=None):
        if self.returncode is None: observe(self.pid, self.record)
        code = super().wait(timeout); self.record['exit'] = self.returncode; return code


class Recording:
    def __enter__(self):
        self.original = subprocess.Popen; subprocess.Popen = RecordingPopen; return self

    def __exit__(self, *exception): subprocess.Popen = self.original


def native(label, argv, *, timeout=60, env=None):
    """One bounded direct native run, PID recorded. The child is exec'd directly, so its PID is the native executable's PID."""
    started = time.monotonic()
    process = subprocess.Popen([str(item) for item in argv], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, env=env)
    record = {'label': label, 'pid': process.pid, 'parentPid': os.getpid(), 'argv': [str(item) for item in argv], 'observations': [], 'exit': None, 'source': 'direct qualifier run'}
    PROCESSES.append(record); observe(process.pid, record)
    try: out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill(); process.communicate(); record['exit'] = 'timeout'; raise
    record['exit'] = process.returncode; record['seconds'] = round(time.monotonic() - started, 3)
    assert process.returncode == 0, (label, process.returncode, err[-300:])
    return out


def verified_workflow(directory, ffmpeg):
    """Fresh workflow verification with the trusted FFmpeg supplied by the caller, never by a receipt."""
    with location_context({'ffmpeg': ffmpeg}): return workflow.verify(directory)['verified']


def refused(action, code):
    try: action()
    except SchemaxisError as error:
        assert error.fault.code == code, (code, error.fault.to_dict()); return error.fault.to_dict()
    raise AssertionError('expected ' + code)


def pixels(index):
    return bytes((30 + index * 25 + x * 2 + y + channel * 18) % 230 for y in range(HEIGHT) for x in range(WIDTH) for channel in range(3))


def samples(count, step=977): return [((i * step) % 24001) - 12000 for i in range(count)]


def write_wav(path, values):
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(RATE)
        stream.writeframes(b''.join(struct.pack('<h', value) for value in values))
    return Path(path)


def source_document(cues, audio_path):
    """A closed schemaxis.whispercpp.segments/1 machine-draft shape around the given cues, bound to the real two-second WAV; no recognition produced it."""
    audio = Path(audio_path).read_bytes()
    document = {'version': 'schemaxis.whispercpp.segments/1', 'language': 'en', 'timeUnit': 'millisecond',
                'audio': {'sha256': hashlib.sha256(audio).hexdigest(), 'bytes': len(audio), 'frames': SAMPLES, 'rate': RATE, 'channels': 1, 'durationMs': 2000, 'durationRemainderFrames': 0},
                'model': {'sha256': hashlib.sha256(PLACEHOLDER).hexdigest(), 'bytes': len(PLACEHOLDER)}, 'nativeJsonSha256': hashlib.sha256(PLACEHOLDER + b' (native json)').hexdigest(),
                'segmentCount': len(cues), 'segments': [{'index': i, 'startMs': s, 'endMs': e, 'text': t} for i, (s, e, t) in enumerate(cues)],
                'review': {'accuracyCertified': False, 'humanReviewRequired': True, 'statement': 'Machine-draft shape of an ' + ASR_NOTE + '.',
                           'policy': {'timing': 'illustrative fixture times in integral milliseconds', 'text': 'illustrative fixture text'}}}
    timed_text.validate(document)  # the shared validator must accept the fixture before any route sees it
    return (json.dumps(document, indent=2, sort_keys=True) + '\n').encode('utf-8')


def layout_document(path, pin, width=BOUNDS[0], lines=BOUNDS[1]):
    return {'version': layout.VERSION, 'operation': 'layout', 'source': {'path': path}, 'sourceSha256': pin, 'maxLineCodePoints': width, 'maxLines': lines}


def graph_for(source, pin, video, audio, captions=None):
    caption = captions if captions else {'$artifact': 'layout', 'index': 0}
    operations = []
    if not captions: operations.append({'id': 'layout', 'document': layout_document(str(source), pin)})
    operations.append({'id': 'review', 'document': {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'review', 'filter': 'muxReview', 'options': {
        'video': str(video), 'audio': str(audio), 'captions': caption, 'captionStatus': 'machineDraft', 'threads': 1}}]}})
    return {'version': 'schemaxis.workflow/1', 'operations': operations}


def vtt_cues(text):
    """Independent WebVTT parser: header, blank-line separated blocks, one timing line, LF payload lines, entities reversed with & last."""
    assert text.startswith('WEBVTT\n\n') and text.endswith('\n\n'), 'WebVTT header or final blank line missing'
    cues = []
    for block in text[len('WEBVTT\n\n'):-2].split('\n\n'):
        lines = block.split('\n'); timing = lines[0]
        start, arrow, end = timing.partition(' --> ')
        assert arrow and all(len(part) == 12 and part[2] == ':' and part[5] == ':' and part[8] == '.' for part in (start, end)), timing
        def millis(clock): return ((int(clock[:2]) * 60 + int(clock[3:5])) * 60 + int(clock[6:8])) * 1000 + int(clock[9:])
        payload = [line.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&') for line in lines[1:]]
        cues.append((millis(start), millis(end), payload))
    return cues


def check_publications(directory, lines, expected_srt, expected_vtt, cues):
    srt = (directory / 'captions.srt').read_text(encoding='utf-8'); vtt = (directory / 'captions.vtt').read_text(encoding='utf-8')
    assert srt == expected_srt and vtt == expected_vtt, 'published SRT or WebVTT differs from the hand-written bytes'
    parsed = vtt_cues(vtt)
    assert [(s, e, p) for s, e, p in parsed] == [(s, e, lines[i]) for i, (s, e, _) in enumerate(cues)], 'independent WebVTT parse differs'
    for (s, e, text), (_, _, payload) in zip(cues, parsed): assert ' '.join(payload) == text, 'joining the lines with one space must restore the cue text'
    summary = json.loads((directory / 'caption-layout.json').read_text())
    assert [(c['startMs'], c['endMs'], c['text'], c['lines']) for c in summary['cues']] == [(s, e, t, lines[i]) for i, (s, e, t) in enumerate(cues)]
    assert all(c['lineCodePoints'] == [len(x) for x in c['lines']] for c in summary['cues'])
    return {'cues': len(parsed), 'srtBytes': len(srt.encode()), 'vttBytes': len(vtt.encode())}


def readback(listing_tool, ffmpeg, review, destination, expected_srt, count=FRAMES):
    """Re-read the published Matroska file with separate FFprobe/FFmpeg invocations and literal expectations."""
    listing = json.loads(native('readback-probe', [listing_tool, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', review]))
    assert [(s['codec_type'], s['codec_name']) for s in listing['streams']] == [('video', 'ffv1'), ('audio', 'pcm_s16le'), ('subtitle', 'subrip')], listing['streams']
    destination.mkdir()
    native('readback-video', [ffmpeg, '-v', 'error', '-y', '-i', review, '-map', '0:v:0', '-an', '-sn', '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', destination / 'v.rgb'])
    assert (destination / 'v.rgb').read_bytes() == b''.join(pixels(i) for i in range(count)), 'video frames differ from literal pixels'
    native('readback-audio', [ffmpeg, '-v', 'error', '-y', '-i', review, '-map', '0:a:0', '-vn', '-sn', '-c:a', 'pcm_s16le', '-f', 'wav', destination / 'a.wav'])
    with wave.open(str(destination / 'a.wav')) as stream:
        decoded = struct.unpack(f'<{stream.getnframes()}h', stream.readframes(stream.getnframes()))
        duration = stream.getnframes() / stream.getframerate()
    assert list(decoded) == samples(SAMPLES), 'PCM samples differ from literal samples'
    native('readback-subrip', [ffmpeg, '-v', 'error', '-y', '-i', review, '-map', '0:s:0', '-c:s', 'srt', '-f', 'srt', destination / 's.srt'])
    extracted = (destination / 's.srt').read_text(encoding='utf-8')
    assert extracted == expected_srt, 'the SubRip extracted from Matroska differs from the hand-written words, line breaks or times'
    return {'streams': 3, 'video': 'ffv1', 'audio': 'pcm_s16le', 'subtitle': 'subrip', 'audioSeconds': duration, 'frames': count, 'extractedSubRipEqualsLiteral': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', required=True, type=Path, help='absolute FFmpeg 9.0.2 binary; ffprobe is the sibling')
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--freeze-manifest', type=Path, help='JSON map of repository-relative owned file to SHA-256, written before this run; checked at start and end')
    args = parser.parse_args()
    ffmpeg = str(args.ffmpeg.absolute()); probe_tool = str(Path(ffmpeg).with_name('ffprobe'))
    directory = args.output_directory.resolve(); directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {'verified': False, 'route': layout.VERSION, 'nativeQualified': False, 'hostOnly': True, 'pid': os.getpid(), 'parentPid': os.getppid(), 'argv': sys.argv,
              'scope': 'FFmpeg review-movie publishing handoff, not ASR requalification and not native qualification of the layout route',
              'declarations': 'automated illustrative fixtures; no recognition ran, no person listened to or reviewed anything',
              'environment': {k: os.environ.get(k) for k in OBSERVED_ENVIRONMENT}, 'cwd': os.getcwd()}
    qualification = ROOT / 'src/schemaxis/adaptors/whispercpp/qualification.json'; qualification_before = sha256(qualification)
    frozen = json.loads(args.freeze_manifest.read_text()) if args.freeze_manifest else None
    def freeze_state(): return {name: sha256(ROOT / name) for name in sorted(frozen)} if frozen else None
    if frozen:
        report['freezeBefore'] = freeze_state(); assert report['freezeBefore'] == frozen, 'owned source differs from the freeze manifest before the run'
    binaries_before = {'ffmpeg': fingerprint(ffmpeg), 'ffprobe': fingerprint(probe_tool)}; report['binariesBefore'] = binaries_before
    try:
        version = native('version', [ffmpeg, '-version']).decode().splitlines()[0]
        assert version.startswith('ffmpeg version 9.0.2 '), version
        report['ffmpegVersion'] = version
        inputs = directory / 'inputs'; inputs.mkdir()
        raw = inputs / 'video.rgb'; raw.write_bytes(b''.join(pixels(i) for i in range(FRAMES)))
        video = inputs / 'video.mkv'
        native('encode-ffv1', [ffmpeg, '-v', 'error', '-y', '-filter_threads', '1', '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', f'{WIDTH}x{HEIGHT}', '-framerate', str(FPS),
                               '-i', raw, '-an', '-threads', '1', '-c:v', 'ffv1', '-level', '1', '-pix_fmt', 'bgr0', video])
        audio = write_wav(inputs / 'speech.wav', samples(SAMPLES))
        source = inputs / 'timed-text.json'; source.write_bytes(source_document(CUES, audio)); pin = sha256(source)
        report['fixtures'] = {'videoFrames': FRAMES, 'videoFps': FPS, 'audioSamples': SAMPLES, 'audioRate': RATE, 'seconds': 2, 'sourceSha256': pin, 'cues': CUES,
                              'recognitionRunHere': False, 'modelDigestIs': 'sha256 of placeholder text, no model'}

        # 1. Host layout through a literal path; no process may be launched by the route.
        def forbidden(*arguments, **keywords): raise AssertionError('the layout route launched a process')
        original = subprocess.Popen; subprocess.Popen = forbidden
        try:
            result = layout.run(layout_document(str(source), pin), directory / 'layout-literal', timeout=60); checked = layout.verify(directory / 'layout-literal')
        finally: subprocess.Popen = original
        assert result['verified'] and result['nativeProcesses'] == 0 and checked['verified'] and result['reflowedCues'] == 2 and result['lines'] == 6, result
        report['literalPathLayout'] = {'result': result, 'readback': check_publications(directory / 'layout-literal', LINES, EXPECTED_SRT, EXPECTED_VTT, CUES), 'noProcessLaunched': True}

        # 2. One verified workflow: layout, then the published SRT artifact (index 0) into muxReview.
        graph = graph_for(source, pin, video, audio)
        (directory / 'workflow.json').write_text(json.dumps(graph, indent=2) + '\n')
        locations = {'ffmpeg': ffmpeg}
        with Recording():
            outcome = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=300)
            assert outcome['status'] == 'succeeded' and verified_workflow(directory / 'workflow', ffmpeg)
            review_dir = next((directory / 'workflow' / 'review').rglob('review.mkv')).parent
            fresh = ffmpeg_adaptor.verify(review_dir, executable=ffmpeg)
        assert fresh['verified'] and fresh['freshNativeVerification'] is True and fresh['streams'] == 3, fresh
        assert fresh.get('recognitionAccuracyCertified') is not True and fresh.get('humanReviewVerified') is not True, fresh
        laid = next((directory / 'workflow' / 'layout').rglob('captions.srt')).parent
        report['workflow'] = {'status': outcome['status'], 'budgetDeclaredByScheduler': outcome.get('budget'), 'freshVerification': {k: fresh.get(k) for k in ('verified', 'streams', 'frames', 'freshNativeVerification', 'freshRuntime', 'captionStatus')},
                              'layoutReadback': check_publications(laid, LINES, EXPECTED_SRT, EXPECTED_VTT, CUES)}
        report['workflow']['matroskaReadback'] = readback(probe_tool, ffmpeg, review_dir / 'review.mkv', directory / 'independent', EXPECTED_SRT)
        # The extracted lines are compared word by word as well, so a whitespace-only difference cannot hide inside a joined string.
        words = [w for _, _, t in CUES for w in t.split(' ')]
        extracted = (directory / 'independent' / 's.srt').read_text(encoding='utf-8').split('\n\n')[:-1]
        assert [w for block in extracted for line in block.split('\n')[2:] for w in line.split(' ')] == words, 'extracted words differ'
        assert [block.split('\n')[2:] for block in extracted] == LINES, 'extracted line breaks differ'
        report['workflow']['wordsCompared'] = len(words)

        # 3. WebVTT: independent host parse (above) plus a recorded, uncertified probe by FFmpeg's own WebVTT demuxer.
        try:
            native('webvtt-probe', [ffmpeg, '-v', 'error', '-y', '-i', laid / 'captions.vtt', '-c:s', 'srt', '-f', 'srt', directory / 'vtt-probe.srt'])
            probed = (directory / 'vtt-probe.srt').read_text(encoding='utf-8')
            report['webvttNativeProbe'] = {'demuxed': True, 'equalsHandWrittenSrt': probed == EXPECTED_SRT, 'observed': probed,
                                           'scope': 'one FFmpeg 9.0.2 demuxer reading of this file; not a player or specification conformance claim'}
        except (AssertionError, subprocess.TimeoutExpired) as error:
            report['webvttNativeProbe'] = {'demuxed': False, 'error': str(error)[:300], 'scope': 'recorded failure; no WebVTT claim is made from FFmpeg'}

        # 4. Controls.
        literal = directory / 'literal-review'
        with Recording():
            literal_result = ffmpeg_adaptor.run({'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'review', 'filter': 'muxReview', 'options': {
                'video': str(video), 'audio': str(audio), 'captions': str(laid / 'captions.srt'), 'captionStatus': 'machineDraft', 'threads': 1}}]}, literal, executable=ffmpeg, timeout=120)
        assert literal_result['verified'] and file_digest(literal / 'review.mkv') == file_digest(review_dir / 'review.mkv'), 'literal-path and workflow-artifact movies differ'
        controls = {'literalPathMovieEqualsWorkflowArtifactMovie': True, 'movieSha256': file_digest(literal / 'review.mkv')}
        with Recording():
            reused = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=300, resume=True)
        assert reused['status'] == 'succeeded' and verified_workflow(directory / 'workflow', ffmpeg)
        controls['resume'] = {'status': reused['status'], 'jobs': [{k: j.get(k) for k in ('id', 'status', 'reused')} for j in reused['jobs']]}
        assert all(j.get('reused') is True for j in reused['jobs']), controls['resume']
        changed = inputs / 'changed-timed-text.json'; changed.write_bytes(source.read_bytes().replace(b'brown', b'brawn', 1)); assert sha256(changed) != pin
        stale_graph = graph_for(changed, pin, video, audio)
        stale = refused(lambda: workflow.execute(stale_graph, directory / 'stale-fresh', locations=locations, timeout=300), 'LAYOUT_SOURCE_STALE')
        assert not list((directory / 'stale-fresh').rglob('review.mkv')), 'a stale layout must not reach the movie'
        changed_in_place = directory / 'changed-in-place.json'; changed_in_place.write_bytes(source.read_bytes())
        resume_graph = graph_for(changed_in_place, pin, video, audio)
        with Recording(): workflow.execute(resume_graph, directory / 'stale-resume', locations=locations, timeout=300)
        changed_in_place.write_bytes(source.read_bytes().replace(b'brown', b'brawn', 1))
        stale_resume = refused(lambda: workflow.execute(resume_graph, directory / 'stale-resume', locations=locations, timeout=300, resume=True), 'LAYOUT_SOURCE_STALE')
        controls['changedSourceOldPin'] = {'fresh': stale['code'], 'resume': stale_resume['code'], 'location': stale['location'], 'movieReached': False}
        second = inputs / 'second-timed-text.json'; second.write_bytes(source_document(SECOND, audio)); second_pin = sha256(second); assert second_pin != pin
        with Recording():
            second_outcome = workflow.execute(graph_for(second, second_pin, video, audio), directory / 'second', locations=locations, timeout=300)
        assert second_outcome['status'] == 'succeeded' and verified_workflow(directory / 'second', ffmpeg)
        second_review = next((directory / 'second' / 'review').rglob('review.mkv')).parent
        second_laid = next((directory / 'second' / 'layout').rglob('captions.srt')).parent
        assert (second_laid / 'captions.srt').read_text(encoding='utf-8') == SECOND_SRT
        readback(probe_tool, ffmpeg, second_review / 'review.mkv', directory / 'independent-second', SECOND_SRT)
        controls['newSourceNewPin'] = {'sourceSha256': second_pin, 'extractedSubRipEqualsLiteral': True, 'movieDiffers': file_digest(second_review / 'review.mkv') != file_digest(review_dir / 'review.mkv')}
        report['controls'] = controls

        # 5. Consumer limits stay strict: the layout of a cue holding a backslash is refused by FFmpeg review, which this work does not loosen.
        backslash = inputs / 'backslash-timed-text.json'; backslash.write_bytes(source_document([(0, 900, 'Back\\slash words are accepted by layout'), (1000, 1950, 'but refused by the review movie')], audio))
        done = layout.run(layout_document(str(backslash), sha256(backslash), 24, 2), directory / 'backslash-layout', timeout=60); assert done['verified']
        with Recording():
            strict = refused(lambda: ffmpeg_adaptor.run({'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'review', 'filter': 'muxReview', 'options': {
                'video': str(video), 'audio': str(audio), 'captions': str(directory / 'backslash-layout' / 'captions.srt'), 'captionStatus': 'machineDraft', 'threads': 1}}]},
                directory / 'backslash-review', executable=ffmpeg, timeout=120), 'UNSUPPORTED_CAPTIONS')
        assert not (directory / 'backslash-review' / 'review.mkv').exists()
        report['consumerLimitsUnchanged'] = {'layoutAccepted': True, 'ffmpegReviewRefused': strict['code']}

        assert sha256(qualification) == qualification_before and layout.VERSION not in json.loads(qualification.read_text())['routes'], 'no qualification receipt may exist for the host-only route'
        assert {k: fingerprint(p) for k, p in (('ffmpeg', ffmpeg), ('ffprobe', probe_tool))} == binaries_before, 'a selected FFmpeg binary changed'
        report['binariesUnchanged'] = True
        if frozen:
            report['freezeAfter'] = freeze_state(); assert report['freezeAfter'] == frozen, 'owned source changed during the run'
        report['verified'] = True
    finally:
        natives = {os.path.realpath(ffmpeg), os.path.realpath(probe_tool)}
        for record in PROCESSES:
            seen = [o['exe'] for o in record['observations']]
            record['nativeExecutableObserved'] = any(os.path.realpath(e) in natives for e in seen)
        observed = [r for r in PROCESSES if r['observations']]; complete = [r for r in observed if r['observations'][-1]['environCount']]
        harness = [r for r in PROCESSES if r['source'].startswith('harness') and r['nativeExecutableObserved']]
        temporary = os.path.realpath(os.environ.get('TMPDIR') or '/tmp')
        def place(record):
            cwd = os.path.realpath(record['observations'][-1]['cwd'])
            return 'temporary directory under TMPDIR' if cwd.startswith(temporary + os.sep) else 'under the output directory' if cwd.startswith(str(directory) + os.sep) else 'elsewhere'
        count = lambda items: {str(k): v for k, v in sorted(Counter(items).items(), key=lambda kv: str(kv[0]))}
        report['nativeEnvironment'] = {
            'launchPath': 'harness: dispatch.SubprocessRunner starts a Python replay script that chdirs and execvpe-s the native command, so the native PID is the replay interpreter PID; direct qualifier runs exec the native directly',
            'processesRecorded': len(PROCESSES), 'harnessNativesObserved': len(harness), 'directNativesObserved': sum(r['nativeExecutableObserved'] for r in PROCESSES if r['source'].startswith('direct')),
            'notObserved': [{'pid': r['pid'], 'stage': r.get('stage'), 'exit': r['exit']} for r in PROCESSES if not r['nativeExecutableObserved']],
            'completeEnvironmentReads': len(complete), 'emptyEnvironmentReadsDuringExec': len(observed) - len(complete),
            'tmpdirPresentInEveryCompleteRead': all('TMPDIR' in r['observations'][-1]['environ'] for r in complete),
            'tmpdirValues': sorted({r['observations'][-1]['environ'].get('TMPDIR') for r in complete}),
            'ompNumThreadsInCompleteReads': count(r['observations'][-1]['environ'].get('OMP_NUM_THREADS') for r in complete),
            'workingDirectoryOfObservedHarnessNatives': count(place(r) for r in harness)}
        report['processes'] = PROCESSES; report['elapsedSeconds'] = round(time.monotonic() - started, 1)
        atomic_json(directory / 'caption-layout-acceptance.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'processes'}, indent=2, ensure_ascii=False))
    print('processes recorded:', len(PROCESSES), 'with an observed native executable:', sum(r['nativeExecutableObserved'] for r in PROCESSES))


if __name__ == '__main__':
    main()
