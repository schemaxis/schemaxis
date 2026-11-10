# Filename capture rules, tag checklists and detected sequences

The viewer retains folder and Schemaxis key-value grouping and adds an editable
filename rule list. Each regex capture maps to a named Text, Number or split-tag
field under `grep.*`. Unmatched files and absent/empty captures receive no value.
Multiple rules can contribute to the same field without overwriting native
filename or checked metadata facts. Extracted values are displayed in Details.

List-valued properties now have searchable, paged checkbox lists: checked values
within a field use OR; different fields use AND. No checked values removes that
field's filter. These filters feed the existing matching selection, hierarchy,
gallery, animation and spatial selection controls.

Rules are applied atomically in a worker, with a 1.5-second batch timeout and
bounded rules/patterns/capture lists. Invalid or expensive drafts preserve the
last applied configuration and values. Collection replacement cancels stale
work; a failing rule on new input does not keep another collection's values.
Applied rules persist in browser storage for the same origin and can be exported
and explicitly imported as a versioned JSON file. Collection JSON never runs
implicitly. No viewed files are edited.

Automatic naming heuristics expose numeric/alphabetic family and token fields
under `auto.*`, scoped by source, folder and filename layout. Detected numeric
and alphabetic orders are separate playback choices, including when correlated.
Numeric values respect zero padding and alphabetic order follows A…Z, AA… .
At most four changing columns are inferred per filename; explicit rules handle
other conventions. New-format output ordinals and declared metadata sequences
are preserved, and inferred orders establish no physical placement or units.

The test folder retains 51 root media payloads with Schemaxis names. Added
`folders/alpha/icons`, `folders/beta/icons`, and `legacy` numeric/alphabetic,
slice and tag examples use procedural 16×16 PNGs. `model.png` and `error.log`
exercise nonmatches. `legacy/filename-rules.examples.json` contains three sample
rules, including independent code/index and tag extraction from the same names.
The generator reproduces all media/metadata bytes. No solver/native application
was run; these are naming and viewer fixtures.

Checks performed:

- JavaScript viewer and Studio Results suite: 45 passed, two optional external
  fixture tests skipped. Includes nine rule/model/browser checks for capture
  typing, literal tag splitting, intersections, folder/sequence coexistence,
  alphabetic playback labels, nonmatches, rule persistence/import/export and
  invalid/expensive regex recovery without blocking the UI.
- Portable-package host check passes with isolated Python and no Schemaxis
  imports. Packaged Chromium acceptance exercises both filename and text workers
  through the actual loopback server's content security policy.
- Release gate: zero hits. `git diff --check`: clean.
- Screenshots, logs and a reproducibly regenerated fixture are retained under
  `evidence/viewer-filename-rules`; the ZIP is rebuilt under ignored `dist`.

```sh
node --test --test-concurrency=1 tests/viewer/*.test.mjs src/schemaxis/studio_ui/tests/results.browser.test.mjs
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_viewer_portable.py -q
python3 tools/release_gate.py
```
