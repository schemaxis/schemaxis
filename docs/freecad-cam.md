# Checked three-axis milling

The `schemaxis.freecad.cam/1` route makes an editable FreeCAD CAM Job, declared
stock, centre-cutting flat endmills and pointed drills, their controllers, ordered
facing, closed flat-floor pockets and drilling operations, and a LinuxCNC program. Its independent
verification replays the actual posted moves against the captured CAD solid.
A nonempty path does not establish that a part is finished.

Start with [the millable enclosure workflow](../examples/schemaxis/freecad-cam-workflow.json).
This explicitly different enclosure has R2 internal cavity corners and a D3
cutter. A finite-radius cutter cannot finish sharp internal corners. Preserve the
original design and change the manufacturing design explicitly, use a suitable
process, or accept a stated residual-volume allowance for roughing. The
[standalone machining document](../examples/schemaxis/freecad-cam-enclosure.json)
uses the supplied millable STEP fixture. The workflow generates the same design
as an editable native model before handing its geometry to CAM.

For two cutter sizes at the same hole centre, use the
[counterbore document](../examples/schemaxis/freecad-cam-counterbore.json) or its
[CAD-to-CAM workflow](../examples/schemaxis/freecad-cam-drilling-workflow.json).
The large cutter stops 2 mm below the top; the smaller cutter reaches 8 mm.
Their removal is the union at each depth, rather than the largest diameter
extended to the deepest cut. The
[cycle variant](../examples/schemaxis/freecad-cam-cycles.json) demonstrates dwell,
chip-breaking and feed-retract, returning to the first-used cutter after a change.

Lengths are millimetres, spindle speed is rpm, feeds are mm/min and quality
limits are mm³. Source units describe the file; checked volume, bounds and
centre of mass use millimetres after conversion. Frozen FCStd admission reads
stored BREP geometry without restoring producer proxies. STEP uses the same
bounded geometry-source contract as technical drawings. Source modelling
history is not recovered by this geometry handoff.

The work origin is the centre of the blank's top face, G54, with Z up. The blank
has the exact source XY bounds and bottom, plus the declared top allowance.
Facing removes that allowance before pocketing. A pocket's `floor` is an
interior source-frame point on exactly one upward-facing horizontal face; native
face indices are resolved from geometry. Pocket depth follows that selected
floor. `stepDown` and the fractional `stepOver` control passes, while `clearance`
and `safe` are positive work-frame traverse planes. Feed, plunge, tool geometry,
reach and spindle data must be chosen for the actual machine and material.

Use either the legacy `tool` object or a `tools` array of one to eight tools.
Each named tool has an `id` and `kind`. A `flatEndmill` uses the same geometry
and cutting data as the legacy flat tool. A `drill` adds conical-tip geometry and
requires an explicit physical-clearance policy, described below. With the named array, every operation selects
its `tool` by that ID and every declared tool must be used. Definition order
determines contiguous native tool numbers; operation order determines tool
changes. Native object names, tool-library paths, UUIDs and scripts are compiled
internally. A single `tool` also supports drilling without per-operation IDs.

A `drill` operation declares `locations` and `bottom`. Locations are source-frame
XY millimetres: an `explicit` list of `centres`, a centred rectangular `grid`
with `columns`, `rows`, `xPitch`, `yPitch`, or a `pitchCircle` with `count`,
`radius`, `phase` in degrees and optional `centre`. A layout contains at most
256 distinct separated holes. `bottom` is source Z, never a positive depth or
native edge index. Every centre must resolve to the intended inward cylindrical
source hole with the selected cutter diameter and bottom; no failed target may
be silently skipped by native CAM. Concentric steps belong to separate operations.

`cycle.kind` selects `drill` (G81, default), `dwell` (G82 with positive `dwell`
seconds), `peck` (G83 with positive `peck` millimetres), `chipBreak` (G73 with
`peck`), or `feedRetract` (G85, feed back to R then rapid to the return plane).
Only the parameter used by that cycle is allowed. `cycle.return` is `initial`
(G98, default) or `retract` (G99). `setup.clearance` supplies the pre-cycle plane;
`setup.safe` supplies R. The independent reader obtains the G98 initial height
from actual preceding NC motion, preserving it while the cycle remains active
and resetting it after G80 or ordinary motion. G99 returns to R.

Cycle expansion uses unremapped LinuxCNC 2.9.4 defaults. Both peck families use
its fixed 0.010 inch (0.254 mm) backoff: G83 retracts to R and re-enters above
the previous cut bottom; G73 makes that short backoff directly. With a small Q
the backoff can rise above R. Partial final pecks retain the exact requested
bottom. Dwell is programmed time; no machine travel-time or acceleration model
is claimed. See the pinned
[controller implementation](https://github.com/LinuxCNC/linuxcnc/blob/v2.9.4/src/emc/rs274ngc/interp_cycles.cc)
and [native generator](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/CAM/Path/Base/Generator/drill.py).

Without `setup.toolClearance`, the original flat-tool rules are unchanged:
cutting length reaches the entire blank, including a tool used only shallowly,
and the shank is no wider than the cutter. The explicit physical policies below
admit shorter flat tools, larger shanks, pointed drills and declared holders only
after the corresponding complete geometry checks. The pre-sized blank still has
zero side/bottom allowance. Exterior detachment, fixtures, machine kinematics,
ramps/helices, tapered/ball cutters, probing, adaptive roughing and other
postprocessors remain unfinished families. This route does not certify a machine
setup.

## Pointed depths and complete tool geometry

A named `kind: "drill"` declares `diameter`, included `tipAngle` in degrees,
`cuttingReach`, total physical `length`, and `rpm`, `feed`, `plunge` and optional
integral `flutes` (two by default). The tip frame has its origin at the physical
apex and +Z toward the spindle. Cone height is radius/tan(tipAngle/2); it must be
positive and below cuttingReach, which must be below length. Cutting reach is an
explicit declaration, separate from native total length. The current standard
drill has constant full radius above its cone. An optional `shankDiameter`,
strictly smaller than diameter, selects the finite SCXReducedDrill profile: full
radius from the cone junction to cuttingReach, an actual annular shoulder there,
and the smaller cylindrical shank from that plane to the physical bit end.
This explicit profile uses the carried tool extension and `open-cam.FCMacro`
launcher in the editable bundle. Open it with the carried separate preference
profile. The extension must be registered before opening the native document;
a bare FCStd opened without that dependency cannot regenerate this tool.
Automatic Schemaxis use compares the complete extension and launcher with its
installed bytes before importing code or opening the document. A smaller
noncutting envelope is never inferred from a scalar receipt or standard drill.

A pointed `drill` operation requires `depthReference`. With `tip`, `bottom` is the
physical apex Z; with `fullDiameter`, it is the full-radius cone junction Z. Both
are absolute SOURCE-frame coordinates. A D3, 120 degree drill has cone height
sqrt(3)/2 mm: fullDiameter at Z=7 places its tip at 7-sqrt(3)/2, whereas tip at
Z=7 puts the junction at 7+sqrt(3)/2. These are different physical cuts. If the
apex goes below the blank, positive `throughClearance` must cover that travel and
the prospective posted-word rounding interval. It does not establish clearance
from a fixture below the part.

Source admission distinguishes an actual blind cone with its cylinder, a cone
clipped by the stock base, a shallow conical spot, and a full-diameter through
hole whose tip is below stock. It checks actual inward surface, angle, junction,
rim and intended axial coverage, followed by containment of the COMPLETE cutting
sweep in the desired source void. A counterbore can truncate an upper pilot wall
only when the retained real cone/junction and complete swept-void check qualify
that composition. Split circular rims are assembled from a complete connected,
non-overlapping cycle of actual source edges before one existing SDK edge is
selected. Missing, repeated or overlapping edges refuse. Split cone faces and a
wholly swallowed pilot with no qualifying actual source face remain required
unfinished variants; receipts or samples do not stand in for those faces.

Either flat or pointed tools can declare `holder` with `stickOut` and one to eight
ordered `steps`, each with `diameter` and `length`. The holder front is stickOut
above the tip; it must be at or beyond cutting reach and strictly below total
bit length, leaving positive insertion. Steps are contiguous and must enclose all
overlapping bit material and cover its end. Their complete outer geometry and
ALL noncutting bit material participate in clearance checks. There is no omission
of an interval between cutting region and holder. The fixed built-in endmill
profile has a 0.01 mm axial transition overlap; a wider shank starts noncutting
material below the declared cuttingLength, and that actual transition is checked.

## Physical stock-clearance policy

Pointed tools and holder declarations require `setup.toolClearance`. Choose one
of the two closed forms:

| Policy | Required positive gap | Geometric meaning |
| --- | --- | --- |
| `kind: "aboveBlank"` | `axialClearance`, mm | Every noncutting and holder region stays above the ORIGINAL allowance-inclusive blank top plus this gap along admitted motions. Earlier cuts provide no access credit. |
| `kind: "evolvingStock"` | `minimumSeparation`, mm | Every complete noncutting and holder sweep has no material overlap and at least this native distance from stock remaining before the motion. Earlier actual cuts can provide access. |

The ordered policy checks all expanded pecks, returns, reentries and active-tool
assignments, including returning to a previously used tool. Only actual feed cuts
remove stock. Rapid cutting occupancy must have no positive-solid intersection
with prefix stock; nominal cutting-wall contact alone is permitted here. Rapids
and tool installation receive ZERO removal credit. Lower ordinary rapid moves
require complete known start/end poses and the full physical checks; their
parser admission alone does not establish access. Noncutting and holder material
always retain the positive gap, so a same-radius shank in a newly cut nominal
bore has zero wall separation and refuses.

Pointed cutting is vertical. Flat cutting admits finite vertical and planar
linear/circular sweeps. A restricted same-XY descent can use only already-earlier
cylindrical material of that SAME cutting motion when proving following guarded
material; future cuts and conical lateral cutting never receive that credit.
Prior wider-cavity access does not prove that a currently represented tool can
usefully rely on this within-motion credit. The explicit reduced-shank example uses this credit with its actual smaller
noncutting profile; disabling that credit produces a collision in the controlled
qualification. A prior wider cavity alone is not counted as that discriminator. The actual initial machine and
tool-changer trajectory is unknown: proof begins at the first complete programmed
clearance pose and covers declared subsequent tool assignments and moves.

Fresh native tools must show their complete physical profiles. Set comparisons
prove cutting credit lies inside the actual bit and that credited plus guarded
regions cover the complete bit and every holder section. Current desired voids,
recorded dimensions and mutable readbacks do not establish that authority.
Ordered material replay updates actual prefix stock after each checked feed and
compares the final remaining solid with the captured target. No quality allowance
turns a positive physical collision into permissible boundary contact. Native
distance and numerical balance are empirical kernel checks, not a certified
machine clearance or a rigorous bound on all geometry errors. Aggregate motions,
primitives, topology and Boolean/distance work are bounded; excessive work refuses
before publication rather than skipping a target or physical check.

Verification binds saved Job ownership, cutter/settings, geometric targets,
operation order and persisted paths to independently parsed posted NC. Only
reviewed native proxy classes and their bounded, closed serialised states are
admitted; the saved tool's state must match the declared cutter and built-in
endmill identity. Only
finite absolute-XYZ, mm, XY-plane, G54 motion is admitted. A fixed
preamble explicitly sets incremental IJ arc centres, feed per minute,
exact path mode, cancelled cutter/cycle state and cleared temporary offsets.
Tool changes require an explicit spindle stop. XY rapid moves require known
start and end positions above the declared safe plane under the original policy.
The explicit ordered policy admits lower known-pose moves only after its complete
physical prefix-stock proof. Horizontal lines and circular arcs
use an ideal constant-radius program model: posted arc endpoint radii must
agree within 0.0000001 mm, matching the CAD kernel's geometric scale and
exceeding the eight-decimal posting quantisation. The separately persisted
six-decimal native Path representation admits at most 0.000002 mm radius
disagreement for identity comparison; it never supplies material replay.
Endpoint and centre comparisons use absolute rounding budgets, and a redundant
native XY-plane K word must be zero. These checks do not bound a controller's
arc interpolation, servo following or actual machining error. Lines and arcs
with distinct endpoints closer than 0.000001 mm are refused; only exactly
equal XY endpoints denote a complete circle. Conflicting codes in one modal
group are refused rather than interpreted by choosing the last word. Lines and arcs
have continuous capsule/annular-sector coverage; vertical plunges have disc
coverage. For the original flat-tool policy, actual tip depths partition the blank into constant-coverage slabs,
which are subtracted in two dimensions and extruded. No sampled tool positions
stand in for material coverage. Every subtraction checks area balance and every
extrusion checks volume; untrustworthy kernel results fail. Independent CAD
cross-sections include every actual target Z boundary; their
area/moment integrals must match the captured solid volume and centre of mass.
Planar differences report excess stock and desired material removed. Oblique
walls, curved-Z surfaces and general surfacing remain unqualified. All absolute
observed area/volume balance discrepancies are accumulated in mm³
and added to each finish volume. The authored limits govern these conservative
assessed volumes; discrepancies are never subtracted or cancelled. Nonfinite and
grossly inconsistent results fail. This is numerical consistency evidence, not a
certified bound on every possible kernel error. These are numerical
CAD-kernel checks, not an exact arithmetic geometric proof. Fresh verification
uses current trusted code and a configured FreeCAD executable, never a command
path from an editable receipt; it reads shapes without opening CAM proxies.
Every fresh replay also reconstructs the installed builtin endmill in a new
native document and compares its full editable property, expression and
dependency graph, BREP topology/coordinates and resolved tool element maps.
The explicit physical-tool family instead uses finite complete solid unions and
ordered prefix stock as described above. Only tightly bounded double-precision
rounding and documented native cache or
presentation changes are normalised. Native surfaces must independently show
the declared flat end and full-depth cylindrical cutting edge. The initial
published document admits only the finite native property/extension vocabulary
and its named payloads; injected GUI state, external-link properties and foreign
expressions are refused. Geometry-only replay of an edited GUI document does
not certify its GUI state for subsequent restoration.

Named-tool and explicit physical-policy jobs additionally rebuild the complete current typed Job from the
captured source bytes before restoring a submitted CAM document. That comparison
binds every object, dependency, expression, proxy, complete string inventory,
element map and payload to one coherent trusted construction. Independent
observations and material receipts are witnesses, not source authority. Checked
native bytes are pinned before archive reads and after full comparison; a
private reopen copy must retain that same digest before use and afterwards.
The saved native Path writes six decimal places, so readback is compared through
that exact serialization. Eight-decimal posted words supply material replay;
their rounding bound does not become a geometry tolerance.

`cam-project.zip` contains the editable native document, a minimal isolated
`preferences.cfg`, an empty local tool-assets directory and reopening
instructions. Extract it, run from the extracted directory and launch
`FreeCAD --user-cfg preferences.cfg machining.FCStd`, then activate the CAM
workbench before editing/recomputing. That carries the qualified 0.00001 mm
LibArea curve accuracy, a global native preference that an FCStd alone does not
preserve. The Job separately retains its geometry tolerance. An arbitrary
existing FreeCAD session may have different global settings.
The profile keeps the extracted tool-assets folder local and records FreeCAD
1.1's optional asset-migration offer as handled, so activation does not move it.
Native operations remain editable: regenerate and repost after changing a tool
or cycle. Original verification belongs to the original typed intent and files.
General adoption of an externally edited CAM project's proxy and GUI history
is not supplied; express the changed intent in a fresh typed CAM document.

`machining.FCStd` retains editable native operations and controller;
`program.ngc` is posted LinuxCNC text; `remaining.brep`, `residual.brep` and
`gouge.brep` support inspection. `material.json` records continuous replay and
finish limits. `TARGET_GOUGED` requires correcting the toolpath/target or design;
`UNFINISHED_MATERIAL` requires investigating unreachable corners, missing
operations or excess stock. `UNSUPPORTED_TOOLPATH` requires a qualified motion
family. `TOOL_COLLISION` requires changing a motion, tool or prior cutting operation;
`TOOL_CLEARANCE` requires sufficient space for the complete noncutting/holder
envelope and its requested gap. Increasing a finish-volume allowance cannot
resolve either physical refusal. `RESOURCE_LIMIT` requires a smaller coherent
workload or another qualified strategy. `MATERIAL_REPLAY_FAILED` preserves a numerical failure rather than
silently accepting an uncertain part. Replan into a fresh output directory.


The [pointed-drill example](../examples/schemaxis/freecad-cam-pointed.json)
uses a D2, 90 degree physical cone, cuttingReach3, shankDiameter1 and length16
with a stepped holder. Its blind hole removes exactly22*pi/3 mm3 and has removed
Z centre -323/88 mm in the work frame. The
[two-job workflow](../examples/schemaxis/freecad-cam-pointed-workflow.json)
builds the finished solid before consuming its declared native publication.
Run `tools/qualify_freecad_cam_physical.py --directory <fresh-directory>
--executable <absolute-FreeCADCmd> --gui <absolute-FreeCAD>` from the checkout
with `PYTHONPATH=src`. This performs controlled synthetic qualification; it does
not adopt arbitrary edited CAM projects or certify real machine conditions.
