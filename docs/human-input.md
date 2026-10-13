# Start with the car, not a calculator

[humanInput.json](../examples/paraview-vehicle-demo/humanInput.json) is a runnable
vehicle template. It separates three jobs:

* **dimensions** records measurements: model bounds and ground height.
* **views** describes intent: include an upstream length and a downstream wake,
  extend sideways by a model width, and frame a vehicle orbit.
* **settings** holds the case path, patch names, field styles, output size and counts.

The remaining pipeline is reusable. For another case with the same patch naming,
change the case path and dimensions. Different patch names or fields necessarily
require corresponding settings changes; dimensions cannot identify geometry.
The template assumes downstream is +X and vertical is +Z.

## Seven coordinates, many views

```json
"dimensions": {
  "model": {
    "min": [-0.881434, -1.05855, -0.33061],
    "max": [3.26831, 1.05855, 0.802693]
  },
  "ground": -0.332088
}
```

No wheel or mirror dimensions are required for the requested views. Add named
bounds when you need a wheel close-up; avoid maintaining unused measurements.
The ground is the supplied domain floor, not the model's lowest coordinate.

```json
"modelAndWake": {
  "$value": "boundsFrame",
  "args": {
    "bounds": {"$document": "/dimensions/model"},
    "before": [1, 1, 0],
    "after": [2.5, 1, 0],
    "floor": {"$document": "/dimensions/ground"},
    "aspect": [16, 9]
  }
}
```

`before` and `after` are multiples of the **original** X/Y/Z extents.
`boundsFrame` extends the bounds, sets the floor, then supplies enough height for
a YZ cross-section of the requested aspect ratio, while retaining the model.
If a tall model requires more height, inclusion takes priority over aspect ratio.
The sample resolves to X [-5.031178, 13.642670], Y [-3.175650, 3.175650], and
Z [-0.332088, 3.24051825]. No one needs to type those calculated coordinates.

Use `boundsExtend` for general expansion; negative factors shrink a bound.
`boundsUnion` accepts a list of bounds and encloses them all. These are spatial
calculations, not mesh operations. Invalid or inverted bounds are rejected.
Named views may reference other named views. Reference cycles are rejected.

## Zoom, leave the data alone

There are **no clip filters** in this template. Slices pass through the internal
fluid domain. `slicePositions` derives uniformly spaced positions between the
named view's limits; one requested slice is placed at the centre. `fitCamera`
frames the named bounds without distorting the geometry. A 16:9 camera may see
additional surrounding data where the view's physical aspect ratio differs.
`padding` adds breathing room and can be set to zero for a tighter frame.
Camera zoom does not reduce the mesh size or processing cost.

The orbit derives its focal point and distance from the vehicle view bounds;
`distanceScale` is a dimensionless multiplier. Its 12 azimuths cover a revolution
without duplicating the starting frame. Elevation is 25 degrees. Images are
stills, not an encoded movie. Model dimensions, projection and output aspect
can be changed independently; extreme perspective aspect ratios may need a
larger distance multiplier.

The contour uses **xkcd:radioactive green**. Its p=-250 value, the colour ranges,
and the patch groups are editable settings. p is interpolated from cells to
points for contour construction; p, U magnitude and nut slice colours remain
cell-based. The file uses stored field values without an assumed unit conversion.

## Directions that read like directions

Cameras and filter normals accept `[x, y, z]`, `"x+"`, `"y-"`, or
`{"azimuth": 30, "elevation": 25}`. With the default Z-up convention, azimuth
starts at +X and increases towards +Y; elevation rises towards +Z. Camera
direction means **from the focal point towards the camera**, not viewing inward.
`up` also accepts these forms and must not be parallel to camera direction.
`directionVector` constructs a vector from any of these forms, with an optional
length. This is useful for vector-valued options that are not directions.

## One declared language for humans and agents

`$document` uses a JSON pointer to reuse a value. `$value` calls a declared pure
function at authoring time, after its argument references resolve. It cannot run
Python, import arbitrary modules or read arbitrary files. The same typed function
catalogue is available to runtime `$call` expressions. The reference generator
publishes argument types and defaults from that catalogue.

```bash
PYTHONPATH=src python3 -m schemaxis query examples/paraview-vehicle-demo/humanInput.json
PYTHONPATH=src python3 -m schemaxis schema --expand examples/paraview-vehicle-demo/humanInput.json
PYTHONPATH=src python3 -m schemaxis run examples/paraview-vehicle-demo/humanInput.json \
  --paraview-root /path/to/ParaView-5.13.3 \
  --output-directory evidence/my-vehicle --timeout 600
```

Use a new output directory. `latest` is resolved through native reader metadata;
only that selected time is executed. `plan` alone cannot discover source times.
The generated document schema applies to the **expanded** input, not the authored
reference/function markers. Schema validation checks structure; native execution
and visual review remain necessary. `verification.json` records image identities,
effective appearances/cameras and hashes; authoring resolution records how the
references and calculations were obtained.

`pvbatch` execution is currently serial. Reading a decomposed case accesses all
processor directories but is not MPI-distributed execution. The refactor does
not add or claim an MPI launcher.
