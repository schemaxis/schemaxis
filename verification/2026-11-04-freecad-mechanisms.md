# FreeCAD prescribed mechanism subset — native qualification

Baseline is FreeCAD 1.1.4. Source commit `cc7b9293bd35c1b4f94bb9869f5fda8ff956d9bc`
passed the full mechanism qualifier and canonical native conformance with source
digest `sha256:32d8798056e393c314c2d22591fa6d49ef81af0febf643a8a2f3984e5892daae`.
These receipts establish the named subset below. Independent integration review,
generated Help, installed authoring and packaging remain separate gates. The
whole FreeCAD adaptor remains incomplete.

The registered `schemaxis.freecad.mechanism/1` route supports prescribed
constant-speed Revolute/Slider motion over a verified fixed assembly tree, with
saved native Simulation/Motion objects and inclusive sampled trajectories.
Constructor assemblies admit named top and bottom faces only; arbitrary planar
face connectors remain missing. Verified sourced assembly mounts support the
separately tested tilted and clocked serial chain. Other joint types, closed
loops, couplings, dynamics, contact and collision remain missing.

The constructor hinge has independently expected final origin `(-2,16,19)` mm
and rotation 180 degrees, from a 90 degree rotated ground and local offset
`(3,4,5)` mm. The slider variant travels 12.5 mm to `(-2,6,31.5)` mm. The sourced
serial project combines a tilted connector, a clocked 120 degree hinge and a
negative 10 mm slider; actual native endpoints match separately derived literal
transforms. Native per-frame component placements, volume, solid count and
centre of mass are checked against the host trajectory. Two actual native motion
and timeline edits were saved and reopened in fresh GUI processes.

The full qualifier rejects 14 constructor and 16 serial semantic mutations with
refreshed publication hashes, including native formulas, joint references,
initial poses, App/GUI proxies, GUI camera/rank/visibility, shape and material
payloads, DOCTYPE, unused SID entries and malformed element maps. Constructor
App and GUI proxy attacks are refused before any submitted source is opened;
only a trusted typed regeneration may enter the GUI. A globally configured
assembly GUI workflow passes source creation, motion, reuse and damaged-output
rebuild using a private display, D-Bus session, configuration, data and temporary
directories. Native receipts confirm the effective paths and CAM migration
refusal preference.

Canonical native conformance passes the hinge and slider baselines, publication
deletion/tampering, native runner timeout and pre-launch cancellation. Host
coverage includes strict GUI prolog parsing, complete canonical SID inventory,
structured archive faults, finite GUI dispatch and deadline/cancellation gates.
The FreeCAD host suite passed 228 tests at this implementation epoch.

The private evidence manifest records exact files, digests, runtime and bounded
job receipts. Earlier failed probes remain retained as failures, including source
attachment-engine, GUI visibility/camera and qualifier rank-selection defects.
Their repaired results are established by the frozen successful runs above;
historical receipts have not been relabelled as current.
