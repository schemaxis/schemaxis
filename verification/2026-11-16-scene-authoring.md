# Guided scene authoring

Copyright (C) 2026 David L. F. Gaden.

## Delivered behaviour

Adaptor annotations select shared GUI controls for the existing scene contract:
pipeline visibility, per-object geometry/text appearances, Matplotlib colours,
cell/point fields, explicit array inspection, image settings, cameras, appearance
variants, geometry/measurement outputs and bundles. No publication schema keys
were added. See [the coverage audit](../docs/design/paraview-scene-authoring.md).

Nested array and union fields now expose the existing value picker. Camera
framing can retain a linked Spatial box, select object extents, or create a
volume using the existing builder. Scene and volume changes apply together;
Cancel discards both. Removing cameras refreshes surviving picker destinations.

## Verification

- 54 focused Python tests passed: Studio scene/catalogue metadata, colour
  parsing, publication, spatial cameras, publication framing and Live Data.
- 22 guidance tests passed; generated Studio help passes its freshness check.
- Seven scene browser tests passed against real Studio and Chromium: untouched
  round trips and cancellation, unavailable selections, searchable palette
  selection, RGB entry, field colouring, explicit inspection, linked frames,
  camera removal, variants, text annotations, volume creation, new scenes and
  restoring omitted appearance defaults. Narrow dark layout has no horizontal
  overflow. Light/dark screenshots were inspected.
- Four existing Spatial Stage 2 browser tests and four OpenFOAM reader/block
  selection browser tests passed.
- The non-browser JavaScript suite passed 924 of 925 tests. The unchanged
  `gui-audit3.test.mjs` expectation for an empty reader selection fails: it
  expects every block, while the unchanged helper returns no blocks. An isolated
  rerun reproduces that failure. Neither file was altered for this work.

Bounded serial ParaView 5.13.3 checks passed:

- Wavelet to point-to-cell to surface: cell-array inspection and verified PNG
  using a fixed range, legend and linked spatial camera bounds.
- Sphere: named xkcd colour, surface edges, opacity, verified PNG and editable
  state bundle with independent relocated reload verification.
- Vector-array inspection: three components, magnitude range and each component
  range matched known calculator output.

The initial OSMesa installation could not start because its system
`libglapi.so.0` dependency was absent. The successful checks used an explicitly
selected installed ParaView executable without changing application PATH.

These checks do not establish MPI, exhaustive native coverage or a full
repository Python/release-gate pass. Remaining design refinements are identified
in the coverage audit; unsupported native appearance settings are not exposed.

Before committing the combined scene, Spatial and Live Data changes, the combined
host regression selection ran 316 tests successfully, with nine skips. The
release-content gate passed with no unallowlisted hits, generated help was
current, and the staged diff passed its whitespace check. This was a targeted
host regression run, not the full repository Python suite.
