# Blender strategic capability families

This map uses useful stable Blender workflows as its denominator. It is not an
API method count, and this programme remains unfinished. The public
[Blender manual](https://docs.blender.org/manual/en/5.2/) and
[Python API](https://docs.blender.org/api/5.2/) ground the family inventory.
The runtime target is Blender5.2.3 LTS, released22October2026; the prior local
launcher was found to report4.5.14 and is not used as proof of5.2 behaviour.

| Family | Implemented workflow | Verification / remaining strategic gaps |
|---|---|---|
| Mesh and curve modelling | Mesh/material DAG, procedural primitives, profiles/tubes, booleans and reviewed modifier chains; explicit polygon topology and per-corner UVs | Existing native cases plus production geometry save/reopen. Typed constant/dense/sparse mesh fields and multiple named UV coordinate/projection/unwrap/packing workflows now have bounded native acceptance, including loose-edge domains and source-part sharing. General edit-mode topology, complete curves/surfaces and the full modifier catalogue remain unfinished. |
| Scene assets and hierarchy | Nested collections, shared/independent object-data instances, collection instances, text/curve/custom mesh, parent relationships and named bindings | Connected animated product/save/reopen. Complete packed native/GLB and embedded glTF asset import now preserve hierarchy/materials and native child animation. Native Scene/ViewLayer selection now preserves collection ownership, nested instances/offsets, object/data sharing, exclusions, material slots and local object dependencies with finite closure and actual instance geometry checks. Linked-library overrides, source render-layer transplantation and broad asset-browser reuse remain open. |
| Materials and textures | Layered artist finishes, named image sampler roles, packed scalar channels, shared stored UV transforms and explicit normal/height/coverage intent, alongside curated composable shader graphs | Independent Fresnel, Snell, Lambert/TBN, channel and displacement fixtures accompany source reconstruction, editable native graphs and captured-input lifecycle checks. Named UV/attribute readers and explicit/projection/smart/seam unwrap and pixel-gap packing retain native editable UV sets. Painting, baking, UDIM, adaptive Smart minification, general shader-coordinate Jacobians and the broader shader/volume catalogue remain unfinished. |
| Cameras and lights | Legacy framing plus named cameras, lights and native timeline channels | Native camera/light values and publications. No complete shot composition, view layers/render passes or stereo pipeline. |
| Animation | Object/bone transform tracks, visibility, light/camera channels, interpolation and timeline | Host-calculated linear/constant key+midpoint checks, native project reopen. Reusable role-bound Actions/NLA layers now cover trim, scale, repeat, reverse, weighted REPLACE/ADD/SUBTRACT/MULTIPLY, fades and holds. Relative/absolute shape authoring supports masks, references and normalized progress; packed native asset reuse preserves ordinary CLIP tracks. Retargeting, authored drivers, COMBINE, custom absolute Key spacing and fractional authored keys remain open. |
| Rigging and deformation | Armatures, bone hierarchy, explicit vertex weights, editable Armature modifiers and reviewed object/bone constraints including IK | Analytic single-bone deformation workflow. No automatic weights, complete rig controls, constraint catalogue, pose assets or retargeting. |
| Geometry Nodes | Curated composable primitives/fields/transforms/curve/mesh/instance/material nodes and editable modifier binding | Procedural lifted mesh and fresh reopen. Reusable typed shader/geometry/compositor group interfaces, nested composition, shared instances and checked resource handles now work. Typed named scalar/integer/boolean/vector/colour/quaternion fields are available; imported object/collection geometry resource authoring, volumes, simulation/repeat zones, custom interface policies/panels and complete node catalogues remain open. |
| Compositing | Native compositing node group, render layers, adjustments, blur/glare, alpha, transforms and lens distortion | Composited render+graph reopen. No complete pass/mask/keying/denoise catalogue, multilayer EXR workflow or image-sequence inputs. |
| Simulation | Rigid bodies and cloth settings, collisions/pins and bounded sequential frame evaluation | Native evaluation/reopen acceptance in progress. Portable baked cache manifests, fluid/smoke/fire, soft bodies and procedural simulations remain open. |
| Render and exchange | Prepare-only scenes, saved-scene render route, selected frame PNGs; evaluated STL/PLY/OBJ/GLB/USD publications with geometry readback | Fresh native output reopening, independent mesh parsers and explicit unit/loss metadata. Native packed project edit/reuse and bounded STL/PLY/OBJ/GLB/glTF/USD source workflows are implemented. Animated/rigged export fidelity and the complete external dependency/import catalogue remain open. |
| Volumes, point clouds and particles/hair | Not implemented as coherent authoring families | Volume/VDB and point-cloud resources, emitters, modern hair curves/grooming and their procedural/simulation handoffs remain required; no omission approved. |
| Sculpt/paint/Grease Pencil | Not implemented | Important potential workflows; no omission approved. Stable automated authoring/brush/stroke semantics and verification need implementation. |
| Sequence/video/tracking | Cross-adaptor image-to-video workflows exist | Native sequencer editing, tracking/reconstruction, clip dependencies and timing are not implemented. No omission approved. |

Application UI customization, developer debugging facilities and arbitrary
third-party add-ons are outside this public stable workflow programme. Their
omission does not justify excluding the important families above. See the
[production guide](blender-production.md) for exact current restrictions.

Mesh fields and texture coordinates use the [mesh-data guide](blender-mesh-data.md). These bounded implementation milestones do not close the broader modelling, texture-paint or procedural application families.

[Captured image previews](blender-image-preview.md) select an independent
Workbench image and active UV map, with bounded resource interpretation and
native packed project reuse. Painting, baking, UDIM and multi-slot/per-face
authoring were not covered by that image milestone. Named
[surface layouts and Object palettes](blender-material-assignments.md) are under
qualification; painting, baking and UDIM remain unfinished.

Typed [geometry resources](blender-geometry-resources.md) add Object/Collection Info, whole-asset carriers and selected-part modifiers. Imported unbounded resource geometry remains unfinished.

Finite [selected mesh editing](blender-mesh-editing.md) adds ordered local
selection, extrusion/inset, triangulation, bridging, cuts and winding/shading
repair before field/resource composition. General bevel/knife/dissolve/subdivide,
open or unequal bridges and topology data interpolation remain required. This
bounded subset does not close the mesh-modelling family.

Layered artist finishes, image role/channel sampling, shared stored UV normal bases and built-in OSL applicability are described in [Layered surface materials](blender-surface-materials.md). Whole Blender coverage remains unfinished.
