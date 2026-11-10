# Godot animatedSprite3D completion review — 26 October 2026

Changed scope: new operation `animatedSprite3D` on `schemaxis.godot/1`, a timed
`AnimatedSprite3D`/`SpriteFrames` built from an Aseprite sheet PNG and its
`schemaxis.aseprite.sheet/1` metadata. This is a product hypothesis (a technical
artist carrying authored frame timing from Aseprite into an editable Godot scene),
not evidence of customer demand. Static `sprite3D`, geometry, transforms,
hierarchy, preview and the retained legacy outputs are unchanged and re-run as
controls. `absorbedVersion` stays 4.7.2; this review does not advance it.

## Decisions

- **Time.** SpriteFrames durations are relative. The animation speed is fixed at
  1 frame per second and each duration is `durationMS / 1000`, so authored
  milliseconds are playing seconds; no rate is inferred. `set_animation_loop_mode`
  is used because `set_animation_loop` is deprecated in the 4.7 API.
- **Tag scope.** One named tag, forward only. Reverse and ping-pong are refused
  (`UNSUPPORTED_ANIMATION_DIRECTION`); other tags are not imported; unknown
  metadata keys, trimming and offsets are refused or absent from the contract.
- **Bounds.** At most 32 frames of 256x256 in a 4096x256 / 524288-pixel sheet,
  PNG 1 MiB, metadata 64 KiB, durations 1-5000 ms, slice at most 8000 ms, at most
  four animated sprites per scene. All are enforced before any native process.
- **Placement.** `pixelSize`, local `position` and an optional `parent` group.
- **Observed native limit.** Godot 4.7.2 computes the playing rate before advancing
  the frame, so a boundary crossing carries the leftover `frame_progress` fraction,
  not leftover time. The verifier's bound is one tick plus `tick*|d_new/d_old-1|` per
  crossing reached. Boundary samples use 12 ms either side when decisive; otherwise the first
  decisive offset from a fixed list (12 ms multiplied by powers of 1.5, or 30%, 20% and
  10% of the shorter adjacent frame). This may be closer or farther. If none is
  decisive, the clip is refused. Every planned sample must be farther from a boundary than the bound and
  is compared with an exact frame; a sample inside the bound fails closed, and clips
  whose frames the 1 ms clock cannot tell apart are refused before Godot starts
  (`UNSUPPORTED_ANIMATION_TIMING`). Rendered appearance, GUI playback, pacing and other
  frame rates are not covered. `--frame-delay` has no effect together with `--fixed-fps`;
  live timeout and cancellation of the playback stage therefore use a blocking `wait.gd`
  Godot process as a stand-in for that stage. This proves the shared runner's handling and
  evidence retention, not interruption in the middle of the sampling loop.

## Checklist

| ID | Result |
| --- | --- |
| registration | Route accepts `spriteMetadata` beside `image` and `spriteSheet`; no new route or app-name branch. |
| schema | `animatedSprite3D` is the last `oneOf` alternative so existing guidance addresses are stable; generated schemas/reference regenerated and `--check` passes. |
| semantics | Planner: absolute paths, tag-name pattern, group parent, count; capture: strict metadata, rectangles, PNG header budget before decode; faults carry `$.nodes[i].options.metadata:metadata.frames[k].field`. |
| native-mapping | `SpriteFrames` (`AtlasTexture` per frame into one sheet `ImageTexture`, relative durations, speed 1, loop mode), `AnimatedSprite3D` (`autoplay`, `pixel_size`, nearest filtering), saved with `PackedScene`. API pages for SpriteFrames and AnimatedSprite3D re-read on 26 October 2026. |
| execution | Third fresh process `playback` through the shared runner (`--fixed-fps 1000`, 150 warm-up frames, recorded min/max delta); timeout and cancellation retention checked. |
| discovery | Operation purpose/keywords, three positive and one negative search case (`skeletal rig animation tween`). |
| guidance | Operation and all 13 field/structural addresses reviewed; `studio_guidance.py --app godot --check` clean. |
| help | Packaged Studio help regenerated; `--check` passes. |
| fixtures | Committed original sheet and two metadata documents with a generator and `--check`; two development-kit cases. |
| examples | Standalone host example, Aseprite-to-Godot workflow example, Studio snippet and template (baseline, play-once variant), one invalid example. |
| tests | `tests/unit/test_godot_animated_sprite.py` (plan, capture, refusals, same-path PNG and metadata reuse, oracle, wrong-frame/boundary/resolution cases, one native generated-sheet case). |
| qualification | `tools/qualify_godot_animation.py` (see evidence). Existing `qualification.json` receipts are not edited here and are stale for the new source. |
| maintenance | No `upstream.json` change. Godot 4.7.2 official stable is the observed runtime and equals the absorbed version. The local Aseprite executable reports 1.3.17.2, older than the latest release 1.3.18.6; it is recorded as the producer actually used, not as a current Aseprite qualification. |

## Not done / limits

The development kit has two cases, `animated-sprite` and `animated-sprite-variant`, built
from the committed 24x8 original fixtures (`examples/schemaxis/sprite-animation-fixture.png`,
`sprite-animation-fixture.json`, `sprite-animation-fixture-variant.json`, regenerated and checked by
`tools/generate_godot_animation_fixtures.py --check`) and the kit's `resources` map. Their
expectations are literals; they do not prove shared lifecycle probes for the sampling loop.
Timeout and cancellation of the playback stage are proved by the dedicated qualifier only.
`qualification.json` and `upstream.json` are not edited here, so route receipts are stale
until the parent reruns `adaptor conform --native`. No GUI, renderer, audio, scripts,
physics or tween claims are made. Reviewer judgement of the guidance prose and bound
derivation is still required.
