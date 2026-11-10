"""Optional native caption segmentation target: honest semantics, host-side observation only.

`maxSegmentLength` maps to the whisper.cpp CLI options `-ml N -sow` and is a native TARGET. The host never
refuses a cue for exceeding it: official v1.9.5 `whisper_wrap_segment` splits only before a token that starts
with a space (so a word longer than N, or text in a script written without spaces, stays whole), counts
Unicode code points per token including that leading space, and places boundaries with experimental
token-level timestamps. The host only counts and reports the published cues that exceed the target.
"""

OPTION = 'maxSegmentLength'
MINIMUM = 16
MAXIMUM = 200
NATIVE = ('-ml', '-sow')
LOSS = ('Optional maxSegmentLength passes the native options -ml N -sow, a segmentation target and not a guaranteed maximum: whisper.cpp counts '
        'Unicode code points per token (UTF-8 lead bytes, not bytes, grapheme clusters or display width), counts each leading space, and splits only '
        'before a token that starts with a space, so a word longer than N and text in scripts written without spaces can exceed it; such cues are '
        'published and counted, never refused. Cue boundaries come from the experimental native token-level timestamps and are observed, not certified.')
STATEMENT = ('maxSegmentLength is a native segmentation target, not a guaranteed maximum or a readability certification. Cues over the target are '
             'published unchanged and counted. Cue boundaries come from the experimental native token-level timestamps and are not certified. '
             'The words are an unreviewed machine draft: a person must review every caption against the audio.')
COUNTING = ('Unicode code points of the published cue text, surrounding spaces removed. The native count also includes the leading space of each '
            'space-led token, so it is never lower than this count: a cue over the target here was over it natively too.')


def native_arguments(plan):
    """Extra whisper-cli arguments for a plan; empty when the option was not authored."""
    return [NATIVE[0], str(plan[OPTION]), NATIVE[1]] if OPTION in plan else []


def losses(plan):
    return [LOSS] if OPTION in plan else []


def observe(plan, segments):
    """The segments.json `segmentation` member, or None when the option was not authored."""
    if OPTION not in plan: return None
    target = plan[OPTION]
    over = sum(1 for s in segments if len(s['text']) > target)
    return {'maxSegmentLength': target, 'nativeOptions': [NATIVE[0], str(target), NATIVE[1]], 'enforced': False, 'unit': COUNTING,
            'cueCount': len(segments), 'cuesOverTarget': over, 'statement': STATEMENT}


def summary(member):
    """Counts only, for the verified result; nothing here can read as a pass."""
    return {'maxSegmentLength': member['maxSegmentLength'], 'cues': member['cueCount'], 'cuesOverTarget': member['cuesOverTarget'], 'enforced': False}
