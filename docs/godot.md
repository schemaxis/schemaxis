# Godot scene adaptor

`schemaxis.godot/1` constructs small editable 3D Godot projects from declared JSON.
The host uses Python's standard library and Schemaxis's existing validation/fault
modules; Godot runs in two separate headless processes, with an optional third
graphical process for a PNG preview. No authored GDScript,
native reflection, arbitrary properties, or shell commands are accepted.

## API for integration

Import from `schemaxis.adaptors.godot` or `schemaxis.adaptors.godot.adaptor`:

| API | Contract |
| --- | --- |
| `DECLARATIONS` | Mapping of operation name to `native`, `kinds`, `options` with nested `value` declarations, and typed `inputs`. |
| `plan(document)` | Pure, deterministic JSON-compatible plan, version `schemaxis.godot.plan/1`. Does not launch Godot or read geometry files. Defaults are expanded; input is not mutated. |
| `schema()` | Closed JSON Schema for literal `schemaxis.godot/1` documents. Cross-node and camera constraints are enforced by `plan`. |
| `run(document, directory, executable=None, timeout=120)` | Builds and reopens in distinct Godot processes, verifies readback, returns a JSON-compatible verified result. Directory must not exist. Executable must be absolute, or set `GODOT_EXECUTABLE`. Timeout is a total budget across all native stages including optional preview, in seconds, bounded to `(0, 3600]`. |
| `verify(directory)` | Offline validation of retained input, receipts, digests, and native readback. Does **not** launch Godot again. Raises a structured fault for incomplete or modified evidence. |

All domain faults are `schemaxis.core.faults.SchemaxisError` with a stable code, location and
recovery guidance. Failed native runs retain `result.json` with `verified: false`,
the structured fault and native logs. Preflight failures do not create a job.
The returned successful result contains `status`, `verified`, `artifacts` (2),
`nodeCount`, `runtime`, and absolute `project` and `scene` paths. With
`"preview": true`, `artifacts` is 3 and `preview` is the absolute PNG path.

The adaptor registers its host-safe contracts in its own `adaptor.json`. Shared
CLI, schema, console and reference entry points discover that manifest and
delegate to these functions. Workflow scheduling, verified artifact handoffs and resume are supported.
See [media workflows](media-workflows.md) for PNG sprite placement and artifact order. Geometry file dependencies are the `options.file` values on
`readGLTF` nodes. Scheduling should use one serial native job; no MPI, simulation
time series, general rendering or physics execution contract is provided.

## Authoring

The top-level keys are `version`, optional `units` (`m` only), `nodes`, and
optional Boolean `preview` (default false).
There must be 1–128 declarations, exactly one camera and at least one geometry or sprite
node. Identifiers match `[A-Za-z][A-Za-z0-9_]{0,63}` and must be unique.
Nodes use `id`, `filter`, optional `options`, and typed `inputs`.

| Filter | Options | Inputs |
| --- | --- | --- |
| `transformGroup` | Local XYZ `position`, degree XYZ `rotation`, positive XYZ `scale` | Optional `parent` group |
| `material` | RGB `colour`, `roughness`, `metallic`, all channels in `[0,1]` | None |
| `box` | Positive XYZ `size`, XYZ `position` | `material` |
| `sphere` | Positive `radius`, XYZ `position` | `material` |
| `cylinder` | Positive `radius`, `height`, XYZ `position` | `material` |
| `plane` | Positive XZ `size` pair, XYZ `position` | `material` |
| `readGLTF` | Absolute `.gltf` `file`, XYZ `position` | `material` |
| `sprite3D` | Absolute PNG `file`, XYZ `position`, `pixelSize` in metres per pixel | None |
| `animatedSprite3D` | Sheet PNG `file`, `metadata` (`schemaxis.aseprite.sheet/1`), tag `animation`, Boolean `loop`, `pixelSize`, XYZ `position` | Optional `parent` group |
| `camera` | `position`, `target`, degree `fov`, `near`, `far`, Boolean `orbit` | None |
| `directionalLight` | Degree XYZ `rotation`, RGB `colour`, `energy` | None |

Material inputs must reference earlier material declarations; every declared
material must be used so it is preserved and verified. Materials are native
`StandardMaterial3D` resources, geometry is native `MeshInstance3D`, and all
scene nodes are owned by the saved root. Primitive meshes retain their editable
native parameters. Geometry has local position, rotation (degrees, Godot's YXZ Euler
order) and scale; optional parent groups organise static assemblies (see below). Coordinates are metres, Y is up,
and cameras look down -Z.
Camera target must be separated from its position and not parallel to Y.
Camera clipping requires `near < far`; visibility/framing is the author's choice.

Primitive dimensions are limited to 0.001–10000 m, and positions to ±100000 m.
Sphere tessellation is fixed at 32 radial segments and 15 rings, which includes
the equator; cylinders use 32 radial segments and one ring. `schema()` exposes
all numerical limits and defaults.

See `examples/schemaxis/godot-primitives.json` for a runnable scene.
`examples/schemaxis/godot-gltf.json` is a template: replace its absolute file path.

## Geometry import and loss limits

The deliberately narrow glTF 2.0 subset accepts one scene, one identity mesh
node, one mesh, one TRIANGLES primitive, embedded base64 buffers, float32
POSITION and optional NORMAL attributes, and optional unsigned indices.
Each resource is at most 8 MiB, all resources total at most 32 MiB, with at most
three buffers/views/accessors and 100000 elements per accessor. External URIs,
GLB, transforms, materials, textures, animation, skins, morph targets and
extensions are rejected, not silently discarded. Geometry receives the declared
Schemaxis material. The resulting native mesh is an editable `ArrayMesh` rather
than a live link to the glTF file.

Input bytes are captured and hashed before native import. Bounds are computed
independently from POSITION bytes, not trusted glTF extrema. Retained source
bytes, native bounds and triangle count are checked offline. The original source
may move or disappear after capture; verification uses the retained copy.
This does not establish vertex-by-vertex topology, normal or visual equivalence.

## Native output and verification

`run` writes `project.godot`, then uses Godot's `PackedScene.pack` and
`ResourceSaver.save` to create `scene.tscn`. A second process loads and
instantiates the saved scene with the resource cache ignored. Both receipts
record runtime, process id, node count, node ownership, geometry bounds and
primitive parameters/tessellation, material values, light values and camera
pose, projection settings and orbit state. Verification compares the receipts
with each other and with the declared input. It checks SHA-256 digests of the
project, scene, trusted scripts and retained glTF files.

Readback uses relative and absolute tolerances of `1e-5` for Godot single-precision
values; Godot can give flat imported mesh AABBs approximately `1e-5` m thickness.
Receipts and hashes detect accidental changes; they are not signed attestations
against an actor able to rewrite all evidence.

Keep the output directory together. `orbit.gd` is a fixed trusted generated
asset, not authored code. Open `project.godot` in Godot 4 and run the scene:
left-drag orbits, the wheel zooms, and R resets the camera. `orbit: false` produces
a fixed camera without an attached script. The remaining job JSON, logs and
`worker.gd` are retained for audit. Editing the saved scene is supported in Godot,
but intentionally invalidates the original verification receipt.

`verify` also reads the retained `scene.tscn` as streamed text (never
executed) and compares it with the plan independently of the native receipts:
node names, Godot types, full parent paths, absence of foreign ownership,
instancing or group attributes, local transforms of groups and geometry, camera
direction, and any declared `position`. A scene whose hierarchy or placement was
edited therefore fails even if its hash manifests were regenerated. A contradiction
raises `VERIFICATION_FAILED` at `scene.tscn` with the line; unreadable scene text
raises `SCENE_MALFORMED` and an oversized file `RESOURCE_LIMIT`. Keep a
hand-edited scene as an unverified human revision, or rerun the adaptor in a
fresh directory. This does not compare materials, mesh resources or light and
camera settings in the text scene; those remain covered by the native receipts.

## Qualification

```bash
PYTHONPATH=src GODOT_EXECUTABLE=/absolute/path/to/godot \
  python3 -m unittest discover -s tests/unit -p test_schemaxis_godot.py -v

PYTHONPATH=src python3 tools/qualify_godot.py \
  --executable /absolute/path/to/godot \
  --directory /absolute/path/to/fresh-evidence --timeout 60
```

The qualifier constructs/reopens all four primitives, an independently measured
indexed glTF triangle and a fixed-camera variant. It checks rejection of altered
bounds, node count, material, camera and process evidence, and launches the
saved project's actual main scene for three headless frames. Native checks use
small CPU-only scenes. They do not establish visual quality, GUI editing or
mouse interaction. Godot 4.7.2 was used for local native qualification.

## Optional rendered console image

Set `"preview": true` on a complete scene document. This adds one fixed 640×480
`preview.png` to the artifact hash manifest and result. The existing console
manifest fallback can serve it without changes to shared console code:

```text
set document preview true
preview
image
```

The preview is rendered from the saved scene in an isolated Xvfb display using
Godot's actual X11/OpenGL compatibility renderer, Mesa software rendering and
two llvmpipe threads. It requires Linux `xvfb-run` (including its X server/auth
utilities), Mesa/OpenGL and an X11-capable Godot build. Missing `xvfb-run` raises
`PREVIEW_UNAVAILABLE`; native startup/render failures remain structured faults
with `render.log`. No preview silently substitutes a blank headless image.

The worker waits for three completed render frames, captures the viewport,
saves PNG, reloads it natively and compares every decoded pixel. It records
the real display/renderer, process id, scene readback and PNG digest in
`rendered.json`. Host verification checks PNG dimensions, chunk CRCs, bounded
decompression, scanline lengths/filter bytes and the artifact digest. A valid
capture may be visually empty if the authored camera misses the geometry;
successful capture is not a visibility assertion. The render process and its
Xvfb wrapper share the job timeout and dispatcher cancellation context. Normal
runs still require no graphical display.

Build, reopen and render all use `schemaxis.dispatch.SubprocessRunner` with
`schemaxis.core.runners.Interpreter`. A fixed host-Python replay uses `os.execvpe` to become
Godot (or `xvfb-run`), preserving the PID/session tracked by the dispatcher.
Authored values are never executed as source. Inherited allocation/cancel state
is not replaced. Cancellation and timeout retain the shared `RUNNER_CANCELLED`
and `RUNNER_TIMED_OUT` fault codes and an unverified failed result. Each stage
receives only the remaining monotonic deadline budget; cleanup may additionally
take the dispatcher's termination grace period. No next stage launches after
the budget expires. Replay sources, full logs and metrics are under
`.dispatch/<stage>/`; `<stage>-submission.json` records the native argv as well
as the host replay command. `<stage>.log` remains available for convenience.

Add `--preview` to `tools/qualify_godot.py` to exercise this path. Set
`GODOT_GRAPHICAL_TESTS=1` alongside `GODOT_EXECUTABLE` to run the graphical unit
test, which checks that changing the material changes the actual PNG pixels.
Local graphical qualification used Godot 4.7.2 and Mesa llvmpipe. The image was
also visually inspected; GUI editing and mouse interaction were not qualified.

The capture follows Godot's documented
[viewport post-draw screenshot API](https://docs.godotengine.org/en/stable/classes/class_viewport.html#class-viewport-method-get-texture).

Official API references consulted:

- [PackedScene ownership and packing](https://docs.godotengine.org/en/stable/classes/class_packedscene.html)
- [GLTFDocument runtime import](https://docs.godotengine.org/en/stable/classes/class_gltfdocument.html)
- [Node3D transforms and look-at](https://docs.godotengine.org/en/stable/classes/class_node3d.html)

## Development admission

This adaptor now provides the [development kit](adaptor-development.md) delivery
contract, operation selection guidance, explicit optional-feature decisions and
an editable [acceptance example](../examples/schemaxis/godot-admission.json).
Run the common host/native conformance recipe and inspect its scoped source-bound
receipt; structural admission alone is not native qualification. The
[current audit](design/adaptor-framework/AUDIT.md) records native availability and
exact qualification limits.

## Static assemblies

Use `transformGroup` to name a pivot and move a static geometry assembly together.
It creates a non-renderable native `Node3D`. Its optional `position` (XYZ metres,
zero by default), `rotation` (XYZ degrees, zero by default) and `scale` (positive
XYZ factors, one by default) define its transform relative to its parent.
Every geometry operation and `transformGroup` accepts optional `inputs.parent`:

```json
{"id":"arm","filter":"transformGroup",
 "options":{"position":[1,0,0],"rotation":[0,0,45],"scale":[1,3,1]},
 "inputs":{"parent":"assembly"}}
```

Omit `parent` to attach to the saved scene root. Parent ids may refer forward;
the planner orders dependencies deterministically and rejects missing groups,
non-group parents and cycles. Materials still reference earlier declarations.
Flat documents retain their original order and meaning. Cameras, lights and
sprites remain at the root; camera targets and orbit controls keep their existing
world-space interpretation. This slice does not add animation, physics, scene
instancing or Godot's unrelated named membership groups.

Transforms use Godot's intrinsic YXZ Euler convention: apply local scale, then
Z, X and Y rotations, then translation; apply each ancestor transform afterward.
Non-uniform ancestor scales with rotated descendants can produce shear. Both
execution and the independent host verifier preserve the complete affine basis;
neither approximates it by adding Euler angles or multiplying axis scales.
Individual scales must be in `[0.001,1000]`; negative/mirrored and zero scales are
unsupported. Hierarchies allow at most 16 parent links, world-position components
within ±1000000 m, and world basis-column lengths within `[0.000001,10000]`.
`DEPENDENCY_CYCLE`, `INVALID_DEPENDENCY`, `TYPE_MISMATCH` and `RESOURCE_LIMIT`
identify the affected parent field; remove a cyclic link, use a group id, or
reduce the nesting/accumulated transform respectively.

The fresh native process recursively measures every saved node. It records its
actual parent, scene-root owner, local and global basis, global position and
transform inheritance. Geometry `bounds` are world AABBs formed by transforming
the original mesh-local AABB corners. Group `bounds` are the union of descendant
geometry world AABBs; an empty group has `null` bounds. These are bounding boxes,
not precise oriented surface envelopes or collision geometry. All descendants
are owned by the root after `add_child`, so `PackedScene.pack` saves them even
when their immediate parent is another group. Native readback is checked against
host affine composition, not only against the first native receipt. The existing
`1e-5` absolute and relative single-precision tolerances apply.

The editable [nested assembly example](../examples/schemaxis/godot-hierarchy.json)
uses forward parents and nested rotations/non-uniform scale. Studio's **Static
transform assembly** starter adds a pivot and two locally positioned blocks.
The bounded qualifier below checks independently derived literal world values,
a changed ancestor transform, empty/aggregate group bounds, the legacy flat
scene, ten jointly forged receipt variants and live timeout/cancellation retention:

```sh
PYTHONPATH=src python3 tools/qualify_godot_hierarchy.py \
  --executable /absolute/path/to/godot --directory evidence/godot-hierarchy
```

This slice was freshly exercised with official Godot 4.7.2 on 17 October 2026.
Graphical interaction, animation and physics are outside this acceptance scope.
The [completion review](../verification/2026-10-17-godot-completion.md) separates
these new checks from prior flat-scene and preview qualification.
Official [Node3D transforms](https://docs.godotengine.org/en/stable/classes/class_node3d.html),
[Node ownership](https://docs.godotengine.org/en/stable/classes/class_node.html#class-node-property-owner)
and [PackedScene packing](https://docs.godotengine.org/en/stable/classes/class_packedscene.html#class-packedscene-method-pack)
were reviewed for the implementation.

The saved-scene structural check reads the canonical single-line node properties written by Godot’s saver. It rejects incomplete or multiline node assignments, non-canonical placement aliases and non-identity root placement; it is not a general Godot text-scene editor. Resource/material contents and script bindings remain outside this structural text check.

The lexical scan tracks strings and balanced resource values across the whole file, so resource text cannot masquerade as a node header. Multiline resource dictionaries are allowed; complete tags and single-line node values cannot hide a second assignment or tag after their closing token.

Saved scenes have no new whole-file size ceiling: embedded mesh resources can exceed 4 MiB under the existing import envelope. Resource values are scanned in 64 Ki-character chunks and hashes stream in 1 MiB chunks. Canonical tag and single-line node-property limits are 16384 and 65536 characters; resource nesting is limited to 64 levels. These guards cover the declared 128-node hierarchy and do not limit embedded resource payload size.


## Timed sprite animation

`animatedSprite3D` carries an Aseprite artist's per-frame timing into an editable
Godot scene. It is a product hypothesis for the Aseprite-to-Godot hand-off, not
evidence of customer demand. It reads two captured inputs from one Aseprite
publication, `sheet.png` and `sheet.json` (`schemaxis.aseprite.sheet/1`), selects
one named tag, and creates a native `AnimatedSprite3D` with its own `SpriteFrames`.
Inside a workflow, both fields are generic artifact references to the producer's
publications (zero-based `index` 2, the third publication, for the image and 3, the fourth, for the metadata; the Aseprite publications are `sprite.aseprite`, `preview.png`, `sheet.png`, `sheet.json`); absolute paths also work.

```json
{"id": "hero", "filter": "animatedSprite3D", "inputs": {"parent": "rig"},
 "options": {"file": {"$artifact": "sprite", "index": 2},
             "metadata": {"$artifact": "sprite", "index": 3},
             "animation": "pulse", "loop": true, "pixelSize": 0.05, "position": [0, 0.5, 0]}}
```

**Supported meaning.** The named tag must run `forward`; its frames
(`fromFrame` to `toFrame`, one-based, inclusive) play in order. `loop: true`
repeats, `false` plays once and holds the last frame. Reverse, `pingPong` and
`pingPongReverse` tags are refused (`UNSUPPORTED_ANIMATION_DIRECTION`) rather than
flattened, other tags are not imported, and the metadata must be exactly
`version`, `width`, `height`, `frames` (`x`, `y`, `width`, `height`, `durationMS`)
and `tags` (`name`, `fromFrame`, `toFrame`, `direction`). Trimmed frames, offsets,
layers, slices and user data do not exist in this contract.

**Time.** Godot stores frame durations as *relative* weights; a frame lasts
`duration / (animation FPS x playing speed)` seconds. Schemaxis never infers a
rate: the animation speed is fixed at 1 frame per second, `speed_scale` stays 1,
and each frame's duration is `durationMS / 1000`, so the Aseprite milliseconds are
the playing seconds. Editing speed in Godot later rescales every frame together.
Godot saves the durations as 32-bit floats, hence the existing `1e-5` readback
tolerance.

**Bounds, all enforced before Godot starts.** PNG at most 1 MiB, 4096 x 256 pixels
and 524288 decoded pixels, non-interlaced 8-bit RGB or RGBA; metadata at most 64 KiB;
1 to 32 frames of one size, each at most 256 x 256, inside the sheet and not
overlapping; each `durationMS` 1 to 5000 (whole integers, no NaN or fractions); the
slice at most 8000 ms; at most four animated sprites per scene. Faults carry
structured locations such as `$.nodes[1].options.metadata:metadata.frames[2].durationMS`.
The adaptor owns its decoder use and metadata reader; it imports no other adaptor.

**Native evidence.** Both inputs are captured and hashed; the same unchanged path
bytes reuse a workflow result and changed bytes of either invalidate it. Godot builds
the `SpriteFrames` (an `AtlasTexture` per frame into one sheet texture, durations,
speed, loop mode), attaches the node (`autoplay` set to the animation), saves
`scene.tscn`, and a fresh process reopens it with the cache ignored and reads back every
rectangle, duration, order, loop mode, frame pixel digest, and writes the raw frame
pixels to `animation_<id>.rgba`. The host independently crops the captured sheet and
reads `scene.tscn` text (sub-resources, regions, durations, loop mode, name) to compare
byte-for-byte and value-for-value.

A third fresh process, `playback`, loads the saved scene and advances the real
`AnimatedSprite3D` through SceneTree process frames at `--fixed-fps 1000` after a
150-frame warm-up (startup deltas are not uniform; the receipt records min and max
delta, both exactly 1 ms). Samples are taken from the node's own `frame`,
`frame_progress`, `is_playing()` and playing speed at times inside every frame, around
every boundary, across the loop wrap and past the end of a non-looping slice. The host
derives the expected frame and progress from the authored durations alone.

**Observed limit.** Godot 4.7.2 computes the playing rate before it advances the frame, so
the rest of a tick that crosses a boundary runs at the *previous* frame's rate and the
leftover `frame_progress` fraction, not leftover time, carries over. A crossing from a
frame of duration `d_old` to one of `d_new` therefore mis-times by at most one tick times
`|d_new/d_old - 1|`. The verifier's bound is one tick plus that term for every crossing
reached (not a ratio-capped or tuned figure). Boundary samples are placed 12 ms either side when that is decisive; otherwise
at the first decisive offset from a fixed list (12 ms multiplied by powers of 1.5, or
30%, 20% and 10% of the shorter adjacent frame). If none is decisive, the clip
is refused. Every planned sample must lie farther from
a possible boundary than the bound, and its expected frame is exact; a sample inside the bound fails closed.
When the bound cannot be met (frames of a few milliseconds, or a frame many times longer
or shorter than its neighbour, especially when looping) the clip is refused before Godot
starts with `UNSUPPORTED_ANIMATION_TIMING`: the fixed 1 ms playback clock cannot tell its
frames apart, which limits what can be verified, not what Godot can play. This does not
certify rendered appearance, GUI playback, vsync pacing or frame-skipping at other frame rates.
Official [SpriteFrames](https://docs.godotengine.org/en/stable/classes/class_spriteframes.html)
and [AnimatedSprite3D](https://docs.godotengine.org/en/stable/classes/class_animatedsprite3d.html)
references were re-read for this operation; `set_animation_loop` is deprecated, so
`set_animation_loop_mode` is used.

`tools/qualify_godot_animation.py` runs the real Aseprite producer (the locally
configured executable, reported as observed, not as the latest release), the
workflow hand-off, changed duration/pixel/order/loop cases, metadata and rectangle
controls, hash-refreshed semantic mutants, timeout and cancellation retention, and
legacy static-sprite and hierarchy controls. Its hash-refreshed mutants also refresh the
publication metadata and prove it current before expecting the semantic reason, and include a
source-PNG pixel mutant. The saved project's main scene is also run headless at a fixed tick so its
`autoplay` is observed advancing. The development kit's `animated-sprite` and
`animated-sprite-variant` cases use the committed 24x8 sheet fixtures
(`tools/generate_godot_animation_fixtures.py --check`) with literal durations, rectangles, loop
mode, frame pixel hashes and decisive playback frames; they do not claim shared timeout or
cancellation of the sampling loop.
