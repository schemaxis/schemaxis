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
| `material` | RGB `colour`, `roughness`, `metallic`, all channels in `[0,1]` | None |
| `box` | Positive XYZ `size`, XYZ `position` | `material` |
| `sphere` | Positive `radius`, XYZ `position` | `material` |
| `cylinder` | Positive `radius`, `height`, XYZ `position` | `material` |
| `plane` | Positive XZ `size` pair, XYZ `position` | `material` |
| `readGLTF` | Absolute `.gltf` `file`, XYZ `position` | `material` |
| `sprite3D` | Absolute PNG `file`, XYZ `position`, `pixelSize` in metres per pixel | None |
| `camera` | `position`, `target`, degree `fov`, `near`, `far`, Boolean `orbit` | None |
| `directionalLight` | Degree XYZ `rotation`, RGB `colour`, `energy` | None |

Material inputs must reference earlier material declarations; every declared
material must be used so it is preserved and verified. Materials are native
`StandardMaterial3D` resources, geometry is native `MeshInstance3D`, and all
scene nodes are owned by the saved root. Primitive meshes retain their editable
native parameters. Geometry has position, rotation (degrees, Godot's YXZ Euler
order) and scale, but no authored hierarchy. Coordinates are metres, Y is up,
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
