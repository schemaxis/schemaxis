# Named FreeCAD measurements

A CAD model can publish named geometric quantities for expressions and other
adaptors. Add `measurements` to a `schemaxis.freecad/1` document:

```json
"measurements": [
  {"id":"finishedVolume", "node":"rounded", "quantity":"volume"},
  {"id":"height", "node":"rounded", "quantity":"extentZ"},
  {"id":"verticalEdgeLength", "node":"blank", "quantity":"totalEdgeLength",
   "edges":{"where":{"parallelTo":[0,0,1]}, "expect":4}}
]
```

Every ID must be distinct; each node must be a declared solid. Measurements may
inspect intermediate nodes as well as the final output. The list contains 1–32
entries when present. The [example](../examples/schemaxis/freecad-measurements.json)
measures a rounded part and the original blank's vertical edges.
These named scalars can also drive a bounded [CAD target study](freecad-design-studies.md).

| Quantity | Value | Units |
| --- | --- | --- |
| `volume` | Positive solid volume | `mm^3` |
| `surfaceArea` | Total native surface area | `mm^2` |
| `extentX`, `extentY`, `extentZ` | World-axis bounding-box extent | `mm` |
| `centreOfMass` | Three world coordinates, assuming uniform density | `mm` |
| `bounds` | `[xmin,xmax,ymin,ymax,zmin,zmax]` | `mm` |
| `totalEdgeLength` | Sum of the selected edge lengths | `mm` |
| `edgeCount` | Number of selected edges | `count` |

Only the last two quantities accept and require `edges`, using the
[semantic selector or explicit-index contract](freecad-selections.md). Selection
must succeed; missing or ambiguous matches fail the candidate. Multiple edge
measurements of the same source share one inventory. Each inventory is bounded to
10000 edges and the combined measurement inventory to 20000.

The uniform-density centre combines constituent solid centres using volume
weights, including native compounds produced by finishing. It does not infer
materials or calculate physical mass. World extents are not principal dimensions,
wall thickness, clearance or manufacturing checks.

## Publications and value references

Without measurements, the existing three publications retain their order. With
measurements, the adaptor appends `measurements.json` as **artifact 3** after STEP
(0), STL (1) and FCStd (2). Each named entry identifies its source node, quantity,
units and `value`; edge entries also retain their selected indices.

A workflow value reference can read the finished volume:

```json
{"$value":"cad", "artifact":3, "path":"/measurements/finishedVolume/value"}
```

The producer must verify before any consumer can resolve this value. The consumer
still owns the interpretation and expected units; no implicit unit conversion is
performed. A numerical expression can explicitly convert mm³ to cm³ by multiplying
by 0.001.

The [measured workflow](../examples/schemaxis/freecad-measured-workflow.json)
executes two analytic CAD heights. For each variant, its measured height controls
Gmsh's mesh size, while measured volume and edge length feed an Octave table. It
combines verified file handoff (STEP) with verified value handoff from the same
producer. Unchanged complete jobs support normal workflow reuse.

Use public `inspect_resource` with a pointer such as
`/measurements/finishedVolume` to inspect the value and units together. A dedicated
live session's `geometry` response includes the requested measurement publication
under `measurements`, associated with that geometry revision. Invalid measurement
selection during a live apply rolls back the native transaction.

## Verification

Build and fresh native reopening independently measure the requested nodes.
`built.json` and `verification.json` retain `measurementObservations`. Host
verification checks source membership, finite positive geometry, coordinate
bounds, selection predicates, units and derived values. The published JSON must
exactly agree with the build observation, and reopening must agree within the
stated numeric comparison. Updating only a publication's hash cannot legitimise
an altered value. Existing native/STEP/STL checks remain in force.

These measurements use FreeCAD's native BREP kernel; the host does not contain a
second independent BREP implementation. The acceptance tool adds independent
rounded-prism volume, area, extent and centre formulas, tests translated variants,
challenges measurement evidence, and checks downstream native numerical results.
See [verification](../verification/2026-09-30-freecad-measurements.md).
