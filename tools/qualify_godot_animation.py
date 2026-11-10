#!/usr/bin/env python3
"""Bounded native acceptance for Godot animatedSprite3D fed by a real Aseprite sheet.

Runs the configured Aseprite executable as the producer (its observed version is
recorded; it is a hand-off observation, not a qualification of the latest release),
then Godot build/reopen/playback. Expectations are literal or derived here from
analytic pixels and authored milliseconds, never read back from Godot receipts.
"""
import argparse
import base64
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import threading
import time
import zlib
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from schemaxis import publication_metadata, workflow
from schemaxis.adaptors.aseprite import adaptor as aseprite
from schemaxis.adaptors.godot import run, verify
from schemaxis.adaptors.godot import adaptor as godot
from schemaxis.adaptors.godot import sprites
from schemaxis.artifacts import atomic_json
from schemaxis.png import decode as decode_png
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation

REAL_DISPATCH = godot.dispatch_stage
BACKGROUND = [20, 40, 80, 255]
DOTS = [(1, 1, 2, 2, [250, 150, 30, 255]), (3, 3, 3, 2, [40, 200, 120, 255]), (5, 5, 2, 3, [230, 60, 90, 255])]
PROBE = '''extends SceneTree
func _initialize():
    var packed = ResourceLoader.load("res://scene.tscn", "PackedScene", ResourceLoader.CACHE_MODE_IGNORE)
    var scene = packed.instantiate()
    var out = []
    for sprite in scene.find_children("*", "AnimatedSprite3D", true, false):
        var frames = sprite.sprite_frames
        var name = String(sprite.animation)
        var listed = []
        for index in range(frames.get_frame_count(name)):
            var texture = frames.get_frame_texture(name, index)
            var image = texture.get_image()
            image.convert(Image.FORMAT_RGBA8)
            listed.append({"rect": [texture.region.position.x, texture.region.position.y, texture.region.size.x, texture.region.size.y],
                "duration": frames.get_frame_duration(name, index), "pixels": Marshalls.raw_to_base64(image.get_data())})
        out.append({"name": name, "loopMode": int(frames.get_animation_loop_mode(name)), "fps": frames.get_animation_speed(name),
            "playing": sprite.is_playing(), "frames": listed})
    var handle = FileAccess.open("res://live.json", FileAccess.WRITE)
    handle.store_string(JSON.stringify(out))
    scene.free()
    quit(0)
'''

# The saved project's main scene instantiated by its own application/run/main_scene setting; the
# AnimatedSprite3D starts through its saved autoplay (no play() call) and is only read as it advances.
AUTOPLAY = '''extends SceneTree
var elapsed = 0.0
var counting = false
var delta_min = 1.0
var delta_max = 0.0

func _process(delta):
    if counting:
        elapsed += delta
        delta_min = min(delta_min, delta)
        delta_max = max(delta_max, delta)
    return false

func _initialize():
    var targets = JSON.parse_string(FileAccess.get_file_as_string("res://targets.json"))
    for _warmup in range(150):
        await process_frame
    var scene = load(String(ProjectSettings.get_setting("application/run/main_scene"))).instantiate()
    root.add_child(scene)
    var sprite = scene.find_children("*", "AnimatedSprite3D", true, false)[0]
    var samples = []
    var cursor = 0
    var frames = 0
    counting = true
    while cursor < targets.size():
        await process_frame
        frames += 1
        if frames > 20000:
            quit(2)
            return
        while cursor < targets.size() and elapsed >= float(targets[cursor]) - 0.0000001:
            samples.append({"target": targets[cursor], "elapsed": elapsed, "frame": sprite.frame, "progress": sprite.frame_progress,
                "playing": sprite.is_playing(), "animation": String(sprite.animation), "autoplay": String(sprite.autoplay)})
            cursor += 1
    var handle = FileAccess.open("res://autoplay.json", FileAccess.WRITE)
    handle.store_string(JSON.stringify({"samples": samples, "minDelta": delta_min, "maxDelta": delta_max}))
    scene.free()
    quit(0)
'''
TICK = 0.001


def producer(durations=(100, 250, 400), order=(0, 1, 2), direction='forward'):
    nodes = [{'id': 'canvas', 'filter': 'sprite', 'options': {'width': 8, 'height': 8, 'durationMS': durations[0]}},
             {'id': 'colours', 'filter': 'palette', 'inputs': {'sprite': 'canvas'}, 'options': {'colours': [
                 [0, 0, 0, 0], BACKGROUND, *[d[4] for d in DOTS]]}}]
    previous = 'colours'
    for frame in range(1, 4):
        if frame > 1:
            nodes.append({'id': f'f{frame}', 'filter': 'frame', 'inputs': {'sprite': previous}, 'options': {'durationMS': durations[frame-1]}})
            previous = f'f{frame}'
        x, y, w, h, colour = DOTS[order[frame-1]]
        for name, box, paint in ((f'bg{frame}', (0, 0, 8, 8), BACKGROUND), (f'dot{frame}', (x, y, w, h), colour)):
            nodes.append({'id': name, 'filter': 'rect', 'inputs': {'sprite': previous}, 'options': {
                'layer': 'base', 'frame': frame, 'x': box[0], 'y': box[1], 'width': box[2], 'height': box[3], 'colour': paint}})
            previous = name
    nodes.append({'id': 'pulse', 'filter': 'tag', 'inputs': {'sprite': previous}, 'options': {
        'name': 'pulse', 'fromFrame': 1, 'toFrame': 3, 'direction': direction}})
    nodes.append({'id': 'bounce', 'filter': 'tag', 'inputs': {'sprite': 'pulse'}, 'options': {
        'name': 'bounce', 'fromFrame': 1, 'toFrame': 2, 'direction': 'pingPong'}})
    return {'version': 'schemaxis.aseprite/1', 'nodes': nodes, 'output': 'bounce'}


def analytic_pixels(order):
    """Literal RGBA bytes for each frame, from the authored rectangles only."""
    frames = []
    for index in order:
        x, y, w, h, colour = DOTS[index]
        raw = bytearray()
        for row in range(8):
            for column in range(8):
                raw += bytes(colour if x <= column < x+w and y <= row < y+h else BACKGROUND)
        frames.append(bytes(raw))
    return frames


def scene(file, metadata, animation='pulse', loop=True, parent=True):
    nodes = [{'id': 'hero', 'filter': 'animatedSprite3D', 'options': {
        'file': file, 'metadata': metadata, 'animation': animation, 'loop': loop, 'pixelSize': 0.05, 'position': [0, 0.5, 0]}},
        {'id': 'camera', 'filter': 'camera', 'options': {'position': [0, 0, 3], 'target': [0, 0, 0]}}]
    if parent:
        nodes.insert(0, {'id': 'rig', 'filter': 'transformGroup', 'options': {'position': [1, 0, 0]}})
        nodes[1]['inputs'] = {'parent': 'rig'}
    return {'version': 'schemaxis.godot/1', 'nodes': nodes}


def ideal(durations, loop, elapsed):
    """Qualifier-owned ideal clock: frame, and distance to the nearest boundary."""
    total, edges = sum(durations), [0.0]
    for duration in durations:
        edges.append(edges[-1]+duration)
    if not loop and elapsed >= total:
        return len(durations)-1, abs(elapsed-total)
    local = elapsed % total if loop else elapsed
    index = max(i for i in range(len(durations)) if edges[i] <= local)
    near = min(abs(local-edge) for edge in edges)
    return index, min(near, total-local if loop else near)


def bound(durations, loop, elapsed):
    """Qualifier-owned derived bound: one tick plus TICK*|d_new/d_old-1| per crossing reached.

    Godot 4.7.2 computes the rate before advancing the frame, so the rest of a crossing tick runs
    at the previous frame's rate; nothing here is tuned to observed results.
    """
    count, slack, crossing, time = len(durations), TICK, 0, 0.0
    while loop or crossing < count-1:
        time += durations[crossing % count]
        if time > elapsed+TICK:
            break
        slack += TICK*abs(durations[(crossing+1) % count]/durations[crossing % count]-1.0)
        crossing += 1
    return slack


def check_samples(durations, loop, samples):
    """Exact expected frame for every sample; a sample inside the derived bound would be a defect."""
    total = sum(durations)
    for sample in samples:
        frame, gap = ideal(durations, loop, sample['elapsed'])
        assert gap > bound(durations, loop, sample['elapsed']), ('undecidable sample', sample)
        assert sample['frame'] == frame, (sample, frame)
        assert sample['playing'] is (loop or sample['elapsed'] < total), sample
        if not loop and sample['elapsed'] >= total:
            assert math.isclose(sample['progress'], 1.0, abs_tol=1e-4), sample
    assert {s['frame'] for s in samples} == set(range(len(durations)))


def check_fixtures():
    """The committed development-kit fixtures are exactly what their generator writes."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root/'tools/generate_godot_animation_fixtures.py'), '--check'],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return True


def autoplay_project(godot_exe, source, directory, targets, timeout=60):
    """Run the saved project's main scene headless at a fixed 1 ms tick; return real autoplay samples."""
    directory = Path(directory)
    directory.mkdir()
    for name in ('project.godot', 'scene.tscn', 'orbit.gd'):
        shutil.copy(Path(source)/name, directory/name)
    (directory/'autoplay.gd').write_text(AUTOPLAY)
    (directory/'targets.json').write_text(json.dumps(targets))
    godot.dispatch_stage([godot_exe, '--headless', '--fixed-fps', str(sprites.PLAYBACK_FPS), '--path', str(directory),
                          '--script', 'res://autoplay.gd'], directory, 'autoplay', timeout)
    played = json.loads((directory/'autoplay.json').read_text())
    assert math.isclose(played['minDelta'], TICK, rel_tol=1e-6) and math.isclose(played['maxDelta'], TICK, rel_tol=1e-6), played
    return played['samples']


def check_autoplay(godot_exe, source, directory, durations_ms, loop, animation, timeout=60):
    durations = [d/1000 for d in durations_ms]
    targets = sprites.sample_targets(durations, loop)
    samples = autoplay_project(godot_exe, source, directory, targets, timeout)
    assert [s['target'] for s in samples] == targets
    assert all(s['animation'] == animation and s['autoplay'] == animation for s in samples), samples
    check_samples(durations, loop, samples)
    return {'samples': len(samples), 'frames': [s['frame'] for s in samples]}


def check_native(directory, durations_ms, loop, order):
    """Independently compare saved resource, raw pixels and sampled playback."""
    durations = [d/1000 for d in durations_ms]
    reopened = json.loads((directory/'reopened.json').read_text())['scene']['nodes']['hero']['animation']
    expected_pixels = analytic_pixels(order)
    assert [f['rect'] for f in reopened['frames']] == [[8.0*i, 0.0, 8.0, 8.0] for i in range(3)]
    for frame, seconds in zip(reopened['frames'], durations):
        assert math.isclose(frame['duration'], seconds, rel_tol=1e-6), (frame, seconds)
    raw = (directory/'animation_hero.rgba').read_bytes()
    assert raw == b''.join(expected_pixels), 'native pixels differ from the analytic frames'
    for frame, pixels in zip(reopened['frames'], expected_pixels):
        assert frame['rgbaSHA256'] == hashlib.sha256(pixels).hexdigest()
    assert reopened['loopMode'] == (1 if loop else 0) and reopened['fps'] == 1.0 and reopened['speedScale'] == 1.0
    playback = json.loads((directory/'playback.json').read_text())
    assert playback['clock']['minDelta'] == playback['clock']['maxDelta'] == 0.001
    samples = playback['sprites']['hero']['samples']
    check_samples(durations, loop, samples)
    return {'samples': len(samples), 'frames': [s['frame'] for s in samples]}


def refresh(directory):
    """Refresh every ordinary mutable integrity binding after a deliberate edit."""
    prepared = json.loads((directory/'plan.json').read_text())
    names = ['project.godot', 'scene.tscn', 'orbit.gd', 'worker.gd']
    names += [n for node in prepared['nodes'] if node['filter'] in godot.IMPORTS for n in godot.retained_names(node)]
    atomic_json(directory/'artifacts.json', {n: godot.digest(directory/n) for n in names})
    atomic_json(directory/'verification.json', {'artifacts': godot.artifact_manifest(directory, prepared)})
    result = json.loads((directory/'result.json').read_text())
    atomic_json(directory/'result.json', result)
    publication_metadata.finalise(directory)


def refresh_sources(directory):
    prepared = json.loads((directory/'plan.json').read_text())
    node = next(n for n in prepared['nodes'] if n['filter'] == 'animatedSprite3D')
    entry, animation = godot.capture_animation(node, 0, (directory/'source_hero.png').read_bytes(), (directory/'source_hero.json').read_bytes())
    sources = json.loads((directory/'sources.json').read_text())
    sources['hero'] = entry
    atomic_json(directory/'sources.json', sources)
    atomic_json(directory/'animation_hero.json', entry['animation'])
    return animation


def mutant(base, target, name, edit, resource=refresh):
    """Copy, mutate, refresh all bindings, expect one specific semantic reason."""
    path = target/('mutant-'+name)
    shutil.copytree(base, path)
    edit(path)
    resource(path)
    if resource is refresh_sources:
        refresh(path)
    # Every ordinary binding, including the output metadata publications, is genuinely current
    # before the semantic reason is expected.
    assert publication_metadata.verify(path)['verified'], name
    assert json.loads((path/'artifacts.json').read_text()) == {
        n: godot.digest(path/n) for n in json.loads((path/'artifacts.json').read_text())}, name
    try:
        verify(path)
    except SchemaxisError as error:
        return error.fault.code, error.fault.message
    raise AssertionError('Hash-refreshed mutant accepted: '+name)


def qualify(godot_exe, aseprite_exe, directory, timeout=60):
    target = Path(directory).resolve()
    target.mkdir(parents=True, exist_ok=False)
    out = {'fixturesCurrent': check_fixtures(),
           'aseprite': subprocess.run([aseprite_exe, '--version'], capture_output=True, text=True, timeout=20).stdout.strip(),
           'godot': subprocess.run([godot_exe, '--version'], capture_output=True, text=True, timeout=20).stdout.strip()}
    sheets = {}
    for label, args in {'baseline': {}, 'duration': {'durations': (250, 100, 400)}, 'order': {'order': (2, 0, 1)},
                        'pixels': {'order': (1, 1, 1)}, 'reverse': {'direction': 'reverse'}}.items():
        folder = target/('aseprite-'+label)
        aseprite.run(producer(**args), str(folder), aseprite_exe, 60)
        sheets[label] = folder
    cases = {}
    for label, durations, loop, order in (('baseline', (100, 250, 400), True, (0, 1, 2)), ('nonloop', (100, 250, 400), False, (0, 1, 2)),
                                          ('duration', (250, 100, 400), True, (0, 1, 2)), ('order', (100, 250, 400), True, (2, 0, 1)),
                                          ('pixels', (100, 250, 400), True, (1, 1, 1))):
        source = sheets['baseline' if label == 'nonloop' else label]
        document = scene(str(source/'sheet.png'), str(source/'sheet.json'), loop=loop)
        result = run(document, target/('godot-'+label), godot_exe, timeout)
        assert result['verified'] and verify(target/('godot-'+label))['verified']
        cases[label] = check_native(target/('godot-'+label), durations, loop, order)
    # Committed development-kit fixtures run natively with the same independent literals.
    fixtures = Path(__file__).resolve().parents[1]/'examples/schemaxis'
    run(scene(str(fixtures/'sprite-animation-fixture.png'), str(fixtures/'sprite-animation-fixture.json')), target/'godot-fixture', godot_exe, timeout)
    cases['fixture'] = check_native(target/'godot-fixture', (100, 250, 400), True, (0, 1, 2))
    out['cases'] = cases
    # The saved project's main scene autoplays headless at a fixed tick; samples are read, never assigned.
    out['autoplay'] = {label: check_autoplay(godot_exe, target/('godot-'+label), target/('autoplay-'+label), durations, loop, 'pulse', timeout)
                       for label, durations, loop in (('baseline', (100, 250, 400), True), ('nonloop', (100, 250, 400), False),
                                                      ('duration', (250, 100, 400), True), ('fixture', (100, 250, 400), True))}
    baseline = target/'godot-baseline'
    # Captured sources are independent of the original paths: alter the originals, verify offline.
    standalone = target/'standalone-source'
    shutil.copytree(sheets['baseline'], standalone)
    run(scene(str(standalone/'sheet.png'), str(standalone/'sheet.json')), target/'godot-standalone', godot_exe, timeout)
    (standalone/'sheet.json').write_text('{}')
    assert verify(target/'godot-standalone')['verified']
    # Live fresh reopen with a qualifier-owned probe, launched by the shared runner.
    live = target/'live'
    live.mkdir()
    for name in ('project.godot', 'scene.tscn'):
        shutil.copy(baseline/name, live/name)
    for name in ('orbit.gd',):
        shutil.copy(baseline/name, live/name)
    (live/'probe.gd').write_text(PROBE)
    godot.dispatch_stage([godot_exe, '--headless', '--path', str(live), '--script', 'res://probe.gd'], live, 'probe', timeout)
    probed = json.loads((live/'live.json').read_text())[0]
    assert probed['name'] == 'pulse' and probed['loopMode'] == 1 and probed['fps'] == 1.0
    assert [math.isclose(f['duration'], s, rel_tol=1e-6) for f, s in zip(probed['frames'], (0.1, 0.25, 0.4))] == [True]*3
    assert b''.join(base64.b64decode(f['pixels']) for f in probed['frames']) == b''.join(analytic_pixels((0, 1, 2)))
    out['liveReopen'] = {'frames': 3, 'runtimeProcess': 'qualifier-owned probe through the shared runner'}
    # Controls: refused before any native job exists.
    refusals = {}
    source = sheets['baseline']
    metadata = json.loads((source/'sheet.json').read_text())
    controls = {
        'zero-duration': (lambda m: m['frames'][1].update(durationMS=0), 'INVALID_SPRITE_METADATA', 'frames[1].durationMS'),
        'nan-duration': (None, 'INVALID_SPRITE_METADATA', 'metadata'),
        'fractional-duration': (lambda m: m['frames'][1].update(durationMS=250.5), 'INVALID_SPRITE_METADATA', 'frames[1].durationMS'),
        'overlap': (lambda m: m['frames'][1].update(x=4), 'INVALID_SPRITE_METADATA', 'frames[1]'),
        'outside-sheet': (lambda m: m['frames'][2].update(x=20), 'INVALID_SPRITE_METADATA', 'frames[2]'),
        'unknown-key': (lambda m: m['frames'][0].update(trimmed=True), 'UNSUPPORTED_SPRITE_METADATA', 'frames[0]'),
        'version': (lambda m: m.update(version='schemaxis.aseprite.sheet/2'), 'UNSUPPORTED_VERSION', 'metadata.version'),
        'bad-tag-range': (lambda m: m['tags'][1].update(toFrame=9), 'INVALID_SPRITE_METADATA', 'tags[1].toFrame'),
        'size-mismatch': (lambda m: m.update(width=32), 'INVALID_SPRITE_METADATA', 'metadata.width'),
    }
    for name, (edit, code, where) in controls.items():
        altered = copy.deepcopy(metadata)
        text = json.dumps(altered)
        if edit:
            edit(altered)
            text = json.dumps(altered)
        else:
            text = text.replace('"durationMS": 250', '"durationMS": NaN')
        path = target/('control-'+name+'.json')
        path.write_text(text)
        try:
            run(scene(str(source/'sheet.png'), str(path)), target/('refused-'+name), godot_exe, timeout)
        except SchemaxisError as error:
            assert error.fault.code == code and where in error.fault.location, (name, error.fault)
            assert not (target/('refused-'+name)).exists()
            refusals[name] = [error.fault.code, error.fault.location]
        else:
            raise AssertionError('Control accepted: '+name)
    for name, document, code in (('reverse-direction', scene(str(sheets['reverse']/'sheet.png'), str(sheets['reverse']/'sheet.json')), 'UNSUPPORTED_ANIMATION_DIRECTION'),
                                 ('pingpong-tag', scene(str(source/'sheet.png'), str(source/'sheet.json'), animation='bounce'), 'UNSUPPORTED_ANIMATION_DIRECTION'),
                                 ('unknown-tag', scene(str(source/'sheet.png'), str(source/'sheet.json'), animation='missing'), 'UNKNOWN_ANIMATION'),
                                 ('png-not-png', scene(str(source/'sheet.json'), str(source/'sheet.json')), 'INVALID_SPRITE_SHEET')):
        try:
            run(document, target/('refused-'+name), godot_exe, timeout)
        except SchemaxisError as error:
            assert error.fault.code == code, (name, error.fault)
            refusals[name] = [error.fault.code, error.fault.location]
        else:
            raise AssertionError('Control accepted: '+name)
    out['refusals'] = refusals
    # Hash-refreshed semantic mutants: every ordinary binding is refreshed first.
    def text_edit(old, new):
        def edit(path):
            scene_text = (path/'scene.tscn').read_text()
            assert old in scene_text, old
            (path/'scene.tscn').write_text(scene_text.replace(old, new, 1))
        return edit
    def swap_references(path):
        import re
        scene_text = (path/'scene.tscn').read_text()
        refs = re.findall(r'"texture": SubResource\("([^"]+)"\)', scene_text)
        order = iter([refs[1], refs[0]] + refs[2:])
        scene_text = re.sub(r'"texture": SubResource\("[^"]+"\)', lambda m: '"texture": SubResource("'+next(order)+'")', scene_text)
        (path/'scene.tscn').write_text(scene_text)
    def flip_pixel(path):
        raw = bytearray((path/'animation_hero.rgba').read_bytes())
        raw[0] ^= 1
        (path/'animation_hero.rgba').write_bytes(bytes(raw))
    def edit_receipts(change):
        def edit(path):
            for name in ('built.json', 'reopened.json'):
                receipt = json.loads((path/name).read_text())
                change(receipt)
                atomic_json(path/name, receipt)
        return edit
    def edit_playback(change):
        def edit(path):
            receipt = json.loads((path/'playback.json').read_text())
            change(receipt)
            atomic_json(path/'playback.json', receipt)
        return edit
    def edit_png(path):
        width, height, pixels = decode_png((path/'source_hero.png').read_bytes())
        pixels = bytearray(pixels)
        pixels[0] ^= 1    # first pixel of frame 0
        rows = b''.join(b'\0'+bytes(pixels[y*width*4:(y+1)*width*4]) for y in range(height))
        def chunk(kind, body):
            return struct.pack('>I', len(body))+kind+body+struct.pack('>I', zlib.crc32(kind+body) & 0xffffffff)
        (path/'source_hero.png').write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
                                             + chunk(b'IDAT', zlib.compress(rows))+chunk(b'IEND', b''))
    def edit_metadata(path):
        meta = json.loads((path/'source_hero.json').read_text())
        meta['frames'][1]['durationMS'] = 260
        (path/'source_hero.json').write_text(json.dumps(meta))
    mutants = {
        'saved-duration': (text_edit('"duration": 0.25', '"duration": 0.5'), refresh, 'Saved frame duration differs'),
        'saved-loop': (text_edit('"loop": 1', '"loop": 0'), refresh, 'Saved loop state differs'),
        'saved-rectangle': (text_edit('Rect2(8, 0, 8, 8)', 'Rect2(0, 0, 8, 8)'), refresh, 'Saved frame rectangle differs'),
        'saved-order': (swap_references, refresh, 'Saved frame rectangle differs'),
        'saved-autoplay': (text_edit('autoplay = "pulse"', 'autoplay = "other"'), refresh, 'Saved animation name or autoplay differs'),
        'raw-pixels': (flip_pixel, refresh, 'Native frame pixels differ'),
        'joint-receipt-duration': (edit_receipts(lambda r: r['scene']['nodes']['hero']['animation']['frames'][0].update(duration=0.2)),
                                   refresh, 'Frame duration differs'),
        # The source PNG half: sources.json, the animation definition and every sidecar are refreshed to the
        # edited sheet, so the hit is the semantic comparison with Godot's retained pixel readback.
        'source-png-pixel': (edit_png, refresh_sources, 'Sprite atlas readback differs'),
        'source-metadata-duration': (edit_metadata, refresh_sources, 'Frame duration differs'),
        'playback-frame': (edit_playback(lambda r: r['sprites']['hero']['samples'][1].update(frame=2)), refresh, 'Playback state'),
        'playback-clock': (edit_playback(lambda r: r['clock'].update(minDelta=0.002)), refresh, 'Playback clock'),
        'playback-schedule': (edit_playback(lambda r: r['sprites']['hero']['samples'][0].update(target=0.04)), refresh, 'Playback sample times'),
    }
    forged = {}
    for name, (edit, resource, reason) in mutants.items():
        code, message = mutant(baseline, target, name, edit, resource)
        assert code == 'VERIFICATION_FAILED' and reason in message, (name, code, message)
        forged[name] = message
    out['hashRefreshedMutants'] = forged
    # Timeout and cancellation of the playback stage. A blocking wait.gd Godot process stands in for the stage
    # (--frame-delay is ignored under --fixed-fps), so this proves the shared runner's handling and evidence
    # retention for a live native playback-stage process, not interruption in the middle of the sampling loop.
    retained = {}
    document = scene(str(sheets['baseline']/'sheet.png'), str(sheets['baseline']/'sheet.json'))
    for mode in ('cancel', 'timeout'):
        event = threading.Event()
        def slowed(command, directory, stage, budget, environment):
            if stage != 'playback':
                return REAL_DISPATCH(command, directory, stage, budget, environment)
            # --frame-delay is ignored under --fixed-fps, so a real Godot process that blocks
            # takes the playback stage's place: this exercises the shared runner's timeout and
            # cancellation of a live native playback-stage process, not the sampling loop itself.
            (directory/'wait.gd').write_text('extends SceneTree\nfunc _initialize():\n    OS.delay_msec(30000)\n    quit(0)\n')
            command = [command[0], '--headless', '--path', str(directory), '--script', 'res://wait.gd']
            stop = threading.Event()
            def monitor():
                end = time.monotonic()+10
                while not stop.wait(0.01) and time.monotonic() < end:
                    if any((directory/'.dispatch'/stage).glob('replay-*.py')):
                        time.sleep(1.0)  # the blocking Godot process is live
                        event.set()
                        return
            thread = threading.Thread(target=monitor) if mode == 'cancel' else None
            if thread:
                thread.start()
            try:
                return REAL_DISPATCH(command, directory, stage, budget, environment)
            finally:
                stop.set()
                if thread:
                    thread.join()
        wanted = 'RUNNER_CANCELLED' if mode == 'cancel' else 'RUNNER_TIMED_OUT'
        with allocation({'threads': 2}, event), patch('schemaxis.adaptors.godot.adaptor.dispatch_stage', side_effect=slowed):
            try:
                run(document, target/('live-'+mode), godot_exe, timeout if mode == 'cancel' else 3)
            except SchemaxisError as error:
                assert error.fault.code == wanted, (mode, error.fault)
            else:
                raise AssertionError('Expected bounded failure: '+mode)
        failed = json.loads((target/('live-'+mode)/'result.json').read_text())
        assert failed['verified'] is False and failed['fault']['code'] == wanted
        assert (target/('live-'+mode)/'playback.log').exists() and not (target/('live-'+mode)/'artifacts.json').exists()
        retained[mode] = wanted
    out['liveFailureRetention'] = retained
    # Workflow hand-off: both generic artifact references; unchanged reuse; changed producer invalidates.
    wf = json.loads((Path(__file__).resolve().parents[1]/'examples/schemaxis/aseprite-animation-to-godot.json').read_text())
    locations = {'aseprite': aseprite_exe, 'godot': godot_exe}
    first = workflow.execute(wf, target/'workflow', locations=locations, timeout=timeout)
    resumed = workflow.execute(wf, target/'workflow', locations=locations, timeout=timeout, resume=True)
    assert first['verified'] and resumed['verified']
    assert [j['reused'] for j in first['jobs']] == [False, False] and [j['reused'] for j in resumed['jobs']] == [True, True]
    changed = copy.deepcopy(wf)
    changed['operations'][0]['document'] = producer(durations=(100, 250, 300))
    second = workflow.execute(changed, target/'workflow-changed', locations=locations, timeout=timeout)
    assert second['verified']
    directory2 = Path(second['jobs'][1]['directory'])
    out['workflow'] = {'firstReused': [j['reused'] for j in first['jobs']], 'resumedReused': [j['reused'] for j in resumed['jobs']],
                       'changedProducer': check_native(directory2, (100, 250, 300), True, (0, 1, 2)),
                       'inputHashes': sorted(first['jobs'][1].get('inputHashes', {}).values())}
    # Legacy controls: flat primitives, static sprite3D from the same real sheet, hierarchy.
    examples = Path(__file__).resolve().parents[1]/'examples/schemaxis'
    legacy = {}
    for name in ('godot-primitives', 'godot-hierarchy'):
        legacy[name] = run(json.loads((examples/(name+'.json')).read_text()), target/('legacy-'+name), godot_exe, timeout)['verified']
    static = {'version': 'schemaxis.godot/1', 'nodes': [
        {'id': 'still', 'filter': 'sprite3D', 'options': {'file': str(sheets['baseline']/'sheet.png'), 'pixelSize': 0.05}},
        {'id': 'camera', 'filter': 'camera', 'options': {'position': [0, 0, 3], 'target': [0, 0, 0]}}]}
    legacy['static-sprite3D'] = run(static, target/'legacy-static-sprite', godot_exe, timeout)['verified']
    assert all(legacy.values()) and not (target/'legacy-static-sprite'/'playback.json').exists()
    out['legacy'] = legacy
    out['limits'] = ('Headless AnimatedSprite3D playback at a fixed 1 ms process tick with a derived boundary tolerance; forward tags only; '
                     'no GUI, rendering, pacing, other frame rates, scripts, physics, audio or latest-Aseprite qualification.')
    out['verified'] = True
    atomic_json(target/'qualification.json', out)
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--aseprite', required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--timeout', type=float, default=60)
    arguments = parser.parse_args()
    print(json.dumps(qualify(arguments.executable, arguments.aseprite, arguments.directory, arguments.timeout), indent=2))
