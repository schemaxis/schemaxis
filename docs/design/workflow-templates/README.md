# Workflow templates and creator

2026-10-03 · Architecture approved; first development milestone started.
Review source baseline: Schemaxis `4487292`.
See [implementation status](implementation-status.md) for delivered scope and checks.

The proposal is to make a successful workflow into a reusable tool: its author
chooses the inputs and selections that another person may change; its user fills
in a form, checks the displayed selections, and runs the declared process.

Start with [the architecture](architecture.md), then the
[delivery plan](delivery-plan.md).
[Source review](source-review.md) records what already exists, documentation drift,
the Qt grid widget assessment, and the limits of the ParaView integration proposal.
The [numerical-coupling extension](numerical-coupling.md) incorporates the whole
of thesis Chapter 2 and Appendix C, separating study feedback from live numerical
coupling, step control and STSC.

The approved architectural direction is:

1. Add a versioned **workflow-template manifest**, a separate values file, and an
   ordinary `schemaxis.workflow/1` body. Use the existing workflow executor.
2. Treat application visits as uniquely named operations. `A → B → C → A` has
   four operations, with two using the same adaptor. Reusing an application does
   not require reusing its process or creating a dependency cycle.
3. Treat a whole-workflow feedback study as an outer controller over complete,
   verified attempts. Reuse the existing bounded feedback machinery. Distinguish
   a parameter sweep, design iteration and physical simulation time.
4. Make selections real typed inputs. A historical chip can be promoted explicitly
   to a selection tied to one asset, a reusable selector, or a required run parameter.
5. Extend the current browser creator and its common service. Use the reviewed Qt
   grid's interaction ideas and tests; do not transplant its number model or make Qt a
   prerequisite for the first release. A desktop shell remains possible later.
6. Support view providers with explicit capabilities: retained geometry/images,
   interactive controls and optional native previews. Do not require embedding an
   arbitrary application's existing window.

An example template bundle is in [examples](examples). The first supported
manifest/value subset is specified in [the template contract](template-contract.md).
Its workflow body uses current contracts and demonstrates
FreeCAD → Gmsh → Octave → FreeCAD. Host checks are recorded in
[design-checks.json](design-checks.json); they establish planning behaviour only.

The full car/CFD example drives the design, but is not the first acceptance case.
CFD physics/boundary configuration, solver execution, transferable case
directories and native qualification are separate unfinished capabilities.
The creator must display those gaps clearly rather than infer support from an
adaptor name. Initial delivery should complete one small working template through
creator, CLI and agent paths before extending the CFD chain.

The creator, selections, native template acceptance and numerical controllers
remain later milestones. Historical design probes remain preserved separately
from new implementation checks.
