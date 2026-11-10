# Technical rendering and display colour

The three Blender routes accept the same `render` record: scene construction,
direct `schemaxis.blender.production/1`, and rendering a captured saved scene with
`schemaxis.blender.render/1`. `renderer.kind` chooses `cycles`, `eevee` or
`workbench`. Cycles remains the default. The
[technical enclosure example](../examples/schemaxis/blender-technical-render.json)
combines editable topology, a scientific field, object colours and Workbench
lighting; its native scene remains editable.

Cycles uses the existing `device`, `samples`, `denoise` and `seed` controls.
`device` is `CPU`, `CUDA` or `OPTIX`; a requested accelerated backend must actually
exist. EEVEE has its own `renderer.samples`, screen ray-tracing, fast GI and shadow
quality controls. Workbench surface shading has technical lighting, display colour, background,
antialiasing, shadows, cavity, outline, xray and backface-culling choices. Native
shader graphs and scene lights affect Cycles/EEVEE; Workbench uses its declared
Studio, MatCap or Flat lighting and display colours.

Nondefault legacy Cycles controls are refused on other engines because they would
not control their output. Workbench also refuses nondefault legacy world and area
light controls. Shared `threads` and `transparent` remain available. Workflow
planning conservatively reserves one graphics slot for EEVEE/Workbench, separately
from Cycles CUDA/OptiX selection. This reservation is not proof of a particular
physical GPU or driver; a software graphics context may execute the native job.

For EEVEE, `rayTracing.kind: "screen"` exposes tracing resolution, precision,
surface thickness, backface handling and denoising. `backfaces` chooses
`singleSided` or `bothSides` with a `radianceReuse` fraction. Fast GI approximation
requires ray tracing and chooses `ambient` or `global`. Its roughness threshold
is below one, because one disables that approximation. Distance zero means no
explicit maximum; thickness, bias, resolution, rays and steps control its
approximation. Filtering may be `none` or `filtered` with at least one enabled
spatial, temporal or bilateral filter. Screen tracing cannot recover arbitrary
off-screen geometry; probe authoring and bake/cache workflows remain unfinished.

Workbench Studio lighting chooses one of the bundled studio presets; rotation
requires `worldSpace: true`. MatCap chooses a bundled material capture. Custom
user presets with the same name are refused. Flat lighting is useful for field
plots and exact colour patches. Background is explicit RGB. Shadows use a
normalized direction and darkness/shift/focus. Cavity can be world-space,
screen-space or both, with separate ridge/valley strengths. Xray alpha and outline
colour are independent presentation controls.

Colour sources have distinct meanings:

- `material` uses material display colour, not the shader node graph. A root
  material graph has `viewportColour`; DAG materials retain their existing
  `colour` value for both display and their Principled shader.
- `object` uses geometric objects' `displayColour`. Choose `colour` with a `value`
  RGB triple, or `inherit`. Inherit preserves a geometric prototype's native
  colour on an instance; newly constructed geometric objects start white.
  Colouring a hierarchy or collection carrier does not recolour its children;
  explicit colour on a nongeometric prototype is refused.
- `attribute` uses mesh colour channels. `meshData.activeColour` and
  `meshData.renderColour` select declared `colour` or `byteColour` channels;
  omitted selectors choose the first declared colour channel. Values retain
  their existing linear-float versus encoded-byte conventions.
- `single` supplies one RGB colour for the technical render. `random` uses
  Blender's object-based colour assignment.
- `texture` uses a material graph's independent `displayTexture` image and the
  mesh's active UV map, with a deliberate material-swatch fallback. See
  [captured image previews](blender-image-preview.md) for image interpretation,
  resource bounds and native edit/adoption.

`colourManagement` is independent of the engine. `view` chooses `agx`, `standard`,
`neutral`, `aces13`, `aces20` or `raw`; AgX additionally has a contrast choice.
Exposure is in stops: one stop doubles scene-linear values. Gamma is positive.
White balance is explicitly off or on with temperature in kelvin and tint.
Standard/sRGB is useful for quantitative colour patches; AgX/Neutral/ACES tone
mapping changes the appearance of highlights. These transforms do not replace
image texture colour-space declarations.

Output stays non-interlaced 8-bit RGBA PNG with sRGB display and zero output dither.
Output colour management follows the declared scene; per-output overrides and an
undeclared switch from surface shading to wireframe are refused.
A valid uniform image is allowed: colour-channel variation is not a validity test.
Native verification checks the declared controls and graph/pointer state. Imported
asset data is independently reconstructed from captured source bytes and authorised
field/edit/binding intent before opening the submitted project; stored asset
readbacks cannot replace that source authority. Active UV and active/render colour
selectors are part of asset fidelity. Integer identifiers retain exact types and
values; custom metadata compares exactly, separately from native floating-point
rounding tolerance. Independent qualification separately checks independent colour/exposure expectations. General
verification does not rerender every arbitrary image as an exact pixel oracle.
Custom OCIO configurations/LUT capture, texture painting and baking,
MatCap flip intent/readback, render layers/AOVs, multilayer EXR and broader
render/cache controls remain application-wide gaps.

The fixed baseline is Blender 5.2.3 LTS. See the official
[rendering manual](https://docs.blender.org/manual/en/5.2/render/index.html),
[EEVEE ray-tracing API](https://docs.blender.org/api/5.2/bpy.types.RaytraceEEVEE.html)
and [5.2 rendering changes](https://developer.blender.org/docs/release_notes/5.2/rendering/).

Layered artist finishes, image role/channel sampling, shared stored UV normal bases and built-in OSL applicability are described in [Layered surface materials](blender-surface-materials.md). Whole Blender coverage remains unfinished.
