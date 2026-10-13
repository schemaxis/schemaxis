"""Bounded human-mediated UXP sequence observation, without project mutation."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import secrets
import stat
import sys
import time

from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys

VERSION = 'schemaxis.premiere/1'
TICKS = 254016000000
MAX_BYTES = 1024 * 1024
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}
OPTIONS = {
    'projectPath': TEXT,
    'sequenceName': {'type': 'string', 'minLength': 1, 'maxLength': 256, 'required': True},
    'fps': {'type': 'integer', 'minimum': 24, 'maximum': 60, 'default': 25},
    'width': {'type': 'integer', 'minimum': 2, 'maximum': 8192, 'default': 1920},
    'height': {'type': 'integer', 'minimum': 2, 'maximum': 8192, 'default': 1080},
    'clips': {'type': 'array', 'minItems': 1, 'maxItems': 128, 'required': True,
              'items': {'type': 'object', 'properties': {
                  'sourcePath': TEXT,
                  'startFrame': {'type': 'integer', 'minimum': 0, 'maximum': 1000000, 'default': 0},
                  'frameCount': {'type': 'integer', 'minimum': 1, 'maximum': 600, 'required': True}}}},
}
DECLARATIONS = {'sequenceContract': {'native': 'Premiere read-only UXP sequence observation',
                                    'kinds': ['sequenceObservation'], 'inputs': {},
                                    'options': {key: {'value': value} for key, value in OPTIONS.items()}}}
LOSSES = ['Experimental integration: no installed Premiere native acceptance has been recorded',
          'Read-only sequence structure and source identities; source bytes, effects, colour, audio and rendered pixels are not verified',
          'Two matching observations detect observed edits but are not an atomic transaction or cryptographic proof of application execution',
          'No project creation, save, rendering, export, workflow scheduling or automatic reuse']


def _absolute(value):
    return isinstance(value, str) and '\x00' not in value and (PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute())


def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    if document.get('operation') != 'sequenceContract': fail('UNKNOWN_OPERATION', 'select sequenceContract')
    options = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS}, location='$')
    if options['fps'] not in (24, 25, 30, 50, 60): fail('INVALID_RATE', 'select integer 24, 25, 30, 50 or 60 fps', '$.fps')
    for path in [options['projectPath'], *(clip['sourcePath'] for clip in options['clips'])]:
        if not _absolute(path): fail('INVALID_RESOURCE', 'native project/source identities must be absolute paths without NUL')
    if any(ord(c) < 32 for c in options['sequenceName']): fail('INVALID_SELECTION', 'sequence name contains control characters')
    count = 0
    tick = TICKS // options['fps']
    clips = []
    for clip in options['clips']:
        clips.append({'sourcePath': clip['sourcePath'], 'startTicks': str(count * tick),
                      'endTicks': str((count + clip['frameCount']) * tick),
                      'inTicks': str(clip['startFrame'] * tick),
                      'outTicks': str((clip['startFrame'] + clip['frameCount']) * tick),
                      'durationTicks': str(clip['frameCount'] * tick)})
        count += clip['frameCount']
    if count > 600: fail('RESOURCE_LIMIT', 'sequence contract exceeds 600 timeline frames')
    prepared = {'version': 'schemaxis.premiere.plan/1', 'operation': 'sequenceContract', 'options': options,
                'timebaseTicks': str(tick), 'endTicks': str(count * tick), 'frames': count, 'clips': clips, 'losses': LOSSES}
    if len(_encode(_request(prepared, 'f' * 32, 999999999999999))) > MAX_BYTES:
        fail('RESOURCE_LIMIT', 'encoded sequence request exceeds 1 MiB')
    return prepared


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    properties = {k: argument_schema(v) for k, v in OPTIONS.items()}
    properties['fps']['enum'] = [24, 25, 30, 50, 60]
    explanations = {'projectPath': 'Exact absolute path identity of the open saved Premiere project; its bytes are not read.',
                    'sequenceName': 'Exact name of the active sequence to inspect; no sequence is selected or modified.',
                    'fps': 'Integer sequence rate: 24, 25, 30, 50 or 60. Fractional/drop-frame rates are unsupported.',
                    'width': 'Expected sequence frame width; rendered dimensions are not inspected.',
                    'height': 'Expected sequence frame height; rendered dimensions are not inspected.',
                    'clips': 'Ordered contiguous clips on the sole unmuted video track, at zero-based timeline positions.'}
    for k, text in explanations.items(): properties[k]['description'] = text
    for k, text in {'sourcePath': 'Exact absolute native source path identity; no source-content readback.',
                    'startFrame': 'Zero-based source frame at the sequence timebase; default 0.',
                    'frameCount': 'Positive duration in sequence frames; out points are exclusive.'}.items():
        properties['clips']['items']['properties'][k]['description'] = text
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION, 'description': 'Experimental Premiere contract version.'},
          'operation': {'const': 'sequenceContract', 'description': 'Observe the active sequence through the supplied read-only UXP panel.'},
          **properties}, ['version', 'operation', 'projectPath', 'sequenceName', 'clips'])}


def _closed(value, members, where):
    if not isinstance(value, dict) or set(value) != set(members): fail('VERIFICATION_FAILED', 'closed observation fields differ', where)


def _text(value, where, limit=4096):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or '\x00' in value:
        fail('VERIFICATION_FAILED', 'bounded native identity is absent', where)


def _ticks(value, where):
    if not isinstance(value, str) or not re.fullmatch(r'0|[1-9][0-9]{0,18}', value):
        fail('VERIFICATION_FAILED', 'ticks must be canonical bounded nonnegative decimal strings', where)
    return int(value)


def _version(value, where):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,5}(?:\.[0-9]{1,8})?', value):
        fail('VERIFICATION_FAILED', 'native runtime version is absent or malformed', where)
    return tuple(map(int, value.split('.')))


def _observation(value, prepared):
    _closed(value, ('runtime', 'project', 'sequence', 'track', 'clips'), 'observation')
    runtime, project, sequence, track = (value[k] for k in ('runtime', 'project', 'sequence', 'track'))
    _closed(runtime, ('hostName', 'hostVersion', 'uxpVersion', 'applicationPath'), 'runtime')
    if runtime['hostName'] != 'premierepro': fail('VERIFICATION_FAILED', 'response does not identify Premiere Pro')
    if _version(runtime['hostVersion'], 'hostVersion') < (26, 5, 0): fail('UNSUPPORTED_RUNTIME', 'Premiere 26.5.0 or later is required')
    if not isinstance(runtime['uxpVersion'], str) or not re.fullmatch(r'(?:uxp-)?[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,5}(?:\.[0-9]{1,8})?(?:-[A-Za-z0-9.-]{1,64})?', runtime['uxpVersion']):
        fail('VERIFICATION_FAILED', 'native UXP runtime identity is absent or malformed')
    if not _absolute(runtime['applicationPath']): fail('VERIFICATION_FAILED', 'native application path identity is absent')
    _closed(project, ('name', 'path', 'guid'), 'project')
    for field in ('name', 'path', 'guid'): _text(project[field], 'project.' + field)
    options = prepared['options']
    if project['path'] != options['projectPath']: fail('CONTRACT_MISMATCH', 'active native project path differs')
    _closed(sequence, ('name', 'guid', 'width', 'height', 'timebaseTicks', 'zeroPointTicks', 'endTicks',
                       'videoTrackCount', 'audioTrackCount', 'captionTrackCount'), 'sequence')
    for field in ('name', 'guid'): _text(sequence[field], 'sequence.' + field)
    for field in ('width', 'height', 'videoTrackCount', 'audioTrackCount', 'captionTrackCount'):
        if type(sequence[field]) is not int: fail('VERIFICATION_FAILED', 'native count/dimension must be an integer', field)
    expected = {'name': options['sequenceName'], 'width': options['width'], 'height': options['height'],
                'timebaseTicks': prepared['timebaseTicks'], 'zeroPointTicks': '0', 'endTicks': prepared['endTicks'],
                'videoTrackCount': 1, 'captionTrackCount': 0}
    for k, expected_value in expected.items():
        if sequence[k] != expected_value: fail('CONTRACT_MISMATCH', 'native sequence differs', 'sequence.' + k)
    if not 0 <= sequence['audioTrackCount'] <= 8: fail('VERIFICATION_FAILED', 'native audio track count exceeds bound')
    for field in ('timebaseTicks', 'zeroPointTicks', 'endTicks'): _ticks(sequence[field], field)
    _closed(track, ('index', 'name', 'muted', 'audioClipCount', 'transitionCount'), 'track')
    _text(track['name'], 'track.name', 256)
    if type(track['index']) is not int or track['index'] != 0 or track['muted'] is not False:
        fail('CONTRACT_MISMATCH', 'sole video track must be index 0 and unmuted')
    for field in ('audioClipCount', 'transitionCount'):
        if type(track[field]) is not int or track[field] != 0: fail('CONTRACT_MISMATCH', 'audio clips and transitions are unsupported', field)
    clips = value['clips']
    if not isinstance(clips, list) or len(clips) != len(prepared['clips']): fail('CONTRACT_MISMATCH', 'native clip count differs')
    flags = ('disabled', 'adjustmentLayer', 'reversed', 'offline', 'nested', 'merged', 'multicam', 'proxy')
    identities = ('name', 'projectItemId')
    for i, (clip, expected_clip) in enumerate(zip(clips, prepared['clips'])):
        _closed(clip, (*expected_clip, *identities, *flags), 'clip.' + str(i))
        for field in identities: _text(clip[field], field)
        if any(clip[field] is not False for field in flags): fail('CONTRACT_MISMATCH', 'unsupported native clip state', str(i))
        for field, expected_value in expected_clip.items():
            if clip[field] != expected_value: fail('CONTRACT_MISMATCH', 'native clip source or range differs', str(i) + '.' + field)
        for field in ('startTicks', 'endTicks', 'inTicks', 'outTicks', 'durationTicks'): _ticks(clip[field], field)
    return value


def _bytes(path):
    path = Path(path)
    if path.is_symlink(): fail('VERIFICATION_FAILED', 'bridge/evidence file must not be a symlink', str(path))
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            status = os.fstat(stream.fileno())
            if not stat.S_ISREG(status.st_mode) or status.st_size > MAX_BYTES:
                fail('VERIFICATION_FAILED', 'bridge/evidence must be a bounded regular file', str(path))
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES: fail('VERIFICATION_FAILED', 'bridge/evidence byte bound exceeded')
        return data
    except (OSError, ValueError) as error: fail('VERIFICATION_FAILED', str(error), str(path))


def _json(path):
    try: return json.loads(_bytes(path))
    except (ValueError, UnicodeError) as error: fail('VERIFICATION_FAILED', 'malformed retained JSON: ' + str(error), str(path))


def _request(prepared, nonce, expiry):
    return {'version': 'schemaxis.premiere.request/1', 'operation': 'sequenceContract', 'nonce': nonce,
            'expiresAtMs': expiry, 'responseFile': 'response-' + nonce + '.json',
            'contract': prepared}


def _encode(value):
    return (json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')


def _response(response, request, request_data):
    _closed(response, ('version', 'nonce', 'requestSHA256', 'status', 'observation'), 'response')
    if response['version'] != 'schemaxis.premiere.response/1' or response['nonce'] != request['nonce']:
        fail('VERIFICATION_FAILED', 'response contract or attempt nonce differs')
    if response['requestSHA256'] != hashlib.sha256(request_data).hexdigest(): fail('VERIFICATION_FAILED', 'response consumed a different request')
    if response['status'] != 'observed': fail('VERIFICATION_FAILED', 'native observation did not complete')
    return _observation(response['observation'], request['contract'])


def _receipt(directory, prepared):
    request_data = _bytes(directory / 'request.json')
    request = _json(directory / 'request.json')
    _closed(request, ('version', 'operation', 'nonce', 'expiresAtMs', 'responseFile', 'contract'), 'request')
    if not isinstance(request['nonce'], str) or not re.fullmatch('[0-9a-f]{32}', request['nonce']): fail('VERIFICATION_FAILED', 'attempt nonce is absent')
    if type(request['expiresAtMs']) is not int or not 1 <= request['expiresAtMs'] < 10**15: fail('VERIFICATION_FAILED', 'bounded request deadline is absent')
    if request != _request(prepared, request['nonce'], request['expiresAtMs']) or request_data != _encode(request):
        fail('VERIFICATION_FAILED', 'trusted request differs from authored sequence contract')
    observation = _response(_json(directory / 'response.json'), request, request_data)
    if _json(directory / 'observation.json') != observation: fail('VERIFICATION_FAILED', 'published native observation differs')
    return {'artifacts': [{'file': str(directory / 'observation.json'), 'kind': 'sequenceObservation',
                          'format': 'Premiere UXP JSON observation', 'sha256': file_digest(directory / 'observation.json')}],
            'requestSHA256': hashlib.sha256(request_data).hexdigest(), 'responseSHA256': file_digest(directory / 'response.json'),
            'runtime': observation['runtime'], 'frames': prepared['frames'], 'losses': LOSSES}


def run(document, directory, *, bridge=None, executable=None, timeout=300):
    prepared = plan(document)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS', 'use a fresh attempt directory', str(directory))
    directory.mkdir(parents=True, exist_ok=False)
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', prepared)
    atomic_json(directory / 'result.json', {'status': 'running', 'verified': False})
    try:
        if sys.platform not in ('win32', 'darwin'): fail('NATIVE_ENVIRONMENT_UNAVAILABLE', 'Premiere Pro UXP requires a Windows or macOS host with Premiere 26.5+ installed')
        if executable is not None: fail('INVALID_EXECUTION', 'this route uses a selected UXP job folder, not an executable command')
        if type(timeout) not in (int, float) or not 0 < timeout <= 3600: fail('INVALID_TIMEOUT', 'bridge timeout must be positive and at most 3600 seconds')
        if not isinstance(bridge, (str, Path)) or not Path(bridge).is_absolute(): fail('BRIDGE_NOT_CONFIGURED', 'set --premiere-bridge to an existing private job directory')
        root = Path(bridge)
        if root.is_symlink() or not root.is_dir(): fail('INVALID_RESOURCE', 'bridge root must be a real existing directory')
        nonce = secrets.token_hex(16)
        job = root / ('schemaxis-premiere-' + nonce)
        job.mkdir(mode=0o700)
        deadline = time.monotonic() + timeout
        request = _request(prepared, nonce, int((time.time() + timeout) * 1000))
        request_data = _encode(request)
        (directory / 'request.json').write_bytes(request_data)
        (job / 'request.json').write_bytes(request_data)
        atomic_json(directory / 'bridge-job.json', {'jobDirectory': str(job), 'responseFile': request['responseFile'], 'nonce': nonce})
        response_path = job / request['responseFile']
        while True:
            if cancellation_requested(): fail('RUNNER_CANCELLED', 'Premiere observation cancelled')
            if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'Premiere panel did not finish before the shared deadline')
            if response_path.exists() or response_path.is_symlink(): break
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        response_data = _bytes(response_path)
        (directory / 'response.json').write_bytes(response_data)
        observation = _response(_json(directory / 'response.json'), request, request_data)
        atomic_json(directory / 'observation.json', observation)
        atomic_json(directory / 'verification.json', _receipt(directory, prepared))
        verify(directory, require_result=False)
        if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'Premiere observation verification exceeded the shared deadline')
        if cancellation_requested(): fail('RUNNER_CANCELLED', 'Premiere observation cancelled')
        result = {'status': 'succeeded', 'verified': True, 'artifacts': 1, 'observation': str(directory / 'observation.json')}
        atomic_json(directory / 'result.json', result)
        return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED', str(error), str(directory))
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        prepared = plan(_json(directory / 'authored.json'))
        result = _json(directory / 'result.json')
        if not isinstance(result, dict): fail('VERIFICATION_FAILED', 'retained result must be an object')
        if require_result and (result.get('status') != 'succeeded' or result.get('verified') is not True):
            fail('INCOMPLETE_EXECUTION', 'Premiere observation did not complete')
        if _json(directory / 'plan.json') != prepared: fail('VERIFICATION_FAILED', 'sequence plan differs')
        receipt = _receipt(directory, prepared)
        if _json(directory / 'verification.json') != receipt: fail('VERIFICATION_FAILED', 'native observation verification evidence differs')
        return {'verified': True, 'artifacts': 1, 'frames': prepared['frames'], 'runtime': receipt['runtime']}
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        fail('VERIFICATION_FAILED', 'malformed retained observation: ' + str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
