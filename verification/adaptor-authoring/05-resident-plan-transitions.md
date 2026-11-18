# Ordinary resident plan transitions

Copyright (C) 2026 David L. F. Gaden.

This bounded shared-runtime support is accepted after implementation, independent
adversarial review and repaired failure checks. It keeps compatible resident
objects through ordinary node and selection edits. It does not complete
extractBlock authoring, expose compound publication or qualify browser controls.

## Delivered contract

`RuntimeClosure.prepare_transition` plans a change without native calls. Reuse
requires matching filter, declaration, input bindings, commands, applied option
set and effective converted constructor values at the concrete visit. Replacement
propagates through input producers; observation-only dependencies propagate
invalidation. Same identifiers alone grant no continuity. Unselected sources are
not constructed. Removed objects retire in the previous dependency order,
consumers first; retained handles enter the target typed registry.

The optional `preserve` set requires exact retained handles with no configure,
command or update. Unsupported preservation refuses before mutation with node
reasons. Graph resident apply uses this shared transition without a full rebuild
fallback. Live Data's native worker uses the same primitive, while its preserving
entry point remains Python-only.

A recoverable failure reverses the transition and verifies prior observations;
Graph also verifies prior geometry. Measured Data replies and Graph transition
replies are admitted before installing the successful document/revision. Reply
admission failure therefore reverses or reports uncertainty. A failed native
construction may have allocated an object without returning a handle: it records
unknown ownership, retains known handles and reports uncertainty instead of
claiming a clean rollback. Pre-construction input/port failures remain distinct.
A failed deletion records abandoned ownership and is never retried as though its
outcome were known. Uncertain workers block further ordinary work; explicit
cleanup deletes known handles once, then resets the backend or ends its process.

See [the runtime contract](../../docs/identity-authoring.md).

## Host evidence

The final affected suite ran **477 tests, 17 skipped**, in 316 seconds. The skipped
cases require optional native applications or YAML configuration. This is an
affected regression run, not the final full host suite.

`tests/unit/test_resident_transition.py` has 26 passing tests covering typed
registry/ports/lists, added and removed siblings, reordered roots, effective
constructors, changed independent peers, observations, time/axes/commands,
preflight refusals, dirty propagation, reversal and partial ownership. New failure
checks discriminate against the preceding frozen candidate.

Twelve independent asserting cases passed for Graph/Data construction failures
before and after allocation, raw and structured exceptions, pre-construction port
failures, actual measured-reply budget rejection, successful retry and failed
reversal. The scaled budget is 4,000 bytes with 64 measured output ports; it uses
the real admission path. Reader identity/read count, exact previous document,
plan, visit, observations and values are checked. Independent identity/ordinary
edit composition and before/after-side-effect delete controls also passed.
Existing resident-identity reproducers remain consistent with their accepted
baseline. Help, inventory and the changed-path release gate were current/clean.

## Fresh bounded native evidence

The following ran serially, with one owned native process at a time, using the
frozen implementation and test-only counters. Native process exit was checked.
All 786 packaged Python files in each actual worker archive matched the frozen
source. Full face coordinates and topology were independently checked against
raw tetrahedron data and analytic shrink/translation calculations.

- **ParaView 5.13.3 Data:** eight states through actual DataProcess transport.
  The source reader and untouched skin filter executed once throughout sibling
  addition, reorder, removal, re-addition and option change. An unrelated
  definition edit updated nothing. Changing an independent peer file replaced
  that peer; an observation-dependent filter retained its proxy and recomputed
  correctly. A third unselected reader was never registered. Evidence SHA256:
  `199433622f52f2dd54eceec5f04cca27e6e4e9be20c23dfc2c0f3361ecf3ce03`.
- **Blender 5.2.3 Graph:** six ordinary edit states retained the source importer
  call/update count of one and unchanged transform handle. Creation epochs
  distinguish a removed/re-added sibling even if a native address is reused.
  A real polygon-free PLY import allocated an object and then failed without
  returning it; native membership proved the unknown allocation. The worker
  reported uncertainty and refused further apply/geometry while retaining the
  original reader. Evidence SHA256:
  `f82019ac513e220467dc160e7189f57ff952431994e7e2cea4170946a647298d`.
- **ParaView 5.13.3 Graph:** the six-state class was rerun after reply admission
  changed. Source/untouched filter execution counts remained one; only the
  changed sibling re-executed. Evidence SHA256:
  `60a7cbf6e681564944f42e1545c6f21fddcedbfaf0dc6cc7702e1b7d229598d6`.

Reproducible classes are in `tests/conformance/test_paraview_resident_transition.py`
and `tests/conformance/test_blender_resident_transition.py`. These qualify the
stated Linux serial classes, not MPI, every operation or other application versions.

## Required remaining work

The first two compatibility gaps below are resolved by the subsequently accepted
[public Data host/wire support](06-preserving-data-host.md). They describe the
boundary at this earlier transition slice; the other rollout requirements remain.

- Expose preserving native-worker transitions through the host/private wire.
  The current host still discards failed ordinary Data workers. An older bare
  window can also create another reader after an ordinary sibling addition;
  this predates this slice and remains a required compatibility repair.
- Preserve exact ownership while serving compatible old windows without
  re-executing unrelated `onVisit` branches. No name-based alias inference.
- Qualify practical identity-view/history lifecycle, ordered compound edits,
  incomplete-draft publication, browser history/batch membership and all four
  authoring dimensions across the full inventory.
- Unknown allocations require backend reset or process shutdown. Fresh physical
  evidence proves honest uncertainty and process exit; explicit reset cleanup
  of that exact leftover object was not separately observed. Construction errors
  without allocation conservatively report uncertainty too.
- The updated native-only Blender missing-file step and earlier ParaView invalid
  edit case were not rerun physically after this repair. Their limits are not
  hidden by the fresh native cases above. The final full host suite remains due.

Coverage stays partial and complete extractBlock authoring stays not qualified.
