"""Host-only human corrections of a retained whisper.cpp machine draft, with author-declared cue timing edits.

This is the separately versioned successor route ``schemaxis.whispercpp.correct/3``. ``correct/1`` (``corrections.py``) and
``correct/2`` (``corrections_deletion.py``) promise the original machine timestamps and are unchanged. Like them, this route
never launches whisper-cli and reads no audio or model. It captures one pinned machine ``segments.json`` and applies authored
per-cue text replacements, authored deletions of whole cues, and authored timing edits by unique ORIGINAL source index, then
publishes the new closed reviewed contract (``schemaxis.timedtext.reviewed/3``), plain text, SRT, WebVTT and an exact ledger.

A timing edit states both ends of the final interval as integer elapsed milliseconds. It replaces the whole interval of one
retained cue; it never adds, splits or merges cues and never touches the audio. The finished cue set is judged as a whole, so the
order in which edits are listed never causes a false overlap refusal: every retained cue must satisfy
``0 <= startMs < endMs <= audio duration (rounded up to a millisecond)`` and no cue may start before the previous retained cue
ends. Nothing is clamped, reordered or rounded. Source indices stay the original draft indices after deletions.

The review status and every timing are declarations by the author. Nothing here listens to the audio or verifies that an edited
time is more accurate than the machine time, so the review and ledger say ``synchronizationCertified: false``. Every run and
every verification replays the whole derivation from the captured draft bytes and the authored edits, so refreshed ordinary
hashes cannot hide an altered publication.
"""
import hashlib
import math
from pathlib import Path

from schemaxis.adaptors.whispercpp import caption_review
from schemaxis.adaptors.whispercpp.corrections import (
    CAPTURED, LEDGER, REVIEWED, SRT, TRANSCRIPT, VTT, artifacts, bounded, digest, evidence_names, exact, membership, published,
    read_json, refuse, resources, same_json, sha, wants_review)
from schemaxis.artifacts import atomic_json
from schemaxis.core import timed_text
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError

VERSION = 'schemaxis.whispercpp.correct/3'
PLAN_VERSION = 'schemaxis.whispercpp.correction-plan/3'
LEDGER_VERSION = 'schemaxis.whispercpp.corrections/3'
RUNTIME = 'host-only'
MAX_CORRECTIONS = timed_text.MAX_CUES
STATUSES = timed_text.REVIEWED_STATUSES
TOP = ('version', 'draft', 'basisSha256', 'review', 'corrections', 'deletions', 'timings', 'captionReview')
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
    'deletions': {'type': 'array', 'maxItems': MAX_CORRECTIONS, 'items': {'type': 'integer', 'minimum': 0, 'maximum': MAX_CORRECTIONS - 1}},
    'timings': {'type': 'array', 'maxItems': MAX_CORRECTIONS, 'items': {'type': 'object', 'properties': {
        'index': {'type': 'integer', 'minimum': 0, 'maximum': MAX_CORRECTIONS - 1, 'required': True},
        'startMs': {'type': 'integer', 'minimum': 0, 'maximum': timed_text.MAX_NUMBER, 'required': True},
        'endMs': {'type': 'integer', 'minimum': 0, 'maximum': timed_text.MAX_NUMBER, 'required': True}}}},
    'captionReview': {'type': 'boolean', 'default': False}}
STATEMENT = ('The review status and every edited time are declarations recorded from the author of the correction document. Schemaxis did not '
             'verify who reviewed the transcript, that the audio was heard, or that any replacement, deletion or edited time is correct or '
             'synchronized with the audio; recognition accuracy, reviewer identity, audio synchronization and caption accessibility are not '
             'certified. An edited time is the author\'s stated interval, not a measured one.')
TIMING_POLICY = ('Author-edited cue intervals replace the machine draft\'s experimental token-level times for the listed source cues only; '
                 'every other retained cue keeps its machine time. Times are integer elapsed milliseconds inside the audio duration, never '
                 'clamped, reordered or rounded, and not certified as synchronized with the audio.')
SEGMENTATION_STATEMENT = ('maxSegmentLength was a native segmentation target for the machine draft, not a guaranteed maximum or a readability '
                          'certification. cueCount and cuesOverTarget are recounted on the retained, reviewed cues and over-target cues are published '
                          'unchanged; unedited cue boundary times are the draft\'s experimental token-level timestamps, edited ones are the author\'s, '
                          'and none are certified.')
LEDGER_STATEMENT = ('Exact record of the authored replacements, deletions and timing edits against the pinned machine draft, with the source index, original '
                    'text and original timing of every cue. It proves which cues changed, were removed or were retimed, not that any edit is correct, '
                    'that the captions are synchronized with the audio, who made the edit or that the audio was reviewed. In every section originalStartMs and '
                    'originalEndMs are the machine draft\'s times and startMs and endMs are the published (possibly author-edited) times; a deleted cue '
                    'has no published time, so a deletion records only originalStartMs and originalEndMs.')
LOSSES = [
    'Host-only: whisper-cli is never launched and no audio, model or recognition run is read or repeated. Only the pinned draft segments.json bytes and the authored edits are used.',
    'Text replacement, whole-cue deletion and whole-interval timing edits by unique original source index. Retained cues are renumbered contiguously from zero as published; language and the audio, model and native-JSON provenance are carried over. Unedited cues keep their machine times; no splits, merges or insertions, and the audio is never changed.',
    f'The draft must be an unedited machine {timed_text.SOURCE_VERSION} within the shared timed-text budgets ({timed_text.MAX_CUES} cues, {timed_text.MAX_CUE_CHARACTERS} characters per cue, '
    f'{timed_text.MAX_TOTAL_CHARACTERS} in total). A reviewed document is not a draft, and the machine draft is never modified. A draft with no cues is refused.',
    'Edited times are judged on the finished cue set: ordered, nonoverlapping, 0 <= startMs < endMs and at most the audio duration rounded up to a millisecond. They are never clamped, reordered or rounded, and a refusal names the offending edit.',
    'Deleting every cue of a nonempty draft is allowed only by explicit deletion: the reviewed document, the plain text and the SRT then hold no cues and the WebVTT holds only its header.',
    'The status human-corrected or human-reviewed-unchanged is a declaration by the author and is recorded as provenance; a timing edit counts as a change. Reviewer identity, hearing the audio, recognition accuracy, audio synchronization, readability and accessibility are not verified or certified.']
EMPTY_LOSS = 'captionReview is refused when every cue is deleted: a caption review with no cues would read as a pass.'
REVIEW_LOSS = caption_review.LOSS + ' On this route the durations are those of the published, possibly edited, times.'


def plan(document):
    exact(document, TOP, '$', 'use only the declared members of the correction document')
    if document.get('version') != VERSION:
        refuse('UNSUPPORTED_VERSION', 'expected ' + VERSION, '$.version', 'set version to ' + VERSION)
    if 'draft' in document: exact(document['draft'], ('path',), '$.draft', 'name only draft.path; pin the bytes with basisSha256')
    if 'review' in document: exact(document['review'], ('status', 'note'), '$.review', 'declare only review.status and review.note')
    for name, shape, hint in (('corrections', ('index', 'text'), 'a replacement is exactly {"index": N, "text": "replacement"}'),
                              ('timings', ('index', 'startMs', 'endMs'), 'a timing edit is exactly {"index": N, "startMs": integer, "endMs": integer}')):
        listed = document.get(name)
        for number, item in enumerate(listed if isinstance(listed, list) else []):
            exact(item, shape, f'$.{name}[{number}]', hint + '; a deletion is a bare source index in $.deletions')
    try: p = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS}, location='$')
    except SchemaxisError as error:
        fault = error.fault
        if fault.recovery: raise
        raise SchemaxisError(Fault(fault.code, fault.message, fault.location, fault.phase, observed=fault.observed,
                                   recovery=f'correct the value at {fault.location}; see docs/whispercpp.md#cue-timing-edits for the closed correction document')) from None
    path = p['draft']['path']
    if '\0' in path or not path.startswith('/') or '..' in Path(path).parts or Path(path).suffix.lower() != '.json':
        refuse('INVALID_DRAFT_SOURCE', 'select an absolute local segments.json path without parent references', '$.draft.path',
               'point at the segments.json published by the whisper.cpp route (or hand it over as a workflow text artifact)')
    if not timed_text.HEX.fullmatch(p['basisSha256']):
        refuse('INVALID_SHA256', 'use 64 lowercase hexadecimal digits', '$.basisSha256', 'copy the sha256 of the draft segments.json you reviewed')
    problem = timed_text.note_problem(p['review']['note'])
    if problem:
        refuse('CORRECTIONS_NOTE_INVALID', problem, '$.review.note', f'write a plain-text note of 1 to {timed_text.MAX_NOTE_CHARACTERS} characters without markup brackets, controls or the caption arrow')
    deleted = {}
    for number, index in enumerate(p.get('deletions', [])):
        if index in deleted:
            refuse('DELETION_DUPLICATE', f'cue {index} is already deleted by $.deletions[{deleted[index]}]', f'$.deletions[{number}]',
                   'list each source cue index once', index=index)
        deleted[index] = number
    seen = {}
    for number, item in enumerate(p.get('corrections', [])):
        at = f'$.corrections[{number}]'
        if item['index'] in seen:
            refuse('CORRECTION_DUPLICATE', f'cue {item["index"]} is already corrected by $.corrections[{seen[item["index"]]}]', at + '.index',
                   'merge the replacements into one entry per cue', index=item['index'])
        seen[item['index']] = number
        if item['index'] in deleted:
            refuse('CORRECTION_DELETION_CONFLICT', f'cue {item["index"]} is both replaced and deleted ($.deletions[{deleted[item["index"]]}])', at + '.index',
                   'either replace the cue text or delete the cue, not both', index=item['index'])
        problem = 'replacement text is blank' if not item['text'].strip() else timed_text.cue_text_problem(item['text'])
        if problem:
            refuse('CORRECTION_TEXT_INVALID', problem, at + '.text', 'use visible plain text without surrounding spaces, controls, markup brackets or the caption arrow; blank text is never a replacement (delete the cue instead)',
                   index=item['index'])
    retimed = {}
    for number, item in enumerate(p.get('timings', [])):
        at = f'$.timings[{number}]'
        if item['index'] in retimed:
            refuse('TIMING_DUPLICATE', f'cue {item["index"]} is already retimed by $.timings[{retimed[item["index"]]}]', at + '.index',
                   'state one interval per cue', index=item['index'])
        retimed[item['index']] = number
        if item['index'] in deleted:
            refuse('TIMING_DELETION_CONFLICT', f'cue {item["index"]} is both retimed and deleted ($.deletions[{deleted[item["index"]]}])', at + '.index',
                   'either retime the cue or delete the cue, not both', index=item['index'])
        if not item['startMs'] < item['endMs']:
            refuse('TIMING_INTERVAL_INVALID', 'a cue needs startMs < endMs, both as integer elapsed milliseconds', at,
                   'state the whole new interval with startMs before endMs; a cue cannot be empty or reversed', index=item['index'], startMs=item['startMs'], endMs=item['endMs'])
    changed = bool(p.get('corrections') or p.get('deletions') or p.get('timings'))
    if (p['review']['status'] == 'human-corrected') != changed:
        refuse('CORRECTIONS_STATUS_CONFLICT', 'human-corrected needs at least one replacement, deletion or timing edit and human-reviewed-unchanged needs none',
               '$.review.status' if changed else '$.corrections',
               'declare human-reviewed-unchanged with no edits, or human-corrected with at least one replaced, deleted or retimed cue',
               corrections=len(p.get('corrections', [])), deletions=len(p.get('deletions', [])), timings=len(p.get('timings', [])))
    if 'captionReview' not in document: p.pop('captionReview')
    return {'version': PLAN_VERSION, 'operation': 'correct', **p, 'losses': [*LOSSES, *([REVIEW_LOSS, EMPTY_LOSS] if wants_review(p) else [])]}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, **{k: argument_schema(v) for k, v in OPTIONS.items()}},
                                              ['version', 'draft', 'basisSha256', 'review'])}


def query(document): plan(document); return ['correct'], {}


def reusableInputs(document):
    p = plan(document)
    return {'draft': hashlib.sha256(bounded(p['draft']['path'], 'INVALID_DRAFT_SOURCE', 'DRAFT_SOURCE_MISSING')).hexdigest()}


def final_times(source, retained, edits, limit):
    """Judge the finished cue set (never the edit order): every retained cue's interval inside the audio, ordered and nonoverlapping."""
    previous, before = 0, None
    for source_index in retained:
        item = edits.get(source_index)
        start, end = (item['startMs'], item['endMs']) if item else (source[source_index]['startMs'], source[source_index]['endMs'])
        # A violation is blamed on an edit when one of the two cues involved was retimed; an unedited neighbour cannot be at fault.
        culprit = next((edits[k]['number'] for k in (source_index, before) if k in edits), None)
        at = '$.timings' if culprit is None else f'$.timings[{culprit}]'
        if end > limit:
            refuse('TIMING_AFTER_AUDIO', f'cue {source_index} would end at {end} ms, after the audio duration of {limit} ms (rounded up to a millisecond)', at,
                   'end the cue at or before the audio duration; the audio is never extended and the time is never clamped', index=source_index, endMs=end, audioDurationMs=limit)
        if start < previous:
            refuse('TIMING_OVERLAP', f'cue {source_index} would start at {start} ms, before the previous retained cue ends at {previous} ms', at,
                   'adjust this or the neighbouring cue so the finished cues are ordered and do not overlap (touching intervals are allowed); cues are never reordered or clamped',
                   index=source_index, startMs=start, previousEndMs=previous, previousSourceIndex=before)
        previous, before = end, source_index


def derive(p, draft):
    """Every publication, as exact bytes, from the captured draft bytes and the authored plan alone."""
    basis = sha(draft)
    if basis != p['basisSha256']:
        refuse('CORRECTIONS_STALE', 'the draft bytes differ from basisSha256; the edits were written against another draft', '$.basisSha256',
               'review the current draft again, then copy its sha256 into basisSha256 (and re-check every index and time); a changed draft is never edited silently',
               expected=p['basisSha256'], actual=basis)
    decoded = timed_text.strict_json(draft, '$.draft')
    view = timed_text.validate(decoded, '$.draft')
    if view['source'] != timed_text.SOURCE_VERSION:
        refuse('DRAFT_NOT_MACHINE_DRAFT', 'the draft is already a reviewed document; corrections apply to the original machine draft only', '$.draft.path',
               'edit the original machine segments.json again with all intended edits, so the reviewed document keeps one basis')
    source = [dict(segment) for segment in decoded['segments']]
    count = len(source)
    deletions = p.get('deletions', [])
    for number, index in enumerate(deletions):
        if index >= count:
            refuse('DELETION_INDEX_INVALID', f'cue {index} does not exist; the draft has {count} cues (0 to {count - 1})', f'$.deletions[{number}]',
                   'use a source cue index from the draft segments.json', index=index, cueCount=count)
    replacements = {}
    for number, item in enumerate(p.get('corrections', [])):
        at = f'$.corrections[{number}]'
        if item['index'] >= count:
            refuse('CORRECTION_INDEX_INVALID', f'cue {item["index"]} does not exist; the draft has {count} cues (0 to {count - 1})', at + '.index',
                   'use a cue index from the draft segments.json', index=item['index'], cueCount=count)
        if item['text'] == source[item['index']]['text']:
            refuse('CORRECTION_NOOP', 'the replacement equals the existing cue text', at + '.text',
                   'remove this entry, or declare human-reviewed-unchanged when no cue changes', index=item['index'])
        replacements[item['index']] = item['text']
    edits = {}
    for number, item in enumerate(p.get('timings', [])):
        at = f'$.timings[{number}]'
        if item['index'] >= count:
            refuse('TIMING_INDEX_INVALID', f'cue {item["index"]} does not exist; the draft has {count} cues (0 to {count - 1})', at + '.index',
                   'use an original source cue index from the draft segments.json (indices do not shift after deletions)', index=item['index'], cueCount=count)
        original = source[item['index']]
        if (item['startMs'], item['endMs']) == (original['startMs'], original['endMs']):
            refuse('TIMING_NOOP', 'the stated interval equals the cue\'s existing machine interval', at,
                   'remove this entry, or declare human-reviewed-unchanged when no cue changes', index=item['index'], startMs=item['startMs'], endMs=item['endMs'])
        edits[item['index']] = {'startMs': item['startMs'], 'endMs': item['endMs'], 'number': number}
    gone = set(deletions)
    retained_sources = [i for i in range(count) if i not in gone]
    final_times(source, retained_sources, edits, timed_text.audio_limit(decoded['audio']))
    cues = [{'index': published_index, 'startMs': edits[i]['startMs'] if i in edits else source[i]['startMs'],
             'endMs': edits[i]['endMs'] if i in edits else source[i]['endMs'], 'text': replacements.get(i, source[i]['text'])}
            for published_index, i in enumerate(retained_sources)]
    final = sum(len(c['text']) for c in cues)
    if final > timed_text.MAX_TOTAL_CHARACTERS:
        growth = {number: len(item['text']) - len(source[item['index']]['text']) for number, item in enumerate(p['corrections'])}
        number = max(growth, key=lambda n: (growth[n], -n))
        refuse('TIMED_TEXT_RESOURCE_LIMIT', f'the corrected transcript would hold {final} characters; the limit is {timed_text.MAX_TOTAL_CHARACTERS} in total, and this replacement adds the most ({growth[number]})',
               f'$.corrections[{number}].text', f'shorten this replacement or the other replacements, or delete cues, so the corrected transcript stays within {timed_text.MAX_TOTAL_CHARACTERS} characters',
               characters=final, limit=timed_text.MAX_TOTAL_CHARACTERS, index=p['corrections'][number]['index'])
    if wants_review(p) and not cues:
        refuse('CAPTION_REVIEW_EMPTY', 'captionReview needs at least one retained cue; every cue is deleted', '$.captionReview',
               'omit captionReview, or keep at least one cue: a caption review of no cues would read as a pass')
    corrected, retimed = sorted(replacements), sorted(edits)
    reviewed = {k: decoded[k] for k in ('language', 'timeUnit', 'audio', 'model', 'nativeJsonSha256')}
    reviewed.update({'version': timed_text.REVIEWED3_VERSION, 'segmentCount': len(cues), 'segments': cues})
    if 'segmentation' in decoded:
        reviewed['segmentation'] = {**decoded['segmentation'], 'statement': SEGMENTATION_STATEMENT, 'cueCount': len(cues),
                                    'cuesOverTarget': sum(len(c['text']) > decoded['segmentation']['maxSegmentLength'] for c in cues)}
    reviewed['review'] = {
        'status': p['review']['status'], 'accuracyCertified': False, 'identityVerified': False, 'synchronizationCertified': False,
        'statement': STATEMENT, 'note': p['review']['note'],
        'basis': {'version': timed_text.SOURCE_VERSION, 'sha256': basis, 'bytes': len(draft), 'cueCount': count},
        'correctionCount': len(corrected), 'correctedIndices': corrected, 'deletionCount': len(gone), 'deletedSourceIndices': sorted(gone),
        'retainedSourceIndices': retained_sources, 'timingEditCount': len(retimed), 'timingEditedIndices': retimed,
        'originalTimings': [{'sourceIndex': i, 'startMs': source[i]['startMs'], 'endMs': source[i]['endMs']} for i in retained_sources],
        'timingPolicy': TIMING_POLICY, 'policy': dict(decoded['review']['policy'])}
    timed_text.validate(reviewed, '$.reviewed')
    reviewed_bytes = timed_text.canonical_json(reviewed)
    ledger_document = {
        'version': LEDGER_VERSION, 'status': p['review']['status'], 'note': p['review']['note'],
        'basis': {'version': timed_text.SOURCE_VERSION, 'sha256': basis, 'bytes': len(draft), 'cueCount': count},
        'reviewedVersion': timed_text.REVIEWED3_VERSION, 'reviewedSha256': sha(reviewed_bytes),
        'language': reviewed['language'], 'audioSha256': reviewed['audio']['sha256'], 'modelSha256': reviewed['model']['sha256'],
        'sourceCueCount': count, 'publishedCueCount': len(cues), 'correctionCount': len(corrected), 'deletionCount': len(gone),
        'timingEditCount': len(retimed), 'unchangedCueCount': sum(i not in replacements and i not in edits for i in retained_sources),
        'timingPolicy': TIMING_POLICY,
        'replacements': [{'sourceIndex': i, 'publishedIndex': retained_sources.index(i),
                          'originalStartMs': source[i]['startMs'], 'originalEndMs': source[i]['endMs'],
                          'startMs': cues[retained_sources.index(i)]['startMs'], 'endMs': cues[retained_sources.index(i)]['endMs'],
                          'original': source[i]['text'], 'replacement': replacements[i]} for i in corrected],
        'timingEdits': [{'sourceIndex': i, 'publishedIndex': retained_sources.index(i), 'originalStartMs': source[i]['startMs'], 'originalEndMs': source[i]['endMs'],
                         'startMs': edits[i]['startMs'], 'endMs': edits[i]['endMs'], 'text': replacements.get(i, source[i]['text'])} for i in retimed],
        'deletions': [{'sourceIndex': i, 'originalStartMs': source[i]['startMs'], 'originalEndMs': source[i]['endMs'], 'original': source[i]['text']} for i in sorted(gone)],
        'retained': [{'publishedIndex': n, 'sourceIndex': i, 'originalStartMs': source[i]['startMs'], 'originalEndMs': source[i]['endMs'],
                      'startMs': cues[n]['startMs'], 'endMs': cues[n]['endMs'], 'original': source[i]['text'], 'text': cues[n]['text'],
                      'edited': i in replacements, 'retimed': i in edits} for n, i in enumerate(retained_sources)],
        'accuracyCertified': False, 'identityVerified': False, 'synchronizationCertified': False, 'statement': LEDGER_STATEMENT}
    outputs = {REVIEWED: reviewed_bytes, TRANSCRIPT: timed_text.plain_text(cues).encode('utf-8'), SRT: timed_text.srt_text(cues).encode('utf-8'),
               VTT: timed_text.vtt_text(cues).encode('utf-8'), LEDGER: timed_text.canonical_json(ledger_document)}
    if wants_review(p): outputs[caption_review.FILE] = timed_text.canonical_json(caption_review.build(reviewed, sha(reviewed_bytes)))
    return outputs, ledger_document, reviewed


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
        declared = view['review']
        if (view['source'] != timed_text.REVIEWED3_VERSION or view['status'] != p['review']['status'] or declared['basisSha256'] != p['basisSha256']
                or declared['deletedSourceIndices'] != sorted(p.get('deletions', [])) or declared['timingEditedIndices'] != sorted(t['index'] for t in p.get('timings', []))
                or declared['sourceCueCount'] != ledger['sourceCueCount']):
            refuse('VERIFICATION_FAILED', 'reviewed version, status, basis, deletions or timing edits differ from the authored declaration', REVIEWED, 'rerun from the declared input')
        if receipt['artifacts'] != artifacts(directory, wants_review(p)): refuse('VERIFICATION_FAILED', 'correction publication membership/digest differs', 'verification.json', 'rerun')
        if set(receipt['evidence']) != evidence_names() or any(digest(directory, n) != receipt['evidence'][n] for n in evidence_names()):
            refuse('VERIFICATION_FAILED', 'retained correction evidence differs', 'verification.json', 'rerun from the declared input')
        fresh = {'verified': True, 'artifacts': len(published(wants_review(p))), 'runtime': RUNTIME, 'nativeProcesses': 0, 'reviewStatus': p['review']['status'],
                 'cues': len(reviewed['segments']), 'sourceCues': ledger['sourceCueCount'], 'corrections': ledger['correctionCount'], 'deletions': ledger['deletionCount'],
                 'timingEdits': ledger['timingEditCount'], 'basisSha256': p['basisSha256'], 'reviewedSha256': ledger['reviewedSha256'],
                 'accuracyCertified': False, 'identityVerified': False, 'synchronizationCertified': False}
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
