# Native FreeCAD assemblies

`schemaxis.freecad.assembly/1` creates an editable built-in FreeCAD assembly. It uses
`Assembly::AssemblyObject`, `Assembly::JointGroup`, the installed
`JointObject.GroundedJoint` and `JointObject.Joint` implementations, and the
compiled `assembly.solve()` API. It does not approximate an assembly with a
compound, fuse, manually assigned final placements or authored Python proxies.
FreeCAD 1.1.x is the qualified runtime family; qualification currently uses the
installed 1.1.3 build.

The standalone adaptor lives in `schemaxis.adaptors.freecad.assembly` and exposes
`plan(document)`, `schema()`, `run(document, directory, *, executable=None,
timeout=120, gui_executable=None)` and `verify(directory, require_result=True)`.
Planning, schema and verification do not import native application modules.
`run` requires a fresh output directory. `executable` is an absolute `freecadcmd`
launcher (or `FREECAD_CMD`); `gui_executable` optionally supplies the GUI launcher.
The timeout applies separately to each native process. Cancellation terminates
the process owned by that stage.

## CLI and console

The CLI recognises the assembly document version for planning, execution,
verification and provider queries. From the repository root:

```bash
PYTHONPATH=src python -m schemaxis plan examples/schemaxis/freecad-assembly.json
PYTHONPATH=src python -m schemaxis query examples/schemaxis/freecad-assembly.json
PYTHONPATH=src python -m schemaxis schema --provider freecad --section assembly
PYTHONPATH=src python -m schemaxis run examples/schemaxis/freecad-assembly.json \
  --output-directory evidence/assembly-cli-example \
  --freecad /path/to/freecadcmd \
  --freecad-gui /path/to/freecad
PYTHONPATH=src python -m schemaxis verify evidence/assembly-cli-example
```

Choose a fresh output directory for `run`. `--freecad-gui` is optional: it adds
the native joint task editors and image evidence before independent reopening.
Omitting it performs command-line native execution and verification. Assembly
node inspection remains unsupported. The [common runtime](adaptor-runtime.md)
adds finite analytic visits and scheduled workflow participation, including resume.

The FreeCAD console opens assembly JSON and supports complete document-field
edits, undo/redo, configured batch previews and saving verified `.FCStd` output:

```bash
PYTHONPATH=src python -m schemaxis console --provider freecad \
  --workspace .schemaxis-assembly \
  --freecad /path/to/freecadcmd
```

Then enter these console commands:

```text
open examples/schemaxis/freecad-assembly.json
set document dimensions '{"plateThickness":7,"postHeight":20}'
list
preview
save assembly-edited.FCStd
save assembly-edited.json
```

`set document FIELD JSON` replaces a complete field, including `parts`,
`components`, `grounded`, `joints` or authoring containers; the candidate is
validated before committing. `list` reports component instances. `preview`
uses the configured batch assembly runner; without an executable it only stores
the authored input and plan. Saving `.FCStd` requires a successful verified
checkpoint for the current revision; saving JSON retains the authored assembly.
The console's batch configuration takes `freecadcmd`; the optional GUI decoration
flag shown above belongs to CLI `run`, not the console command.

Live assembly execution is explicitly unsupported. Do not use `live` for an
assembly; `unload` an existing live client before a configured batch preview.
Node modelling commands such as `add` or node-level `set` do not apply to assembly
documents. See [the console guide](console.md) for session and checkpoint rules.

## Declared parts, instances and joints

See [the complete example](../examples/schemaxis/freecad-assembly.json). Its two
primitive part definitions are instantiated as four reusable `App::Link`
components: two plates and two posts. Three fixed joints connect them to one
grounded component.

```json
{
  "version": "schemaxis.freecad.assembly/1",
  "parts": [{"id": "plate", "type": "box", "options": {"length": 40, "width": 30, "height": 5}}],
  "components": [{"id": "base", "part": "plate"}, {"id": "lid", "part": "plate"}],
  "grounded": "base",
  "joints": [{"id": "mount", "type": "fixed",
    "parent": {"component": "base", "face": "top"},
    "child": {"component": "lid", "face": "bottom"}, "offset": [0, 0, 20]}]
}
```

- `parts`: 1–32 typed definitions. A `box` accepts `length`, `width`, `height`;
  a `cylinder` accepts `radius`, `height`. Dimensions are 0.01–10000 mm.
- `components`: 2–32 instances with unique IDs and a declared `part` reference.
  Optional `position` is XYZ in mm; `rotation` is yaw about +Z in degrees,
  limited to ±360. Non-ground placements are solver starting guesses. The
  grounded component's placement is the assembly's world anchor.
- `grounded`: exactly one component ID, represented by a real native grounded
  joint.
- `joints`: exactly one fixed parent joint for every other component. Joints can
  be authored in any order; planning orders them from the root. Cycles, duplicate
  child constraints, disconnected components and grounding a child are rejected.
- Joint `parent`/`child` endpoints select `top` or `bottom`, the planar cap at
  local Z=height or Z=0. Native face IDs are resolved from cap geometry and
  checked on reopening; authored input does not assume `FaceN` ordering.
- `offset` is an XYZ offset in the parent's local connector frame, bounded to
  ±100000 mm per coordinate. The fixed joint makes the two connector frames
  coincide. For these caps both connector frames have local +Z; the contract
  does not use outward face normals to flip a component.
- `units` defaults to `mm`; no other units are accepted. Pure document
  references/functions in `dimensions`, `definitions`, `settings` and the
  declaration resolve through `schemaxis.documents.resolve_document`.

Changing one native source part updates every linked instance. Joint references
remain actual native subelement references, and native joint attachment offsets
are editable in FreeCAD. With `gui_executable`, the saved FCStd also includes the
installed ground/joint view providers and native joint task editors, plus a
rendered image and full application-window screenshot as auxiliary evidence.
Without that optional stage the model, links, joint properties and solver are
editable, but this adaptor does not claim the GUI task-editor setup.

## Verification and evidence

```bash
PYTHONPATH=src python tools/qualify_freecad_assembly.py
```

The default evidence root is `evidence/assembly-20260920`. Completed evidence is
never overwritten; choose `--directory` for another run. `--headless` omits the
optional GUI stage. The qualification script supplements the integrated CLI and
console paths with shared-part editing and fresh GUI-reopening checks.

`model.FCStd` is the main publication. `authored.json`, `plan.json`, `built.json`,
`verification.json`, per-process submissions and logs retain the inputs and
verification evidence. Successful verification requires all of the following:

1. A real native Assembly and JointGroup with the exact declared joint/component
   membership; active attached `Fixed` joints and one native ground.
2. Correct primitive dimensions and component source links, including repeated
   instances pointing to the same native source object.
3. Component world positions, orientation axes, bounds and solid volumes matching
   host-calculated analytic expectations. Fixed connector translations and
   rotations must coincide. Checks use relative tolerance 1e-7 and absolute
   tolerance 1e-6.
4. Every non-ground component is deliberately translated and rotated, followed
   by an explicit `assembly.solve()` call, with no intervening recompute or
   connector presolve. Return code zero and analytically restored placements
   are required. Numeric before/perturbed/after poses are retained.
5. A separate `freecadcmd` process opens the FCStd, checks its native definition
   and saved placements, then repeats the solver perturbation test. Verification
   binds the evidence to the native file's SHA-256 digest.

The qualification script additionally changes the shared plate thickness from
5 to 7 mm in the reopened native document, recomputes/solves, saves
`edited.FCStd`, and independently reopens that file. It checks all updated
placements and both linked plate volumes against the updated analytic model.
With the GUI enabled, another GUI process verifies that the saved native joint
editors restore and that the assembly remains visible and solvable.

## Limits and provenance

This version deliberately supports **fixed trees only**. Revolute joints,
closed-loop or redundant constraints, arbitrary orientation mating frames,
subassemblies, imported parts, external document links, arbitrary CAD feature
documents, interference checking, contact, motion and multibody dynamics are
unsupported. `expectedDegreesOfFreedom: 0` describes the fixed rooted tree; it is
not a reported numerical DOF diagnostic from FreeCAD. Solver success and the
perturbation tests establish the qualified static cases, not universal solver
convergence. This adaptor does not reverse-sync manual FCStd edits into authored
JSON; use updated input for a new verified publication.

Public installed API usage was inspected in FreeCAD's
`Mod/Assembly/AssemblyTests/TestCore.py`, `JointObject.py` and
`assembly.solve.__doc__`. These supplied API names, reference conventions and
solver status meanings. The adaptor calls the installed implementations; it
does not copy their solver or joint implementation source.
