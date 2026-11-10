"""Bounded spritesheet/metadata capture and an independent playback oracle.

Everything here is host-side and Godot-free. The planner never reads files; ``run``
captures the PNG and ``schemaxis.aseprite.sheet/1`` metadata bytes, validates them
here before any native process starts, and ``verify`` repeats the same derivation
from the retained bytes, so native receipts are compared with an independent model.

Time model: SpriteFrames durations are *relative* (Godot divides by the animation's
frames per second and the playing speed). Schemaxis fixes the animation speed at
1 frame per second, so a frame's relative duration is exactly its authored
``durationMS / 1000`` seconds. Milliseconds are never inferred from a rate.
"""
import json
import math
import re
import struct

from .errors import fault

SHEET_VERSION = 'schemaxis.aseprite.sheet/1'
MAX_PNG_BYTES = 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024
MAX_SHEET_WIDTH, MAX_SHEET_HEIGHT, MAX_SHEET_PIXELS = 4096, 256, 524288
MAX_FRAME_SIZE, MAX_FRAMES = 256, 32
MAX_DURATION_MS, MAX_ANIMATION_MS = 5000, 8000
DIRECTIONS = ('forward', 'reverse', 'pingPong', 'pingPongReverse')
ANIMATION_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}')
TICK = 0.001          # fixed process delta used by the playback stage (seconds)
WARMUP_FRAMES = 150   # frames awaited before play(); startup deltas are not uniform
PLAYBACK_FPS = 1000
CLOCK_LATE = 0.002    # a sample is read at most this long after its target (seconds)
SIGNATURE = b'\x89PNG\r\n\x1a\n'


def png_header(data, location):
    """Read IHDR only; enforce the pixel budget before any decompression."""
    if len(data) > MAX_PNG_BYTES:
        fault('RESOURCE_LIMIT', 'Spritesheet PNG exceeds the 1 MiB budget.', location,
              'Export a smaller sheet (at most 32 frames of at most 256x256).')
    if len(data) < 33 or not data.startswith(SIGNATURE) or data[12:16] != b'IHDR':
        fault('INVALID_SPRITE_SHEET', 'Spritesheet must be a PNG file.', location, 'Provide the Aseprite sheet.png publication.')
    width, height, depth, mode, compression, filtering, interlace = struct.unpack('>IIBBBBB', data[16:29])
    if depth != 8 or mode not in (2, 6) or compression or filtering or interlace:
        fault('UNSUPPORTED_SPRITE_SHEET', 'Use a non-interlaced 8-bit RGB or RGBA PNG.', location,
              'Re-export without palette, grayscale, 16-bit or interlaced samples.')
    if not (1 <= width <= MAX_SHEET_WIDTH and 1 <= height <= MAX_SHEET_HEIGHT and width*height <= MAX_SHEET_PIXELS):
        fault('RESOURCE_LIMIT', 'Spritesheet exceeds 4096x256 pixels or 524288 decoded pixels.', location,
              'Reduce the frame count or canvas size.')
    return width, height


def _reject_constant(name):
    fault('INVALID_SPRITE_METADATA', 'Metadata contains a non-finite number: '+name+'.', 'metadata',
          'Use finite integer values.')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fault('INVALID_SPRITE_METADATA', 'Metadata repeats key '+repr(key)+'.', 'metadata', 'Remove the duplicate key.')
        result[key] = value
    return result


def _exact(value, names, location):
    if not isinstance(value, dict):
        fault('INVALID_SPRITE_METADATA', 'Expected an object.', location, 'Use the published sheet.json structure.')
    unknown, missing = sorted(set(value)-set(names)), sorted(set(names)-set(value))
    if unknown:
        fault('UNSUPPORTED_SPRITE_METADATA', 'Unsupported metadata keys: '+', '.join(unknown)+'.', location,
              'Only the schemaxis.aseprite.sheet/1 keys are imported; nothing is silently ignored.')
    if missing:
        fault('INVALID_SPRITE_METADATA', 'Missing metadata keys: '+', '.join(missing)+'.', location,
              'Provide every schemaxis.aseprite.sheet/1 key.')


def _integer(value, low, high, location):
    if type(value) is not int or not low <= value <= high:
        fault('INVALID_SPRITE_METADATA', 'Expected an integer in ['+str(low)+', '+str(high)+'].', location,
              'Use an exact integer within the documented bound.')
    return value


def parse_metadata(data, sheet_width, sheet_height):
    """Strictly validate sheet metadata against the actual PNG dimensions."""
    if len(data) > MAX_METADATA_BYTES:
        fault('RESOURCE_LIMIT', 'Sprite metadata exceeds 65536 bytes.', 'metadata', 'Provide the compact sheet.json publication.')
    try:
        document = json.loads(data.decode('utf-8'), parse_constant=_reject_constant, object_pairs_hook=_unique)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        fault('INVALID_SPRITE_METADATA', 'Metadata is not valid UTF-8 JSON: '+str(error)[:120], 'metadata',
              'Provide the Aseprite sheet.json publication unchanged.')
    _exact(document, ('version', 'width', 'height', 'frames', 'tags'), 'metadata')
    if document['version'] != SHEET_VERSION:
        fault('UNSUPPORTED_VERSION', 'Expected '+SHEET_VERSION+'.', 'metadata.version', 'Provide schemaxis.aseprite.sheet/1 metadata.')
    for key, actual in (('width', sheet_width), ('height', sheet_height)):
        if _integer(document[key], 1, MAX_SHEET_WIDTH, 'metadata.'+key) != actual:
            fault('INVALID_SPRITE_METADATA', 'Metadata '+key+' differs from the PNG ('+str(actual)+').', 'metadata.'+key,
                  'Pair the sheet PNG with the metadata published beside it.')
    frames = document['frames']
    if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_FRAMES:
        fault('INVALID_SPRITE_METADATA', 'Provide 1 to 32 frames.', 'metadata.frames', 'Reduce the frame count.')
    result, covered = [], set()
    for index, frame in enumerate(frames):
        where = 'metadata.frames['+str(index)+']'
        _exact(frame, ('x', 'y', 'width', 'height', 'durationMS'), where)
        x, y = _integer(frame['x'], 0, sheet_width, where+'.x'), _integer(frame['y'], 0, sheet_height, where+'.y')
        w = _integer(frame['width'], 1, MAX_FRAME_SIZE, where+'.width')
        h = _integer(frame['height'], 1, MAX_FRAME_SIZE, where+'.height')
        duration = _integer(frame['durationMS'], 1, MAX_DURATION_MS, where+'.durationMS')
        if x+w > sheet_width or y+h > sheet_height:
            fault('INVALID_SPRITE_METADATA', 'Frame rectangle leaves the sheet.', where, 'Correct x, y, width and height.')
        if result and (w, h) != (result[0]['width'], result[0]['height']):
            fault('INVALID_SPRITE_METADATA', 'Frames must share one width and height.', where, 'Export uniform frames.')
        for row in range(y, y+h):
            span = set(range(row*sheet_width+x, row*sheet_width+x+w))
            if span & covered:
                fault('INVALID_SPRITE_METADATA', 'Frame rectangles overlap.', where, 'Frames must not share pixels.')
            covered |= span
        result.append({'x': x, 'y': y, 'width': w, 'height': h, 'durationMS': duration})
    tags = document['tags']
    if not isinstance(tags, list) or len(tags) > MAX_FRAMES:
        fault('INVALID_SPRITE_METADATA', 'tags must be a list of at most 32 tags.', 'metadata.tags', 'Reduce the tags.')
    seen = {}
    for index, tag in enumerate(tags):
        where = 'metadata.tags['+str(index)+']'
        _exact(tag, ('name', 'fromFrame', 'toFrame', 'direction'), where)
        if not isinstance(tag['name'], str) or not 1 <= len(tag['name']) <= 64 or tag['name'] in seen:
            fault('INVALID_SPRITE_METADATA', 'Tag names must be unique strings of 1 to 64 characters.', where+'.name', 'Rename the tag.')
        start = _integer(tag['fromFrame'], 1, len(result), where+'.fromFrame')
        end = _integer(tag['toFrame'], 1, len(result), where+'.toFrame')
        if end < start:
            fault('INVALID_SPRITE_METADATA', 'Tag range is reversed; frames are one-based, inclusive.', where, 'Use fromFrame <= toFrame.')
        if tag['direction'] not in DIRECTIONS:
            fault('INVALID_SPRITE_METADATA', 'Unknown tag direction.', where+'.direction', 'Use one of: '+', '.join(DIRECTIONS)+'.')
        seen[tag['name']] = {'name': tag['name'], 'fromFrame': start, 'toFrame': end, 'direction': tag['direction']}
    return {'width': sheet_width, 'height': sheet_height, 'frames': result, 'tags': seen}


def derive_animation(metadata, name, loop, pixels, sheet_width):
    """Select one forward tag slice; return the closed native animation definition."""
    tag = metadata['tags'].get(name)
    if tag is None:
        fault('UNKNOWN_ANIMATION', 'The metadata declares no tag named '+repr(name)+'.', '$.animation',
              'Choose one of: '+', '.join(sorted(metadata['tags']) or ['(no tags)'])+'.')
    if tag['direction'] != 'forward':
        fault('UNSUPPORTED_ANIMATION_DIRECTION', 'Tag '+repr(name)+' runs '+tag['direction']+'; only forward is supported.',
              '$.animation', 'Retag the slice as forward; reverse and ping-pong would change its meaning.')
    frames = []
    for number in range(tag['fromFrame'], tag['toFrame']+1):
        entry = metadata['frames'][number-1]
        crop = b''.join(pixels[((entry['y']+row)*sheet_width+entry['x'])*4:((entry['y']+row)*sheet_width+entry['x']+entry['width'])*4]
                        for row in range(entry['height']))
        frames.append({'sheetFrame': number, 'rect': [entry['x'], entry['y'], entry['width'], entry['height']],
                       'durationMS': entry['durationMS'], 'duration': entry['durationMS']/1000, 'pixels': crop})
    if sum(f['durationMS'] for f in frames) > MAX_ANIMATION_MS:
        fault('RESOURCE_LIMIT', 'The animation exceeds 8000 ms.', '$.animation', 'Choose a shorter tag.')
    sample_targets([f['duration'] for f in frames], loop)   # refuse undecidable timing before any native process
    return {'name': name, 'loop': loop, 'fps': 1.0, 'frames': frames}


def definition(animation):
    """Pixel-free JSON-safe form retained as animation_<id>.json and read by the worker."""
    return {'name': animation['name'], 'loop': animation['loop'], 'fps': 1.0, 'tick': TICK,
            'warmupFrames': WARMUP_FRAMES,
            'frames': [{k: v for k, v in f.items() if k != 'pixels'} for f in animation['frames']],
            'sampleTargets': sample_targets([f['duration'] for f in animation['frames']], animation['loop'])}


def boundaries(durations):
    edges, total = [0.0], 0.0
    for duration in durations:
        total += duration
        edges.append(total)
    return edges


def tolerance(durations, loop, elapsed):
    """Bound on how far native playback can sit from the ideal continuous clock.

    Godot 4.7.2 computes the frame rate before it advances the frame, so the rest of
    a tick that crosses a boundary still runs at the *previous* frame's rate and the
    leftover progress *fraction* (not leftover time) carries over. A crossing from a
    frame of duration d_old to one of d_new therefore shifts the clock by at most
    TICK*|d_new/d_old-1|. The bound is one tick of quantisation plus that shift for
    every crossing reached so far; it grows with the ratio, so extreme clips fail
    the decisive-sample planning below instead of loosening this bound.
    """
    count = len(durations)
    slack, crossing, time = TICK, 0, 0.0
    while loop or crossing < count-1:
        time += durations[crossing % count]
        if time > elapsed+TICK or crossing > 20000:
            break
        slack += TICK*abs(durations[(crossing+1) % count]/durations[crossing % count]-1.0)
        crossing += 1
    return slack


def locate(durations, loop, elapsed):
    """Ideal (frame, progress, playing) at elapsed seconds, and the boundary distance."""
    total = sum(durations)
    if not loop and elapsed >= total:
        return len(durations)-1, 1.0, False, abs(elapsed-total)
    local = math.fmod(elapsed, total) if loop else elapsed
    edges = boundaries(durations)
    for index, duration in enumerate(durations):
        if local < edges[index+1]:
            gap = min(abs(local-edges[index]), abs(local-edges[index+1]))
            if loop:
                gap = min(gap, abs(local), abs(total-local))
            return index, (local-edges[index])/duration, True, gap
    return len(durations)-1, 1.0, False, 0.0


def decisive(durations, loop, target):
    """True when the expected frame at ``target`` (and up to CLOCK_LATE after it) is
    unambiguous: the distance to every possible boundary exceeds the derived bound."""
    for elapsed in (target, target+CLOCK_LATE):
        if locate(durations, loop, elapsed)[3] <= tolerance(durations, loop, elapsed):
            return False
    return True


def refuse_timing(where):
    fault('UNSUPPORTED_ANIMATION_TIMING',
          'The 1 ms playback clock cannot tell this animation\'s frames apart ('+where+'): the timing error Godot can '
          'accumulate at frame boundaries (one tick times each duration ratio) is as large as the distance to the boundary.',
          '$.animation', 'Choose a tag whose frame durations are longer or closer together (at least a few tens of milliseconds, '
          'without a frame more than about ten times longer or shorter than its neighbour).')


def boundary_margin(durations, loop, edge, limit, sides):
    """Smallest decisive offset (12 ms preferred) at which both sides of an edge can be sampled."""
    candidates = [0.012]+[round(0.012*1.5**power, 6) for power in range(1, 14)]
    candidates += [round(limit*fraction, 6) for fraction in (0.3, 0.2, 0.1)]
    for margin in candidates:
        if margin < limit and all(decisive(durations, loop, round(edge+side*margin, 6)) for side in sides):
            return margin
    refuse_timing('boundary at '+format(edge, '.3f')+' s')


def sample_targets(durations, loop):
    """Seconds after play(): inside every frame, around each boundary, loop/end.

    Every target is decisive (see ``decisive``) or the clip is refused, so each
    sample can be compared with an exact expected frame.
    """
    edges = boundaries(durations)
    total = edges[-1]
    targets = set()
    for index, duration in enumerate(durations):
        middle = round(edges[index]+duration/2, 6)
        if not decisive(durations, loop, middle):
            refuse_timing('frame '+str(index))
        targets.add(middle)
    for index in range(1, len(durations)):
        margin = boundary_margin(durations, loop, edges[index], min(durations[index-1], durations[index]), (-1, 1))
        targets.update((round(edges[index]-margin, 6), round(edges[index]+margin, 6)))
    if loop:
        wrap = min(durations[-1], durations[0])
        margin = boundary_margin(durations, loop, total, wrap, (-1, 1))
        targets.update((round(total-margin, 6), round(total+margin, 6)))
        for index in range(min(2, len(durations))):
            middle = round(total+edges[index]+durations[index]/2, 6)
            if not decisive(durations, loop, middle):
                refuse_timing('frame '+str(index)+' of the second lap')
            targets.add(middle)
        margin = boundary_margin(durations, loop, 2*total, wrap, (-1, 1))
        targets.update((round(2*total-margin, 6), round(2*total+margin, 6)))
    else:
        before = boundary_margin(durations, loop, total, durations[-1], (-1,))
        after = boundary_margin(durations, loop, total, 0.5, (1,))
        targets.update((round(total-before, 6), round(total+after, 6), round(total+0.5, 6)))
    return sorted(targets)


def check_sample(durations, loop, sample):
    """Return an error message, or None when the native state matches the model.

    The expected frame is exact: a sample whose distance to a possible boundary is
    within the derived bound cannot decide the frame and fails closed.
    """
    elapsed, frame, progress = sample['elapsed'], sample['frame'], sample['progress']
    if not (isinstance(elapsed, (int, float)) and math.isfinite(elapsed) and sample['target']-1e-6 <= elapsed <= sample['target']+CLOCK_LATE):
        return 'sample clock does not follow its target'
    if not (type(frame) is int and 0 <= frame < len(durations) and isinstance(progress, (int, float))
            and math.isfinite(progress) and -1e-4 <= progress <= 1+1e-4):
        return 'sample frame or progress is out of range'
    expected, ideal_progress, playing, gap = locate(durations, loop, elapsed)
    slack = tolerance(durations, loop, elapsed)
    if gap <= slack:
        return 'sample lies within '+format(slack, '.4f')+' s of a frame boundary; its frame is not decidable'
    if not loop and not playing:
        if (frame, sample['playing']) != (len(durations)-1, False) or abs(progress-1.0) > 1e-4:
            return 'non-looping animation did not finish on its last frame'
        return None
    if sample['playing'] is not True:
        return 'looping animation stopped' if loop else 'animation stopped before its authored end'
    if frame != expected:
        return 'frame '+str(frame)+' differs from independently derived frame '+str(expected)
    edges = boundaries(durations)
    implied = edges[frame]+progress*durations[frame]
    total = sum(durations)
    if loop:
        wrapped = abs(implied-math.fmod(elapsed, total))
        difference = min(wrapped, total-wrapped)
    else:
        difference = abs(implied-elapsed)
    if difference > slack:
        return 'implied playback time differs from the clock by '+format(difference, '.4f')+' s (limit '+format(slack, '.4f')+' s)'
    return None


def inspect_scene(text, identity):
    """Independent text reading of the saved SpriteFrames and AnimatedSprite3D node.

    Returns the node's animation properties and each frame's atlas rectangle and
    relative duration as written by Godot's saver. Resource text is only scanned.
    """
    resources = {}
    for match in re.finditer(r'\[sub_resource type="([A-Za-z0-9_]+)" id="([^"]+)"\]\n(.*?)(?=\n\[|\Z)', text, re.S):
        resources[match[2]] = (match[1], match[3])
    node = re.search(r'\[node name="'+re.escape(identity)+r'" type="AnimatedSprite3D"[^\]]*\]\n(.*?)(?=\n\[|\Z)', text, re.S)
    if node is None:
        return None
    body = node[1]
    def prop(name, body=body):
        found = re.search(r'^'+name+r' = (.+)$', body, re.M)
        return found[1].strip() if found else None
    reference = re.fullmatch(r'SubResource\("([^"]+)"\)', prop('sprite_frames') or '')
    if reference is None or reference[1] not in resources or resources[reference[1]][0] != 'SpriteFrames':
        return None
    animations = re.search(r'animations = \[(.*)\]', resources[reference[1]][1], re.S)
    if animations is None:
        return None
    block = animations[1]
    frames = []
    for frame in re.finditer(r'"duration": ([-0-9.eE+]+),\s*"texture": SubResource\("([^"]+)"\)', block):
        kind, atlas = resources.get(frame[2], (None, ''))
        region = re.search(r'^region = Rect2\(([^)]*)\)', atlas, re.M)
        frames.append({'duration': float(frame[1]),
                       'rect': [float(v) for v in region[1].split(',')] if kind == 'AtlasTexture' and region else None})
    names = re.findall(r'"name": &?"([^"]*)"', block)
    loops = re.findall(r'"loop": (1|0|2|true|false)', block)
    speeds = re.findall(r'"speed": ([-0-9.eE+]+)', block)
    entries = []
    if len(names) == len(loops) == len(speeds) == 1:
        entries.append({'name': names[0], 'loop': loops[0], 'speed': float(speeds[0]), 'frames': frames})
    else:
        entries = [{'name': name, 'loop': None, 'speed': float('nan'), 'frames': []} for name in names] or [None, None]
    return {'animation': prop('animation'), 'autoplay': prop('autoplay'), 'pixelSize': prop('pixel_size'),
            'animations': entries}
