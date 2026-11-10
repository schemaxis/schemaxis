import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from schemaxis.adaptors.godot import adaptor, integration, plan, run, sprites, verify
from schemaxis.core.faults import SchemaxisError

BACKGROUND = (20, 40, 80, 255)


def png(width, height, pixels, colour=6):
    channels = 4 if colour == 6 else 3
    rows = b''.join(b'\0'+bytes(pixels[y*width*channels:(y+1)*width*channels]) for y in range(height))
    def chunk(kind, body):
        return struct.pack('>I', len(body))+kind+body+struct.pack('>I', zlib.crc32(kind+body) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, colour, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows))+chunk(b'IEND', b''))


def sheet(frames=3, size=4, colour=6):
    """Frame i is filled with a distinct analytic colour (10+40i, 20, 200-30i)."""
    raw = bytearray()
    for _row in range(size):
        for frame in range(frames):
            pixel = (10+40*frame, 20, 200-30*frame, 255)
            raw += bytes(pixel if colour == 6 else pixel[:3])*size
    return png(size*frames, size, raw, colour)


def metadata(durations=(100, 250, 400), size=4, tags=None):
    return {'version': 'schemaxis.aseprite.sheet/1', 'width': size*len(durations), 'height': size,
            'frames': [{'x': i*size, 'y': 0, 'width': size, 'height': size, 'durationMS': d} for i, d in enumerate(durations)],
            'tags': tags if tags is not None else [{'name': 'walk', 'fromFrame': 1, 'toFrame': len(durations), 'direction': 'forward'},
                                                   {'name': 'rock', 'fromFrame': 1, 'toFrame': 2, 'direction': 'pingPong'}]}


def document(**options):
    values = {'file': '/data/sheet.png', 'metadata': '/data/sheet.json', 'animation': 'walk', **options}
    return {'version': 'schemaxis.godot/1', 'nodes': [
        {'id': 'rig', 'filter': 'transformGroup'},
        {'id': 'hero', 'filter': 'animatedSprite3D', 'inputs': {'parent': 'rig'}, 'options': values},
        {'id': 'view', 'filter': 'camera'}]}


def fault(test, call, code, where=''):
    with test.assertRaises(SchemaxisError) as caught:
        call()
    test.assertEqual(caught.exception.fault.code, code, caught.exception.fault)
    test.assertIn(where, caught.exception.fault.location)
    return caught.exception.fault


class AnimatedSpritePlanTests(unittest.TestCase):
    def test_plan_expands_defaults_and_keeps_static_sprite_contract(self):
        node = plan(document())['nodes'][1]
        self.assertEqual(node['options'], {'file': '/data/sheet.png', 'metadata': '/data/sheet.json', 'animation': 'walk',
                                           'loop': True, 'pixelSize': 0.01, 'position': [0, 0, 0]})
        self.assertEqual(adaptor.DECLARATIONS['sprite3D']['options'].keys(), {'position', 'file', 'pixelSize'})
        self.assertEqual(list(adaptor.DECLARATIONS)[-1], 'animatedSprite3D')
        alternatives = adaptor.schema()['properties']['nodes']['items']['oneOf']
        self.assertEqual(alternatives[-1]['properties']['filter'], {'const': 'animatedSprite3D'})
        self.assertIn('options', alternatives[-1]['required'])

    def test_relative_paths_names_parents_and_counts_are_refused_with_locations(self):
        fault(self, lambda: plan(document(metadata='sheet.json')), 'UNSUPPORTED_RESOURCE', '.options.metadata')
        fault(self, lambda: plan(document(file='sheet.png')), 'UNSUPPORTED_RESOURCE', '.options.file')
        fault(self, lambda: plan(document(animation='walk cycle')), 'INVALID_NAME', '.options.animation')
        fault(self, lambda: plan(document(pixelSize=0)), 'INVALID_ARGUMENT')
        wrong = document()
        wrong['nodes'][1]['inputs']['parent'] = 'view'
        fault(self, lambda: plan(wrong), 'TYPE_MISMATCH', '.inputs.parent')
        many = document()
        many['nodes'] += [{**copy.deepcopy(many['nodes'][1]), 'id': 'extra%d' % i} for i in range(4)]
        fault(self, lambda: plan(many), 'RESOURCE_LIMIT')

    def test_a_scene_of_only_an_animated_sprite_satisfies_the_visible_content_rule(self):
        planned = plan({'version': 'schemaxis.godot/1', 'nodes': [document()['nodes'][1].copy() | {'inputs': {}},
                                                                   {'id': 'view', 'filter': 'camera'}]})
        self.assertEqual(planned['expectedNodeCount'], 3)

    def test_reuse_fingerprints_cover_both_source_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            image, meta = Path(folder)/'sheet.png', Path(folder)/'sheet.json'
            image.write_bytes(sheet())
            meta.write_text(json.dumps(metadata()))
            doc = document(file=str(image), metadata=str(meta))
            first = integration.reusableInputs(doc)
            self.assertEqual(set(first), {str(image), str(meta)})
            self.assertEqual(integration.reusableInputs(doc), first)
            meta.write_text(json.dumps(metadata((100, 250, 401))))
            changed = integration.reusableInputs(doc)
            self.assertEqual(changed[str(image)], first[str(image)])
            self.assertNotEqual(changed[str(meta)], first[str(meta)])
            # the image half at the same path: exactly one pixel changes, the metadata is restored
            meta.write_text(json.dumps(metadata()))
            self.assertEqual(integration.reusableInputs(doc), first)
            from schemaxis.png import decode
            width, height, pixels = decode(sheet())
            pixels = bytearray(pixels)
            pixels[0] ^= 1
            image.write_bytes(png(width, height, bytes(pixels)))
            repainted = integration.reusableInputs(doc)
            self.assertNotEqual(repainted[str(image)], first[str(image)])
            self.assertEqual(repainted[str(meta)], first[str(meta)])
            image.write_bytes(sheet())
            self.assertEqual(integration.reusableInputs(doc), first)


class SheetCaptureTests(unittest.TestCase):
    def capture(self, data=None, meta=None, **options):
        node = plan(document(**options))['nodes'][1]
        return adaptor.capture_animation(node, 1, data or sheet(), json.dumps(meta or metadata()).encode())

    def test_capture_selects_the_forward_slice_with_seconds_and_independent_crops(self):
        entry, animation = self.capture()
        self.assertEqual([f['duration'] for f in animation['frames']], [0.1, 0.25, 0.4])
        self.assertEqual([f['rect'] for f in animation['frames']], [[0, 0, 4, 4], [4, 0, 4, 4], [8, 0, 4, 4]])
        for index, frame in enumerate(animation['frames']):
            self.assertEqual(frame['pixels'], bytes((10+40*index, 20, 200-30*index, 255))*16)
        self.assertEqual(entry['animation']['fps'], 1.0)
        self.assertEqual(entry['metadata']['sha256'], hashlib.sha256(json.dumps(metadata()).encode()).hexdigest())
        rgb_entry, rgb = self.capture(data=sheet(colour=2))
        self.assertEqual(rgb['frames'][0]['pixels'], bytes((10, 20, 200, 255))*16)

    def test_tag_slice_and_loop_are_explicit_not_inferred(self):
        _, animation = self.capture(animation='walk', loop=False)
        self.assertFalse(animation['loop'])
        meta = metadata(tags=[{'name': 'tail', 'fromFrame': 2, 'toFrame': 3, 'direction': 'forward'}])
        _, tail = self.capture(meta=meta, animation='tail')
        self.assertEqual([f['sheetFrame'] for f in tail['frames']], [2, 3])
        fault(self, lambda: self.capture(animation='rock'), 'UNSUPPORTED_ANIMATION_DIRECTION', '.options')
        fault(self, lambda: self.capture(animation='absent'), 'UNKNOWN_ANIMATION')

    def test_metadata_is_refused_with_structured_locations(self):
        def altered(edit, raw=None):
            meta = metadata()
            edit(meta)
            return self.capture(meta=meta)
        cases = [
            (lambda m: m['frames'][1].update(durationMS=0), 'INVALID_SPRITE_METADATA', 'frames[1].durationMS'),
            (lambda m: m['frames'][1].update(durationMS=True), 'INVALID_SPRITE_METADATA', 'frames[1].durationMS'),
            (lambda m: m['frames'][1].update(durationMS=250.5), 'INVALID_SPRITE_METADATA', 'frames[1].durationMS'),
            (lambda m: m['frames'][1].update(durationMS=5001), 'INVALID_SPRITE_METADATA', 'frames[1].durationMS'),
            (lambda m: m['frames'][1].update(x=2), 'INVALID_SPRITE_METADATA', 'frames[1]'),
            (lambda m: m['frames'][2].update(x=10), 'INVALID_SPRITE_METADATA', 'frames[2]'),
            (lambda m: m['frames'][2].update(width=3), 'INVALID_SPRITE_METADATA', 'frames[2]'),
            (lambda m: m['frames'][0].update(trim=1), 'UNSUPPORTED_SPRITE_METADATA', 'frames[0]'),
            (lambda m: m.update(version='schemaxis.aseprite.sheet/2'), 'UNSUPPORTED_VERSION', 'metadata.version'),
            (lambda m: m.update(height=5), 'INVALID_SPRITE_METADATA', 'metadata.height'),
            (lambda m: m.pop('tags'), 'INVALID_SPRITE_METADATA', 'metadata'),
            (lambda m: m['tags'][0].update(fromFrame=3, toFrame=2), 'INVALID_SPRITE_METADATA', 'tags[0]'),
            (lambda m: m['tags'][0].update(direction='backward'), 'INVALID_SPRITE_METADATA', 'tags[0].direction'),
            (lambda m: m['tags'].append(dict(m['tags'][0])), 'INVALID_SPRITE_METADATA', 'tags[2].name'),
            (lambda m: m.update(frames=[]), 'INVALID_SPRITE_METADATA', 'metadata.frames'),
        ]
        for edit, code, where in cases:
            with self.subTest(where=where, code=code):
                fault(self, lambda edit=edit: altered(edit), code, where)
        for text, code in ((b'{', 'INVALID_SPRITE_METADATA'), (b'\xff', 'INVALID_SPRITE_METADATA'),
                           (json.dumps(metadata()).replace('250', 'NaN').encode(), 'INVALID_SPRITE_METADATA'),
                           (b'{"version": 1, "version": 2}', 'INVALID_SPRITE_METADATA'), (b'x'*70000, 'RESOURCE_LIMIT')):
            with self.subTest(text=text[:12]):
                node = plan(document())['nodes'][1]
                fault(self, lambda text=text: adaptor.capture_animation(node, 1, sheet(), text), code, '.metadata')

    def test_png_and_budget_refusals_precede_native_work(self):
        node = plan(document())['nodes'][1]
        fault(self, lambda: adaptor.capture_animation(node, 1, b'not a png', b'{}'), 'INVALID_SPRITE_SHEET', '.options.file')
        wide = png(8, 1, bytes(32))
        fault(self, lambda: adaptor.capture_animation(node, 1, wide, json.dumps(metadata()).encode()), 'INVALID_SPRITE_METADATA', 'metadata.width')
        header = bytearray(sheet())
        header[16:24] = struct.pack('>II', 4097, 4)
        fault(self, lambda: adaptor.capture_animation(node, 1, bytes(header), b'{}'), 'RESOURCE_LIMIT', '.options.file')
        header[16:24] = struct.pack('>II', 4, 257)
        fault(self, lambda: adaptor.capture_animation(node, 1, bytes(header), b'{}'), 'RESOURCE_LIMIT', '.options.file')
        fault(self, lambda: adaptor.capture_animation(node, 1, sheet() + bytes(sprites.MAX_PNG_BYTES), b'{}'), 'RESOURCE_LIMIT')
        long_meta = metadata((5000, 4000))
        fault(self, lambda: self.capture(meta=long_meta, data=sheet(frames=2)), 'RESOURCE_LIMIT', '.options')


class PlaybackOracleTests(unittest.TestCase):
    DURATIONS = [0.1, 0.25, 0.4]

    def test_schedule_covers_every_frame_boundary_wrap_and_end(self):
        looping = sprites.sample_targets(self.DURATIONS, True)
        self.assertEqual(looping, sorted(set(looping)))
        for boundary in (0.1, 0.35, 0.75):
            self.assertTrue(any(abs(t-boundary) < 0.02 and t < boundary for t in looping), boundary)
            self.assertTrue(any(abs(t-boundary) < 0.02 and t > boundary for t in looping), boundary)
        self.assertGreater(max(looping), 1.5)
        once = sprites.sample_targets(self.DURATIONS, False)
        self.assertGreater(max(once), 1.0)
        self.assertEqual(sprites.locate(self.DURATIONS, False, 5.0)[:3], (2, 1.0, False))

    def test_locate_derives_frame_and_progress_independently(self):
        frame, progress, playing, _ = sprites.locate(self.DURATIONS, True, 0.225)
        self.assertEqual((frame, playing), (1, True))
        self.assertAlmostEqual(progress, 0.5)
        self.assertEqual(sprites.locate(self.DURATIONS, True, 0.8)[0], 0)
        self.assertEqual(sprites.locate(self.DURATIONS, True, 1.3)[0], 2)

    def state(self, elapsed, frame, progress, playing=True, target=None):
        return {'target': elapsed if target is None else target, 'elapsed': elapsed, 'frame': frame, 'progress': progress, 'playing': playing}

    def test_native_like_states_pass_and_wrong_timing_fails(self):
        good = [self.state(0.05, 0, 0.5), self.state(0.112, 1, 0.054), self.state(0.55, 2, 0.5045),
                self.state(0.762, 0, 0.132), self.state(1.3, 2, 0.5045)]
        for sample in good:
            self.assertIsNone(sprites.check_sample(self.DURATIONS, True, sample), sample)
        for sample in (self.state(0.05, 1, 0.5), self.state(0.55, 2, 0.1), self.state(0.8, 0, 0.5, playing=False),
                       self.state(0.225, 1, float('nan')), self.state(0.225, 3, 0.5), self.state(0.225, 1, 0.5, target=0.5)):
            self.assertIsNotNone(sprites.check_sample(self.DURATIONS, True, sample), sample)
        swapped = [0.25, 0.1, 0.4]
        self.assertIsNotNone(sprites.check_sample(swapped, True, self.state(0.225, 1, 0.5)))
        self.assertIsNotNone(sprites.check_sample([0.4, 0.25, 0.1], True, self.state(0.05, 1, 0.1)))

    def test_nonlooping_end_state_is_required_after_the_last_frame(self):
        self.assertIsNone(sprites.check_sample(self.DURATIONS, False, self.state(1.25, 2, 1.0, playing=False)))
        self.assertIsNotNone(sprites.check_sample(self.DURATIONS, False, self.state(1.25, 0, 0.1)))
        self.assertIsNotNone(sprites.check_sample(self.DURATIONS, False, self.state(1.25, 2, 1.0, playing=True)))

    def test_tolerance_is_the_derived_tick_plus_ratio_distance_sum(self):
        self.assertAlmostEqual(sprites.tolerance(self.DURATIONS, True, 0.01), sprites.TICK)
        # one crossing 0.1 -> 0.25 contributes TICK*|2.5-1|, not TICK*max(1, ratio)
        self.assertAlmostEqual(sprites.tolerance(self.DURATIONS, True, 0.112), sprites.TICK*(1+1.5))
        # equal durations never add error beyond the quantisation tick
        self.assertAlmostEqual(sprites.tolerance([0.1, 0.1, 0.1], True, 1.5), sprites.TICK)
        # a shrinking ratio contributes |r-1|, a growing one more
        self.assertAlmostEqual(sprites.tolerance([0.25, 0.1], False, 0.26), sprites.TICK*(1+0.6))
        self.assertGreater(sprites.tolerance([0.01, 4.0], True, 0.05), sprites.tolerance([0.1, 0.1], True, 0.05))
        # changed-timing worst case across two laps, with the wrap crossing included
        self.assertAlmostEqual(sprites.tolerance([0.25, 0.1, 0.4], True, 1.512), 0.00895)

    def test_changed_timing_sample_at_1512_rejects_the_wrong_frame_and_accepts_the_right_one(self):
        changed = [0.25, 0.1, 0.4]
        self.assertIsNone(sprites.check_sample(changed, True, self.state(1.512, 0, 0.048)))
        for wrong in (self.state(1.512, 2, 1.0), self.state(1.512, 1, 0.1), self.state(1.512, 2, 0.5)):
            message = sprites.check_sample(changed, True, wrong)
            self.assertIn('frame', message, wrong)
        self.assertEqual(sprites.locate(changed, True, 1.512)[0], 0)
        self.assertTrue(1.512 in sprites.sample_targets(changed, True))

    def test_every_planned_boundary_sample_is_decisive_for_exact_frames(self):
        for durations in ([0.1, 0.25, 0.4], [0.25, 0.1, 0.4], [0.4, 0.25, 0.1], [0.02]*32, [0.1]*3, [0.05, 0.5], [0.1], [0.3, 0.3]):
            for loop in (True, False):
                with self.subTest(durations=durations[:3], loop=loop):
                    for target in sprites.sample_targets(durations, loop):
                        self.assertTrue(sprites.decisive(durations, loop, target), target)
                        for late in (0.0, 0.001, sprites.CLOCK_LATE):
                            expected, progress, playing, gap = sprites.locate(durations, loop, target+late)
                            self.assertGreater(gap, sprites.tolerance(durations, loop, target+late))
                    # a frame one off at the planned +/-12 ms boundary samples must be refused
                    edge = [t for t in sprites.sample_targets(durations, loop) if abs(t-durations[0]) < 0.02 and len(durations) > 1]
                    for target in edge:
                        frame, progress, playing, _ = sprites.locate(durations, loop, target)
                        sample = self.state(target, (frame+1) % len(durations), 0.5)
                        self.assertIsNotNone(sprites.check_sample(durations, loop, sample))

    def test_samples_inside_the_bound_of_a_boundary_fail_closed(self):
        # 1 ms past a boundary is inside the 1 ms tick plus ratio shift: undecidable, never waved through
        message = sprites.check_sample(self.DURATIONS, True, self.state(0.101, 1, 0.01))
        self.assertIn('not decidable', message)
        self.assertIn('not decidable', sprites.check_sample(self.DURATIONS, True, self.state(0.101, 0, 0.99)))
        self.assertIn('not decidable', sprites.check_sample(self.DURATIONS, False, self.state(0.75+0.001, 2, 1.0, playing=False)))

    def test_clips_the_one_millisecond_clock_cannot_resolve_are_refused_before_native_work(self):
        node = plan(document())['nodes'][1]
        for durations in ((1, 1, 1), (100, 1), (1, 5000), (10, 10, 10)):
            with self.subTest(durations=durations):
                meta = metadata(durations)
                data = sheet(frames=len(durations))
                found = fault(self, lambda meta=meta, data=data: adaptor.capture_animation(node, 1, data, json.dumps(meta).encode()),
                              'UNSUPPORTED_ANIMATION_TIMING', '.options')
                self.assertIn('1 ms', found.message)
        # looping needs second-lap proof that a single long frame next to a short one cannot give
        meta = metadata((100, 5000))
        looping = sheet(frames=2)
        fault(self, lambda: adaptor.capture_animation(node, 1, looping, json.dumps(meta).encode()), 'UNSUPPORTED_ANIMATION_TIMING', '.options')
        once = plan(document(loop=False))['nodes'][1]
        _, animation = adaptor.capture_animation(once, 1, looping, json.dumps(meta).encode())
        durations = [f['duration'] for f in animation['frames']]
        for target in sprites.sample_targets(durations, False):
            self.assertTrue(sprites.decisive(durations, False, target))

    def test_dense_and_extreme_supported_clips_have_coherent_exact_bounds(self):
        for durations, loop in (([0.02]*32, True), ([0.02]*32, False), ([0.04, 0.1], True), ([0.1, 5.0], False), ([0.25]*32, False)):
            targets = sprites.sample_targets(durations, loop)
            for target in targets:
                frame, _, playing, gap = sprites.locate(durations, loop, target)
                self.assertGreater(gap, sprites.tolerance(durations, loop, target), (durations[:2], loop, target))


@unittest.skipUnless(os.environ.get('GODOT_EXECUTABLE'), 'GODOT_EXECUTABLE is not configured')
class AnimatedSpriteNativeTests(unittest.TestCase):
    def test_generated_sheet_builds_reopens_plays_and_verifies(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base/'sheet.png').write_bytes(sheet())
            (base/'sheet.json').write_text(json.dumps(metadata()))
            doc = document(file=str(base/'sheet.png'), metadata=str(base/'sheet.json'))
            result = run(doc, base/'run', os.environ['GODOT_EXECUTABLE'], 60)
            self.assertTrue(result['verified'])
            self.assertTrue(verify(base/'run')['verified'])
            playback = json.loads((base/'run'/'playback.json').read_text())
            self.assertEqual({s['frame'] for s in playback['sprites']['hero']['samples']}, {0, 1, 2})
            self.assertEqual((base/'run'/'animation_hero.rgba').read_bytes(),
                             b''.join(bytes((10+40*i, 20, 200-30*i, 255))*16 for i in range(3)))


if __name__ == '__main__':
    unittest.main()
