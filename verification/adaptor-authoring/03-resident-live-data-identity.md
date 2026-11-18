# Resident Live Data identity views

Copyright (C) 2026 David L. F. Gaden.

The statements below describe this slice at its acceptance. See the subsequent
[durable Console and geometry support](04-durable-identity.md) for its separately
scoped implementation and verification.

This support slice lets a checked, unsaved node rename keep Live Data's resident
native objects and measurements. It adds a shared strict
`RuntimeClosure.reidentify` primitive, Live Data witnessed views, a worker
`data-reidentify` command and a declared ParaView `extents.relabel` capability.
See the [contract and limitations](../../docs/identity-authoring.md#resident-live-data-identity-views).
It adds no end-user mutation surface. No Name control, console command, MCP
method, saved document or session history uses it yet.

Sol accepted this bounded support slice after independent adversarial review and
rechecks. The reproduced unaffected-reader and partial-native-relabel defects are
closed. This acceptance does not qualify complete extractBlock authoring; its
inventory status remains partial and not qualified.

## Delivered scope

- Prepare previews without any session change; Cancel is not accepting.
  Accepting recomputes the checked rename and binds the exact input, output and
  policy digests, operation scope and identity. No-op, stale, forged-digest,
  collision, changed-source, unknown-view, cross-document view and unsupported
  relabel cases refuse atomically.
- Each provider/document/operation has one tree of witnessed views. Requests
  without a view claim its original view, so existing windows keep their
  residency, refresh and inspection. Names that a witnessed view gives to another
  identity contest only that identity, the name and their downstream nodes. An
  unrelated node reusing an old name, including after chained renames, never
  acquires a renamed object. Unaffected resident nodes are served in place
  without retiring the other view's nodes.
- Workers are translated node by node from each node's own measured evidence.
  A consumer or peer source whose recipe changed in one view inherits nothing
  elsewhere. Its unchanged upstream or peer reader stays resident for every view,
  and the changed node is kept, never retired, for the view that owns it.
- Observations matching the original recipe are copied to the recomputed
  signatures of the renamed node and its affected downstream nodes, never moved.
  Changed recipes and visits inherit nothing.
- Workers are aligned exactly before ordinary analysis or inspection. The primitive
  replans the replayed document itself. It refuses unless the plan reproduces
  exactly and changes only identities, then rebinds the same objects. It runs no
  create, configure, update, delete or `onVisit` command, and reverses completed
  labels on failure. ParaView reconciles a `RenameSource` that changed the
  registration and then raised, or whose readback failed. It either verifies
  the restored label or reports uncertainty. The primitive trusts only
  structured refusals as atomic. An unprovable label state leaves an
  `uncertain`, refused worker with its handles intact, never a reload.

## Host evidence

`PYTHONPATH=src:tests/unit python3 -m unittest test_live_identity` passed
21 tests. They use real host planning, the checked rename, the Live Data worker,
the shared primitive, the declared ParaView relabel hook and transport
validation. Only executable discovery and the native application are replaced,
by a counting backend with one label namespace per process. Coverage:

- a bare original window and a witnessed renamed view alternating Refresh,
  inspection, selection status and evaluation three times on one process, with
  the same handle objects and values. Exactly one reader execution, no creation
  or deletion after loading, and one relabel per view switch;
- derived rename, idempotent re-acceptance, Undo/Redo, chained and inverse renames;
- unrelated old-name reuse in bare and witnessed drafts, including after a chain;
- an unaffected source beside a reused witnessed name. It keeps its handle,
  process and read count and is reported loaded. Inspection and Refresh reload
  in place (only the alignment relabel, no create, update or delete). The
  contested identities report unloaded and explicit loads refuse atomically;
- a consumer setting changed in one view while the original view keeps its
  unchanged reader (same handle, one read, no new process). A changed source
  still invalidates;
- an unchanged reader beside a peer source changed in the witnessed view, after
  unload and explicit reload. The original and witnessed views alternate
  inspection and Refresh on one process with both handles and one read each.
  The original view never reports the changed peer loaded. Its own different
  peer recipe loads as a separate pipeline;
- visit, recipe, document and workflow operation isolation; unload and close;
- the atomic refusals above; reversed partial relabel, uncertain rollback failure,
  and a raw native label exception (uncertain worker, refused loads, no new process);
- the declared ParaView hook with a stand-in proxy manager (host logic, not
  physical native failure coverage). It covers change-then-raise, both names
  registered and raise-before (each verified restored), readback failure and
  failed reversal (uncertain, handles kept), and harmless collision and
  unreadable-preflight refusals;
- primitive object identity, refusal of an altered planner, forged steps and
  collisions before any native call; worker stale-plan and result-digest checks.

`test_live_data` still passes unchanged. The authoring inventory status test now
reconciles review credit with the judged ledger. Exactly one record is accepted
(extractBlock renaming: bounded core and resident Live Data support, still partial
and not qualified); every other record stays not reviewed.

## Bounded serial native evidence

`tests/conformance/test_paraview_live_identity.py` passed with ParaView 5.13.3 in
serial mode (opt-in; it skips without an installation). A test-only worker module,
packaged into the test's runtime archive, counts each algorithm's `StartEvent` by
proxy global ID and reports through the existing `status` command. For two test
names it makes the real `RenameSource` raise after changing the registration;
restoring the second name also raises. A tiny ASCII
PLY tetrahedron is read by `readPLY` (`vtkFileSeriesReader`) and shrunk by a
derived node.

| Step | Reader label | Derived label | Reader executions | Process |
| --- | --- | --- | ---: | --- |
| Loaded original | `mesh` | `skin` | 1 | first |
| Accepted source rename; bare original refresh/inspect | `mesh` | `skin` | 1 | first |
| Witnessed source rename view | `globe` | `skin` | 1 | first |
| Witnessed derived rename view | `globe` | `hull` | 1 | first |
| Undo to bare original view | `mesh` | `skin` | 1 | first |
| Redo to derived rename view | `globe` | `hull` | 1 | first |
| Refused native label collision | `globe` | `hull` | 1 | first |
| Real rename changed then raised; restored | `globe` | `hull` | 1 | first |
| Original view after a derived setting changed in the other view | `mesh` | `skin` (rebuilt) | 1 | first |
| Real rename changed then raised; restore failed | `doomed` (uncertain) | `skin` | 1 | first |

Through the restored-failure row, every step kept the same reader and shrink
proxy global IDs and one execution of each. The reader read the actual file: bounds `[0,1,0,2,0,3]`, 4 points,
4 polygons, `vtkPolyData`. The shrink output kept 4 cells. The old registration
name was absent after each relabel. Renaming to a name already registered
natively refused with `NATIVE_IDENTITY_COLLISION` and left labels unchanged.

When the real rename changed the registration and then raised, the hook restored
and verified the old label and reported `NATIVE_RELABEL_FAILED` with `restored`.
The test name stayed absent and the worker kept serving its views. After the
witnessed view changed a derived setting, the original view inspected the same
reader proxy with one execution and no new process; only the changed consumer
was rebuilt by ordinary refresh. When restoring also failed, the worker became
`uncertain`. Logical `mesh` and native `doomed` stay visible on the same proxy, with
one execution. Selection reports unloaded, explicit load refuses with
`IDENTITY_TRANSITION_UNAVAILABLE`, and no process starts until Live Data is disabled.

Controls show that the counter detects real work. A changed derived setting was
rebuilt by ordinary refresh (new shrink proxy, one execution; bounds
`[0,0.5,0,1,0,1.5]`) while the reader stayed at one execution. A changed file
recipe left Refresh unresolved without starting a process. Its explicit load used
a new process and read the other file once (X bounds `[10,11]`). Both processes
exited when the session closed.

A separate focused case read two independent files in the original view, then
reloaded the witnessed view with the peer changed to the first file. The process
held two distinct proxies, each executed once, both with bounds `[0,1,0,2,0,3]`.
The original view (unchanged reader only, peer unloaded) and the witnessed view
(both readers) then alternated inspection and Refresh twice. The same proxies
kept one execution each, with no new process. The original peer (X `[10,11]`) was
never reported loaded.

This qualifies serial ParaView Live Data reader/filter relabelling only. It is
not MPI, live geometry preview, every generated operation or other adaptors.
FreeCAD Name/Label and Blender semantics are not inferred from it.

## Not qualified in this slice

- Live geometry preview (`GraphWorker`): its document/selection, object IDs and
  labels, geometry digest and apply/rollback still rebuild for a renamed node.
- Durable session and workspace history, transactional Undo/Redo, publication
  failure handling and reopen.
- Browser editor history, Name unlock, batch membership, console/CLI/MCP mutation
  methods and a generic patch path.
- Contested identities in a draft without a view, and windows of other documents
  that share only by content, need an explicit view to use a lineage's resident
  worker for those nodes. Their observations remain content-shared. A worker also
  still requires every resident node's name in the request, as before this slice.
- Resource-role ParaView registrations are refused, not relabelled.
