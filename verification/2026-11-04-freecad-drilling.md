# FreeCAD common unthreaded drilling milestone

This review covers `holeLocations`, `boltGrid`, `boltCircle` and native `hole`
on `schemaxis.freecad/1`. Whole FreeCAD completion remains open. The public
[Hole documentation](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/PartDesign_Hole.md)
and [native property API](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/PartDesign/App/FeatureHole.cpp)
were checked against installed stable1.1.4. The reviewed contract deliberately
keeps threads, taper and standards tables visible as remaining Hole modes.

The implementation expresses locations/pitch/phase separately from drill and
head dimensions. Native constrained pitch/phase construction geometry and fixed
expressions retain layout intent, with a single `PartDesign::Hole` owning bore
diameter. Finite typed mappings/readback and closed saved-document checks expose
no authored reflection, scripts or raw constraint indices for these intents.

## Completion checklist

| Item | Reviewed delivery and checks |
| --- | --- |
| registration/schema | Existing version and batch route retained; typed profiles, Hole conditional options and native length drivers. Existing inputs remain compatible. |
| semantics | Same-Body ownership/current-tip composition, finite depth/tip conventions, exact recess fields, distinct/bounded locations and actual stock intersection. Meaningful host invalid cases cover these rules. |
| native mapping | Native Sketcher circles/construction geometry/constraints/expressions and `PartDesign::Hole`; fixed reviewed native property types/enums; direct native and saved XML readback. |
| execution/qualification | Dedicated bounded native qualifier checks independent neutral STEP mechanics, native edit/save/second-edit/fresh reopen, refreshed publication-digest semantic attacks, workflow reuse/invalidation and missed-material refusal. Exact executed result/source identity is retained separately. Process exit alone is insufficient. |
| discovery | Four curated operation intents and search phrases cover drill centres, rectangular bolt pattern, pitch circle and counterbore drilling, alongside existing Pocket/pattern search cases. |
| guidance/help | Every changed schema field and operation reviewed, shared frame/driver meanings reused where identical; inherited STEP field addresses relocated to preserve guidance after node insertion. Dedicated local drilling guide plus generated reference/Help checks. |
| examples/Studio | Persistent grid/Hole starter, generated enclosure variant and editable Studio drilling document. The maintained native-generated enclosure STEP fixture also repairs the earlier FEM starter's missing source prerequisite; invalid Poisson-ratio fixture repairs its readiness negative case. |
| tests/maintenance | Meaningful host tests, existing FreeCAD regressions, generated reference/Help and assessment checks. Native1.1.4 remains the absorbed version; conservative editorial breadth25/abstraction75 scores retained. Receipt freshness is distinct from implementation coverage. |

## Mechanical acceptance

Independent volume integrals and neutral STEP surface/point checks cover plain
grid/explicit/bolt-circle drilling, flat/conical blind tips with both depth
conventions, cylindrical/conical/compound head recesses, side/forward/oblique
frames, a circle whose marker radius differs from actual bore radius, multi-Body
continuation and a native Hole pattern. Counterbore stock30×30×10 with four
diameter3 bores and diameter6×depth2 heads has volume9000−144π mm³.

The enclosure composes driven wall/floor/height, four attached bosses, one
fastening grid/Hole and a second Body lid. Baseline housing volume10128+60π mm³
matches the earlier four-Pocket model. Native parameter edits change wall,
floor, stock/boss height and bore diameter; independent volume and bore
centres/radii/voids are checked after each edit and fresh reopening. Independent
grid and bolt-circle edits test native pitch/phase propagation.

Retained-file attacks alter Hole diameter, extent, reversal, tip, thread/taper
flags, custom-recess mode, profile link, layout construction status, constraints,
expressions and recess dimensions while refreshing the publication SHA. The
production verifier must reject native semantic changes, rather than relying on
a stale digest. The closed saved settings contract also retains the existing
safe native opening boundary.

## Executed result

The frozen `c7e88e70fea854cfa930804c2ef72b3f1f4f0aa8` implementation passed the
bounded native drilling round:22 geometry cases,27 refreshed-digest attacks,
grid/circle/enclosure two-stage edits and fresh reopening, workflow reuse,
changed-intent refusal, invalid saved-history rebuilding and missed-stock
`INVALID_GEOMETRY`. Independent STEP checks also cover offset/single-column
grids, an odd offset pitch circle, general circular sketches and a non-default
drill-point angle. Source identity:
`sha256:147ba6283adcad398ece3baab95647ef8630979ce746b32bc9a2eb375e6aed9d`.

The canonical native route qualifier separately passed all29 declared cases
plus timeout/cancellation lifecycle checks against that same source identity;
its successful receipt is registered. Older assembly/FEM receipts retain their
separate source epochs. Integration or later source changes make these receipts
conservatively stale until independently rerun; the named evidence stays scoped.

Host checks passed167 FreeCAD tests,20 assessment tests and543 Studio search
tests. Guidance had899 reviewed/61 reference/zero pending/stale records.
Generation/checks passed174 reference artifacts and1514 Help topics; all three
owner routes passed structural readiness admission. Shared generated outputs
were restored for integration ownership after checking, so integration must
regenerate its unified outputs. These counts describe executed checks, rather
than an upstream API coverage percentage.

Native holes can still fail for invalid stock intersections, oversized head
recesses or kernel/topology changes. Layout locations do not implement general
fastener/BOM semantics or automatic attachment repair. Further PartDesign,
surface/BRep, mechanism, manufacturing and analysis families remain real work
in the [family inventory](../docs/freecad-capabilities.md).
