# Continue an imported solid as an editable Body

A `bodySeed` may be the final Body output, including a sourced assembly component;
subsequent machining features are optional.

Use `bodySeed` when a checked solid import is your starting stock and you want
native PartDesign features, rather than a separate Part boolean result. Declare
an empty `body`, then make `bodySeed` its first member with `body` and `source`
inputs. Continue that seed with ordinary Body sketches, Pockets and supported
ordered features. Select the final solid tip as `output`.

`importMesh` retains the original admitted STL and optional linked refinement;
`importSTEP` retains the original admitted STEP. They keep their editable source
Placement. The seed links to the selected import output, and its Placement follows
that output through a compiled native expression. Authored expression strings,
native helper classes and arbitrary property dictionaries are unavailable.

A seed must start its Body. It cannot consume a member of another Body, reseed an
existing history or follow a sketch. The legacy `readSTEP` reader cannot appear
in a seeded graph: use checked `importSTEP` with explicit units and expectations,
or `importMesh` with explicit units. Existing arbitrary imported FCStd documents
are not accepted as this typed import route.

## Three coordinate systems

The import's orientation, position and clocking place its solid in **Body-local
coordinates**. Sketch and feature frames in that Body use those same coordinates.
An optional Body `frame` gives a world origin, local X direction and normal. The
right-handed frame then places the completed Body into the main part document.
Frame coordinates are millimetres; directions are dimensionless orthogonal unit
vectors. Defaults are an identity Body frame and the ordinary import defaults.

The main route exports the completed Body in world coordinates to STEP and STL.
Its native publication retains the source import, original asset, seed, sketches,
features and Body layout. Assembly component placements and named mounts are
**Body-local for every admitted Body source**. A component instance applies its
own frame to the completed local shape. The producer Body's layout remains in the
copied source history but is not applied a second time to component geometry.
A mode that combines both source-world and component placement is not provided.

For example, a stock origin of `[3,4,5]`, followed by a Body origin `[7,8,9]`,
places the stock through both transforms in a part export. In a sourced assembly,
the component frame places the stock at its Body-local origin `[3,4,5]`; named
mount positions are measured in that same local frame. With rotations, apply the
source frame first, then the Body or component frame. The order matters.

## Editable and portable history

A completed sourced assembly retains each admitted source FCStd and typed source
intent, plus original STL or STEP bytes when the source uses checked imports.
Pure typed histories retain an empty original-asset set. Verification can reconstruct that captured
input after the producer run and original import file have been removed. It
checks the whole saved history, source links, expression roles, included assets,
string inventory, topology maps and payloads against trusted fresh construction
before restoring a submitted source. Receipt geometry is a witness, not authority.

Original assets are admitted as bounded geometry; included files do not provide a
way to load arbitrary scripts or native objects. Changed cached shapes, missing
embedded originals, extra archive members and inconsistent unit/frame metadata refuse
verification even when publication hashes are refreshed. Replacing every captured
input and authored pin creates a different input; this is not authenticated proof
that the replacement was produced by the historical source run.

Native source Placement and Body layout can be edited after reopen. A changed
native design no longer verifies as the original authored run. Retain that run,
update the typed source intent and build a new run. A saved FCStd edit cannot
replace the typed source intent or original asset authority for this history
route. This route does not recover a
parametric import feature history hidden inside STEP or STL. STL remains faceted;
scan repair, surface fitting and broad reverse engineering remain unfinished.

## Adopt a saved STL or STEP checkpoint

Capture a stable original file with the shared input command:

```bash
python3 -m schemaxis input adopt saved/casting.stl snapshots/casting-001
```

Place the printed `reference` object at the checked `importMesh` node's
`options.file` inside a workflow operation. The same workflow-only position is
available on checked `importSTEP`. Keep the existing explicit units, orientation,
placement and STEP expectations. The snapshot must contain one complete file;
directories, file sets, legacy `readSTEP` and FCStd history files are outside
this admission policy. The checked importer still validates the selected bytes.

The workflow pins the snapshot digest, rechecks it on consumption and verifies
it after execution. A changed file needs a deliberately adopted new snapshot
and updated workflow; it cannot silently reuse the previous result. STL keeps
faceted geometry, and STEP carries solid geometry without the source feature
history. Adoption does not infer units or repair geometry.

## Scope and recovery

Portable assembly sources include typed Pad/Pocket Bodies, the separately
admitted ordered Body history families, and checked import or typed Part-solid
seeds. See [portable Body histories](freecad-body-history.md) for capture,
retirement, repeated saves and the qualified cases. New history operations do not
automatically acquire assembly-source support. The main part route also accepts
supported typed Part solid sources. Ordinary typed Bodies also accept an [explicit Body frame](freecad-body-frames.md). A direct Draft Wire-to-Body bridge,
source-world assembly mode and
arbitrary foreign FCStd history are separate missing capabilities. These examples
and checks do not establish whole FreeCAD completion.

If a seed is rejected, check first-member order and external-solid ownership. If
an import is rejected, inspect its units, topology, winding or STEP expectations;
conversion is not a repair operation. If a saved file differs from trusted
reconstruction, retain the failed file and rebuild from updated typed intent.
Do not replace verification records to make a changed design look unchanged.
