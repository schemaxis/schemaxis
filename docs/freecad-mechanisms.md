# Prescribed FreeCAD mechanisms

`schemaxis.freecad.mechanism/1` turns selected fixed joints in a verified assembly
into native Revolute or Slider joints. It retains editable FreeCAD Simulation and
Motion objects and publishes a checked trajectory. Use it for hinge travel,
sliding components and serial mechanisms whose motion you already prescribe.
General joint types, loops, coupled constraints, dynamics, contact and collision
checking remain unfinished.

Start with [the quarter-turn example](../examples/schemaxis/freecad-mechanism.json),
[the slider variant](../examples/schemaxis/freecad-mechanism-slider.json), or the
[fixed assembly to motion workflow](../examples/schemaxis/freecad-mechanism-workflow.json).
The Studio **Prescribed assembly motion** starter exposes the source, authored
joint ID, kind, endpoint and duration. It uses the same typed document contract.

```json
{
  "version": "schemaxis.freecad.mechanism/1",
  "source": "verified-assembly/model.FCStd",
  "durationSeconds": 2,
  "intervals": 12,
  "framesPerSecond": 24,
  "motions": [{"joint": "hinge", "kind": "rotation", "end": 90}]
}
```

`source` identifies the actual verified fixed-assembly publication with its
producer packet. It must be named `model.FCStd`; an arbitrary FreeCAD file is not
admitted. Constructor packets can travel with `authored.json`, `plan.json`,
`built.json`, `verification.json`, `result.json` and their FCStd: their publication
identity may explicitly be the relative `model.FCStd`. Mechanism verification
relocates only that identity, validates the native constructor facts, rebuilds
from the typed intent and binds the complete saved document before opening it.
The repository's small own-native example packet demonstrates this contract.
Sourced history assemblies still need their verified producer run and provenance;
removing that dependency prevents re-verification, even though the native mechanism
contains copied geometry. Keep those runs when sharing a sourced mechanism.

Each motion names the source author's joint ID, such as `hinge`, rather than a
native name such as `Joint0`. A joint appears at most once. Other joints remain
fixed. Rotation endpoints are degrees; translation endpoints are millimetres;
duration is seconds. Displacement starts at zero and varies linearly to `end`.
The adaptor compiles that law to the native angular-radians or linear-mm formula;
there is no authored formula or Python field.

Positive displacement follows the parent connector's local Z axis. Rotation
uses its right-hand rule. For every child, the transform is parent world pose,
parent mount, fixed offset and clocking, prescribed motion, then inverse child
mount. A downstream slider therefore follows an upstream hinge's moving frame.
Offsets are not reapplied in world coordinates. The grounded component stays fixed.
These are rigid placement predictions; solids may intersect along the trajectory.

Duration defaults to 1 second (0.01–3600); intervals default to 12 (2–240); playback
rate defaults to 24 frames/s (1–120). `intervals` determines equally spaced sample
times, independently of playback rate. Rotation is limited to one revolution and
15 degrees per interval. A 90-degree motion needs at least 6 intervals. Translation
is limited to ±1000 mm. There must be a nonzero displacement somewhere. These
bounds keep native solving and verification finite; they do not establish
continuous collision clearance between samples.

A successful run publishes:

- `model.FCStd`: the native assembly with motion objects, restored to its initial
  pose after checking every frame;
- `motion.json`: units, constant-speed law, initial pose and N+1 inclusive time
  samples, each with row-major 4×4 component placement matrices.

The native engine supplies an additional duplicate initial frame before its
inclusive timeline. The published trajectory contains each requested time once.
It contains placements, not velocity/acceleration, stresses, reaction forces,
actuator loads or swept volumes. Opening the native file allows ordinary FreeCAD
editing; Schemaxis does not reverse-synchronise those changes into authored JSON.
Change the JSON and rerun to obtain a newly verified publication. Native direct
edits and fresh reopening are exercised separately in qualification.

Both configured FreeCAD batch and GUI launchers are required. GUI execution uses
its own Xvfb display, D-Bus session, preferences and data/cache/temp directories;
the private CAM migration preference refuses the startup offer. It does not
migrate user assets. Cancellation and the whole-run deadline cover native stages,
display startup, regeneration and host comparison checkpoints. Failure retains
logs and an incomplete/failed result where execution has begun; use a fresh output
directory after correcting intent.

Verification checks analytic connector composition against actual native frames
and each component's actual volume, solid count and moving centre of mass. It
checks native timing, formulas and joint identities, then repeats in a fresh GUI
process. Submitted mechanism documents and proxies are never opened by verification:
current trusted regeneration supplies the comparison. Native object/property and
dependency membership, proxies, GUI settings and payload contents remain bound.
String IDs and object IDs are compared under named identity correspondence; the
entire string inventory is included, even entries unused by maps. GUI material
payload filenames can change with allocation order, so complete bytes are bound
to their provider/property identity. Source constructor allocation UUIDs and
creation/save times are constructor allocation metadata. Default GUI root ranks
follow native object IDs and are bound under the same named-object bijection,
with root ordering retained; edited ranks are refused. Constructor GUI decoration
is regenerated on the same private transport, preserving its visibility/proxies.
The camera is set deterministically from component bounds before saving.

`UNKNOWN_JOINT` requires a current authored joint ID. `DUPLICATE_MOTION` requires
one record per joint. `MOTION_RESOLUTION` requires more intervals or a smaller
rotation. `UNSUPPORTED_SOURCE` requires the complete admitted source packet and
matching native state. `VERIFICATION_FAILED` rejects changed motion, geometry,
proxies, maps, views, timing or publication bytes. Keep the failed evidence and
native logs; refreshing a file hash cannot establish semantic correctness.

This is a prescribed open-tree mechanism milestone. The broader
[FreeCAD completion inventory](adaptor-strategic-completion.md) remains open.
