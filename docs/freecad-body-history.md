# Portable editable Body histories

Use a typed part publication as a sourced assembly component when you need its
editable history after the producer project is unavailable. The assembly retains
the source FCStd, complete typed source intent and any admitted original geometry.
Pure Pad/Pocket histories require no original asset files. This route does not
accept arbitrary foreign FCStd documents or infer a recipe from their shapes.

The existing `schemaxis.freecad/1` part route and
`schemaxis.freecad.assembly/1` assembly route need no new document version. A part
must select the final solid tip of a Body. The complete authored document remains
in the captured history, including other Bodies and parameters; only the selected
Body supplies component geometry. Supported cases include origin-based
Pad/Pocket parts, separately admitted ordered histories, and
[checked imports or typed Part solids feeding a Body seed](freecad-body-seeds.md).
Each newer native feature family still needs its own source qualification.
Helix and arbitrary feature/property extensions are not implied by this guide.

## Capture and place a component

In a workflow, refer to the producer's native artifact, rather than its geometric
STEP or STL export. For the part route the native artifact is index 2:

```json
{
  "version": "schemaxis.freecad.assembly/1",
  "parts": [{
    "id": "housing",
    "source": {"$artifact": "housingProducer", "index": 2},
    "mounts": {"base": {}, "lid": {"position": [0, 0, 20]}}
  }],
  "components": [
    {"id": "fixedHousing", "part": "housing"},
    {"id": "spareHousing", "part": "housing"}
  ],
  "grounded": "fixedHousing",
  "joints": [{
    "id": "sparePlacement", "type": "fixed",
    "parent": {"component": "fixedHousing", "mount": "base"},
    "child": {"component": "spareHousing", "mount": "base"},
    "offset": [80, 0, 0]
  }]
}
```

The surrounding workflow must contain `housingProducer`. A standalone assembly
can instead use the native path from an existing verified part publication.
Planning validates that publication and captures its typed recipe during the run.
An older assembly missing the complete typed record must be rebuilt from its
producer while that producer is still available; missing information cannot be
recovered by changing receipt fields.

Component placements and mount positions use the selected **Body-local** frame.
The producer's Body layout remains in the copied history. It is removed exactly
once when deriving local component geometry, then the component frame places
that geometry in the assembly. The part's STEP/STL exports use world coordinates.
For seeded Bodies, source Placement acts first, followed by either Body layout
for a part export or component placement for an assembly. These rotations need
not commute. Ordinary unseeded Bodies can also declare an explicit
[Body-to-world frame](freecad-body-frames.md); the component still uses local geometry. A mode combining
source-world layout with component placement is also unfinished.

## Reopen, retire inputs and resume

Standalone assembly verification reconstructs every captured source from typed
intent and admitted original bytes, then binds the complete saved source and
copied assembly. It can operate after all producer directories and original
STL/STEP files have been removed. It does not need their original STEP/STL
exports. Changed bytes later placed at an old producer path cannot override the
assembly's owned capture during standalone verification.

Workflow resume additionally checks input identity. Missing original inputs may
reuse a successfully verified, complete retained capture. An original still
present with changed bytes refuses reuse; deliberately update the input and run
a new workflow. Keep the complete assembly publication and its retained inputs,
not only `model.FCStd`. Native-only inspection and provenance verification are
different operations.

Imported originals remain bounded geometry with explicit units and frames. A
pure history has no original asset members; it does not gain permission to use
included files. Source records, object ownership, proxies, links, expressions,
all persistent strings, topology dictionaries and shape payloads must bind to
trusted construction before any submitted source is restored. Scalar volume or
bounding-box receipts are witnesses and cannot replace that authority.

## Saves, edits and execution budgets

An unchanged FreeCAD save can change persistent topology encodings. For this
explicit Body-local path, verification may advance a freshly rebuilt reference
through installed FreeCAD close/open/recompute/save transitions. Each candidate
must preserve the complete indexed native geometry and match the submitted
archive as one whole state. Verification never restores the submitted document
to discover a matching state, combines fields from different states, or strips
dictionary flags. An observed repeated state stops with a structured refusal;
it is not proof that every possible future SDK state was exhausted.

All source reconstruction and copied-assembly checks share the standalone
verification budget of 120 seconds, including reference construction and saves.
Tighter caller deadlines and cancellation remain effective. The normal scheduled
construction default is 300 seconds. A six-source, seven-instance qualification
completed construction in about 165 seconds and standalone verification in about
36 seconds on its recorded machine; these timings are evidence, not a runtime
promise. The same construction with an explicit 120-second limit timed out.
Scheduled execution currently repeats complete source verification at several
boundaries, so large histories may reach the budget even when individually valid.

Native parameters remain editable after reopening a copied assembly, and shared
instances update together. A design edit changes the result: preserve the old
run, update typed source intent and create a new verified publication. This route
does not adopt arbitrary native edits back into authored JSON. If unchanged saves
cannot match a trusted state within the budget, preserve the failed packet and
rebuild from typed intent; do not replace verification receipts.

## Reproduce the focused qualification

From a source checkout, with an installed Schemaxis environment or `PYTHONPATH=src`:

```bash
python3 tools/qualify_freecad_body_history.py \
  --freecad /path/to/freecadcmd \
  --freecad-gui /path/to/freecad \
  --output-directory /path/to/new/body-history-proof
```

The output directory must be new. `--examples-directory` selects another copy of
the public examples. Supply `--freecad-gui` to exercise the private GUI route explicitly; without
that option an existing configured GUI may still be selected. The report records
whether an explicit GUI was requested. The tool creates its own producers and copied STL,
compares literal local/world geometry, exercises repeated trusted saves and
copied parameter edits, retires its own inputs temporarily, and tests refreshed
dictionary/payload attacks before restoring every input. It records exact source,
runtime, recipe and input hashes; a failure remains false in `report.json`.
Run under your normal resource envelope. The existing
`qualify_freecad_body_inputs.py` separately covers pinned STL/STEP input adoption.

This qualification covers named cases and their authority/lifecycle boundaries.
Broad FreeCAD, assembly, feature editing and all Body layouts remain incomplete.
