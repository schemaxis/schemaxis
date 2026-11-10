# Blender simulation caches

Declare a bake with `production.simulationCaches` when a saved rigid-body or cloth
study needs stable results when frames are reopened in a different order. The
supported modes are **rigid-body packed**, **cloth packed** and **cloth disk** on
the qualified Blender 5.2.3/e13b728c6880 runtime. This finite feature does not add
joints, motors, soft-body, Geometry Nodes simulation, fluids or volume caches.

```json
{
  "simulationCaches": [{
    "id": "physics",
    "kind": "cloth",
    "object": "Sheet",
    "frameStart": 1,
    "frameEnd": 10,
    "storage": "disk"
  }]
}
```

Place this array inside the existing `production` object beside the corresponding
`cloth` or `rigidBodies` declaration. The `object` is a logical cloth object ID;
leave it empty for the rigid-body world. Each ID and consumer is unique, with at
most 32 caches. The cache must cover the **complete production timeline**, within
1000 frames. This prevents rendering or sampling an implicitly unbaked interval.
The owning native scene, constructor, runtime and fingerprints come from trusted
construction; they are not authored strings or saved-receipt permissions.

Packed mode keeps baked data inside the scene publication. Disk mode publishes
owned `.bphys` files in `blendcache_0000/` beside `0000.blend` (and corresponding
folders for later visit basenames). Keep the scene and its declared cache files
together. Disk files have individual hashes and `simulationCache` artifact roles;
arbitrary external paths and inherited external caches are refused. Aggregate
limits bound files, decoded observations and captured inputs before acceptance.

Use the supplied examples:

- [Rigid freefall and fixed floor](../examples/schemaxis/blender-simulation-cache-rigid-packed.json).
- [Packed cloth with fixed corner pins](../examples/schemaxis/blender-simulation-cache-cloth-packed.json).
- [The same cloth with owned disk files](../examples/schemaxis/blender-simulation-cache-cloth-disk.json).

They use `prepareOnly`, so demonstrate editable native physics without rendering.
Run a document through the normal `schemaxis run` route, then use
`schemaxis verify` on its output directory with the qualified Blender configured.
Native cache qualification is available through
`tools/qualify_blender_caches.py --blender /absolute/path/to/blender --output NEW_DIRECTORY`.

Verification reconstructs the declared source and physics independently, bakes a
fresh reference and compares owned disk bytes **before opening a submitted scene**.
Packed/native data also needs complete indexed geometry across every cached frame
and physical parameter checks. A mutable cache manifest or a successful Bake
operator alone is insufficient. Edited geometry, gravity, mass, dependency bytes,
frame bounds or cache payloads require fresh construction and baking; changing
saved observations and outer hashes does not authorize stale data.

Change the authored simulation intent and build a fresh publication after editing
physics parameters. Reusing an old bake after changing parameters is refused. A cancelled bake has no accepted
completion; start a fresh output rather than treating partial cache files as a
publication. Disk caches are tied to this native solver/build, not a portable
interchange format. Retain the declared captured inputs needed for verification;
retiring an original path does not turn an edited replacement into source authority.

Rigid-body **disk** conversion is explicitly unsupported in this fixed runtime:
its native storage setter crashes before baking. Planning refuses that mode;
packed rigid-body mode remains available. This limitation is not a claim that the
wider rigid-body or cloth families are complete. Current first consumers require
static unparented mesh inputs with the supported physics/modifier dependency
closure; animated inputs, force-field collections and rest-shape overrides require
separate contracts.

The qualifier also exercises an adopted PNG material input in a cache-bearing
workflow after retiring its original producer directory. This is render-input
retirement: the colour input does not drive the simulated geometry. Cancellation
is requested only after a native-owned event marks the actual bake call, followed
by a fresh public construction and verification. Qualification results must be
read from their source-bound report; these controls are not implied by a manifest.
