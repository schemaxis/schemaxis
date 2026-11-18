# Durable Console identity and live geometry

Copyright (C) 2026 David L. F. Gaden.

This support slice connects the checked ordinary-node rename to durable Console
history and the second resident domain, live geometry. The bounded implementation
and evidence below are accepted for the scope stated here. They do not qualify complete
extractBlock authoring or unlock browser Name controls.

## Delivered scope

- Dedicated Python `prepare_rename` / `rename` and console/CLI `rename-preview` /
  `rename` operations bind the exact document UUID, authored revision, forward
  proof, policy and operation scope. The source and selection form one undo group.
- Durable Undo/Redo restores the exact authored endpoints and original source
  spelling. Runtime ownership stays private. Ordinary source/patch edits receive
  no inferred rename credit; actual history snapshots can restore their retained
  transaction-bound pending chain only at its exact native status token. An
  inapplicable archive does not block ordinary history Preview.
- Both present resident domains prepare before publication. Live Data stages
  metadata under its existing lock; graph preparation checks the authored scene,
  active plan and adaptor-owned geometry projection without native mutation.
  An unpublished failure adopts nothing. A visible-but-durability-uncertain commit
  retains the exact pending witness and monotonic published revision.
- Native graph alignment is lazy and strict. It reuses the same handles, ports,
  observations and evaluated values. Actual geometry must match the projected
  previous coordinates/topology. Readback failure reverses and verifies, or
  leaves uncertain handles intact. There is no identity-only reset/reread fallback.
- Full workflow and design envelopes are retained by shared spatial Draft handling;
  embedded node selection uses the exact operation and `/workflow` pointer base.
  Recovered sessions claim no old handles. Explicitly loaded new owners can adopt
  directed original history proofs while pre-Undo bare windows keep their root.
- A changed installed policy removes stale optional continuity credit during
  recovery without making authored source/history unreadable. Identity transport
  errors remain structured and retain the actual client for explicit cleanup.
  Checked preparation refusals retain a healthy preview; a successful ordinary
  Preview clears an earlier recorded fault. Unchanged-policy corrupt witnesses
  refuse recovery, while changed policy loses only optional continuity credit.
- Unused Live Data families consume no views. Pending graph proofs cancel only
  verified adjacent opposite directions of the same original proof. Any Undo,
  Redo or rename that would exceed the 32-step packet bound requires explicit
  Preview first. Request-local policy snapshots and a bounded defensive
  validation cache preserve fresh independent worker admission.

See [the API and adaptor contract](../../docs/identity-authoring.md).

## Host evidence

`tests/unit/test_durable_identity.py` covers native-free prepare, source and derived
handle preservation, composite identity projection, expression-bearing lowered
plans, native readback reversal and uncertainty, unpublished and visible-uncertain
publication, pending and aligned history branches, lost geometry-response retry,
exact YAML source restoration, stale native plans/client replacement, both resident
domains, recovered bare-window compatibility, unsupported resident ownership, and
standalone/workflow/design scope isolation.

The final new host module passed 21 tests with YAML enabled, followed by focused
incomplete-draft and unrelated-name cases. The chosen affected authoring, Console
recovery/server/references, Live Data,
strict primitive, spatial and native-neutral live-worker regression set passed
181 tests with five optional YAML skips. Architecture/discovery and the extracted
strict preparation primitive passed 13 additional tests. The declared YAML extra
was subsequently supplied for the exact-source rename/Undo/Redo case, which passed.
These are host checks; they do not import native ParaView for their assertions.

The repair pass reran all 23 durable tests successfully and exercised 14 additional
cases in `tests/unit/test_durable_identity_repair.py`, including actual public
Preview after ordinary-history restoration, visible ordinary publication failures,
valid declaration/schema upgrades, independent worker readmission, plugin fault
isolation, context-local cache lifetime, 32 queued steps and unused-family isolation.
The 32-step counted-worker alignment took about 2.3 seconds; this is host evidence,
not an observed native timeout. The affected identity-policy, Live Data, recovery,
authoring and architecture/discovery set passed 93 tests. Separate metadata checks
were performed before acceptance of this extension; they granted no premature
coverage credit.

The subsequent host repair adds checked-preparation refusal preservation, explicit
uncertainty and successful Preview fault recovery, and unchanged-policy witness
integrity cases. The existing bound case also checks guidance for Undo/Redo.
The final combined durable/repair run passed all 40 tests with YAML enabled.
These checks preserve the prior native transfer contract; the retained physical
archives precede these host lifecycle/recovery and diagnostic-text changes.

The subsequent reply-admission repair checks the actual full wire encoding before
submission/publication, including current geometry, measured observations and
status identities. Eleven small-budget host cases passed and exercise indented-envelope limits,
oversized faults, early composite identity growth refusal, direct worker refusal,
durable Data rename/Undo preparation and cached observations after unload. Current
measured replies are covered; unknown future native inspection output is not
prefetched or inferred. Optional inspection geometry retains its explicit
unavailable result when necessary. The final combined durable/repair run again
passed all 40 tests with YAML enabled; architecture/discovery passed ten tests
and metadata reconciliation passed nine. The current worker path also passed
the fresh physical check described below.

## Physical geometry evidence

`tests/conformance/test_paraview_durable_identity.py` uses a test-only instrumented
ParaView worker with actual file readers. It counts the native algorithm's
`StartEvent`, records proxy global IDs and registrations, and retains full geometry
objects, authored documents, revisions, current digests and historical checkpoints.
Instrumentation adds no product protocol or command.

Serial ParaView 5.13.3 runs passed for a tetrahedral PLY reader with an
expression-driven shrink filter and a separate four-block VTM reader. Across
source/derived rename, Undo, Redo, explicit preview and readback-reversal/retry,
each process retained its own proxy IDs and every reader/filter execution count
remained one. The PLY source has four points/four cells and bounds
`[0,1,0,2,0,3]`; its shrink output has twelve points/four cells and bounds
`[0,2/3,0,4/3,0,2]`. Every retained face, vertex coordinate, triangle and edge
remained exact.

The composite file contains four explicit tetrahedra, with X origins 0, 4, 8 and
12. Geometry contains four leaves, block indices 1–4, sixteen points and sixteen
cells, with union bounds `[0,13,0,2,0,3]`. Only the node, label and corresponding
`node/block/index` IDs change. Full topology and coordinates stay exact.

Both serial cases inject a geometry-readback failure after native relabelling.
The worker restores the original registration and verifies its previous geometry;
the durable rename remains pending and retry succeeds on the same handles. Cancel
has no native effect. Earlier checkpoint files, authored digests, receipts and
artifact hashes remain historical and verify. Both native processes exited.

A separate physical Console case held one graph worker and one Live Data worker
at the same time. Five recorded states cover initial load, rename, Undo, Redo and
explicit Preview plus Refresh. Each domain kept its own distinct PID and source/
shrink proxies, with one execution each. Full geometry remained exact; Live Data
inspection reported four points/four cells and bounds `[0,1,0,2,0,3]`. Extents were
resolved against each actual authored input digest, and Refresh created or updated
no objects. Both workers exited. This is evidence of coordinated ownership in two
independent native processes, not shared proxy identity between domains.

A fresh coupled run on the repaired policy-admission path recorded seven states,
including sixteen queued renames and their sixteen directed Undo steps. Both
domains retained their own reader/filter proxies and execution counts of one;
old bare-window inspection and the current view remained usable. The Live Data
lineage held seventeen edges, below its unchanged bound of 32. Actual native
alignment requests took 16.6 seconds forward and 16.8 seconds in reverse against
a 60-second request budget; these timings exclude host publication construction.
Full geometry remained exact and both actual native processes exited.

The subsequent exact-wire/admission repair repeated this coupled seven-state case
on its final production archive. All forty measured Graph identity requests stayed
below 60 seconds; the sixteen-step forward/inverse alignments took 16.7/16.9 seconds.
The Data worker handled 52 actual read-only preparations within 67 measured identity
requests; the longest Data identity request took 1.6 seconds rounded upward. Both
domains again retained their own reader/filter IDs and execution counts of one,
full geometry, current and old bare-window observations, and seventeen lineage
edges. Both native PIDs exited, and both historical checkpoint receipts and their
four artifact hashes verified. Both worker archives matched the final wire encoder,
artifact writer, adaptor metadata and all other critical identity/runtime modules.
This fresh reader/filter run qualifies the current shared admission path; the
serial composite evidence above remains class evidence from its earlier archive.

## Remaining acceptance boundaries

- Independent challenge of this support slice is still required.
- Browser-local editor history, saved-name forms, Properties, batch membership,
  quick rows and unsaved Apply integration are not included. No new MCP method or
  admission snapshot was added.
- Resource registrations, owner-derived anonymous descendants, affected borrowed
  recipes, runtime output consumers and routes without audited policies keep their
  precise existing refusals.
- Physical evidence qualifies these serial ParaView file-reader/filter and
  composite geometry classes. It does not qualify MPI, every generated operation,
  other adaptors, every native resource or all block-selector semantics.
- Subset ordering and provenance, full adaptor authoring coverage and the final
  full host suite remain separate required work.

## Acceptance and remaining work

Independent challenge closed the publication/history, policy-upgrade recovery,
checked-refusal lifecycle, pending-chain guidance and actual-wire resource
admission findings. Boundary probes independently admitted an exact-limit wire
file and a fitting complete geometry reply, while refusing the next byte or
identity expansion before submission/publication. Cached-only observations and
unchanged peer measurements contributed to the complete reply bound.

The bounded core/Console and two resident-domain implementation is accepted.
The fresh tiny ParaView reader/filter qualification covers the current path and
physical sixteen-step chains. Earlier serial composite/expression evidence keeps
its stated archive and class limits. Native qualification here is on Linux;
Windows newline translation and other platforms have not been qualified.

Complete authoring remains partial: browser-local history and editable saved
Names, batch membership, compound ordinary edits, incremental graph changes,
additional identity/reference scopes, subset semantics and all other inventoried
units remain required. The deep-malformed-declaration loader follow-up also
remains required before completing the rollout. This acceptance grants no new
MCP capability, all-adaptor coverage or universal native qualification.
