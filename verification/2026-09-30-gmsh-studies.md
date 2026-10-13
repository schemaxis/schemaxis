# Gmsh meshing intent and feedback verification — 2026-09-30

Gmsh now supports named-boundary sizing, independently measured tetrahedral
quality and bounded refinement under declared acceptance requirements. The shared
feedback controller owns execution ordering, evidence and decision replay; the
Gmsh adaptor owns sizing semantics, measurements and the refinement policy.

## Final native evidence

Two newly executed serial acceptance runs passed on the final implementation:

- `evidence/gmsh-studies-20260930-08/report.json`: new quality/sizing/feedback,
  nested analytic visits and Octave measurement handoff.
- `evidence/gmsh-existing-20260930-10/report.json` and
  `native/qualification.json`: the existing native conformance kit, FreeCAD →
  Gmsh → ParaView workflows and four public authoring cases.

Both record the same final Gmsh source identity:
`sha256:b0fadac7d4af79c272ae67deb6bd9d5bde012a364131826d33e81178b64b6c6f`.
Native Gmsh was 4.15.2. These are bounded serial checks; historical receipts for
other adaptors are not refreshed and no MPI or exhaustive native coverage is
claimed. Bulk evidence and machine-specific configuration remain local.
The successful existing conformance receipt was registered through
`adaptor_conformance.register`, so Gmsh discovery reports source-current evidence
for those four named cases. The additional feedback checks remain explicitly
scoped in the separate study report above.

## Independent measurements and feedback

The 10 mm cube refinement case required maximum tetrahedral edge length ≤ 3 mm,
minimum mean ratio ≥ 0.1 and at most 20000 tetrahedra, within four attempts.

| Target size (mm) | Tetrahedra | Measured longest edge (mm) | Minimum mean ratio | Decision |
| --- | --- | --- | --- | --- |
| 3.00 | 336 | 5.004046 | 0.581395 | Resolution unmet |
| 2.10 | 676 | 4.166105 | 0.409259 | Resolution unmet |
| 1.47 | 1633 | 2.943628 | 0.405743 | Accepted |

The acceptance tool independently computes the selected longest edge directly
from retained tetrahedral connectivity and coordinates using `math.dist`, without
reusing the new quality-summary implementation. The normal verifier also compares
host edge extrema with native Gmsh measurements before and after reopening.
Analytic regular-tetrahedron tests check the mean-ratio formula, scale/rotation/
translation invariance, flattening and orientation rejection.

Named-boundary sizing reduced the fixed face's longest triangle edge from
3.261198 to 1.214297 mm, while the opposite face remained at 3.250972 mm. This
checks spatially selective sizing rather than merely a global refinement.
A declared fixed-boundary maximum of 0.9 mm was met on the second refinement
attempt at 0.845364 mm, with 2096 tetrahedra.

An analytic example used document references and an expression to supply maximum
edge requirements of 4.5 and 3 mm. The two outer states independently accepted
their inner studies after two and three attempts, retaining twelve publications.

## Refusals, provenance and integration

- Iteration limit, cell acceptance budget and minimum-size cases all completed
  with an auditable unmet outcome. Each exported only the JSON and HTML reports,
  with no candidate mesh selected. Public execution returned
  `STUDY_REQUIREMENTS_NOT_MET`.
- Changing authored input, execution result, machine report, human report,
  rejected-candidate summary or rejected-candidate VTU caused verification to
  fail. Restored evidence verified again. Host tests additionally challenge
  truncated/extra attempts, forged decisions and selected indices.
- Native failures, callback failures, cancellation and total timeout remain
  execution faults. A failing observation callback preserves earlier verified
  evidence and returns a structured fault without publishing success.
- A workflow consumer could not succeed after an unmet producer. A successful
  Gmsh study supplied its selected longest-edge measurement to Octave; the
  independent CSV assertion matched it. Both jobs were reused on unchanged
  workflow resume and verified again.
- The existing FreeCAD → Gmsh → ParaView cases passed for 5 and 7 mm part heights,
  including named planar boundary areas, ParaView volume integration and CAD/mesh
  reuse. ParaView read back all three quality arrays with the same numeric ranges
  as the independent mesh summary. Changed captured STEP bytes were rejected. Multi-solid STEP and empty
  or exhaustive named-face selections were rejected.
- The public authoring loop passed four source/property edit cases and the
  invalid-input case. Its measurement inspection now requests JSON pointers
  because the richer mesh summary exceeds a single bounded response.

## Reports and limits

The final full host regression run completed **846 tests with 22 expected skips**
and no failures or errors. Its transcript is retained in
`evidence/gmsh-studies-20260930-08/host-tests.log`. This includes generated-reference
drift checks, authored/resolved schemas, the example corpus, existing framework
regressions, analytic refinement preparation, quality oracles and feedback faults.
An earlier run exposed a stale generated module index after the new fault import;
reference regeneration corrected it before this successful full run.

Every attempted mesh is retained with its inputs, native readback, verified
publications and decision. `study.html` is regenerated during verification and
must agree with the machine history. Static HTML inspection checked table
structure, absence of executable embeds and local artifact links. Browser URL
security blocked opening the local report, so rendered visual inspection was not
performed; no browser-policy workaround was used.

Refinement is geometric size reduction, not a solver-error estimator or proof of
mesh independence. The measured minimum shape quality decreased as the global
mesh became finer, confirming why size and shape requirements remain separate.
The selected mesh is the first acceptable tested candidate, not a proven optimum.
Native volume tolerance remains a hard prerequisite for accepting observations.
Named boundaries retain the bounded planar selection model. The conservative
work estimate can reject feasible local refinements. Partial-study continuation,
persistent native-process rollback, arbitrary cyclic workflows and general
optimisation remain outside this change.

## Reproduction

Configure the native applications, then run:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
PYTHONPATH=src python3 tools/qualify_gmsh_studies.py \
  --config /path/to/private-config.json --output-directory new-study-acceptance
PYTHONPATH=src python3 tools/qualify_gmsh.py \
  --config /path/to/private-config.json --output-directory new-handoff-acceptance
```

See [Gmsh usage](../docs/gmsh.md), the
[analytic example](../examples/schemaxis/gmsh-analytic-refinement.json), and the
[shared policy design and FreeCAD next steps](../docs/feedback-studies.md).
