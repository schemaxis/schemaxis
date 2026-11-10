# FreeCAD uniform-wall shell milestone

This review covers `shell` on the existing `schemaxis.freecad/1` route. It lowers
uniform wall/opening intent to editable native `PartDesign::Thickness`, using
the implemented Skin mode. Upstream Pipe/RectoVerso enum entries are documented
as unimplemented and are not exposed. Whole FreeCAD completion remains open.
The public [Thickness documentation](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/PartDesign_Thickness.md)
and [stable1.1.4 property API](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/PartDesign/App/FeatureThickness.cpp)
were checked independently of the adaptor implementation.

| Completion item | Reviewed delivery |
| --- | --- |
| registration/schema | Existing batch part version; typed thickness, opening selectors, side, corners, optional native intersection handling and persistent thickness driver. |
| semantics | Current-tip Body composition, positive dimension, exact-cardinality Cartesian planar openings, duplicate authored/resolved openings rejected. No numeric face indices or arbitrary native properties. |
| native mapping | Fixed native Skin/Value/Join/Reversed/Intersection/Base contracts; exact public property types and enum values; native source-face inventory and saved XML settings/links. |
| execution/qualification | Native box, cylinder, inward/outward, sharp/rounded, two-opening tube and side-opening controls plus shelled enclosure; independent neutral geometry/analytic integrals, native two-stage edits/save/fresh reopen, hostile refreshed-digest artifacts and workflow invalidation. |
| discovery/guidance/Help | Uniform-wall/hollow-cup phrases, reviewed operation and every new field, dedicated shell guide, generated reference/Help checks and maintained family inventory. Existing imported-STEP guidance addresses relocated without changing their meanings. |
| examples/Studio | Simple shell control, uniform-wall drilled two-Body enclosure and editable wall/floor/lid Studio starter. Separate floor/wall requirements retain explicit cavity/Pocket modelling. |
| tests/maintenance | Meaningful host invalid/selection/driver tests and native negative selectors. Native1.1.4 remains absorbed; editorial breadth25/abstraction75 retained as conservative subjective estimates, not API percentages. |

## Independent mechanics and lifecycle

The primary box has40×30×20 mm exterior dimensions. A3 mm inward top opening
removes34×24×17 mm of stock, leaving10128 mm³ and z centroid80472/10128 mm.
Top+bottom openings leave7680 mm³. The outward sharp control leaves14088 mm³;
the rounded outward control integrates the vertical rounded rectangle and
bottom cylinder/sphere offsets to12000+513π mm³. Its z first moment is
77340+1779.75π mm⁴. Eight radius3 cylinders and four radius3 spheres, independently
read from neutral STEP, check the rounded joins. Controls also check bounds,
centres of mass, wall points and cavity voids. A cylindrical cup and side opening
exercise different topology and directions. The optional intersection handler's
assignment/readback is covered; general self-intersection healing is not claimed.

The uniform-wall enclosure composes shell, attached mounting bosses, one
constrained grid/Hole and a second Body slotted lid. Native edits change wall,
stock height, boss height and bore diameter twice, save each result and reopen in
a fresh process. Independent volume/bores/voids, cavity-floor elevation and lid
volume prove propagation through the real native history. Its baseline geometry
matches the earlier independently dimensioned enclosure.

Saved native wall value/type, mode, side, join, intersection setting, opening link
and base-history attacks refresh publication digests and must fail semantic
verification. Missing planar, ambiguous extreme and duplicate-resolved opening
cases test explicit native refusal. Workflow checks require verified reuse,
changed-intent refusal and rebuilding after saved-history corruption.

General surface sewing, variable thickness, arbitrary rotated/curved opening
selection, topology repair, sheet-metal bends, draft and broad offset healing
remain open. Native kernel failures for complex offsets remain explicit; this
milestone does not imply whole PartDesign or FreeCAD completion.

## Executed result

The frozen `eb73182` implementation plus `04f658c` independent-oracle correction
passed the final bounded native round: nine geometry/enclosure cases, eight
refreshed-digest saved-property/link attacks, three exact selection refusals,
native two-stage edit/save/fresh reopening and workflow reuse/invalidation.
The earlier independent-centroid helper error read CenterOfMass on a generic
STEP Shape; the correction reads its actual Solid subshape. No native adaptor
mapping or numerical tolerance was changed to obtain the passing result.

All 32 canonical modelling cases plus timeout/cancellation also passed against
the same source identity, and the receipt is registered:
`sha256:c80a0a97754f934497374dea7e435166fa8c68f00f055b58323f3869d529354f`.
The dedicated neutral checks establish the analytic integrals and mechanical
interpretation in addition to the canonical receipt's declared assertions.

Host checks passed 172 FreeCAD tests, 20 assessment tests and 545 Studio search
tests. Guidance contained 920 reviewed/61 reference/zero pending/stale records.
Generation/checks passed 174 reference artifacts and 1517 Help topics; all three
owner routes passed structural readiness admission. Shared generated outputs
were restored after checking for unified integration ownership. Later source
changes and unified generated output legitimately make receipts conservatively
stale; these results remain scoped to their recorded source and workflows.

Independent integration review repeated all nine native geometry controls,
eight refreshed-hash attacks, three selection refusals, native edits/fresh
reopening and workflow reuse/invalidation against the integrated implementation.
A separate full enclosure assembly lifecycle retained the Thickness history and
shared part instances through two height edits, fresh reopenings, source removal
and hostile topology payload checks. These are scoped shell and composition
milestones; the application-wide family inventory remains open.
