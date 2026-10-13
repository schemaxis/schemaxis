# Aseprite adaptor

`schemaxis.aseprite/1` creates small editable RGB sprites with normal image layers,
animation frames, a palette, filled raster shapes and animation tags. Host imports,
planning and schema generation require only Python 3.10+ and the existing Schemaxis
package. Native execution uses the separately installed, user-licensed Aseprite.

The adaptor is available directly from `schemaxis.adaptors.aseprite`:

```python
import json
from schemaxis.adaptors.aseprite import plan, run, verify, schema, DECLARATIONS

document = json.load(open('examples/schemaxis/aseprite-animation.json'))
prepared = plan(document)  # JSON-compatible; no native process or filesystem work
result = run(document, '/tmp/my-new-sprite-job',
             executable='/path/to/aseprite', timeout=60)
assert verify('/tmp/my-new-sprite-job')['verified']
```

`ASEPRITE_EXE` is the optional executable fallback. Supply an absolute executable
path and a fresh output directory. The timeout is per native process, greater than
zero and at most 600 seconds. Shared registry, CLI, scheduled workflows, generated references and console
integration are supported. See [media handoffs](media-workflows.md) for ordered
publications and the Godot/FFmpeg examples.
The conventional declarations module is `schemaxis.adaptors.aseprite.adaptor`.

## Document contract

A document has exactly `version`, `nodes` and `output`. Each node has an `id`,
`filter`, `options` and, except for the first node, `inputs: {"sprite": "previousId"}`.
All operations return kind `sprite`. Start with exactly one `sprite` node, use a
linear chain and select its final node as `output`. Branches are rejected because
native mutations operate on one editable sprite. Unknown keys and operations fail
before launching Aseprite; authored scripts and native reflection are unsupported.

| Filter | Options and meaning |
| --- | --- |
| `sprite` | Required `width`, `height`; initial `layer` defaults to `base`; `durationMS` defaults to 100; `colours` defaults to transparent and white. |
| `layer` | Required unique `name`; appends a visible normal layer above existing layers. |
| `frame` | Appends an empty frame; `durationMS` defaults to 100. No implicit frame copying. |
| `palette` | Required `colours`; replaces the global palette without changing RGB pixel values. |
| `pixel` | Required `layer`, `x`, `y`, `colour`; `frame` defaults to 1. |
| `rect` | Pixel options plus required positive `width`, `height`; filled rectangle. |
| `circle` | Pixel options plus required nonnegative integer `radius`; filled integer disk centred at `(x,y)`. |
| `tag` | Required unique `name`, `fromFrame`, `toFrame`; optional `direction`: `forward`, `reverse`, `pingPong`, `pingPongReverse`. |

Coordinates are zero-based canvas pixels; frame indices and tag endpoints are
one-based and inclusive. Rectangle coverage is `[x,x+width)` by `[y,y+height)`.
A circle includes pixels whose squared distance from its centre is at most the
squared radius; radius zero draws one pixel. Shapes must fit wholly inside the
canvas. Draw operations replace pixels in the selected cel. RGBA colours are four
integer bytes, with alpha restricted to 255 or transparent `[0,0,0,0]`. Transparent
drawing erases pixels. Partial alpha, blend modes, indexed colour, groups, external
image imports, fonts and arbitrary Lua are outside this version's contract.

Limits: 256 nodes, 256×256 canvas, 16 layers, 32 frames, 256 palette entries,
64-character layer/tag names, 1–65535 ms frame durations, and 262144 total
canvas×layer×frame pixels. `schema()` exposes structural validation; `plan()` also
enforces dependencies, bounds, resource limits and supported colour semantics.

## Outputs and evidence

Each job retains `authored.json`, `plan.json`, the exact trusted `worker.lua`,
separate `build.log` and `reopen.log`, and a structured `result.json`. Outputs are:

- `sprite.aseprite`: editable layers, frames, palette and tags.
- `preview.png`: the first composited frame.
- `sheet.png`: all composited frames in one horizontal row, untrimmed.
- `sheet.json`: `schemaxis.aseprite.sheet/1` metadata with sheet dimensions, per-frame
  rectangles and durations, and named tags with inclusive one-based endpoints.

The Lua worker is a fixed Python string packaged in `native_source.py`, copied to
the job directory. It reads authored values from validated JSON, without source
interpolation, `load`, shell commands or authored paths. The shared
`schemaxis.dispatch.SubprocessRunner` runs a trusted Python launcher that changes
to the job directory and replaces itself with Aseprite using `os.execv`.
This preserves the runner's process-group ownership, resource environment and
cooperative cancellation. Calls use argument arrays and no shell. Cancellation,
timeout and failed execution retain the structured `RUNNER_CANCELLED`,
`RUNNER_TIMED_OUT` and `RUNNER_FAILED` faults in `result.json`. Stage transcripts
remain available along with the runner's full logs, resource metrics and
successful `build-submission.json` / `reopen-submission.json` reports.
Aseprite remains a trusted local executable, not a
sandbox for hostile plugins or altered worker files.

A second native process reopens the `.aseprite` and both PNGs. Its independent
`verification.json` records runtime version, dimensions, layer order, frame
durations, palette, tags, every cel's canvas pixels and both PNGs' decoded pixels.
Cel trimming and absent empty cels are normalised to full transparent canvases.
The host compares this readback with a separately implemented Python integer
raster model, including normal-layer compositing and sheet frame placement.
Neither process exit zero nor file existence is accepted as success.

`verify(directory)` rechecks the authored plan, independent model, native receipt,
sheet metadata and SHA-256 digests of every publication, receipt and retained
worker. It is offline verification of retained evidence, not a new native reopen
and not a cryptographic attestation against coordinated evidence forgery. Missing,
altered, incomplete and invalid evidence fails with structured Schemaxis faults.

## Qualification

```bash
ASEPRITE_EXE=/path/to/aseprite \
  PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_schemaxis_aseprite.py -v
PYTHONPATH=src python3 tools/qualify_aseprite.py \
  --executable /path/to/aseprite \
  --output-directory /tmp/aseprite-qualification-new
```

The qualification exercises `aseprite-icon.json` (8×8, transparent cutout) and
`aseprite-animation.json` (16×16, two layers, two frames, palette and ping-pong tag).
It also reopens each editable file, adds a layer and known pixel, saves an editable
copy, and verifies that change in another fresh native process. Original verified
artifacts remain intact. A structured `qualification.json` summarises the checks.
This is bounded CPU batch acceptance; it does not claim GUI appearance review,
GPU support or exhaustive Aseprite feature coverage.

## Primary API references

Implementation uses the official [batch CLI](https://www.aseprite.org/docs/cli/),
[Sprite](https://www.aseprite.org/api/sprite),
[Image](https://www.aseprite.org/api/image),
[Palette](https://www.aseprite.org/api/palette),
[Tag](https://www.aseprite.org/api/tag) and
[JSON](https://www.aseprite.org/api/json) APIs.
Keep machine-specific installation guidance and smoke-test locations in private
installation notes, following [installation](installation.md).

## Development admission

This adaptor now provides the [development kit](adaptor-development.md) delivery
contract, operation selection guidance, explicit optional-feature decisions and
an editable [acceptance example](../examples/schemaxis/aseprite-admission.json).
Run the common host/native conformance recipe and inspect its scoped source-bound
receipt; structural admission alone is not native qualification. The
[current audit](design/adaptor-framework/AUDIT.md) records native availability and
exact qualification limits.
