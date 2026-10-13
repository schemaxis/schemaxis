# First adaptor growth through the completed framework

Gmsh is the first new provider delivered through the development kit after the
existing-adaptor migration. The reviewed node scaffold became three real
operations (`box`, `readSTEP`, `tetrahedral`), complete selection/context material,
editable inputs, independent verification and a source-bound qualification receipt.
No shared application-name routing branch or host dependency was added.

The [official release page](https://gmsh.info/) identified **4.15.2** as stable;
that exact package was installed in an isolated ignored environment and qualified.
Its absorbed version is recorded only after successful native acceptance. The
worker uses the [public Gmsh API](https://gmsh.info/doc/texinfo/) in separate build
and reopen processes. User configuration and PATH were not changed.

## Independent results

- Native kit baseline: a 10×10×10 mm cube, **1000 mm³**. Variant: 20×10×10 mm,
  **2000 mm³**, with a changed target edge length. Literal bounds and physical
  names also pass. Two cases, **28 missing/tampered evidence checks**, timeout and
  pre-launch cancellation all pass.
- [FreeCAD → Gmsh → ParaView](../examples/schemaxis/freecad-gmsh-paraview.json):
  20×10×5 mm then 20×10×7 mm parts. Gmsh observes **1000 and 1400 mm³**;
  ParaView independently integrates **1000.0000000000005** and
  **1399.9999999999998 mm³**. The volume meshes contain 433 and 562 tetrahedra;
  boundary meshes contain 288 and 368 triangles. These counts are observations,
  not a requirement that meshing always produces identical connectivity.
- ParaView reads both VTU files and retains physical tag 1 for the volume and 2
  for the boundary. Independent expected bounds and CAD-volume agreement pass.
  FreeCAD and Gmsh reuse their verified attempts on unchanged workflow resume;
  the general ParaView file-reader path conservatively reruns.
- A synthetic two-solid STEP is rejected. Corrupting captured STEP bytes invalidates
  verification; restoring them restores verification. Offline verification uses
  captured input rather than depending on the external original.
- A deterministic public client performs discovery, bounded context retrieval,
  source editing, property patches, planning, execution, verification and structured
  summary inspection. It observes **1000 then 2000 mm³** and rejects duplicate
  physical names. **39 requests / 37,614 response bytes**. This is procedure proof,
  not an autonomous-model evaluation.

Every run independently parses the ASCII MSH subset, calculates positive signed
cell volumes, checks complete exterior faces and closed manifold edges, enforces
CAD volume tolerance, and parses VTU back to check coordinates/connectivity/tags.
The fresh native process independently reopens MSH. Integrity checks bind retained
publications, native evidence and authored/effective plans.

The handoff runtimes were FreeCAD 1.1.3 build 20260725 and ParaView 5.13.3, using
their existing adaptors. Their absorbed versions were not changed by this work.

## Verification and reproduction

The catalogue-wide host qualification and development admission pass for **eleven
adaptors / thirteen routes**. All **759 operation identifiers** have selection
guidance. All **50 generated reference files** pass. Twelve native route receipts
are source-current; the experimental case-preparation route still has no
registered native qualification. Current receipts collectively cover 26 cases, 264 integrity
checks and 24 lifecycle checks; this growth run freshly exercised QGIS and Gmsh,
while other source-current receipts retain the preceding migration's evidence.

**737 unit tests passed, 22 skipped (759 total)** in 188.691 seconds. Both
capability-protocol tests pass (59.061 seconds). The first regression run exposed
a hard-coded route count and a first-page discovery assumption; tests now compare
against the registry and follow bounded pages. Its upstream-evidence check ran
before this record existed; the completed tree passes that check too. Gmsh’s
release monitor reports 4.15.2 current with no pending update or attention item.
Seven focused Gmsh unit tests pass, covering host conformance, units/names/dependencies/resource limits,
independent tetrahedral geometry, VTU corruption, inverted/missing-boundary meshes,
missing input/runtime/evidence, and false native success.

```sh
PYTHONPATH=src python3 tools/qualify_gmsh.py \
  --config /path/to/private-config.json --output-directory new-acceptance
PYTHONPATH=src python3 -m schemaxis adaptor record new-acceptance/native/qualification.json
PYTHONPATH=src python3 -m schemaxis readiness --admission --check
PYTHONPATH=src python3 tools/qualify_adaptor_migration.py --output-directory new-host-check
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
PYTHONPATH=src python3 -m schemaxis reference --check
```

Bulk native evidence is in `evidence/gmsh-final-acceptance/`; regression logs and
catalogue checks use `evidence/adaptor-growth-*`. Failed/earlier probe directories
were retained. See [the guide](../docs/gmsh.md), [delivery bundle](../src/schemaxis/adaptors/gmsh/readiness.json)
and [registered receipt](../src/schemaxis/adaptors/gmsh/qualification.json).

This is one serial solid, first-order cells, one whole-volume group and one complete
boundary group. Imported face labels, per-face selections, multi-solid assemblies,
high-order/parallel meshes and solver setup are not qualified. Curves are represented
by linear cells subject to the declared CAD-volume tolerance; the analytic fixtures
here are boxes. Native meshing success and positive volumes do not certify mesh
adequacy for a particular simulation. VTU carries numeric group IDs; retain the
summary for physical names, millimetre units and explicit conversion losses.
