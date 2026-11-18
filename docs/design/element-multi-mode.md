# Element multi-mode and meaningful names

Copyright (C) 2026 David L. F. Gaden.

## Purpose and delivered scope

Multi-mode is an **authoring transaction containing several ordinary elements**.
It is not a new runtime node, sweep, implicit loop, or native group. A user opens
an element's settings and chooses **Switch to multi-mode**. Each row
has its own Name and selection. The same window can restore starting settings to
selected rows and combine selected new rows into one selection.

ParaView `extractBlock` is the reference implementation. Studio projects one
shared framework for compact rows, suggested Names and optional Batch actions.
The adaptor coverage inventory records enabled operations and applicability.
Runtime documents retain their ordinary node and input contracts.

For an OpenFOAM reader loading all regions, create extracts for `internalMesh`,
`WT_wall_XP`, `WT_wall_XM` and `Inlet`. They remain independently connectable,
colourable, inspectable and publishable. An extract selecting several blocks is
still **one** element: a selector list does not imply one output per item.

## Audit rubric: classify every operation before enabling it

Start from the registered declarations and generated Add catalogue for every
supported route, including native/generated operations and document-level items.
Produce a complete inventory with one row per operation: route, operation,
source declaration/schema, classification, evidence, proposed variable fields,
shared fields, naming policy, validation and native-test needs. Reconcile the
inventory count with discovery; explicitly list missing or ambiguous entries.

Use these classifications:

| Classification | Decision and evidence required |
| --- | --- |
| Independent siblings | Suitable when several ordinary elements independently consume the same input/context and differ in meaningful selectors or configuration. State what each output means. |
| Conditional | Suitable only with a specific mode, input kind or prerequisite. Declare and test that gate before enabling. |
| Collection within one element | A list is intrinsically one operation: mesh coordinates, an ordered animation, a material layout, connection list or vector components. Do not split it merely because it is a list. A separate explicit sibling mode may still be useful if justified. |
| Sequential/stateful | Commands mutate shared state, depend on previous steps or consume resources. Do not offer parallel sibling authoring unless ordering and ownership are preserved and explained. |
| Singleton/global | Document-wide time, render settings, output directories or a unique environment. Ordinary per-element duplication has no meaning. |
| Side-effect/output | Independent writes may qualify, but destinations, overwrite rules, order and resource conflicts require explicit collision checks and native acceptance. Never copy output paths blindly. |
| Insufficient evidence | Record the exact missing semantics or test. Leave disabled pending evidence; do not call it unsupported. |

Suitability is independent of naming. A singleton or sequential operation can
still benefit from a name derived from its field, file, plane, operation target,
material or destination. Assess naming for **every** node, including nodes that
will never have multi-mode. Prefer a few useful, stable identifying values to a
serialization of all settings. Avoid secrets, absolute paths and long expressions.
Keep existing operation explanations, units, default meanings and pitfalls.

Subset selection is a third, independent audit dimension. For every operation
and every relevant field, identify whether a user chooses from an available
superset, even if that operation cannot use multi-mode. Record the source,
completeness and ordering of choices, empty/default/All behaviour, patterns,
exclusions and ambiguity of leaf names. Follow the `extractBlock` reference:
Select All/Deselect All, filtered Select shown/Deselect shown, toggled names,
Shift-click ranges, Ctrl/Cmd-click toggles and mouse box selection (Ctrl/Cmd-drag
toggles). Where declarations provide meaningful sections, consider section
Select/Deselect or +/− actions as well. Do not infer scientific groups from names.
Keep unshown selections and dynamic patterns, explain any explicit snapshot,
and test ordinary settings and each applicable multi-mode surface. Record gaps in the adaptor coverage inventory.

## Shared declaration and extension contract

Studio's adaptor-owned `guidance.json` operation record accepts `authoring`:

```json
{
  "instanceFields": [
    {"path": "/options/selectors", "label": "Blocks", "style": "lastSegment"}
  ],
  "naming": {},
  "multiMode": {
    "batchPath": "/options/selectors",
    "rationale": "Independent extracts share an input while selecting their own blocks."
  }
}
```

Either policy can be supplied independently. The catalogue checks the
declared paths against the node schema and projects the policies for Studio.
Existing one-field policies continue to work. The frontend uses the same
control as the full settings form for each declared row field. An instance field
can identify an option or an upstream input. Other inputs and options are
inherited from the captured settings.

Naming combines literal values in field order. A field can use the last segment
of a slash-separated selector or the count of entries in a list. A record field
can select one declared member property for the Name while rendering the whole
record in Settings. The prefix defaults to the operation.
Expressions use the ordinary generated fallback instead of being evaluated.
Batch acts on a single declared list. Split and fan-out copy other settings.
Grouping requires those settings and inputs to agree.

An adaptor can require validation of the complete candidate through the existing
host planner before Apply. FreeCAD uses this for Body ownership. HDF5 uses it
for the object and link namespace. Blender uses it for bindings, tracks and
other settings where a row can affect an existing owner. Inside a workflow the
planner checks the candidate in its authored workflow scope.

Nested records that have no separate Name can expose their own distinguishing
settings as compact rows. HDF5 object rows edit paths and Blender material
binding rows edit the object and material. A nested policy can limit multi-mode
to a document setting or a member kind, such as Blender cloth caches.

## Settings, selection and grouping

Saved node Names stay fixed in Studio Settings and multi-mode to preserve
references. Users can choose the Name before adding an instance.

The dialog begins in **Single instance** mode. **Switch to multi-mode** captures
its complete settings once and opens an exclusive instance view: the ordinary
form, duplicated guidance and final-value navigation leave the layout. The title
identifies **Multi-mode**. A compact fixed toolbar holds **Add instance** and
**Batch actions**; only the instance list scrolls, while outer Apply/Cancel remain
visible. There is no silent switch back that discards rows.

The captured starting settings are immutable for this dialog. When editing an
existing element, its first row retains the original Name and references.
**Properties…** changes only the chosen row; later additions and reset actions
continue to use the captured starting settings. The batch panel contains its own
selection editor, seeded from the initial selection, with available names for the
starting input. It does not expose a second ordinary settings form.

- **Add instance** copies captured starting settings and inputs into a new, expanded
  instance with an empty selection. Available choices for that same input remain
  available; selection begins independently. It captures current edits, collapses
  earlier instance editors and focuses the new editor without scrolling away its
  predecessor. The instance list scrolls to the preceding collapsed summary, with
  the new expanded instance directly beneath it. This also applies after many
  additions or when the previously open editor was an older row.
  Invalid pending text prevents adding without collapsing the current editor.
  Empty drafts are valid while editing
  and must satisfy the ordinary schema when the outer dialog applies.
- **One instance per selected item** creates one ordinary instance for each unique
  exact entry in the batch selection. A fresh, unedited starter row is replaced:
  four selections produce four instances, with no extra combined instance. If the
  starter had an explicit Name before activation, the first child retains it.
  Existing rows and rows edited after activation are retained, including a row
  whose only edit was its Name. Closing its expanded header also completes the starter and
  protects it from replacement. If the selection requests an instance whose
  selection, inputs and settings already match a row, the action reports the
  conflict and the draft rows stay as they were. Changing the batch selection
  preserves earlier instances and edited groups. Patterns and
  exclusions cannot be split without explicit, safely enumerated choices.
- Each instance header is a keyboard-accessible button showing its Name and
  complete selected group. Clicking it, or pressing Enter/Space while focused,
  opens or closes quick settings. The expanded header is highlighted. Name and
  selection edits update the summary immediately; no per-instance Apply or Done
  action is needed. Quick settings put available-name chips immediately after
  Name; **Selectors and patterns** reveals exact-entry and pattern editing.
  Selecting more items never auto-collapses the editor. Folding
  preserves selection controls and inspected choices. An empty starter opens
  expanded, shows “No blocks selected” (using the declared field label), and can
  be populated immediately. Failed activation leaves the action recoverable.
- **Properties…** opens the ordinary settings editor for that instance alone.
  Its changes are staged locally; cancelling it leaves the instance unchanged.
  Existing identity and explicit Name ownership survive. **Delete** requires
  confirmation before removing a new instance from the draft. The original
  referenced instance cannot be deleted here.
- Split, group, selected-item creation and reset actions live in the secondary
  **Batch actions** section. Opening it reveals the instance-selection checkboxes;
  closing it hides those checkboxes while preserving their selection. They remain
  explicit operations; the quick editor
  does not require them for creating or editing ordinary instances.
- **Split selected rows** replaces selected new rows with one row per exact entry.
  A manually entered Name remains on the first resulting row. It refuses the
  original existing row, patterns and exclusions. This avoids an unwanted combined
  element when starting a new batch from several selections.
- Row checkboxes select the targets of **Use starting settings for selected instances**. That
  action replaces other configuration, including inputs, from the immutable starting snapshot;
  each row keeps its Name and row selection. Unselected rows are unchanged.
- Each row uses the same selection editor as a single element: exact names,
  complete hierarchy paths, regular expressions and exclusions remain explicit.
  A pattern is one selector expression, never an implicit sibling generator.
  Clicking an available-name chip again deselects it. Exact block selections are
  removed directly; pattern-selected blocks receive an exact-name exclusion so
  the dynamic pattern survives. Reader All becomes the currently available names
  except the clicked name. Reader patterns have no exclusion representation, so
  affected matches become explicit names; the control explains this snapshot.
  An empty selection highlights no names; exclusion-only block selections retain
  the selector language's implicit-all meaning.
- **Group selected rows** unions exact entries into the first selected new row,
  in order, without duplicates. Other settings must be identical. Divergent
  settings, expressions or exclusions refuse grouping with an explanation.
- The original row cannot be removed or included in Group selected rows in this
  phase. Its selection can be edited directly; it can also receive
  explicitly restored starting settings. New rows can be removed freely.
  Saved Names are fixed in both quick rows and their Properties windows, even
  without downstream references. Explain this as an identity-preservation rule,
  not as a claim that a reference search found a consumer. Ordinary single-instance
  forms permit renaming but do not update references automatically.

For duplicate leaf names use full hierarchy paths (`/Root/A/wall` and
`/Root/B/wall`). Grouping preserves those paths. The existing case-name picker
shows convenient leaf names; it does not prove that a leaf is unambiguous or
that every region was loaded. Inspection of the actual pipeline input remains
the authority for block availability. A selector matching nothing can yield an
empty native result; an authored valid selector is not evidence of nonempty data.
**Ask the application** inspects the row's own selected input. Native choices
stay local and survive unrelated shared-header refreshes. Changing the input
clears the former input's choices or restores choices already inspected for the
new input. Instances sharing an input reuse its loaded names; instances on other
inputs keep their own choices. Late replies never populate the wrong input.

After Apply the rows remain ordinary nodes. Studio remembers explicit batch
membership and starting settings separately in browser-local authoring metadata,
scoped to the document and workflow operation. Selecting a known member in Overview
and choosing **Edit settings…** reopens the surviving members of that batch
directly in multi-mode. Deleted instances do not appear in the table.
Existing members keep their Names and document positions; new members append.
Downstream references are preserved, and one Undo restores a batch edit.

Membership survives page reloads in the same Studio browser origin. It is not
written into exported input JSON/YAML and does not transfer between browsers or
Studio origins. Imported or older untracked nodes open their own full settings
window and can enter multi-mode to create an explicitly remembered batch. Never
infer membership from matching types, options or name prefixes. Missing members
are omitted, including members renamed outside the batch; their original identities
stay in the authoring record so Undo can restore membership even after a batch edit.
Ambiguous or differently typed identities still invalidate a recorded membership.
A single surviving member can reopen its batch and add new instances.

The quick-row names panel reserves its height for the choices themselves. Headings,
filtering, help and bulk-selection controls sit above that viewport, which grows
with the screen height. Longer lists scroll within it, and the enclosing instance
list scrolls independently while the dialog toolbar and Apply/Cancel remain visible.

## Names and identity

Name is the editable instance name used in references. Configuration suggestions
apply to new elements in both single-mode and multi-mode. For example:
`["//internalMesh"]` suggests `extractBlock_internalMesh`, and a group can suggest
`extractBlock_WT_wall_XP_WT_wall_XM`. A suggestion is sanitized and bounded before
a deterministic `_2`, `_3`, … collision suffix is assigned in row order.

An explicit input event in Name transfers ownership to the user even if the
entered text equals the previous suggestion. Later configuration changes must
not overwrite it. Opening an existing element always treats its name as owned;
never infer ownership from a type-plus-number spelling. User names that collide
are refused rather than silently rewritten. New automatically named rows can
be regenerated as their selection changes. No name-policy state needs persistence:
after saving, every authored name is treated as owned on reopen.

Reader naming uses the parent folder and marker file stem, suppressing repeated
identical parts: `004_031_9d/case.foam` becomes `004_031_9d_case`, while
`004_031_9d/004_031_9d.foam` becomes `004_031_9d`. Follow the selected adaptor's
identity schema; naming must not silently introduce an identifier rejected by
its references. This does not imply a change to variable/expression identifiers. Numeric instance
names in expressions use quoted references, for example
``extents(`004_031_9d_case`).mid`` (the instance name is enclosed in backticks).

## Validation, atomicity and reference stability

The dialog works on local snapshots. Cancel, Escape and closing the dialog write
nothing. Apply checks that the document did not change while the dialog was open,
then validates every row against the same schema as a single node. Expressions
use the existing host checker at their final destination. Generated names are
unique across existing identities and the batch. Explicit collisions and invalid
names are shown before any document edit. Unfinished required fields retain the
existing explicit fill-marker workflow; no plausible native values are invented.
Final values refer to the actual instances. An unused, unfinished starting selection
does not block saving completed instances.

For an existing node, the first row replaces it in place with its original ID;
new rows append in order. Downstream connections, publications and expressions
that refer to the original keep referring to it. No broad string replacement or
implicit rewiring occurs. Inputs are copied as references, including port objects.
The complete change is one editor document replacement, giving one Undo and Redo
step. Workflow variable metadata is staged and committed through the same existing
transaction as node edits. JSON/YAML round-trips contain only ordinary nodes.

Future bulk editing of several existing nodes must additionally protect external
references when deleting, grouping or renaming members. A name change needs the
existing reference-aware rename machinery or explicit refusal; never replace
arbitrary matching text in options, file paths or expressions.

## Required verification for each adaptor rollout

1. Verify metadata validation, catalogue projection, operation inventory counts
   and absence of native imports during discovery. Test naming independently of
   multi-mode, including missing/literal/expression values and collisions.
2. Exercise Add and Edit in a real browser: selecting the original, entering
   multi-mode, named rows, selected-only settings, grouping, mixed settings,
   explicit user names, invalid rows, collisions, stale documents and cancel.
3. Verify one Undo/Redo step, reopening saved data, ordinary downstream references
   and JSON/YAML/workflow nesting. Verify existing names are not silently changed.
4. Run a bounded native example for the enabled semantics. Inspect output names,
   hierarchy, nonempty data and independent outputs; a successful process alone
   is insufficient. Keep serial evidence distinct from MPI coverage.
5. Record commands, scope and real limitations in the change report. Missing native
   runtime or input data is a qualification gap, not a successful native test.

The reference tests are `element-authoring.test.mjs`,
`multi-mode.browser.test.mjs` and `test_studio_element_authoring.py`. Existing
reader and pipeline authoring tests remain regression coverage. Future rollout,
portable batch metadata, reference-aware removal of saved batch members,
compound varying fields, automatic pattern fan-out
and destination-aware writer batches are deliberately outside this first phase.

## Saved Names

Name suggestions use the instance's own settings and data, and yield to the
first user edit. Users choose the Name before they add an instance. A saved
node Name is fixed in ordinary Settings, multi-mode rows and Properties to
preserve references. Existing checked rename APIs retain their scoped support.

## Reuse the settings that distinguish an instance

Declare the ordered settings that distinguish an instance once in adaptor
guidance. Use their values to suggest a Name and use their existing schema
controls in compact multi-mode rows. New rows inherit the remaining settings
and inputs from the captured starting instance. Share the field declaration
within an operation family when its field semantics match. A family can still
record a naming formatter, a row-specific override or a reason multi-mode
does not apply.

An operation can declare up to four ordered instance fields. Operations
without a batch path can still add and edit several compact rows. The
`extractBlock` reference varies Blocks. Its assembly stays fixed.

ParaView Threshold varies the lower and upper bounds while inheriting the
starting input and array. It offers compact rows without Batch. Point and cell
array subset controls on ParaView conversion and Pass Arrays filters load exact
names from the selected input's reported association. Users can enter an exact
name manually and retain selections that the current inspection omits.

Studio Settings uses the shared subset control for unique arrays of literal
schema-enumerated strings. These choices come from the declaration. Selecting
shown items preserves selections outside the current filter.

Compact rows also cover independent primitive sources in ParaView, Blender,
FreeCAD and Godot, plus representative Octave and QGIS operations.
An authored operation selector or a schema branch that occupies one property
has no sibling slot. An output writer needs a separate publication contract
for Batch because it owns a destination.

The generated ParaView Extract Block picker lists literal full paths in the
selected assembly, so matching leaf labels remain distinct. Its compact rows
vary the paths and inherit the starting assembly. Octave output selection
lists declared table nodes and retains their authored output order.

Generated ParaView data readers get compact source rows when their declaration
has one file constructor and no inputs. Name suggestions use file basenames.
Reader fields backed by a native array-selection domain offer its available
names, including disabled names. This is separate from the arrays in the
reader's output. It does not inspect a writer's managed readback file before
the file has been published. Writer loss acknowledgements are explicit choices
from the comparison contract.

Generated ParaView filters with typed required data ports can use those ports as
compact row fields. Explicit adaptor guidance takes precedence when a smaller
set of options better distinguishes instances. Named inputs on different output
ports remain distinct. Multi-input fields retain the order in which inputs were
chosen.

File-list controls can append a subset of the files shown in the Studio browser.
Users can browse several folders before applying the selection. Selected paths
are appended in selection order and existing authored entries keep their order.
A ParaView reader therefore keeps the timeline ordering chosen for a file series.

A named member of a nested collection can use the same instance editor.
Blender uses field guidance to select the compact controls for individual
material, geometry and compositor node kinds and scene objects. **Create
sibling instances** starts from the selected member and adds draft siblings to
the owning list. The original Name and existing graph links are preserved.
Apply the enclosing settings to save the updated list.

Nested policies can also declare an applicability condition or a field that
must be unique within the collection. For example, ngspice allows sibling
components for DC and AC sweeps, and ExifTool requires each captured media entry
to have a distinct path. Both rules are checked before the enclosing edit is
applied. When two neighbouring collections share one Name namespace, such as
Blender attributes and UV maps, suggestions account for names in both.

ParaView managed writer rows select the input and accepted losses for separate
publication Names. The planner assigns each output its own path. Blender
geometry exports can use Batch to create one publication per selected object
while inheriting the format and frame.

ParaView scene rows can vary geometry, images, exports and visibility while
sharing the same pipeline. Each scene keeps its own publication Name. The
existing single-scene rule applies when a document requests an editable state
bundle. Blender and Shotcut declare at most one scene or timeline, respectively.
