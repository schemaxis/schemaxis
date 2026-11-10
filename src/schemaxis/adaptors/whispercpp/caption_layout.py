"""Host-only explicit line layout of a retained whisper.cpp timed transcript for SRT and WebVTT.

This route never launches whisper-cli and reads no audio or model. It captures one pinned timed-text document (a machine
``segments.json`` or a ``schemaxis.timedtext.reviewed/1``, ``/2`` or ``/3`` document, read by the shared closed validator), and publishes
``captions.srt``, ``captions.vtt`` and ``caption-layout.json`` in which every cue text is broken into at most ``maxLines`` lines of
at most ``maxLineCodePoints`` Unicode code points.

A line break replaces one isolated ordinary space (U+0020), a single space with no ordinary space next to it, and nothing else. A run of two or more
adjacent ordinary spaces is never broken or normalised: it stays inside one indivisible unit together with the characters around it. Words, their
order, case and punctuation, every cue index and every start and end millisecond are carried over exactly, no cue is split, merged, retimed or
reordered, and joining the lines of a cue with one space restores the source cue text byte for byte.

Per cue the layout is chosen by three fixed rules: the fewest lines, then the smallest sum of squared line lengths (so lines are as even as
the words allow), then the earliest first break (and the earliest second break). The search is a dynamic program over at most 128 words
(a cue holds at most 256 code points), at most three lines and at most 40 words per line, so its work is bounded before any file is read.
An unbreakable run (a word, or words joined by a no-break space or by two or more adjacent ordinary spaces) longer than ``maxLineCodePoints`` and a
cue that needs more than ``maxLines`` lines are refused naming the cue; nothing is split inside a run, truncated or allowed to exceed a bound.

Lengths count Unicode code points of the source text (spaces, punctuation and combining marks each once). They are not grapheme clusters, display
width, font metrics, readability or accessibility guarantees, and a script written without spaces can be refused although it looks narrow. The review
status and language of the source are the source author's declarations and are carried unchanged; this route can promote none of them.

Every run and every verification replays the whole derivation from the captured source bytes and the authored bounds, so refreshed ordinary
hashes cannot hide an altered publication. A coherently rewritten set of captures and claims is only new consistent data, not signed authentication.
"""
import hashlib
import math
import os
from pathlib import Path
import re
import stat
import time

from schemaxis.adaptors.whispercpp import corrections as retained
from schemaxis.artifacts import atomic_json
from schemaxis.core import timed_text
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.dispatch import cancellation_requested

VERSION = 'schemaxis.whispercpp.captions/1'
PLAN_VERSION = 'schemaxis.whispercpp.caption-layout-plan/1'
LAYOUT_VERSION = 'schemaxis.whispercpp.caption-layout/1'
OPERATION = 'layout'
RUNTIME = 'host-only'
SRT = 'captions.srt'
VTT = 'captions.vtt'
LAYOUT = 'caption-layout.json'
CAPTURED = 'captured-source.json'
LIMIT = timed_text.MAX_DOCUMENT_BYTES
MIN_WIDTH, MAX_WIDTH = 8, 80
MIN_LINES, MAX_LINES = 1, 3
TOP = ('version', 'operation', 'source', 'sourceSha256', 'maxLineCodePoints', 'maxLines')
SHA = {'type': 'string', 'minLength': 64, 'maxLength': 64}
OPTIONS = {
    'source': {'type': 'object', 'required': True, 'properties': {'path': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}}},
    'sourceSha256': {**SHA, 'required': True},
    'maxLineCodePoints': {'type': 'integer', 'minimum': MIN_WIDTH, 'maximum': MAX_WIDTH, 'required': True},
    'maxLines': {'type': 'integer', 'minimum': MIN_LINES, 'maximum': MAX_LINES, 'required': True}}
POLICY = {
    'kind': 'deterministic word-boundary line layout; not a standard, a conformance test or a certification',
    'breakOpportunity': 'only an isolated ordinary space (U+0020), one with no ordinary space next to it; a run of two or more adjacent ordinary spaces, a no-break space, an ideographic space and every other character belong to their unbreakable run',
    'textLength': 'Unicode code points of the source cue text, counting spaces, punctuation and combining marks once each; not grapheme clusters, display width, font metrics or readability; no markup or WebVTT escaping is counted',
    'objective': ['fewest lines', 'smallest sum of squared line lengths in code points', 'earliest first break, then earliest second break'],
    'join': 'joining the lines of a cue with one space restores the source cue text exactly; adjacent ordinary spaces are kept inside their unbreakable run, never normalised, trimmed or broken',
    'unchanged': 'cue index, start and end milliseconds, order, count and every word are carried over exactly; no cue is split, merged, retimed or reordered',
    'srt': 'plain payload lines exactly as in the other SRT publications: no markup is added or escaped, and how a player interprets the text is not certified',
    'vtt': 'each line escapes & < > exactly once and line breaks are kept; no cue settings, styles, voices or speaker labels are written',
    'refusal': 'an unbreakable run longer than maxLineCodePoints or a cue that needs more than maxLines lines is refused naming the cue; nothing is split inside a run, truncated, retimed or widened'}
STATEMENT = ('The review status, the language and the audio and model digests are carried unchanged from the pinned source document, whose status is a '
             'declaration by its author. This layout only moves line breaks between words. It does not verify who reviewed the transcript, hear the audio, '
             'change a word or a time, or certify recognition accuracy, readability, accessibility or audio synchronization; a person must still review the captions.')
CLAIMS = {'humanReviewRequired': True, 'accuracyCertified': False, 'readabilityCertified': False, 'accessibilityCertified': False,
          'synchronizationCertified': False, 'identityVerified': False}
LOSSES = [
    'Host-only: whisper-cli is never launched and no audio, model or recognition run is read or repeated. Only the pinned source bytes and the two authored line bounds are used.',
    f'The source must be a machine {timed_text.SOURCE_VERSION} or a {timed_text.REVIEWED_VERSION}, {timed_text.REVIEWED2_VERSION} or {timed_text.REVIEWED3_VERSION} document read by the shared closed validator '
    f'({timed_text.MAX_DOCUMENT_BYTES} bytes, {timed_text.MAX_CUES} cues, {timed_text.MAX_CUE_CHARACTERS} characters per cue, {timed_text.MAX_TOTAL_CHARACTERS} in total). Its status is carried unchanged and is never promoted.',
    'Only line breaks change: a break replaces one isolated ordinary space. Words, cue indexes, start and end milliseconds and cue count are preserved exactly; nothing is split, merged, retimed, reordered or reworded, and there are no cue settings, styles, positions or speaker labels.',
    'Line length counts Unicode code points of the source text, never grapheme clusters, display width, font metrics or readability. An unbreakable run longer than maxLineCodePoints (a long word, words joined by a no-break space or by two or more adjacent ordinary spaces, or a long run of a script written without spaces) or a cue needing more than maxLines lines is refused naming the cue, never split or truncated.',
    'A run of two or more adjacent ordinary spaces is never broken, trimmed or normalised: it stays inside its unbreakable run, so a cue that fits is published as it is and a longer run can make a cue refuse. SRT payload lines are plain text and WebVTT payload lines escape & < > once; neither is a certification of how a player renders them.',
    'A source with no cues (every cue of a reviewed/2 or reviewed/3 draft deleted) publishes an empty SRT and a WebVTT header; no cue is invented. Review status, accuracy, readability, accessibility and audio synchronization are not verified or certified.']


def refuse(code, message, location, recovery, **observed):
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed, recovery=recovery))


def plan(document):
    retained.exact(document, TOP, '$', 'use only the declared members of the caption layout document')
    if document.get('version') != VERSION:
        refuse('UNSUPPORTED_VERSION', 'expected ' + VERSION, '$.version', 'set version to ' + VERSION)
    if document.get('operation') != OPERATION:
        refuse('UNKNOWN_OPERATION', 'select ' + OPERATION, '$.operation', 'set operation to ' + OPERATION)
    if 'source' in document: retained.exact(document['source'], ('path',), '$.source', 'name only source.path; pin the bytes with sourceSha256')
    try: p = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS}, location='$')
    except SchemaxisError as error:
        fault = error.fault
        if fault.recovery: raise
        raise SchemaxisError(Fault(fault.code, fault.message, fault.location, fault.phase, observed=fault.observed,
                                   recovery=f'correct the value at {fault.location}; see docs/whispercpp.md#caption-line-layout for the closed layout document')) from None
    path = p['source']['path']
    if '\0' in path or not path.startswith('/') or '..' in Path(path).parts or Path(path).suffix.lower() != '.json':
        refuse('INVALID_SOURCE', 'select an absolute local .json path without parent references', '$.source.path',
               'point at the segments.json or reviewed-segments.json that a whisper.cpp route published (or hand it over as a workflow text artifact)')
    if not timed_text.HEX.fullmatch(p['sourceSha256']):
        refuse('INVALID_SHA256', 'use 64 lowercase hexadecimal digits', '$.sourceSha256', 'copy the sha256 of the source document you reviewed')
    return {'version': PLAN_VERSION, 'operation': OPERATION, **p, 'losses': list(LOSSES)}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, 'operation': {'const': OPERATION}, **{k: argument_schema(v) for k, v in OPTIONS.items()}},
                                              ['version', 'operation', 'source', 'sourceSha256', 'maxLineCodePoints', 'maxLines'])}


def query(document): plan(document); return [OPERATION], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1: refuse('INVALID_EXECUTION', 'caption layout runs serially on the host', identity, 'omit threads or use 1')
    return {'threads': 1}


def sha(data): return hashlib.sha256(data).hexdigest()


def bounded(path, code='VERIFICATION_FAILED', missing=None):
    """Hold the bytes of one regular file (final component never a link, never a device, directory or FIFO) within the byte budget.

    The descriptor is statted before and after the read, so a file that changes while it is held is refused. `missing` names a distinct fault for an absent path."""
    recovery = f'use a regular file of at most {LIMIT} bytes (no symbolic link, device, directory or FIFO)'
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > LIMIT: raise ValueError('not a bounded regular file')
            data = stream.read(LIMIT + 1)
            after = os.fstat(stream.fileno())
        if len(data) > LIMIT or len(data) != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError('file changed while it was read or exceeds the byte budget')
        return data
    except (FileNotFoundError, NotADirectoryError) as error:
        if missing:
            refuse(missing, 'the source document does not exist: ' + str(error.strerror or error).lower(), str(path),
                   'point source.path at the segments.json or reviewed-segments.json that a whisper.cpp route published; a missing file is not repaired or replaced')
        refuse(code, 'select an intact regular file within the byte budget: ' + str(error), str(path), recovery)
    except (OSError, ValueError) as error:
        refuse(code, 'select an intact regular file within the byte budget: ' + str(error), str(path), recovery)


def reusableInputs(document):
    p = plan(document)
    return {'source': sha(bounded(p['source']['path'], 'INVALID_SOURCE', 'SOURCE_MISSING'))}


def break_cue(text, width, lines, index):
    """The lines of one cue, chosen by the fixed objective, or a refusal naming the cue. Joining the result with one space restores `text`."""
    at = f'$.source.segments[{index}].text'
    if len(text) <= width: return [text]
    # Only a single space with no ordinary space on either side is a break opportunity; every unit starts and ends with a non-space character.
    words = re.split(r'(?<! ) (?! )', text)
    sizes = [len(word) for word in words]
    count = len(words)
    longest = max(range(count), key=lambda number: (sizes[number], -number))
    if sizes[longest] > width:
        refuse('LAYOUT_WORD_TOO_LONG', f'cue {index} holds an unbreakable run of {sizes[longest]} code points, longer than maxLineCodePoints {width}', at,
               'raise maxLineCodePoints, or correct the source text to break the run with single spaces; a run (a word, or words joined by a no-break space or '
               'by two or more adjacent ordinary spaces) is never split here',
               cue=index, word=longest, wordCodePoints=sizes[longest], maxLineCodePoints=width)
    prefix = [0]
    for size in sizes: prefix.append(prefix[-1] + size)

    def span(first, last): return prefix[last] - prefix[first] + last - first - 1

    needed, first = 0, 0
    while first < count:
        last = first + 1
        while last < count and span(first, last + 1) <= width: last += 1
        needed, first = needed + 1, last
    if needed > lines:
        refuse('LAYOUT_TOO_MANY_LINES', f'cue {index} needs {needed} lines of at most {width} code points, but maxLines is {lines}', at,
               'raise maxLines or maxLineCodePoints; the cue is never truncated, split or retimed', cue=index, linesNeeded=needed, maxLines=lines, maxLineCodePoints=width)
    # best[k][i]: the least sum of squared line lengths that puts words i.. on exactly k lines, or None when impossible.
    best = [[None] * (count + 1) for _ in range(needed + 1)]
    best[0][count] = 0
    for k in range(1, needed + 1):
        for first in range(count - 1, -1, -1):
            for last in range(first + 1, count + 1):
                length = span(first, last)
                if length > width: break
                rest = best[k - 1][last]
                if rest is not None and (best[k][first] is None or length * length + rest < best[k][first]): best[k][first] = length * length + rest
    result, first = [], 0
    for k in range(needed, 0, -1):
        for last in range(first + 1, count + 1):
            length = span(first, last)
            if length > width: break
            if best[k - 1][last] is not None and length * length + best[k - 1][last] == best[k][first]:
                result.append(' '.join(words[first:last]))
                first = last
                break
    if first != count or ' '.join(result) != text or len(result) != needed or any(len(line) > width for line in result):
        refuse('LAYOUT_INVARIANT', f'cue {index} produced a layout that does not restore the source text within the bounds', at, 'report this defect; no caption is published', cue=index)
    return result


def derive(p, source, checkpoint=None):
    """Every publication, as exact bytes, from the captured source bytes and the authored bounds alone."""
    basis = sha(source)
    if basis != p['sourceSha256']:
        refuse('LAYOUT_SOURCE_STALE', 'the source bytes differ from sourceSha256; the layout was authored against another document', '$.sourceSha256',
               'review the current document, then copy its sha256 into sourceSha256; a changed source is never laid out silently', expected=p['sourceSha256'], actual=basis)
    view = timed_text.validate(timed_text.strict_json(source, '$.source'), '$.source')
    width, lines = p['maxLineCodePoints'], p['maxLines']
    laid, published = [], []
    for index, cue in enumerate(view['cues']):
        if checkpoint: checkpoint()
        broken = break_cue(cue['text'], width, lines, index)
        laid.append({'index': index, 'startMs': cue['startMs'], 'endMs': cue['endMs'], 'text': cue['text'], 'lines': broken,
                     'lineCodePoints': [len(line) for line in broken], 'reflowed': len(broken) > 1})
        published.append({'startMs': cue['startMs'], 'endMs': cue['endMs'], 'text': '\n'.join(broken)})
    review = view.get('review')
    summary = {
        'version': LAYOUT_VERSION,
        'source': {'version': view['source'], 'bytes': len(source), 'sha256': basis, 'basisSha256': review['basisSha256'] if review else None},
        'status': view['status'], 'language': view['language'], 'audioSha256': view['audioSha256'], 'modelSha256': view['modelSha256'], 'durationMs': view['durationMs'],
        'bounds': {'maxLineCodePoints': width, 'maxLines': lines}, 'policy': dict(POLICY),
        'cueCount': len(laid), 'reflowedCueCount': sum(cue['reflowed'] for cue in laid), 'lineCount': sum(len(cue['lines']) for cue in laid), 'cues': laid,
        'review': {**CLAIMS, 'statement': STATEMENT}}
    outputs = {SRT: timed_text.srt_text(published).encode('utf-8'), VTT: timed_text.vtt_text(published).encode('utf-8'), LAYOUT: timed_text.canonical_json(summary)}
    return outputs, summary


def published(): return (SRT, VTT, LAYOUT)
def kinds(): return {SRT: 'file', VTT: 'file', LAYOUT: 'text'}
def evidence_names(): return {'authored.json', 'plan.json', 'captures.json', CAPTURED}


def digest(directory, name): return sha(bounded(directory / name))


def artifacts(directory):
    return [{'file': str(directory / n), 'kind': kinds()[n], 'sha256': digest(directory, n)} for n in published()]


def membership(directory):
    """Only host evidence and publications: a launcher, submission or native log is itself a failure."""
    from schemaxis.run_paths import MANIFEST
    expected = evidence_names() | {*published(), 'verification.json', 'result.json', 'schema.snapshot.json', MANIFEST, 'job.json'}
    expected |= {name + '.metadata.json' for name in published()}
    for path in directory.iterdir():
        # `.dispatch` is not exempt: this route never creates it, so any content there was planted and is never read or run.
        if path.name not in expected or path.is_symlink() or not path.is_file():
            refuse('VERIFICATION_FAILED', 'unexpected or nonregular retained layout member (a host-only run holds no native evidence)', path.name, 'rerun from the declared input in a fresh directory')


def read_json(directory, name): return retained.read_json(directory, name)
def same_json(actual, expected): return retained.same_json(actual, expected)


def run(document, directory, *, executable=None, timeout=300):
    """`executable` is accepted for the shared runner and never used: no native process exists on this route."""
    p = plan(document)
    if type(timeout) not in (int, float) or isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        refuse('INVALID_ARGUMENT', 'timeout must be finite in (0,3600]', '$.timeout', 'use a finite number of seconds')
    deadline = time.monotonic() + timeout
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): refuse('OUTPUT_EXISTS', 'select a fresh output directory', str(directory), 'choose a new output directory')

    def checkpoint():
        if cancellation_requested(): refuse('RUNNER_CANCELLED', 'caption layout cancelled', '$', 'rerun when ready; no partial publication is kept as verified')
        if time.monotonic() >= deadline: refuse('RUNNER_TIMED_OUT', 'caption layout exhausted its total deadline', '$', 'rerun with a longer timeout or a shorter transcript')

    directory.mkdir(parents=True); atomic_json(directory / 'authored.json', document); atomic_json(directory / 'plan.json', p)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    try:
        checkpoint()
        source = bounded(p['source']['path'], 'INVALID_SOURCE', 'SOURCE_MISSING')
        (directory / CAPTURED).write_bytes(source)
        atomic_json(directory / 'captures.json', {'source': p['source']['path'], 'sha256': sha(source), 'bytes': len(source)})
        outputs, _ = derive(p, source, checkpoint)
        for name, data in outputs.items(): (directory / name).write_bytes(data)
        try: again = bounded(p['source']['path'], 'INVALID_SOURCE', 'SOURCE_MISSING')
        except SchemaxisError as error:
            refuse('LAYOUT_SOURCE_CHANGED', 'the source document could no longer be read after the layout was derived', '$.source.path',
                   'rerun from the current document; nothing was published as verified', cause=error.fault.to_dict())
        if again != source:
            refuse('LAYOUT_SOURCE_CHANGED', 'the source document changed while the layout was derived; the held bytes are not the file any more', '$.source.path',
                   'rerun from the current document and copy its new sha256 into sourceSha256 after reviewing it')
        checkpoint()
        atomic_json(directory / 'verification.json', {'runtime': RUNTIME, 'artifacts': artifacts(directory),
                                                      'evidence': {n: digest(directory, n) for n in sorted(evidence_names())}})
        result = verify(directory, require_result=False)
        result['status'] = 'succeeded'; atomic_json(directory / 'result.json', result); return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try: refuse('LAYOUT_FAILED', str(error), '$', 'rerun from the declared input')
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()}); raise error


def verify(directory, require_result=True):
    """Semantic replay: derive every publication again from the captured bytes and authored bounds; nothing stored is trusted."""
    directory = Path(directory).absolute()
    try:
        p = plan(read_json(directory, 'authored.json')); receipt = read_json(directory, 'verification.json')
        if not isinstance(receipt, dict) or set(receipt) != {'runtime', 'artifacts', 'evidence'} or receipt['runtime'] != RUNTIME or not isinstance(receipt['evidence'], dict):
            refuse('VERIFICATION_FAILED', 'host-only receipt member set differs', 'verification.json', 'rerun from the declared input')
        if not same_json(read_json(directory, 'plan.json'), p): refuse('VERIFICATION_FAILED', 'effective layout plan differs', 'plan.json', 'rerun from the declared input')
        if require_result and read_json(directory, 'result.json').get('status') != 'succeeded': refuse('INCOMPLETE_EXECUTION', 'caption layout did not complete', 'result.json', 'rerun')
        membership(directory)
        source = bounded(directory / CAPTURED)
        if not same_json(read_json(directory, 'captures.json'), {'source': p['source']['path'], 'sha256': sha(source), 'bytes': len(source)}):
            refuse('VERIFICATION_FAILED', 'source/capture binding differs', 'captures.json', 'rerun from the declared input')
        outputs, summary = derive(p, source)
        for name, data in outputs.items():
            if bounded(directory / name) != data:
                refuse('VERIFICATION_FAILED', 'publication differs from independent replay of the captured source and authored bounds', name, 'rerun from the declared input; a published file was altered')
        if receipt['artifacts'] != artifacts(directory): refuse('VERIFICATION_FAILED', 'layout publication membership/digest differs', 'verification.json', 'rerun')
        if set(receipt['evidence']) != evidence_names() or any(digest(directory, n) != receipt['evidence'][n] for n in evidence_names()):
            refuse('VERIFICATION_FAILED', 'retained layout evidence differs', 'verification.json', 'rerun from the declared input')
        fresh = {'verified': True, 'artifacts': len(published()), 'runtime': RUNTIME, 'nativeProcesses': 0, 'sourceVersion': summary['source']['version'],
                 'sourceSha256': p['sourceSha256'], 'reviewStatus': summary['status'], 'cues': summary['cueCount'], 'reflowedCues': summary['reflowedCueCount'],
                 'lines': summary['lineCount'], 'maxLineCodePoints': p['maxLineCodePoints'], 'maxLines': p['maxLines'], **CLAIMS}
        if require_result and not same_json(read_json(directory, 'result.json'), {**fresh, 'status': 'succeeded'}):
            refuse('VERIFICATION_FAILED', 'retained result differs from independent replay', 'result.json', 'rerun from the declared input')
        return fresh
    except SchemaxisError as error:
        if error.fault.code in ('VERIFICATION_FAILED', 'INCOMPLETE_EXECUTION'): raise
        refuse('VERIFICATION_FAILED', 'retained layout evidence violates its contract (' + error.fault.code + ')', error.fault.location, 'rerun from the declared input', cause=error.fault.to_dict())
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeDecodeError, RecursionError) as error:
        refuse('VERIFICATION_FAILED', 'invalid retained layout evidence: ' + str(error), str(directory), 'rerun from the declared input')


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
