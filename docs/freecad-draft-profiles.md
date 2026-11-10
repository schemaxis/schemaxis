# Editable polygon profiles

Use `draftProfile` for a closed straight-edged outline whose vertices should
remain editable as a native Draft Wire. Concave L and U outlines compose with
Part extrusion and solid booleans. This complements constrained Sketcher
profiles; a Draft Wire has editable points rather than sketch constraints.

```json
{"version":"schemaxis.freecad/1","nodes":[
  {"id":"outline","filter":"draftProfile","options":{
    "points":[[0,0],[10,0],[10,2],[4,2],[4,6],[0,6]]}},
  {"id":"stock","filter":"extrude","inputs":{"profile":"outline"},
   "options":{"length":10}}
],"output":"stock"}
```

Supply 3–256 distinct local `[x,y]` points in millimetres, in boundary order.
The final edge closes automatically: omit a repeated first point. Clockwise
and counterclockwise outlines are supported. Nonadjacent edges may neither
cross nor touch; adjacent edges may continue straight but cannot double back.
An outline must enclose a nonzero area. Native geometry may still refuse very
small or poorly conditioned features after host validation.

`plane` defaults to `XY`. The other bases are `XZ` (local X along world X,
local Y along world Z, normal −Y) and `YZ` (local X along world Y, local Y
along world Z, normal +X). `angle` rotates the outline about its positive
local plane normal in degrees, then `origin` translates it in world millimetres.
The defaults are zero angle and `[0,0,0]`. Coordinates and origin components
are bounded to ±100000 mm, and angle to ±36000 degrees. These bounds do not
promise that every feature size is representable by the native kernel.

Part extrusion's `direction` is a world vector. For a YZ profile use
`[1,0,0]` to extrude along its positive normal. The
[turned U example](../examples/schemaxis/freecad-draft-profile-turned.json)
shows a translated, clocked YZ profile. The
[drilled L bracket](../examples/schemaxis/freecad-draft-profile-bracket.json)
and Studio starter **Editable Draft polygon bracket** retain the outline,
extrusion, cutter and subtraction as separate native features.

Open the FCStd, select **outline**, and edit its **Points** or **Placement** in
FreeCAD's Data properties. Recompute and save to update downstream native Part
features. A native edit is a changed design; the original Schemaxis receipt
does not certify it. Update authored intent and run in a new directory for a
new verified publication. STEP and STL retain geometry, not the Draft Wire or
its feature relationships.

Verification independently measures the saved source BREP's complete vertices,
straight edges, winding, area, perimeter and frame. It also constructs a fresh
typed graph using the configured installed FreeCAD runtime and binds every
saved property, proxy, expression, payload, string ID and topology map. An
unchanged native save may change persistent-name and exact BREP serialization;
the verifier can reproduce one complete first-reopen/save reference from that
fresh graph. It compares the entire reference state, with no mixed-field
fallback or tolerance for changed geometry. Submitted FCStd objects are never
restored during this verification. A configured command executable is required.

`INVALID_DRAFT_PROFILE` requires correcting the ordered boundary or its area.
`UNSUPPORTED_BODY_PROFILE` means this Draft profile cannot seed a PartDesign
Body; use the existing constrained Sketcher profile operations for Body histories.
Live preview and a sourced-assembly history bridge for Draft objects remain
unavailable. Curves, holes within one outline, Draft dimensions/text,
arrays/clones/transforms, snapping workflows and broader drafting remain missing.
This polygon milestone does not complete the Draft workbench or FreeCAD adaptor.

The fixed FreeCAD 1.1.4 native mapping uses the installed
[Wire constructor](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/Draft/draftobjects/wire.py)
and [public wire factory](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/Draft/draftmake/make_wire.py).
