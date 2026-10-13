# Design verification, 2026-09-27

These checks qualify the separate interaction prototype, not the production
console or native application behaviour.

## Browser checks

Exercised in an in-app browser through computer-use automation:

- Default desktop viewport: inspected layout, source, property panel and elbow
  illustration. Adjusted layout minimums so the command drawer and status remain
  visible at the tested desktop height.
- Changed bend radius from 60 to 75 through keyboard input in Properties; source
  updated and `$document` references remained intact. Preview remained labelled
  as an earlier revision until explicitly refreshed.
- Tried picking before refreshing: rejected with a current-preview instruction.
- Refreshed, picked inlet and added a 20 mm extension. Source contained nine nodes,
  including the four expected extrude/cut/fuse nodes, with `extendedPipe` output.
- Applied the scripted assistant suggestion: radius became 80; the upstream
  selection became stale. Undo restored 75. Changing the draft after creating a
  suggestion disabled its Apply button with a stale-proposal explanation.
- Entered invalid JSON: retained the text, displayed the parser error and disabled
  preview/export. Undo restored the last usable source.
- Switched to YAML: confirmed read-only export preview and the expected document
  values. This does not exercise YAML input parsing, which is not implemented.
- Searched the adaptor catalogue for `1D`: returned the registered GNU Octave
  metadata. No proposed circuit-design adaptor was listed.
- Walked through all three setup steps; completion explicitly reported no saved
  preferences or installations. Download permission defaults to unchecked.
- Changed the licensing preference to freely available; the design explicitly
  reported that licence metadata is not connected and did not imply filtered,
  verified licensing results.
- Ran `set document dimensions` through the command drawer: bend radius became
  70 in both the source and Properties, with an earlier-revision preview label.
- Searched the operation catalogue for `box`, inspected its declared defaults and
  inserted it: source gained the box node and selected it as output.
- Inspected the 390 × 844 layout: navigation becomes compact and the inspector
  follows the document vertically; source/model remain available.

## Source and host checks

- `node --check docs/design/authoring-workspace/workspace.js` passed.
- Compared the catalogue fixture with the current adaptor registry, FreeCAD
  declarations and original pipe input: matched.
- Planned the prototype's base elbow through the real host FreeCAD planner: passed.
- Evaluated the prototype's actual pure YAML serializer with the elbow document,
  then independently parsed the result using the already available Python YAML
  library: the result equalled the original authored document. No dependency was
  added to Schemaxis.
- Whitespace checks passed for the new design files.

No native application, real AI backend, installer download, external account or
production HTTP authoring endpoint was exercised. The prototype's draft checker
is intentionally a limited subset. The production unit suite was not rerun for
these isolated design files; no production source was modified.
