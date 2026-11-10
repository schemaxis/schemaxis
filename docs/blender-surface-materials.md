# Layered Blender surface materials

Use `production.surfaceMaterials` to describe a reusable physical surface by its
layers and texture roles. A material ID can be assigned to an object, a logical
material slot, or a Geometry Nodes material input. These IDs share the namespace
with `materialGraphs` and mesh-graph materials. Keep a single definition for a
finish that several objects share; use the existing material assignment layout
and object override palette when their face regions are shared but colours differ.

An entry containing only `{"id":"finish"}` gives an opaque grey dielectric with
roughness 0.5 and IOR 1.5. Layer options have defaults, so an ordinary finish does
not require constructing a shader graph. Expert `materialGraphs` remain available
for other reviewed combinations. Artist intent is retained in the saved project;
the compiler constructs the finite shader graph during planning and execution.

```json
{
  "id": "paint",
  "baseColour": {"kind": "constant", "value": [0.04, 0.09, 0.25]},
  "roughness": {"kind": "constant", "value": 0.3},
  "coat": {"weight": {"kind": "constant", "value": 1}}
}
```

## Images and channel roles

Declare original still images in `production.images`; samplers reference those
resource IDs. A material's sampler IDs are local to that material. Separate
samplers can reuse one captured image with different lookup coordinates, wrapping
or interpolation. Image colour space and alpha interpretation belong to the image
resource. Use `sRGB` for ordinary colour images and `Non-Color` for numeric maps.
Packed data images can use `alphaMode:"channelPacked"` to keep RGB and alpha as
independent data channels.

```json
{
  "id": "panelFinish",
  "samplers": [
    {"id": "colour", "image": "paintColour",
     "coordinates": {"kind": "uv", "set": {"kind": "named", "name": "FinishUV"}}},
    {"id": "orm", "image": "packedData",
     "coordinates": {"kind": "uv", "set": {"kind": "named", "name": "FinishUV"}}},
    {"id": "normal", "image": "normalData",
     "coordinates": {"kind": "uv", "set": {"kind": "named", "name": "FinishUV"}}}
  ],
  "baseColour": {"kind": "sample", "sampler": "colour"},
  "roughness": {"kind": "sample", "sampler": "orm", "channel": "green"},
  "metallic": {"kind": "sample", "sampler": "orm", "channel": "blue"},
  "normal": {"kind": "normalMap", "map": {"sampler": "normal"}}
}
```

Scalar sources select red, green, blue, alpha, or linear luminance, then map the
input interval [0,1] into an explicit `range`, clamping at its endpoints. Reverse
the range to invert a channel. The usual range is [0,1]; quantities such as IOR
have their own physically useful defaults. RGB scalar channels require Non-Color.
Luminance uses linear RGB weights 0.2126, 0.7152, 0.0722 and can reuse a colour
image. Alpha can reuse a colour image unless that resource explicitly ignores it.
Colour sources optionally multiply RGB by a linear `tint`. Colour constants and
tints are linear values, not sRGB byte values.

Artist sRGB colour and luminance sampling keeps a real positive-alpha colour
mask in the graph so adding another consumer of image alpha cannot silently
change colour association. This keeps the same native colour interpretation
when coverage changes from a constant to the same image's alpha. Native image
precision still applies: Cycles can lose substantial RGB precision in 8-bit
sRGB texels near zero alpha. A measured `(200,100,50,3)` texel produces opaque
emission `(170,85,0)` in the fixed Cycles runtime; this is not encoded-byte
fidelity. EEVEE and Non-Color data follow their separate native paths.
Associated zero-alpha colour is black; choose ignored alpha when those file
colours must be displayed opaquely. Non-Color numeric RGB and channel-packed data
retain their separate data interpretation. Expert image nodes retain Blender's
native link-dependent colour/alpha semantics.

Samplers choose UV, generated, or object coordinates. Flat projection is required
for a UV sampler; spatial coordinates also support box, sphere and tube projection.
Wrapping supports repeat, extend, clip and mirror. Filtering supports nearest,
linear, cubic and native smart interpolation. Smart requires
`render.renderer: {"kind":"cycles", "shadingSystem":"osl"}` with CPU or
OptiX, using Blender's built-in shader nodes. Omission selects the historical SVM
backend; explicit `"svm"` normalizes to that same default. Script nodes and shader
code remain outside this contract. The configured runtime must include OSL.
Smart without OSL, and EEVEE box projection with clip/extend, are refused rather
than silently changing the authored effect. Sphere/tube seams retain the
renderer's documented filtering limitations.

Smart selects the fixed renderer's native option. Independent tests qualify its
cubic magnification, but do not establish adaptive minification or pixel-footprint
antialiasing. Large tiled-image probes still alias with packed images and with
native-generated texture caches for unpacked images. Cache generation alone is
not an accepted filtering workflow; automatic mip-cache ownership and portable
minification remain open. Choose adequate render sampling and inspect the result
when a finish repeats below pixel size.

## Stored UVs and normal orientation

A tangent normal map defaults to its sampler's stored UV set. `active` means the
render-active evaluated UV map; `named` selects a particular map. Missing maps on
actually used evaluated face materials are faults. OpenGL and DirectX conventions
are explicit; DirectX reverses the green-axis convention. Object and world normal
encodings are also available. Normal-map images require Non-Color interpretation.

To rotate, mirror or nonuniformly scale a finish consistently, create one named
stored UV map and use it for base colour, packed channels and normal mapping:

```json
{
  "object": "panel",
  "uvMaps": [
    {"name": "BaseUV", "method": "planar", "size": [2, 1]},
    {"name": "FinishUV", "method": "copy", "source": "BaseUV",
     "transform": {"pivot": [0.5, 0.5], "scale": [-2, 3],
                   "rotationDegrees": 45, "offset": [0, 0]}}
  ],
  "renderUV": "FinishUV"
}
```

The stored transform scales around the pivot, rotates counterclockwise, then adds
the offset. Signed nonzero scales mirror the basis. A copy can read an original
map or an earlier declared map. It cannot reference itself or a later declaration.
The original and final maps together must fit Blender's eight-map limit. Shared
mesh data still requires the explicit `refuse`, `copy` or `shared` ownership policy.
Pack the base set first, then transform a separate copy; a transformed map does
not inherit unit-tile or pixel-padding guarantees.
Transforms that overflow native UV storage, merge distinct adjacent corners, or
lose/reverse an existing triangle orientation through float32 rounding are refused.
Reduce a large offset or rescale the map when this precision fault occurs. This
local feature check does not claim exact arithmetic for every UV coordinate.

A sampler's own coordinate transform changes texture lookup. Its normal basis
remains the selected stored UV map. Arbitrary shader coordinate transforms do not
automatically rotate or correct encoded normal vectors by a texture Jacobian.
Use the shared stored-map route when that orientation is required.

`normal` also supports height bump and a normal-map/bump chain. Bump distance uses
production length units. Coat normals can follow the base, use geometric normals,
or have their own detail chain. Normal-map `base` chooses the original or displaced
surface basis when combining normal maps with displacement.

## Physical layers and renderer policy

The base exposes metallic, roughness, IOR, coverage and transmission. Diffuse
roughness, specular level/tint/anisotropy/tangent, coat, sheen, emission and thin
film are grouped by their physical roles. Specular rotation is in degrees; film
thickness is in nanometres. Specular and subsurface anisotropy may be signed.
Subsurface scattering offers diffusion, random walk, skin, or thin-wall scattering.
Bulk scattering distance and relative RGB radii are separate. Skin additionally
uses subsurface IOR; inactive method-specific controls are refused.

`wall:"thin"` represents sheets. It has a distinct thin-scattering layer and
does not accept bulk scattering radii or thickness. For EEVEE the compiler also
connects zero output thickness and selects slab mode. `realtime` controls the
EEVEE approximation: probe or screen transmission, automatic or explicit sphere/
slab object-space thickness, and shadow-derived thickness. Screen transmission
requires EEVEE screen ray tracing in the render settings. These settings remain
retained engine-specific intent when a project is rendered with Cycles.

Cycles is required for anisotropy, diffuse roughness, random-walk methods, thin
film, and true surface displacement. EEVEE uses its documented approximations,
including an approximate sheen layer and screen-space transmission limitations.
Workbench supplies technical material/texture previews through `viewportColour`
and `displayTexture`; it does not evaluate these physical layers.

Displacement chooses none, bump-only, geometry, or both, with height, midlevel,
distance and object/world space. It uses the existing bounded mesh tessellation;
it does not silently add adaptive subdivision. Object-space displacement follows
object scale; world-space displacement retains its world distance. Shader
displacement changes rendered geometry. Stored mesh vertices and ordinary mesh
exports retain the base geometry; use typed mesh edits when the displaced shape
must be handed off as geometry. Choose framing appropriate to the displaced
surface when setting an explicit camera.

## Verification and recovery

Native construction and reopening compare generated graphs, actual material/data
ownership, image resources and renderer settings. Mandatory fresh reconstruction
from retained trusted inputs binds hidden shader defaults, source geometry/UVs,
packed images and effective material assignments before opening submitted native
state. Updating a file hash or copying its readback does not authorise a changed
shader, UV input, image interpretation or material pointer. Deliberate edits require
a new adopted input and a new run. Preserve the original output and failure logs.

Fresh reconstruction also binds the final writer's renderer, output/display
settings, writer and production camera/light configuration, local scene/collection
membership, view-layer masks/overrides, compositor ownership and Workbench display
settings. Camera/object placement, deltas, ray visibility, light linking and owned
action channels also come from fresh construction. The submitted `input.json` must
match current lowering of `authored.json`; it cannot replace that authority.
Camera-marker membership, the exact saved frame/subframe, global gravity and file
working colour space are source-owned too. Legacy Curve/Font data includes render
tessellation, character layout, profiles, font dependencies and owned actions;
the current viewport mesh alone does not supply those inputs. Workbench binds its
object shadow/display controls as well as scene shading. Curve shape keys need a
reviewed shape contract and are refused; mesh shape-key support is unchanged.
Fresh-reader deadlines share the caller's remaining budget and structured native
faults remain available through public verification. Hidden bounce limits
can change transmitted light even when ordinary readbacks are unchanged. Numeric
properties requested by existing Attribute shaders are bound separately, including
Object/Instancer/View Layer lookup candidates and future animated mode choices.
An unqueried viewport sampling change remains an inspection edit; the same value
is source-owned when a shader reads it. This adds no authored RNA setter or stored
signature authority. Writer-camera stereo/depth of field, display curves, populated sequencers,
background scenes, custom camera shaders, AOV/lightgroup/Freestyle render layers
need further typed contracts and are refused in this scene-rendering scope.
Production cameras retain their existing typed depth-of-field controls. Renderer
participation is bounded to 16,384 reachable object/collection members, 128 view
layers and 64 MiB of evidence. An intentional edit requires a new trusted input
and NEW output; changing cached witnesses does not adopt the edited state.
Existing rigid-body/cloth/collision and force-field settings are also source-owned
render inputs, including inactive defaults and effector filters. Derived solver
matrices are evaluated after warmup; they are not substituted for stored transform
channels. Soft bodies, rigid-body constraints, force textures/source-object
references, cloth rest-shape overrides and baked/external/disk caches need further
typed contracts and are refused. This fidelity check adds no new physics authoring
coverage.

The separate `render/1` route treats its `.blend` as a newly supplied source. It
does not authenticate an earlier producer packet or adopt changed witnesses on
that producer's behalf. Verify the producer packet separately when its original
intent is the contract being checked.

The scene-wide shader limits include artist materials, expert graphs, reusable
groups and captured/imported material trees. They bound allocation and recursive
expansion; they do not prove a bound on every shader's render time. Independent
reference scenes qualify particular normal, channel, Fresnel, refraction and
displacement outcomes. They do not establish arbitrary rendered-image equivalence.

UV-sphere primitives now publish deterministic edge and oriented face indices.
The fixed native BMesh sphere constructor previously returned allocation-dependent
ordering despite identical geometry. An older sphere packet can therefore fail
fresh source reconstruction. Preserve that packet and rerun its trusted authored
intent into a new output with the current constructor and original inputs. This
recovery keeps exact topology, UV and material-region authority; resnapshotting a
submitted consumer or accepting a tolerant topology match cannot repair it.
