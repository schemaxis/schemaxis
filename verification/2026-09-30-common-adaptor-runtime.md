# Common adaptor runtime verification — 2026-09-30

The shared framework now prepares expressions, document references, pure value
functions and finite analytic inputs for all thirteen adaptors and fifteen routes.
The registry and direct built-in entry points use the same boundary. Native
application modules remain isolated from host discovery and planning.

## Scope and evidence

Final native evidence is retained locally in
`evidence/common-runtime-20260930-05/report.json` and
`evidence/common-runtime-20260930-05/workflow-report.json`.
These are newly executed serial checks; they do not refresh older qualification
receipts, imply MPI coverage, or claim exhaustive application coverage.

The route sweep used two distinct effective inputs from each route's existing
independent development fixtures. For each available route it planned both
states, executed them natively, ran the existing independent fixture assertions,
verified every child and aggregate publication, rejected altered aggregate state
indices, restored the evidence and verified again. Each route's retained source
digest was checked against the final implementation.

| Route | Two changing native states | Independent assertions and corruption rejection |
|---|---|---|
| ParaView | Passed | Passed |
| Blender graph | Passed | Passed |
| FreeCAD solids | Passed | Passed |
| FreeCAD assembly | Passed | Passed |
| Blender rendering | Passed | Passed |
| Godot | Passed | Passed |
| Aseprite | Passed | Passed |
| Octave | Passed | Passed |
| Calc | Passed | Passed |
| Cantera | Passed | Passed |
| Case preparation (since moved to a separate package) | Unavailable | Not run natively |
| FFmpeg | Passed | Passed |
| Gmsh | Passed | Passed |
| ngspice | Passed | Passed |
| QGIS | Passed | Passed |

That is 14/15 routes (93%) with native two-state evidence. Case-preparation
planning and shared input support are covered on the host, but native execution
returns `INTERPRETER_NOT_FOUND`: no launcher is configured for this run.
The sweep therefore deliberately reports `verified: false` overall; its fourteen
successful per-route records remain explicit. This percentage measures this
bounded qualification exercise, not overall adaptor maturity.

## Native workflow checks

- The committed [Gmsh → Octave example](../examples/schemaxis/workflow-analytic-values.json)
  ran two whole-workflow states. Measured Gmsh volumes were 1000 and 1200 mm³;
  Octave received each volume, an expression-derived half-volume, and the mesh
  size selected through a cross-operation document reference (3 and 2 mm).
  Independent numeric checks passed, all twelve publications verified, and all
  four unchanged jobs were reused on resume.
- A separate Gmsh → Octave workflow used verified mesh volume as the start of an
  analytic range controlling an Octave sequence's endpoint. Planning explicitly
  deferred the consumer; execution produced two consumer states with final
  values 1000 and 2000. Native tables and the complete workflow verified.
- A FreeCAD fixed assembly executed as a scheduled operation, independently
  verified its retained native assembly publication, and reused its verified job
  on an unchanged resume.

## Host checks and limits

The final full host regression run completed **833 tests, with 22 expected skips**
and no failures or errors (238.155 seconds). This includes generated-schema drift
checks, the expanded example corpus and the existing publication/editor/scheduler
regressions. The transcript is retained in
`evidence/common-runtime-20260930-05/host-tests.log`.

`tests/unit/test_adaptor_runtime.py` covers all-route preparation and direct entry
points, expressions over synchronized inputs, Cartesian order and limits,
definition-site references and cycles, cross-operation references, scoped axes,
producer-derived analytic ranges, pre-execution validation, corrupted values,
publication byte hashes, aggregate protocol checks, resume locking and failed
session lifecycle. Existing regression checks preserve ParaView publication-axis
rules and graph reuse semantics.

The common session is a logical apply/verify/close lifecycle with isolated native
executions per visit. It does not claim a persistent native process for every
application. Existing graph engines retain their specialised incremental worker
semantics. Studies are finite, bounded and verified; arbitrary cyclic workflow
feedback, adaptive convergence and persistent GUI sessions are not added here.
Case preparation remains experimental and is not a solver or mesher.

Reproduce the route sweep after configuring runtimes:

```bash
PYTHONPATH=src python3 tools/qualify_common_runtime.py \
  --config evidence/adaptor-extension-config.json \
  --output-directory evidence/common-runtime-repeat --timeout 300
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
```
