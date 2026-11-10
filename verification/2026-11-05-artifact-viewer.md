# Independent artifact viewer — 2026-11-05

Implemented the standalone `schemaxis_viewer` Python package and
`schemaxis-viewer` console entry point. Runtime uses only Python's standard
library and local browser modules; no Schemaxis runtime imports or external
JavaScript dependencies. Usage and preview limits: `docs/artifact-viewer.md`.

Verified this session:

- Host suite: `PYTHONPATH=src python3 -m unittest discover -s tests/unit -q`:
  1,984 tests, successful, 33 skipped.
- Targeted current viewer HTTP tests: 5 passed, including selected-file access,
  external symlink exclusion, traversal refusal, byte ranges, CSP, changed-file
  refusal and overlapping selections.
- Current metadata and native-observation host checks: 12 and 10 passed.
- `node --test tests/viewer/*.test.mjs`: 15 passed (13 model tests and two browser
  acceptance tests). Covers gallery, XYZ, independent/synchronised selection,
  reverse playback, actual WebGL texture pixels, keyboard navigation, mesh
  preview, table search/plot, text search, narrow layout, real server/sidecar
  import, hash rejection, domain mesh registration and browser file selection
  under the server's CSP.
- Wheel built with `pip wheel --no-deps --no-build-isolation`; viewer assets and
  console entry point present. Extracted viewer-only package launches in isolated
  Python without importing Schemaxis.
- Release gate, including new viewer source/tests/guide: zero reported hits.
- `git diff --check`: passed.
- Local in-app browser exercised with the procedural, explicitly synthetic demo.

The native ParaView executable was not invoked. Native observation changes were
checked using host fixtures, not a new native CFD acceptance run. Existing
unrelated release-gate work was preserved.

Metadata producer updates preserve optional explicit group/sequence/overview
hints and reject invalid hints. Multiple/nonzero-offset native Slice cuts no
longer claim a single base-plane texture mapping. Existing four-corner
projection and metadata digest tests pass. Focal-plane camera images remain
separate from physically registered cuts.

Not provided: native VTK/GLTF geometry rendering, workbook calculation, a general
multidimensional data cube, inferred CFD surface masks, or saved viewing sessions.
STL/OBJ previews and CSV/TSV exports supply the supported alternatives. Unknown
spatial placement stays unavailable; filenames provide labelled sequence order
rather than physical registration. Backgrounds and annotations in image textures
retain their original pixels and do not become claimed surface measurements.
