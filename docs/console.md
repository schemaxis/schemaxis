# Schemaxis console

The console keeps authored documents, history, provider configurations and
checkpoint provenance in a locked workspace. Planning imports no native GUI
libraries and requires only the Python standard library and the Schemaxis package.
Native applications run in their own processes.

```bash
PYTHONPATH=src python3 -m schemaxis console --workspace '.schemaxis'
```

## Commands

Commands use shell-style quoting (`shlex`), but never execute a shell. Quote JSON
arguments with single quotes and paths containing spaces with either quote style.
Command arity is strict. `help` lists the supported command forms.
On a real terminal, optional stdlib `readline` provides editing, arrow-key
history and Tab completion for commands, active node IDs, document UUIDs and
providers. The latest 500 history entries persist in the workspace. Piped input
remains line-oriented JSON, and platforms without readline use plain input.

```text
new "Bracket design" freecad
rectangle profile 80 50
extrude bracket 6
set bracket length 8
preview
save "design intent.json"
undo
redo
circle hole 3
add bore extrude '{"length":10}' '{"profile":"hole"}'
add cut cut '{}' '{"base":"bracket","tool":"bore"}'
show cut
inspect cut
```

`rectangle` and `circle` create the declared constrained FreeCAD sketch features.
`box ID LENGTH WIDTH HEIGHT` and `extrude ID [PROFILE] LENGTH` are convenience
commands. Omitting PROFILE uses the selected feature. The bounded utterance
`draw a rectangle 80 x 50 mm centred on the origin` is also supported. Arbitrary
Python, native reflection and unrestricted natural-language execution are absent.

`add ID FILTER [OPTIONS_JSON] [INPUTS_JSON]`, `set ID OPTION JSON`, and `remove ID`
validate a candidate document before committing it. Dependencies, declared types,
option bounds and supported keys are checked by the provider. Referenced nodes
cannot be removed while their consumers remain. Removing the last node restores
the provider's empty template. `set document FIELD JSON` edits an authored
top-level field, such as `linearDeflection`, `scenes` or `dimensions`; `version`
and `nodes` cannot be replaced through that command. `open FILE` replaces the
active document's entire authored content and is undoable.

`select ID` changes selection without changing the model revision. `show ID`
changes FreeCAD output or the first Blender/ParaView scene's visible output.
Other authored scene settings are preserved. `inspect [ID]`, `list`, `history`,
`artifacts`, and `status` return structured data.

Blender and ParaView permit validated draft graphs without publications. The
first renderable node creates a default scene; resources do not become visible.
Preview still requires a complete provider publication plan:

```text
new "Scene design" blender
add paint material '{"colour":[0.1,0.4,0.8,1]}'
add cube cube '{"size":2}' '{"material":{"$object":"paint"}}'
preview
```

Godot draft authoring validates declared nodes while allowing an incomplete
scene; preview requires a used material, geometry and exactly one camera.
Aseprite maintains `output` as the final sprite operation:

```text
new "Game scene" godot
add paint material
add block box '{}' '{"material":"paint"}'
add camera camera
preview
new "Pixel sprite" aseprite
add canvas sprite '{"width":16,"height":16}'
add frame frame '{}' '{"sprite":"canvas"}'
preview
```

## Documents and providers

`new [NAME] [PROVIDER]` creates a new document with a UUID and retains previous
documents. `use DOCUMENT_UUID` activates one; `provider PROVIDER` activates an
existing document for that provider or creates one. Providers are resolved from
the shared trusted adaptor registry. Registry entries may specify an `adaptor`
module and `consoleTemplate`; otherwise the conventional provider module is used.

The FreeCAD provider also accepts `schemaxis.freecad.assembly/1` through `open`.
Assembly documents retain `parts`, `components`, `grounded`, `joints` and authored
metadata without inventing a node graph. Edit complete fields with `set document
FIELD JSON`; undo/redo preserve the full assembly. `list` lists component instances,
and status includes `documentVersion` and a component count. Preview dispatches
to the assembly planner/runner, and verified assemblies save as `.FCStd`.
Node modelling commands and live assembly execution are explicitly unsupported.

`configure PROVIDER LOCATION` saves an adaptor configuration without switching
documents. `connect [LOCATION]` configures the active provider. Executables must
be absolute executable files; ParaView may use an installation directory.
Multiple configurations coexist. Configuration does not mean a native process
is resident. Each document retains its own native client and revision-scoped
geometry cache, so FreeCAD, Blender and ParaView instances can coexist. Switching
documents preserves those instances and caches without replaying authored edits.
`unload` closes only the active document's live client and invalidates its geometry,
retaining configuration and authored data. `disconnect` additionally removes the active
provider configuration, so subsequent previews of the active document use
planning mode. Other documents' already-retained clients remain available.

## Native previews and saved artifacts

`preview [DIRECTORY]` uses a fresh UUID checkpoint directory by default. Without
a configured executable or live client it stores authored input and a plan.
With an executable it invokes the provider and requires verified native output.
Native artifact paths come from receipts, including Blender's actual scene
filenames. Multiple native scenes require an explicit future selection mechanism;
the console refuses to guess which one to save.

`live LOCATION` starts the active provider's bounded persistent client: a FreeCAD
GUI executable, Blender executable, or ParaView pvpython/pvbatch/installation root.
Preview applies the document and requests geometry; FreeCAD additionally saves
an FCStd checkpoint. Blender and ParaView clients advertising `save` publish a
native `.blend` or `.pvsm` plus a retained save receipt. Older clients without
native save retain geometry only and cannot save a native scene from that
checkpoint. A client belongs exclusively to the document/provider active when
attached. Start or assign a separate client for another document; switching back
selects the original instance. Assigning one client to two documents is rejected.
Replacing an active client closes that instance without touching other documents.
`geometry` requires a successful live preview of the current revision. `image
[FILE]` first uses a verified batch PNG: a unique `preview.png`, or the sole PNG
artifact. Ambiguous multi-image checkpoints are rejected. Otherwise it asks the
current live client for an image. Geometry queries, including after switching back,
ask the worker to detect native GUI divergence and compare its native revision
and geometry digest with the retained cache;
native GUI changes are never silently imported into authored intent.

`save FILE.json` (or `.schemaxis`) saves the complete authored document.
`save FILE.FCStd`, `save FILE.blend`, `save FILE.pvsm` or `save FILE.aseprite` copies the matching native artifact from
a successful checkpoint of the current document revision. Other native suffixes
are rejected. Before copying, the console checks the receipt digest, document
identity, revision, authored digest, artifact containment and artifact digest.
Destinations are published atomically without overwriting existing paths.
Native GUI residency is not required to copy an already verified checkpoint.
FreeCAD live snapshots report `verificationScope: nativeLiveSnapshot` and
`independentReopen: false`. The console checks that the owned client's saved
FCStd is a ZIP with a CRC-readable, parseable `Document.xml` rooted at `Document`,
then retains its digest. These container checks do not independently prove saved
geometry or successful native reopening. Batch adaptor verification has its own
stronger execution/readback contract; it is not implied by live snapshot saving.
Live Blender receipts describe native library parsing and object/material
membership; live ParaView receipts describe state XML and proxy membership.
They do not claim independent geometry replay or dataset reload. Save responses
retain that `verificationScope` and the provider's `externalDependencies` and
`datasetsCopied` fields. ParaView states do not package referenced datasets,
sidecars or case directories; keep those resources available. Live Blender may
also reference unpacked external images. The console checks the retained native
receipt digest as well as the native file before copying.
Godot scene files depend on project resources; standalone native save is rejected
with the retained checkpoint project directory. Use that complete project.

Every authored edit, undo and redo receives a new increasing workspace revision.
Undo does not restore an old revision number. Editing invalidates preview use,
geometry and images for that document only, retaining its client for the next
preview. Other documents' clients and caches are unaffected; an old native
checkpoint cannot be saved as the new model.
Failed native attempts remain in `documents[ID].attempts` and invalidate live
residency. A completed checkpoint of an unchanged revision remains available
after a failed retry; `lastPreview` identifies that completed checkpoint, not the
failed attempt. Recovered interrupted attempts are marked `interrupted`.
Cancellation, timeout, native exit, detected GUI divergence and uncertain worker
state discard only the affected document's unusable live client while preserving
authored intent and other native instances. Status
reports `nativeState: unavailable` and a `nativeFault`; start a new live client
to recover. Failed apply with verified rollback may reuse its existing client.

## Durability and integration API

`session.json` contains the complete state and a checksum. Writes synchronise a
temporary file, atomically replace the state, then synchronise the directory.
Memory changes only after publication. If publication succeeds but directory
fsync or cleanup fails, `atomic()` raises `AtomicPublicationError` (`OSError`)
with `published=True`, `durable=False`, and `path`. This means the visible file
may already contain the new bytes; it does not mean rollback. Session commits
compare those bytes with the intended envelope and reconcile in-memory state,
invalidating affected runtime caches, before re-raising. If reconciliation fails,
the session closes. Other state owners using `atomic`, including reference stores,
must likewise reload/reconcile or stop writes after this exception. Never retry
from stale in-memory state. Startup validates the checksum and
authored documents. Corrupt state is rejected rather than silently reset. Native
clients and geometry are never restored. An OS advisory lock prevents concurrent
session owners and is released on `close()` or process exit. Do not delete the
lock file to bypass a running session. These guarantees target local POSIX
filesystems; the checksum detects corruption, not a malicious workspace owner.

```python
from schemaxis.console import ConsoleSession, AdaptorConsoleSession

with ConsoleSession(workspace, executable=None) as session:
    session.execute('box block 10 20 30')
    state = session.status()
    identity = state['activeDocument']
    revision = state['revision']
    record = state['documents'][identity]
```

Both constructors use the same implementation. `AdaptorConsoleSession(workspace,
provider, executable)` changes the initial default provider. Existing workspace
recovery preserves its active document. `session.live` is a settable accessor for
the active document's client; clients expose
`request('apply', document=doc)`, geometry, save, image and close. Geometry/save/image
convenience methods are optional when the same commands are supported by `request`.
`geometry()` returns revision-tagged objects, preserving `nativeRevision` separately.
`image()` returns an absolute PNG path. `status()` includes current `artifacts`, `documents`,
`activeDocument`, top-level `revision`, `references`, `configurations`, `connections`,
`configured` and `resident`. `connections` includes all retained native clients;
each document record includes its own `resident`, `nativeState` and `nativeFault`.
Returned authored data are copies. `session.close()` attempts to close every
retained client and releases the workspace lock even if a client's close fails.

The HTTP owner serialises calls with its RLock and schedules native jobs. Reference
registration and message segments live in its separate store, keyed by document
and revision; it overlays those references on the session's status. The CLI owner
closes the session in `finally`. `run_console` does not assume ownership.

## Shared source and property editing

The visual console now includes **Edit source / properties**, with recoverable
invalid JSON, located diagnostics, pointer/property navigation and shared undo.
Terminal and agent tools use the same authoring history and revision checks. See
[shared authoring](shared-authoring.md) for commands, file conflicts and agent use.

## Inspection workspaces

The workspace selector now offers Geometry study, Text inspection and Tables and
signals. Capture local text/CSV, inspect numeric columns, and add typed evidence
chips to the same context composer. [Typed inspection](typed-inspection.md) explains
coordinate conventions, snapshot provenance, paging and the synthetic fixtures.

## Workflow study

The [Workflow study preset](workflow-authoring.md) displays real operation/artifact
dependencies, navigates to their source, and changes an existing handoff through
validated shared undo. Use `new "My workflow" workflow` or the labelled example
button; native execution remains in the shared service or CLI.
