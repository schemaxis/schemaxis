# PrusaSlicer FFF slicing

`schemaxis.prusaslicer/1` slices one closed STL part into fused-filament (FFF/FDM)
G-code with an explicit printer, filament and print profile. `sliceModel`
publishes the G-code, a per-layer table, a summary with PrusaSlicer's native
print-time and filament estimates, and the exact configuration it used. An
independent pure-Python replay of the G-code decides whether the result is
accepted; a successful native exit alone is not.

**This adaptor never controls a printer.** It does not upload, stream or send
G-code to any machine, and it does not certify print quality, adhesion,
strength, dimensional accuracy or thermal safety. See
[assumptions and limits](#assumptions-and-limits).

```sh
PYTHONPATH=src python3 -m schemaxis plan examples/schemaxis/prusaslicer-pla.json
# Replace model.file with an absolute STL path first.
PYTHONPATH=src python3 -m schemaxis run my-slice.json \
  --prusaslicer /absolute/path/to/prusa-slicer --output-directory evidence/my-slice
PYTHONPATH=src python3 tools/qualify_prusaslicer.py --native \
  --executable /absolute/path/to/prusa-slicer --output-directory evidence/my-prusaslicer-qualification
```

## Target runtime

The target is the latest stable upstream release, **PrusaSlicer 2.9.6**
([release notes](https://github.com/prusa3d/PrusaSlicer/releases/tag/version_2.9.6)).
The 3.0.0 alphas are prereleases and are not targeted. The adaptor uses only the
public [command-line interface](https://github.com/prusa3d/PrusaSlicer/wiki/Command-Line-Interface):
`--help` for runtime identity, `--info` for native model readback, and
`--load`, `--scale`, `--center`, `--threads`, `--datadir` and `--export-gcode`
for slicing. Option names and meanings follow the 2.9.6
[configuration definitions](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.6/src/libslic3r/PrintConfig.cpp).

Configure an absolute path to a PrusaSlicer 2.9.6 executable that accepts these
console options, using `schemaxis configure`, `--prusaslicer` or the
`PRUSASLICER_EXECUTABLE` environment variable. On Linux, the official
distribution channel is [Flathub](https://flathub.org/apps/com.prusa3d.PrusaSlicer);
a flatpak launcher is not a plain executable, so point Schemaxis at a console
binary. The first line of `--help` must identify version 2.9.6. Discovery and
planning never import or launch PrusaSlicer.

Each native stage runs in its own process with exactly one slicing thread, a
private `--datadir` and a private home directory inside the attempt. No user,
vendor or system presets are read, and nothing is uploaded.

## Document and units

All lengths are **millimetres**, speeds **mm/s**, accelerations **mm/s²**,
temperatures **degrees Celsius**, density **g/cm³**, filament mass **grams** and
time **seconds**. STL files carry no unit, so `model.units` is required.

| Field | Meaning and bounds | Native key(s) |
| --- | --- | --- |
| `model.file` | Absolute path to one binary or ASCII STL, ≤ 16 MiB and ≤ 100000 triangles | input file |
| `model.units` | `millimetre`, or `inch` (scaled by 25.4) | `--scale` |
| `model.sha256` | Optional pin of the exact STL bytes | — |
| `printer.bedSize_mm` | [width, depth], 50–1000 mm, origin front-left | `bed_shape` |
| `printer.maxPrintHeight_mm` | 10–1000 mm | `max_print_height` |
| `printer.nozzleDiameter_mm` | 0.15–1.2 mm | `nozzle_diameter` |
| `printer.gcodeFlavour` | `marlin2` only | `gcode_flavor` |
| `printer.maxFeedrate_mm_s` | X/Y limit for the time estimate, 20–1000 | `machine_max_feedrate_x/y` |
| `printer.maxAcceleration_mm_s2` | One acceleration for the time estimate, 100–30000 | `machine_max_acceleration_*` |
| `material.type` | Label: PLA, PETG, ABS or ASA | `filament_type` |
| `material.filamentDiameter_mm` | 1.0–3.5 mm | `filament_diameter` |
| `material.density_g_cm3` | 0.5–3.0 | `filament_density` |
| `material.firstLayerNozzleTemperature_C`, `nozzleTemperature_C` | 150–320 °C | `first_layer_temperature`, `temperature` |
| `material.firstLayerBedTemperature_C`, `bedTemperature_C` | 0–130 °C | `first_layer_bed_temperature`, `bed_temperature` |
| `material.fanSpeed_percent` | 0–100 from layer 2; first layer fan off | `min/max/bridge_fan_speed` |
| `print.firstLayerHeight_mm`, `layerHeight_mm` | 0.04–1.0 mm and ≤ 0.8 × nozzle | `first_layer_height`, `layer_height` |
| `print.extrusionWidth_mm` | 1–2 × nozzle and > every layer height; all features | `*extrusion_width` |
| `print.perimeters`, `topSolidLayers`, `bottomSolidLayers` | 1–10, 0–30, 0–30 | same names |
| `print.infillDensity_percent`, `infillPattern` | 0–100 %; rectilinear, grid or gyroid; 100 % needs rectilinear | `fill_density`, `fill_pattern` |
| `print.perimeterSpeed_mm_s`, `infillSpeed_mm_s` | 5–500 mm/s | perimeter and infill speed families |
| `print.firstLayerSpeed_mm_s`, `travelSpeed_mm_s` | 5–200 and 10–1000 mm/s | `first_layer_speed`, `travel_speed` |
| `placement.centre_mm` | Optional bed point for the bounding-box centre; default bed centre | `--center` |
| `requirements[]` | Optional named maxima on `printTime_s`, `filamentMass_g` or `filamentLength_mm` | — |

The planner rejects invalid combinations before any file is read or process is
launched: `INVALID_PROFILE` for layer heights above 0.8 × nozzle, widths outside
1–2 nozzle diameters or not above the layer heights, and 100 % non-rectilinear
infill; `INVALID_RESOURCE` for relative or non-STL paths; `MODEL_OUT_OF_BOUNDS`
for a centre outside the bed; and `INVALID_REQUIREMENT` for duplicate names.

## Model checks before slicing

Before launching PrusaSlicer, the run reads the STL with an independent bounded
parser. It requires one closed, consistently oriented, non-degenerate triangle
mesh: every directed edge appears once and has an oppositely directed partner,
all triangles form one connected shell, and the signed volume is positive. Triangle winding is authoritative; stored
facet normals are ignored. Edge pairing does not detect self-intersections. ASCII
files must contain exactly one `solid`, with nothing after `endsolid` except its
name. Volume uses a mesh-local reference vertex so translation does not change it.

The scaled bounding box must fit the bed around the placement centre and the
declared height, and each footprint side must be at least two extrusion widths.
Failures are `INVALID_MODEL`, `MODEL_OUT_OF_BOUNDS` or `INPUT_DIGEST_MISMATCH`,
and no attempt directory is created. The model is always dropped onto the bed;
it is never rotated, arranged or repaired.

## Fixed generation policy

Schemaxis renders `config.ini` from the declared values plus a fixed policy;
see `src/schemaxis/adaptors/prusaslicer/profile.py`. Authored text never becomes
G-code, configuration keys, preset names or scripts. The policy includes:

- start G-code `G21, G90, M83, G28, G92 E0` and end G-code `M104 S0, M140 S0, M107, M84`;
  PrusaSlicer inserts the declared temperature waits before the start G-code;
- relative extrusion, 0.8 mm retraction at 35 mm/s, no Z-hop, wipe or firmware retraction;
- classic perimeters, one extruder, no supports, brim, skirt, raft, ironing,
  wipe tower, spiral vase, arc fitting, binary G-code, object labels or thumbnails;
- empty custom, layer and post-processing G-code;
- `machine_limits_usage = time_estimate_only`: machine limits affect only the
  native time estimate and are not emitted. Z and E limits are fixed at 12 and
  120 mm/s;
- cooling on, with slowdown below 5 s layer time down to 10 mm/s; this can only
  lower speeds.

## Independent checks

Verification does not trust native success flags. After slicing, and again on
every `schemaxis verify`, the adaptor recomputes everything from retained bytes:

1. **Runtime identity**: `--help` must report PrusaSlicer 2.9.6 and the G-code
   header must name the same runtime.
2. **Native model readback**: `--info` on the retained STL must match the
   independent facet count, extents and minimum corner (1e-5 times the largest
   extent), and volume (relative 1e-4). Each numeric allowance additionally
   includes 0.5e-6 in raw STL length or cubic units for PrusaSlicer 2.9.6's
   fixed six-decimal text rounding, before the authored unit conversion.
   Values must be finite; the reader must report a manifold single part and no repairs.
3. **Configuration readback**: every rendered key must appear with the same
   value in the configuration block that PrusaSlicer embeds in the G-code.
4. **G-code replay** (`gcode.py`): only the commands the fixed policy can emit are
   accepted. Arcs, inch units, tool changes, extrusion while changing Z, a second
   homing or homing after motion are rejected. Homing is modelled at the bed origin.
5. **Build volume**: every move stays inside the bed and below the maximum height.
6. **Layers**: the first extrusion is on the first layer, every extrusion layer
   lies on the grid first-layer height + k × layer height, and none lies above the
   model top. Native `;Z:` annotations must
   equal the replayed layers. The gap below the model top and any empty grid
   layers are reported. Slivers or tips narrower than one line can leave a layer
   empty, so exact counts are asserted only by the flat-topped acceptance cases.
   PrusaSlicer 2.9.6 stops at the last full layer at or below the model top, so a
   10 mm box with 0.2 + k × 0.15 mm layers ends at 9.95 mm.
7. **Envelope**: on every layer, extrusion centrelines stay inside the model
   footprint inset by half the extrusion width. The deviation of the union
   envelope from that inset is reported for prismatic parts.
8. **Setpoints**: `M109`/`M190` waits for the first-layer temperatures precede the
   first extrusion. Every first-layer extrusion runs at the first-layer nozzle and
   bed setpoints with the fan off, and every later extrusion at the later setpoints
   and the declared fan duty. No undeclared temperature is ever commanded.
9. **Feedrates**: first-layer extrusion never exceeds the first-layer speed;
   later extrusion never exceeds the larger of the perimeter and infill speeds;
   travel never exceeds the travel speed.
10. **Filament arithmetic**: the replayed extruded length must match the native
    `filament used [mm]`; volume (from the declared diameter) and mass (from the
    declared density) must match the native cm³ and gram figures.
11. **Time bounds**: the native normal-mode estimate must lie between a
    constant-speed lower bound and a rest-to-rest trapezoidal upper bound, both
    computed from the replayed moves and the declared feedrate and acceleration
    limits.
12. **Plausibility**: deposited filament volume is positive and at most 1.2 × the
    model volume.
13. **Fresh reload**: a separate native process loads only the configuration
    embedded in the published G-code and re-slices the retained STL. Its G-code
    must be identical apart from the `; generated by` timestamp line.

Tolerances: coordinates 0.011 mm, because G-code prints three decimals. Feedrates
0.01 mm/s, printed in mm/min. Filament length 0.006 mm plus 5×10⁻⁶ mm per
extrusion move, for five-decimal E values and two-decimal statistics, plus 10⁻⁴
relative. Native times print whole seconds, so the bounds allow ±1 s. Fan duty
allows half a step of the 0–255 scale.

## Publications and evidence

| File | Kind | Content |
| --- | --- | --- |
| `model.gcode` | text | ASCII Marlin 2 G-code with embedded native configuration and estimates |
| `layers.csv` | table | Per layer: index, z, moves, path and filament length, XY envelope, peak feedrate, nozzle/bed/fan setpoints |
| `slice-summary.json` | text | Native estimates, replay results, requirement margins and losses |
| `config.ini` | text | The exact configuration passed to PrusaSlicer |

`verification.json` binds the publication digests, the retained STL copy, every
stage's command, submission, stdout and stderr, and the reloaded G-code.
Tampering with any of them makes verification fail. Publications can be passed to
workflows. For example, `layers.csv` is a numeric table; its units are in its
column names.

## Faults and recovery

| Code | Meaning | Recovery |
| --- | --- | --- |
| `INVALID_PROFILE` | Inconsistent printer/print settings | Edit the located setting within the documented bounds |
| `INVALID_RESOURCE` | Path is relative, not `.stl`, missing, a symlink or > 16 MiB | Give an absolute path to a regular STL file |
| `INVALID_MODEL` | Open, inverted, degenerate, multi-solid or too-narrow mesh | Export one closed, consistently oriented solid; no repair is attempted |
| `INPUT_DIGEST_MISMATCH` | STL bytes differ from `model.sha256` | Restore the file or deliberately update the digest |
| `MODEL_OUT_OF_BOUNDS` | Footprint or height does not fit | Move the centre, scale the model, or declare the real bed |
| `UNSUPPORTED_RUNTIME` | The executable's `--help` does not report PrusaSlicer 2.9.6 (checked first; no `--info` or slice is launched) | Configure a 2.9.6 console executable |
| `RUNNER_FAILED`, `NATIVE_EXECUTION_FAILED` | PrusaSlicer refused or produced no G-code, for example an object with no first-layer extrusion (a point or edge resting on the bed) | Read the retained stage stderr; reorient or flatten the base before exporting the STL |
| `VERIFICATION_FAILED` | Native readback or replay disagrees. A native `--info` that disagrees with the independent STL analysis (`stage: info`) stops the attempt before slicing | Inspect the retained logs; rerun in a fresh directory |
| `PERFORMANCE_NOT_MET` | A native estimate exceeds a named limit | Change the profile or revise the limit; rerun |

Native stages are gated in order: the runtime identity is checked as soon as
`--help` returns, and the native `--info` readback is compared with the host STL
analysis before the slice starts. A refused attempt keeps its `result.json` fault
and the stage logs that ran, and publishes no G-code. These checks are repeated
when `verify` replays retained attempts, so they only move earlier.

## Assumptions and limits

- The G-code targets a generic Marlin 2 FFF machine described only by the
  declared values. It has not been executed on, sent to or validated for any
  physical printer, firmware or material.
- Temperatures, speeds and fan values are authored setpoints. Schemaxis checks
  that they are applied as declared, not that they suit the material, machine or
  environment.
- Print time and filament figures are PrusaSlicer model estimates for that
  generic machine. They are checked only against kinematic bounds and filament
  arithmetic, not measured on hardware.
- One STL object and one extruder only. There are no supports, modifiers,
  multi-material or variable layer height. 3MF/STEP input, mesh repair, printer
  presets, network upload and physical printer control are separate capabilities
  and are not implemented.

## Acceptance cases

A verified `geometry` artifact can supply `model.file` through a workflow
`$artifact` reference. It must still satisfy the STL and physical-size checks,
and `model.units` remains required. The
[OpenSCAD-to-PrusaSlicer example](../examples/schemaxis/openscad-to-prusaslicer.json)
constructs a two-hole plate and slices its retained STL with explicit
`millimetre` units. The native OpenSCAD 2021.01 / PrusaSlicer 2.9.6 handoff,
workflow verification and unchanged reuse of both operations passed. It produces
reviewable files and does not connect to a printer.

The development cases slice original analytic fixtures. Their literal
expectations are derived from geometry, not copied from native output:

- `examples/schemaxis/prusaslicer-box.stl`: a 24 × 16 × 10 mm box (3840 mm³).
  With the PLA profile (0.2 mm layers, 0.45 mm width, centre 125, 105) it gives
  50 layers from 0.2 to 10.0 mm. The perimeter envelope is x 113.225–136.775 and
  y 97.225–112.775. With the PETG profile (0.4 mm first layer, then 0.3 mm
  layers, 0.68 mm width, centre 150, 150) it gives 1 + 9.6/0.3 = 33 layers. Its
  100 % rectilinear infill should deposit about the solid volume (ratio 1 ± 10 %).
- `examples/schemaxis/prusaslicer-box-inch.stl`: a 1.0 × 0.6 × 0.4 inch box
  declared in inches, sliced as 25.4 × 15.24 × 10.16 mm (3932.89536 mm³) with
  0.254 mm layers: 40 layers to 10.16 mm.

Run `tools/qualify_prusaslicer.py` for host conformance; add `--native` and an
executable for bounded native acceptance. See the
[completion review](../verification/2026-10-16-prusaslicer-completion.md) for
the latest results and remaining gaps.
