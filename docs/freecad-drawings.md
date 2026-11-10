# Technical drawings from checked CAD geometry

Use `schemaxis.freecad.drawing/1` to turn a solid into an editable TechDraw sheet,
with independently specified dimensions and native SVG/PDF publication. This
adds a manufacturing documentation workflow. TechDraw's broader section, detail,
hatching, GD&T, balloon/table and multi-page workflows remain programme gaps.
It does not complete the FreeCAD adaptor.

Declare what the sheet should communicate: paper size, title/revision, standard
views, scale, dimensions and notes. Schemaxis lays out the views on A4 or A3
landscape paper, reserves a title strip, and chooses one common conservative scale
when `scale` is `fit`. Explicit scales that exceed that envelope fail instead of
silently clipping the geometry. Dimension label positions are page coordinates
in millimetres, measured from the lower-left corner; native relative coordinates
are handled internally. Default horizontal dimensions occupy separate lanes above the view, and
vertical dimensions occupy separate lanes to its right. The fit calculation
reserves those lanes and shifts the geometry within its cell; three dimensions
on one view need no authored paper coordinates. You can place labels explicitly;
automatic layout is not a general annotation collision solver.

```json
{
  "version": "schemaxis.freecad.drawing/1",
  "source": {
    "file": "stock.FCStd",
    "object": "stock",
    "units": "mm",
    "expect": {
      "volume": 12000,
      "bounds": [0, 40, 0, 30, 0, 10],
      "centreOfMass": [20, 15, 5]
    }
  },
  "sheet": {"title": "Machining stock", "revision": "A", "scale": "fit"},
  "views": ["front", "top", "right", "isometric"],
  "dimensioning": [
    {"id": "length", "view": "front", "type": "overallWidth"},
    {"id": "thickness", "view": "right", "type": "overallHeight"}
  ],
  "notes": ["All dimensions in mm", "Deburr sharp edges"]
}
```

`dimensioning` is the drawing annotation list. The framework's `dimensions` field
retains its existing document-value meaning; it is not a list of TechDraw objects.

## Capture and source ownership

A plain STEP input uses the existing checked single-solid STEP vocabulary and
its 32 MiB/100000 entity/2000 loop-edge limits. `source.units` asserts the unit
the file actually assigns: mm, cm, m or inch. FreeCAD converts that geometry to
its native millimetres. The expectations and the published drawing always use
millimetres; declaring another unit never rescales a file arbitrarily.

An FCStd input needs `object`, naming exactly one internal object name or unique
label. The host reads a bounded archive/XML record and extracts only that object's
stored BREP shape. It never opens the input document in FreeCAD and never restores
proxies, scripts, macros, add-ons, expressions or linked files. This permits a
frozen shape from an otherwise complex project without executing its history.
The selected stored shape frame is the drawing frame; assembly parent transforms
and App::Link instance resolution are not reconstructed. Export a positioned
STEP solid when a world assembly placement matters. The native reader must find
one valid positive-volume solid matching the declared volume, ordered
`[xmin,xmax,ymin,ymax,zmin,zmax]` bounds and uniform-density centre of mass.
These are declared geometric checks, not proof of the identity of symmetric parts.

The drawing embeds its own frozen source shape and sheet template. It owns no
live link to the original model. Keep the upstream CAD publication for editable
feature history. Native drawing edits do not reverse-synchronise to Schemaxis,
and a later upstream model edit requires a new drawing run. Captured source bytes
are hashed and retained; saved verification works after the original supplier
file has been removed.

## Dimension intent

Six orthographic directions and `isometric` are available. Measurements use
orthographic views; isometric presentation is not dimensioned.

| Intent | Meaning and selection |
| --- | --- |
| `overallWidth`, `overallHeight` | Measure projected model extents. Independent expected values come from the authored source bounds. Equivalent coincident extreme vertices are interchangeable for the specified axis distance. |
| `horizontal`, `vertical`, `distance` | Measure between source-coordinate point selectors, projected onto the view. Each `from`/`to` record names `point: [x,y,z]` and `on: vertex` or `circleCentre`. A circular centre also declares its `radius`; the projected circle must match that position and radius uniquely. |
| `diameter`, `radius` | Select exactly one projected circle by `radius` and measure it. Several equal holes are ambiguous; use point-based circular-centre dimensions for their mounting offsets. |
| `edgeLength` | Measure exactly one straight projected edge of the declared `length`. Equal-length edges require a more specific point-based dimension. |

For an enclosure with a 2 mm wall, for example, a top-view `horizontal` dimension
can select outer corner `[0,0,30]` and inner corner `[2,2,30]`. A mounting offset
can run from an outer corner to a circular centre such as
`{"point":[10,10,2],"on":"circleCentre","radius":2}`. Endpoints are resolved
against the current projected geometry every time. Authored native edge/vertex
indices and arbitrary native properties are not exposed.

The native objects keep measured values rather than substituted text. A label
position does not change the measured quantity. Automatic circular labels use
alternating sides of the view so radius and diameter leaders have different
directions and retain the standard `R`/diameter symbols; linear dimensions use
separate horizontal or vertical lanes. An
explicit page position remains available for a chosen drawing arrangement.
Missing/ambiguous anchors fail
with `EMPTY_SELECTION`/`AMBIGUOUS_SELECTION`; invalid intent and out-of-sheet
layout fail before launch. A source that does not match its declared facts fails
with `EXPECTATION_FAILED`. Correct the source, view or selection rather than
replacing a measurement with an arbitrary display value.

## Delivery and verification

The run publishes `drawing.FCStd` (artifact0, `cadScene`), `drawing.svg` (1,
`image`) and `drawing.pdf` (2, `document`). Supply both the command-line and GUI
FreeCAD locations through normal local configuration. The GUI publication process
uses a private virtual display, D-Bus session, configuration, application data
and temporary directories. Startup suppresses the CAM asset migration offer in
that private profile; native receipts confirm the effective isolation paths.
It does not change the
user's PATH or preferences.

The supported native baseline is FreeCAD1.1.4. A command process builds the
sheet, a fresh command process reopens it and changes/restores a native view
scale, and a separate GUI process recomputes and publishes it. Verification
checks declared geometry, projection spans and frames, sheet ownership, measured
text, native dimension links, persisted types/settings/layout, annotations and
embedded template units. Native SVG dimension text is checked against authored
geometry independently of App measurement readback: on this runtime a missing
GUI recompute can publish zero despite correct App readback. Artifact hashes
and a PDF signature/truncation check complement these content checks; the native
acceptance also renders and inspects PDF output. This is not exhaustive PDF or
annotation collision validation.

`examples/schemaxis/freecad-drawing-workflow.json` demonstrates a CAD output
feeding a drawing through `$artifact`, followed by verified reuse. The native
qualification tool exercises an independently constructed enclosure, wall and
mounting dimensions, STEP/source variants, native edits/fresh reopen, incorrect
geometry, ambiguous holes, refreshed-hash semantic tampering, damaged publication
invalidation and retained-source verification.

## Public API basis and remaining work

The mappings use the stable [FreeCAD1.1.4 TechDraw source](https://github.com/FreeCAD/FreeCAD/tree/1.1.4/src/Mod/TechDraw),
the documented [TechDraw GUI publication API](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/TechDrawGui_API.md),
and the [latest stable release](https://github.com/FreeCAD/FreeCAD/releases/tag/1.1.4).
The implemented set covers standard mechanical sheets, not all drafting intent.
Sections/details, clipping/breaks, hatching, tolerances/GD&T, datum symbols,
weld/surface-finish symbols, hole tables, bills of materials, multi-sheet layout,
DXF publication and associative upstream model updates remain substantial gaps.
They remain in the strategic completion denominator.
