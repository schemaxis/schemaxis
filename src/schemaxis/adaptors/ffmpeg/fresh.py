"""Fresh native verification of encodeFrames, encodeSheet and encodeVideo publications.

The published bytes and the captured sources are held once, copied to a private directory, and decoded and probed again
by a trusted FFmpeg and its sibling ffprobe. Expectations come from the held captured PNG files (or a fresh native decode
of the captured video); retained readbacks, receipts and results are consistency diagnostics, never the decision."""
import hashlib
import shutil
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

from schemaxis.artifacts import file_digest
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.errors import fail
from schemaxis.native_command import execute
from . import review, video

MAX_PUBLICATION = 512 * 1024 * 1024
MAX_RGB = video.MAX_RGB
MAX_PROBE = 4 * 1024 * 1024
DEMUXER = {'h264': 'mov', 'ffv1': 'matroska'}
BUDGET = {'ffv1': 0, 'h264': 16}
# H.264 decode and swscale output may differ in the last bit between FFmpeg builds; a retained readback made by another build
# is accepted as consistent only within this per-frame mean error. The same build must reproduce the retained bytes exactly.
RUNTIME_DRIFT = 1.0
OPERATIONS = 'an encodeFrames, encodeSheet or encodeVideo publication'


def trusted(executable=None):
    """review.trusted with wording for these operations: explicit argument, configuration, environment; never PATH."""
    try:
        return review.trusted(executable)
    except SchemaxisError as error:
        fault = error.fault
        raise SchemaxisError(Fault(fault.code, fault.message.replace('a muxReview publication', OPERATIONS), fault.location,
                                   fault.phase, fault.retryable, fault.to_dict()['observed'], fault.recovery)) from None


def fresh_commands(paths, scratch, prepared, width, height):
    """Fixed fresh recipe for the private copy: local files only, forced container demuxer, no authored flags."""
    from . import adaptor as base
    options = prepared['nodes'][0]['options']
    demuxer = DEMUXER[options['codec']]
    published = str(scratch / prepared['output'])
    ffmpeg, ffprobe = paths['ffmpeg'], paths['ffprobe']
    reopen = ['-protocol_whitelist', 'file', '-f', demuxer]
    commands = base.native_commands(ffmpeg, scratch, prepared, width, height)
    commands['decode'] = commands['decode'][:commands['decode'].index('-filter_threads') + 2] + ['-threads', str(options['threads']), *reopen, '-i', published,
        '-map', '0:v:0', '-an', '-sn', '-dn', '-fps_mode', 'passthrough', '-fs', str(MAX_RGB + 1),
        '-f', 'rawvideo', '-pix_fmt', 'rgb24', str(scratch / 'decoded.rgb')]
    commands['probe'] = [ffprobe, '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', *reopen, published]
    commands[review.TIMELINE] = [ffprobe, '-v', 'error', '-select_streams', 'v:0', '-read_intervals', '%+#602', '-show_frames',
        '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', *reopen, published]
    return commands


def launcher(scratch, stage, command, name, limit):
    """Bind the stage to the digest of the exact file it opens, apply resource limits, then exec the fixed argv."""
    return ('import hashlib, json, os, resource, stat\nfrom pathlib import Path\n'
        + 'resource.setrlimit(resource.RLIMIT_AS, (2147483648,2147483648))\n'
        + f'resource.setrlimit(resource.RLIMIT_FSIZE, ({limit},)*2)\n'
        + f'path=Path({str(scratch / name)!r})\ncommand={command!r}\n'
        + 'if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode): raise ValueError("native input is not regular")\n'
        + 'digest=hashlib.sha256()\nwith path.open("rb") as stream:\n'
        + '    for block in iter(lambda:stream.read(1048576), b""): digest.update(block)\n'
        + f'Path({str(scratch / (stage + "-inputs.json"))!r}).write_text(json.dumps({{str(path):digest.hexdigest()}},sort_keys=True))\n'
        + 'os.execvpe(command[0],command,os.environ)\n')


def launch(scratch, stage, script, deadline, location):
    """One fixed launcher through the shared cancellable runner; a native failure on the held bytes means they do not verify."""
    path = scratch / (stage + '-launcher.py')
    path.write_text(script)
    try:
        execute([sys.executable, str(path)], scratch, stage, review.budget(stage, deadline))
        if stage.startswith('source-'):
            video.check_diagnostics(scratch, stage, location)
        else:
            review.quiet(scratch, stage)
    except SchemaxisError as error:
        if error.fault.code not in ('RUNNER_FAILED', 'INVALID_RESOURCE'):
            raise    # timeout, cancellation and unavailable-runtime faults keep their own codes
        fail('VERIFICATION_FAILED', 'fresh native %s of the retained bytes failed: %s' % (stage, error.fault.message), stage,
             cause=error.fault.to_dict())


def bound(scratch, stage, name, data):
    expected = {str(scratch / name): hashlib.sha256(data).hexdigest()}
    if not review.same_json(review.strict_json((scratch / (stage + '-inputs.json')).read_bytes(), stage + '-inputs.json'), expected):
        fail('VERIFICATION_FAILED', 'fresh native stage consumed different bytes than were verified', stage)


def read_output(scratch, name, limit):
    path = scratch / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        fail('VERIFICATION_FAILED', 'required bounded native readback is absent or oversized', name)
    return review.bounded_bytes(path, limit, name)


def compare_frames(expected, raw, codec):
    """Every decoded frame against the host-derived frame, in order; equal frames short-circuit, errors are per-frame means."""
    if len(raw) != sum(map(len, expected)):
        fail('VERIFICATION_FAILED', 'decoded frame count or dimensions differ from the captured source', stage='decode',
             expectedBytes=sum(map(len, expected)), decodedBytes=len(raw))
    view, offset, errors = memoryview(raw), 0, []
    for index, frame in enumerate(expected):
        actual = view[offset:offset + len(frame)]
        offset += len(frame)
        if actual == frame:
            errors.append(0.0)
            continue
        error = sum(abs(a - b) for a, b in zip(frame, actual)) / len(frame)
        if error > BUDGET[codec]:
            fail('VERIFICATION_FAILED', 'decoded video frame differs from the captured source frame beyond the fidelity budget',
                 stage='decode', frame=index, meanError=error, budget=BUDGET[codec])
        errors.append(error)
    return errors


def probe_view(probe):
    """The typed stream facts that retained and fresh probes must agree on."""
    stream, form = probe['streams'][0], probe['format']
    return {'codec': stream.get('codec_name'), 'pixelFormat': stream.get('pix_fmt'), 'width': stream.get('width'),
            'height': stream.get('height'), 'frames': stream.get('nb_read_frames'), 'rate': stream.get('avg_frame_rate'),
            'colorSpace': stream.get('color_space'), 'colorRange': stream.get('color_range'),
            'container': form.get('format_name'), 'streams': form.get('nb_streams')}


def observe(prepared, payloads, published, paths, deadline, tagged=True):
    """Decode and probe the held published bytes again. Returns facts; ``payloads`` are the held captured sources."""
    from . import adaptor as base
    node = prepared['nodes'][0]
    options = node['options']
    location = '$.nodes[0].options.file'
    scratch = Path(tempfile.mkdtemp(prefix='schemaxis-ffmpeg-fresh-'))
    try:
        (scratch / prepared['output']).write_bytes(published)
        execute([paths['ffmpeg'], '-version'], scratch, 'version', review.budget('version', deadline))
        identity = (scratch / 'version.stdout').read_text(errors='replace').splitlines()[:1]
        if not identity or not identity[0].startswith('ffmpeg version '):
            fail('UNSUPPORTED_RUNTIME', 'the trusted executable does not identify as FFmpeg', 'version', observed=identity[:1])
        facts = {'runtime': identity[0]}
        if node['filter'] == 'encodeVideo':
            (scratch / 'input-0000').write_bytes(payloads[0])
            recipe = video.commands(paths['ffmpeg'], scratch, prepared)
            for stage in ('source-probe', 'source-decode'):
                launch(scratch, stage, base.readback_launcher(scratch, prepared, stage, recipe[stage]), deadline, location)
                bound(scratch, stage, 'input-0000', payloads[0])
            if (scratch / 'source-probe.stdout').stat().st_size > video.MAX_PROBE:
                fail('RESOURCE_LIMIT', 'source probe exceeded byte budget', 'source-probe')
            width, height, pixels = video.read(scratch, prepared)
            facts['sourceDecodedSHA256'] = file_digest(scratch / 'source-decoded.rgb')
        else:
            width, height, pixels = base.frames(prepared, payloads)
        recipe = fresh_commands(paths, scratch, prepared, width, height)
        limits = {'probe': 8 * 1024 * 1024, review.TIMELINE: 8 * 1024 * 1024, 'decode': MAX_RGB + 4 * 1024 * 1024}
        for stage in ('probe', 'decode', review.TIMELINE):
            launch(scratch, stage, launcher(scratch, stage, recipe[stage], prepared['output'], limits[stage]), deadline, location)
            bound(scratch, stage, prepared['output'], published)
        probe = review.strict_json(read_output(scratch, 'probe.stdout', MAX_PROBE), 'probe.stdout')
        base.validate_probe(probe, width, height, len(pixels), options, tagged=tagged)
        review.check_timeline(review.strict_json(read_output(scratch, review.TIMELINE + '.stdout', MAX_PROBE),
                                                 review.TIMELINE + '.stdout'), len(pixels), Fraction(options['fps']))
        decoded = read_output(scratch, 'decoded.rgb', MAX_RGB)
        errors = compare_frames(pixels, decoded, options['codec'])
        facts.update(width=width, height=height, frames=len(pixels), fps=options['fps'], codec=options['codec'], errors=errors,
                     decodedSHA256=hashlib.sha256(decoded).hexdigest(), framesSHA256=hashlib.sha256(b''.join(pixels)).hexdigest(),
                     probe=probe_view(probe), duration=float(probe['format']['duration']), publication=hashlib.sha256(published).hexdigest())
        return facts
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def bind(retained, fresh, retained_probe, tagged):
    """Facts from the fresh observation must agree with the retained readbacks by exact type.

    The same FFmpeg build reproduces the retained decoded bytes exactly. Another build may differ in the last bit of an H.264
    to RGB conversion; then each frame must agree within RUNTIME_DRIFT and the decision still rests on the fresh observation."""
    same = retained['runtime'] == fresh['runtime']
    names = ['width', 'height', 'frames', 'fps', 'codec', 'publication']
    if abs(retained['duration'] - fresh['duration']) > 0.002:
        names.append('duration')
    differing = [name for name in names if name == 'duration' or not review.same_json(retained[name], fresh[name])]
    seen, now = probe_view(retained_probe), fresh['probe']
    if not tagged:
        seen, now = ({key: value for key, value in view.items() if not key.startswith('color')} for view in (seen, now))
    differing += ['probe.' + key for key in now if not review.same_json(seen[key], now[key])]
    if same:
        differing += [name for name in ('decodedSHA256', 'errors', 'framesSHA256')
                      if not review.same_json(retained[name], fresh[name])]
    else:
        close = (len(retained['errors']) == len(fresh['errors'])
                 and all(abs(a - b) <= RUNTIME_DRIFT for a, b in zip(retained['errors'], fresh['errors'])))
        differing += [] if close else ['errors']
    if 'sourceDecodedSHA256' in fresh and 'sourceDecodedSHA256' in retained and same:
        differing += [] if retained['sourceDecodedSHA256'] == fresh['sourceDecodedSHA256'] else ['sourceDecodedSHA256']
    if differing:
        fail('VERIFICATION_FAILED', 'fresh native facts differ from the retained readbacks: ' + ', '.join(sorted(set(differing))),
             stage='facts', differing=sorted(set(differing)))
