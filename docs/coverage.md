# Coverage and next milestones

Updated 2026-09-25. Executable discovery is the exact option-level contract.

| Area | Implemented | Important limits |
| --- | --- | --- |
| ParaView | 61 curated interfaces + 535 generated source/filter and 44 writer bindings; explicit output ports, tables, partitioned data, AMR and hyper-tree grids | 5.13.3 serial and a qualified 10-operation MPI subset; generated bindings are not native qualification; format-specific fidelity checks; some native writer fixtures fail; trusted extension packages |
| Blender | 37 operations; direct STL/PLY import, evaluated STL exports; Cycles CPU/CUDA/OPTIX; materials, native scene reopening | Saved-scene render groups; no animation, Geometry Nodes or full Blender parity |
| FreeCAD | Solid features, booleans, polygon and fully constrained rectangle/circle sketches; extrusion/revolution, loft, list unions, fillet/chamfer, STEP input; native fixed assemblies | 1.1.x; mm; solid pipeline outputs one solid; assembly contract is a separate fixed-joint tree with linked box/cylinder parts; no motion solver qualification or FEM |
| Godot | 13 operations including PNG Sprite3D; native material/primitive/glTF scene construction, camera, directional/omni/spot lights and checked geometry transforms, editable project/scene, fresh-process reopening | 4.x; bounded glTF subset; no arbitrary authored scripts or complete game authoring; retain the whole project bundle |
| Aseprite | Sprite, layers, frames, palettes, pixel/rectangle/circle drawing, animation tags; editable sprite and sheet outputs | 1.3.x; bounded dimensions/frames; opaque RGBA or fully transparent colours; no arbitrary authored Lua |
| FFmpeg | PNG sequences and timed sprite sheets to H.264/FFV1; native decode and stream checks | 600 frames, bounded RGB/RGBA PNG, alpha on black, no audio or arbitrary filters |
| QGIS | Four vector operations: GeoJSON/GeoPackage import, EPSG reprojection, metric buffer, rectangle clip; project/map publication | 2D, one-layer files, bounded feature/vertex counts; no raster/terrain or live geometry |
| Octave | Eleven operations: samples/CSV, sequences/signals, scale, resampling, moving means, derivatives, integration, linear fits and FFT | 11.3.0; real bounded 1D tables, no arbitrary code or plotting |
| Calc | Numeric tables, formula summaries, native XLSX → ODS round-trip | 26.8.0.3; fixed formulas, numeric cells; no live Excel/OnlyOffice/Sheets connection |
| Shared console | Durable multi-document authoring, history, previews, checkpoint provenance, local visual UI, prose with revision-bound native/image references | Declared commands execute; arbitrary prose is recorded only; live geometry supported by bounded FreeCAD/Blender/ParaView clients; native GUI edits are not reverse-synchronised |
| Application workflows | Resource-aware concurrent jobs, durable artifact references, verified retries; Godot/Aseprite/media/geospatial handoffs | No cross-process live objects; glTF bridge has a bounded mesh contract |
| Local tooling | Blender source build, Godot, FreeCAD, Aseprite, whisper.cpp CUDA, ComfyUI SDXL | See each registered provider's installation contract; installed tooling alone is not an adaptor |

Added Blender geometry: plane, UV sphere, ico sphere, cylinder, cone, torus;
solidify, subdivision, decimate, triangulate, smooth, array, mirror, boolean, transform.
Existing material, cube, bevel and glTF reader remain supported.

Added ParaView: cone, cylinder, plane, disk; seven dataset/mesh readers;
ID generation, array selection, curvature and structured subset extraction.
Native acceptance covers these operations on supplied simple datasets. It does
not establish every enum/option combination or arbitrary production-file compatibility.

See [catalogue intake, capability contracts and extension language](paraview-catalogue.md).
`schemaxis coverage` accounts for all 596 inventoried source/filter/writer definitions and five typed resource definitions,
including exclusions; it does not claim full application parity.

## Earlier proposed product sequence

1. Package one repeatable engineering demo: dataset → ParaView analysis → Blender
   presentation → evidence bundle. Make installation and failure recovery boring.
2. Test that workflow with a few prospective users and measure time saved. Prioritise
   their blocking gaps before another broad application wrapper.
3. The first bounded FreeCAD provider is now implemented: see [CAD examples](freecad-examples.md). Expand against concrete workflows.
   Existing CAD tooling and numeric geometry checks make this a coherent next bridge.
4. Add Godot when a workflow needs interactive delivery; Aseprite is already available
   for sprite assets. Keep local AI generation as an asset-production companion.
5. Expand adaptors against real workflows, then qualify larger data, packaging,
   supported-platform matrices and MPI where required.

The current user-directed priority is auditing/replacing the console, a shared
multi-adaptor foundation, visual feedback and selection-as-language, followed by
bounded native adaptor growth. On 2026-09-25 the user explicitly requested numerical
and spreadsheet expansion; Octave and Calc are now implemented. Browser automation
and direct Excel/OnlyOffice/Google Sheets integration remain future work.
The sequence above is a prior engineering recommendation, not evidence of demand. User
validation remains necessary; broad feature parity alone does not establish a product.

The current CAD and mesh expansion is documented in [CAD and mesh workflows](cad-and-mesh-workflows.md), with native acceptance examples and explicit exchange losses.

## Media and geospatial expansion

See [media workflows](media-workflows.md) and [QGIS](qgis.md). The new applications
extend the earlier sequence with concrete image/video and vector GIS contracts.
FreeCAD assemblies, richer multi-object glTF/material exchange, GIS terrain,
FFmpeg titles/layouts and a user-selected BIM/electronics/CFD vertical remain
future work. Broad native app parity and user demand are not established by
these additions.

Native evidence and exact checks: [media/geospatial qualification](../verification/2026-09-20-media-geospatial.json).

See [September adaptor expansion](adaptor-expansion.md) and [numerical analysis](numerical-analysis.md).
