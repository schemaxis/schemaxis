# PrusaSlicer adaptor completion review (2026-10-16)

**Architect closeout:** shared reference/Help generation, catalogue and workflow
guidance integration, admission checks, the full host suite and final native
qualification are complete. A fresh receipt is registered against the final
source. See the [integration verification](2026-10-16-architecture-integration.md).
The implementation-agent handoff below records its earlier state; its pending
central-integration items are now resolved. Application scope limits remain.

Scope: new provider `prusaslicer`, route `schemaxis.prusaslicer/1`, operation
`sliceModel`. It slices one closed STL with an explicit generic Marlin 2 FFF
printer, filament and print profile, and publishes G-code, a per-layer table, a
summary with native estimates, and the exact generated configuration. Physical
printer control, upload and any physical print, firmware, material or safety
claim are excluded. See the [guide](../docs/prusaslicer.md).

## Runtime and sources

- Latest stable upstream: **PrusaSlicer 2.9.6** (GitHub release
  `version_2.9.6`, published 2026-06-25). The 3.0.0 alphas are prereleases.
  The release source is the GitHub latest-release endpoint, read with a pattern
  for the `version_` tag prefix; an offline parse of the fetched payload returned `2.9.6`.
- Since 2.8.1, Linux binaries are distributed only through Flathub, and no
  flatpak was available on the qualification workstation. The native runtime used
  here was therefore built locally from the unmodified `version_2.9.6` source
  archive, CLI-only (`SLIC3R_GUI=OFF`, STEP import off, static dependency bundle).
  Build-only shims supplied missing host tools: a no-op `autoreconf`/`makeinfo`,
  an empty DBus package config (DBus is linked only by the GUI), and the bundle's
  own pinned libpng 1.6.35. The binary reports
  `PrusaSlicer-2.9.6+UNKNOWN based on Slic3r (without GUI support)`. The official
  Flathub or Windows/macOS binaries were **not** exercised.
- Public interfaces used: the documented command-line options `--help`,
  `--info`, `--load`, `--scale`, `--center`, `--threads`, `--datadir`,
  `--loglevel` and `--export-gcode`; configuration keys from the 2.9.6
  `PrintConfig.cpp`; and the G-code comment formats written by `GCode.cpp` and
  `GCodeProcessor.cpp`. No PrusaSlicer source is copied into the repository.

Native observations retained in the adaptor:

- With relative extrusion, 2.9.6 refuses to slice unless `layer_gcode` contains
  `G92 E0`. It reports this on stderr and **still exits 0**, so a missing G-code
  publication is a separate `NATIVE_EXECUTION_FAILED` fault.
- A per-extruder list such as `start_filament_gcode` loaded as an empty list is
  read past its end by the template processor ("Invalid utf8 sequence"). The
  policy writes one explicit empty element (`""`).
- The `--help` identity carries a build suffix (`+UNKNOWN` here). The G-code
  header carries only `2.9.6`, so the adaptor compares version numbers.
- With a constant layer height, slicing stops at the last full layer at or below
  the model top. A 10 mm box with 0.2 + k × 0.15 mm layers ends at 9.95 mm.

## Checklist results

| ID | Result | Evidence and rationale |
| --- | --- | --- |
| registration | Done | `adaptor.json`: `runtimeFamily` 2.9, process mode, `mpi` false, workflow/scheduled/compose routes, hooks `query`, `reusableInputs` (STL path → SHA-256), `resources` (exactly one thread), `--prusaslicer` CLI option, no accepted artifacts. The registry discovers the manifest without framework changes. |
| schema | Done | Typed declarations for model/printer/material/print/placement/requirements with bounds and enums; portable ECMAScript-compatible path pattern; host conformance checks schema/planner agreement on 7 examples, undeclared root fields and typed defaults. |
| semantics | Done | Located faults before native launch: `INVALID_PROFILE` (layer ≤ 0.8 × nozzle, width 1–2 × nozzle and above layer heights, 100 % only rectilinear), `INVALID_RESOURCE`, `MODEL_OUT_OF_BOUNDS`, `INVALID_REQUIREMENT`. At run time, before any attempt directory is created: STL closed/oriented/single shell/non-degenerate/positive volume (`INVALID_MODEL`), digest pin (`INPUT_DIGEST_MISMATCH`) and footprint/height fit. Volume uses a mesh-local reference vertex. |
| native-mapping | Done (bounded) | Every rendered key is read back from the configuration block embedded in the G-code. Native `--info` is compared with the independent STL analysis. Units map to `--scale`, placement to `--center`. Unsupported settings (supports, brims, custom G-code, presets, other flavours) are not exposed. |
| execution | Done | Four isolated stages (version, info, slice, fresh reload) under one deadline. Each has a trusted driver that binds input digests before `exec`, plus a private datadir and home. Every stage's command, submission, stdout and stderr is retained. `verify` replays everything from retained bytes; tampering, missing files and forged semantics are rejected. |
| discovery | Done | Application and operation purposes and keywords in `capabilities.py`. Six reviewed search cases cover all four kinds (synonym `gcode`/`FDM`, multiword `print time estimate`/`layer height`, ambiguous `slice`, negative `laser engraving`) on all four surfaces. Capability matching passes in `check_cases`. |
| guidance | Done | `guidance.json`: the operation and all 45 field addresses `reviewed`, with units, defaults, native keys and pitfalls; `tools/studio_guidance.py --app prusaslicer --check` reports 46 reviewed, 0 pending, 0 stale. Domain review of material temperature ranges is intentionally not claimed: the values are setpoints, not suitability advice. |
| help | Pending central generation | Local guide `docs/prusaslicer.md` with faults, recovery and public API links. In a disposable checkout copy, `schemaxis reference` generated `docs/generated/prusaslicer-operations.md` and `tools/generate_studio_help.py` succeeded after this note existed. Shared generated files are **not** written by this agent; readiness `studio.help` fails in the live checkout until the architect regenerates. |
| examples | Done | `examples/schemaxis/prusaslicer-{pla,petg,inch}.json` (absolute placeholder path, as for FFmpeg), original analytic fixtures `prusaslicer-box.stl` (24 × 16 × 10 mm) and `prusaslicer-box-inch.stl` (1.0 × 0.6 × 0.4 in), four invalid readiness examples, and three Studio templates plus nine snippets, all host-planned with filled values. |
| tests | Done (focused) | `tests/unit/test_prusaslicer.py`: 16 tests (15 host + 1 native-gated) covering planning, faults, schema, hooks, STL defects (open, inverted, duplicate, degenerate, multi-shell, trailing solid, far translation), pre-launch faults without attempt creation, G-code replay semantics and policy violations, analytic kinematic bounds, metadata and search cases. The full shared suite is run by the parent. |
| qualification | Preliminary pass; not recorded | Host conformance passed. Native conformance passed all three cases with timeout and pre-launch-cancellation lifecycle probes and integrity tamper checks. `tools/qualify_prusaslicer.py` adaptor probes passed (below). The receipt is **not** registered: shared Help regeneration will change the source digest, so the parent must rerun and record afterwards. |
| maintenance | Done | `upstream.json`: latest-stable policy, release pattern source, scope, evidence and acceptance recipe. `absorbedVersion` was set to 2.9.6 only after the final host checks and bounded native acceptance in this session passed. Its scope names the CLI-only source build and leaves the official binaries unverified. |

`completion.notApplicable`: `mpi`, because the route pins one native thread.

## Native acceptance results (preliminary, this session)

Cases (independent literal expectations from fixture geometry):

| Case | Layers | First / top z (mm) | Envelope deviation | Temperatures (°C) | Other |
| --- | --- | --- | --- | --- | --- |
| `pla-box` | 50 | 0.2 / 10.0 | 0.000 mm | 215/210 nozzle, 65/60 bed | fan 100 % |
| `petg-solid-box` | 33 | 0.4 / 10.0 | 0.000 mm | 240/245 nozzle, 85/90 bed | fan 40 %; deposited/model volume 1.017 (expected 1 ± 10 %) |
| `inch-box` | 40 | 0.254 / 10.16 | < 1e-13 mm | 215/210, 65/60 | 0.24 in³ native info, 3932.895 mm³ scaled |

Observed native estimates lay inside the independent kinematic brackets, for
example `pla-box`: 542 s native in [466, 579] s. Replayed filament matched
native to within rounding: 729.383 mm replay versus 729.38 mm native.
Every fresh reload produced identical G-code apart from the timestamp line.

Adaptor-specific probes (`tools/qualify_prusaslicer.py`):

- A 1 s print-time limit on a verified PETG slice gives `PERFORMANCE_NOT_MET`
  with margin −655 s; the attempt is not reusable (`INCOMPLETE_EXECUTION`).
- Forged later-layer nozzle setpoint, forged layer Z and forged native time
  estimate, each with recomputed publication digests: `verify` rejects them. The
  independent replay alone also rejects them for the named reasons: temperature
  setpoint, off-grid layer and time outside the kinematic bounds.
- A footprint off the bed gives `MODEL_OUT_OF_BOUNDS` before launch, with no
  attempt directory created.

Exploratory checks, not development cases: a non-whole-layer box and a pyramid
lifted 5 mm above z = 0 both verified. The pyramid was dropped to the bed;
containment held and its envelope deviation of 0.067 mm is reported, not asserted.
An octahedron resting on its vertex was refused by PrusaSlicer itself ("no
extrusions in the first layer", exit 1), and the failure was retained as
`RUNNER_FAILED` with stderr. The verifier therefore requires first-layer extrusion.

## Commands

```sh
PYTHONPATH=src python3 -m unittest tests.unit.test_prusaslicer -q
PYTHONPATH=src python3 tools/studio_guidance.py --app prusaslicer --check
PYTHONPATH=src python3 -m schemaxis readiness --app prusaslicer --admission --check
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.prusaslicer/1 --output-directory NEW_DIR
PYTHONPATH=src python3 tools/qualify_prusaslicer.py --native --executable ABSOLUTE_PRUSASLICER --output-directory NEW_DIR
PYTHONPATH=src python3 -m schemaxis adaptor record NEW_DIR/conformance/qualification.json
```

Final runs in this session, after the last source edit: 16 unit tests passed,
including the native-gated one. Guidance check: 46 reviewed. Host conformance
passed. `tools/qualify_prusaslicer.py --native` passed all three cases, both
lifecycle probes and all six adaptor probes. Native `adaptor conform --native`
through a private `SCHEMAXIS_CONFIG` passed again. Live readiness admission fails
only `studio.help`. In a disposable checkout copy after `schemaxis reference` and
`tools/generate_studio_help.py`, admission passed and all seven PrusaSlicer Studio
search/Help regressions passed.

## Remaining gaps

- Packaged Help and the generated operation reference need central regeneration;
  the Studio search regression's Help surface fails until then. Capability, adaptor
  and Add surfaces passed in this session.
- The native receipt must be rerun and recorded after shared generation; no
  receipt in this package is claimed as source-current.
- Only a locally built CLI-only 2.9.6 binary was qualified. Official Flathub,
  Windows and macOS builds, GUI builds' console mode and other releases are
  unverified.
- Scope is deliberately small: one STL object, generic Marlin 2 G-code, one
  extruder, classic perimeters and no supports. 3MF/STEP input, mesh repair,
  vendor presets, other firmware flavours and FreeCAD/Blender → PrusaSlicer
  handoffs (`acceptedArtifacts`) remain candidates.
- No physical print, printer, firmware or material qualification of any kind.
- Shared workflow guidance is keyed by embedded-document `oneOf` index. Adding
  built-in routes alphabetically shifts later indices: `schemaxis.prusaslicer/1`
  is now `oneOf/17`, whose existing record still describes Shotcut. The workflow
  guidance file is shared and was not edited here.
