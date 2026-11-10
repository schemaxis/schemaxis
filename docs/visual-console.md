# Schemaxis Studio

Studio is the local graphical interface to Schemaxis's shared authoring, planning,
execution and verification APIs. It uses the same durable workspace as the
[terminal console](console.md). It is dependency-free in the browser: no npm build,
CDN, external fonts or hosted rendering service is needed.

From the repository root:

```bash
PYTHONPATH=src python3 -m schemaxis console --workspace .schemaxis/studio --web
```

Open the printed `http://127.0.0.1:…/?token=…` URL. Keep the terminal running while
using Studio. Reopen the same workspace to recover saved documents and revisions.
Opening Studio does not launch native applications. For a complete, small
Designer-to-Runner walkthrough, start with the [sample-and-scale study](../examples/studio/README.md).

## Built-in help

Open **Help** in the top bar or left rail, choose **Open Help** in the Ctrl+K
command palette, or press **F1**. Help is available in every interface role.
It ships with Studio, including installed wheels, and needs no internet connection
or native application. The local Studio server must remain running.

Search operation names, option keys, concepts or `$` commands; filter by category.
The ParaView guide covers input, publication and execution, and every one of its
645 registered operation identifiers has a separate reference topic. Existing
operation references for other adaptors and the shared authoring guide are supplied
too. Use **On this page** or **Jump to section**, linked topics, and **Back/Forward**
to navigate. Examples have **Copy** buttons. Flow charts render locally and retain
their authored source. Large linked schemas can be downloaded or opened in full.

The Workbench **Help** button opens the selected node's operation reference when
available; with no selected operation it opens adaptor-level help. Opening help
preserves editor text. The selected help topic is restored with the other tabs.
Help descriptions distinguish syntax templates, declaration coverage and native
qualification; browsing help does not qualify an operation or run a workflow.

Repository maintainers regenerate supplied help after documentation changes:

```sh
PYTHONPATH=src python3 tools/generate_paraview_guide.py
python3 tools/generate_studio_help.py
python3 tools/generate_studio_help.py --check
```

The Markdown files are the editable source. The second command packages searchable
topics and linked reference files under `studio_ui/help`; larger files are compressed
and expand when selected. No build-time or runtime Markdown/Mermaid dependency is
required. The renderer supports headings, paragraphs, lists, tables, fenced code,
inline code/emphasis, links and the simple declared flow charts used in the guide;
raw HTML is displayed as text.

## Find your way around

The top bar shows the workspace, role, command search, connection and theme.
The left rail opens windows; tabs let several documents remain open together.
The bottom panel holds **Problems**, **Jobs**, **Log** and **Console**. Errors
appear as notifications and stay in Problems; source locations can lead back to
an editor. The command palette opens with **Ctrl+K**.

| Window | Purpose |
| --- | --- |
| **Help** | Search packaged guides, operation contracts, shared `$` syntax and examples |
| **Start** | Create a design or adaptor instance; reopen a saved workspace document |
| **Workflow Designer** | Connect operation instances through named ports; expose parameters and export templates |
| **Adaptor Workbench** | Edit one adaptor input, inspect its schema, insert declared snippets, and preview its artifacts |
| **Schema Editor** | Open and edit JSON against one or more registered document schemas |
| **Case Runner** | Inspect a template, set parameter values, plan, run and inspect verified outputs |
| **Settings** | Theme, editor preferences, role and managed naming/execution defaults |
| **Application Setup** | Locate native applications for this workspace |

Choose **Developer** for authoring, **User** for templates and results, or **Admin**
for application setup and organisation-style defaults. These are local interface
modes, not accounts or a security boundary. Admin includes Developer and User
capabilities. Settings labels identify managed values such as output index width
and default worker count.

Light and dark themes use the same typography, spacing, panels and controls
throughout the windows. Theme and editor preferences are stored in the workspace.
Switching the theme does not change an authored document.

## Variables and expressions

Open **Variables & expressions** in the top bar or command palette. From Start,
choose an existing document or create an empty workflow design. A design can hold
shared values and Case Runner parameters before any operations exist; compilation
and template export still require operations.

Create named dimensions, settings, reusable JSON values, calculations or sweeps.
The scope selector distinguishes shared workflow values from each operation's
local values. For a literal shared value in a workflow design, **Expose in Case
Runner** declares a parameter with a default, optional units and help. Units are
labels, not automatic conversions. Existing parameter constraints remain enforced
by host validation. Sweep sampling accepts explicit JSON values or a regular
start/end/count sequence.

Use **Value or expression…** beside an Add-form or Workbench property, **Variables
& expressions…** in a fill prompt, or **Value at cursor…** in the Workbench or
Designer source editor. The same picker offers named values, calculations,
registered functions and supported runtime expressions. Incompatible named values
are disabled with a reason. Creating a value from the picker stages its definition
and binding together; Cancel discards both, and applying is one undoable edit.
Add-form edits remain staged until **Add operation**.

The picker previews literals, absolute document references and scalar arithmetic.
Other functions and runtime values are explicitly deferred to host validation or
execution. A schema-compatible marker still needs a valid resolved value and the
required producer data. See the [shared expression reference](dollar-reference.md).

Workbench and Schema Editor changes stay in the current draft until saved.
Designer variable edits save a revision in the workspace. Editing shared workflow
values from an operation Workbench saves the operation and workflow together;
stale revisions are rejected. Apply or discard pending Designer table/source edits
before opening the global manager. Saved history and local editor Undo retain
their existing roles. Values referenced elsewhere cannot be removed through the
manager; update their references first.

## Workflow Designer

Create a design from Start or open a saved design from the recent-document list.
The left palette searches adaptor names, purposes and declared operations. Add
an operation, give it an instance ID, and choose an available starter input.
Multiple instances of the same adaptor are allowed.

Select a box to inspect its identity and input/output ports. Ports are a named
interface on that operation: an input targets an existing authored runtime input;
an output identifies an artifact index, or a value inside an artifact. Data kind,
formats and units describe compatibility. These are workflow interfaces, not
ParaView's native output-port numbering.

Drag an output port to an input port to connect them. One output can feed several
inputs; one input accepts one connection. Several inputs allow several incoming
producers. Compatibility warnings help authoring, while the shared host and native
planners remain authoritative. Select a connection to inspect or remove it.
A dependency already encoded directly in operation JSON remains until that
source reference is edited; deleting a named overlay does not erase its base input.

Drag boxes to arrange them, pan the background or with the middle mouse button,
and use the wheel to zoom. **F** fits the canvas; **Delete** removes the current
canvas selection when the canvas has focus. Canvas edits are saved to the
workspace with revision checks and undo history. Moving a box changes presentation
layout without changing an exported template's semantic digest.

The lower tabs cover the template contract:

- **Parameters** holds exposed values, labels, defaults, constraints and help.
  Exposing an operation option moves its literal value into workflow settings and
  replaces the option with a workflow-scoped reference.
- **Outputs** declares aliases for operation artifacts and an optional naming
  pattern. Name previews use the declared values; actual names are published only
  after a run verifies.
- **Source** edits the complete design JSON. **Validate** checks it without saving;
  **Apply source** publishes the edit as one revision. Local changes are preserved
  when another window changes the saved design; discard/reload or resolve the
  conflict before applying a stale revision.
- **Sample data** attaches text, CSV, TSV or table JSON to an output port for local
  text/grep and table inspection. Samples stay in that window, are lost when it
  closes, and are excluded from templates. They do not replace runtime inputs.

**Compile workflow** produces an ordinary workflow document. **Export template**
writes `template.json`, `workflow.json` and `cases/example.json` into a new or empty
directory and checks the bundle. Cases with supplied values are checked by binding.
**Expose unfilled values as parameters** allows a draft template to retain those
markers in its example case; fill that case before planning or running it. Other
unfilled values prevent export. The design remains a separate editable document.
Template export does not overwrite an existing bundle.
The exported example case carries the design's naming preferences; load that case
in Case Runner to use them.

Closing a connection loop highlights its members and exposes controller settings.
Fixed-point and constant-relaxation settings can be saved, but native execution
of authored coupling loops is not available. A cyclic design cannot be compiled
or exported for execution. S6 requires a separate design review and native
qualification; saving a controller is not execution evidence.

## Adaptor Workbench

Open a standalone adaptor instance from Start, or an operation from the Designer.
The **Outline** selects declared nodes. **Input** provides JSON highlighting,
completion and diagnostics; suggestions can be disabled. **Schema** shows the
selected input contract, and **Properties** provides supported structured edits.

The **Templates & snippets** library supplies starter cards and category buttons
above the editor. Hover or focus a snippet to preview every insertion; click or
press Enter to apply it as one undoable edit. Category popovers are searchable,
and Ctrl+K also finds snippets. Favourites and recent items appear first.
The packaged catalogues contain 326 snippets and 57 templates across all 15
adaptors, including 100 ParaView snippets and 10 ParaView templates.

Typed `$fill` markers open a value picker. Enter accepts a value, Tab and
Shift+Tab move between fields, and Esc leaves the remaining markers for later.
The values-to-fill badge resumes filling. Pickers offer literals, suitable
references and expressions supported by the schema at that value. Scientific
array pickers offer names from the last native geometry observation.
Repeated uses of one snippet field are filled together and count as one value.
Properties and completion can also **Fill required** keys, and selecting a filter offers
its common options. New Instance and Designer operation dialogs have template
cards describing their requested fields.

Typing keeps diagnostics local and quiet until the edit settles. Explicit
Validate, Save, Preview, Run, Export and tab changes publish a single summary.
Drafts may contain markers; planning and running return `UNFILLED_VALUES` until
all markers are filled or removed. A starter still needs suitable
resources and a configured application to run.

**Validate** performs host validation. **Save** retains the edit; a nested
operation is written back to its parent design, while a standalone input can be
written to a selected source file. Conflicting document revisions or external
source-file changes are rejected rather than silently replacing newer work.
Unsaved edits have a close/reload guard.

**Preview** produces a host planning checkpoint when no native application is
configured, and uses the configured native path when available. **Run** requires
an available native configuration. An operation opened from a design can create
an independent preview instance; its workflow-scoped references still need bound
values. Use the complete template in Case Runner to execute producer/consumer
handoffs.

Available viewer tabs depend on the adaptor's declaration. Opening a sample file
loads local viewing data; it does not modify the native model or authored input.
After a native preview verifies, supported artifacts can be opened in these tabs.

## Schema Editor and saved work

**Open JSON** uses the browser file picker. Choose the relevant schema versions
in the left panel; nested workflow operations use their own document versions.
The editor offers highlighting, completion, formatting and diagnostics, including
malformed JSON that needs repair.

**Save draft** publishes the text to the Studio workspace and makes it available
as a recent document. **Export JSON** downloads the current text as a standalone
file, including edits that have not yet been saved as a workspace revision. It
does not silently overwrite the file selected by Open JSON. Saved edits have
undo/redo; local unsaved changes are guarded on close or reload.

Closing a window tab does not delete its saved workspace document. Typing alone
is not durable storage: use Save, Save draft or Apply source as appropriate.
Designer canvas gestures save automatically. Keep both the workspace and any
exported source/template files needed for later work.

## Case Runner

Enter a template directory or its `template.json` path and click **Inspect template**. Relative paths are resolved inside the Studio workspace. The form
comes from the template's parameter declarations: numbers, integers, booleans,
strings, enumerations and fixed-length numeric vectors, with defaults, help,
units and supported constraints. Image size or accuracy appears only if the
creator exposed it as an ordinary parameter.

A case file is `schemaxis.workflow-values/1`: an exact template ID, revision and
digest, parameter values, and optional run settings. **Load case** checks its
identity and binding. **Save case** writes inside the workspace. A new path must
not already contain a file; load an existing case before editing it. Saving uses
the loaded file digest, so external changes produce a conflict. Save does not
rewrite the template.

Run options include an output directory, worker count and naming overrides.
Leave the output directory blank to allocate a new workspace run directory.
Existing nonempty run directories are rejected. Worker count limits parallel
scheduling; dependencies and application resource requests still determine what
can run together.

**Plan** checks the bound workflow without starting applications. The diagram
shows operations and their dependencies, and expected aliases appear below it.
Plan details identify deferred native checks where producer artifacts do not yet
exist. **Run** submits an asynchronous job through the existing executor; its
progress comes from retained workflow evidence. **Cancel run** requests native
termination and may leave partial evidence. It does not roll back an application.

After the workflow verifies, the runner publishes a `named/` view with links or
copies and a `naming.json` manifest. Native artifact names and receipts remain
unchanged. Names support `{index}`, `{operation}`, `{output}`, `{param:ID}`,
`{axis:NAME}`, `{artifact}` and `{ext}`. Unsafe characters are sanitised, and
collisions fail naming without overwriting publications. A naming failure is
reported separately; a verified native run remains verified and its original
outputs remain available.

The UI rechecks the output evidence before presenting publications and verifies
fetched preview bytes against their recorded SHA-256. Select a CSV/TSV for the
Table viewer, text/JSON for Text, a supported image for Image, or STL/geometry
JSON for 3D. Other allowed formats have downloads for their native applications.
The live job list and Runner selection belong to the current server session;
run files remain on disk, but Studio does not yet provide a durable run-history
browser across server restarts.

## Viewer meaning and limits

The 3D viewer can orbit, pan, zoom, fit, section and use perspective walk controls.
Rendered geometry is explicit tessellation, not geometry guessed from JSON.
Workbench 3D sample loading expects the declared geometry JSON format. Runner STL
previews support binary/ASCII triangles with a bounded conversion. STEP, native
CAD assemblies, Blender projects and similar files are not universal browser
geometry imports.

Image picks describe pixels; table picks describe cells/ranges; text picks and
grep extraction describe displayed text. Workbench picks become removable chips
with inspectable metadata that can be copied. Their document/revision information
helps interpretation, but these chips are not a universal native selection
contract. A pixel does not identify a CAD face, and a sampled triangle is not
an enduring topological reference across model edits. Natural-language text or a
viewer pick never becomes arbitrary executable code.

Viewer HTTP reads are limited to 32 MiB and an allowed file-type list. Designer
sample attachments are limited to 10 MiB. The Runner's STL preview is limited to
200,000 triangles. Use the native application or a smaller explicit publication
when a format or size exceeds the browser preview contract. Native capability
and verification scope differ by adaptor; a shared window does not imply equal
coverage of all application features.

## Application setup, security and lifecycle

Select **Admin**, then **Ctrl+K → Open Application Setup**. Enter an executable
path, or an installation root where the adaptor requires one, and save it.
Locations are stored in the workspace; configured installation defaults are also
used. **Check locations** checks availability without launching applications.
A Located badge is not a native qualification result. For machine-wide CLI
configuration, see [installation](installation.md).

The server binds only `127.0.0.1`. API calls require a per-launch random token and
check Host/Origin. Packaged assets are confined to the UI directory. Artifact
reads are authenticated, limited by type/size, and confined to the workspace plus
run directories registered by this server session. Scripts and styles use a
strict content security policy; authored data is not inserted as HTML.

The session URL permits operating the local workspace: keep its token private.
This is a single-person workstation tool, not a hardened remote multi-user
service. A hostile process running as the same operating-system user is outside
that boundary. Role selection does not provide separate user authorisation.

Native jobs are serially owned by the Studio session, with each workflow's
scheduler applying its own bounded parallelism. State polling remains available
while a native job runs. Closing the server requests cancellation before releasing
session resources. Saved drafts and on-disk evidence have separate lifecycles;
inspect partial results after an interruption rather than treating an existing
file or a successful process exit as proof of verification.
