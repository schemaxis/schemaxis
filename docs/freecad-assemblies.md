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

## Assembling modelled parts at named mounts

Instead of primitive constructors, every part of an assembly may name a verified
[PartDesign part](freecad-part-design.md) publication. The assembly then contains
one editable copy of each part's complete history (its design parameters,
sketches, Pad/Pocket features and expressions), repeated `App::Link` instances,
named mounting frames and real fixed joints. The two forms never mix in one
document: either every part has `type`/`options` or every part has
`source`/`mounts`.

```json
{
  "version": "schemaxis.freecad.assembly/1",
  "parts": [
    {"id": "plate", "source": {"$artifact": "plate", "index": 2}, "mounts": {
      "top": {"position": [0, 0, {"terms": {"thickness": 1}}]},
      "side": {"position": [{"terms": {"width": 0.5}}, 0, {"terms": {"thickness": 0.5}}],
               "z": "+X", "x": "-Z"}}},
    {"id": "spacer", "source": {"$artifact": "spacer", "index": 2}, "mounts": {
      "bottom": {}, "top": {"position": [0, 0, {"terms": {"thickness": 1}}]}}}
  ],
  "components": [
    {"id": "base", "part": "plate", "rotation": 30},
    {"id": "spacer", "part": "spacer"},
    {"id": "cover", "part": "plate"}
  ],
  "grounded": "base",
  "joints": [
    {"id": "baseToSpacer", "type": "fixed",
     "parent": {"component": "base", "mount": "top"},
     "child": {"component": "spacer", "mount": "bottom"},
     "offset": [5, 0, 0], "clocking": 90},
    {"id": "spacerToCover", "type": "fixed",
     "parent": {"component": "spacer", "mount": "top"},
     "child": {"component": "cover", "mount": "side"}, "offset": [0, 0, 2]}
  ]
}
```

See [the complete workflow](../examples/schemaxis/freecad-assembly-parts-workflow.json),
which builds both parts and then the assembly.

- `source`: the `model.FCStd` publication of a verified `schemaxis.freecad/1`
  run with exactly one PartDesign Body whose solid tip is the output. Inside a
  workflow use `{"$artifact": "<part operation>", "index": 2}`; the part route
  publishes STEP (0), STL (1) and FCStd (2). Standalone, give the file path.
  The planner reads that run's own receipts and refuses symbolic links, other
  routes, legacy Part-route outputs, design studies, units other than mm, any
  other publication index, unbounded or malformed archives and bytes that differ
  from the receipt (`UNSUPPORTED_SOURCE`, `INPUT_CHANGED`).
  It also refuses a part whose values the saved document cannot store exactly:
  a parameter or literal with more than 16 decimal places, or a binding
  coefficient or offset with more than 15 significant digits. FreeCAD built that
  part's stored geometry from the unrounded value, so the assembly's recompute
  would produce different geometry. Re-run the part with representable values.
- `mounts`: 1–16 named part-local frames. `position` (default `[0, 0, 0]`) has
  three entries, each a number in mm or a binding to **that part's own**
  parameters, `{"terms": {"thickness": 1}, "offset": 0}`, with the
  [parameter limits](freecad-parameters.md). A bound coordinate becomes a native
  expression on the mount, so editing the part's parameter in FreeCAD moves the
  mount and everything attached to it. `z` and `x` choose the mount's axes from
  `+X -X +Y -Y +Z -Z` (defaults `+Z` and `+X`; `x` is required when `z` is not
  ±Z and must be perpendicular to it); `y` completes a right-handed frame.
  Mount IDs must differ from the part's own feature names.
- `components` and `grounded` are as for primitive parts. Component and joint
  IDs must not reuse FreeCAD helper labels such as `Origin`, `X-axis` or `Ground`.
- Joint endpoints name a `mount`. `offset` (mm) is a translation in the parent
  mount frame and `clocking` (degrees, ±360, default 0) turns about the parent
  mount's +Z after that translation. Both are written to the parent connector
  (`Offset1`); the child connector (`Offset2`) stays identity.

**In Studio.** The generic part form offers three kinds: `box`, `cylinder` and
`Modelled part`. The form's `source` field is a plain path. A workflow source,
`{"$artifact": "<part operation>", "index": 2}`, has to be written in the JSON
editor. Named `mounts` and joint `parent`/`child` endpoints are edited as JSON
values; joint endpoints offer `Face endpoint` or `Mount endpoint`. Studio has no
dedicated mount editor or sourced-assembly template. Begin from the
[workflow example](../examples/schemaxis/freecad-assembly-parts-workflow.json).
The host planner remains the authority for every sourced rule.

**Frame convention.** A fixed joint makes the child mount frame coincide with the
parent mount frame:

```text
worldChild = worldParent · parentMount · T(offset) · Rz(clocking) · inverse(childMount)
```

Mounts are frames, not surface normals. To seat a part on another, give both
mounts the same +Z. To hang or flip a part, choose opposing axes deliberately:

```text
  seated (both +Z up)            flipped (parent mount -Z)
     ┌─────────┐ child               ┌─────────┐ parent
     └────▲────┘ bottom: z=+Z        └────┬────┘ under: z=-Z, x=+X
     ┌────▲────┐ top: z=+Z           ┌────▼────┐ top: z=+Z on the child,
     └─────────┘ parent              └─────────┘ child hangs below, upside down
```

There is no automatic opposing-normal rule.

**In the FreeCAD GUI.** The joint task panel's simple *Offset* and *Rotation*
fields edit the **child** connector (`Offset2`). The authored offset and clocking
appear under *Show advanced offsets* as the first connector (`Offset1`). A GUI edit
of the simple fields therefore composes as `inverse(childMount · Offset2)`. Manual
GUI edits are never synchronized back into the authored JSON.

**Closed source envelope.** Before any FreeCAD process can open a source, the
host inspects the saved file. This happens at planning, on the bytes about to be
copied, on the retained copy immediately before the first native stage, and
again during verification. Only the form that the qualified PartDesign route
writes is admitted:

- the fixed FreeCAD XML prolog, with no DOCTYPE, entity or extra declaration;
- the closed element vocabulary of that route;
- for each object type, exactly its persistent and transient properties and
  extensions; the only dynamic properties allowed are the declared
  `dim_<parameter>` lengths;
- references and expressions that stay inside the source, naming whole objects
  only (no face, edge or vertex sub-element references);
- archive members that are exactly `Document.xml`, the minimal view record, the
  string table and the payloads the document names;
- syntactically valid BREP, element-map and string-table payloads.

Python objects, external file links, unknown properties, extensions or types,
extra, missing, duplicate or escaping members, and corrupt payloads are refused
with `UNSUPPORTED_SOURCE` (or `INPUT_CHANGED` for changed bytes) before FreeCAD
starts. Each source is limited to 64 MiB stored and 512 MiB expanded. All
sources of one assembly together are limited to 128 MiB stored and 512 MiB
expanded (`ASSEMBLY_LIMIT`).

**What execution does.** `run` verifies each producer again, copies its FCStd
byte-for-byte into `sources/`, and runs three separate native processes. For a
sourced assembly the timeout bounds the whole run. The capture process opens each
retained copy alone, records every stored history shape, recomputes the feature
history and compares each recomputed shape with the stored one. The comparison
covers validity, topology counts, every vertex position (matched one-to-one),
each face's surface type and area, each edge's curve type and length, volume,
area, bounds and centre of mass. Numbers may differ by at most 64 units in the
last place at the part's size, which is floating-point noise. A shape that
passes is consistent with its history, but this is not a proof of identical
geometry. A substituted or inconsistent stored shape, such as a centred slot
turned a quarter turn that keeps every summary measure, fails before anything is
built. A
capture process measures each copy alone. A build process embeds each copy
(`Document.copyObject` of the complete document), adds the mounts and joints,
solves, perturbs every ungrounded component, solves again and saves. A reopen
process inspects the saved state **before** any recompute or solve, because a
recompute alone re-solves the assembly. The whole-run timeout and cancellation
are checked again after final verification, so a run that overruns or is
cancelled there is reported as `RUNNER_TIMED_OUT` or `RUNNER_CANCELLED`, not as
success. FreeCAD renames the second copy of
colliding names (`N0` becomes `N001`, `SchemaxisParameters` becomes
`SchemaxisParameters001`); the adaptor records that map and never assumes it.
The saved file also carries a minimal first-open view state: links, the
assembly, the ground and each source tip are visible, and the installed joint
view providers are named so the joint editor opens without a GUI stage. The
optional GUI capture stage (`--freecad-gui`) is refused for sourced assemblies
(`UNSUPPORTED_STAGE`) because it would replace that verified state.

**What verification checks.** In addition to the primitive checks below:

- Every embedded source is the producer's saved objects under one bijective rename:
  identical types, properties, dependencies and expressions. No object reference
  may leave its own source. The only accepted differences are labels set by the
  adaptor, visibility, mounts appended to the Body, the sketch attacher engine
  FreeCAD selects on copy, property status bits and last-digit origin-helper
  placements.
- Mount expressions must match the exact millimetre-qualified affine grammar.
  FreeCAD silently accepts unitless text on these coordinates, so a unitless
  expression with the right value is still rejected.
- Only the controlled ground and joint proxies may exist, no link may name an
  external file, and the GUI view state must be exactly the minimal record.
- Component placements, mount frames and connector coincidence are compared with
  an independent closed-form transform. Volume and area must equal the producer
  receipt. The centre of mass must equal the transformed centre measured on the
  captured copy alone.
- World bounds are compared **exactly** only when the pose is a signed axis
  permutation (quarter turns). After any other rotation a pocket may remove the
  corners that define the box, so bounds are only checked to lie inside the
  rotated producer box. That check is labelled containment, not equality.
- Every payload member of the saved assembly is bound to independent evidence
  or to a stated structural rule, and the archive may contain nothing else:
  - Embedded BREP shapes, for every history feature (not only the tip), must equal
    the retained producer's bytes. The only exception is that a producer `-0.0…`
    token may appear as `0.0…` at the same position, the one change FreeCAD makes
    when copying.
  - Element maps are bound by structure: the same section skeleton and child
    records, the same postfix tables (object tags remapped, string-hasher
    identifiers masked), the same postfix-table relationships, tags that name only
    the same source's objects, and string references inside the merged table.
  - A datum shape must be the fixed planar template at its saved mount placement.
  - Link placement and scale lists must be empty.
- The source files and their retained copies must keep their digests. Workflow
  resume reuses an assembly only while its sources are unchanged.

## Verification and evidence

```bash
PYTHONPATH=src python tools/qualify_freecad_assembly.py
```

The default evidence root is `evidence/assembly-20260920`. Completed evidence is
never overwritten; choose `--directory` for another run. `--headless` omits the
optional GUI stage. The qualification script supplements the integrated CLI and
console paths with shared-part editing and fresh GUI-reopening checks.

Sourced assemblies have their own native qualifiers, which need a fresh
directory and never overwrite evidence:

```bash
PYTHONPATH=src python3 tools/qualify_freecad_assembly_sources.py \
  --directory evidence/assembly-sources --executable /path/to/freecadcmd
PYTHONPATH=src python3 tools/qualify_freecad_assembly_sources_gui.py \
  --assembly evidence/assembly-sources/workflow/assembly/batch-0/attempt-0001 \
  --directory evidence/assembly-sources-gui --gui-executable /path/to/freecad --xvfb /path/to/Xvfb
```

The first runs a workflow of five part producers (two with colliding native
names, a corner-removing pocket, a circle Pad and a literal Body) and two
assemblies. It then checks:

- resume reuse and invalidation after a source byte changes;
- a literal analytic volume, area, bounds and centre-of-mass oracle;
- that rotated corner-pocket bounds are containment only, while quarter turns are exact;
- deliberate convention changes;
- a shared-source native edit with a fresh reopen;
- a relocated copy opened with every input unavailable;
- saved-file tamper and malformed-archive negatives, and native reopening of tampered copies;
- that the GUI capture stage is refused.

The second uses a private display for first-open visibility, the native joint
editor, embedded sketch editing, a native edit with save and reopen, and the
child-side behaviour of the joint panel's simple Offset field.

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
closed-loop or redundant constraints, face or edge selection on modelled parts,
mixing primitive and sourced parts, subassemblies, imported STEP or third-party
FCStd parts, external document links, live console or design-study execution,
interference checking, contact, motion and multibody dynamics are unsupported.
Sourced parts are limited to verified single-Body phase-one publications;
mounts attach to the Body origin XY plane with signed-axis orientations.

FreeCAD re-encodes the element maps of the second and later sources against the
assembly's merged string hasher, and even regenerates them on recompute. The
encoded name entries inside those maps are therefore counted and isolated, not
decoded. Decoding them would need FreeCAD's internal element-map encoding. The
qualified route does not reference elements by mapped name: sketches and mounts
attach to origin planes, joints reference whole mount datums, and sources may
not contain sub-element references. A same-structure exchange of name entries
leaves geometry, placements and the solve unchanged, and recompute regenerates
the maps. Before the first recompute, however, such an exchange can make a mapped
edge name resolve to a different edge, which would affect a new name-based
reference created in the GUI before recomputing. The source envelope is applied to new assembly
admission only; the phase-one part verifier itself is unchanged. `expectedDegreesOfFreedom: 0` describes the fixed rooted tree; it is
not a reported numerical DOF diagnostic from FreeCAD. Solver success and the
perturbation tests establish the qualified static cases, not universal solver
convergence. This adaptor does not reverse-sync manual FCStd edits into authored
JSON; use updated input for a new verified publication.

Public installed API usage was inspected in FreeCAD's
`Mod/Assembly/AssemblyTests/TestCore.py`, `JointObject.py` and
`assembly.solve.__doc__`. These supplied API names, reference conventions and
solver status meanings. The adaptor calls the installed implementations; it
does not copy their solver or joint implementation source.
