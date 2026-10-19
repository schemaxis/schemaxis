# KiCad adaptor completion review (2026-10-16)

**Architect closeout:** shared reference/Help generation, catalogue and workflow
guidance integration, admission checks, the full host suite and final native
qualification are complete. A fresh receipt is registered against the final
source. See the [integration verification](2026-10-16-architecture-integration.md).
The implementation-agent handoff below records its earlier state; its pending
central-integration items are now resolved. Application scope limits remain.

Scope: new adaptor `kicad`, route `schemaxis.kicad/1` (document model) with
`inspectBoard`, `designRuleCheck` and `drillExport`. Board authoring is out of scope.
Bulk transcripts stay in local `evidence/`; this note records the checks and results.

## Upstream target

- Latest stable KiCad is **10.0.7**, released 2026-10-07
  ([release notes](https://www.kicad.org/blog/2026/10/KiCad-10.0.7-Release/),
  [release-notes index](https://www.kicad.org/blog/categories/Release-Notes/)). 10.0.7
  RC1/RC2 preceded it; release candidates are excluded by the `upstream.json` pattern.
- Native runtime: the official KiCad 10.0 Ubuntu 24.04 package
  (`kicad_10.0.7~ubuntu24.04.1_amd64.deb` from the KiCad
  [Launchpad archive](https://launchpad.net/~kicad/+archive/ubuntu/kicad-10.0-releases)),
  SHA-256 `ce96f7c3bd935a021c65b301427f74c1c16b211210b49ce9b40309ce5ecfbb33`, equal to the
  archive's `Packages` index. It was extracted without root into the private evidence
  folder with its distribution library dependencies; no system installation or PATH
  change. Observed `kicad-cli version`: `10.0.7`; build OCC 7.6.3, wxWidgets 3.2.4.
- Public interfaces used: [kicad-cli](https://docs.kicad.org/10.0/en/cli/cli.html)
  `pcb export stats`, `pcb drc --format json`, `pcb export drill`; the
  [board file format](https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/); the
  [DRC JSON schema](https://schemas.kicad.org/drc.v1.json). The statistics semantics
  (minimum track clearance on each item's primary layer; drill table grouping) were
  read from the public 10.0.7 sources `pcbnew/board_statistics_report.cpp` and
  `pcbnew/board_statistics.cpp`; token names from the public board parser. No upstream
  code is copied.

## Fixtures and expectations

Four original boards, written by hand and re-saved in the KiCad 10.0 format with
`kicad-cli pcb upgrade --force`, are in `examples/schemaxis/fixtures/kicad/`.
Expectations come from the declared coordinates (see `docs/kicad.md#fixtures`):

| Fixture | Independent expectation | Observed (KiCad 10.0.7) |
| --- | --- | --- |
| `tiny-board` | 4 footprints, 6 holes (4 plated), 30 x 20 mm, min clearance 1.9-2(0.125) = 1.65 mm, clean DRC | as expected; native stats agree with host reader on every compared field |
| `tiny-variant` | 6 footprints, 9 holes (6 plated), 40 x 25 mm, 1.2 mm thick, min clearance 1.9-0.15-0.2 = 1.55 mm, J1 at 270° puts pin 3 at (2.92, 12.5) | as expected; merged inch drill file matched hit-for-hit |
| `tiny-clearance` | two AUX segments meet 0.35 mm from a 0.25 mm GND track: two 0.1 mm breaches of 0.2 mm | `DRC_VIOLATIONS`; 2 `clearance` errors, actual 0.1000 mm, host prediction confirmed |
| `tiny-open` | GND split into two pad clusters: 1 missing connection | `DRC_VIOLATIONS`; 1 unconnected item, 2 `track_dangling` warnings, prediction confirmed |

J1's 90° rotation on the baseline was confirmed by KiCad reporting zero unconnected
items with the GND track ending at the predicted (10.54, 10) mm pad.

## Checklist results

| ID | Result |
| --- | --- |
| registration | `adaptor.json`: id `kicad`, runtime family 10.0, workflow/compose routes, `query`/`reusableInputs`/`resources` hooks, `--kicad` CLI option, serial process mode, display identity. Feature decisions in `readiness.json`: workflow, composition, reusable inputs, source/property authoring supported; native inspection, MPI, time batches, live editing, native save and conversion unsupported with reasons (`mpi`, `time-batches` also in `completion.notApplicable`). Registry discovery needs no app-name branch. |
| schema | Three closed `oneOf` variants; `board` required string, integer maximums 0–100000 default 0, `units` enum mm/in, `separatePlating` boolean. Tests reject cross-operation fields, negative/boolean/fractional counts and undeclared keys in schema and planner. |
| semantics | Planner: absolute `.kicad_pcb` path without control characters, exact faults (`INVALID_RESOURCE`, `UNKNOWN_FILTER`, `UNKNOWN_ARGUMENT`, `INVALID_ARGUMENT`, `UNSUPPORTED_VERSION`). Before any native launch the captured board is parsed: formats 20240108–20260206 only (newer/older → `UNSUPPORTED_BOARD`), exactly two copper layers, through vias only, no oval/offset/backdrilled holes or footprint-owned Edge.Cuts, back-side drilled pads rejected for drill export, size/depth/item limits (`RESOURCE_LIMIT`), malformed s-expressions and non-finite values rejected. |
| native-mapping | Each operation maps to one public `kicad-cli` command with fixed flags (JSON, mm, all severities, absolute decimal Excellon). Read back: native statistics vs host reader, DRC JSON schema/version/source/severities and console totals, drill hits vs board holes. Losses listed in plan and summary. Runtime must be 10.0.x; only 10.0.7 was run. |
| execution | Fresh run directory; board and sibling `.kicad_pro`/`.kicad_dru` read through a nonblocking, non-following, size-bounded regular-file descriptor (FIFOs, symlinks and oversized files rejected before hashing), captured and digest-checked; isolated HOME/XDG/`KICAD_CONFIG_HOME`; one total deadline across stages; captured copies re-hashed after every stage (`NATIVE_MUTATED_INPUT`); `DRC_VIOLATIONS` stops before drill export and leaves no receipt. Verification recomputes every conclusion from retained files and binds every expected stage record: exit code 0, the exact plan recipe command (portable executable and run-directory tokens), the run's own replay script and the retained stdout/stderr tails; all records and logs are digest-bound and size-bounded. Native conformance: timeout → `RUNNER_TIMED_OUT`, pre-launch cancellation → `RUNNER_CANCELLED`, integrity tampering detected. |
| discovery | Application and operation purposes/keywords in `capabilities.py`; seven reviewed `search-cases.json` cases cover all kinds and surfaces (Excellon, DRC, "clearance violation", "board statistics", ambiguous "holes", negatives "gerber" and "autorouter"). Capability search: all pass. Studio selection/Add: pass in the shared tree. Help: passes after Help generation in an isolated copy of the checkout; the shared tree needs central generation. |
| guidance | `guidance.json`: 3 operations and 32 field addresses, all `reviewed` (35/35), with units, defaults, pitfalls, examples and file extension; `tools/studio_guidance.py --check --app kicad` passes. |
| help | `docs/kicad.md` guide with faults/recovery, linked API pages. Generated `docs/generated/kicad-operations.md` and packaged Help were produced only in an isolated copy (rendered correctly, all contextual operation topics resolve); central regeneration is pending. |
| examples | `kicad-inspect`, `kicad-drc`, `kicad-drill` (baseline), `kicad-drill-variant` (variant), invalid `kicad-relative-invalid` (`INVALID_RESOURCE`) and `kicad-gate-invalid` (`INVALID_ARGUMENT`, schema-invalid). Studio: three snippets and three templates with path placeholders and test values; library validation passes. |
| tests | `tests/unit/test_kicad_admission.py` (17 tests, all pass): host conformance, plan/schema, reader facts, malformed/version/unsupported boards, arc bounds, statistics disagreement, DRC validation and forged reports, connectivity incl. crossing/overlap/roundrect cases, comparison budget, drill falsification, runtime faults and a replayed stand-in runtime for tamper, forged-clean DRC, mutation and old-version rejection, FIFO/symlink/oversized inputs, and stage-record forgery (exit code, command, script, logs, deletion) even with refreshed digests. Independent review findings fixed: same-net crossings/overlaps and rounded corners are no longer treated as connections (now `unchecked`), copper scope is exactly two layers, gap and connectivity scans use x-sorted sweeps with explicit comparison and result budgets. |
| qualification | `tools/qualify_kicad.py` on KiCad 10.0.7 (rerun after the review fixes): 6/6 cases including literal drill-hit coordinates, 13/13 tamper probes detected, shared CLI `run`/`verify` parity, repository fixtures unchanged. `schemaxis adaptor conform schemaxis.kicad/1 --native`: verified (4 cases plus lifecycle probes). These receipts were **not recorded**: later guidance edits and the pending central Help regeneration change the source digest. Record a fresh receipt after shared generation. |
| maintenance | `upstream.json`: latest-stable policy, release-notes pattern excluding RCs, absorbed 10.0.7 on the basis of the native acceptance above, acceptance recipe. `schemaxis updates --app kicad` reports current. |

## Commands run

```sh
PYTHONPATH=src python3 -m unittest tests.unit.test_kicad_admission        # 17 OK
PYTHONPATH=src python3 tools/studio_guidance.py --check --app kicad       # 35 reviewed
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.kicad/1 --output-directory NEW   # host verified
SCHEMAXIS_CONFIG=PRIVATE PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.kicad/1 --native \
  --output-directory NEW --timeout 300                                    # native verified, not recorded
python3 tools/qualify_kicad.py --kicad KICAD_CLI --output-directory NEW   # verified
node --test src/schemaxis/studio_ui/tests/search-acceptance.test.mjs     # kicad Help pending generation; all pass in isolated generated copy
PYTHONPATH=src python3 -m schemaxis updates --app kicad                   # current
```

## Remaining gaps

- Central `schemaxis reference` and `tools/generate_studio_help.py` regeneration, then
  a fresh native conformance receipt and `schemaxis adaptor record`.
- The candidate catalogue entry and README remain for the architect.
- Not covered: board authoring, multilayer boards, blind/buried/micro vias, slots and
  offsets, backdrills, zone refill, schematic parity, Gerber/STEP/position/IPC outputs,
  drill maps, footprint-owned outlines and drill export for back-side drilled pads.
- Host DRC predictions model straight tracks, through vias and simple pads with one
  netclass; arcs, zones, custom pads and same-net overlaps are reported `unchecked`.
- Only KiCad 10.0.7 on Ubuntu 24.04 x86_64 was run; other 10.0.x releases and
  platforms are accepted by the version check but unqualified.
