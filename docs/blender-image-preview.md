# Image previews on scientific and product surfaces

Workbench can display a captured image independently of the material's shader.
Use `render.renderer.colourSource: {"kind":"texture"}` and select
`materialGraphs[].displayTexture: {"kind":"image","image":"fieldImage"}`.
The image name refers to `production.images[].id`; it is not a file path or a
native node name. Root material graphs own this choice; reusable node groups do
not. Cycles and EEVEE continue to evaluate the material's shader graph.

The [runnable surface example](../examples/schemaxis/blender-image-preview.json)
uses a small authored four-quadrant image, a scalar temperature channel and two
UV sets. Workbench uses `meshData.activeUV`; shader rendering can independently
use `renderUV` or an explicit named UV node. The active map in this example shows
the four image quadrants in their original order. Its shifted render map would
exchange the left and right quadrants. Flat lighting, Standard/sRGB, zero exposure
and disabled antialiasing make interior colour samples directly interpretable.
Studio's **Captured image on a scientific surface** starter asks for an image
file before insertion. Its required path has no fabricated default.

`displayTexture: {"kind":"none"}` deliberately chooses the material's
`viewportColour`, even when the shader graph contains other image nodes. A mesh
without usable UVs also falls back to that swatch on the qualified native release.
The adaptor maintains a separate unlinked preview node; it does not connect the
preview image to a shader input. The image remains a declared retained resource
even when no shader node uses it.

An image's `colourSpace` describes its stored values. Use `sRGB` for ordinary
encoded colour images and `Non-Color` for linear scientific/data channels.
The display transform still encodes the final render. `alphaMode` defaults to
`straight`, where RGB and alpha are independent stored channels with alpha acting
as a mask. `premultiplied` means the stored RGB already contains the alpha factor.
`channelPacked` keeps all channels independent, including RGB where alpha is zero;
`ignore` treats the image as opaque. These interpretation choices affect shader
consumers of the same image too. Workbench preview transparency is native display
behaviour, not a general compositing or optical-transmission model.

Files are limited to 64 MiB each and 256 MiB in aggregate. Each decoded image is
limited to 8192 pixels per axis and 4,194,304 pixels; all declared images together
are limited to 16,777,216 pixels. PNG/JPEG dimension headers are checked before
native decoding. Other supported single-file image formats receive the pixel
checks immediately after native load, before packing and material evaluation.
This policy covers one file, one view and one ordinary tile; UDIM, sequences and
multiview resources remain unfinished. Images use the fixed baseline's
half-precision cache policy. Capture checks byte counts and content stability;
verification checks original and retained bytes plus the saved native image's
interpretation and packed payload.

`RESOURCE_NOT_FOUND` needs a restored or corrected source path.
`INVALID_RESOURCE` needs a regular file, rather than a directory, FIFO or device.
`RESOURCE_UNREADABLE` needs readable storage and permissions.
`RESOURCE_BUDGET_EXCEEDED` needs smaller images or fewer resources. Recovery uses a
new output directory; a partial run is not a successful reusable scene.

For deliberate manual edits, save a separate native project, run
`schemaxis input adopt <saved.blend> <snapshot-directory>`, and place the returned
`reference` at an asset's `file` inside a workflow. Blender accepts pinned
single-file references at image/asset files, declared mesh/CSV reader files, and
the saved-scene render route's `sceneFile`. Directory and file-set references,
other fields and undeclared readers are refused. The existing native policies
still require supported self-contained inputs; adoption does not package missing
external libraries or caches. Resume rechecks both the pinned snapshot and current
native result. Changing the original saved edit after adoption does not change
its snapshot; adopt again to request a different input.

Native verification binds the preview image/helper, interpretation, packing and
UV selectors. Imported material fidelity is reconstructed independently from
captured inputs before the submitted project is opened. Submitted readbacks are
not source authority. Qualification uses independently expected encoded pixels,
including fractional straight versus premultiplied linear channels. General
verification checks bounded PNG decoding and declared native state; it does not
rerender arbitrary images as an exact pixel oracle. Texture painting, baking,
multi-slot/per-face authoring, UDIM layouts and broader rendering remain open.

The fixed baseline is Blender 5.2.3 LTS. Official references:
[Workbench object colour](https://docs.blender.org/manual/en/5.2/render/workbench/color.html)
and [Image interpretation API](https://docs.blender.org/api/5.2/bpy.types.Image.html).
