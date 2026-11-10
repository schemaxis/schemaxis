# Artifact viewer interface — 2026-11-05

The interface audit identified weak discovery of later image sequences, a slice
locator buried below metadata and lost on scroll, ambiguous preview checkboxes,
repeated playback controls, and lost browsing context after opening a file.

Implemented:

- Four persistent, descriptive viewing modes with data counts and explanations
  for unavailable modes. Collection summaries identify file types.
- Direct contents links and Animate actions for every sequence.
- Independent data-pane scrolling; a stable location panel above metadata on
  desktop, moved into pinned navigation at narrower widths.
- Explicit thumbnail selection, a selected-card outline and a separate Open
  action. Hover does not replace the selection. The locator uses a registered
  overview or a world-coordinate reference sketch.
- Secondary Display options and a restore action available in other views.
- Compact Play/Pause transports; reverse, loop and speed controls in Playback
  options. 3D uses coordinate rows without repeated image windows. Mesh and
  frame options appear when applicable.
- Gallery scroll, page, selection and thumbnail-size restoration. Explicit
  selections carry into animation and spatial viewing. Detail-view navigation
  cannot change the locator while leaving the enlarged image behind.

Verification:

- `node --test tests/viewer/*.test.mjs`: 16 passing tests, including 13 model
  checks and three browser acceptance tests.
- The interface browser check covers explicit keyboard selection, hover
  stability, sequence jumps, gallery/detail restoration, Gallery-to-Animate
  continuity, pinned location at 1500/1100/900/600 px, compact 3D controls,
  hidden-data recovery and unavailable-mode explanations.
- Viewer HTTP host checks: 5 passed. The Python server and metadata producer
  interfaces were not changed for this interface revision.
- Wheel build, packaged location module, release scan and diff whitespace check
  passed. Local synthetic-demo screenshots were inspected at desktop and narrow
  widths.

The earlier complete host-suite result remains in
`verification/2026-11-05-artifact-viewer.md`; it was not rerun for these browser
interface changes.

## Folder switching correction

The folder picker previously shared the additive file-import path, retaining the
old collection and its selection. Open folder now replaces the session after
reading the new selection, releases old blob URLs and resets the filter,
selection, gallery position and playback. Add files and drops remain additive;
an empty selection leaves the session intact.

A Chromium regression check reproduced the old behaviour (eight retained files
instead of four). It now passes for consecutive folders with identical names and
filenames, replacement of an open image, updated metadata on reopening the same
folder, blob URL release, additive files and empty picker selections.

Fresh verification: all 17 viewer JavaScript/model/browser checks and all five
viewer HTTP host checks pass. The full host suite was not rerun for this change.
