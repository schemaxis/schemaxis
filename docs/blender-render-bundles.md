# Blender render layers and output bundles

The finite production-route contract below has source-bound native qualification.
Use its declared CPU/scientific, captured-resource and managed-output limits.
Whole Blender coverage and unlisted rendering variants remain incomplete.

A production can describe several views of one scene and publish their images,
scientific passes and masks together. Declare `production.viewLayers`, enable
the passes on each layer, then reference those passes from `renderBundles`.
Every reference uses a logical ID. Output destinations are generated inside the
managed run directory; an output ID is not a filesystem path.

| Declaration | Purpose |
| --- | --- |
| `viewLayers` | Select visible collections, material/World overrides and enabled passes. |
| `renderAovs` | Name additional scalar (`value`) or four-channel (`colour`) passes. |
| `materialAovs` | Connect a declared pass to a typed source on a particular material or World. |
| `renderLightgroups` | Assign declared lights and optionally the World to a named lighting contribution. |
| `renderBundles` | Choose camera, frames, output encodings and the exact enabled pass references to publish. |
| `worlds`, `sceneWorld` | Reuse constant or captured-image environment lighting, including layer overrides. |

## Select scene contents

Each layer has its own collection rules. `include` keeps ordinary visibility;
`exclude` removes the selected collection and its descendants; `holdout` makes
its visible surfaces cut holes in the layer; `indirectOnly` retains indirect
lighting contributions while hiding the collection from camera rays. A child
rule can refine its parent's policy. Rules refer to declared collections or a
captured asset's collection occurrence, rather than guessing a native name.

An asset target has `kind:"asset"`, an `asset` ID and a `path` of original
collection names below that asset's imported root. Paths distinguish nested
occurrences. Repeated asset instances retain separate layer policies. Ambiguous
or conflicting projections are refused; exclusion does not delete source data.

`materialOverride` replaces effective surface materials on that layer.
`worldOverride` selects a declared World for that layer. These choices affect
which material owns a field lookup or AOV writer. A required named attribute must
exist with the appropriate type/domain on the geometry that actually uses that
writer after the layer override and render-time evaluation.

## Choose AOV sources and owners

A writer declares `id`, `aov`, `target` and `source`. A target is a declared
material, a declared World, or an original captured object's material slot.
Sources are finite constants, named geometry attributes, declared graph output
ports, or artist surface channels such as `roughness` and `baseColour`. A tap
reuses the existing surface input; it does not substitute a second material.
Scalar and colour pass types must agree with their sources.

Captured `sourceObject` and `sourceSlot` identify the **original material
owner**, before Object palettes or other material assignments. The writer applies
to every effective user of that shared material. It is not a per-part mask.
Use collection layer selection or Cryptomatte for part isolation. Two aliases
cannot independently write the same AOV on one actual material owner.

For attribute sources, `missing:"error"` requires the named field;
`missing:"zero"` deliberately adopts Blender's zero fallback. Worlds have no
mesh attribute domain. Graph output and artist channel taps require their
declared material graph; arbitrary native sockets, Python and shader scripts
are not authored input.

Generic attribute taps refuse Cycles standard names such as `temperature`,
`density`, `color` and `velocity`: these select built-in renderer attributes
instead of a same-named stored geometry field. Rename both the stored field
and its writer source, for example to `sx_temperature`. The logical AOV pass
may still be named `temperature`. The refusal applies to both missing-field
policies; finding a same-named mesh field does not establish the rendered value.

## Preserve numeric data and masks

Use PNG for a display preview. Its values pass through the render's colour
management and cannot stand in for signed vectors, linear radiance or physical
depth. Use FLOAT EXR for scientific data. `half` is an explicit precision choice
for ordinary EXR images; numeric object/material indices and Cryptomatte IDs
require FLOAT precision. EXR compression is `none`, `zips` or `zip`.

A `multilayer` output lists named `layers`, each with an explicit source.
An `image` output has one source and an encoding. A source can refer to a
standard pass, an AOV, a lightgroup, complete Cryptomatte coverage, denoising
data, or a declared compositor output. The pass must first be enabled on an
enabled view layer. Cryptomatte output includes all requested coverage ranks
and their complete identity manifest; choosing one rank would lose overlapping
objects. A matte is not interchangeable with a numeric index pass.

Perspective depth is distance along the camera's viewing axis. It differs from
the Euclidean distance to an off-axis surface point. Position and normal passes
retain their scene/world conventions, independently of display colour mapping.
EXR raster rows run from the upper edge downward. Compare scientific pixels in
that coordinate convention and avoid silhouettes when checking exact interior
values. Motion and renderer-specific passes have their own availability checks.

## Reuse lighting resources

A World has `id` and typed `lighting`: constant `colour`/`strength`, or an
`environment` referencing a captured `production.images` resource. Environment
rotation is an XYZ rotation in radians; projection is `equirectangular` or
`mirrorBall`, with an explicit interpolation choice. Image colour space belongs
to the image resource. A `Non-Color` numeric environment and an sRGB display
image have different interpretations.

World visibility separates camera, diffuse, glossy, transmission, shadow and
scatter rays where Cycles supports those distinctions. Mist is either `none`
or `distance`, with start, depth, height and falloff. Use the same coordinate
scale as the scene geometry. Importance sampling has `automatic`, `manual` or
`none` intent and a bounded resolution; large maps consume additional memory.

Lightgroups name actual declared lights and optionally the World. Membership
must be disjoint. Summing group RGB can reproduce linear beauty only when all
radiance contributions are assigned and the comparison uses matching, unaltered
render samples. A sum alone does not prove correct group membership. Alpha,
Cryptomatte coverage and colour-managed previews are not radiance contributions.

## Examples and saved projects

The companion JSON documents are full production inputs, rather than native
Python scripts:

- [Scientific panel](examples/blender-render-bundles-analysis.json): animated
  oblique panel, raw geometry passes, a scalar field and complete masks.
- [Artist layers](examples/blender-render-bundles-artist.json): multiple material
  slots, artist channel taps, World/material overrides and lighting groups.
- [Captured assembly](examples/blender-render-bundles-assembly.json): repeated
  captured parts and nested layer selection. Its
  [source production](examples/blender-render-bundles-assembly-source.json) creates
  a housing with a through-window, a bent tubular shaft and an annular flange in
  named nested collections. Run both commands from the checkout root after
  configuring Blender:

```bash
schemaxis run docs/examples/blender-render-bundles-assembly-source.json --output-directory bundle-source
schemaxis run docs/examples/blender-render-bundles-assembly.json --output-directory bundle-assembly
```

The second input captures `bundle-source/0000.blend` twice, at separate
positions. The selected layer excludes the left shaft, makes the right housing
a holdout and retains the right shaft only for indirect light. Its captured
slot tap nominates the original shared steel material; the tag is owner-wide.
It sets `render.transparent:true` so uncovered backgrounds have zero alpha.
With an opaque World background, excluding a part exposes that background
instead of producing a transparent hole; a holdout can still cut alpha.

The scientific example supplies independent reference facts: the camera is at
`(5,0,3)` and looks at the origin, the panel normal is
`(1/2,0,sqrt(3)/2)`, and the panel translates from zero to `z=0.5`. Position
samples therefore satisfy the corresponding plane equation; the temperature
field `sx_temperature` is 300 on both frames, published as the `temperature`
AOV. The artist example's raw roughness values are
0.375 and 0.75 on the two face regions, and 0.25 under the material override.
The two World tags are 0.125 and 0.875. These are authored reference values;
they must not be inferred from the generated image or verification receipt.

Saved writers retain relative managed paths. Publication is verified from fresh
authored intent and admitted input bytes, including layer membership, effective
shader owners, file/channel layout and numeric planes. A file's presence or a
matching checksum alone does not establish the requested render. Source reuse,
edits and interrupted runs need their ordinary public verification lifecycle.
