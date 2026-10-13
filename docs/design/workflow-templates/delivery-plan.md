# Delivery plan

Status: development began on 2026-10-03 with template binding, resource capture
and deferred artifact planning.
See [implementation status](implementation-status.md) for observed delivery.
This sequence does not claim that the complete CFD workflow is ready.

## Approved direction and remaining milestones

Proceed with manifest/body/case separation, browser-first creator,
selection promotion, bounded outer feedback and the initial small exemplar.
The proposal keeps an optional Qt shell and richer ParaView view provider open
without making either a prerequisite for template authoring.

The first subset is frozen in [template-contract.md](template-contract.md) and
[resource-contract.md](resource-contract.md). Rich selections and numerical
participant contracts require their own qualification. Retain the design history;
mark delivery status separately. Numerical coupling is an additional track in
[numerical-coupling.md](numerical-coupling.md), not an implicit extension of D4.

## D0 — Contract and compatibility foundation

- Freeze the small first-release template/value JSON schemas and strict loader.
- Use existing scoped references, workflows and finite analytics. Preserve old
  bare workflow behaviour and host-only discovery/planning.
- Define typed resource/selection extension hooks through registry metadata.
- Decide initial UI editor component with a bounded offline completion/diagnostic
  exercise. Do not select it by screenshots alone.
- Correct the specific stale documentation listed in source-review.md as part of
  the implementation, backed by parser/schema conformance checks.
- Resolve the recorded artifact-only STEP planning limitation using typed deferred
  handoffs; keep native file/type validation intact. Include a literal mesh-size
  case so success cannot depend on a coincidental scalar-result reference.

Acceptance: malformed/mismatched versions are rejected with source locations;
old workflows remain unchanged; an ordinary four-stage A→B→C→A plan is accepted;
binding/source-map fixtures are agreed before parallel work begins.

## D1 — A usable template without requiring a GUI

First complete slice: parameterise the reviewed FreeCAD → Gmsh → Octave → FreeCAD
example, supply two dimension sets, and produce verified outputs using the same
template through CLI and service. Keep ordinary source readable and editable.

Work includes parameter metadata, defaults/constraints/units, atomic binding,
case save/load, manifest digest, named output aliases, diagnostics and captured
effective documents. Add additive template CLI and service methods with expected
revision/digest arguments. Exact command spellings are frozen in D0.

Acceptance:

- Defaults and a second case produce the intended native dimensions and declared
  downstream quantities, with independent native acceptance checks.
- Bad units/types, missing values, unknown parameters, overlapping targets,
  deleted targets and stale revisions cannot produce an executable bound case.
- A form/service/CLI edit produces the same effective workflow and input digest.
- A completed run remains tied to the original template and values after edits.
- An analytic case uses the existing sweep semantics and records every requested
  state; attempted and completed counts are separate.

## D2 — Creator with parameter forms and useful views

Build on shared authoring, workflow graph, discovery and inspection modules.
Provide capability search, adding/reordering/removing named stages, valid handoff
editing, source completion/highlighting, parameter promotion and a focused run form.
Reordering must report broken producer order; never silently retarget references.

Reuse geometry/image/text/table views. Add an editable case table separately from
immutable result snapshots; save a case edit through the common revision service.
Include keyboard navigation, atomic rectangular paste, undo, errors and selection
chips. No formula engine or arbitrary spreadsheet execution in this slice.

Acceptance: create and save a two-case template entirely through the GUI; reopen
it; execute the same captured case through CLI; compare effective documents;
exercise invalid JSON recovery, source-to-form links, undo, stale edits and
keyboard-only completion of the core flow. A second input must actually be run
before the template is labelled reusable for that input class.

## D3 — Selections as inputs, followed by bounded previews

First selection target: adapt the existing FreeCAD edge resolver and revision-bound
chips to explicit fixed/rule/parameter promotion. Add image rectangles/polygons
as region inputs and a table selection with stable column identity. A common
envelope does not imply all adaptors implement every selection kind.

Then add slice-plane and streamline-seed overlay controls to the ParaView view.
They author values over displayed geometry. An explicit preview operation can run
a bounded subset in an owned session. Keep live rendering dependencies optional.

Acceptance:

- Dimension changes either re-resolve the intended set or report empty/ambiguous
  selection. The originating historical chip remains unchanged.
- A template requests a new user's selection and records the exact accepted
  rule/asset binding; no silently stale face or triangle IDs.
- Image regions round-trip across zoom/display scale; coordinate and fill-rule
  tests include edges, non-square images and changed image digests.
- A slow old preview cannot replace a newer view; drag cancellation/undo preserve
  authored state; merely opening the form never starts native processing.
- An unavailable live integration falls back to supported controls and retained
  data with an accurate status.

## D4 — Whole-workflow feedback

Adapt the shared feedback engine to a full verified template candidate. Start
with one controlled scalar and a simple deterministic numerical observation;
native acceptance can use an analytic CAD measurement. A test double may prove
controller transitions, but cannot qualify the CFD chain.

Acceptance: at least two complete candidates; known convergent and unmet examples;
zero/NaN/missing observation; dimensionally incompatible update; invalid geometry;
iteration/deadline exhaustion; cancellation; evidence tampering; and a changed
selector. Native faults stop dependent work. An unmet study exports no success
candidate. Verification replays the same decisions and checks every attempt.

No arbitrary graph cycles, unrecorded optimiser code or partial-history resume.
Later policies may support several controls only after their bounds, units,
convergence meaning and replay contract are separately specified.

## D5 — Car/CFD qualification and installer

Qualify in separate increments:

1. Editable/imported model admission, meaningful design dimensions, scene placement
   and wind-tunnel construction with explicit units and flow direction.
2. Surface identity mapping and boundary inventory; exact-name and bounded-pattern
   selectors; one- and two-patch cases; native assignment readback.
3. CFD physics settings and qualified case preparation.
4. Solver adaptor/process ownership, case-directory manifests, mesh/solver quality
   criteria, stable result checkpoints and force measurements with units.
5. ParaView operations on those outputs, then one bounded force-driven design loop.

These are domain capabilities, not prerequisites for D1–D3. Verify conservation,
mesh/solver convergence and engineering assumptions where the domain task requires
them; do not infer a scientifically valid optimisation from a completed process.

Package a Linux local launcher/installer after D2 has a real user flow. Verify
clean-machine installation, packaged UI/schema assets, native-app configuration,
uninstall/update preservation and an offline launch. Do not bundle licences or
silently download every native application. The Qt shell and other platforms are
separate later decisions.
