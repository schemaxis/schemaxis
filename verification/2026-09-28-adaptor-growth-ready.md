# Adaptor growth readiness acceptance

The development kit is ready for the next bounded adaptor. This record describes
newly run checks against the implementation delivered after the contract and
scaffold milestones. Bulk evidence is retained under ignored `evidence/adaptor-kit/`;
portable scoped receipts are committed beside the owning adaptor manifests.

## Shared verification

- **747 unit tests passed, 22 skipped**, 177.157 seconds. Log:
  `evidence/adaptor-kit/final-unit.log`. Skips are not native qualification.
- Both progressive capability-protocol conformance tests passed, 57.500 seconds.
- All **47 generated-reference files** passed the current-content check.
- Four-route `readiness --admission --app octave --app freecad --app ffmpeg --check`
  passed. The whole-catalogue audit intentionally reports eight legacy routes as
  incomplete, with actionable migration diagnostics.
- Fourteen focused kit tests passed after recording receipts. They cover bounded
  context/revisions, conflicting claims, invalid cases, schema drift, wrong numeric
  results, evidence restoration, receipt completeness and fixture freshness.
- The full suite includes both generated scaffold models and the independent
  watchdog adversary, shared in-flight cancellation, process-group timeout cleanup,
  separate-session child cleanup and cancellation during evidence publication.

## Fresh native kit receipts

All eight cases below passed host conformance, native execution, independent
expectations and re-verification. Every publication plus authored input, effective
plan and verification evidence was tested both missing and tampered, then restored:
**76 integrity rejections** in total. Each route also rejected a native timeout and
pre-launch cancellation with the required exact fault: **8 lifecycle checks**.

| Route | Recorded runtime | Independent cases | Registered receipt |
| --- | --- | --- | --- |
| `schemaxis.octave/1` | Octave 11.3.0 | Linear derivative 2, then 3, at x = 0, 1, 2 | [Octave](../src/schemaxis/adaptors/octave/qualification.json) |
| `schemaxis.freecad/1` | FreeCAD 1.1.3, build 20260725, Git 145529fe741292ff0b3977a01195bf0247425794 | Box volumes 1000 and 1500 mm³, one solid; reopened native/STEP/STL publications | [FreeCAD](../src/schemaxis/adaptors/freecad/qualification.json) |
| `schemaxis.freecad.assembly/1` | Same FreeCAD runtime | Three fixed joints, one ground, plate thickness 5 then 7 mm; saved assembly verification | [FreeCAD](../src/schemaxis/adaptors/freecad/qualification.json) |
| `schemaxis.ffmpeg/1` | FFmpeg 6.1.1-3ubuntu5 | Known 2×2 PNG, FFV1 at 25 then 12 fps; every decoded RGB byte matches | [FFmpeg](../src/schemaxis/adaptors/ffmpeg/qualification.json) |

The media case initially failed despite a successful encoder exit: automatic FFV1
slicing decoded this tiny image as black, with mean absolute RGB error 127.5. The
independent verifier rejected it. A local native reproduction isolated the slice
choice; an explicit single FFV1 slice preserves the bytes. The original failure is
retained in `final-ffmpeg/`; fresh successful final-source results are in
`qualified/ffmpeg/`. Verification also now returns its recorded native runtime.
No fidelity tolerance was relaxed.

Portable recipe `resources` bind repository-relative fixtures at existing JSON
pointers. Tests prove equivalent checkouts have equal input fingerprints, changed
binary bytes invalidate freshness, and traversal/symlink escapes fail. Qualification
includes the current framework/owning-adaptor source and fixture bytes; all four
registered receipts report **source-current**. Their runtime observations do not
update upstream absorbed-version policy or claim latest-release compatibility.

## Published-context product proof

`tools/qualify_adaptor_growth.py` imports no adaptor implementation. It uses the
public JSON-lines service to discover, retrieve revision-bound context in 4096-byte
pages, author and patch shared drafts, plan, execute, inspect and verify all eight
pilot cases. Ordinary JSON example files and resource bindings are read only from
published delivery references. Both node and assembly document models pass.

The client checks numerical CSV values through `inspect_resource`, CAD volume and
assembly joint/DOF verification, and video count/timing observations. The native kit
above separately checks the complete recipe assertions, including assembly thickness
and decoded pixel error. Results are not inferred solely from a job success flag.

All four meaningful invalid examples were rejected with their published exact
fault. An unregistered route produced `UNSUPPORTED_VERSION`; an isolated missing
Octave configuration produced a retained `INTERPRETER_NOT_FOUND` failure. The
user's configuration was unchanged. Eight positive cases required no unexpected
retry or change to published guidance. Full request counts, context/response byte
volumes, timings and negative results are in `public-context-pages/report.json`.
The main client made 182 requests (153,282 response bytes). Its 45 context requests
used 44,154 response bytes, eight member walks, and at most 1,832 bytes per response
under the 4,096-byte context budget. The separate unavailable-runtime client retains
its own request records.

Additional public transport acceptance passed:

- `tools/qualify_agent_service.py`: three FreeCAD refinements; verified
  **Octave → Calc → Octave** workbook handoff with frequency 8/amplitude 2; reuse of
  a retained table resource; incompatible table-to-CAD binding rejected. Report:
  `agent-handoff/report.json` (158 requests, 99,804 response bytes, one expected rejection).
- `tools/qualify_authoring.py`: the same draft survives an invalid edit and process
  restart, undo restores it, and a real terminal-console property edit changes
  verified volume **1000 → 1500 mm³**. Stale plans and invalid drafts are blocked.
  Report: `human-authoring/report.json` (36 requests, three expected rejections).

These are deterministic client and console evaluations, not autonomous-model
quality evaluations. No new browser UI or MPI qualification is claimed.

## Reproduce

Configure the named runtimes privately as described in the installation guide.
FFmpeg may use `--executable` or a private configuration; no PATH changes are needed.
Always choose fresh output directories.

```sh
PYTHONPATH=src python3 -m schemaxis readiness --admission \
  --app octave --app freecad --app ffmpeg --check
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.octave/1 \
  --native --output-directory evidence/recheck-octave
# Repeat for schemaxis.freecad/1, schemaxis.freecad.assembly/1 and schemaxis.ffmpeg/1.
PYTHONPATH=src python3 tools/qualify_adaptor_growth.py \
  --output-directory evidence/recheck-growth
PYTHONPATH=src python3 tools/qualify_agent_service.py \
  --output-directory evidence/recheck-handoff
PYTHONPATH=src python3 tools/qualify_authoring.py \
  --output-directory evidence/recheck-authoring
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
PYTHONPATH=src python3 -m unittest discover -s tests/conformance -p test_capability_protocol.py -q
PYTHONPATH=src python3 -m schemaxis reference --check
```

After intentional source changes, old receipts become stale. Repeat the relevant
native conformance before `adaptor record`; never merely edit the stored digest.
See [growth readiness](../docs/design/adaptor-framework/GROWTH-READINESS.md) for the
completion criteria and [audit](../docs/design/adaptor-framework/AUDIT.md) for legacy
migration. MPI, H.264, live editing, untested operations and exhaustive schema/planner
equivalence remain outside these new receipts.
