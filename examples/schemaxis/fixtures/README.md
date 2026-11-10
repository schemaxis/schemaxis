# Native acceptance fixtures

`blender-cube.blend` is a self-contained Schemaxis scene produced from
[`blender-admission.json`](../blender-admission.json) by the primary Blender route
on Blender 5.2.2. It contains the analytic side-length-2 cube, declared material,
camera and trusted Schemaxis node/visibility metadata. No external libraries or
unpacked images are required. Its publication was independently verified and
reopened before being copied here. This fixture is input data, not executable code;
the saved-scene runner disables automatic scripts.

To regenerate, run the JSON example into a fresh directory using the configured
Blender runtime, verify it, then copy its single scene publication here. Review
changed geometry and native version before replacing the fixture. Source-bound
qualification includes these exact bytes, so replacement invalidates the saved-scene
receipt. Do not regenerate solely to silence a stale qualification check.

`calc/typed-parts.csv` is the canonical typed CSV for the Calc `readTypedCSV` example
([`calc-typed-csv.json`](../calc-typed-csv.json)): quoted text, a leading-zero ID, formula-looking
notes and the reserved `\N` null token. Its bytes are the typed handoff the declared-row baseline
publishes, so a host test fails if either drifts. Source-bound qualification includes these bytes.

`calc/sqlite-regions.json` and `calc/sqlite-lines.json` are SQLite table sources for
[`calc-sqlite-typed-workflow.json`](../calc-sqlite-typed-workflow.json), a producer workflow rather
than a standalone operation: SQLite summarises counts and totals by a label (a leading-zero ID,
formula-looking and sign-leading text, a NULL label and a group whose total is NULL), and Calc reads
the resulting `summary.csv` file artifact as a typed CSV. Replace the `/replace/with/` paths with
absolute paths. SQLite text is printable ASCII, so these fixtures carry no Unicode.
