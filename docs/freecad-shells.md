# Uniform walls and native shell histories

`shell` turns a current Body solid into an open, uniform-wall part with a native
`PartDesign::Thickness` feature. Specify wall `thickness` once and identify the
faces to remove as `openings`. It is useful for housings, cups and through-tubes.
The [shell enclosure](../examples/schemaxis/freecad-shell-enclosure.json)
combines this intent with attached mounting bosses, a constrained fastening grid,
native drilling and a second Body's slotted lid. One named wall dimension controls
the side walls, floor and lid thickness; editing it moves the attached bosses
through their native floor-support links.

## Wall and opening intent

Thickness is positive millimetres, default 2. Supply at least one opening, for
example `[{"face":"top"}]`; top and bottom together produce a through-tube.
Each opening identifies an outward Cartesian direction: top/bottom, left/right,
front/back. Optional `position` is outermost (default) or innermost among planar
faces pointing in that direction. Selection requires exactly one extreme face.
Missing, equally extreme or duplicate resolved faces fail explicitly; no face
index, first-face assumption, anchor or attachment offset is authored here.

`side: inward` (default) preserves the exterior and offsets the remaining walls
into the stock. `outward` preserves the original interior and grows the exterior.
`corners: sharp` (default) intersects offset faces; `rounded` joins outward convex
offsets with arcs. The native algorithm can produce the same geometry for both
join choices on inward offsets, while retaining the selected join intent.
`intersectionHandling` defaults to false and enables native intersection handling
when true; it does not guarantee that an arbitrary self-intersecting offset works.

`drive.thickness` accepts the existing affine native length-driver contract;
omit the literal thickness when driving it. The published FCStd retains a real
native thickness property/expression, source/opening links and Body current tip.
Following profiles can attach to its cavity floor or remaining planar walls.
Each feature must still leave one valid positive-volume solid. Separate Bodies
remain independent; one selected final tip is exported.

## Verification and useful limits

Build and fresh native reopening read wall settings, source and actual opening
links, plus a measured source face inventory. Host code independently resolves
the opening intent from that inventory, checks exact membership and compares
saved XML with native observations. Settings and relationships are checked even
where two settings happen to produce equal shapes. STEP is reread; the existing
STL signed-integral/closure/centre/bounds checks retain their explicit budgets.
STEP and STL carry geometry and lose the editable wall history.

`tools/qualify_freecad_shell.py` uses independent box/cylinder/offset-volume
integrals, neutral STEP wall/void/bounds checks, rounded-corner cylinder/sphere
radii, a cross-family enclosure, native dimension edits/save/fresh reopening,
refreshed-digest property/link attacks and workflow invalidation. A 40×30×20 mm
box with a top opening and 3 mm inward walls has volume
40×30×20−34×24×17 = 10128 mm³. Both top and bottom openings leave 7680 mm³.

This is uniform native Skin thickness, not general surface sewing, variable
thickness, sheet-metal bends, automatic draft or arbitrary offset healing.
Directional planar openings share the current frame-selection limits; curved or
rotated opening-face predicates and automatic topology repair remain open. Large
thicknesses, tight radii and complex intersections can fail in the kernel after
host admission. Use explicit cavity/Pocket modelling when floor and side-wall
thicknesses must be independent. The broader [family inventory](freecad-capabilities.md)
continues to track unfinished application workflows.

Public API basis: [FreeCAD Thickness](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/PartDesign_Thickness.md)
and the [stable native Thickness API](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/PartDesign/App/FeatureThickness.cpp).
