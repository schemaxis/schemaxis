# Vehicle and wake demonstration

`input.json` is Schemaxis input, executed through ParaView's OpenFOAMReader; it
is not a ParaView state file.

The vehicle case is not distributed with Schemaxis. Bind your own decomposed
OpenFOAM case: the examples name the placeholder `cases/coupe/coupe_AMI.foam`,
which is resolved from the directory where you run Schemaxis. Either place your
case there, or replace the three `file` entries in `input.json` (or the single
`settings.case` value in `humanInput.json`) with the path to your `.foam` marker
file. `schemaxis run` has no case-override option, so edit the input or a copy of
it. The vehicle bounds, patch names and field ranges below describe the original
case; adjust them to suit yours.

The example selects only the latest available time, renders nine evenly spaced
positions per axis with three cell-data appearances (p, U magnitude, nut), and
renders twelve perspective views around the vehicle at 25 degrees elevation.
All images are 1600 × 900. The orbit is a sequence of still images, not a video.

## Volume of interest

Assume downstream is +X. The supplied vehicle bounds give length 4.149744 and
width 2.117100. The volume is:

| Axis | Minimum | Maximum |
| --- | ---: | ---: |
| X | -5.031178 | 13.642670 |
| Y | -3.175650 | 3.175650 |
| Z | -0.332088 | 3.24051825 |

X includes one vehicle length upstream and 2.5 lengths downstream. Y includes one
vehicle width on either side. Z starts at the supplied domain floor; its height
is 3.57260625, giving the YZ cross-section a physical 16:9 aspect ratio.
The fixed X/Y extents imply a 2.94:1 top view, so every plane cannot fill a 16:9
image without either changing the requested bounds or distorting the geometry.
The cameras preserve scale and allow whitespace and room for legends.

Each plane is sliced first, then cropped along its two in-plane axes. This
avoids empty cuts caused by slicing an already-clipped boundary. Each `linear` analytic
specifies its start, end, and count directly. These are independent sweeps, not
a Cartesian product of all three axes.

## Appearance and cameras

* Solid colour: `"colour": "grey"`, `"colour": "black"`, or normalized RGB such
  as `"colour": [0.5, 0.5, 0.5]`. Schemaxis includes Matplotlib colour names.
* Field colour: `"field": ["CELLS", "U"]`, with `"component": -1` for magnitude.
* `"preset"` names a ParaView colour table. This example uses built-in Cool to
  Warm, Viridis and Inferno, with no copied private colour-table files.
* `"legend": true` or `false` toggles the scalar bar. Legend text is currently
  fixed black; orientation axes are currently fixed off. Their colour/size and
  visibility are not exposed as input settings.
* The illustrative fixed ranges are p [-500, 500], |U| [0, 50], nut [0, 0.1].
  They are display choices, not measured extrema. Values outside them saturate.
  Edit them for the desired comparison; removing `range` autoscales each slice.
* `"parallel": true` gives orthographic projection. With `false`, `distance`
  sets the camera-to-focal-point distance in case coordinate units. The orbit
  uses distance 15 and a fixed vehicle-centred focal point.
* Camera `direction` is a vector **from the focal point towards the camera**.
  Filter directions support `{"azimuth": 30, "elevation": 15, "up": "z+"}`.
  For Z-up, azimuth starts at +X and increases towards +Y; angles are degrees.
  Single-camera directions currently require vectors. The camera-list `orbit`
  analytic supports azimuth start/end/count and elevation, but does not expose
  distance/projection overrides. This example lists cameras explicitly to use
  perspective and a fixed distance.

Only the ten requested vehicle patches are shown. The yellow p=-250 isosurface
comes from the original fluid cell pressure through an explicit `cellToPoint`
interpolation, followed by `contour`. A smooth interpolated isosurface is not an
exact surface of the piecewise-constant cell field. The slice colour association
remains CELLS. Pressure values and units are used as stored in the case, without
an assumed density conversion. The contour uses the full internal fluid mesh.

## Run

From the Schemaxis repository root, with an installed ParaView 5.13.3:

```bash
PYTHONPATH=src python3 -m schemaxis run examples/paraview-vehicle-demo/input.json \
  --paraview-root /path/to/ParaView-5.13.3 \
  --output-directory evidence/vehicle-demo --timeout 600
```

Choose an output directory that does not exist. The native time inspection is
needed to resolve `latest`; plain `schemaxis plan` cannot resolve it by itself.

Schemaxis already writes a `verification.json` index with artifact paths, scene,
time/axis identity, appearance, camera, and hashes, plus the effective input and
time-selection records. Appearance indices 0, 1, 2 mean p, |U|, nut respectively.
There is no need to add per-image sidecars for this demonstration.

## Local verification (2026-09-16)

ParaView 5.13.3 selected time 1.0. All 81 slice images rendered with nonempty
slice geometry, including endpoints. The corrected vehicle branch was then run
separately: all 12 orbit images passed native verification, with nonempty tyre,
body and pressure-contour geometry. Representative slice and orbit images were
visually inspected. The final input also passed the generated JSON Schema.
The vehicle branch explicitly extracts named blocks because reader region
selection alone retained the internal mesh in this runtime.

Local evidence: `evidence/vehicle-demo-20260916-v2` for slices, and
`evidence/vehicle-demo-20260916-orbit` for the corrected orbit. Disregard the
orbit images in the former directory; they preceded the extraction correction.

## Human template

Use [humanInput.json](humanInput.json) for the newer, reusable version. It keeps
all physical coordinates in `dimensions`, derives named view bounds, and zooms
with cameras rather than clipping the mesh. Its pressure contour is
`xkcd:radioactive green`. See [the human-input guide](../../docs/human-input.md).
The earlier `input.json` remains the explicitly clipped version described above.
