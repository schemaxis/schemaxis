# Schemaxis Studio guide

Studio is the graphical editor for declared application workflows. The same JSON
is used by the GUI, CLI and agents. Start with one application and one useful
publication; inspect and validate it before adding a study or another application.

## Find the right help

Help searches operation names, option names, descriptions, examples and shared
`$` syntax. Select a category to narrow the results. Application operation
references list the declared contract; application guides explain how to combine
operations. Operation reference opens directly in the configuration window. Its
embedded view omits an introductory paragraph already shown above the form; the
complete topic remains available in Help. About this operation retains additional
guidance without repeating the main explanation. Suggest a correction copies the
guidance context for review without submitting changes.

The `?` beside an operation or field opens its conceptual help: what the value
means and how it changes the result, units and conventions, what happens when it
is omitted, dependencies on other settings, examples and common mistakes. It also
shows the native operation and property that Schemaxis sets, and the sources the
explanation was written from. **Schema details** lists the allowed values,
bounds and defaults that validation actually enforces.

- *Conceptual guidance* is explanation written for that field from the adaptor's
  implementation and the application's official documentation.
- *From adaptor references* is text carried over from the application's own
  documentation, such as ParaView's property descriptions.
- When omitted, a field keeps the default stated in its help. For many generated
  ParaView operations Schemaxis assigns nothing, so ParaView's own initial value
  applies; ParaView can derive some of these from the input data, so set values
  explicitly when the result depends on them.

Numeric fields accept a number, a named value or an expression, such as
`model.mid` or `0.002 * model.deltaX`. Studio keeps expressions as `$expr`
markers; it asks the host to check their meaning and destination. Other
**Runtime value** forms (`$sweep`, `$time`, `$observe`, `$calc`, …) remain
available; see the [$ reference](dollar-reference.md). If an explanation is wrong or unclear,
open **Suggest a correction → Copy help request** and send the copied record
with your correction; it identifies the adaptor, route and schema address.

- [Getting started](getting-started.md): installation and the first workflow.
- [User guide](user-guide.md): applications, planning, execution and publications.
- [JSON input](json-input.md): the document structure.
- [Shared authoring](shared-authoring.md) and [$ reference](dollar-reference.md): expressions, references, composition and studies.
- [Workflow authoring](workflow-authoring.md) and [Workflow design](workflow-design.md): connect application stages and expose parameters.
- [Typed inspection](typed-inspection.md): inspect data before selecting fields or consuming artifacts.
- [Installation](installation.md) and [Updates](updates.md): application configuration and compatibility.

## Workbench sidebars and element settings

The left sidebar offers **Overview** and **Templates**. Its mode buttons stay
visible while the content scrolls. Overview follows the selected element, lists
pipeline connections and provides read-only explanations from its declared schema.
Click a pipeline element to highlight its entire source and expand its details;
click its title again to deselect and collapse it. Text-editor cursor selection
continues to update Overview. Templates keeps document sections, templates and
snippets available in the same sidebar.

Each expanded element encloses its title and properties in one outlined box.
**Edit**, **Duplicate** and **Delete** sit just below its title. The title and actions
stick to the top while its properties scroll, then leave with the end of that
element. Each title click immediately toggles selection; rapid clicks do not open
settings. **Edit** and **Edit settings…** above the input reopen the full
configuration window (including a remembered multi-mode batch).
Edit is enabled when the selection has a settings form. Duplicate and Delete use
the existing reference-aware draft edits; Undo restores them. Removing dependent
nodes or publication references asks for confirmation.

The right sidebar holds **Case data**: regions, arrays, times and available
observations. Its heading, refresh action and search field stay fixed while the
names scroll. Region and array names use natural alphabetical order (for example,
`wall2` before `wall10`); time values retain their supplied order. Click a name to insert it at a compatible cursor position or copy
it. Each section has **Copy** and **Export CSV**. Copy appends all values to the
list at the cursor, skipping existing values, in one undoable edit; at other
cursor positions it copies a JSON list (also valid YAML). **Copy all** copies a
JSON object with the named sections. CSV exports use Section and Value columns.
Copy/export always include the entire section or all sections, even when the
search hides some names. Clipboard failures are reported in the panel.
Saved inspection references remain available below the case information.

Matching sidebar icons flank the view row: the left icon toggles the left sidebar;
the right icon toggles Case data, beside **Controls**. Both panel choices are
remembered independently. The row contains Input, Schema, 3D, Image, Table and Text
views without file or diagnostic summaries. The central **Schema** tab retains
the selected schema browser; **Text** displays relevant text artifacts.

## Start, open and recent work

**Start** has a card for each authoring application: Workflow Designer, Adaptor
Workbench and Schema Editor. Each offers **New…**, **Open…** for a saved file
on disk, and its most recent documents with the file each was saved to.
**All…** lists every document of that kind in the workspace. Opening a file
adds it to the workspace; opening it again shows the same document. The number
of recent items is a setting, and zero hides the lists.

## Build a ParaView input

Open a ParaView Workbench, or choose a ParaView document in Schema Editor.
Both editors share the Add catalogue. Start with a supplied template if it matches
your task; otherwise add a reader or generated source, then filters and outputs.

1. Choose **Add Input** for a file reader or **Add Source** for generated data.
2. Search by the declared identifier or native operation name. The complete
   declared catalogue is available, including operations without native receipts.
3. Select the operation to open its configuration window. Studio assigns a unique
   name automatically. Expand **Name** only if you want to rename it.
   Reader file paths must point to your data; a demonstration path is not a file.
4. Required fields are visible. Expand **Optional settings** to see every declared
   option, including those normally left to defaults. Enable only settings you
   want to author; omitted options retain the adaptor/native behaviour.
5. Choose **Add operation** to insert configured values, or **Insert required
   placeholders** to insert only the required skeleton. Empty required fields
   become `$fill` markers. Cycle through them with the existing fill controls.
6. Select an upstream object in **Pipeline**, then choose **Add Filter**. The
   first required input defaults to that compatible object, or the preceding
   compatible object when none is selected. Use the dropdown or **Browse pipeline…**
   to choose another input. Additional ports remain explicit; multiple-input ports
   support multiple selections. ParaView references can select an output port under
   **Advanced**. Reopen **Edit settings…** to change these inputs later.
7. Add a **Scene** using **Presentation & controls**. Its name is automatic; select
   geometry or visible nodes. Use **Appearance** for colours, fields, representation,
   opacity, lighting, textures and scalar bars.
8. Choose **Add Output** to add an image or writer export to a selected scene.
   Images need camera(s). Names are automatic and writer sources use the selected
   compatible object;
   inspect their optional verification, extension and readback settings.
9. Validate, plan and inspect the source data. Fix missing references, unsuitable
   field associations or native domains. Run a small publication and examine its
   verification result before expanding the workflow.

[ParaView guide](paraview-guide.md), [complete operation reference](paraview-operation-reference.md)
and [settings reference](paraview-settings-reference.md) describe the contract in detail.

For **Extract Block**, choose **Switch to multi-mode** in the Add/Edit window.
The title changes from **Single instance** to **Multi-mode**, replacing the normal
form with the instance list. The compact toolbar and Apply/Cancel footer stay
visible while the instances scroll.

Each instance header shows its Name and selected blocks. Click it to open or close
quick settings; the open header is highlighted. Name and selection edits update
the summary immediately. Available-name chips appear below Name; click a chip
again to deselect it. Expand **Selectors and patterns** for exact-entry and pattern
editing. Starting with no blocks selected opens an editable empty instance.
Available names sort naturally. Adding another instance folds the open editors
and moves focus to the new one. The preceding instance stays visible as a collapsed
row above the new editor, making the addition clear; older instances remain above
it in the scrollable list.

**Add instance** opens an empty selection with the settings and input captured
when multi-mode began. **Properties…** changes only that instance, then returns to
multi-mode; Cancel leaves it unchanged. Editing one instance never changes the
defaults of later additions. **Delete** asks for confirmation.

**Batch actions** has a separate selection editor. Choose blocks there and use
**One instance per selected item**: four exact selections create four extracts
from a fresh starter. Existing instances and edited groups are kept; matching
instances are skipped. Patterns and exclusions remain explicit groups.
Opening Batch actions reveals instance-selection checkboxes. Use **Split selected
rows**, **Group selected rows**, or **Use starting settings for selected instances**
for those checked instances. Resetting settings preserves each Name and selection.
Apply creates ordinary elements together, with one Undo/Redo step; Cancel leaves
the input unchanged.

Studio remembers batches created here in this browser. Select any known member
in Overview and use **Edit** to reopen its multi-mode window. Saved members
keep their Names and references. Only surviving members of that original batch
appear; deleted instances stay out of the table, and unrelated extracts are not
added. Undoing a deletion restores the member to the remembered batch. The available
block names have their own scrolling area, separate from the headings and selection
controls. Batch membership stays outside exported input files; older or imported
untracked nodes open their individual settings window.

Saved instance Names are currently fixed in multi-mode, including its Properties
windows. This protects existing identities; it does not mean Studio found a
reference to every such Name. Ordinary single-instance settings allow a rename,
but do not rewrite references for you. The text editor also permits ID changes;
update any references when making one.

New extracts suggest names such as `extractBlock_internalMesh`. OpenFOAM readers
suggest the parent folder plus file stem: `004_031_9d/case.foam` becomes
`004_031_9d_case`, while `004_031_9d/004_031_9d.foam` becomes `004_031_9d`.
Typing your own Name preserves it as other settings change. Existing elements
keep their names when reopened.

## Browse without knowing an operation name

**Add anything…** searches the whole catalogue. The groups separate file inputs,
generated sources, filters, outputs, and presentation/control settings. Search
results load in bounded pages; use Show more to continue. Curated recipe buttons
remain available for multi-operation tasks such as slice sweeps.

The four pipeline groups do not cover the whole document: scenes, cameras,
appearance, sweeps, time selection, definitions, dimensions, views, settings and
publication limits belong to **Presentation & controls**. Scene/image selectors
choose an existing target. Add that target first. Adding a value at an occupied
setting uses the editor's replacement preview and undo transaction.

## Configure complex values

Configuration forms follow the schema recursively. Select an alternative for a
union, add/remove array items, and expand optional nested properties. A proxy
choice such as a clipping plane or box has its own nested options. Free-form
objects are editable as JSON; their help shows the available schema. Scalar,
vector and box controls accept expressions directly. The JSON editor also
accepts expression and analytic markers, including a camera written as one
`{"$expr":"fitCamera(bounds = model, direction = 'z+', up = 'y+')"}` value.

A displayed default is an annotation; an unchecked optional field is omitted.
An empty enabled field becomes a placeholder, including an optional field you
explicitly chose to include. An operation with an empty input can be saved as a
draft but cannot run until placeholders are filled. Cancel changes nothing.
Insertion is one undo action and does not execute a native application.

## Understand validation failures

A diagnostic shows a message, the authored JSON pointer, and line/column. For
example `/nodes/3/options/normal` addresses the normal of the fourth node. A
missing key has no text of its own, so the containing object is highlighted while
the intended address stays in the diagnostic. **Show in input** navigates to it.
Syntax errors point to the parser's character position. Problems retains explicit
validation failures; background checks remain local to the editor.

Structural validation checks JSON types, required keys, allowed options and
limits. Planning checks graph references and cross-option rules. Native execution
checks actual reader files, data arrays, proxy domains and output verification.
Passing the schema alone does not guarantee that a native operation will work.
The catalogue records unqualified operations and known gaps instead of silently
implying acceptance.

## Other applications

Each application has a declared operation reference and application guidance.
Choose its category in Help or search the application name and operation.

| Application | Guide | Operation contract |
| --- | --- | --- |
| Blender | [Media workflows](media-workflows.md) | [Operations](generated/blender-operations.md) |
| FreeCAD | [CAD and mesh](cad-and-mesh-workflows.md) | [Operations](generated/freecad-operations.md) |
| Gmsh | [Gmsh](gmsh.md) | [Operations](generated/gmsh-operations.md) |
| QGIS | [QGIS](qgis.md) | [Operations](generated/qgis-operations.md) |
| Godot | [Godot](godot.md) | [Operations](generated/godot-operations.md) |
| Aseprite | [Aseprite](aseprite.md) | [Operations](generated/aseprite-operations.md) |
| FFmpeg | [Media workflows](media-workflows.md) | [Operations](generated/ffmpeg-operations.md) |
| Octave | [Numerical analysis](numerical-analysis.md) | [Operations](generated/octave-operations.md) |
| Cantera | [Cantera](cantera.md) | [Operations](generated/cantera-operations.md) |
| ngspice | [ngspice](ngspice.md) | [Operations](generated/ngspice-operations.md) |
| Calc | [Calc workbooks](calc.md), [Numerical analysis](numerical-analysis.md) | [Operations](generated/calc-operations.md) |
| Inkscape | [Inkscape](inkscape.md) | [Operations](generated/inkscape-operations.md) |
| Shotcut | [Shotcut](shotcut.md) | [Operations](generated/shotcut-operations.md) |
| Premiere Pro | [Premiere](premiere.md) | [Operations](generated/premiere-operations.md) |
| R | [R](r.md) | [Operations](generated/r-operations.md) |
| CalculiX | [CalculiX](calculix.md) | [Operations](generated/calculix-operations.md) |

Curated templates/snippets are application-owned. Complete Add coverage currently
includes ParaView's full declared catalogue; other application authoring models
must implement the [Studio adaptor contract](studio-adaptor-contract.md) as they
are brought to the same level.

## Develop an adaptor for Studio

See the [Studio adaptor contract](studio-adaptor-contract.md),
[adaptor development](adaptor-development.md) and [adaptor readiness](adaptor-readiness.md).
A new operation needs a declaration, all configurable fields, useful Help,
insertion coverage and located diagnostics, together with meaningful host checks
and bounded native acceptance evidence.

### Compact JSON and navigation

Workbench and Schema Editor offer **Compact** and **Expand** beside the editor.
Compact places short arrays and objects on one line when they fit the chosen
line width (40–240 columns, initially 100). Longer containers retain indentation;
individual strings are never split. Expand restores fully indented JSON. Both
actions preserve values and use the editor’s undo history. Invalid JSON is left
in place so it can be corrected.

**Pipeline** opens by default at the top of the sidebar. It lists nodes, named
results, incoming connections and compact options, including XYZ vectors. Its
numbers are zero-based JSON indices: node 0 is the first node. Click a row to
highlight its entire source object and read its field explanations directly below the selected row. It follows the current draft,
includes nested workflow documents and retains its last readable list during
incomplete JSON edits. **How to read the pipeline** explains references and
expression syntax.

Select a Pipeline row to enable **Duplicate** and **Delete**. Duplicate assigns
a fresh name and retains the original object's input connections. Delete removes
the selected object. If other nodes depend on it, Studio first lists the complete
dependent set and affected scene/output references. Either action is one draft
edit: Undo restores the previous document. Nested pipeline edits stay inside
their containing document. These controls are shared by Workbench and Schema Editor.

**Document sections** replaces the old Outline. It navigates scenes, settings,
definitions, workflow components and other document-level structures. Nodes
appear only in Pipeline, so the two lists serve different purposes. **Help** is
the general operation reference; **Edit settings…** opens the selected instance configuration.

Configuration and Overview help show the native operation/property beside the
Schemaxis JSON key where a declared binding exists. For example Calculator's
**Function (equation)** maps to `Calculator.Function` and the JSON key
`expression`; **Result array name** maps to `ResultArrayName` and `result`.
Native documentation is reference material, with provenance; it does not imply
that every option has undergone scientific or native acceptance testing.

### Previewing real data and outputs

Use **Preview with live data** on the Workbench Input toolbar to validate and
execute the current draft through the configured native application. This uses
the same execution path as **Run**, including publishing the input revision; it
does not write a source file. Configure the application through Setup first.
**Preview** remains the host planning action.

Available live geometry opens in **3D** after native execution. Verified image,
table and text artifacts appear under **Verified outputs**, with **View** buttons
for supported formats. Use **Image** to inspect screenshots. The viewer toolbar
can reload an available native preview. After editing, a preview from earlier
input is labelled accordingly; execute again to refresh it. These are explicit
previews, rather than execution on every keystroke or a connection to an existing
ParaView desktop session.

### Place a Stream Tracer seed line

Stream Tracer needs two different inputs: the **flow dataset** containing a
three-component velocity field, and the **seed source** providing starting
points. A `line` source is a useful seed source. Its Resolution is the number of
intervals; it produces Resolution + 1 points. A streamline length is a distance
in dataset coordinates, not a count of line samples.

1. Load and preview the flow source first. For OpenFOAM cell velocity, add
   `cellToPoint` before tracing and select the resulting POINTS vector array.
2. Add a `line`, or select the line node in **Pipeline**. Choose **Place line
   endpoints…** in its configuration form, opened through **Edit settings…**.
3. Choose **Load preview bounds**, then select the flow dataset in **Bounds
   source**. **All displayed geometry** uses the visible preview extents, which
   can differ from the full flow dataset. Without a preview, expand **Dataset
   bounds** and enter its six limits manually.
4. Choose XY, XZ or YZ. Set the perpendicular coordinate, then click inside the
   box to place start and end. The drawing preserves the projected bounds'
   proportions. Exact XYZ entries remain editable.
5. With preview geometry available, **3D surface picking** opens a perspective
   view. Rotate the data and click its surfaces, edges or vertices to choose a
   point. The XYZ fields show the picked coordinates; this does not establish
   that the point is inside a fluid cell. For interior seeds, use a suitable 2D
   plane or adjust the coordinates.
6. Choose **Use endpoints**. Both endpoints are applied together as one editor
   change. Connect this line to Stream Tracer's seed port, choose the correct
   velocity array, integration direction and maximum length, then preview again.

The 2D box is a bounds projection, not a mesh cross-section. The selector uses an
explicit saved preview snapshot and labels unsaved draft changes. It does not
execute incomplete downstream filters or bind coordinates dynamically to future
bounds. Empty streamlines can indicate seeds outside the fluid, an absent or
incorrectly associated vector array, or integration limits unsuitable for the
dataset. Inspect these before increasing sampling density.

[Streamline placement example](../examples/studio/streamline-placement.json)
provides a self-contained generated flow, seed line and visible streamlines.

### Choosing an OpenFOAM case

In **Add Input → foam**, Studio supplies a name such as `foam1`.
Its `file` is the `.foam` marker in the case folder, rather than the mesh data
itself. **Browse…** opens the desktop's ordinary existing-file dialog on Linux
when Zenity and a desktop display are available. Select the marker and choose
**Add operation**. Studio reads bounded case headers to detect processor folders
versus serial/reconstructed layout and list regions, fields and times. It records
the detected case type and, for a document without `times`, the first available
time. Explicit reader choices and document times are preserved. This header
inspection does not start ParaView; **Ask the application** and live previews
need the configured executable.

The chooser inserts an absolute path and does not
upload, copy or create case files. You can also type the path directly. Relative
reader paths use the directory from which Studio was launched, not the JSON
file’s folder or the browser’s Downloads folder.

**Browse…** opens the desktop's own Open window when Studio runs on a desktop.
Otherwise, or when **Browse with the desktop's Open window** is off in Settings,
it opens Studio's Open window: places (Home, Workspace, recent folders), **Back**,
**Forward**, **Up** and clickable folder breadcrumbs. Type a folder and press
Enter, filter names in the current folder, show hidden files, or enable **All
file types** when a suggested extension filter hides a valid input. Click a file
to select it and **Open** (or double-click) to use it. Escape closes it while preserving
the configuration form. Selecting a file fills the path; it does not execute the
reader. Very large folders require a more specific path (2,000-entry limit).

The form shows practical descriptions next to the fields. For `caseType`, choose
the layout containing your results: processor folders for Decomposed Case, or
the main case folder for serial/reconstructed data. `regions` selects volume
and boundary mesh parts; `cellArrays` selects existing cell fields. `skipZero`
defaults to **true**, so an omitted setting skips time zero in both the header
list and the native reader. Include the setting and choose **false** to offer
time zero as well. If you already authored `times`, change it explicitly to
select the newly available time. The question-mark buttons retain technical constraints
under **Schema details**.

### Extracting blocks by name

Select the reader or composite filter in **Pipeline**, then choose
**Add Filter → extractBlock**. The name and input are already filled.
**Blocks to extract** is a list of entries, built the same way as reader
regions. An entry is a block name such as `internalMesh` (written as the
selector `//internalMesh`), a regular expression matched against block names,
or an exclusion, which removes the blocks it matches. A list holding only
exclusions starts from every block, so removing the stable parts of a case
leaves the model:

```json
"selectors": [{"exclude": "^(WT_|wheels_|procBoundary|internalMesh$)"}]
```

The names in the case are listed under the entries, without their `patch/`
prefix; click one to toggle it. **Select All** adds all loaded names, including
names hidden by the filter. **Deselect All** clears the complete selection,
including patterns, exclusions and pending entries. Filter the names and use
**Select shown** or **Deselect shown** to work on a group while retaining other
selections. Shift-click selects or deselects the visible range from the last
clicked name; Ctrl/Cmd-click also toggles individual names. Drag a box over names
to add them, or Ctrl/Cmd-drag to toggle them. Keyboard Enter/Space toggles a
focused name. These controls also appear in multi-mode quick settings and Batch
actions. Bulk additions use the loaded names, keeping existing dynamic patterns;
filtered removals add exclusions when a pattern selects the removed blocks.
They do not silently expand a pattern into separate nodes.

The line above the names reports what the whole list
selects in this case. Expressions are resolved when the input is loaded, so one
authored list serves cases whose names vary. An expression that matches nothing
is an error. A full selector path such as `/Root/boundary/walls` can also be
typed as an exact entry. Existing filters show the same list when reopened with **Edit settings…**.

**Load names** reads the case headers of the reader in this pipeline.
**Ask the application** loads the chosen input and its upstream dependencies in
a separate serial worker and lists the blocks it reports. It leaves the
displayed preview and saved document alone, and can work while downstream
filters are unfinished. It requires one explicit time/parameter state, at most
200 upstream nodes and at most 10,000 block entries. Only regions loaded by the
reader can be extracted; expand the reader's `regions` setting if a patch is
missing.

## CFD input authoring controls

Use **Add Input → foam** to choose an OpenFOAM marker with **Browse…**. The
node is named after the marker file (`coupe_AMI.foam` gives `coupe_AMI`; a
generic `case.foam` takes its folder's name) until you type a name yourself.
Relative dataset paths are resolved from Studio's launch directory.

**Save** writes the input to its file, asking where the first time. The arrow beside **Save** offers
**Save as…**, which writes a new file and makes it the one later saves go to,
and **Open…**. Saving over an existing file asks first.

The settings window for an operation has two screens, named at its top:
**Settings** and **Final values**. Final values lists whatever Settings left
open; anything left empty stays a placeholder that the editor offers to fill
after the operation is added. Enter never closes the window. Drag any window by
its title bar, and the fill window by its heading, to see the text behind it.
To reopen the window for a node that already exists, put the cursor in it and
press **Edit settings…** above the input or **Edit** below its Overview title;
**Apply changes** replaces the node as one undoable edit.
**Load names** sits beside the screen names, with **Live data preview** for a
reader, and each list of names has its own.

**Expert mode**, in Settings, folds the help text in these windows behind the
**?** buttons: one at the top for the introduction, one on each setting.

Reader regions and cell arrays are chosen as **All**, which writes
`{"select":"all"}`, or as **Named entries**. Each entry is an exact name or a
regular expression; **Add entry**, **Edit** and **Delete** manage the list, and
Enter adds the entry being typed. Typing only previews what an expression
would match; nothing joins the list until it is added. Several exact names can be added at once,
separated by commas. A mixed list is written as, for example,
`["internalMesh", {"pattern": "^patch/wheels_"}]`. Boundary region names have
the `patch/` prefix. Expressions are matched when the case is loaded; one that
matches nothing is an error. With no entries the setting is left out and the
reader's default applies.

**Load names** reads bounded case headers and never loads a native mesh. It
reports its limits for binary, collated and multi-region cases. Choosing a file
loads them automatically. Once loaded, each entry shows what it matches, and
the names can be clicked to add them. **Ask the application** asks ParaView for
advertised region/array names without updating mesh data.

The same names stay available while editing. **Case data** in the right panel lists the regions, cell arrays and times of
the open case: click a name to add it to the list under the cursor, or to copy
it when the cursor is elsewhere. The editor's suggestions offer them wherever
text is accepted. **Live Data…**, beside **Run**, opens the source checklist, including when there
is only one input. **Inspect selected node** loads or reuses that node and its
upstream dependencies and displays a bounded 3D snapshot when supported. Neither
inspection action runs downstream publications or requires unfinished downstream
nodes to validate. Live inspection still needs usable upstream inputs and one
selected state; workflow-produced files must exist before they can be inspected.
If the loaded mesh exceeds the browser display limit, inspection still supplies
bounds, counts and available names in **Case data**; Studio explains why the 3D
snapshot was omitted. Spatial **Refresh from Live Data** calculates extents from resident sources
without transferring the mesh to the browser. Both retain the native data until **Disable all Live Data**
or session exit.
Use **Inspect selected node** again to update its mesh preview after changing the draft. Inspection preserves the
input, including unfilled fields. Adding a reader uses header metadata, when
available, to record its layout and first stored time without launching ParaView.

The workbench's actions sit at the right of the window tabs, and move to their
own row in a narrow window. **Validate** checks the current draft with the host
planner. **Preview** creates a planning checkpoint for a complete input. **Run**
executes and verifies the complete input in the configured application.
**Adaptor help** opens the selected adaptor/operation reference; the title-bar
**Help** opens the general Studio guide. The native status explains whether an
executable is available and how to open Application Setup in Admin mode.
For ParaView, the configured location can be the installation root, its `bin`
directory, or the `paraview`, `pvpython` or `pvbatch` executable. Studio finds
the scripting executable in that installation for live inspection; selecting
`paraview` does not launch the desktop application as a worker.

The sidebar's header chooses **Overview** (the pipeline) or **Templates** (document
sections, templates and snippets); its close button and the sidebar button left
of the view tabs hide and restore it. Overview follows the editor cursor, including
when it is deep inside a node's options. **Edit**, **Duplicate** and **Delete**
operate on that node and scroll with its sticky title within its properties box.
**Controls**, right of the view tabs, hides the Add and editing rows
so the input takes the full height. **Snippets & templates** opens the snippet
categories. These layout choices are remembered.

Section recipe buttons insert on click. Hover/focus shows a temporary preview;
the click commits one draft edit. A template or snippet whose planned edit
replaces the whole input (or, in Schema Editor, the whole operation input under
the cursor) first opens **Replace input?** or **Replace operation input?**. It
names the item, the scope and any document-version change, lists the planned
changes in order and shows the changed text. Cancel, the close button, Escape
and a click outside leave the input, selection and Undo history unchanged.
**Replace input** commits that reviewed edit as one draft change; Undo restores
the previous input. If the input, its format, the cursor scope or the window
changes while the review is open, nothing is replaced and the item must be chosen
again. Merges and additions insert without this review. Three centre slices create one plane for each
axis; slice sweeps create arrays of planes across the data volume. **Undo** and
**Redo** use draft history (Ctrl+Z / Ctrl+Shift+Z). **Undo saved edit** and
**Redo saved edit** travel through saved workspace revisions.

Every expandable list has two small buttons left of its label. The first opens
one level, or closes the item and everything below it. The second opens
everything below a closed item, and closes an open one. The Schema view also has
expand/collapse-all, expansion depth, search, select-all and copy. **Show
Problems** on a diagnostic notification opens the bottom panel. Its close button
dismisses the popup; Problems and Log remain available. Settings can suppress
popups while retaining that history.

## Vectors and volumes in Variables & expressions

Use **Variables & expressions** for reusable named values in `dimensions`,
`definitions` and `settings`, and for declared `sweeps`. A numeric input accepts
`2`, `gap / 2` or `model.mid` as appropriate to its destination. Expressions
remain authored text inside a `$expr` marker; a computed preview never replaces
the expression with its current number. **Check expression** asks the host for
the result type and evaluation phase without launching an application. A syntax
error selects the offending text where the host supplies a location.

New variable names start empty. Editing a value allows name, group and scope
changes; explicit references and parameter targets follow the change. Moving a
sweep between scopes, converting a sweep into an ordinary value, and moving a
Case Runner parameter outside shared workflow scope require creating and rebinding
a destination value first; the editor explains these constraints.

A saved vector offers component choices such as `velocity.x`, authored as a
reference to `/dimensions/velocity/0`. Vector components can themselves contain
scalar references or expressions. The **volume** value type edits an AABB as
`{"min":[0,-1,0],"max":[4,1,2]}` with separate minimum/maximum coordinates.
Use the function value source to derive reusable regions and points:

- `boundsFromExtents` converts native `[xmin,xmax,ymin,ymax,zmin,zmax]` extents,
  including a runtime `$observe` of a node's `bounds`, to an AABB.
- `boundsExtend` uses `before` and `after` fractions of the original span.
  `[0.5,0.5,0.5]` on both sides adds half a span on each side; an `after` of
  `[2.5,0.5,0.5]` adds an extra two spans in the positive X wake direction.
- `boundsPoint` chooses `min`, `mid` or `max` independently for each coordinate.
  `boundsCentre3D`, `boundsSize` and component references provide other points
  and scalar lengths.
- `fitCamera` frames a volume using a direction, up axis and image aspect ratio;
  `orbitCameras` creates a series of views around it.

Model extents, data extents and manually authored areas of interest can all feed
these helpers. Runtime measurements remain pending until data is available;
a static preview never invents a runtime bound.

### Inspect spatial expressions

Open **Spatial** in the title bar, or **Spatial…** in Variables & expressions.
Choose the document or workflow operation in **Spatial scope**. The list shows
named scalars, vectors and boxes with their authored values and evaluation state.
Select a row to edit a literal or choose **Edit expression** to preserve a
dependency. **Apply changes** applies the staged edits together; Cancel leaves
the draft alone.

The **Data extents** card is always visible, even before you add a literal.
**Load data extents** asks the configured application for reader bounds directly;
you do not need to save an expression or click Apply in ParaView. It shows
`dataExtents = (xmin, ymin, zmin), (xmax, ymax, zmax)`, or explains why bounds
are unavailable. Hover over the result for full precision. For generated
geometry or a filtered region, use a node’s extents instead.

**Add literal / volume…** opens a guided volume builder. Start from coordinates
(corners or centre and size), **Data extents**, **A node’s extents**, or **A saved
value**. Choose **Inflate %**, **Inflate by distance**, **Resize**, **Translate**,
**Push face**, **Set face**, **Union**, or **Intersect** to add ordered adjustments.
Each control explains its units and meaning. For example, 10% inflation adds 5%
at each end; a distance of 0.2 adds 0.1 at each end. Union encloses both boxes;
it does not combine their geometry. A disjoint intersection cannot be added.
Flat boxes are valid.

The preview uses the host evaluator and automatically resolves values from available
Live Data. **Select Live Data…** opens the source checklist. **Refresh from Live Data**
recalculates from resident sources without rereading input files, with cancellation available. **Keep linked to sources**
saves a normal expression; **Fixed numbers** saves the full-precision result
and is available only for a valid, current preview. Coordinate-only volumes
save as literals. **Show expression** exposes the generated expression without
requiring you to write it. **Add volume** or **Update volume** stages the result;
**Apply changes** commits the whole Spatial edit. Closing either window without
applying its changes discards that window’s edits. **Quick literal** remains
available for direct scalar, vector and coordinate entry.

Boxes use dataset coordinates: either six limits in
`[xmin,xmax,ymin,ymax,zmin,zmax]` order or `{"min":[x,y,z],"max":[x,y,z]}`.
Studio preserves either representation. Vectors can be shown as points or as
lines from the origin. The visibility checkboxes control overlays only.
Unresolved entries, faults and boxes with inverted limits are not drawn.

`extents(body)` needs the named node's loaded output. `dataExtents` needs the
data-loading nodes of the selected document. Until those observations exist,
the list says **needs-data**; this is not an instruction to type guessed
coordinates. **Live data** explicitly starts the configured application to load
spatial dependencies. It can inspect a draft with unfinished downstream fields;
the dependencies themselves must be usable. **Cancel live data** cancels that
job. Adaptors without extent support do not offer this action.

Resolved live values and available records from a verified run carry their
source and captured draft revision. Upstream recipe or visit changes invalidate
measurements; editing names or downstream expressions reuses compatible upstream
observations and evaluates the new expression.
Spatial currently shows the first visit (time index zero and sweep indices
zero); it has no visit selector. It does not display every position of a sweep
at once. ParaView Workbench Live data inspection shares the resident data service
and makes its measured extents available to Spatial.

### Work through the car example and templates

The [car example](../examples/paraview-car/README.md) derives its model from the
union of body and wheel extents. Its wake, seed line and cameras read that model
by name. Open its `input.json`, set `settings.case` and the body/wheel patch
names for your case, then use Spatial to inspect `model`, `wake`, `seedX` and
`seedY`. Checking the document without loaded data leaves these entries
unresolved. Its latest-time selection also requires reader inspection before
a plan can enumerate times.

Studio checks the pipeline and expressions before Run, then defers source-time
inspection to the configured application. A latest-time selection can therefore
run as authored; structural and expression errors still block Run. Spatial
expression checks remain usable while the time selection is pending.

The seed expression `sweep(model.min.y, model.max.y, seedPositions)` moves both
ends of one line together because both refer to the same named `seedY` entry.
Its count is constant; its endpoints become available after the model loads.
The complete example produces twelve files at its default five positions.
The README records a bounded native run and explains the case-specific patch
names and display range; Studio inspection alone does not reproduce that run.

Three supplied ParaView templates also use these expressions:

| Template | Fill in | Position expression |
| --- | --- | --- |
| Slice sweep | Slice positions | A fraction of `data.deltaX`, where `data = extents(source)`. |
| CFD orthogonal-slice overview | OpenFOAM case file and slices per axis | Three coordinated fractions of `domain`, where `domain = extents(speed)`. |
| Synchronised geometry study | Design samples, initial radius and final radius | `extents(sphere).mid` follows the changing sphere. |

Template insertion replaces the current draft as one undoable edit. Fill the
highlighted fields, then Validate. The CFD template expects a reconstructed
case with `U` and `p`; its field range remains a choice for the author. These
templates retain the expressions after filling, so a changed dataset or sphere
can supply new extents at execution.

The five OpenFOAM templates (CFD overview, pressure-coefficient report,
Q-criterion orbit, wake streamlines and wall-yplus report) explicitly select the
latest stored case time with `{"source":"case","select":{"latest":1}}`.
The reader still skips time zero by default. To use another stored time, edit
`times`; to include zero, also set `skipZero` to false.

Output settings explain filename tokens and provide presets. Parameter tokens
include a key and value, while sweep tokens provide a sweep value. Explicit output
filenames take precedence. **Default parallel workers** controls independent Case
Runner workflow operations, rather than native threads or MPI ranks. Developers
can edit it; explicit template/workflow worker settings take precedence.

### Live Data and linked spatial volumes

**New volume** suggests a Name from its source and adjustments. The suggestion
stops changing after the first manual Name edit. Existing spatial Names are
editable. Renaming updates bound expression and `$document` consumers in the
same staged document; Cancel discards the edit and Apply remains one undo step.
A collision or an expression whose references cannot be identified is reported
without changing the document.

A linked volume is a recipe: `inflate(extents(`tires`), 0.1)` can be saved
before any input data is available. Schemaxis checks the type and dependency
graph, including cycles, in the shared core. Coordinates are needed for a
preview or a fixed snapshot, not for saving the recipe. The disabled Add/Update
button explains its current reason in its tooltip.

The top bar's **Live Data** indicator and the workbench's **Live Data…** button
open **Live Data selection**. Choose
source nodes or derived nodes, then **Enable selected Live Data**. Upstream
requirements load automatically, and compatible native objects stay in memory
across windows. Additional selections retain previously loaded compatible nodes.
**Disable all Live Data** releases native processes; closing a dialog does not.
The indicator shows total resident native-process memory (including application
overhead, not just mesh bytes). Native loading can be cancelled through the
selection dialog or Jobs.

Spatial and New volume resolve missing values automatically when their source
nodes are already loaded, including building required derived nodes. They never
silently enable another input. Under Settings → Live Data, turn off
**Automatically resolve spatial values from loaded Live Data** to calculate on
request instead. Cached values still appear immediately.

**Refresh from Live Data** recalculates values and updates changed derived nodes
using resident sources. **Refresh extents** does the same for `dataExtents`.
These controls remain available while Live Data is enabled and are disabled
when it is off; their tooltips explain this. Refresh does not reread files from
disk. The selection dialog disables **Enable selected Live Data** when all
selected nodes are already loaded and offers **Refresh from Live Data** separately.

Measured bounds remain session knowledge even after unloading native memory.
Adding or renaming a value does not invalidate its upstream measurements. Changing
the upstream recipe or visit makes old measurements inapplicable; enabling that
changed input supplies new ones. `dataExtents` needs bounds for all readers in the
selected document; use a node's extents when loading only a subset. Input files
changed externally require disabling and re-enabling Live Data to reread them.
Resident data and cached measurements are not restored after exit/reboot. Save
preserves the recipe, not a hidden mesh or cache.

The persistent console exposes the same service:

```text
data list
data load reader selectedRegion
data status
data refresh
data refresh selectedRegion
data eval "inflate(extents(selectedRegion), 0.1)"
data unload
```

Use `--operation ID` with list/load/refresh/eval inside a workflow. `data refresh`
resolves named values; supplying nodes limits it to those nodes. `data eval`
automatically resolves missing bounds from resident sources; add `--cached`
to use existing measurements only. Neither command enables unloaded inputs. The console prompt
shows Live Data state and resident memory. CLI clients can issue these through
`schemaxis console --command ...` within one process; use the interactive console
or a long-running agent service to retain memory between requests. Process exit
releases native memory. `schemaxis spatial rename input.json --name old
--new-name new` prints a renamed input without overwriting the original file.

Python clients use `schemaxis.live_data.LiveDataSession.refresh(request)` to
resolve from resident sources, or `evaluate(request)` for cached evaluation. Trusted-local agent/MCP
clients use the `spatial` method with `live_data_list`, `live_data_load` (`nodes`),
`live_data_refresh`, `live_data_status` and `live_data_unload`. `spatial_eval` reuses the service's
observations; `spatial_rename` accepts `section`, `name` and `newName`. These are
session resources shared across requests. Strict MCP retains its planned-task
execution boundary and does not admit native Live Data actions.

### Creating ParaView scenes with controls

Use **Add → Scene**, or edit a scene already in the input. **Visible objects**
shows the pipeline as selectable chips. Filter by name or operation, use
**Select shown** to add a group, and open **Appearance…** beside an object.
Selections outside the filter keep their settings. Missing objects remain marked
**unavailable** until you explicitly remove them.

In Appearance, **Colour by** selects **Solid colour** or **Data field**. The colour
browser includes the bundled Matplotlib names, including `tab:` and `xkcd:`;
RGB/RGBA can be entered in 0–1 or 0–255 units. A data field has a separate
**Cell data / Point data** association and array name. **Ask the application**
inspects this object and its upstream data; it is never triggered just by opening
the form. **Use inspected range** copies the inspected range into a fixed override.
Leave Range out for automatic rescaling at each visit. Representation, opacity,
components, presets and legend controls are available alongside colouring.

Under **Images & cameras**, add an image and one or more cameras. Size presets
and background controls fill the existing image settings. Direction buttons set
the view and a compatible up direction. Leave camera Bounds out to frame all
visible geometry, choose a pipeline object's bounds, or use **Choose Spatial box
or expression…** to link an existing area of interest. **New volume…** opens the
Spatial volume builder directly. Its definition and the scene are staged together:
Apply accepts both in one editor transaction, and Cancel discards both. Changing
a linked box later changes the next run's camera without editing the scene.

**Appearance variants** contain per-object overrides for successive colour
states. An empty entry renders the base appearance; every entry repeats images
and glTF outputs. A variant cannot remove a field inherited from the base, so
use a separate scene for that field-to-solid change. **Data outputs** supplies
pipeline choices for geometry and measurements and keeps the existing export
forms. **Bundles** explains the supported editable ParaView state-bundle scope
before execution. The guided controls preserve the existing input format.

For the full coverage audit and deferred interface refinements, see
[Guided ParaView scene authoring](design/paraview-scene-authoring.md).
