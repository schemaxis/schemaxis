# Editable drilling and fastening locations

Use `hole` for round drilling, blind drill tips and head recesses in a native
PartDesign history. It consumes a Body-owned location profile and continues the
Body's current `base`. The native feature owns the drill diameter once; sketch
marker radii do not define it. The [drilling starter](../examples/schemaxis/freecad-drilling.json)
keeps grid pitch, drill diameter and counterbore depth as editable native drivers.
The [drilled enclosure](../examples/schemaxis/freecad-drilled-enclosure.json)
combines the cavity, four attached bosses, one grid/Hole feature and a second
Body's slotted lid. Its unchanged baseline housing volume is10128+60π mm³.

## Choose location intent

* `holeLocations` takes distinct local `[x,y]` centres in millimetres.
* `boltGrid` takes columns, rows, xPitch and yPitch. The rectangular grid is
  centred on `centre` (default `[0,0]`). Pitch is adjacent-centre spacing,
  including when a row or column contains only one centre. Native named pitch
  constraints drive the marker positions; editing pitch moves the holes.
* `boltCircle` takes count, pitch-circle radius, phase in degrees and centre.
  Phase is counterclockwise from local +X; count instances divide360 degrees
  equally. Native radius/phase constraints drive all marker positions.

The count limit is256 centres overall, with at most64 rows/columns or circular
instances. A location sketch must belong to its Hole's Body; it cannot make a
Pad or Pocket. Each centre must actually reach stock material. A fully
constrained ordinary `circle`, or typed `sketch` consisting of non-construction
circles, can also supply locations; construction geometry is ignored.

Profiles use the [history frame/attachment contract](freecad-histories.md#sketch-frames-and-attachments).
For a top-face sketch the default Hole `direction: backward` enters material;
`forward` follows its local normal. Explicit orthonormal frames permit angled
drilling. Direction is about the profile, rather than world Z. Checked planar
attachments reject ambiguous equally extreme faces.

## Specify drilling and head recesses

Lengths are millimetres. `diameter` defaults to4. `extent: throughAll` is the
default and omits depth. `extent: length` requires positive `depth`.
Blind drilling defaults to a flat tip. With `tip: conical`, `tipAngle` is the
included angle (default118 degrees). `depthMeasure: cylindrical` measures the
straight bore and adds the cone below it; `tip` measures to the cone apex and
therefore shortens the cylindrical section. Through-all drilling has no blind
tip or alternate depth convention.

| recess | Required extra dimensions | Meaning |
| --- | --- | --- |
| none (default) | none | Plain bore |
| counterbore | recessDiameter, recessDepth | Cylindrical head pocket from the entry plane |
| countersink | recessDiameter, recessAngle | Conical entry widening to the head diameter |
| counterdrill | recessDiameter, recessDepth, recessAngle | Cylindrical head pocket followed by a conical transition |

Recess angle is its included cone angle. Recess diameter must exceed drill
diameter. Blind bores must continue below the head recess and retain positive
cylindrical depth. Extraneous recess fields fail planning. Native countersink
depth is the derived distance to its virtual cone apex; users specify diameter
and angle rather than that redundant native quantity.

`drive` supports Hole diameter, finite depth, recessDiameter and recessDepth;
grid xPitch/yPitch and bolt-circle radius also accept existing affine native
length drivers. Phase remains an editable native angular constraint, without an
authored angular-driver contract. Patterns can repeat native Hole features.

## Persistence, verification and scope

FCStd retains Sketcher constraints/expressions, attachments, current-tip links
and a real editable `PartDesign::Hole`. Native build and fresh reopening read
back typed settings; host verification independently checks saved XML, closed
expression templates and constraint geometry. Neutral STEP volume, cylinder
axes/centres/radii and inside/outside points independently test the native
machining interpretation; STL is the existing checked tessellated handoff.
STEP/STL lose the feature history.

`tools/qualify_freecad_drilling.py` tests the documented layouts, blind-depth
conventions, head recesses, side and oblique frames, multi-Body continuation,
native patterns, two edits/saves/fresh reopening, refreshed-digest tampering and
workflow reuse/invalidation. A missed-material centre is rejected. Kernel
validity still depends on stock, overlap and chosen dimensions.

This is common unthreaded drilling, not every Hole mode: threaded/modelled
threads, tapered bores, standards-derived fastener tables and up-to-face extents
remain open. Live Body editing and reverse synchronisation remain open. The
[capability families](freecad-capabilities.md) retain the broader programme.

Public API basis: [FreeCAD Hole documentation](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/PartDesign_Hole.md)
and [native Hole public implementation](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/PartDesign/App/FeatureHole.cpp).
