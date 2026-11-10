# Blender mesh fields and named UV mapping

This change extends the production route with typed scientific mesh channels,
named texture-coordinate sets, projection/unwrap/packing and explicit prototype
sharing. It does not complete Blender's strategic application inventory.

The implementation baseline remains5.2.3 LTS. Native API probes confirmed the
chosen mesh storage types/domains, named-attribute output types and UV operators;
FLOAT2 storage has no supported Geometry Nodes FLOAT2 reader. See the
[guide](../docs/blender-mesh-data.md) for conventions, selectors, losses and faults.

Current execution checks:98 host tests passed with3 explicitly optional live
skips. The broad native suite passed20 workflows, including93 meaningful
type/domain/storage variants, canonical edge values, three unwrap methods with
independent positive UV area/pixel-gap assertions, explicit/box mapping, copy/shared
ownership, physical GLB geometry and native field editing/adoption. Additional
checks cover actual shader pixels, field+morph+armature composition, imported
collection prototypes, loose edges and two captured CAD enclosure variants.
The execution source is frozen; final integrated acceptance remains pending.

The strict mutation qualifier rejected18 refreshed-hash semantic mutations and
accepted6 unchanged native saves through the identical current-native path.
Typed fields, named/packed coordinates, active/render UV choice, seam endpoints,
shader/GN reader bindings and copied/shared ownership were all challenged.
Existing reusable-node-group regression passed5 native workflows. Dedicated
Studio browser acceptance selected among24 distinct labelled channel variants,
authored a sparse vector and inserted the validated declaration. Asset8, motion5 and collection10 native regressions passed (plus8 collection
refusals). Two additional field-node workflows proved Boolean mask effects on
individual evaluated vertices and quaternion rotation of asymmetric instances.
The non-square UV-padding oracle was strengthened to measure the separating
texture axis in actual pixels; fresh native verification retained roughly16px
clearance for an8px request across all three unwrap solvers.
Production verification uses deterministic native packing and unit-tile bounds;
independent island/pixel-clearance assertions cover the bounded fixtures and
solver matrix, without claiming a general arbitrary-polygon clearance proof.

| Checklist | Delivery and remaining evidence |
| --- | --- |
| registration/schema/semantics | Existing production routes; closed typed records, no authored code/reflection; domain shapes, names, shared owners, seams and UV controls checked |
| native mapping/execution | Finite mesh/channel and UV API mapping with actual persisted readback; fresh-process verification inherits isolated runner and trusted-runtime policy |
| discovery/guidance/Help | Application search terms/case,4437 reviewed+246 attributed records with0 pending/stale; private Help generation/check produced1518 topics and all6 Blender search cases passed. Actual packaged Help remains integration-owned and stale in this worker baseline |
| examples/Studio | Editable field panel and Studio starter; scientific field→procedural geometry/shader→physical export; actual browser authored a sparse vector using24 distinct labelled variants |
| lifecycle/tampering | Native edit/adopt and sharing controls implemented; 18 strict native attacks and6 unchanged-save controls passed; assets8/motion5/groups5/collections10 regressions passed |
| qualification/maintenance | Frozen baseline unchanged; broader workflow claims remain open; scope/fingerprint and acceptance recipes updated; final integrated evidence remains pending |

The historical CAD producer used by the optional acceptance composition is a
captured input, not a claim of fresh FreeCAD qualification. Independent expected
footprints and lid heights derive from its authored geometry and quarter-turn.

Final shared-gate status is explicit: the worker baseline’s real readiness
admission failed three packaged Help checks; the combined560-test Studio/search
run passed543 and failed17 stale-Help assertions (one Blender,16 inherited
FreeCAD). No gate was waived. Private regeneration and link/search QA passed,
but the master must regenerate the actual shared assets and rerun admission,
required host/Studio suites and packaging on the integrated source. Host-only
production conformance,98 Blender tests(3 optional live skips) and5 schema/parser
parity tests passed. Whole-application completion and release remain open.
