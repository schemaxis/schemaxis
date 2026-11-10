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

Coordinates and edge directions refer to the selected native occurrence in world
space. For a Body-owned feature, its containing Body frame is applied exactly
once, including intermediate features. A final seeded or explicitly placed Body
uses the same world carrier as its part export. The source-history verifier's
separate Body-local witness is not a named world measurement. Existing receipts
from a misframed older run need a new verified publication; changing coordinate
values in a receipt does not repair their provenance.

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

## Coordinate frames and helical geometry

Coordinates, bounding boxes and geometric edge predicates use the native world
frame. This includes intermediate features inside a placed Body: the containing
Body frame and the feature's own placement each apply once. The publication
records `coordinateFrame: "native-world"` and millimetre coordinate units.

For a typed Helix graph, volume and uniform-density centre of mass come from
empirical oriented flux and first moments of a formal float-endpoint model. The original
face charts are joined by typed edge ribbons, collapsed-edge fans, vertex caps
and curved connector patches. The executable ledger checks zero symbolic incidence
using the same pieces and coefficients and their floating endpoint tokens. Its
`zeroBoundary` result does not certify geometric closure of the ideal coefficient
laws: law-to-token endpoint jumps are not integrated. Surface area is the empirical
area of the original charts with straight UV connectors; it excludes the artificial
joining skin. These quantities are representation-specific. Native and STEP
surface areas are compared at the stated comparison tolerance L, not L/1000.

Two differently partitioned integrations check numerical resolution. The same
instrument measures requested intermediate solids; an exact output occurrence
reuses its checked result within the shared request budget. The publication
records `solidMeasureMethod: "schemaxis.freecad.gauss-green/2"` and
`certifiedErrorBound: false`. The local integration targets are L/1000 and the
partition comparison is L/10. Neither is a certified whole-geometry error bound.
Native kernel values condition the calculation and check positivity; they are not
the published Helix solid measures or a test of geometry identity.

Completion checks sampled face-trace gaps against native edge tolerances and
endpoint gaps against native vertex tolerances. New UV connectors must pass finite
coefficient-hull separation checks, including the non-endpoint portions of
adjacent curves and other new connectors. Isolated shared endpoint contact needs
a finite separating-cone proof. A further terminal-overlap case permits a
connector to retrace a strict terminal subset of an adjacent affine curve in
the opposite wire direction. When finite coefficient and endpoint laws agree,
this is an exact stored-law zero-chain retrace. Eligible curves
are lines or reviewed degree-one, two-pole rational spans with positive weights.
Native three-dimensional seam closure does not invalidate an injective affine
UV law. If both ends retrace, their exact parameter intervals must leave a
strict nonempty retained span, even when they share one native vertex.
Whole-edge, beyond-end, crossing, curved or ambiguous overlaps refuse. The
original charts and completion pieces are still integrated in full; no numeric
piece is removed, projected, snapped or subtracted twice. One explicitly empirical
line-end case also permits a floating token that differs from the exact law end,
provided both that token and the connector's other end are exactly collinear with
the stored line. The other end must lie strictly inside both the ideal and
evaluated line segments. Exact overlap then cancels, but a non-integrated endpoint
jump remains; the record retains its rational vector and ordering and makes no
zero-flux claim. Rounded off-line ends, rational endpoint disagreements and
ambiguous orderings cannot use this additional case.
Native evaluation and integration still use floating arithmetic: a line's
evaluated endpoint, a connector's subtracted slope, and subdivided or
knot-inserted homogeneous controls can round. The endpoint-cone tests on those
controls do not certify separation of the original native curve at arbitrarily
small angles. A very small synthetic angular-separation test establishes the
finite predicate's behaviour, not native geometric accuracy at that scale.

Every line endpoint jump receives the same sampled chart-one-form diagnostic,
including lines without terminal overlaps and added UV connectors. For connectors,
the token is the declared next trace endpoint, rather than the connector's rounded
end evaluation. The diagnostic samples the actual Green primitive at the rounded
ideal end, midpoint and token, then multiplies componentwise sampled magnitudes by
the exact jump's converted differential magnitude. Its gauge and samples are
retained. A separately preflighted diagnostic envelope leaves the measured chart's
domain, primitive gauge and arithmetic unchanged. Nonfinite or unrepresentable
nonzero jump coefficients refuse. Area, volume and normalised first-moment
companions combine with the other empirical choices, with joint volume-to-centre
propagation and the unchanged L/1000 targets. This is a line-specific chart
diagnostic, not total closure uncertainty or a bound; higher-degree primitives
can exceed its three-sample estimate. Conic/rational endpoint jumps, 3D ribbon and
fan end rungs versus floating caps, connector patch end rounding, native evaluation
and quadrature roundoff remain unmodelled.
Conics have an additional exact rational disjointness test between the ideal
endpoint-to-endpoint connector and the entire ideal stored ellipse. Its convex
implicit quadratic must be strictly positive everywhere on the connector, or
strictly negative everywhere. Endpoint or interior zeros remain unresolved.
Incidence still requires the original float-evaluated endpoint identity before
this test. Two additional finite conic cases declare an isolated auxiliary lens:
a single closed conic occurrence whose stored width is strictly between one and
two true periods, and a terminal tangent contact with an exactly rational point
on the stored ellipse. The latter requires an injective arc shorter than half a
period, a unique phase lift and a strictly isolated terminal neighbourhood.
Both cases retain the original parameter domains, numerical boundary pieces,
float endpoint tokens and connectors. They do not snap a period or replace a
native curve. Period and phase decisions use bounded outward dyadic enclosures;
unresolved phase, incidence, overlap or support separation refuses.

The declared support must be strictly separated from every unrelated curve and
connector. Rational-curve support tests use exact rational original controls;
unresolved multi-span hulls refuse rather than relying on rounded knot insertion.
The diagnostic surface continuation is preflighted separately, without changing
the measured chart domain or its knots. Its winding-difference caps are two for
the full-turn residual and one for the terminal tangent lens. These are local
auxiliary winding caps, not a certificate that the native wire is simple.
Published chart area is winding-weighted area, rather than a guarantee of
unsigned physical area for a multiply covered chart.

Each lens receives a separate chart-density diagnostic: its exact support area
times its winding cap times a componentwise sampled density maximum. Nine
affinely placed samples use the existing area, volume and normalised first-moment
densities. The nonnegative companions enter the same joint volume-to-centre
propagation as the other empirical diagnostics. This diagnostic does not depend
on the chosen Green primitive, but it can depend on the three-dimensional flux
reference origin. Sampled maxima can miss peaks, so this is not an error bound.
The ideal-conic-to-rational-token joins are neither integrated nor assigned a
chart-one-form jump diagnostic. Conic/rational endpoint jumps, three-dimensional
rung/cap gaps and native floating evaluation therefore remain unmodelled.
Other over-period or tangent configurations still refuse, with no automatic
fallback. Kernel validity alone does not establish availability for every
Revolution intermediate.
Original parameter spans can be obtained by native segmentation; their retained
coefficients are the laws integrated here. The records retain
empirical confinement proxies, a trace-position area companion and an independent
coarse signed-mesh winding discriminator. Sampled maxima and floating hulls are
not interval bounds. The coarse mesh does not prove shell non-self-intersection
or rule out small winding errors. Shell non-self-intersection is assumed, and
original UV wire simplicity relies on the native kernel's tolerance-based
validity check. The native diagnostic mesher allocates before the one-million
facet/point check and cannot be interrupted by the Python numerical timer; it
also requires the external runner's memory and wall-clock limits.
A kernel-valid STEP can still refuse when its
reconstructed face traces contradict its saved tolerance. Scalar agreement does
not override that refusal.

The unchanged shared request limit is four million native evaluations, with two
million per measurement level, adaptive depth 18 and a 240-second numerical
budget. Public execution also has its caller's runtime deadline (normally 300
seconds). Intermediate measurements, native and STEP representations share these
budgets. The graph's limit of 1000 turns is an input bound, not a promise that a
1000-turn model can be resolved. Profile complexity, pitch, radius, conicity,
growth, handedness and native STEP projection affect availability. Requests can
refuse for unresolved geometry, resource limits or deadline expiry. Qualification
includes particular three-, six-, twelve- and twenty-four-turn controls; it does
not establish a complete parameter envelope. The 24-turn STEP fine level used
about 1.934 million of its two-million evaluations, so larger or more complex
requests may exhaust the fixed budget. No automatic tolerance or budget relaxation
is applied.

Regenerate older measurement publications before reuse with the current adaptor.
The explicit frame metadata and world-coordinate Body observations change their
verification contract; older receipt bytes are not accepted as current evidence.

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

These measurements use the original native BREP geometry; the host does not
contain a second independent BREP implementation. Ordinary solid measures use
the native kernel values; typed Helix graphs use the bounded instrument above. The acceptance tool adds independent
rounded-prism volume, area, extent and centre formulas, tests translated variants,
challenges measurement evidence, and checks downstream native numerical results.
See [verification](../verification/2026-09-30-freecad-measurements.md).
