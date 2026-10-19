# FreeCAD mechanical-part workflow qualification

The phase-one increment adds one origin-based PartDesign Body, owned fully
constrained rectangle/circle sketches, one first Pad and a linear through-all
Pocket history. Named length parameters drive sketch dimensions and Pad length;
a literal signed circle centre supplies editable offset constraints. The existing
Part primitive/boolean/profile workflows keep their declarations and plans.
Assembly/placement and broader import/preparation work remain subsequent phases.

The host contract checks optional ownership ports consistently in planning and
schemas, rejects branches/cross-owner or reused profiles, distinguishes Body
containers from solid output, and permits empty Bodies/unused sketches during
incremental authoring only with a separate valid output. Live sessions and scalar
designStudy reject this batch-only route explicitly. The parameter foundation is
recorded in [its qualification note](2026-10-17-freecad-parameters.md).

Bounded native qualification targets FreeCAD 1.1.4. The independent mechanical-part
oracle uses an 80 × 50 mm plate and offset radius-3 hole: volume `(4000 − 9π)t`,
surface area `2(4000 − 9π) + (260 + 6π)t`, analytic bounds and asymmetric centre of
mass. Native point membership and cylindrical faces establish the through-hole.
Every driver's endpoints, direct unbound centre edits, saved edited FCStd reopening
in another process and STEP volume are checked. A fixed-depth Pocket matching the
initial shape is rejected semantically, then becomes a blind hole after a thickness
edit and fails the independent geometric oracle.

The acceptance tool also exercises literal models, finite variants, high-precision
Pad expressions, an empty Body with Tip None/eight origin helpers and visible
unowned output, and an unused sketch that does not replace the solid Tip. Refreshed
artifact hashes cannot legitimise altered Body placement, Group/Tip, ownership,
Origin roles, sketch attachment, constraint names/types/endpoints, expressions or
Pocket extent/direction. Corrupt/truncated literal FCStd files return structured
verification faults.

An independent actual GUI probe exposed a first-open problem in headless output:
App.Visibility alone was overwritten while view providers were restored. A minimal
native-format GuiDocument.xml carrying typed per-object visibility resolved it;
GUI reopening showed the Body/final tip without manual visibility changes, exposed
the real Pad expression, entered the bore Sketcher editor and exited with solver
zero, full constraints and unchanged valid volume. The adaptor persists only that
bounded visibility state and strictly checks its membership, types, duplicates and
values. Camera and style are native defaults. Headless checks alone are not claimed
as GUI qualification. A subsequent independent GUI check of freshly generated
parameter-driven and literal parts confirmed first-open visibility, actual sketch
edit mode, fully constrained solver state and unchanged volume after leaving the
editor. An empty Body with a separate solid output showed only that solid. All
checks used isolated settings and copies of the synthetic models.

The actual Studio browser check also adds an optional Body-owned circle through
the typed operation form, preserves all existing parameters and feature nodes,
validates the resulting document and checks atomic undo. Pad exposes its required
Body and profile inputs; cancelling its form preserves the document.

Reproduce host and native checks with:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_freecad*.py' -q
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_schemaxis_freecad.py' -q
PYTHONPATH=src python3 tools/studio_guidance.py --app freecad --check
node --test tests/studio/freecad-part-design.browser.test.mjs
PYTHONPATH=src python3 tools/qualify_freecad_part_design.py \
  --directory NEW_EVIDENCE_DIRECTORY --executable /absolute/path/to/freecadcmd
PYTHONPATH=src python3 tools/qualify_freecad_parameters.py \
  --directory ANOTHER_NEW_DIRECTORY --executable /absolute/path/to/freecadcmd
```

Native receipts and generated references are refreshed at the integration gate;
this note does not replace source-bound receipts. Qualification is serial and
bounded to these workflows, not general Sketcher, all PartDesign features, every
geometric parameter combination or arbitrary native GUI editing. Native edits do
not reverse-sync authored JSON. STEP/STL retain geometry, not feature history.
