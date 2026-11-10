"""Host-only human corrections of a retained whisper.cpp machine draft, with explicit cue deletion.

This is the separately versioned successor route ``schemaxis.whispercpp.correct/2``; the text-only route
``schemaxis.whispercpp.correct/1`` (``corrections.py``) is unchanged. Like it, this route never launches whisper-cli and
reads no audio or model. It captures one pinned machine ``segments.json``, applies authored per-cue text replacements and
authored deletions of whole cues by unique source index, and publishes the new closed reviewed contract
(``schemaxis.timedtext.reviewed/2``), plain text, SRT, WebVTT and an exact ledger.

A deleted cue is removed from every publication and the retained cues are renumbered contiguously from zero as published;
the ledger maps each published index back to its source index and keeps the original text and timing of every deleted
cue. Timings of retained cues are carried over untouched. Deleting every cue of a nonempty pinned draft is allowed only
through this explicit, validated route and publishes an empty transcript, an empty SRT and a bare WebVTT header. An original
machine draft with no cues is still refused by the shared reader, and a reviewed document is still refused as a draft.

The review status is a declaration by the author of the corrections. Nothing here verifies who reviewed the transcript, that
the audio was heard or that a deletion was right, so every publication says so. Every run and every verification replays the
whole derivation from the captured draft bytes and the authored edits, so refreshed ordinary hashes cannot hide an altered
publication.
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

VERSION = 'schemaxis.whispercpp.correct/2'
PLAN_VERSION = 'schemaxis.whispercpp.correction-plan/2'
LEDGER_VERSION = 'schemaxis.whispercpp.corrections/2'
RUNTIME = 'host-only'
MAX_CORRECTIONS = timed_text.MAX_CUES
STATUSES = timed_text.REVIEWED_STATUSES
TOP = ('version', 'draft', 'basisSha256', 'review', 'corrections', 'deletions', 'captionReview')
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
    'captionReview': {'type': 'boolean', 'default': False}}
STATEMENT = ('The review status is a declaration recorded from the author of the correction document. Schemaxis did not verify who reviewed '
             'the transcript, that the audio was heard, or that any replacement, deletion or timing is correct; recognition accuracy, reviewer '
             'identity and caption accessibility are not certified. A deleted cue is removed from the publications, not proved to be a mistake.')
SEGMENTATION_STATEMENT = ('maxSegmentLength was a native segmentation target for the machine draft, not a guaranteed maximum or a readability '
                          'certification. cueCount and cuesOverTarget are recounted on the retained, reviewed cues and over-target cues are published '
                          'unchanged; cue boundary times are the draft\'s experimental token-level timestamps and are not certified.')
LEDGER_STATEMENT = ('Exact record of the authored replacements and deletions against the pinned machine draft, with the source index, original text '
                    'and timing of every cue. It proves which cues changed or were removed, not that any edit is correct, who made it or that the '
                    'audio was reviewed.')
LOSSES = [
    'Host-only: whisper-cli is never launched and no audio, model or recognition run is read or repeated. Only the pinned draft segments.json bytes and the authored edits are used.',
    'Text replacement and whole-cue deletion by unique source index. Retained cues keep their timings, language and the audio, model and native-JSON provenance and are renumbered contiguously from zero; no timing edits, splits, merges or insertions.',
    f'The draft must be an unedited machine {timed_text.SOURCE_VERSION} within the shared timed-text budgets ({timed_text.MAX_CUES} cues, {timed_text.MAX_CUE_CHARACTERS} characters per cue, '
    f'{timed_text.MAX_TOTAL_CHARACTERS} in total). A reviewed document is not a draft, and the machine draft is never modified. A draft with no cues is refused.',
    'Deleting every cue of a nonempty draft is allowed only here: the reviewed document, the plain text and the SRT then hold no cues and the WebVTT holds only its header. This records an author\'s declaration that nothing remains to publish; it is not evidence that the recording is silent or that the original text was wrong.',
    'The status human-corrected or human-reviewed-unchanged is a declaration by the author and is recorded as provenance. Reviewer identity, hearing the audio, recognition accuracy, readability and accessibility are not verified or certified.']
EMPTY_LOSS = 'captionReview is refused when every cue is deleted: a caption review with no cues would read as a pass.'


def plan(document):
    exact(document, TOP, '$', 'use only the declared members of the correction document')
    if document.get('version') != VERSION:
        refuse('UNSUPPORTED_VERSION', 'expected ' + VERSION, '$.version', 'set version to ' + VERSION)
    if 'draft' in document: exact(document['draft'], ('path',), '$.draft', 'name only draft.path; pin the bytes with basisSha256')
    if 'review' in document: exact(document['review'], ('status', 'note'), '$.review', 'declare only review.status and review.note')
    listed = document.get('corrections')
    for number, item in enumerate(listed if isinstance(listed, list) else []):
        exact(item, ('index', 'text'), f'$.corrections[{number}]', 'a replacement is exactly {"index": N, "text": "replacement"}; a deletion is a bare source index in $.deletions; timings cannot be edited')
    try: p = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS}, location='$')
    except SchemaxisError as error:
        fault = error.fault
        if fault.recovery: raise
        raise SchemaxisError(Fault(fault.code, fault.message, fault.location, fault.phase, observed=fault.observed,
                                   recovery=f'correct the value at {fault.location}; see docs/whispercpp.md#cue-deletion for the closed correction document')) from None
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
    changed = bool(p.get('corrections') or p.get('deletions'))
    if (p['review']['status'] == 'human-corrected') != changed:
        refuse('CORRECTIONS_STATUS_CONFLICT', 'human-corrected needs at least one replacement or deletion and human-reviewed-unchanged needs neither',
               '$.review.status' if changed else '$.corrections',
               'declare human-reviewed-unchanged with no edits, or human-corrected with at least one replaced or deleted cue',
               corrections=len(p.get('corrections', [])), deletions=len(p.get('deletions', [])))
    if 'captionReview' not in document: p.pop('captionReview')
    return {'version': PLAN_VERSION, 'operation': 'correct', **p, 'losses': [*LOSSES, *([caption_review.LOSS, EMPTY_LOSS] if wants_review(p) else [])]}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, **{k: argument_schema(v) for k, v in OPTIONS.items()}},
                                              ['version', 'draft', 'basisSha256', 'review'])}


def query(document): plan(document); return ['correct'], {}


def reusableInputs(document):
    p = plan(document)
    return {'draft': hashlib.sha256(bounded(p['draft']['path'], 'INVALID_DRAFT_SOURCE', 'DRAFT_SOURCE_MISSING')).hexdigest()}


def derive(p, draft):
    """Every publication, as exact bytes, from the captured draft bytes and the authored plan alone."""
    basis = sha(draft)
    if basis != p['basisSha256']:
        refuse('CORRECTIONS_STALE', 'the draft bytes differ from basisSha256; the edits were written against another draft', '$.basisSha256',
               'review the current draft again, then copy its sha256 into basisSha256 (and re-check every index); a changed draft is never edited silently',
               expected=p['basisSha256'], actual=basis)
    decoded = timed_text.strict_json(draft, '$.draft')
    view = timed_text.validate(decoded, '$.draft')
    if view['source'] != timed_text.SOURCE_VERSION:
        refuse('DRAFT_NOT_MACHINE_DRAFT', 'the draft is already a reviewed document; corrections apply to the original machine draft only', '$.draft.path',
               'edit the original machine segments.json again with all intended replacements and deletions, so the reviewed document keeps one basis')
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
    gone = set(deletions)
    retained_sources = [i for i in range(count) if i not in gone]
    cues = [{'index': published_index, 'startMs': source[i]['startMs'], 'endMs': source[i]['endMs'], 'text': replacements.get(i, source[i]['text'])}
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
    corrected = sorted(replacements)
    reviewed = {k: decoded[k] for k in ('language', 'timeUnit', 'audio', 'model', 'nativeJsonSha256')}
    reviewed.update({'version': timed_text.REVIEWED2_VERSION, 'segmentCount': len(cues), 'segments': cues})
    if 'segmentation' in decoded:
        reviewed['segmentation'] = {**decoded['segmentation'], 'statement': SEGMENTATION_STATEMENT, 'cueCount': len(cues),
                                    'cuesOverTarget': sum(len(c['text']) > decoded['segmentation']['maxSegmentLength'] for c in cues)}
    reviewed['review'] = {
        'status': p['review']['status'], 'accuracyCertified': False, 'identityVerified': False, 'statement': STATEMENT, 'note': p['review']['note'],
        'basis': {'version': timed_text.SOURCE_VERSION, 'sha256': basis, 'bytes': len(draft), 'cueCount': count},
        'correctionCount': len(corrected), 'correctedIndices': corrected, 'deletionCount': len(gone), 'deletedSourceIndices': sorted(gone),
        'retainedSourceIndices': retained_sources, 'policy': dict(decoded['review']['policy'])}
    timed_text.validate(reviewed, '$.reviewed')
    reviewed_bytes = timed_text.canonical_json(reviewed)
    ledger_document = {
        'version': LEDGER_VERSION, 'status': p['review']['status'], 'note': p['review']['note'],
        'basis': {'version': timed_text.SOURCE_VERSION, 'sha256': basis, 'bytes': len(draft), 'cueCount': count},
        'reviewedVersion': timed_text.REVIEWED2_VERSION, 'reviewedSha256': sha(reviewed_bytes),
        'language': reviewed['language'], 'audioSha256': reviewed['audio']['sha256'], 'modelSha256': reviewed['model']['sha256'],
        'sourceCueCount': count, 'publishedCueCount': len(cues), 'correctionCount': len(corrected), 'deletionCount': len(gone),
        'unchangedCueCount': len(cues) - len(corrected),
        'replacements': [{'sourceIndex': i, 'publishedIndex': retained_sources.index(i), 'startMs': source[i]['startMs'], 'endMs': source[i]['endMs'],
                          'original': source[i]['text'], 'replacement': replacements[i]} for i in corrected],
        'deletions': [{'sourceIndex': i, 'startMs': source[i]['startMs'], 'endMs': source[i]['endMs'], 'original': source[i]['text']} for i in sorted(gone)],
        'retained': [{'publishedIndex': n, 'sourceIndex': i, 'startMs': source[i]['startMs'], 'endMs': source[i]['endMs'], 'original': source[i]['text'],
                      'text': cues[n]['text'], 'edited': i in replacements} for n, i in enumerate(retained_sources)],
        'accuracyCertified': False, 'identityVerified': False, 'statement': LEDGER_STATEMENT}
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
        if (view['source'] != timed_text.REVIEWED2_VERSION or view['status'] != p['review']['status'] or view['review']['basisSha256'] != p['basisSha256']
                or view['review']['deletedSourceIndices'] != sorted(p.get('deletions', [])) or view['review']['sourceCueCount'] != ledger['sourceCueCount']):
            refuse('VERIFICATION_FAILED', 'reviewed version, status, basis or deletions differ from the authored declaration', REVIEWED, 'rerun from the declared input')
        if receipt['artifacts'] != artifacts(directory, wants_review(p)): refuse('VERIFICATION_FAILED', 'correction publication membership/digest differs', 'verification.json', 'rerun')
        if set(receipt['evidence']) != evidence_names() or any(digest(directory, n) != receipt['evidence'][n] for n in evidence_names()):
            refuse('VERIFICATION_FAILED', 'retained correction evidence differs', 'verification.json', 'rerun from the declared input')
        fresh = {'verified': True, 'artifacts': len(published(wants_review(p))), 'runtime': RUNTIME, 'nativeProcesses': 0, 'reviewStatus': p['review']['status'],
                 'cues': len(reviewed['segments']), 'sourceCues': ledger['sourceCueCount'], 'corrections': ledger['correctionCount'], 'deletions': ledger['deletionCount'],
                 'basisSha256': p['basisSha256'], 'reviewedSha256': ledger['reviewedSha256'], 'accuracyCertified': False, 'identityVerified': False}
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
