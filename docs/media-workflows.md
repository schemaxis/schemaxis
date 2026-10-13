# Image, sprite and video workflows

Schemaxis's scheduled workflows now include Aseprite and Godot. Both publish
ordered, hashed artifact manifests and participate in verification and resume.
Aseprite procedural jobs have no external inputs; Godot hashes its embedded glTF
and PNG inputs before reuse. The scheduler rechecks producer evidence before any
handoff. Native application objects never cross processes.

## Published artifact order

| Producer | Index | Kind | Publication |
| --- | --- | --- | --- |
| Aseprite | 0 | `sprite` | Editable `sprite.aseprite` |
| Aseprite | 1 | `image` | First composited frame, `preview.png` |
| Aseprite | 2 | `spriteSheet` | Horizontal `sheet.png` |
| Aseprite | 3 | `spriteMetadata` | `sheet.json`, rectangles and durations |
| Godot | 0 | `project` | `project.godot`; retain the whole directory |
| Godot | 1 | `scene` | `scene.tscn`; retain its project/resources |
| Godot | 2, if requested | `image` | `preview.png` |
| FFmpeg | 0 | `video` | `video.mp4` or `video.mkv` |
| Inkscape | 0 | `text` | Editable `diagram.svg` |
| Inkscape | 1 | `image` | Measured page export, `diagram.png` |
| Inkscape | 2 | `text` | `diagram-measurements.json` |
| Shotcut | 0 | `video` | Verified cut timeline, `video.mkv` |
| Shotcut | 1 | `videoProject` | `project.mlt`; requires its captured media companions |
| Shotcut | 2 | `videoProjectBundle` | `project-bundle.zip`, containing the project and captured media |

Godot consumes `gltf`, `image` and `spriteSheet`; FFmpeg consumes `image`,
`spriteSheet` and `spriteMetadata`. Individual file options still enforce their
format contracts. Aseprite is a procedural producer in this release, not an image
importer. FreeCAD assemblies remain standalone.

Shotcut consumes `video` with the exact source-rate, dimension and frame-range
limits in its [timeline guide](shotcut.md). The [diagram-to-video workflow](diagram-video.md)
connects Inkscape PNGs to FFmpeg publication and Shotcut cuts, with portable project
bundles, independent frame-order checks, verified reuse and failed-producer blocking.

## Godot image placement

The new `sprite3D` operation embeds a PNG as an editable native `Sprite3D` with an
`ImageTexture`. It requires an absolute `file`, accepts a metre-valued `position`
and `pixelSize` (metres per source pixel, default 0.01). It needs no material input.
A scene still needs exactly one camera and at least one mesh or sprite.

Input is bounded non-interlaced 8-bit RGB/RGBA PNG; palette, grayscale, 16-bit and
interlaced images are rejected. The host decodes actual source pixels; a fresh
Godot process reopens the saved scene and checks the texture's dimensions and
SHA-256 of RGBA pixels. The texture is embedded, so the original PNG may disappear
without breaking offline verification or the saved scene. Images remain flat
sprites: this is not sprite-sheet animation playback or arbitrary game authoring.
The whole sheet is displayed unless the first-frame image is selected instead.

```bash
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/sprite-to-godot.json \
  --aseprite /absolute/aseprite --godot /absolute/godot \
  --output-directory /fresh/sprite-scene
```

## FFmpeg publication

`schemaxis.ffmpeg/1` declares exactly one node, with one of two operations:

- `encodeFrames`: `files` is an ordered array of absolute PNG paths or workflow
  artifact references. Repeated references repeat frames; there is no glob or
  implicit sorting.
- `encodeSheet`: `file` is the sheet PNG; `metadata` is a
  `schemaxis.aseprite.sheet/1` JSON artifact. Rectangles are extracted in metadata
  order. Frame durations must be exactly representable at the chosen rate.
  Tags are retained in the source metadata but do not select/reorder playback.

Common options are `fps` (integer 1–120, default 25), `codec` (`h264`, default,
 or `ffv1`), and `threads` (1–16, default 1). An explicit workflow thread
allocation must match the encoder setting. Use `--ffmpeg /absolute/ffmpeg`,
`FFMPEG_EXECUTABLE`, or an installed `ffmpeg` on PATH. A matching `ffprobe`
executable must be beside it. Launcher wrappers may configure a private runtime.

Limits: 600 encoded frames, 4096 pixels per dimension, bounded decoded/input byte
budgets (192 MiB), equal frame dimensions and the PNG subset above. H.264 requires
even width/height. Alpha is explicitly composited onto black. There is no audio,
colour-management guarantee, scaling, arbitrary filter graph or authored command
line. The first release does not add titles or comparison layouts.

`ffv1` writes a lossless Matroska video. Fresh native decoding must match every
RGB byte, including order and count. `h264` writes an MP4 with YUV420 conversion;
each decoded frame must have mean absolute RGB error no greater than 16/255.
Highly chromatic fine detail may fail this bound; use FFV1 in that case.
`ffprobe` independently reads dimensions, codec, frame count, rate and duration.
These checks establish bounded fidelity, not perceptual quality certification.

An optional root `deliverable` object expresses the media result you need:
`width`/`height` in pixels, exact `frames`, `durationSeconds`, `maxBytes` for the
encoded file, and `maxMeanRGBError` in RGB byte levels (0–16). Supply any subset
with at least one requirement. Duration uses absolute `durationToleranceSeconds`
(0–1 seconds, default 0.002); a tolerance requires a target duration. Quality is
the maximum of the mean absolute RGB errors measured for each decoded frame,
after alpha-on-black compositing. FFV1 is always byte-exact; its quality budget
cannot relax that invariant. A stricter H.264 budget can reject an otherwise
correct video.

```json
"deliverable": {
  "width": 1920, "height": 1080, "frames": 50,
  "durationSeconds": 2, "durationToleranceSeconds": 0.002,
  "maxBytes": 10000000, "maxMeanRGBError": 8
}
```

The policy checks observed native duration, source/native dimensions and frame
count, actual encoded byte size and full decoded pixel errors. The adaptor does
not resize or retime sources to satisfy these requirements. Each check retains
the expected and observed values, its outcome and a suggested corrective action
under `verification.json`'s `deliverable`. Offline verification reconstructs the
assessment from authored requirements and retained evidence. Invalid policies
fail during planning; invalid sources and native failures retain their own fault
codes. Correct videos with unmet requirements fail with `DELIVERABLE_NOT_MET` and
retain their video, native evidence and explained assessment. They are not
published as successful workflow handoffs. Adjust the source, fps or codec and
run in a fresh directory; there is no automatic encoder search.

The [portable deliverable example](../examples/schemaxis/ffmpeg-deliverable.json)
targets the kit's 2×2 PNG fixture. Replace its absolute placeholder to run it
directly. The bounded native acceptance recipe is:

```bash
PYTHONPATH=src python3 tools/qualify_ffmpeg_deliverable.py \
  --executable /absolute/ffmpeg --output-directory /fresh/media-deliverable
```

The run retains source bytes, the exact RGB sequence, decoded RGB, probe output,
commands, logs and evidence. New decode/probe stages use adaptor-owned launchers
that hash the actual encoded input immediately before entering the native tool.
Offline verification regenerates those launchers and checks input bindings and
output digests, so refreshing ordinary artifact/publication metadata cannot pair a
changed video with stale RGB/probe readback. Exact historical direct command
receipts remain readable and report `nativeReadbackBound: false`; they lack this
additional stage association. Verification needs no native tool or original inputs.
Receipts are integrity evidence, not signed attestations against coordinated forgery.
Source capture and scheduler fingerprints reject devices/FIFOs before opening,
recheck the opened descriptor, and enforce both per-file and total byte budgets.
NUL paths are rejected during host planning.

```bash
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/sprite-to-video.json \
  --aseprite /absolute/aseprite --ffmpeg /absolute/ffmpeg \
  --output-directory /fresh/sprite-video

PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/blender-to-video.json \
  --blender /absolute/blender --ffmpeg /absolute/ffmpeg \
  --output-directory /fresh/blender-video

PYTHONPATH=src python3 -m schemaxis verify /fresh/blender-video
```

The Blender example prepares once, renders two camera groups and assembles a
24-frame, two-second MP4. `--resume` uses unchanged authored workflow input and
verified source hashes. Altered/missing artifacts cannot be reused as successes.

API references: [FFmpeg](https://ffmpeg.org/ffmpeg.html),
[FFprobe](https://ffmpeg.org/ffprobe.html),
[Godot Sprite3D](https://docs.godotengine.org/en/stable/classes/class_sprite3d.html).

Adaptor-level offline verification uses retained inputs. Whole-workflow verification
and resume additionally require the original external input paths and hashes to
remain available and unchanged.
