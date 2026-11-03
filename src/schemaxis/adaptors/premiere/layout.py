# Copyright (C) 2026 David L F Gaden
"""Complete-track editorial layout contracts and independent frame coverage checks.

The planner converts authored frames to ticks. The verifier reconstructs a small
frame occupancy grid from observations; it never trusts a producer's coverage.
"""
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail, keys

NAME = {'type': 'string', 'minLength': 1, 'maxLength': 256, 'required': True}
FRAME = {'type': 'integer', 'minimum': 0, 'maximum': 599, 'required': True}
COUNT = {'type': 'integer', 'minimum': 1, 'maximum': 600, 'required': True}


def options(common):
    return {**{key: value for key, value in common.items() if key != 'clips'},
            'endFrame': COUNT,
            'tracks': {'type': 'array', 'minItems': 1, 'maxItems': 8, 'required': True,
                       'items': {'type': 'object', 'properties': {
                           'name': NAME,
                           'clips': {'type': 'array', 'minItems': 0, 'maxItems': 128, 'required': True,
                                     'items': {'type': 'object', 'properties': {
                                         **common['clips']['items']['properties'],
                                         'timelineFrame': FRAME}}}}}},
            'requirements': {'type': 'array', 'minItems': 0, 'maxItems': 32, 'default': [],
                             'items': {'type': 'object', 'properties': {
                                 'name': NAME,
                                 'tracks': {'type': 'array', 'minItems': 1, 'maxItems': 8, 'required': True,
                                            'items': {'type': 'string', 'minLength': 1, 'maxLength': 256}},
                                 'startFrame': FRAME,
                                 'frameCount': COUNT,
                                 'minimumActiveTracks': {'type': 'integer', 'minimum': 1, 'maximum': 8, 'default': 1}}}}}


def _name(value, where):
    if not value.strip() or any(ord(c) < 32 for c in value):
        fail('INVALID_SELECTION', 'use a nonblank name without control characters', where)


def plan(document, *, definitions, version, ticks, absolute, losses):
    keys(document, ('version', 'operation', *definitions), '$')
    if document.get('version') != version:
        fail('UNSUPPORTED_VERSION', 'expected ' + version)
    values = validate_arguments(definitions, {k: v for k, v in document.items() if k in definitions}, location='$')
    if values['fps'] not in (24, 25, 30, 50, 60):
        fail('INVALID_RATE', 'select integer 24, 25, 30, 50 or 60 fps', '$.fps')
    if not absolute(values['projectPath']):
        fail('INVALID_RESOURCE', 'native project identity must be an absolute path without NUL', '$.projectPath')
    _name(values['sequenceName'], '$.sequenceName')
    tick = ticks // values['fps']
    names, tracks, count, last = set(), [], 0, 0
    for index, track in enumerate(values['tracks']):
        where = '$.tracks[' + str(index) + ']'
        _name(track['name'], where + '.name')
        if track['name'] in names:
            fail('INVALID_SELECTION', 'complete layout track names must be unique', where + '.name')
        names.add(track['name'])
        clips, end = [], 0
        for i, clip in enumerate(track['clips']):
            loc = where + '.clips[' + str(i) + ']'
            if not absolute(clip['sourcePath']):
                fail('INVALID_RESOURCE', 'native source identity must be an absolute path without NUL', loc + '.sourcePath')
            start, duration = clip['timelineFrame'], clip['frameCount']
            if start < end:
                fail('INVALID_LAYOUT', 'list clips in timeline order without within-track overlap', loc + '.timelineFrame')
            end = start + duration
            if end > values['endFrame']:
                fail('INVALID_LAYOUT', 'clip exceeds declared exclusive sequence end', loc + '.frameCount')
            clips.append({'sourcePath': clip['sourcePath'], 'startTicks': str(start * tick),
                          'endTicks': str(end * tick), 'inTicks': str(clip['startFrame'] * tick),
                          'outTicks': str((clip['startFrame'] + duration) * tick),
                          'durationTicks': str(duration * tick)})
        count += len(clips)
        last = max(last, end)
        tracks.append({'index': index, 'name': track['name'], 'clips': clips})
    if not 1 <= count <= 128:
        fail('RESOURCE_LIMIT', 'complete layout requires 1..128 total clips', '$.tracks')
    if last != values['endFrame']:
        fail('INVALID_LAYOUT', 'exclusive sequence end must equal the latest clip end; empty tail padding is unsupported', '$.endFrame')
    labels = set()
    for index, requirement in enumerate(values['requirements']):
        where = '$.requirements[' + str(index) + ']'
        _name(requirement['name'], where + '.name')
        if requirement['name'] in labels:
            fail('INVALID_SELECTION', 'requirement names must be unique', where + '.name')
        labels.add(requirement['name'])
        selected = requirement['tracks']
        if len(set(selected)) != len(selected) or not set(selected) <= names:
            fail('INVALID_SELECTION', 'select distinct declared track names', where + '.tracks')
        if requirement['minimumActiveTracks'] > len(selected):
            fail('INVALID_LAYOUT', 'minimum active tracks exceeds selected track count', where + '.minimumActiveTracks')
        if requirement['startFrame'] + requirement['frameCount'] > values['endFrame']:
            fail('INVALID_LAYOUT', 'coverage range exceeds declared exclusive sequence end', where + '.frameCount')
    return {'version': 'schemaxis.premiere.plan/1', 'operation': 'sequenceLayout', 'options': values,
            'timebaseTicks': str(tick), 'endTicks': str(values['endFrame'] * tick),
            'frames': values['endFrame'], 'tracks': tracks, 'losses': losses}


def coverage(observation, authored):
    """Reconstruct editorial occupancy from exact native intervals, not plan ticks.

    Caller separately validates the closed observation and native identities.
    A nonintegral tick boundary is rejected rather than rounded onto a frame.
    """
    from .adaptor import TICKS, _ticks
    tick = TICKS // authored.get('fps', 25)
    frames = authored['endFrame']
    grids, summaries = {}, []
    for track in observation['tracks']:
        grid = [False] * frames
        for clip in track['clips']:
            parsed = {key: _ticks(clip[key], 'coverage.' + key) for key in
                      ('startTicks', 'endTicks', 'inTicks', 'outTicks', 'durationTicks')}
            if any(value % tick for value in parsed.values()):
                fail('CONTRACT_MISMATCH', 'native range is not aligned exactly to sequence frames')
            start, end = parsed['startTicks'] // tick, parsed['endTicks'] // tick
            duration = parsed['durationTicks']
            if not 0 <= start < end <= frames or duration != parsed['endTicks'] - parsed['startTicks'] or duration != parsed['outTicks'] - parsed['inTicks']:
                fail('CONTRACT_MISMATCH', 'positive normal-speed source and timeline lengths must agree')
            for frame in range(start, end):
                if grid[frame]:
                    fail('CONTRACT_MISMATCH', 'overlapping native items on one video track are unsupported')
                grid[frame] = True
        grids[track['name']] = grid
        gaps, cursor = [], 0
        while cursor < frames:
            if grid[cursor]:
                cursor += 1
                continue
            start = cursor
            while cursor < frames and not grid[cursor]:
                cursor += 1
            gaps.append({'startFrame': start, 'endFrame': cursor})
        summaries.append({'name': track['name'], 'occupiedFrames': sum(grid), 'gaps': gaps})
    checks = []
    for requirement in authored.get('requirements', []):
        start = requirement['startFrame']
        end = start + requirement['frameCount']
        minimum = requirement.get('minimumActiveTracks', 1)
        missing = [frame for frame in range(start, end)
                   if sum(grids[name][frame] for name in requirement['tracks']) < minimum]
        checks.append({'name': requirement['name'], 'startFrame': start, 'endFrame': end,
                       'minimumActiveTracks': minimum, 'uncoveredFrames': missing,
                       'passed': not missing})
    return {'version': 'schemaxis.premiere.layout/1', 'frames': frames, 'tracks': summaries,
            'requirements': checks,
            'meaning': 'Editorial interval coverage only; no proof of visible pixels, opacity, effects or source contents.'}
