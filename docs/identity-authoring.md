# Checked identity authoring

Copyright (C) 2026 David L. F. Gaden.

`schemaxis.identity_rename.rename_identity` previews one authored identity change
against an exact document digest. It returns a new document and reference-change
provenance. It does not save a draft, change selection or history, start an
application, or transfer resident native handles.

```python
from schemaxis.identity_rename import rename_identity
from schemaxis.storage import digest

candidate = rename_identity(
    document,
    identity_pointer="/nodes/0/id",
    new_name="004_inlet",
    expected_input_digest=digest(document),
)
rewritten = candidate["input"]
```

The caller's input remains unchanged on success and failure. Input and candidate
must be finite JSON, at most one MiB, 64 levels and 100,000 values. The size limit
is checked incrementally before canonical digest materialization, including when
a new name expands many references. Pointers use RFC 6901 escaping.
A stale digest, invalid identity, duplicate identity scope, destination collision
or unresolved relevant reference raises a structured fault before returning any
candidate. The new name obeys the owning route's actual identity schema; ParaView
allows leading digits and hyphens. A no-op still checks the digest and applicable
identity/reference safety.

The result contains `inputDigest`, `outputDigest`, `policyDigest`, ordered
`changedPointers` and scoped `identityChanges`. Changed pointers address the
original document; a renamed map key is reported at its old address. Identity
changes include the identity kind, scope pointer, identity-property pointer,
old/new names, provider and exact document route. These records describe the
preview; they do not certify a durable edit or native-state migration. The canonical
`storage.digest` ignores object-key order. The candidate preserves authored order,
but the digest does not witness that order. The combined encoded
`changedPointers`/`identityChanges` metadata has a separate one MiB budget,
including JSON and pointer escaping. Addresses are budgeted before collection;
exceeding the budget raises `IDENTITY_LIMIT` at `$changedPointers` or
`$identityChanges`.

## Implemented scope

The first policy covers ordinary explicitly named nodes in ParaView's
`schemaxis/1` route, including generated operations and resource nodes. The same
node identity can be selected inside an ordinary `schemaxis.workflow/1` operation
or the workflow embedded in `schemaxis.workflow-design/1` and `/2`. The pointer
selects the exact operation scope. Equal names in peer operation documents,
settings keys, native calculator text, filenames and block selectors stay intact.

Calc's `schemaxis.calc/1` route declares its single table node as a zero-input
source (see [Calc](calc.md#renaming-the-table-node)). A preview changes only that
`id` for all four source operations and declares no further references. Column
labels, CSV paths, cells, requirement names and generated sheet names stay literal.
Its nested typed-column and requirement names are not identities of this policy.

The transaction follows declared scalar/list input ports and node/port objects,
`$object` references, explicit inline consumers, `times.source`, scene visible
and appearance map keys, geometry lists, measurement/export node references and
writer resources. It preserves ordering and output port numbers. Observation
markers (`$observe`, `$sample`) and checked `extents(node[, port])` calls follow
the renamed node. Expression source ranges are rewritten using the checked host
call binding; ordinary entry names are not graph identities.

`$document` pointers follow moved reference-map keys, including suffixes,
operation/workflow qualifiers, and relative references whose own definition site
moves. Address calculation is shared with document resolution. Valid design input
targets and parameter targets retain their addresses: currently permitted targets
do not address the scene map keys moved by a node rename. Contract-valid designs
are checked before and after the preview in the host tests.

Unfilled options, scalar-reference or reference-list `$fill` placeholders and
unrelated semantic expression errors remain authored. Graph discriminators and
input containers must be literal and declared; unresolved slots in those positions
refuse at their authored locations. A zero-input source node with any property its
closed schema variant does not declare, including an `inputs` container, refuses at
that property. A `$observe`, `$sample` or `$object` marker that the route's policy
does not declare refuses in the selected scope when its value is the old name, the
new name or not a literal string. Invalid expression syntax anywhere in the
input, including peer metadata, refuses the preview. Invalid `$document` operation
qualifiers, scope qualifiers or extra keys also refuse, even in peer metadata;
fault locations include the full workflow/design input address.

Same-scope `$document` chains that read an owned identity follow its rewrite.
An indirect graph reference to an arbitrary free string is refused if updating
it would require changing text with no declared identity ownership. Copied JSON
binds in its consuming operation. The preview inspects borrowed typed references,
observation markers and checked extents calls; affected cross-scope imports refuse
at the importing site until a preservation contract is implemented. A borrowed
extents binding whose consuming graph is missing or unresolved also gives a
structured composition refusal at that site. Harmless metadata imports remain
supported, including unrelated incomplete peers. Previously unresolved references to the new
name refuse rather than silently becoming bound, including through composition.

## Resident Live Data identity views

`LiveDataSession.prepare_identity_transition(request, identity_pointer, new_name,
expected_input_digest)` previews a rename for one Live Data request. It recomputes
the checked rename above and changes nothing in the session. Cancel is simply not
accepting. `accept_identity_transition(request, identity_pointer, new_name,
expected)` takes the preview's `inputDigest`, `outputDigest` and `policyDigest`
(and no caller-supplied identity changes), recomputes the rename and refuses with
`STALE_IDENTITY_TRANSITION` unless every digest matches. It adopts the candidate as
an unsaved view. It writes no source or session file, selects or loads no
source and starts no process.

Only a graph node of the request's own operation scope can be renamed.
`IDENTITY_TRANSITION_NOOP`, `IDENTITY_SCOPE_MISMATCH` and
`UNSUPPORTED_IDENTITY_TRANSITION` refuse other cases. All refusals happen before any
session change. The result names the original view (`from`) and the new view
(`to`). Repeating an accepted transition from the same view returns the same
views. Requests may carry `view` to say which witnessed view their draft belongs
to. A view is bound to its provider, `sessionDocument` and operation
(`IDENTITY_VIEW_MISMATCH` otherwise).

Views form one tree for each provider, document and operation. Its root is the
original view. A request without a view of that tree claims its root, so an
existing window keeps working unchanged. Suppose such a draft also holds a name
that some witnessed view gives to a root identity. The root's input could not
contain it, because the checked rename refuses collisions. So that identity, that
name and everything downstream of either are contested for the draft. They are
never loaded or relabelled for it, and an explicit load or inspection refuses
with `IDENTITY_VIEW_REQUIRED`. An unrelated node that reuses an old name therefore
never acquires the renamed native object, including after chained renames.
Unaffected nodes of the same draft stay resident.

A request never retires a resident node it does not own: a contested node, one of
unknown lineage, or one whose recipe differs and is not needed. If every node the
request needs is already resident with an exactly matching recipe, the worker
reloads its own plan unchanged and in place, so it creates, updates and deletes
nothing. Otherwise the worker's own definitions of those kept nodes are carried
unchanged into the load. Conflicting shared entries refuse with
`LIVE_DATA_CONFLICT`, or leave Refresh unresolved, and no process starts. A kept
node recomputed from a changed upstream loses its recorded recipe. Only needed
resident sources must match. A changed peer source therefore neither blocks an
unchanged reader nor is claimed for a different recipe of the same name. Undo returns to the
`from` view and Redo to the `to` view. An inverse rename creates a separate view,
even when its input matches an earlier one. A contested draft cannot accept a
further rename (`IDENTITY_VIEW_REQUIRED`); pass its view.

Accepting copies, and never moves, each cached observation whose exact recipe
matches the original view. The copy goes to the recomputed signature of the
renamed node and every affected downstream node, with the node field renamed.
Content-compatible sharing across windows and documents is unchanged. A changed
input recipe, time or sweep visit inherits nothing.

Resident workers exactly in the original view join its tree. A worker serves the
views of its own tree node by node. Physical names follow the exact witnessed
mapping. Each resident node keeps the view, name and signature where its current
recipe was measured, and that evidence is carried to a requested view by exact
recomputation along witnessed edges. A node whose recipe differs from a witness
keeps its name but has no compatibility there. Alignment never overwrites its
evidence, so its own view still owns it. A node a witness never held has unknown
lineage and is excluded. An unchanged upstream reader therefore stays resident for
every view. Before
ordinary load analysis or inspection, the host sends the worker
`data-reidentify` with the worker's current plan digest, the ordered rename steps
and the expected result digest. The worker recomputes the rename of its own plan
and checks both digests. It then calls `RuntimeClosure.reidentify`, which
replans the replayed document itself. It refuses unless the plan reproduces
exactly and differs only by those identities.

The same native objects, evaluated values, observations, last time, ports, input
order, selection and object-registry ownership are rebound. Nothing is created,
configured, updated, commanded, deleted or reread, and no `onVisit` command runs.
Earlier evidence stays historical; the worker appends a bounded log of applied
transitions. Old and new views can alternate Refresh and inspection on one worker
process. Refresh still never starts a process or enables an unselected source.

Native labels are adaptor semantics. An adaptor opts in by declaring
`extents.relabel`, a binding `relabel(backend, handle, old, new)` that renames one
resident label in place. Without it, accepting a transition that would need
resident relabelling refuses with `UNSUPPORTED_IDENTITY_TRANSITION`. Such a worker
cannot serve another view: Refresh stays unresolved, and an explicit load refuses
with `IDENTITY_TRANSITION_UNAVAILABLE` instead of rebuilding.

ParaView renames the `sources` registration with `RenameSource`, keeping the proxy
and its global ID. Before renaming, it refuses a mismatched or resource
registration, unreadable registrations, and a destination already registered
natively (`NATIVE_IDENTITY_COLLISION`). These refusals change nothing. Afterwards
it reads the registrations back. After any exception or mismatch it restores the
old label and verifies it, reporting `NATIVE_RELABEL_FAILED` with `restored`.
The shared primitive trusts only such structured refusals as atomic. It reverses
completed steps, and treats any other failure as possibly partial.

If labels cannot be proved restored, the closure is poisoned and the worker
becomes `uncertain`. Its handles stay in place and it refuses further work until
Live Data is disabled. It is never reset or reloaded as recovery.

Sessions hold at most 32 transitions. Unload releases workers but keeps views and
measurements; closing the session releases everything. The unsaved view API does
not itself save source. The dedicated durable operation below stages these same
views for Console history; browser Name controls remain unchanged.
Durable edits consume no Live Data transition when their exact provider/document/
operation family has no resident worker, cached observations or witnessed view.
Another document's live data does not impose this limit on an unused family.
Its later explicit Load starts a new bare owner; no earlier handle is inferred.

## Durable Console identity history

`AdaptorConsoleSession.prepare_rename(pointer, name, document_id, expected_revision,
operation=None)` checks an exact authored revision and returns a candidate without
saving, consuming a view or touching native state. `rename(...)` recomputes that
proof, publishes the source and selection in one undo group, then installs host
metadata for lazy resident alignment. `operation` is a keyword argument for an
embedded workflow or design operation. The whole design envelope remains in the
proof; an identity pointer starts with `/workflow/operations/...` for a design.
Incomplete semantic drafts retain their diagnostics. Syntax and identity ambiguity
still refuse. Source uses its existing JSON or YAML renderer.

The console/CLI commands are `rename-preview POINTER NAME [--operation ID]` and
`rename POINTER NAME [--operation ID]`. Python callers supply the document UUID and
revision explicitly; a serial console command binds the active revision. Existing
raw `source` and `patch` commands keep their ordinary edit behaviour and never
infer a rename from matching settings.

Durable history stores the exact original forward proof and a transaction ID;
Undo and Redo use that proof with direction. Undo restores the exact original
source, selection and metadata, including unquoted expression tokens. The native
plan independently replays the same identities and may retain canonical backticks.
The worker reconciles only those bound tokens through checked replay, never by
ignoring arbitrary plan differences. Revisions continue increasing. Historical
checkpoints and their receipts stay immutable.

Before publication, the session checks every present resident domain. Graph
preparation validates the full authored scene, active lowered plan, selection and
adaptor identity capability. Live Data stages only metadata while holding its
existing session lock through publication and installation. No native rename,
load, view consumption or irreversible adoption precedes publication. An
unpublished failure installs nothing. A visible but durability-uncertain
`AtomicPublicationError` advances the authored state once and installs the exact
pending witness before propagating the error; it never claims native alignment.
An existing graph worker at a different authored base refuses before publication:
Preview the current document first, or explicitly `unload` that native client.
An uncertain owner also requires explicit release. Transport failures are structured
and recorded in native status while retaining the client for cleanup. This bounded
identity-only operation does not yet compose ordinary edits with a rename.

A pending graph chain is bound to the document UUID, revision, client identity and
native revision/document/geometry digests. Geometry or Preview aligns it before
reading or applying anything. Refusal leaves the published source and pending
proof available for retry or explicit unload, with no fallback rebuild. A lost
geometry response after successful alignment does not repeat the native rename.
Ordinary edits discard active pending credit. Returning through the actual history
snapshot can restore its retained transaction-bound chain; equal raw text alone
cannot. Restoration requires the archive's exact native status token. An ordinary
Preview that advanced the worker makes that archive inapplicable; ordinary history
then previews normally without reusing its old identity credit. Fresh stale or forged
identity requests still refuse. Ordinary publication clears pending credit whenever
the new bytes became visible, including a visible `AtomicPublicationError`.

At most 32 directed graph proofs may wait for alignment. Independently verified
adjacent opposite directions of the same original proof cancel. Any operation
that would exceed the bound refuses before publication with instructions to
Preview before continuing Undo, Redo or rename. Returning exactly to the starting vertex reads the
owned geometry without a rename or ordinary apply. Policy admission uses bounded
defensive caching of all actual policy, schema and declaration data. A checked
request compiles each exact route once; worker requests always admit independently,
and subsequent requests reload and fingerprint the actual data, including faults.

Private views and native owners are never persisted. Reopening reports no resident
handles. If data is explicitly loaded after recovery, directed history adoption
can bind that new owner using the original durable proof. Undo of historical
A→B then establishes the newly loaded bare B view as the root and A as its inverse
target, so a pre-Undo bare B window keeps its own reader. No pre-recovery handle is
claimed. Browser-local history and unsaved Apply remain separate work.
Saved witnesses are optional continuity metadata. Recovery checks their bounded
structure and exact authored endpoints. A changed or removed policy loses old
identity credit while otherwise valid source, revision and history remain readable.
Under the unchanged admitted policy, failed proof verification refuses recovery. Undo/Redo then follow ordinary history. The old policy digest is
never silently upgraded, and malformed workspace state still refuses recovery.

## Checked resident reply limits

The native file protocol admits at most 32 MiB per complete request or reply,
using its actual indented JSON encoding, Unicode escaping and final newline.
Requests are checked before submission. Oversized result or fault details become
bounded structured faults; no partially truncated product result is returned.

Identity preparation checks the full projected geometry reply, including renamed
observation keys, status identities, metadata, revision and digest fields, and
preparation/alignment replies. The geometry projector reserves expanded identity
bytes before copying the complete projected collection. A known oversized result
refuses before durable publication and before native relabelling, preserving the
healthy preview and owned reader. Use a shorter name; an already pending change
can be undone. Native reidentify repeats the same admission check.

Live Data's private read-only preparation checks its actual current resident node
list and measured extents replies. The locked host stage also checks retained
observation-cache projections at their exact visits, including after unload.
This admits current measurements, not unknown future native output after ordinary
settings/time changes. It never fetches geometry merely to rename. Optional
ParaView inspection geometry that exceeds the wire budget reports the existing
`geometryUnavailable` result while retaining required measurements and metadata;
oversized required metadata remains a structured refusal.

## Live geometry identity contract

An adaptor declares `liveIdentityGeometry(objects, steps, budget=None)` alongside `liveGraph`
and `extents.relabel`. It opts into bounded construction with
`liveIdentityGeometryBudget: true` and declares `liveIdentityStatusFields`, including
`id` and `label`, as exact node identity fields in its status objects. The projector
must reserve repeated expanded identity strings through the supplied budget before
materialising the collection. Status projection changes only declared owner fields;
native IDs and unrelated metadata remain exact. The host-safe projector returns copied geometry with only
adaptor-owned logical identities changed. ParaView projects `node`, `label`, simple
object IDs, and composite `node/block/flatIndex` IDs; coordinates, face IDs,
triangles, edges and block indices stay exact.

`GraphWorker` accepts internal `graph-prepare-identity` and `graph-reidentify`
requests with exact native digests/revision and directed forward proofs. Preparation
uses `RuntimeClosure.prepare_reidentify`; execution uses the same checked
correspondence through `reidentify`. Neither applies options nor updates native
data. After relabelling, actual geometry must equal the projected previous objects.
The geometry digest changes with its logical identities; it is not fabricated as
unchanged. The complete response digest also includes revision and authored metadata.

If post-relabel geometry verification fails, the worker reverses the checked steps
and verifies the original geometry. Verified restoration reports
`IDENTITY_TRANSITION_FAILED` and retains the original handles. Failed restoration
reports `IDENTITY_TRANSITION_UNCERTAIN`, retains the uncertain handles, and refuses
further work until explicit release. It never resets or rereads as identity recovery.
The [bounded verification](../verification/adaptor-authoring/04-durable-identity.md)
separates host proof from actual serial reader/filter and composite qualification.

## Ordinary resident transitions

An ordinary edit grants no identity continuity. `RuntimeClosure.prepare_transition`
plans one change of plan, roots and visit without native calls. A resident node keeps
its exact handle only when its filter, full declaration, input bindings, `onVisit`
commands and applied option set are unchanged, its constructor values convert to the
values its handle was built with at the concrete visit, and no input producer is
replaced. Other resident nodes are replaced with a stated reason. Nodes no longer
selected or replaced are deleted in the old plan's reverse dependency order before
any creation; unselected sources are never created. Observation-only dependencies
make a node dirty but never replace it. A late constructor value refuses.

`preserve` names resident nodes that must keep their handle and receive no configure,
command or update. When that cannot be proved natively-free (changed time, commands,
changed effective values, an affected dependency or sampled observations), the
change is refused with per-node reasons before any native call.

`GraphWorker.apply` uses this transition whenever a resident graph exists; adding,
removing or reordering visible siblings and changing options no longer resets the
graph. A failure while resolving inputs, or in configure, update, present, geometry
readback or reply admission, is reverted by the reverse transition (the failing node
is replaced) and verified against the previous observations and geometry, reporting
`APPLY_FAILED` with the handles that were kept. A failure inside a backend's object
construction returns no handle but proves nothing about what was allocated: the
node's ownership becomes unknown, no rollback is claimed, and the session reports
`UNCERTAIN_STATE` with its known, abandoned and unknown owners. A failed deletion
abandons that one handle, which is never deleted twice; failed restoration also
reports `UNCERTAIN_STATE`. An uncertain session refuses further work; reset deletes
each known handle once in dependency order before the backend's own reset, and
closing a Live Data worker leaves unknown objects to its process shutdown. The
resident path never falls back to a full rebuild. Live Data `data-load` reuses the
same transition and admits its measured reply before adopting the document; a failed
direct load still releases all resident data, as before. Its `preserve` form refuses
ineligible changes and reverts or becomes uncertain instead of releasing data.

The public Live Data host uses a private preserving protocol for existing workers.
Preparation and execution bind the exact process nonce, monotonic ownership generation,
plan digest, roots and concrete visit, as well as the complete candidate and protected
nodes. Execution independently rechecks preparation. A generation advances across
successful changes, verified reversal and identity transfer, so returning to the same
plan does not make an old request valid again. This protocol is internal; no new MCP
action or public native handle is exposed.

A compatible old window may inspect currently measured nodes while a newer window's
additional branches remain resident. Exact per-handle recipe, visit and witnessed-view
checks still apply; an omitted sibling is not a reason to load another reader.
When all requested measurements are already current, the worker returns them without
applying its plan, executing unrelated `onVisit` commands or updating a source. When
new work is needed, unchanged sources and unrelated retained branches are protected;
conflicting definitions, visits or commands refuse before native mutation. When a
witnessed Name alignment is pending, the worker first checks ordinary eligibility
against a non-owning, exactly renamed planning projection. The host independently
checks its predicted owner, and both future request envelopes must fit before any
relabel. Actual alignment and ordinary execution still independently verify their
own current owner and candidate. This preflight is not a general atomic compound
transaction: a later native failure during eligible ordinary work is reversed or
reported uncertain in the already acknowledged aligned namespace. Changed source
recipes still require explicit loading and receive distinct evidence.

A checked refusal preserves the healthy owner. Verified reversal restores its prior
host evidence and updates only the verified ownership generation. Native uncertainty
retains the actual client and blocks reuse until explicit release. If a preserving
request's reply is lost, its single IPC slot is quarantined: no retry or status request
overwrites the pending command, and the process remains owned until explicit close.
Selected native inspection uses the same retained transport and verifies the exact
owner in its readback. The complete owner-bearing inspection reply is budgeted;
optional geometry falls back to `geometryUnavailable` while required measurements
and ownership remain available. Required metadata exceeding the limit still
refuses. A checked inspection refusal keeps the owner healthy; an
unacknowledged or mismatched reply retains it as uncertain. Cancellation and
explicit close retain their intentional cleanup behavior. Legacy
`data-load` keeps its documented release policy; supplied client factories must
explicitly implement preserving request ownership to serve existing residents.

## Boundaries requiring further support

- Only one ordinary graph identity is renamed per call. Inline/generated targets,
  operation identities, nested named collections/maps, external template bundles,
  and routes without an audited policy remain unsupported.
- Explicit inline identities and deterministic anonymous sibling identities
  reserve the collision namespace. Identical explicit inline constructions may
  reuse an identity, including an ordinary definition; conflicting constructions
  and duplicate ordinary definitions refuse. An anonymous child whose generated
  name derives directly from the renamed owner refuses. Anonymous grandchildren
  under a stable explicit child keep their names and are supported. Preserving
  owner-derived descendant identities is required follow-up work.
- Known runtime `$value`/`$artifact` consumers of the changed workflow producer,
  design output ports/connections and named outputs require a declared output
  identity contract. They are refused rather than assuming producer receipts or
  artifact identities are unchanged.
- The pure preview is not a mutation API. Use the dedicated checked Console
  operation below for a durable edit. Saved-name UI actions, browser editor
  history and a new public MCP mutation method remain outside this support.
  Passing a preview through an ordinary patch grants no resident identity proof.
- Browser batches, nested Properties, membership history, subset ordering, full
  block-selector identity and source-specific choice provenance have separate
  acceptance requirements. A core preview does not qualify those behaviours.

## Adaptor policy contract

An exact route can declare a package-local `authoringReferences` binding. The
binding returns ordinary data with version `schemaxis.authoring-references/1`.
Registry admission confines the binding to the adaptor package. Loading validates
closed keys, selector forms, identity constraints and literal schema compatibility.
Invalid successfully returned policy data raises `INVALID_REFERENCE_POLICY` with
its policy location and leaves the adaptor registered. A genuine binding import
or call failure retains the existing plugin quarantine boundary. These lazy
loads can include peer operation policies during composition inspection, so a
preview can quarantine a peer with a genuinely failing binding. It does not mutate
authored input or persist a candidate. No native discovery or reflection is involved.

The policy has five required fields: `version`, `identities`, `references`,
`markers` and `expressions`. Each initial identity descriptor declares `name`,
`form: "array-property"`, a property-path `collection`, `nameProperty`, `nameSchema`
and `graph: {discriminator, inputs}`. Its string schema must match every projected
operation variant, including local schema references and constraints encountered
on the traversal. The supported name keywords are `type`, `pattern`, `enum`,
`minLength` and `maxLength`. Unsupported validation composition such as `const`,
`not`, `allOf` or conditional identity constraints refuses policy admission instead
of being discarded. Known explanatory annotations (`title`, `description`,
`$comment`, `default`, `examples`, `deprecated`, `readOnly`, `writeOnly` and
`x-schemaxis-contract`) are allowed. Later collection/map identity forms need an
explicit contract extension; merely finding an `id` or `nodes` key grants support
only when an admitted descriptor declares it.

Identity name patterns are checked with JSON Schema search semantics. A pattern
that must cover the whole name ends with the lookahead `(?![\s\S])`,
which Python and ECMA-262 (Studio) both read as the true end of the string.
A final `$` is not enough: in Python it also matches before a final line break.

`graph.inputs` is normally the literal input-container property, which every
identity variant must declare even for operations with zero ports. The explicit
spelling `"inputs": null` declares zero-input source nodes without a container. It
is admitted only when all of the following hold; otherwise admission refuses with
`INVALID_REFERENCE_POLICY` at the descriptor's `graph`:

- the route is non-graph (its `graph` flag is `false` or omitted), so the framework
  never expands node inputs;
- every ordinary declaration explicitly declares `inputs: {}`, and the adaptor
  declares no writer operations;
- every identity variant is a `type: "object"` schema with
  `additionalProperties: false`, and none declares the framework's `inputs` property.

The admitted projection then records each operation's closed property names. Any
other value for `inputs`, including an omitted key, an empty string, `false` or an
object, is refused. Graph routes and existing string spellings are unchanged.

Reference records declare an `identity`, typed selector `path` and `shape`:
`scalar`, `list`, `keys`, or `writer-resources`. Selector segments are literal
property names or `{"each":"array"}` / `{"each":"map"}`. Writer-resource
references additionally declare their owner's operation `discriminator`.
`markers` explicitly associate `$observe`, `$sample` or `$object` with an identity;
`expressions` can associate `extents` with that identity. The current interpreter
checks the supported shapes against the route schema and projects graph and
writer ports from the actual declarations, including generated operations. It
also proves that declared consumer name constraints accept every declared identity:
matching or omitted constraints suffice, as does checking a finite identity enum.
Other narrower scalar/list/port constraints refuse admission. Map `propertyNames`
uses the same proof; maps with fixed property-specific values or required names
refuse because moving a key could change validation. Constraints on relevant
ancestor schemas and local references are checked too.

Declared marker value schemas use the same proof wherever reachable through
actual schema keywords and local references, including common runtime definitions
and adaptor runtime variants. Explicit properties and every matching
`patternProperties` expression constrain a marker together. `additionalProperties`
is consulted only when neither an explicit property nor a matching pattern owns
that marker key, including `true` and the default open-object behavior. `false`
excludes a valid marker at that key. Malformed patterns and unproven or narrower string constraints
refuse admission. Wildcard values that exclude strings cannot carry a valid node
marker; typed object/numeric maps therefore do not cause a blanket refusal.
Compatible wildcard string alternatives and recursive generic JSON maps remain
supported; overlapping `oneOf` string alternatives require a later contract.
Cyclic schema references are inspected once per schema object; traversal is limited
to 100,000 objects and 128 structural path segments. Wildcard string projection
has a 64-level depth and 100,000-step work bound. Relevant ancestor constraints are
checked; literal `const` or `enum` domains containing markers refuse. Alternatives
that test only object property presence are preserved because changing a marker's
value cannot change property presence; value-constraining alternatives still
require the closed proof. Default/example payloads and
unused schema definitions are not mistaken for reachable validation schemas.
Known Schemaxis argument/declaration metadata annotations on marker ancestors have
an explicit allowlist. This is a bounded policy grammar, not a general JSON Schema
implication solver.

See the [ParaView policy](../src/schemaxis/adaptors/paraview/authoring_references.py)
and [validator](../src/schemaxis/identity_policy.py). Application-specific
references stay in adaptor data. Other adaptors do not inherit the ParaView
policy. The authoring inventory fingerprints admitted data, exact binding and
per-operation port projection; hook presence alone does not earn implementation,
review or native qualification credit.

### Shotcut asset names

The host preview accepts a pointer such as
`/nodes/0/options/assets/0/name` in a Shotcut timeline document. It checks the
current input digest, validates the destination name and updates each matching
`clips[].asset` in that same timeline. Clip order, frame ranges, resource paths
and the timeline publication ID are preserved. Other workflow operations retain
their own asset namespaces.

The preview returns an owner-local change record and a candidate document.
Studio Apply, durable undo and native continuity for these changes remain pending.
