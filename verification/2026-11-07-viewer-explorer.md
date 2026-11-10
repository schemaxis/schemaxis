# Independent viewer: grouped collections and portable distribution

Implemented nested property hierarchies (up to three levels), overlapping list
membership, branch selection and persistent branch expansion. Checked companion
properties support ordinary filenames as well as descriptive filename hints.
Matching selection intersects the folder, type, property and name filters;
session-wide select/deselect remains available.

Any selected image collection can form a photo series in natural filename order,
using the existing transport controls. Spatial mode can show all selected
registered planes in a compatible source/frame/unit context with the domain mesh.
No physical placement is inferred from photo order or descriptive properties.

Read-only text supports highlighted Find with wrapping occurrence navigation and
whole-word, case and regex options. Grep exposes numbered/named capture columns,
column selection and CSV export. All searches run in a worker with a time and
result bound. CSV/TSV tables and plots remain available; XLSX/ODS have no native
workbook engine.

`examples/viewer-test` contains synthetic registered slices, photos, time frames,
WebM, STL/OBJ, a log and CSV/TSV tables. The fixture was subsequently corrected
to use the actual Schemaxis filename serializer in a single flat directory,
with grouping labels supplied by filename properties. See
`2026-11-07-viewer-filename-groups.md` for the corrected fixture's checks.
No solver was run.

`tools/package_viewer.py` produces a portable ZIP containing only the independent
viewer Python package, web assets, launchers, documentation, notices and an
explicit optional sample folder. It contains no Schemaxis runtime modules or
user history. Extraction and `python3 launch.py` (Windows: `start-viewer.cmd`)
require Python 3.10+ and a current browser. Recipients run their own local server;
this does not provide hosted collaboration. Windows/macOS launchers are supplied
but were not executed on those platforms.

## Checks

- Viewer and Studio Results JavaScript/browser suite: 35 passed, two optional
  external-fixture tests skipped. Covers grouping, matching selection, branch
  state, photo stepping, registered plane selection, video decoding, table
  pagination/plots, text navigation/captures/export and invalid-regex recovery.
- Portable ZIP Chromium acceptance: included above. Builds and extracts the ZIP,
  runs it under isolated Python (`-I -S`) with no Schemaxis source path or site
  packages, then reads checked sample planes and executes a search worker through
  the actual loopback server and its strict content security policy.
- Python viewer transport and portable-package checks: nine passed. Includes
  explicit-file boundaries, stale snapshots, ranges, origin checks and package
  operation without importing Schemaxis.
- Release gate: zero hits. `git diff --check`: clean.
- The full repository host suite was attempted but its process ended with
  SIGTERM (exit 143) before a test summary. No complete host-suite pass is claimed.

Commands and bulk logs/screenshots are retained in `evidence/viewer-explorer`.
The portable ZIP is generated under `dist`; both directories are ignored.

```sh
node --test --test-concurrency=1 tests/viewer/*.test.mjs src/schemaxis/studio_ui/tests/results.browser.test.mjs
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_artifact_viewer.py -q
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_viewer_portable.py -q
python3 tools/release_gate.py
python3 tools/package_viewer.py dist/artifact-viewer.zip --sample examples/viewer-test
```
