# Blender scene production

`schemaxis.blender/1` retains its mesh graph and adds an optional
`scenes[0].production` record. It composes named scene assets and motion around
those meshes. The [production starter](../examples/schemaxis/blender-production.json)
builds two instances of a checker-material product, parents them to one motion
control, renders three frames and publishes geometry at specified frames.

This is a strategic coverage milestone. The [family map](blender-capabilities.md)
retains the important unfinished Blender workflows; this addition does not make
the whole adaptor complete.

## Assets and coordinates

`objects` declares named `empty`, `text`, `curve`, `mesh`, `light`, `camera`,
`instance` and `collectionInstance` assets. Mesh graph identities can be used
alongside these identities in hierarchy, tracks, bindings and exports. Object
identities must be distinct from graph outputs and rigs. Collections can be
nested; objects can reference one declared collection. Instances share source
object data when `linked` is true. An object-data instance retains a copied editable modifier stack, with shared
external modifier references. It does not inherit source parenting, animation or
constraints: declare those relationships explicitly. Use a collection instance to
retain complete collection contents.

Locations, vertices, curve points, text size and camera clipping use the declared
production `units`. The stored project retains those numerical coordinates and
Blender's physical scene scale. Object rotations and bone rotations use XYZ Euler
radians. Positive three-component object `scale` is dimensionless. A camera's
`orthographicSize` is a separate length, and `lens` is in millimetres. Mesh `uv`
provides one [u,v] pair per face corner, in exactly the faces' corner order; these
coordinates are dimensionless and can repeat for texture tiling. This is explicit
UV authoring, not automatic unwrapping or a UV editor.

`hierarchy` gives each object at most one parent. `keepWorld:true` retains its
initial world pose by adjusting the local transform; false retains the declared
local pose, so the parent's transform contributes to its world pose. Cyclic
parent and instance relationships fail during planning. An instance's geometry
data sharing also shares material-slot edits; use `linked:false` for independent
data. Material bindings replace the first material assignment on the target.

Image assets have an ID, file, colour space and packing choice. The original and
retained bytes are hashed and checked, and packed images remain in the saved
project. `sRGB` is for colour textures; `Non-Color` preserves numeric data such as
normal maps. Image records handle texture inputs; production.assets adds complete project and
neutral source scenes as described below. Linked libraries and external media
dependency graphs remain open.

## Motion and rigs

`frameStart`, `frameEnd`, `fps` and `currentFrame` define an integer-frame timeline.
`tracks` target a named object and a semantic channel: `location`, `rotation`,
`scale`, `visibility`, `lightEnergy`, `cameraLens` or `cameraScale`. Keys must be
strictly increasing and lie within the timeline. Motion has `LINEAR`, `BEZIER` or
`CONSTANT` interpolation, with linear as the default. Visibility is a boolean
render-hiding channel: true hides the object. Use constant interpolation for
boolean tracks. Bone tracks use `bone` and one of the three transform channels.
Pose-bone translations/rotations are in the bone's local rest coordinate frame;
a bone whose head-to-tail direction is world Z has its local Y along that axis.

`rigs` declares armatures with named bones, rest head/tail locations, parent,
connected and deformation flags. `skin` assigns vertex indices to named bone
weight groups and adds an editable Armature modifier. Vertex indices refer to the
base mesh, before procedural modifiers; weights are in0–1. Explicit weights do
not perform automatic weighting or retarget an imported skeleton. Constraints
support copy transforms/location/rotation/scale, track and damped track, child-of,
path following, inverse kinematics and local transform limits. A constraint on a
pose bone includes its bone ID; IK requires a pose bone. Constraint composition
and authored order remain visible in the native project.

Native readback checks keys, interpolation, skeleton topology, skin assignments
and constraints. It also evaluates all keys and integer midpoints. Linear and
constant channel values are independently calculated on the host. Bézier handles
remain native automatic handles; intermediate Bézier shape does not have an
independent host interpolation implementation.

## Composable node graphs

`materialGraphs`, `geometryGraphs` and `compositor` contain named nodes and explicit
semantic socket links. A link has `from` and `to`, each with `node` and `socket`.
Node IDs, socket IDs and properties come from the finite reviewed catalogue;
authored native class names, property paths and scripts are refused. Cycles,
missing references, incompatible sockets and multiple links to a single ordinary
input fail. Geometry join supports multiple geometry links. A linked socket must
be active for the chosen node operation.

Material graphs compose surface/volume shaders, shader mixing, image and
procedural textures, coordinates, mapping, bump/normal conversion and numeric
operations. `materialBindings` applies the named graph material to an object.
Geometry graphs compose input/output geometry, fields, transforms, primitives,
curve conversion, instancing, material assignment and mesh operations;
`geometryBindings` adds the graph as an editable Geometry Nodes modifier.
Compositing composes rendered layers, exposure, colour adjustments, blur, glare,
alpha layering, transforms and lens distortion. Each graph has one output.
Graphs are saved as native editable node trees with exact node/socket/property
and link readback. These are curated composable catalogues, not every Blender
node or reusable user-defined group interface.

## Simulation

`rigidBodies` declares active/passive bodies with mass in kilograms, friction,
restitution, collision shape and kinematic mode. `cloth` declares mesh cloth with
solver quality, mass and stiffness controls, collision choices and optional
pinned vertex indices. `collisionObjects` adds collision modifiers for cloth.
`gravity` is a three-component acceleration in metres per second squared, with
Blender applying the scene unit scale. `simulationFrames` requests ordered frame
samples; the runner evaluates sequentially from the start, with a1000-frame
budget, and repeats the evaluation after reopening.

This verifies configured settings and bounded evaluated geometry. It does not
publish a portable baked simulation cache, prove solver convergence or establish
fluid, smoke, fire, soft-body, particle or Geometry Nodes simulation coverage.
Reproduction currently requires the saved project and matching qualified runtime.

## Outputs and verification

`renderFrames` adds PNG publications at requested frames. `camera`, when present,
selects a declared camera; otherwise the existing automatically framed camera is
used. The current camera and frame are restored after each group. PNG dimensions
and decoded pixel content are checked; renders are not asserted to be visually
identical across different hardware.

`exports` gives an ID, format, object IDs and optional frame (default currentFrame).
GLB and USD outputs convert physical coordinates to metres. OBJ, PLY and STL
retain the production's numerical units and record those units explicitly in the
publication metadata; downstream consumers must honour them. The exporter bakes
evaluated world-space geometry at that frame into a temporary export scene. It
retains the editable original project and restores the source frame and objects.
These exports provide evaluated geometry, not a portable rig or animation clip.
GLB/USD approximate native materials; OBJ/PLY/STL do not retain procedural shading.

Every exported geometry is imported again in Blender and compared with source
geometric moments. OBJ/PLY/STL receive an additional independent host parser
check. Fresh-process reopening checks saved scene state, production records,
node trees, motion samples and published outputs. Hashes, identities, frames and
publication membership are checked separately. None of these tests makes an
unimplemented Blender family complete.

## Direct production and native asset reuse

Use `schemaxis.blender.production/1` when the task is scene production rather than
mesh DAG authoring. It accepts `production`, optional `visible`, render settings,
image `size`, preview `cameras` and `prepareOnly`. The
[product presentation starter](../examples/schemaxis/blender-product-presentation.json)
uses a physical millimetre product, appearance graph and turntable task without
placeholder graph nodes. Original authored JSON and its route/schema remain the
recorded input; deterministic internal lowering uses the same native executor.

`production.assets` places a complete source below a named root. Its ID can be
used directly for visibility/framing, parenting, turntable intent and exports;
root publications resolve evaluated descendants and collection instances without
duplicating shared descendants. `file` is captured and hashed, `sourceUnits`
defines physical source lengths, and `location`/`rotation`/positive `scale` place
the entire source in production coordinates. Source cameras/lights remain members
for reference integrity; imported lights are render-disabled unless includeLights
is true, and the production active camera remains independently selected.

Supported sources are complete binary GLB or embedded-resource JSON glTF, packed
local `.blend` scene assets, geometry-only STL/PLY/OBJ, and the explicitly bounded
static baked USD subset produced by this adaptor. glTF and the supported USD
subset use physical metres. STL/PLY/OBJ and native-project unit interpretation is
explicit; the default is metres, not filename-based inference. OBJ material
libraries and external glTF resources are refused until their companions have a
captured dependency contract. General USD composition/material/animation import
is a remaining workflow, not a claim made by this static subset.

Native append retains object hierarchy, editable shader materials, armatures and
child animation. A packed source with animated children can rotate as one
presentation asset while its child motion continues. GLB exported by this
adaptor is evaluated static frame geometry, so that source cannot regain a rig
or animation already lost at export. Source project libraries must be local and
images/fonts packed. Stateful simulation caches, script shaders, scripted drivers
and media sequences require further captured-dependency workflows; they are
refused rather than silently discarded or executed. Native geometry drivers, including Blender's simple expressions, currently need
a reviewed material-input dependency contract and are refused. Bake motion to
supported Action channels before reusing the asset. Driver support remains an
unfinished workflow.

Fresh native verification reads the current saved project and checks imported
member types, hierarchy, transforms, complete animation key/handle configuration,
mesh topology, UVs, attributes, weights, shape keys, rest/pose bones, reviewed
modifier/constraint settings, shader links/socket values and packed image bytes.
The read-only fidelity mapping admits explicit object, node, modifier and
constraint classes. Selected native scenes now retain collection ownership,
instances, local object dependencies and ordinary Action/NLA clips; see
[collection asset selection and limits](blender-collection-assets.md). Unsupported
classes and unqualified scene/cache dependencies fail with
`UNSUPPORTED_ASSET_DEPENDENCY`. It is bounded to 4,096 objects,
two million payload records and 64 MiB of fidelity payload. It does not silently
claim to preserve every possible native project dependency.

Current asset proofs use `schemaxis.blender.asset-fidelity/2`. Embedded material
node trees are identified by their owning material, so several trees named
“Shader Nodetree” cannot overwrite one another's shader or image dependencies.
Fresh verification reconstructs those dependencies from trusted captured original
inputs before opening the submitted project. Authored shader verification also
binds native socket defaults, material settings and nested graphs, including
settings outside the authored node catalogue; editor placement stays editable.
Material settings include the fixed-runtime Cycles settings, Line Art masks and
optional Grease Pencil style settings/image pointers. This preservation does not
provide authoring or render acceptance for the unfinished Grease Pencil family.
Asset metadata and tags are retained. Linked material libraries and library
overrides require a future captured override workflow. Editor previews and weak
append provenance do not supply shader or source authority.

An obsolete `/1` asset **proof receipt** returns `RERUN_REQUIRED`. Preserve it and
rerun the authored intent in a **new output directory** using the retained trusted
original asset inputs. If their former workstation paths are unavailable,
explicitly adopt those original captured bytes and reference the new pin. Raw
original `.blend` assets remain reusable through current typed admission. Do not
adopt the submitted consumer project as a substitute for its original inputs,
relabel its witness version, or copy regenerated readbacks into the old receipt.
Some old consumers lost image pointers during dependency pruning; rebuilding
from original inputs restores the full source-owned graph. An unchanged old
consumer may instead have intact native state but obsolete readback structure;
that also needs fresh proof, without weakening the source comparison. Missing or
unknown fidelity versions fail verification rather than selecting an old reader.

Native round-trip fixtures independently check a textured UV mesh and instance,
weighted rig and animated child hierarchy against the static GLB source,
including literal bounds showing their different motion after reuse. Refreshed
project hashes cannot conceal changes to roughness, an unsampled animation key,
a UV coordinate or skin weight: fresh current-byte verification checks those
editable details independently of the saved receipt.

For scientific displacement/colour fields, multiple UV sets, projection/unwrap/packing and explicit mesh-data sharing, see the [mesh-data guide](blender-mesh-data.md). Named native/glTF source parts preserve imported collection ownership. Field coordinates and UV projection use original mesh-local numerical units before parent/asset scale.

Typed procedural references and selected-part modifiers: [geometry resources](blender-geometry-resources.md).

Ordered element selections, extrusion/inset, loop bridges and halfspace cuts:
[selected mesh editing](blender-mesh-editing.md). These stages precede scientific
fields, modifiers, morphs and motion; existing topology data needs an explicit
supported loss policy.

See [render engines and display colour](blender-rendering.md) for Cycles, EEVEE,
Workbench technical shading and explicit colour-management controls.

Named surface regions and linked-instance palettes use the [material assignment guide](blender-material-assignments.md). The bounded DATA/OBJECT workflow is under qualification; it does not close painting, UDIM, baking or broader material families.

Layered artist finishes, image role/channel sampling, shared stored UV normal bases and built-in OSL applicability are described in [Layered surface materials](blender-surface-materials.md). Whole Blender coverage remains unfinished.
