# FreeCAD persistent length parameters: scoped review record

Scope: the first increment of the FreeCAD strengthening assignment adds explicit
named native length drivers and node-local affine relationships for box, cylinder
and extrusion dimensions. It supports batch parts and finite variants. Assembly
constraint extensions and import/preparation extensions remain pending. This file
records the affected delivery surfaces; it does not declare the full assignment
complete or qualify unrelated FreeCAD features.

| Delivery surface | Change and acceptance |
|---|---|
| Contract | Optional parameters/drive, bounded affine terms, independent range extrema, explicit competing-option and unsupported live/designStudy faults. Existing plan fields and publication positions are preserved. |
| Implementation | Native typed VarSet, deterministic readable property names, expressions, recomputation, build/reopen observations and saved-file semantic checks. No shared resolver changes. |
| Verification | Independent plate volume/area and extrusion volume; each driver perturbed independently; edited native copy saved and reopened in a fresh process; same-value relationship forgeries rejected. |
| Discovery | Application purpose, curated operation vocabulary and adaptor-owned positive/ambiguous/negative search cases. |
| Guidance | Parameter identity, physical units, independent bounds, affine terms, native lifetime, defaults and conflict rules are explained per field. |
| Help | Local parameter guide and fault recovery; generated schema/reference/packaged Help refresh is coordinated separately at integration. |
| Examples | Plate, extrusion, finite variants, invalid duplicate binding and a measured CAD-to-CAD workflow, plus an editable Studio starter. |
| Tests | Focused host negatives, exact old-plan compatibility, schema/Studio/guidance and discovery checks; final integration suite remains a separate gate. |
| Qualification | Isolated FreeCAD 1.1.4 native qualification is bounded to the named fixtures, persisted edits, hostile evidence and regression examples. Source-bound common receipts require final integration refresh. |
| Maintenance | Official latest stable 1.1.4 was checked; absorbed version remains unchanged until final scoped host/native gates and review are accepted. |
| Lifecycle | Existing process runner, fresh outputs and unchanged workflow resume retained. Invalid native evidence rebuilds the producer and dependent consumer; an independent job can be reused. Authored changes require a fresh directory. |
| Reuse and loss | No artifact ordering change: STEP0, STL1, FCStd2, optional measurements3. Only FCStd retains native relationships; STEP/STL carry geometry. |

The D2 design received an independent model review, followed by resolution-timing
and native API probes. Root review additionally required an independent box
oracle, strict single-valued typed XML metadata and high-precision native numeric
normalisation tests. These are implementation acceptance requirements, not claims
that generated metadata alone establishes correctness.

The qualifier is `tools/qualify_freecad_parameters.py`; its native worker is
`tools/qualify_freecad_parameters_native.py`. Raw local runs retain authored input,
plan, runtime, submission/PID records, observations, artifacts and rejection
results. The first successful qualification covered plate and extrusion edits,
maximum-length names, negative/multiple drivers, two variants, workflow resume and
invalidation, bracket, semantic fillet and measurements. Final numeric/parser
hardening receives a new source-bound run rather than silently relabelling that
older result.

Legacy assembly code is unchanged by this increment. Its completion metadata
records the established fixed-tree route and regression qualification, not new
assembly functionality. Live geometry still supports its existing contract;
persistent batch drivers deliberately fail before entering a live session.
No MPI, GUI-driver reverse synchronisation, arbitrary expressions, nonlinear
constraints or universal topological identity is claimed.
