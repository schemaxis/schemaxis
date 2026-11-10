# FreeCAD degenerated-edge selection and measurement — 2026-10-24

Scope: the existing solid route's geometric edge inventories, used by semantic
`fillet`/`chamfer` selectors and by `edgeCount`/`totalEdgeLength` measurements. No
application, native option, mapping or export format was added.

## Defect

Valid native solids contain degenerated edges: a sphere's two poles (undefined
curve, length ~2e-15 mm) and a pointed cone's apex (length 0). An edge selector
or edge measurement on a sphere ended in a raw `TypeError: undefined curve type`
inside the native process. On a pointed cone the whole inventory was rejected as
`VERIFICATION_FAILED` ("invalid edge measurement"), so even a base-circle selector
was unusable on a valid solid.

## Change

- Native inventories record such edges as curve `Degenerate` (length at most
  1e-7 mm) and keep contiguous one-based numbering; their curve is never read.
- Geometric predicates never match them. Explicit indices still address them.
- A `Degenerate` record with a longer or negative length, and any other curve
  with non-positive length, is still rejected, so the label cannot hide a real
  edge. A real-length edge without an analytic curve gives `UNSUPPORTED_EDGE`
  with its index and recovery text.
- Inventories without degenerate edges, including retained receipts, have the
  same record shape and verify unchanged.

## Evidence

- `tests/unit/test_freecad_allocation.py`: 6 new tests. Before the change 5
  failed (4 errors, 1 failure) and the unchanged-inventory test passed; after, all pass.
- Affected FreeCAD host modules (selections, measurements, design study, live,
  parameters, part design, assembly, assembly sources, STEP import, adaptor and
  the new module): 137 tests, OK. The full host suite was not run here.
- A bounded serial call of the changed inventory code in a retained FreeCAD
  1.1.3 batch process confirmed: sphere edges 1 and 3 `Degenerate`, cone apex
  `Degenerate`, and `{"curve": "circle"}` on the pointed cone selects only its
  base circle (edge 3).

## Limits

Upstream's latest stable release is 1.1.4; only 1.1.3 was available, so this is a
reproduction and confirmation, not native qualification. `absorbedVersion` and the
route's qualification receipt are unchanged. The existing native qualifiers have
not been rerun for this change. The 1e-7 mm threshold is OCC's confusion
tolerance; shorter genuine edges cannot be distinguished from degenerated ones.
Selection remains geometric re-selection, not persistent topology identity.
