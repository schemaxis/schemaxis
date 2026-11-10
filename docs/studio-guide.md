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

Many fields offer a choice between a literal value and a **Runtime value**
(`$axis`, `$time`, `$observe`, `$calc`, …) that is computed on each selected visit;
see the [$ reference](dollar-reference.md). If an explanation is wrong or unclear,
open **Suggest a correction → Copy help request** and send the copied record
with your correction; it identifies the adaptor, route and schema address.

- [Getting started](getting-started.md): installation and the first workflow.
- [User guide](user-guide.md): applications, planning, execution and publications.
- [JSON input](json-input.md): the document structure.
- [Shared authoring](shared-authoring.md) and [$ reference](dollar-reference.md): expressions, references, composition and studies.
- [Workflow authoring](workflow-authoring.md) and [Workflow design](workflow-design.md): connect application stages and expose parameters.
- [Typed inspection](typed-inspection.md): inspect data before selecting fields or consuming artifacts.
- [Installation](installation.md) and [Updates](updates.md): application configuration and compatibility.

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
   **Advanced**. These controls also appear in the selected object's Properties.
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

## Browse without knowing an operation name

**Add anything…** searches the whole catalogue. The groups separate file inputs,
generated sources, filters, outputs, and presentation/control settings. Search
results load in bounded pages; use Show more to continue. Curated recipe buttons
remain available for multi-operation tasks such as slice sweeps.

The four pipeline groups do not cover the whole document: scenes, cameras,
appearance, axes, time selection, definitions, dimensions, views, settings and
publication limits belong to **Presentation & controls**. Scene/image selectors
choose an existing target. Add that target first. Adding a value at an occupied
setting uses the editor's replacement preview and undo transaction.

## Configure complex values

Configuration forms follow the schema recursively. Select an alternative for a
union, add/remove array items, and expand optional nested properties. A proxy
choice such as a clipping plane or box has its own nested options. Free-form
objects are editable as JSON; their help shows the available schema. Expressions
and analytic syntax can be entered in the JSON editor after insertion.

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
select its Properties and reveal its source. It follows the current draft,
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
the general operation reference; **Properties** edits the selected instance.

Configuration and property Help show the native operation/property beside the
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
   endpoints…** in its configuration form or Properties.
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
**Add operation**. Studio detects processor folders versus serial/reconstructed
layout, reads available mesh regions and fields, and records explicit reader
settings. Unless overridden, it loads all available regions and fields. For a
document without `times`, it records the first available reader time. An explicit
case type, region/array selection or document time is preserved. A notification
reports the detected layout and time; these remain editable in Properties and
Document sections. This setup needs the configured ParaView executable.

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
and boundary mesh parts; `cellArrays` selects existing cell fields; `skipZero`
omits the initial time. The question-mark buttons retain technical constraints
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
prefix; click one to add it. The line above them reports what the whole list
selects in this case. Expressions are resolved when the input is loaded, so one
authored list serves cases whose names vary. An expression that matches nothing
is an error. A full selector path such as `/Root/boundary/walls` can also be
typed as an exact entry. Existing filters show the same list in Properties.

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

**Save** writes the input to its file, asking where the first time. The file
name is shown beside the revision. The arrow beside **Save** offers
**Save as…**, which writes a new file and makes it the one later saves go to,
and **Open…**. Saving over an existing file asks first.

The settings window for an operation has two screens, named at its top:
**Settings** and **Final values**. Final values lists whatever Settings left
open; anything left empty stays a placeholder that the editor offers to fill
after the operation is added. Enter never closes the window. Drag any window by
its title bar, and the fill window by its heading, to see the text behind it.
To reopen the window for a node that already exists, put the cursor in it and
press **Edit settings…** above the input or in Properties, or double-click it in
the pipeline guide; **Apply changes** replaces the node as one undoable edit.
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

The same names stay available while editing. **Case data**, beside
**Properties** in the right panel, lists the regions, cell arrays and times of
the open case: click a name to add it to the list under the cursor, or to copy
it when the cursor is elsewhere. The editor's suggestions offer them wherever
text is accepted. **Live data**, beside **Run**, loads the selected node and its
upstream dependencies and displays a bounded 3D snapshot when supported. Neither
inspection action runs downstream publications or requires unfinished downstream
nodes to validate. Live inspection still needs usable upstream inputs and one
selected state; workflow-produced files must exist before they can be inspected.
Use **Refresh live data** after changing the draft. Inspection preserves the
input, including unfilled fields. Adding a reader uses header metadata, when
available, to record its layout and first stored time without launching ParaView.

The workbench's actions sit at the right of the window tabs, and move to their
own row in a narrow window. **Validate** checks the current draft with the host
planner. **Preview** creates a planning checkpoint for a complete input. **Run**
executes and verifies the complete input in the configured application.
**Adaptor help** opens the selected adaptor/operation reference; the title-bar
**Help** opens the general Studio guide. The native status explains whether an
executable is available and how to open Application Setup in Admin mode.

The sidebar's header chooses **Guide** (the pipeline), **Library** (document
sections, templates and snippets) or **Both**; its close button, and the
sidebar button left of the view tabs, hide and restore it. The guide follows
the editor cursor and selects the containing node, including when the cursor is
deep inside its options. **Edit…**, **Duplicate** and **Delete** operate on
that node. **Controls**, right of the view tabs, hides the Add and editing rows
so the input takes the full height. **Snippets & templates** opens the snippet
categories. These layout choices are remembered.

Section recipe buttons insert on click. Hover/focus shows a temporary preview;
the click commits one draft edit. Three centre slices create one plane for each
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

Output settings explain filename tokens and provide presets. Parameter tokens
include a key and value, while axis tokens provide a sweep value. Explicit output
filenames take precedence. **Default parallel workers** controls independent Case
Runner workflow operations, rather than native threads or MPI ranks. Developers
can edit it; explicit template/workflow worker settings take precedence.
