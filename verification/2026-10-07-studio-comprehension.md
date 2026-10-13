# Studio compact authoring and comprehension — 2026-10-07

Both authoring editors now offer width-aware Compact and fully indented Expand
through the shared undoable formatting transaction. The chosen width is 40–240
columns; indivisible JSON strings may exceed it. Values and pointer navigation
are preserved, and malformed input is not reformatted.

A collapsible comprehension reference follows the draft, describes numbered
nodes, named results, input connections and scalar options, and navigates to
source. It includes nested documents and retains the last readable reference
while syntax is incomplete. Placeholder IDs retain readable fill labels.

Workbench adds an explicit Preview with live data action using the existing Run
path. Existing native geometry and verified image/table/text outputs remain in
the viewer tabs. Labels identify previews from earlier input after draft changes.
This does not attach to an existing ParaView desktop session or execute on each
keystroke. No detachable viewer window was added.

New checks:

- Browser-independent JavaScript suite: 160 passed.
- New real-server compact/comprehension check: passed in both authoring surfaces.
- Workbench browser regression suite: 6 passed, 1 native FreeCAD check skipped.
- Schema Editor browser regression suite: 6 passed.
- Workbench screenshot inspected for layout and readable controls.
- Packaged Help regenerated; 950 topics freshness check passed.
- git diff --check passed.

An initial broad browser run exposed the new width field's inline style under
strict CSP; this was replaced by a stylesheet class and the affected authoring
suites rerun successfully. That broad run also had an editor timing assertion
failure under parallel load; a clean full browser-suite result is not claimed.
The new browser fixture initially omitted required calculator and scene values;
these were corrected before its passing run. No new native application
qualification or Python host-suite run was performed for these UI changes.
