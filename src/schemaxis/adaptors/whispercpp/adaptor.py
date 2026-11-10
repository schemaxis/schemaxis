"""Bounded offline transcription: whisper.cpp runs natively, the host rechecks its evidence.

The native CLI is untrusted. Its JSON is parsed as a closed, strict contract; segments,
captions and text are generated from that independently checked evidence. Hashes and
structure never certify recognition accuracy, so every result carries a review warning.
"""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import time
import unicodedata
import wave

from schemaxis.adaptors.whispercpp import caption_review, languages, segmentation
from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.whispercpp/1'
RATE = 16000
AUDIO_LIMIT = 32 * 1024 * 1024
MAX_SECONDS = 600
MODEL_LIMIT = 4 * 1024 ** 3
RUNTIME_FILE_LIMIT = 1024 ** 3
MAX_RUNTIME_FILES = 64
JSON_LIMIT = 4 * 1024 * 1024
LOG_LIMIT = 4 * 1024 * 1024
MAX_SEGMENTS = 2000
MAX_SEGMENT_CHARACTERS = 1000
MAX_TOTAL_CHARACTERS = 262144
SLACK_MS = 0
RUNTIME = re.compile(r'whisper\.cpp version: (1\.9\.5(?:-dev)?)\n')
HEX = re.compile(r'[0-9a-f]{64}')
# Code points that draw nothing on their own: a cue made only of these reads as blank. Cn (unassigned) is
# deliberately not listed; newly assigned Unicode categories can still differ between hosts.
INVISIBLE = frozenset('\u115f\u1160\u3164\uffa0\u2800')
INVISIBLE_CATEGORIES = frozenset(('Cc', 'Cf', 'Cs', 'Co', 'Zs', 'Zl', 'Zp', 'Mn', 'Mc', 'Me'))
CLOCK = re.compile(r'([0-9]{2,}):([0-5][0-9]):([0-5][0-9])([,.])([0-9]{3})')
SHA = {'type': 'string', 'minLength': 64, 'maxLength': 64}
PATH = {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}
OPTIONS = {
    'audio': {'type': 'object', 'required': True, 'properties': {'path': PATH, 'sha256': SHA}},
    'model': {'type': 'object', 'required': True, 'properties': {'path': PATH, 'sha256': {**SHA, 'required': True}}},
    'language': {'type': 'enum', 'values': list(languages.CODES), 'default': languages.DEFAULT},
    'captionReview': {'type': 'boolean', 'default': False},
    segmentation.OPTION: {'type': 'integer', 'minimum': segmentation.MINIMUM, 'maximum': segmentation.MAXIMUM}}
DECLARATIONS = {'transcribe': {
    'native': 'whisper-cli -m MODEL -f audio.wav -l LANGUAGE -t 1 -p 1 -ng -oj -osrt [-ml MAXSEGMENTLENGTH -sow] -of native',
    'kinds': ['file', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
STAGES = ('version', 'libraries', 'transcribe')
REVIEW = ('Automatic speech recognition output is not certified. Hashes, strict structure, timing bounds and exact '
          'file agreement prove only that these files were derived consistently from the recorded native run; '
          'a person must review the transcript and captions against the audio before relying on them.')
LOSSES = [
    'Local little-endian PCM16 mono 16000 Hz WAV only, at most 32MiB and 600 seconds; no resampling, channel mixing, compressed audio, streams or remote sources.',
    'Explicit local ggml model pinned by SHA-256 (at most 4GiB). Models are never downloaded, copied or selected by this adaptor; model bytes are hashed before and after the native run. Later verification checks retained bindings, not external model bytes or recognition accuracy.',
    'Native CPU, one thread, one processor, default decoding, no prompt, translation, diarisation, VAD, grammar, language detection or authored native flags. Output is whisper.cpp 1.9.5 observed behaviour only.',
    'Segments are integral-millisecond [startMs,endMs) intervals with UTF-8 text; non-increasing, overlapping, empty, control-character or beyond-audio-duration results are refused, never repaired.',
    'Word timestamps, confidence, speaker labels and text normalisation are not produced. Recognition accuracy, language identification and caption readability are not certified.']


def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    if document.get('operation') != 'transcribe': fail('UNKNOWN_OPERATION', 'select transcribe')
    # Earliest admission: an authored language is checked before any other argument so a wrong type, null or unsupported code is cheap and located at $.language.
    if 'language' in document: languages.admit(document['language'])
    p = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS})
    for name, suffix, code in (('audio', '.wav', 'INVALID_AUDIO_SOURCE'), ('model', '.bin', 'INVALID_MODEL')):
        path = p[name]['path'];at = f'$.{name}.path'
        if '\0' in path or not path.startswith('/') or '..' in Path(path).parts or Path(path).suffix.lower() != suffix:
            fail(code, f'select an absolute local {suffix} path without parent references', at)
    if p['audio']['path'] == p['model']['path']: fail('INVALID_MODEL', 'audio and model must be different files', '$.model.path')
    for name in ('audio', 'model'):
        if 'sha256' in p[name] and not HEX.fullmatch(p[name]['sha256']):
            fail('INVALID_SHA256', 'use 64 lowercase hexadecimal digits', f'$.{name}.sha256')
    # An unauthored captionReview stays out of the plan, so documents without the option keep their exact plan bytes.
    # maxSegmentLength has no default and is likewise present only when authored.
    if 'captionReview' not in document: p.pop('captionReview')
    return {'version': 'schemaxis.whispercpp.plan/1', 'operation': 'transcribe', **p, 'losses': plan_losses(p)}


def plan_losses(p):
    """The five original losses, then one per authored option, so plans without options keep their exact bytes."""
    return [*LOSSES, *([caption_review.LOSS] if wants_review(p) else []), *segmentation.losses(p)]


def wants_review(p): return p.get('captionReview') is True


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, 'operation': {'const': 'transcribe'},
        **{k: argument_schema(v) for k, v in OPTIONS.items()}}, ['version', 'operation', 'audio', 'model'])}


def query(document): plan(document);return ['transcribe'], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1: fail('INVALID_EXECUTION', 'transcription runs one serial native thread', identity)
    return {'threads': 1}


def bounded(path, code='VERIFICATION_FAILED', limit=JSON_LIMIT, follow=False):
    try:
        fd = os.open(path, os.O_RDONLY | (0 if follow else getattr(os, 'O_NOFOLLOW', 0)) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit: raise ValueError('not a bounded regular file')
            data = stream.read(limit + 1)
        if len(data) > limit: raise ValueError('file byte budget exceeded')
        return data
    except (OSError, ValueError) as error: fail(code, 'select an intact regular file within the byte budget: ' + str(error), str(path))


def stream_digest(path, limit, code, follow=True, checkpoint=None):
    """Hash through one open descriptor; the identity records what was actually read."""
    try:
        fd = os.open(path, os.O_RDONLY | (0 if follow else getattr(os, 'O_NOFOLLOW', 0)) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit: raise ValueError('not a bounded regular file')
            digest = hashlib.sha256();count = 0
            for block in iter(lambda: stream.read(1 << 20), b''):
                if checkpoint: checkpoint()
                count += len(block)
                if count > limit: raise ValueError('byte budget exceeded')
                digest.update(block)
            after = os.fstat(stream.fileno())
        if count != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError('file changed while it was read')
        return {'sha256': digest.hexdigest(), 'bytes': count, 'device': before.st_dev, 'inode': before.st_ino, 'mtimeNs': before.st_mtime_ns}
    except (OSError, ValueError) as error: fail(code, 'select an intact regular file within the byte budget: ' + str(error), str(path))


def audio_info(data, code='INVALID_AUDIO_DATA', at='$.audio.path'):
    """Strict RIFF inspection precedes independent wave/struct decoding."""
    try:
        if len(data) < 44 or data[:4] != b'RIFF' or data[8:12] != b'WAVE' or struct.unpack_from('<I', data, 4)[0] + 8 != len(data): raise ValueError('RIFF size/header mismatch')
        chunks = {};offset = 12
        while offset < len(data):
            if offset + 8 > len(data): raise ValueError('truncated chunk header')
            name = data[offset:offset + 4];size = struct.unpack_from('<I', data, offset + 4)[0];end = offset + 8 + size
            if end + (size & 1) > len(data) or name in chunks: raise ValueError('duplicate or truncated chunk')
            if name not in (b'fmt ', b'data', b'LIST', b'JUNK'): raise ValueError('unsupported WAV chunk')
            chunks[name] = data[offset + 8:end];offset = end + (size & 1)
        if b'fmt ' not in chunks or b'data' not in chunks or len(chunks[b'fmt ']) != 16: raise ValueError('canonical 16-byte PCM fmt and data required')
        encoding, channels, rate, byte_rate, align, bits = struct.unpack('<HHIIHH', chunks[b'fmt '])
        if (encoding, channels, rate, bits, align, byte_rate) != (1, 1, RATE, 16, 2, 2 * RATE): raise ValueError('require PCM16 mono 16000 Hz')
        if not chunks[b'data'] or len(chunks[b'data']) % 2: raise ValueError('nonempty integral sample frames required')
        with wave.open(io.BytesIO(data), 'rb') as stream:
            if stream.getnframes() * 2 != len(chunks[b'data']) or stream.readframes(stream.getnframes() + 1) != chunks[b'data']: raise ValueError('WAV decoder/data mismatch')
        frames = len(chunks[b'data']) // 2
        if frames > MAX_SECONDS * RATE: fail('AUDIO_RESOURCE_LIMIT', f'audio exceeds {MAX_SECONDS} seconds', at)
        return {'rate': rate, 'channels': channels, 'frames': frames, 'bytes': len(data)}
    except (ValueError, struct.error, wave.Error, EOFError) as error: fail(code, 'use canonical PCM16 mono 16000 Hz WAV: ' + str(error), at)


def audio_capture(p, loader, at='$.audio.path'):
    data = loader()
    info = audio_info(data, at=at)
    sha = hashlib.sha256(data).hexdigest()
    if 'sha256' in p['audio'] and p['audio']['sha256'] != sha: fail('AUDIO_HASH_MISMATCH', 'audio bytes differ from the pinned sha256', at, observed=sha)
    return data, sha, info


def reusableInputs(document):
    p = plan(document)
    data, sha, _ = audio_capture(p, lambda: bounded(p['audio']['path'], 'INVALID_AUDIO_SOURCE', AUDIO_LIMIT))
    model = stream_digest(p['model']['path'], MODEL_LIMIT, 'INVALID_MODEL')
    return {'audio': sha, 'model': model['sha256']}


def commands(executable, p):
    return {'version': [executable, '--version'], 'libraries': [executable, '--version'],
        'transcribe': [executable, '-m', '@MODEL@', '-f', 'captured-audio.wav', '-l', p['language'], '-t', '1', '-p', '1', '-ng', '-oj', '-osrt', *segmentation.native_arguments(p), '-of', 'native']}


def stage_inputs(stage): return ['captured-audio.wav'] if stage == 'transcribe' else []


def launcher(directory, stage, command, p):
    """Trusted launcher: binds inputs, then passes the hashed model descriptor, never a mutable path."""
    model = {'path': p['model']['path'], 'sha256': p['model']['sha256'], 'limit': MODEL_LIMIT} if stage == 'transcribe' else None
    environment = {'LANG': 'C.UTF-8', 'OMP_NUM_THREADS': '1', **({'LD_TRACE_LOADED_OBJECTS': '1'} if stage == 'libraries' else {})}
    return ('import hashlib,json,os,resource,stat\nfrom pathlib import Path\n'
        + f'command={command!r}\npaths={[str(directory / n) for n in stage_inputs(stage)]!r}\nmodel={model!r}\nenvironment={environment!r}\nbindings={{"files":{{}}}}\n'
        + 'resource.setrlimit(resource.RLIMIT_CPU,(3600,3600))\nresource.setrlimit(resource.RLIMIT_FSIZE,(16777216,16777216))\nresource.setrlimit(resource.RLIMIT_AS,(17179869184,17179869184))\nresource.setrlimit(resource.RLIMIT_CORE,(0,0))\n'
        + 'def digest(fd,limit):\n    with os.fdopen(os.dup(fd),"rb") as stream:\n        info=os.fstat(stream.fileno())\n'
        + '        if not stat.S_ISREG(info.st_mode) or info.st_size>limit: raise ValueError("invalid native input")\n'
        + '        h=hashlib.sha256();count=0\n        for block in iter(lambda:stream.read(1<<20),b""):\n            count+=len(block);h.update(block)\n'
        + '        if count!=info.st_size: raise ValueError("native input changed while read")\n    return h.hexdigest(),count\n'
        + f'for name in paths:\n    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n    bindings["files"][name]=digest(fd,{AUDIO_LIMIT})[0];os.close(fd)\n'
        + 'if model:\n    fd=os.open(model["path"],os.O_RDONLY|getattr(os,"O_NONBLOCK",0))\n    sha,count=digest(fd,model["limit"])\n'
        + '    if sha!=model["sha256"]: raise ValueError("model bytes differ from the pinned sha256")\n    os.set_inheritable(fd,True)\n    bindings["model"]={"sha256":sha,"bytes":count}\n'
        + '    command=[f"/proc/self/fd/{fd}" if item=="@MODEL@" else item for item in command]\n'
        + 'bindings["ldLibraryPath"]=os.environ.get("LD_LIBRARY_PATH")\n'
        + f'Path({str(directory / (stage + "-inputs.json"))!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
        + 'env=dict(environment)\nif bindings["ldLibraryPath"] is not None: env["LD_LIBRARY_PATH"]=bindings["ldLibraryPath"]\n'
        + 'os.execve(command[0],command,env)\n')


def qualified_runtime(directory, code='UNSUPPORTED_NATIVE_VERSION'):
    text = bounded(directory / 'version.stdout', code, LOG_LIMIT).decode('utf-8', 'replace')
    match = RUNTIME.fullmatch(text)
    if not match: fail(code, 'configure the qualified whisper.cpp 1.9.5 whisper-cli executable', 'version', observed=text[:200])
    return 'whisper.cpp ' + match.group(1)


def read(directory, name): return strict_json(bounded(directory / name), name, code='VERIFICATION_FAILED')
def digest(directory, name): return hashlib.sha256(bounded(directory / name, limit=AUDIO_LIMIT)).hexdigest()


def library_paths(directory):
    """Dependencies as resolved by the dynamic loader's own trace of the same executable."""
    found = []
    for line in bounded(directory / 'libraries.stdout', 'VERIFICATION_FAILED', LOG_LIMIT).decode('utf-8', 'replace').splitlines():
        line = line.strip()
        if not line or line.startswith('linux-vdso') or line.startswith('statically linked'): continue
        match = re.fullmatch(r'(\S+) => (/.+?) \(0x[0-9a-f]+\)', line) or re.fullmatch(r'()(/.+?) \(0x[0-9a-f]+\)', line)
        if not match: fail('RUNTIME_UNRESOLVED', 'dynamic dependency cannot be resolved to a local file', 'libraries', observed=line[:200])
        found.append((match.group(1) or Path(match.group(2)).name, match.group(2)))
    if len(found) > MAX_RUNTIME_FILES: fail('RUNTIME_RESOURCE_LIMIT', 'too many dynamic dependencies', 'libraries')
    return sorted(found)


def runtime_identity(directory, executable, checkpoint=None):
    files = [{'name': 'whisper-cli', 'path': executable}, *({'name': n, 'path': q} for n, q in library_paths(directory))]
    for item in files: item.update({k: v for k, v in stream_digest(item['path'], RUNTIME_FILE_LIMIT, 'RUNTIME_RESOURCE_LIMIT', checkpoint=checkpoint).items() if k in ('sha256', 'bytes')})
    return files


def strict_json(data, at, code='TRANSCRIPT_INVALID'):
    def pairs(items):
        if len({k for k, _ in items}) != len(items): raise ValueError('duplicate JSON key')
        return dict(items)
    def constant(name): raise ValueError('non-finite JSON number ' + name)
    try:
        text = data.decode('utf-8')
        if text.startswith('﻿'): raise ValueError('byte-order mark')
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as error: fail(code, 'evidence is not strict UTF-8 JSON: ' + str(error), at)


def clock(ms, separator):
    return '%02d:%02d:%02d%s%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, separator, ms % 1000)


def whole(value): return type(value) is int


def closed(value, names, at):
    if not isinstance(value, dict) or set(value) != set(names): fail('TRANSCRIPT_INVALID', 'native JSON has an unexpected member set', at, expected=sorted(names))
    return value


def not_text(c):
    code = ord(c)
    return unicodedata.category(c) == 'Co' or 0xfdd0 <= code <= 0xfdef or code & 0xfffe == 0xfffe


def blank_cue_problem(text):
    """Why checked cue text cannot be published, or None. Formatting characters stay legal inside visible text (emoji sequences)."""
    if all(c in INVISIBLE or not_text(c) or unicodedata.category(c) in INVISIBLE_CATEGORIES for c in text):
        return 'segment text has no visible character (only spaces, joiners, format controls, fillers, combining marks or nonstandard standalone code points); a blank-looking caption is not published'
    return None


def native_segments(raw, p, frames):
    """Closed whisper.cpp JSON contract to checked integral-millisecond segments."""
    root = closed(raw, ('systeminfo', 'model', 'params', 'result', 'transcription'), '$')
    model = closed(root['model'], ('type', 'multilingual', 'vocab', 'audio', 'text', 'mels', 'ftype'), '$.model')
    if not isinstance(model['type'], str) or not isinstance(model['multilingual'], bool) or not all(whole(model[k]) and model[k] > 0 for k in ('vocab', 'mels')) or not whole(model['ftype']):
        fail('TRANSCRIPT_INVALID', 'native model description has invalid values', '$.model')
    for part in ('audio', 'text'):
        if not all(whole(v) and v > 0 for v in closed(model[part], ('ctx', 'state', 'head', 'layer'), '$.model.' + part).values()): fail('TRANSCRIPT_INVALID', 'native model dimensions must be positive integers', '$.model.' + part)
    params = closed(root['params'], ('model', 'language', 'translate'), '$.params')
    if not isinstance(params['model'], str) or not re.fullmatch(r'/proc/self/fd/[0-9]+', params['model']): fail('TRANSCRIPT_INVALID', 'native run did not load the hashed model descriptor', '$.params.model')
    if params['language'] != p['language'] or params['translate'] is not False: fail('TRANSCRIPT_INVALID', 'native language/translation parameters differ from the plan', '$.params')
    if closed(root['result'], ('language',), '$.result')['language'] != p['language']: fail('TRANSCRIPT_INVALID', 'native detected/used language differs from the authored language', '$.result.language')
    if not isinstance(root['systeminfo'], str): fail('TRANSCRIPT_INVALID', 'systeminfo must be text', '$.systeminfo')
    items = root['transcription']
    if not isinstance(items, list): fail('TRANSCRIPT_INVALID', 'transcription must be an array', '$.transcription')
    if not items: fail('TRANSCRIPT_EMPTY', 'native run reported no speech segments; no empty captions are published', '$.transcription')
    if len(items) > MAX_SEGMENTS: fail('TRANSCRIPT_RESOURCE_LIMIT', f'more than {MAX_SEGMENTS} segments', '$.transcription')
    limit = (frames * 1000 + RATE - 1) // RATE + SLACK_MS
    segments = [];previous = 0;total = 0
    for i, item in enumerate(items):
        at = f'$.transcription[{i}]'
        item = closed(item, ('timestamps', 'offsets', 'text'), at)
        stamps = closed(item['timestamps'], ('from', 'to'), at + '.timestamps');offsets = closed(item['offsets'], ('from', 'to'), at + '.offsets')
        values = []
        for side in ('from', 'to'):
            ms = offsets[side]
            if not whole(ms) or not 0 <= ms <= limit: fail('TRANSCRIPT_TIMING', 'timestamp must be an integer millisecond count within the audio duration', f'{at}.offsets.{side}', observed=ms, limitMs=limit)
            if not isinstance(stamps[side], str) or not CLOCK.fullmatch(stamps[side]) or stamps[side] != clock(ms, ','): fail('TRANSCRIPT_TIMING', 'timestamp text disagrees with integer offset', f'{at}.timestamps.{side}')
            values.append(ms)
        start, end = values
        if end <= start: fail('TRANSCRIPT_TIMING', 'segment must have positive duration', at, startMs=start, endMs=end)
        if start < previous: fail('TRANSCRIPT_TIMING', 'segments must be ordered and nonoverlapping', at, startMs=start, previousEndMs=previous)
        raw_text = item['text']
        if not isinstance(raw_text, str): fail('TRANSCRIPT_INVALID', 'segment text must be a string', at + '.text')
        text = raw_text.strip(' ')
        total += len(text)
        if not text or len(text) > MAX_SEGMENT_CHARACTERS or total > MAX_TOTAL_CHARACTERS: fail('TRANSCRIPT_INVALID', 'segment text must be nonempty and within the character budget', at + '.text')
        if any(c in text for c in '<>{}') or any(c in text for c in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069') or '-->' in text or '�' in text or any(unicodedata.category(c) in ('Cc', 'Cs', 'Zl', 'Zp') for c in text) or text != text.strip(): fail('TRANSCRIPT_INVALID', 'segment text contains control, replacement, line-separator or subtitle markup, bidirectional overrides/isolates or caption-marker characters', at + '.text')
        try: text.encode('utf-8')
        except UnicodeEncodeError: fail('TRANSCRIPT_INVALID', 'segment text is not valid Unicode scalar text', at + '.text')
        problem = blank_cue_problem(text)
        if problem: raise SchemaxisError(Fault('TRANSCRIPT_INVALID', problem, at + '.text', 'pipeline', observed={'cue': i, 'codePoints': ['U+%04X' % ord(c) for c in text[:8]]},
            recovery='inspect native.json for this cue; transcribe a cleaner or trimmed recording or choose another pinned model. Blank and non-text cues are never repaired, dropped or published.'))
        segments.append({'index': i, 'startMs': start, 'endMs': end, 'text': text, '_raw': raw_text});previous = end
    return segments


def native_srt(segments):
    """Native SRT is reconstructed from its own JSON values for an independent byte comparison."""
    return ''.join(f"{s['index'] + 1}\n{clock(s['startMs'], ',')} --> {clock(s['endMs'], ',')}\n{s['_raw']}\n\n" for s in segments)


def srt(segments): return ''.join(f"{s['index'] + 1}\n{clock(s['startMs'], ',')} --> {clock(s['endMs'], ',')}\n{s['text']}\n\n" for s in segments)


def vtt(segments):
    escape = lambda t: t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return 'WEBVTT\n\n' + ''.join(f"{clock(s['startMs'], '.')} --> {clock(s['endMs'], '.')}\n{escape(s['text'])}\n\n" for s in segments)


def transcript(segments): return ''.join(s['text'] + '\n' for s in segments)


def segment_document(p, segments, audio_sha, info, model_sha, model_bytes, native_sha):
    document = {'version': 'schemaxis.whispercpp.segments/1', 'language': p['language'], 'timeUnit': 'millisecond',
        'audio': {'sha256': audio_sha, 'bytes': info['bytes'], 'frames': info['frames'], 'rate': info['rate'], 'channels': info['channels'],
                  'durationMs': info['frames'] * 1000 // info['rate'], 'durationRemainderFrames': info['frames'] * 1000 % info['rate']},
        'model': {'sha256': model_sha, 'bytes': model_bytes}, 'nativeJsonSha256': native_sha,
        'segmentCount': len(segments), 'segments': [{k: s[k] for k in ('index', 'startMs', 'endMs', 'text')} for s in segments],
        'review': {'accuracyCertified': False, 'humanReviewRequired': True, 'statement': REVIEW, 'policy': {
            'timing': f'integral milliseconds; 0 <= start < end; start >= previous end; end <= ceil(audio ms)',
            'text': 'UTF-8; surrounding spaces removed; no control, line-separator, replacement or subtitle markup, bidirectional overrides/isolates or caption-marker characters'}}}
    observed = segmentation.observe(p, document['segments'])
    # The member exists only when maxSegmentLength was authored; every other document keeps its exact bytes.
    if observed: document['segmentation'] = observed
    return document


def outputs(document):
    segments = document['segments']
    return {'segments.json': None, 'transcript.txt': transcript(segments), 'captions.srt': srt(segments), 'captions.vtt': vtt(segments)}


def encode_json(value): return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')


def review_document(document):
    """Optional caption review bound to the canonical segment bytes it was derived from."""
    return caption_review.build(document, hashlib.sha256(encode_json(document)).hexdigest())


def write_outputs(directory, document, review=False):
    (directory / 'segments.json').write_bytes(encode_json(document))
    for name, text in outputs(document).items():
        if text is not None: (directory / name).write_bytes(text.encode('utf-8'))
    if review: (directory / caption_review.FILE).write_bytes(encode_json(review_document(document)))


def inspect(directory, p):
    """Recompute all publications from independent evidence; no receipt value is trusted."""
    data = bounded(directory / 'captured-audio.wav', limit=AUDIO_LIMIT);info = audio_info(data, 'VERIFICATION_FAILED')
    audio_sha = hashlib.sha256(data).hexdigest()
    if 'sha256' in p['audio'] and p['audio']['sha256'] != audio_sha: fail('VERIFICATION_FAILED', 'captured audio differs from the pinned sha256')
    model = read(directory, 'model.json')
    if (set(model) != {'path', 'sha256', 'bytes', 'device', 'inode', 'mtimeNs', 'after'} or model['sha256'] != p['model']['sha256'] or model['path'] != p['model']['path']
            or model['after'] != {k: model[k] for k in ('sha256', 'bytes', 'device', 'inode', 'mtimeNs')}): fail('VERIFICATION_FAILED', 'model identity changed or differs from the pin')
    if not all(whole(model[k]) and model[k]>=0 for k in ('device','inode')) or not whole(model['mtimeNs']) or not whole(model['bytes']) or not 0<model['bytes']<=MODEL_LIMIT:
        fail('VERIFICATION_FAILED','retained model identity has invalid numeric fields')
    if not same_json(model['after'],{k:model[k] for k in ('sha256','bytes','device','inode','mtimeNs')}): fail('VERIFICATION_FAILED','retained model identity types differ')
    native = bounded(directory / 'native.json', 'VERIFICATION_FAILED')
    segments = native_segments(strict_json(native, 'native.json'), p, info['frames'])
    if bounded(directory / 'native.srt', 'VERIFICATION_FAILED').decode('utf-8') != native_srt(segments): fail('VERIFICATION_FAILED', 'native SRT disagrees with native JSON segments', 'native.srt')
    return segment_document(p, segments, audio_sha, info, model['sha256'], model['bytes'], hashlib.sha256(native).hexdigest()), info


def artifacts(directory, review=False):
    names = (('segments.json', 'text'), ('transcript.txt', 'text'), ('captions.srt', 'file'), ('captions.vtt', 'file'), *((caption_review.FILE, 'text'),) * bool(review))
    return [{'file': str(directory / n), 'kind': kind, 'sha256': digest(directory, n)} for n, kind in names]


def evidence_names():
    return {'authored.json', 'plan.json', 'captures.json', 'captured-audio.wav', 'model.json', 'runtime.json', 'native.json', 'native.srt',
        *[s + x for s in STAGES for x in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr')]}


def membership(directory, review=False):
    from schemaxis.run_paths import MANIFEST
    published = ('segments.json', 'transcript.txt', 'captions.srt', 'captions.vtt', *(caption_review.FILE,) * bool(review))
    expected = evidence_names() | {*published, 'verification.json', 'result.json', 'schema.snapshot.json', MANIFEST, 'job.json'}
    expected |= {name + '.metadata.json' for name in published}
    for path in directory.iterdir():
        if path.name == '.dispatch':
            if path.is_symlink() or not path.is_dir(): fail('VERIFICATION_FAILED','dispatch member is not an owned directory',path.name)
        elif path.name not in expected or path.is_symlink() or not path.is_file():
            fail('VERIFICATION_FAILED','unexpected or nonregular retained transcription member',path.name)


def same_json(actual, expected):
    return json.dumps(actual,sort_keys=True,allow_nan=False)==json.dumps(expected,sort_keys=True,allow_nan=False)


def run(document, directory, *, executable=None, timeout=300):
    p = plan(document);executable = executable or os.environ.get('SCHEMAXIS_WHISPERCPP') or shutil.which('whisper-cli')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.X_OK): fail('INTERPRETER_NOT_FOUND', 'configure an absolute whisper.cpp 1.9.5 whisper-cli executable')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600: fail('INVALID_ARGUMENT', 'timeout must be finite in (0,3600]')
    deadline = time.monotonic() + timeout;directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS', 'select a fresh output directory', str(directory))
    directory.mkdir(parents=True);atomic_json(directory / 'authored.json', document);atomic_json(directory / 'plan.json', p)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    def checkpoint():
        if cancellation_requested(): fail('RUNNER_CANCELLED', 'transcription cancelled')
        if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'transcription exhausted its total deadline')
    try:
        checkpoint()
        data, sha, info = audio_capture(p, lambda: bounded(p['audio']['path'], 'INVALID_AUDIO_SOURCE', AUDIO_LIMIT))
        (directory / 'captured-audio.wav').write_bytes(data)
        atomic_json(directory / 'captures.json', {'source': p['audio']['path'], 'sha256': sha, 'bytes': len(data), 'info': info});del data
        checkpoint()
        model = stream_digest(p['model']['path'], MODEL_LIMIT, 'INVALID_MODEL', checkpoint=checkpoint)
        if model['sha256'] != p['model']['sha256']: fail('MODEL_HASH_MISMATCH', 'model bytes differ from the pinned sha256', '$.model.sha256', observed=model['sha256'])
        checkpoint()
        runtime_files = None
        for stage, command in commands(str(executable), p).items():
            path = directory / (stage + '-launcher.py');path.write_text(launcher(directory, stage, command, p))
            execute([sys.executable, str(path)], directory, stage, deadline - time.monotonic(), {'LANG': 'C.UTF-8', 'OMP_NUM_THREADS': '1'})
            if stage == 'version': qualified_runtime(directory)
            if stage == 'libraries': runtime_files = runtime_identity(directory, str(executable), checkpoint=checkpoint)
        checkpoint()
        after_runtime = runtime_identity(directory, str(executable), checkpoint=checkpoint)
        if after_runtime != runtime_files: fail('RUNTIME_CHANGED', 'executable or dynamic dependency bytes changed during the run')
        after = stream_digest(p['model']['path'], MODEL_LIMIT, 'INVALID_MODEL', checkpoint=checkpoint)
        if {k: after[k] for k in model} != model: fail('MODEL_CHANGED', 'model bytes or file identity changed during the native run', '$.model.path')
        atomic_json(directory / 'model.json', {'path': p['model']['path'], **model, 'after': {k: after[k] for k in model}})
        atomic_json(directory / 'runtime.json', {'executable': str(executable), 'files': runtime_files})
        document_out, info = inspect(directory, p);write_outputs(directory, document_out, wants_review(p))
        runtime = qualified_runtime(directory)
        atomic_json(directory / 'verification.json', {'executable': str(executable), 'runtime': runtime, 'artifacts': artifacts(directory, wants_review(p)),
            'evidence': {n: digest(directory, n) for n in sorted(evidence_names())}})
        result = verify(directory, require_result=False)
        checkpoint()
        result['status'] = 'succeeded';atomic_json(directory / 'result.json', result);return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED', str(error))
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()});raise error


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        p = plan(read(directory, 'authored.json'));receipt = read(directory, 'verification.json')
        if not isinstance(receipt,dict) or set(receipt)!={'executable','runtime','artifacts','evidence'} or not isinstance(receipt['evidence'],dict): fail('VERIFICATION_FAILED','native receipt member set differs')
        if not same_json(read(directory, 'plan.json'), p): fail('VERIFICATION_FAILED', 'effective transcription plan differs')
        if require_result and read(directory, 'result.json').get('status') != 'succeeded': fail('INCOMPLETE_EXECUTION', 'transcription did not complete')
        membership(directory, wants_review(p))
        data = bounded(directory / 'captured-audio.wav', limit=AUDIO_LIMIT);info = audio_info(data, 'VERIFICATION_FAILED')
        if read(directory, 'captures.json') != {'source': p['audio']['path'], 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'info': info}: fail('VERIFICATION_FAILED', 'audio source/capture binding differs')
        executable = receipt['executable']
        if not isinstance(executable, str) or not Path(executable).is_absolute(): fail('VERIFICATION_FAILED', 'native executable identity must be absolute')
        for stage, command in commands(executable, p).items():
            submission = read(directory, stage + '-submission.json');interpreter = submission.get('interpreter', {}).get('executable');path = directory / (stage + '-launcher.py')
            if not isinstance(interpreter, str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand') != [interpreter, str(path)] or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0: fail('VERIFICATION_FAILED', 'native command/completion differs', stage)
            if bounded(path).decode() != launcher(directory, stage, command, p): fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
            bindings = read(directory, stage + '-inputs.json');expected = {'files': {str(directory / n): digest(directory, n) for n in stage_inputs(stage)}}
            if stage == 'transcribe': expected['model'] = {'sha256': p['model']['sha256'], 'bytes': read(directory, 'model.json')['bytes']}
            if not isinstance(bindings, dict) or set(bindings) != {*expected, 'ldLibraryPath'} or any(bindings[k] != v for k, v in expected.items()) or not (bindings['ldLibraryPath'] is None or isinstance(bindings['ldLibraryPath'], str)): fail('VERIFICATION_FAILED', 'native audio/model input binding differs', stage)
        runtime = qualified_runtime(directory, 'VERIFICATION_FAILED')
        if receipt['runtime'] != runtime: fail('VERIFICATION_FAILED', 'require qualified whisper.cpp 1.9.5 runtime identity')
        files = read(directory, 'runtime.json')
        if set(files) != {'executable', 'files'} or files['executable'] != executable or [(f['name'], f['path']) for f in files['files'][1:]] != library_paths(directory) or files['files'][0] != {'name': 'whisper-cli', 'path': executable, 'sha256': files['files'][0].get('sha256'), 'bytes': files['files'][0].get('bytes')}: fail('VERIFICATION_FAILED', 'runtime dependency identity differs from the loader trace')
        if not all(set(f)=={'name','path','sha256','bytes'} and isinstance(f.get('sha256'), str) and HEX.fullmatch(f['sha256']) and whole(f.get('bytes')) and 0<f['bytes']<=RUNTIME_FILE_LIMIT for f in files['files']): fail('VERIFICATION_FAILED', 'runtime file hashes are malformed')
        expected, _ = inspect(directory, p)
        if read(directory, 'segments.json') != expected: fail('VERIFICATION_FAILED', 'segment evidence differs from independently checked native segments', 'segments.json')
        for name, text in outputs(expected).items():
            if text is not None and bounded(directory / name, limit=JSON_LIMIT).decode('utf-8') != text: fail('VERIFICATION_FAILED', 'caption or transcript text disagrees with checked segments', name)
        if bounded(directory / 'segments.json', limit=JSON_LIMIT) != encode_json(expected): fail('VERIFICATION_FAILED', 'segment evidence is not in canonical form', 'segments.json')
        if wants_review(p):
            report = review_document(expected)
            caption_review.check(strict_json(bounded(directory / caption_review.FILE, limit=JSON_LIMIT), caption_review.FILE, 'VERIFICATION_FAILED'), report)
            if bounded(directory / caption_review.FILE, limit=JSON_LIMIT) != encode_json(report): fail('VERIFICATION_FAILED', 'caption review is not in canonical form', caption_review.FILE)
        if receipt['artifacts'] != artifacts(directory, wants_review(p)): fail('VERIFICATION_FAILED', 'transcription publication membership/digest differs')
        if set(receipt['evidence']) != evidence_names(): fail('VERIFICATION_FAILED', 'native evidence membership differs')
        for n in evidence_names():
            if digest(directory, n) != receipt['evidence'][n]: fail('VERIFICATION_FAILED', 'retained native evidence differs', n)
        fresh = {'verified': True, 'artifacts': 5 if wants_review(p) else 4, 'runtime': runtime, 'segments': expected['segmentCount'], 'audioDurationMs': expected['audio']['durationMs'],
                'audioSha256': expected['audio']['sha256'], 'modelSha256': expected['model']['sha256'], 'accuracyCertified': False, 'humanReviewRequired': True}
        if wants_review(p): fresh['captionReview'] = caption_review.summary(report)
        if segmentation.OPTION in p: fresh['segmentation'] = segmentation.summary(expected['segmentation'])
        if require_result and not same_json(read(directory,'result.json'),{**fresh,'status':'succeeded'}): fail('VERIFICATION_FAILED','retained result differs from independent reopening')
        return fresh
    except SchemaxisError as error:
        if error.fault.code in ('VERIFICATION_FAILED','INCOMPLETE_EXECUTION'): raise
        fail('VERIFICATION_FAILED','retained transcription evidence violates its contract ('+error.fault.code+')',error.fault.location,cause=error.fault.to_dict())
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeDecodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained transcription evidence: ' + str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
