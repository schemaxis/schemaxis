# FreeCAD assemblies of modelled parts at named mounts

Phase two of the FreeCAD strengthening lets `schemaxis.freecad.assembly/1` use
verified PartDesign part publications instead of box/cylinder constructors. The
user's chosen workflow is a rigid arrangement of manufactured parts:

1. Each part definition names a verified single-Body `model.FCStd`, directly or
   through a workflow `$artifact` at index 2.
2. The part declares named mounting frames, optionally bound to its own
   parameters.
3. Components are App::Link instances, joined to one grounded component by a
   tree of real fixed joints. Each joint carries a parent-side offset and
   clocking.

The output is one self-contained FCStd. It contains one editable copy of each
part's complete history: parameters, constrained sketches, Pad/Pocket and
expressions. Constructor and sourced parts never mix. Existing constructor
plans and the immutable 17-example/21-member baseline are unchanged. Historical
evidence is retained; the current common receipts keep their named-case scope.
Phase two is accepted at the final integration epoch below, adds no strengthening
credit, and leaves phase three pending.

## Design decisions

- **Mount frames coincide.** A fixed joint makes the child mount frame coincide
  with the parent mount frame:
  `worldChild = worldParent · parentMount · T(offset) · Rz(clocking) · inverse(childMount)`.
  Axes are right-handed and signed (`+X … -Z`). There is no automatic
  opposing-normal rule; the guide shows seated and flipped examples.
- **Offset and clocking sit on the parent connector.** They are written to
  `Offset1`, and `Offset2` stays identity. In the native task panel, the simple
  Offset and Rotation fields edit `Offset2`. An actual GUI check confirmed that
  such an edit composes on the child side. Manual GUI edits are not
  synchronized back into authored JSON.
- **The optional GUI capture stage is refused** for sourced assemblies
  (`UNSUPPORTED_STAGE`), because it would replace the verified first-open state.
  Headless output writes a minimal native view record instead: visibility plus
  the installed joint view-provider proxies.
- **Embedding uses one public path:** `Document.copyObject` of the complete
  captured source. FreeCAD renames colliding names (`N0` becomes `N001`,
  `SchemaxisParameters` becomes `SchemaxisParameters001`); the native rename map
  is recorded and never assumed.

## Independent checks

Planning reads only the producer's own receipts, through bounded reads. It
refuses the following:

- symbolic links;
- oversized, duplicate-member, escaping-name or malformed archives;
- other routes, legacy Part-route outputs and design studies;
- units other than mm;
- any publication other than index 2;
- bytes that differ from the receipt.

Execution reverifies each producer and keeps a byte-identical copy. It then
runs three native processes: capture, build and reopen.

The reopen process inspects the saved state **before** any recompute or solve,
because a recompute alone re-solves the assembly. Placements, mount frames and
connector coincidence are compared with a closed-form host transform. Volume and
area are compared with the producer receipt. The centre of mass is compared with
the transformed centre measured on the captured copy alone. Every ungrounded
component is perturbed and then solved without presolve.

The saved file is checked without FreeCAD:

- Each embedded source must equal its producer's saved objects under one
  bijective rename. That covers types, properties, dependency records and
  expressions.
- No object reference may cross to another source. This includes a reference
  that keeps the same producer name.
- Mount expressions must match the exact millimetre grammar. FreeCAD silently
  accepts unitless text on these coordinates.
- Links and mounts must have exactly the state the adaptor created them with
  (including `LinkPlacement`, scale and element count).
- Only the controlled joint proxies may exist, and no external file link may
  appear.
- The GUI state must be exactly the minimal record.

The world bounding box is claimed **exactly** only for signed axis permutations.
A pocket can remove the corners that define a rotated box, so other poses use a
labelled containment check, and placement, volume and centre of mass carry the
exactness.

## Native and GUI qualification (FreeCAD 1.1.4)

The final integration run of `tools/qualify_freecad_assembly_sources.py` passed all
13 check groups in 39.8 s on frozen source `sha256:a8f63be0…`. Independent review
confirmed the corrected source and payload boundaries and verified a fresh native
assembly with different offsets and rotations. Shared generation, the full host
and Studio suites, and a fresh GUI run passed on this integration epoch.
The preceding owner run passed the same 13 groups in 37.1 s on `sha256:7347c181…`.
The earlier 12-group run on `sha256:429e9d8b…` is retained as pre-correction
evidence, rather than final acceptance.

- **Workflow.** One workflow builds five producers with the current part route:
  two plates with colliding native names, a corner-removing pocket part, a
  circle-Pad disc with a square pocket, and a literal Body. Two assemblies
  consume them through `$artifact` index 2. Resuming the unchanged workflow
  reused all seven jobs.
- **Literal analytic oracle.** Captured volume, area, bounds and centre of mass
  match closed forms for all five parts, including the quarter-disc corner cut.
- **Shared links.** Two instances of the plate share one embedded Body; the
  spacer has its own.
- **Bounds.** For the corner part rotated 30°, the naive rotated box overstates
  the native world maximum by 3.11 mm, and the check is labelled containment.
  The same part at a quarter turn matches its exact permuted bounds.
- **Convention changes.** Changing the clocking sign, ignoring clocking, changing
  the offset, moving the ground or flipping a mount axis is each rejected against
  the native result.
- **Shared edit.** A qualification-only native edit changed the plate thickness
  from 5 to 7 mm. The recompute alone re-solved the assembly. Both plate
  instances and every dependent mount followed the literal analytic oracle at
  7 mm, and the spacer's parameters and volume stayed unchanged. A fresh process
  reopened the saved copy and passed the same checks before recompute.
- **Relocation.** A relocated copy opened as the only document while the whole
  workflow directory (producers and retained copies) was unavailable.
- **Tamper negatives.** All 22 saved-file tamper and malformed-archive negatives
  were rejected. These include a same-value mount expression, a unitless mount
  expression, cross-source expression and profile references, a moved
  `LinkPlacement`, a wrong mount reference, a changed clocking or offset, a
  detached joint, an external file link and GUI-state changes. Four tampered
  copies were also reopened natively and rejected.
- **Invalidation and GUI stage.** A changed standalone source invalidated both
  planning and verification (`INPUT_CHANGED`). The GUI capture stage was
  refused before any native work.

`tools/qualify_freecad_assembly_sources_gui.py` passed 20 of 20 checks in two
actual FreeCAD GUI processes on final integration source `sha256:a8f63be0…`.
It ran on a private display with private settings and used only copies. The
earlier correction-freeze run on `sha256:05281dd6…` remains historical evidence.

- **First open.** Visibility matched the minimal record for every object, the
  joint view providers were restored, the persisted poses held before recompute
  and the model rendered.
- **Joint editor.** The real double-click handler opened the native joint task
  editor with `Fixed` and the mount labels; cancelling left the poses unchanged.
- **Embedded sketch.** It entered Sketcher edit and stayed fully constrained.
- **Native edit.** A thickness change and a parent offset solved to the oracle,
  were saved and reopened, and persisted.
- **Simple Offset field.** It edited `Offset2`, and the result matched only the
  child-side composition.

## Initial regression checks

These checks ran on initial implementation freeze `sha256:429e9d8b…`; the final
polish checks are recorded below and do not erase this earlier evidence:

- the FreeCAD host tests (71 pattern tests plus 6 legacy tests);
- the exact 17-example/21-member baseline comparison;
- guidance: 365 reviewed and 61 referenced records, none pending or stale;
- the phase-one PartDesign qualifier (14 groups);
- the parameter qualifier (14 groups);
- the constructor-assembly qualifier: headless build, shared edit and fresh
  reopen on 1.1.4.

The constructor qualifier needed two small tool-only corrections for the common
runtime's `state-00000` directory and its aggregate result; production assembly
code was not changed.

## Correction: closed source envelope and bound payloads

An independent review and root probes found two blocking gaps, and the
correction closes both.

**Gap 1.** A refreshed-receipt producer carrying any of the following passed
planning and capture and was opened natively before any refusal:

- an inert Python property;
- a file-bearing external link;
- a DOCTYPE with an internal entity;
- an extra, missing or corrupt payload member.

**Gap 2.** The saved assembly verifier compared payload file *names* but not
their contents, so corrupt, missing, extra or swapped shapes and corrupt element
maps passed after a digest refresh.

**Closed source envelope (host-only, before any native open).** The envelope is
derived from every clean single-Body producer in the qualified evidence, 79 runs
covering parameterised and literal parts, all of which it accepts. It admits only:

- the fixed FreeCAD prolog;
- the route's element vocabulary;
- exactly the persistent and transient properties and the extensions of each
  object type (the declared `dim_<parameter>` lengths are the only dynamic
  properties);
- references and expressions that stay inside the source;
- archive members that are exactly what the document names;
- syntactically valid BREP, element-map and string-table payloads.

It runs at planning, on the bytes about to be copied, on the retained copy
immediately before the first native stage, and in verification. Sources of one
assembly are limited to 128 MiB stored and 512 MiB expanded in total. Host tests
and the native qualifier confirm that each mutant is refused before any native
launch: launcher spies record no invocation, and the native PID log gains no
entry. Every test payload is inert, and no module named in test data is ever
imported.

**History substitution.** A *valid* substituted history shape passes the
envelope by design. The capture stage therefore records every stored history
payload, recomputes, and the host checks agreement immediately after capture,
before any build. A substituted shape is refused with only the capture process
launched. (The rule was strengthened in the final polish below; equal summary
measures alone were not enough.)

**Payload binding (host-only).** The saved assembly may contain only the members
its document names. Every embedded history shape (for every feature, not only the
tip) must equal the retained producer bytes. The one exception is the observed
lexical change from a producer `-0.0…` token to `0.0…` at the same position: 16
of 55 pairs, never the reverse direction or any other token. Near-equal numbers
are refused. Element maps are re-encoded by FreeCAD against the merged string
hasher, and native evidence showed they are also regenerated differently by
recompute. They are therefore bound structurally:

- skeleton and child records;
- postfix tables, with object tags remapped and hasher IDs masked;
- postfix-table relationships;
- tags that name only the same source's objects;
- in-range hasher references.

Datum shapes must be the fixed template at the saved mount placement, and link
lists must be empty.

**Stated limit.** The encoded name entries of the element maps of second and
later sources are counted and isolated but not decoded. Decoding them would
require FreeCAD's internal element-map encoding, and the qualified route never
references elements by mapped name.

**Not changed.** The phase-one part verifier is unchanged. The envelope applies
to new assembly admission only; a proposal for applying it to the phase-one route
is recorded for root.

## Final polish

**Planner type guards.** Mount `z` and `x` given as arrays, objects or null
raised a raw `TypeError`. They now fail as located `INVALID_MOUNT`. A host sweep
of wrong JSON types over every authored field, through `registry.plan` with real
fixtures, finds structured faults or acceptance only.

**History rule (root hypothesis).** Equal topology counts, volume, area, length,
bounds and centre of mass do not prove geometric identity. A centred 10×4 mm
through-slot turned a quarter turn (4×10 mm) keeps every one of those measures.
With refreshed receipts, the actual native run showed the following:

- Under the old rule, the substitution passed capture, and the build and reopen
  processes ran. The final BREP byte binding then refused it, because the build
  regenerates history shapes.
- The capture record now also holds every vertex position, each face's surface
  type and area and each edge's curve type and length. Vertices are matched
  one-to-one. The host refuses the substitution immediately after capture
  (`VERIFICATION_FAILED`, shape `N0.Shape`), with one native launch and no
  `built.json`.

This is a comparison of invariants, not a proof of identity. Numbers may differ
by at most 64 ULP at the part's size (at least 1 mm). Recomputing all 79 corpus
producers showed differences only at the 1e-14 level: precision-pad vertices up
to 6.2e-15 mm and one arc edge length near 1e-14. Host tests accept that noise
and refuse the rotated slot, a 1e-9 mm shift and a changed face type.

**Values the saved document cannot store.** The phase-one precision-pad
producer drives its Pad from the coefficient `0.12345678901234566`. FreeCAD
keeps expression literals to 15 significant digits, but it built the cached
history from the unrounded value. Recomputing during the build therefore
regenerates numerically different BREPs (`2.755982312827313` becomes
`2.755982312827319`) and a different saved Pad `Length`. Both the isomorphism
and the byte binding then refuse a genuine producer, and `purgeTouched` does not
prevent the regeneration. A numeric BREP normalisation was not adopted. Instead,
admission now refuses such sources on the host with `UNSUPPORTED_SOURCE`. A
source is refused if any parameter or literal option does not round-trip at
16 fractional digits, or any binding coefficient or offset does not round-trip
at 15 significant digits. The fault message tells the user to re-run the part
with representable values. Across the 79-producer corpus this predicate matches
the native "recompute differs" observation 79 of 79 times. It refuses only the
six precision-pad runs. Natively, the precision-pad source is refused at
planning with zero native launches.

**Sub-element references.** Sources may not carry `Link` `sub` names or
`LinkSub` entries. The corpus still admits 79 of 79.

**Element maps (Q1).** A small native investigation compared each source's
restored `Shape.ElementMap` before recompute, under the recorded renames:

- The first-copied source's maps are equal after expansion through the string
  hasher and tag remapping.
- Later sources differ in index and separator encoding.
- `getElementHistory` is also hasher-encoded.

No qualified reference consumes mapped names. Every `Link` has an empty `sub`,
every `LinkSub` is empty, and joints reference whole mount datums.

An inert disposable experiment swapped two same-structure name entries. The swap
passed the host verifier. Geometry, placements and the solve were unchanged, and
the maps were identical after recompute. Before recompute, two mapped edge names
resolved to the exchanged edges (`Edge1` and `Edge2`). A *new* name-based GUI
reference created before a recompute could therefore attach to a different edge.
That is the stated remaining limit; no decoder was written.

**Whole-run deadline and cancellation.** After final verification and before
success is published, the run checks for cancellation and its total deadline.
Three contract-level host tests cover normal success, an overrun during final
verification (`RUNNER_TIMED_OUT`) and cancellation (`RUNNER_CANCELLED`). They
**mock** the native runner and verifier. A deliberate mutation that removes the
check makes the tests fail. A separate **native** run with a 1 s whole-run
timeout stopped the capture process (SIGTERM, about 0.4 s), wrote a failed
`RUNNER_TIMED_OUT` result and published nothing. The native case covers a
timeout during a native stage, not one during final verification. The
constructor timeout policy is unchanged.

**Studio metadata.**
- The capability keywords include "rigid assembly of modelled parts at named
  mounts".
- The sourced part alternative is titled `Modelled part`.
- Parent, child, joint, part and top-level guidance explain both the
  primitive-face and the named-mount routes.
- The constructor template, its defaults, the 17 old plans and the publication
  order are unchanged.
- The guide documents the generic JSON-editor limitation: `$artifact` sources,
  mounts and endpoints are written as JSON, and there is no mount editor.
- Only the search unit tests (169 of 169) and the guidance freshness check
  (365 reviewed, 61 referenced, none pending or stale) were run, not the full
  Studio suite.

**Final-polish checks on frozen source `sha256:7347c181…`:**

- `tools/qualify_freecad_assembly_sources.py` passed 13 check groups in 37 s,
  with 29 native launches and the same source digest at start and end.
- The targeted native rotated-slot, precision-pad and timeout runs used the same
  source.
- Host checks:
  - 87 FreeCAD tests plus 6 legacy tests;
  - the exact 17-example old-plan comparison;
  - fresh guidance;
  - readiness admission (exit 0);
  - a release gate over the changed files (0 hits).
- The GUI qualifier and the phase-one, parameter and constructor regression
  qualifiers were **not** rerun. This turn changes no phase-one, parameter or
  constructor code, nor the saved assembly state that the GUI checks inspect.
  The constructor and phase-one routes are covered here by the host tests and
  the exact old-plan comparison only.

## Final integration and acceptance

On 18 October 2026, the supervisor accepted phase two after the following checks
on source `sha256:a8f63be057bf908c507b14878265f3b9d1c2088d433757c26622e15bd7664811`:

- All 2,871 public source, test, tool, guide and example files in the integration
  inventory had identical hashes before and after the checks.
- Full host suite: 1,867 tests ran in 736.9 s, with 33 skips and no failures.
- Full Studio suite: all 55 test files, 439 tests, 436 passed, three existing skips,
  no failures and no TODOs. All six sourced-assembly browser tests and all three
  parent-workflow validation browser tests passed as ordinary assertions.
- Fresh specialised native checks: 13 sourced-assembly groups, 14 persistent
  parameter groups and 14 PartDesign groups, all verified on FreeCAD 1.1.4.
- Fresh GUI checks: 20 passed across two processes. The supervisor also inspected
  the actual first-open model, joint-editor, fully constrained sketch-edit and
  edited-reopen images. The source publication was preserved and all GUI/Xvfb
  processes exited.
- Reference, Studio Help and ParaView guide generation and freshness checks,
  guidance, FreeCAD readiness admission and the public release scan passed.
  Generating the ParaView guide did not launch ParaView.
- Fresh common native receipts were registered for the six named modelling cases
  and two named constructor-assembly cases, including their timeout, pre-launch
  cancellation and integrity checks. These receipts do not silently add the
  specialised sourced-assembly cases to the common-case list.

The ignored evidence is under
`evidence/programme-20261017/integration-openai-20261018/freecad-phase2-final-integration/`,
including `acceptance-gates.json`, both source inventories, complete logs and the
native/GUI reports. The independent final review is in the sibling
`freecad-phase2-final-review/` directory. These results establish this recorded
source epoch; they do not refresh every other adaptor's historical qualification.

The accepted scope retains the saved-value admission rule, capture-invariant
limit and undecoded element-map name-entry limit described above. Phase two
adds no second FreeCAD strengthening credit.

## Limits

This release covers fixed trees only. It does not cover:

- face, edge or axis selection on modelled parts;
- mixed part forms;
- mechanisms, subassemblies, closed or redundant loops;
- imported STEP or third-party FCStd;
- live console or design-study execution;
- interference, contact or BOM claims.

Mounts attach to the Body origin XY plane with signed-axis orientations. The GUI
checks drove the installed task panel through its handlers and widgets; no human
pointer interaction or camera contract is claimed. Locale and FreeCAD versions
after 1.1.4 are untested.

Reproduce with:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_freecad*.py' -q
PYTHONPATH=src python3 tools/studio_guidance.py --app freecad --check
PYTHONPATH=src python3 tools/qualify_freecad_assembly_sources.py --directory DIR --executable FREECADCMD
PYTHONPATH=src python3 tools/qualify_freecad_assembly_sources_gui.py --assembly DIR/workflow/assembly/batch-0/attempt-0001 \
  --directory GUIDIR --gui-executable FREECAD --xvfb XVFB
```
