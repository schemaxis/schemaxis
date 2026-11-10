"""Optional editorial caption review: fixed, transparent heuristics over checked segments.

The report is derived only from the host's independently checked segment document. It never
changes words or timing. The thresholds are this adaptor's editorial defaults, not requirements
of SRT, WebVTT or any accessibility standard, and a report with no flags certifies nothing.
"""
import json

from schemaxis.errors import fail

VERSION = 'schemaxis.whispercpp.caption-review/1'
FILE = 'caption-review.json'
SHORT_MS = 1000
LONG_MS = 7000
DENSE_CODE_POINTS_PER_SECOND = 20
FLAGS = ('short-duration', 'long-duration', 'dense-text')
STATEMENT = ('Flags are fixed editorial heuristics that suggest where to look first. They are not requirements of SRT, WebVTT or '
             'any accessibility standard. An absent flag, including a report with no flags at all, does not mean that the captions '
             'are accurate, readable, accessible or conformant: a person must review every caption against the audio regardless.')
LOSS = ('Optional caption review lists per-cue duration, Unicode code point count and rate with three fixed editorial flags; '
        'text length is counted in code points, not graphemes or display width. It neither alters nor certifies the captions.')
CUE = ('index', 'startMs', 'endMs', 'durationMs', 'codePoints', 'codePointsPerSecondMilli', 'flags')
POLICY = {
    'kind': 'fixed editorial heuristics; not a standard, a conformance test or a certification',
    'shortDurationBelowMs': SHORT_MS,
    'longDurationAboveMs': LONG_MS,
    'denseTextAboveCodePointsPerSecond': DENSE_CODE_POINTS_PER_SECOND,
    'textLength': 'Unicode code points of the published cue text, counting spaces and punctuation once each; not grapheme clusters, not display width, no markup or WebVTT escaping',
    'rate': 'codePointsPerSecondMilli = floor(codePoints * 1000000 / durationMs); dense when codePoints * 1000 > threshold * durationMs, in exact integer arithmetic'}
REVIEW = {'accuracyCertified': False, 'accessibilityCertified': False, 'readabilityCertified': False, 'passCertified': False,
          'humanReviewRequired': True, 'statement': STATEMENT}


def cue_flags(duration, code_points):
    flags = []
    if duration < SHORT_MS: flags.append('short-duration')
    if duration > LONG_MS: flags.append('long-duration')
    if code_points * 1000 > DENSE_CODE_POINTS_PER_SECOND * duration: flags.append('dense-text')
    return flags


def build(document, segments_sha256):
    """Pure, deterministic report from a checked segment document."""
    cues = []
    for segment in document['segments']:
        duration = segment['endMs'] - segment['startMs'];code_points = len(segment['text'])
        cues.append({'index': segment['index'], 'startMs': segment['startMs'], 'endMs': segment['endMs'], 'durationMs': duration,
                     'codePoints': code_points, 'codePointsPerSecondMilli': code_points * 1000000 // duration, 'flags': cue_flags(duration, code_points)})
    return {'version': VERSION, 'segmentsSha256': segments_sha256, 'cueCount': len(cues), 'flaggedCueCount': sum(1 for c in cues if c['flags']),
            'flagCounts': {f: sum(1 for c in cues if f in c['flags']) for f in FLAGS}, 'policy': dict(POLICY), 'cues': cues, 'review': dict(REVIEW)}


def summary(report):
    """Counts only; no value here can read as an overall pass."""
    return {'cues': report['cueCount'], 'flaggedCues': report['flaggedCueCount'], 'flagCounts': dict(report['flagCounts'])}


def whole(value): return type(value) is int


def closed(value, names, at):
    if not isinstance(value, dict) or set(value) != set(names): fail('VERIFICATION_FAILED', 'caption review has an unexpected member set', at, expected=sorted(names))
    return value


def check(actual, expected):
    """Strict structure first, then exact agreement with the independently rebuilt report."""
    root = closed(actual, tuple(expected), FILE + ' $')
    if not isinstance(root['version'], str) or not isinstance(root['segmentsSha256'], str): fail('VERIFICATION_FAILED', 'caption review identity must be text', FILE)
    if not all(whole(root[k]) for k in ('cueCount', 'flaggedCueCount')): fail('VERIFICATION_FAILED', 'caption review counts must be integers', FILE)
    counts = closed(root['flagCounts'], FLAGS, FILE + ' $.flagCounts')
    if not all(whole(v) for v in counts.values()): fail('VERIFICATION_FAILED', 'caption review flag counts must be integers', FILE + ' $.flagCounts')
    closed(root['policy'], tuple(expected['policy']), FILE + ' $.policy')
    for k, v in root['policy'].items():
        if type(v) is not type(expected['policy'][k]): fail('VERIFICATION_FAILED', 'caption review policy value has the wrong type', FILE + ' $.policy.' + k)
    review = closed(root['review'], tuple(expected['review']), FILE + ' $.review')
    for k, v in review.items():
        if type(v) is not type(expected['review'][k]): fail('VERIFICATION_FAILED', 'caption review claim has the wrong type', FILE + ' $.review.' + k)
    if not isinstance(root['cues'], list) or len(root['cues']) != len(expected['cues']): fail('VERIFICATION_FAILED', 'caption review cue membership differs from the checked segments', FILE + ' $.cues')
    for i, cue in enumerate(root['cues']):
        at = f'{FILE} $.cues[{i}]'
        closed(cue, CUE, at)
        if not all(whole(cue[k]) for k in CUE[:-1]): fail('VERIFICATION_FAILED', 'caption review metrics must be integers', at)
        if not isinstance(cue['flags'], list) or not all(isinstance(f, str) and f in FLAGS for f in cue['flags']): fail('VERIFICATION_FAILED', 'caption review flags must be known flag names', at + '.flags')
        for k in CUE:
            if cue[k] != expected['cues'][i][k]: fail('VERIFICATION_FAILED', 'caption review metric or flag differs from independent recomputation', f'{at}.{k}', observed=cue[k], expected=expected['cues'][i][k])
    if json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False): fail('VERIFICATION_FAILED', 'caption review differs from independent recomputation', FILE)
