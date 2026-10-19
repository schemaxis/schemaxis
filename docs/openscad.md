# OpenSCAD dimensioned parts

Use `schemaxis.openscad/1` to make a mounting plate or annular spacer from
millimetre dimensions. Stable OpenSCAD **2021.01** evaluates trusted constructive
geometry in a separate serial process. Discovery and planning use only the host
Python standard library. Authored SCAD, libraries, flags and arbitrary code are
not accepted.

## Choose a part

`plate` constructs a rectangle from local `(0,0,0)` to `(width,depth,height)`
and removes 0–16 circular through-holes. Each hole gives an XY `centre` measured
from the lower-left plate corner and a nominal `diameter`, in mm. The nominal
circles must be at least 0.5 mm inside the rectangle and 0.5 mm apart. Empty
`holes` (also the default) produces a plain plate. Holes span the entire height;
the internal cutter extends 1 mm beyond both faces to avoid coincident ends.

`spacer` constructs an annulus centred on local XY `(0,0)` from Z=0 to `height`.
Supply `outerDiameter`, `boreDiameter` and `height` in mm. Outer minus bore diameter
must be at least 1 mm, giving a nominal radial wall of 0.5 mm. A spacer always
has one through-bore. This is suitable for dimension studies and downstream
geometry exchange; no mechanical strength, manufacturability or printer
suitability is certified.

Both operations require `units: "mm"`. Dimensions range from 0.5 to 200 mm;
height is at most 100 mm. `translation` defaults to `[0,0,0]`; its three mm offsets
are limited to [-100,100] each. Rotation, scaling, unions, freeform solids,
chamfers, blind holes, imported solids and native scene editing are outside this
release. Choose exactly one matching `plate` or `spacer` object.

```json
{
  "version": "schemaxis.openscad/1",
  "operation": "plate",
  "units": "mm",
  "segments": 64,
  "plate": {
    "width": 40, "depth": 30, "height": 3,
    "holes": [{"centre": [10, 10], "diameter": 6}]
  }
}
```

## Circles and precision

`segments` defaults to 64 and must be divisible by four, from 16 to 256.
OpenSCAD's `$fn` makes an **inscribed regular polygon**, not an exact circle.
Diameter is across opposite vertices; the bore across flats is
`diameter*cos(pi/segments)`, so a nominal round shaft need not fit that bore.
Increase resolution deliberately; there is no inferred fit clearance.

Independent volume expectations use polygon area
`n*r*r*sin(2*pi/n)/2`. For a plate this area is subtracted for each hole; for a
spacer it is the outer polygon minus the bore polygon. `part-summary.json`
reports native measured volume, analytic faceted volume, ideal circular volume
and their signed faceting difference separately. The difference is approximation,
not native error. Bounds are exact nominal cardinal extrema before export.

The qualified binary STL route checks coordinates at 0.00004 mm absolute and
volume at 0.0002 relative (1e-7 mm³ absolute floor). Side-wall areas have 0.001
relative tolerance for float32/CGAL quantisation at short facets. These numerical
bounds are verification tolerances, not manufacturing tolerances. Dimensions and
translation limits keep float precision and minimum features well-conditioned.

## Outputs and verification

Each successful execution publishes, in order:

1. `part.stl`: closed oriented binary STL geometry, in mm by this contract.
2. `part.scad`: generated, inspectable native model. It is evidence/output; this
   adaptor never accepts SCAD source as an input.
3. `part-summary.json`: dimensions, bounds, topology, measured and analytic volumes,
   approximation and loss statements.

STL has no unit metadata, colours, materials or analytic curves. Set units
explicitly in consumers. The retained source, launchers, commands and input
bindings are compared against the authored plan; publication membership and
hashes are checked. A second fresh OpenSCAD process imports the STL and exports
another STL, which must preserve independently inspected geometry. Reopening must
retain the exact float32 coordinates and oriented triangle multiset; triangle
record order and cyclic starting vertices may change. A tight 1e-12 relative or
1e-12 mm³ absolute volume comparison allows accumulation rounding only. Both
representations still independently satisfy the original 0.0002 relative analytic
volume check. A new triangulation is not qualified by this facet-preserving route.

The stdlib verifier checks finite binary records and normals, exact declared
contour-corner/end-plane membership, unique triangles, opposite directed edge
pairing, one connected surface, Euler characteristic `2-2*holeCount`, outward
orientation, complete boundary-wall facets/areas, and end triangles that do not
cross or enclose contour corners. Bounds and origin-relative signed volume must
match the declared polygon extrusion. These checks are specific to the supported
parts; they are not a general STL repair or arbitrary self-intersection analyser.

The published STL and generated model are portable files, but the complete retained
execution record is **location-bound**: native commands, launchers and consumed-input
bindings include absolute run paths. Moving or copying that directory to a different
path fails verification; preserve its original location or execute a fresh run at
the new destination. Do not rewrite evidence paths to manufacture a passing receipt.
The native process HOME is the output directory, so any native settings/cache it
creates are local to that run and are not published geometry.

The version probe deliberately requires empty stdout and the exact stderr banner
`OpenSCAD version 2021.01` (apart from surrounding whitespace). Distribution suffixes
or extra Qt/Fontconfig diagnostic lines fail closed with `UNSUPPORTED_NATIVE_VERSION`.
That means the observed build/banner needs investigation and separate qualification;
it does not prove that the distribution's geometry engine is incompatible.

Use a fresh output directory. Each process is limited to 2 GiB address space,
4 MiB per output and 60 seconds CPU; the complete run shares the requested wall
deadline. Cancellation terminates the owned process tree before publication.
Inspect `construct.stderr`, `reopen.stderr` and submission records on failure.
`INVALID_CAD_CLEARANCE` requires moving/shrinking holes or enlarging the body;
`INVALID_CAD_RESOLUTION` requires a multiple-of-four segment count.
`VERIFICATION_FAILED` requires examining the retained native geometry/evidence,
not bypassing the verifier. `OUTPUT_EXISTS` requires a new destination.

## Workflow and authoring

The baseline, translated/coarser variant, spacer and invalid-clearance examples
are in `examples/schemaxis/openscad-*.json`. Studio starters expose the same typed
fields; changing operation requires replacing its matching dimensions object.
Undo restores the complete edit. Required empty values remain `$fill` markers.
The shared finite axes/expression system can vary dimensions or resolution
before literal planning, with every resolved state checked independently.

There are no external reusable input files. Workflow identity includes the
resolved authored dimensions. Verified summary values can drive a downstream
part's height, and unchanged runs reuse verified publications; corrupted cached
geometry invalidates dependent reuse. Changing authored inputs requires a fresh
workflow identity. The STL is intended for an explicitly unit-matched geometry
consumer. The included OpenSCAD-to-PrusaSlicer workflow was executed with native
OpenSCAD 2021.01 and PrusaSlicer 2.9.6: the 40×30×3 mm plate produced 15 checked
0.2 mm layers. Both jobs reused on an unchanged rerun. Geometry correctness and
slicer/toolpath checks remain separate; no printer was controlled.

## Qualification and sources

The release targets the official latest stable 2021.01, not development/nightly
builds. Native qualification is bounded to the cases in the completion note and
source-bound receipt; the presence of a runtime or an old receipt is insufficient.
Run `tools/qualify_openscad.py --openscad /absolute/path/to/openscad
--output-directory evidence/openscad-fresh` after the registered delivery is
reviewed. Add `--prusaslicer /absolute/path/to/prusa-slicer` to repeat the actual
STL-to-toolpath handoff. See [completion evidence](../verification/2026-10-17-openscad-completion.md).

Official sources reviewed for this implementation:

- [Downloads and stable/nightly distinction](https://openscad.org/downloads.html)
- [2021.01 release](https://github.com/openscad/openscad/releases/tag/openscad-2021.01)
- [Official language cheat sheet](https://openscad.org/cheatsheet/): cube, cylinder,
  difference, translate, import and `$fn`.
- [Official documentation index](https://openscad.org/documentation.html), including
  the upstream-linked command-line and import/export manuals.

Versioned input contracts, physical unit conventions and the restricted part
catalogue are Schemaxis policies; OpenSCAD's general language supports much more.
