# FreeCAD technical-sheet milestone — 4 November 2026

This milestone adds the `schemaxis.freecad.drawing/1` route. It does **not**
complete FreeCAD or the entire TechDraw capability family. The remaining
strategic drafting work stays listed in [the drawing guide](../docs/freecad-drawings.md).

## Delivered workflow

Checked STEP or one explicitly selected stored FCStd shape becomes a frozen,
owned source for an editable native TechDraw sheet. The input project itself is
never restored: bounded ZIP/XML admission extracts BREP geometry without loading
its proxies, macros, expressions, linked documents or feature history. STEP uses
the existing bounded single-solid scanner and an explicit assigned-unit assertion.
Independent volume, bounds and uniform-density centre of mass are mandatory.
FCStd parent assembly placements and App::Link resolution are not reconstructed;
the contract is the stored shape frame, with positioned STEP as the alternative.

A4/A3 landscape paper, six orthographic directions, isometric presentation,
title/revision/notes, true geometric dimension intent and native FCStd/SVG/PDF
publication are supported. Overall extents, horizontal/vertical/projected point
distances, circular-centre mounting offsets, radius, diameter and unique straight
edge lengths are measured native objects. Geometric anchor selection resolves
afresh; authored native topology indices and arbitrary label substitutions are
not exposed. Equivalent coincident projected centres are one geometric anchor.

Automatic layout reserves separate horizontal/vertical dimension lanes, stacks
smaller dimensions nearer the geometry, shifts view centres inside their cells,
and includes annotation margins in the common scale calculation. Authors need
no paper coordinates for the enclosure's overall/wall/mounting dimensions.
Optional explicit positions remain an expert control. Title/notes are wrapped
within bounded columns and centred inside the reserved title strip; unavoidable
overflow fails with corrective guidance.

The drawing embeds source geometry and its template. Native drawing editing is
preserved; it does not update the upstream model or reverse-synchronise JSON.

## Fresh verification

Latest stable FreeCAD1.1.4 was checked against its official release and versioned
TechDraw source. Native qualification uses that runtime in separate command-line
build/reopen processes and isolated offscreen GUI publication. GUI preferences
are isolated in the run; no user PATH or application launcher is modified.

- 17 host admission tests passed, including bounded source admission, hostile XML,
  no FeaturePython restoration, semantic point selection, source-removal replay,
  unit faults, automatic lane spacing and overflow, and non-geometric BREP masks.
- Host route conformance passed: schema/planner agreement, deterministic plans,
  caller preservation, valid held-out paper/view changes and wrong-unit refusal.
- One Studio browser test passed: drawing starter discovery, filled typed source,
  validation, wrong-unit feedback and intact document opening.
- The independent native qualifier passed four positive drawing cases: an open
  enclosure with four floor bores, STEP/opposite-view/A3 variation, a cylinder
  with measured radius/diameter, and a triangular prism with unique edge length,
  projected distance and vertical dimensions.
- The enclosure independently checks 2 mm wall,10 mm mounting offset,80 mm overall width
  and30 mm depth. Incorrect source volume and ambiguous repeated-hole size selection
  fail with their distinct native faults.
- Ten refreshed-hash attacks are rejected by semantic saved-document or native SVG
  content checks: source placement, view scale/source/frame, dimension type,
  arbitrary display mode, measurement mode, annotation text, sheet size and
  published wall measurement.
- A copied standalone FCStd is edited, saved and reopened in another process:
  native view scale/title changes persist and the2 mm wall measurement remains.
- CAD publication to drawing workflow execution, verified resume and damaged SVG
  invalidation pass; the producer and independent branch remain reusable.
- Retained verification passes after original FCStd/STEP supplier inputs are removed.
- Native PDF output was rendered and visually inspected: views, dimension text,
  captions and title/notes remain legible inside the page. The automatic-lane
  enclosure requires no authored paper positions. Root review separately
  inspected the preceding representative layout.

The current owner checks are reproducible with
`tools/qualify_freecad_drawing.py`, `tests/unit/test_freecad_drawing.py` and
`tests/studio/freecad-drawing.browser.test.mjs`. Repository-wide generated assets,
combined application workflows, packaging and final source-bound registration
belong to programme integration; those are not implied by these owner checks.

## Verification boundaries

Saved XML checks native object types/membership, source/page/view links, exact
projection settings and positions, dimension types/references/units/measured
mode, annotations and embedded template dimensions. Native measured anchors and
SVG dimension text are independently compared to declared geometry. This detects
a runtime trap where App readback is correct but a missing post-GUI recompute
publishes zero. PDF verification itself checks signature/truncation and hashes;
representative PDF content/layout also receives rendered visual QA.

Frozen BREP comparison preserves geometric bytes. Native1.1.4 observation showed
`isValid` changes the face Checked cache flag, and property ownership clears
Compound/Solid Free flags. Only those precisely located non-geometric bits and
previously qualified signed-zero normalisation are masked. Independent re-import
materialises an unchanged placement to account for native property identity
location storage. Other topology, coordinates, orientation and geometry remain
bound; this is not an arbitrary numerical equivalence tolerance.

Important unfinished TechDraw work includes section/detail/clipped/broken views,
hatching, tolerance/GD&T/datum/weld/surface-finish intent, hole/BOM tables,
multi-page layout, DXF and associative upstream model updates. CAM toolpaths,
manufacturing simulation and the other FreeCAD strategic families remain separate
programme work. No whole-application completion percentage follows from this
milestone.
