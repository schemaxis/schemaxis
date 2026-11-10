"""Host-only human corrections of a retained whisper.cpp machine draft.

This route never launches whisper-cli and reads no audio or model. It captures one pinned machine
``segments.json``, applies authored per-cue text replacements, and publishes a NEW closed reviewed
contract (``schemaxis.timedtext.reviewed/1``), plain text, SRT, WebVTT and an exact correction ledger.
Timings, language and the audio/model/native provenance are carried over untouched; the machine
draft is never modified.

The review status is a declaration by the author of the corrections. Nothing here verifies who
reviewed the transcript or whether any word is right, so every publication says so. Every run and
every verification replays the whole derivation from the captured draft bytes and the authored edits,
so refreshed ordinary hashes cannot hide an altered publication.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import stat

from schemaxis.adaptors.whispercpp import caption_review
from schemaxis.artifacts import atomic_json
from schemaxis.core import timed_text
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError

VERSION = 'schemaxis.whispercpp.correct/1'
PLAN_VERSION = 'schemaxis.whispercpp.correction-plan/1'
LEDGER_VERSION = 'schemaxis.whispercpp.corrections/1'
RUNTIME = 'host-only'
REVIEWED = 'reviewed-segments.json'
LEDGER = 'corrections.json'
TRANSCRIPT = 'transcript.txt'
SRT = 'captions.srt'
VTT = 'captions.vtt'
CAPTURED = 'captured-draft.json'
LIMIT = timed_text.MAX_DOCUMENT_BYTES
MAX_CORRECTIONS = timed_text.MAX_CUES
STATUSES = timed_text.REVIEWED_STATUSES
TOP = ('version', 'draft', 'basisSha256', 'review', 'corrections', 'captionReview')
SHA = {'type': 'string', 'minLength': 64, 'maxLength': 64}
OPTIONS = {
    'draft': {'type': 'object', 'required': True, 'properties': {'path': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}}},
    'basisSha256': {**SHA, 'required': True},
    'review': {'type': 'object', 'required': True, 'properties': {
        'status': {'type': 'enum', 'values': list(STATUSES), 'required': True},
        'note': {'type': 'string', 'minLength': 1, 'maxLength': timed_text.MAX_NOTE_CHARACTERS, 'required': True}}},
    'corrections': {'type': 'array', 'maxItems': MAX_CORRECTIONS, 'items': {'type': 'object', 'properties': {
        'index': {'type': 'integer', 'minimum': 0, 'maximum': MAX_CORRECTIONS - 1, 'required': True},
        'text': {'type': 'string', 'minLength': 1, 'maxLength': timed_text.MAX_CUE_CHARACTERS, 'required': True}}}},
    'captionReview': {'type': 'boolean', 'default': False}}
STATEMENT = ('The review status is a declaration recorded from the author of the correction document. Schemaxis did not verify who reviewed '
             'the transcript, that the audio was heard, or that any word or timing is correct; recognition accuracy, reviewer identity and '
             'caption accessibility are not certified.')
SEGMENTATION_STATEMENT = ('maxSegmentLength was a native segmentation target for the machine draft, not a guaranteed maximum or a readability '
                          'certification. cuesOverTarget is recounted on the reviewed text and over-target cues are published unchanged; cue '
                          'boundary times are the draft\'s experimental token-level timestamps and are not certified.')
LEDGER_STATEMENT = ('Exact record of the authored text replacements against the pinned machine draft. It proves which words changed, not that '
                    'the replacements are correct, who made them or that the audio was reviewed.')
LOSSES = [
    'Host-only: whisper-cli is never launched and no audio, model or recognition run is read or repeated. Only the pinned draft segments.json bytes and the authored edits are used.',
    'Text-only replacement of existing cues by unique index. Timings, language, cue count and the audio, model and native-JSON provenance are preserved; no timing edits, splits, merges, insertions or deletions.',
    f'The draft must be an unedited machine {timed_text.SOURCE_VERSION} within the shared timed-text budgets ({timed_text.MAX_CUES} cues, {timed_text.MAX_CUE_CHARACTERS} characters per cue, '
    f'{timed_text.MAX_TOTAL_CHARACTERS} in total). A reviewed document is not a draft, and the machine draft is never modified.',
    'The status human-corrected or human-reviewed-unchanged is a declaration by the author and is recorded as provenance. Reviewer identity, hearing the audio, recognition accuracy, readability and accessibility are not verified or certified.']


def refuse(code, message, location, recovery, **observed):
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed, recovery=recovery))


def exact(value, names, location, recovery):
    if not isinstance(value, dict):
        refuse('INVALID_DOCUMENT', 'expected an object', location, recovery)
    extra = sorted(set(value) - set(names))
    if extra:
        refuse('UNKNOWN_ARGUMENT', 'unsupported keys; this document is closed', location, f'remove {", ".join(extra)}; allowed members: {", ".join(names)}. {recovery}', keys=extra)


def plan(document):
    exact(document, TOP, '$', 'use only the declared members of the correction document')
    if document.get('version') != VERSION:
        refuse('UNSUPPORTED_VERSION', 'expected ' + VERSION, '$.version', 'set version to ' + VERSION)
    # An absent required member is reported by argument validation as MISSING_ARGUMENT, not as an invalid object.
    if 'draft' in document: exact(document['draft'], ('path',), '$.draft', 'name only draft.path; pin the bytes with basisSha256')
    if 'review' in document: exact(document['review'], ('status', 'note'), '$.review', 'declare only review.status and review.note')
    listed = document.get('corrections')
    for number, item in enumerate(listed if isinstance(listed, list) else []):
        exact(item, ('index', 'text'), f'$.corrections[{number}]', 'a correction is exactly {"index": N, "text": "replacement"}; timings cannot be edited')
    try: p = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS}, location='$')
    except SchemaxisError as error:
        fault = error.fault
        if fault.recovery: raise
        raise SchemaxisError(Fault(fault.code, fault.message, fault.location, fault.phase, observed=fault.observed,
                                   recovery=f'correct the value at {fault.location}; see docs/whispercpp.md#human-corrections for the closed correction document')) from None
    path = p['draft']['path']
    if '\0' in path or not path.startswith('/') or '..' in Path(path).parts or Path(path).suffix.lower() != '.json':
        refuse('INVALID_DRAFT_SOURCE', 'select an absolute local segments.json path without parent references', '$.draft.path',
               'point at the segments.json published by the whisper.cpp route (or hand it over as a workflow text artifact)')
    if not timed_text.HEX.fullmatch(p['basisSha256']):
        refuse('INVALID_SHA256', 'use 64 lowercase hexadecimal digits', '$.basisSha256', 'copy the sha256 of the draft segments.json you reviewed')
    problem = timed_text.note_problem(p['review']['note'])
    if problem:
        refuse('CORRECTIONS_NOTE_INVALID', problem, '$.review.note', f'write a plain-text note of 1 to {timed_text.MAX_NOTE_CHARACTERS} characters without markup brackets, controls or the caption arrow')
    seen = {}
    for number, item in enumerate(p.get('corrections', [])):
        at = f'$.corrections[{number}]'
        if item['index'] in seen:
            refuse('CORRECTION_DUPLICATE', f'cue {item["index"]} is already corrected by $.corrections[{seen[item["index"]]}]', at + '.index',
                   'merge the replacements into one entry per cue', index=item['index'])
        seen[item['index']] = number
        problem = 'replacement text is blank' if not item['text'].strip() else timed_text.cue_text_problem(item['text'])
        if problem:
            refuse('CORRECTION_TEXT_INVALID', problem, at + '.text', 'use visible plain text without surrounding spaces, controls, markup brackets or the caption arrow; blank text is never accepted',
                   index=item['index'])
    changed = bool(p.get('corrections'))
    if (p['review']['status'] == 'human-corrected') != changed:
        refuse('CORRECTIONS_STATUS_CONFLICT', 'human-corrected needs at least one correction and human-reviewed-unchanged needs none',
               '$.review.status' if changed else '$.corrections',
               'declare human-reviewed-unchanged with no corrections, or human-corrected with at least one changed cue', corrections=len(p.get('corrections', [])))
    # An unauthored captionReview stays out of the plan, as in the transcription route.
    if 'captionReview' not in document: p.pop('captionReview')
    return {'version': PLAN_VERSION, 'operation': 'correct', **p, 'losses': [*LOSSES, *([caption_review.LOSS] if wants_review(p) else [])]}


def wants_review(p): return p.get('captionReview') is True


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, **{k: argument_schema(v) for k, v in OPTIONS.items()}},
                                              ['version', 'draft', 'basisSha256', 'review'])}


def query(document): plan(document); return ['correct'], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1: refuse('INVALID_EXECUTION', 'corrections run serially on the host', identity, 'omit threads or use 1')
    return {'threads': 1}


def bounded(path, code='VERIFICATION_FAILED', missing=None):
    """Read one bounded regular file; `missing` names a distinct fault for an absent file or path component."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT: raise ValueError('not a bounded regular file')
            data = stream.read(LIMIT + 1)
        if len(data) > LIMIT: raise ValueError('byte budget exceeded')
        return data
    except (FileNotFoundError, NotADirectoryError) as error:
        if missing:
            refuse(missing, 'the draft segments.json does not exist: ' + str(error.strerror or error).lower(), str(path),
                   'point draft.path at the segments.json published by the whisper.cpp route; a missing file is not repaired or replaced')
        refuse(code, 'select an intact regular file within the byte budget: ' + str(error), str(path), f'use a regular file of at most {LIMIT} bytes (no symbolic link)')
    except (OSError, ValueError) as error:
        refuse(code, 'select an intact regular file within the byte budget: ' + str(error), str(path), f'use a regular file of at most {LIMIT} bytes (no symbolic link)')


def reusableInputs(document):
    p = plan(document)
    return {'draft': hashlib.sha256(bounded(p['draft']['path'], 'INVALID_DRAFT_SOURCE', 'DRAFT_SOURCE_MISSING')).hexdigest()}


def sha(data): return hashlib.sha256(data).hexdigest()


def derive(p, draft):
    """Every publication, as exact bytes, from the captured draft bytes and the authored plan alone."""
    basis = sha(draft)
    if basis != p['basisSha256']:
        refuse('CORRECTIONS_STALE', 'the draft bytes differ from basisSha256; the corrections were written against another draft', '$.basisSha256',
               'review the current draft again, then copy its sha256 into basisSha256 (and re-check every index); a changed draft is never corrected silently',
               expected=p['basisSha256'], actual=basis)
    decoded = timed_text.strict_json(draft, '$.draft')
    view = timed_text.validate(decoded, '$.draft')
    if view['source'] != timed_text.SOURCE_VERSION:
        refuse('DRAFT_NOT_MACHINE_DRAFT', 'the draft is already a reviewed document; corrections apply to the original machine draft only', '$.draft.path',
               'correct the original machine segments.json again with all intended edits, so the reviewed document keeps one basis')
    cues = [dict(segment) for segment in decoded['segments']]
    ledger = []
    for number, item in sorted(enumerate(p.get('corrections', [])), key=lambda pair: pair[1]['index']):
        at = f'$.corrections[{number}]'
        if item['index'] >= len(cues):
            refuse('CORRECTION_INDEX_INVALID', f'cue {item["index"]} does not exist; the draft has {len(cues)} cues (0 to {len(cues) - 1})', at + '.index',
                   'use a cue index from the draft segments.json', index=item['index'], cueCount=len(cues))
        cue = cues[item['index']]
        if item['text'] == cue['text']:
            refuse('CORRECTION_NOOP', 'the replacement equals the existing cue text', at + '.text',
                   'remove this entry, or declare human-reviewed-unchanged when no cue changes', index=item['index'])
        ledger.append({'index': item['index'], 'startMs': cue['startMs'], 'endMs': cue['endMs'], 'original': cue['text'], 'replacement': item['text']})
        cue['text'] = item['text']
    final = sum(len(c['text']) for c in cues)
    if final > timed_text.MAX_TOTAL_CHARACTERS:
        # Judged on the finished cue list, so a later correction that shortens another cue is never refused for an earlier one.
        growth = {number: len(item['text']) - len(decoded['segments'][item['index']]['text']) for number, item in enumerate(p['corrections'])}
        number = max(growth, key=lambda n: (growth[n], -n))
        refuse('TIMED_TEXT_RESOURCE_LIMIT', f'the corrected transcript would hold {final} characters; the limit is {timed_text.MAX_TOTAL_CHARACTERS} in total, and this correction adds the most ({growth[number]})',
               f'$.corrections[{number}].text', f'shorten this replacement or the other replacements so the corrected transcript stays within {timed_text.MAX_TOTAL_CHARACTERS} characters '
               f'(the draft holds {sum(len(c["text"]) for c in decoded["segments"])}); corrections cannot add or merge cues',
               characters=final, limit=timed_text.MAX_TOTAL_CHARACTERS, draftCharacters=sum(len(c['text']) for c in decoded['segments']), index=p['corrections'][number]['index'])
    reviewed = {k: decoded[k] for k in ('language', 'timeUnit', 'audio', 'model', 'nativeJsonSha256', 'segmentCount')}
    reviewed.update({'version': timed_text.REVIEWED_VERSION, 'segments': cues})
    if 'segmentation' in decoded:
        reviewed['segmentation'] = {**decoded['segmentation'], 'statement': SEGMENTATION_STATEMENT,
                                    'cuesOverTarget': sum(len(c['text']) > decoded['segmentation']['maxSegmentLength'] for c in cues)}
    reviewed['review'] = {
        'status': p['review']['status'], 'accuracyCertified': False, 'identityVerified': False, 'statement': STATEMENT, 'note': p['review']['note'],
        'basis': {'version': timed_text.SOURCE_VERSION, 'sha256': basis, 'bytes': len(draft)},
        'correctionCount': len(ledger), 'correctedIndices': [e['index'] for e in ledger], 'policy': dict(decoded['review']['policy'])}
    timed_text.validate(reviewed, '$.reviewed')
    reviewed_bytes = timed_text.canonical_json(reviewed)
    ledger_document = {
        'version': LEDGER_VERSION, 'status': p['review']['status'], 'note': p['review']['note'],
        'basis': {'version': timed_text.SOURCE_VERSION, 'sha256': basis, 'bytes': len(draft)}, 'reviewedSha256': sha(reviewed_bytes),
        'language': reviewed['language'], 'audioSha256': reviewed['audio']['sha256'], 'modelSha256': reviewed['model']['sha256'],
        'cueCount': len(cues), 'correctionCount': len(ledger), 'unchangedCueCount': len(cues) - len(ledger), 'entries': ledger,
        'accuracyCertified': False, 'identityVerified': False, 'statement': LEDGER_STATEMENT}
    outputs = {REVIEWED: reviewed_bytes, TRANSCRIPT: timed_text.plain_text(cues).encode('utf-8'), SRT: timed_text.srt_text(cues).encode('utf-8'),
               VTT: timed_text.vtt_text(cues).encode('utf-8'), LEDGER: timed_text.canonical_json(ledger_document)}
    if wants_review(p): outputs[caption_review.FILE] = timed_text.canonical_json(caption_review.build(reviewed, sha(reviewed_bytes)))
    return outputs, ledger_document, reviewed


def published(review): return (REVIEWED, TRANSCRIPT, SRT, VTT, LEDGER, *(caption_review.FILE,) * bool(review))
def kinds(): return {REVIEWED: 'text', TRANSCRIPT: 'text', SRT: 'file', VTT: 'file', LEDGER: 'text', caption_review.FILE: 'text'}
def evidence_names(): return {'authored.json', 'plan.json', 'captures.json', CAPTURED}


def digest(directory, name): return sha(bounded(directory / name))


def artifacts(directory, review=False):
    return [{'file': str(directory / n), 'kind': kinds()[n], 'sha256': digest(directory, n)} for n in published(review)]


def membership(directory, review=False):
    """Only host evidence and publications: a launcher, submission or native log is itself a failure."""
    from schemaxis.run_paths import MANIFEST
    names = published(review)
    expected = evidence_names() | {*names, 'verification.json', 'result.json', 'schema.snapshot.json', MANIFEST, 'job.json'}
    expected |= {name + '.metadata.json' for name in names}
    for path in directory.iterdir():
        # `.dispatch` is not exempt: this route never creates it, so any content there was planted and is never read or run.
        if path.name not in expected or path.is_symlink() or not path.is_file():
            refuse('VERIFICATION_FAILED', 'unexpected or nonregular retained correction member (a host-only run holds no native evidence)', path.name, 'rerun from the declared input in a fresh directory')


def read_json(directory, name):
    try: return timed_text.strict_json(bounded(directory / name), name)
    except SchemaxisError as error:
        refuse('VERIFICATION_FAILED', 'retained evidence is not strict JSON: ' + error.fault.message, name, 'rerun from the declared input')


def same_json(actual, expected):
    return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)


def run(document, directory, *, executable=None, timeout=300):
    """`executable` is accepted for the shared runner and never used: no native process exists on this route."""
    p = plan(document)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        refuse('INVALID_ARGUMENT', 'timeout must be finite in (0,3600]', '$.timeout', 'use a finite number of seconds')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): refuse('OUTPUT_EXISTS', 'select a fresh output directory', str(directory), 'choose a new output directory')
    directory.mkdir(parents=True); atomic_json(directory / 'authored.json', document); atomic_json(directory / 'plan.json', p)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    try:
        draft = bounded(p['draft']['path'], 'INVALID_DRAFT_SOURCE', 'DRAFT_SOURCE_MISSING')
        (directory / CAPTURED).write_bytes(draft)
        atomic_json(directory / 'captures.json', {'source': p['draft']['path'], 'sha256': sha(draft), 'bytes': len(draft)})
        outputs, _, _ = derive(p, draft)
        for name, data in outputs.items(): (directory / name).write_bytes(data)
        atomic_json(directory / 'verification.json', {'runtime': RUNTIME, 'artifacts': artifacts(directory, wants_review(p)),
                                                      'evidence': {n: digest(directory, n) for n in sorted(evidence_names())}})
        result = verify(directory, require_result=False)
        result['status'] = 'succeeded'; atomic_json(directory / 'result.json', result); return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try: refuse('CORRECTION_FAILED', str(error), '$', 'rerun from the declared input')
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()}); raise error


def verify(directory, require_result=True):
    """Semantic replay: derive every publication again from the captured bytes and authored edits."""
    directory = Path(directory).absolute()
    try:
        p = plan(read_json(directory, 'authored.json')); receipt = read_json(directory, 'verification.json')
        if not isinstance(receipt, dict) or set(receipt) != {'runtime', 'artifacts', 'evidence'} or receipt['runtime'] != RUNTIME or not isinstance(receipt['evidence'], dict):
            refuse('VERIFICATION_FAILED', 'host-only receipt member set differs', 'verification.json', 'rerun from the declared input')
        if not same_json(read_json(directory, 'plan.json'), p): refuse('VERIFICATION_FAILED', 'effective correction plan differs', 'plan.json', 'rerun from the declared input')
        if require_result and read_json(directory, 'result.json').get('status') != 'succeeded': refuse('INCOMPLETE_EXECUTION', 'corrections did not complete', 'result.json', 'rerun')
        membership(directory, wants_review(p))
        draft = bounded(directory / CAPTURED)
        if not same_json(read_json(directory, 'captures.json'), {'source': p['draft']['path'], 'sha256': sha(draft), 'bytes': len(draft)}):
            refuse('VERIFICATION_FAILED', 'draft source/capture binding differs', 'captures.json', 'rerun from the declared input')
        outputs, ledger, reviewed = derive(p, draft)
        for name, data in outputs.items():
            if bounded(directory / name) != data:
                refuse('VERIFICATION_FAILED', 'publication differs from independent replay of the captured draft and authored edits', name, 'rerun from the declared input; a published file was altered')
        view = timed_text.parse(bounded(directory / REVIEWED), expected_sha256=ledger['reviewedSha256'], location=REVIEWED)
        if view['status'] != p['review']['status'] or view['review']['basisSha256'] != p['basisSha256']:
            refuse('VERIFICATION_FAILED', 'reviewed status or basis differs from the authored declaration', REVIEWED, 'rerun from the declared input')
        if receipt['artifacts'] != artifacts(directory, wants_review(p)): refuse('VERIFICATION_FAILED', 'correction publication membership/digest differs', 'verification.json', 'rerun')
        if set(receipt['evidence']) != evidence_names() or any(digest(directory, n) != receipt['evidence'][n] for n in evidence_names()):
            refuse('VERIFICATION_FAILED', 'retained correction evidence differs', 'verification.json', 'rerun from the declared input')
        fresh = {'verified': True, 'artifacts': len(published(wants_review(p))), 'runtime': RUNTIME, 'nativeProcesses': 0, 'reviewStatus': p['review']['status'],
                 'cues': len(reviewed['segments']), 'corrections': ledger['correctionCount'], 'basisSha256': p['basisSha256'],
                 'reviewedSha256': ledger['reviewedSha256'], 'accuracyCertified': False, 'identityVerified': False}
        if wants_review(p): fresh['captionReview'] = caption_review.summary(timed_text.strict_json(outputs[caption_review.FILE]))
        if require_result and not same_json(read_json(directory, 'result.json'), {**fresh, 'status': 'succeeded'}):
            refuse('VERIFICATION_FAILED', 'retained result differs from independent replay', 'result.json', 'rerun from the declared input')
        return fresh
    except SchemaxisError as error:
        if error.fault.code in ('VERIFICATION_FAILED', 'INCOMPLETE_EXECUTION'): raise
        refuse('VERIFICATION_FAILED', 'retained correction evidence violates its contract (' + error.fault.code + ')', error.fault.location, 'rerun from the declared input', cause=error.fault.to_dict())
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeDecodeError, RecursionError) as error:
        refuse('VERIFICATION_FAILED', 'invalid retained correction evidence: ' + str(error), str(directory), 'rerun from the declared input')


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
