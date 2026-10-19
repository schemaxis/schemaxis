# KiCad boards

The `schemaxis.kicad/1` route checks an existing, saved KiCad printed circuit board
with the public `kicad-cli` automation interface. It has three operations:

| Operation | Native command | Publications |
| --- | --- | --- |
| `inspectBoard` | `kicad-cli pcb export stats` | `board-summary.json`, `board-statistics.json` |
| `designRuleCheck` | `kicad-cli pcb drc` | the above plus `drc-report.json` |
| `drillExport` | `kicad-cli pcb drc`, then `kicad-cli pcb export drill` | the above plus Excellon drill files in `drill/` |

Board authoring is outside this first slice. The adaptor never saves, upgrades or
refills a board. It targets KiCad 10.0 (latest stable 10.0.7, released 2026-10-07);
see [Runtime](#runtime).

## Documents and fields

```json
{"version": "schemaxis.kicad/1", "operation": "drillExport",
 "board": "/path/to/boards/sensor.kicad_pcb",
 "maximumErrors": 0, "maximumWarnings": 0, "maximumUnconnected": 0,
 "units": "mm", "separatePlating": true}
```

- `board` is an absolute path to a saved `.kicad_pcb`. A sibling `.kicad_pro`
  (netclasses, rule severities) and `.kicad_dru` (custom rules) with the same name are
  captured with it. Without a project, KiCad's default rules apply (0.2 mm clearance).
- `maximumErrors`, `maximumWarnings` and `maximumUnconnected` (DRC operations,
  default 0) are the largest acceptable counts in the native report.
- `units` (`mm` or `in`, default `mm`) and `separatePlating` (default `true`) select
  the drill file units and whether plated and non-plated holes are written separately.

Every run copies the board and project files into `board/` inside a fresh run
directory. KiCad sees only those copies, under an isolated home directory, so global
footprint/symbol library tables and user settings are never used. The copies are
re-hashed after every native stage; any change fails with `NATIVE_MUTATED_INPUT`.

Supported boards are KiCad 8.0–10.0 board formats (file versions 20240108–20260206)
with exactly two copper layers. Newer or older formats, inner layers, blind/buried or
micro vias, oval or offset drills, backdrills and footprint-owned `Edge.Cuts` outlines
fail with `UNSUPPORTED_BOARD` before KiCad runs. Boards are limited to 4 MiB,
2000 tracks/arcs/vias and 2000 holes.

## Inspect a board

A dependency-free host reader parses the board file and counts footprints by type and
side, pads by type, through vias, nets, holes grouped by size, plating and source, the
`Edge.Cuts` outline bounds, minimum track width, minimum drill and the minimum
track-to-track clearance. KiCad's board statistics report must agree with every one of
these facts; any disagreement fails with `VERIFICATION_FAILED`.

The clearance figure follows KiCad's statistic: edge-to-edge gaps between
different-net tracks and vias, each compared on its own primary layer. It is a summary
number, not a rule check. Boards with arcs or via padstacks leave it unchecked and
say so in `trackClearanceStatus`. Mounting holes and other footprints without
`through_hole` or `smd` attributes are counted as unspecified components, as in KiCad.

## Design rule check

`designRuleCheck` runs `kicad-cli pcb drc --severity-all --format json --units mm`.
The board's own project rules and severities apply. `board-summary.json` records
the native findings by type and severity, the ignored checks, and an assessment:

```json
{"accepted": false, "observed": {"errors": 2, "warnings": 0, "unconnected": 0},
 "maximum": {"errors": 0, "warnings": 0, "unconnected": 0}, "exceeded": ["errors"]}
```

The acceptance decision only uses native counts. If a count exceeds its maximum, the
run fails with `DRC_VIOLATIONS`; `drc-report.json` and the summary are kept for
review, and nothing is published or reused. Raise a maximum only with a recorded
reason: it accepts findings rather than fixing them. Excluded findings are reported
separately and never counted.

Where its model applies, the host also predicts two classes of finding independently
and requires the native report to agree:

- **Clearance**: gaps below the Default netclass clearance between different-net
  straight tracks and through vias on every layer they span, including the actual gap
  KiCad reports. This needs one netclass, no `.kicad_dru` custom rules and clearance
  severity `error`.
- **Unconnected items**: pads of each net are joined through track endpoints, via
  centres and pad anchors; missing joins must equal KiCad's unconnected items. Zones,
  arcs, custom or chamfered pads, floating copper and same-net copper that overlaps
  without an endpoint contact leave this check unchecked.

Each prediction reports `confirmed` or `unchecked` with its reason. All other findings
(for example annular width, silkscreen or courtyard checks) are native-only.

Zones are checked as saved; the run never refills them. Schematic parity is not
checked. Without global libraries, KiCad reports `lib_footprint_issues` for library
footprints unless the project sets those checks to `ignore`.

## Drill export

`drillExport` first runs the design rule check above and only exports if it passes.
It then writes Excellon drill files with absolute origin and decimal coordinates:
`drill/board-PTH.drl` and `drill/board-NPTH.drl`, or one `drill/board.drl` when
`separatePlating` is false. KiCad writes the NPTH file even when it is empty.

The host reads every file independently: header units, file plating role, each tool's
plated/non-plated attribute and diameter, and every hit. Each board hole must match
exactly one hit with the same plating, a diameter and position within half a written
digit (0.0005 mm in millimetres, 0.00005 in in inches). Excellon uses a y-up frame,
so a hole at KiCad board position (8, 10) mm is written `X8.0Y-10.0`.

Only round holes spanning F.Cu to B.Cu are supported. Drilled pads on back-side
footprints are rejected for drill export. No drill map, drill report, Gerber layer
plots or job file are produced; generate layer plots in KiCad.

## Verification

`schemaxis verify RUN` recomputes every published conclusion from retained files:
the effective plan, captured input digests, runtime identity, the host board reader,
the statistics cross-check, the DRC report structure (schema
`https://schemas.kicad.org/drc.v1.json`, the observed KiCad version, requested
severities, console totals), host predictions, the authored assessment and every drill
hit. Changing a publication or retained input fails verification.

## Fixtures

`examples/schemaxis/fixtures/kicad/` holds four original boards written for this
adaptor and saved in the KiCad 10.0 format; their projects declare a 0.2 mm Default
clearance and ignore library checks because the footprints are inline.

| Fixture | Content | Expected result |
| --- | --- | --- |
| `tiny-board` | 30 x 20 mm; J1 two 1.0 mm PTH pads (rotated 90°), R1 two SMD pads, H1/H2 3.2 mm NPTH, two 0.3 mm vias | Clean DRC; 6 holes (4 plated); minimum clearance 1.65 mm |
| `tiny-variant` | 40 x 25 mm; J1 three PTH pads (rotated 270°), R1/R2 SMD, H1/H2 3.2 mm and H3 2.2 mm NPTH, three 0.4 mm vias | Clean DRC; 9 holes (6 plated); minimum clearance 1.55 mm |
| `tiny-clearance` | Baseline plus an AUX net routed 0.1 mm from a GND track | `DRC_VIOLATIONS`: 2 clearance errors, gaps 0.1 mm |
| `tiny-open` | Baseline without one GND track | `DRC_VIOLATIONS`: 1 unconnected item, 2 dangling-track warnings |

Expected values follow from the declared geometry. For example, the closest
different-net copper in `tiny-board` is the end of the SIG track at (19.05, 10) mm and
the GND track at (20.95, 10) mm: 1.9 mm minus two 0.125 mm half-widths is 1.65 mm.
The [examples](../examples/schemaxis/kicad-drc.json) use a placeholder board path;
conformance and `tools/qualify_kicad.py` substitute the fixture path.

## Runtime

Configure an absolute `kicad-cli` from KiCad 10.0 with `schemaxis configure` or pass
`--kicad`; `KICAD_CLI` is also read. Other versions fail with `UNSUPPORTED_RUNTIME`.
The adaptor's [`readiness.json`](../src/schemaxis/adaptors/kicad/readiness.json) and
[`upstream.json`](../src/schemaxis/adaptors/kicad/upstream.json) record the acceptance
cases and the absorbed release; a native receipt applies only to its named cases and
observed runtime. See the official
[kicad-cli documentation](https://docs.kicad.org/10.0/en/cli/cli.html) and
[board file format](https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/).

```sh
PYTHONPATH=src python3 tools/qualify_kicad.py --kicad /absolute/path/to/kicad-cli \
  --output-directory evidence/kicad-qualification
```

## Faults and recovery

| Fault | Meaning and recovery |
| --- | --- |
| `INVALID_RESOURCE` | `board` is not an absolute `.kicad_pcb` path. |
| `RESOURCE_NOT_FOUND` / `RESOURCE_LIMIT` | The board is missing, or exceeds a size or item limit. |
| `UNSUPPORTED_BOARD` | The board uses a structure outside this slice; the fault names it. |
| `INVALID_PROJECT` | The sibling `.kicad_pro` is not a JSON object. |
| `DRC_VIOLATIONS` | Native findings exceed the maximums; fix the board and run again. |
| `VERIFICATION_FAILED` | A native report disagreed with the host reader, or evidence changed. Keep the run and report it. |
| `NATIVE_MUTATED_INPUT` | KiCad changed a captured copy; the run is not trusted. |
| `INTERPRETER_NOT_FOUND` / `UNSUPPORTED_RUNTIME` | Configure a KiCad 10.0 `kicad-cli`. |
