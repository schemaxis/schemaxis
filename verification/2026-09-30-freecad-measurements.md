# Named CAD measurement verification — 2026-09-30

FreeCAD's optional named measurements expose geometric quantities with units as
verified publications. Existing STEP/STL/FCStd ordering is preserved, with JSON
appended only when requested. Measurements can select intermediate solid nodes
and re-use the geometric edge selection contract. Live sessions measure their
current revision and roll back invalid measurement selections during apply.

The bounded acceptance script is `tools/qualify_freecad_measurements.py`. It checks
rounded-prism volume/area, height, uniform-density centre and selected edge length
against analytic formulas, including translation and changing height. The native
kernel represents some finishing results as compounds; their centre is calculated
from constituent solid centres with volume weights.

The final native run passed at
`evidence/freecad-measurements-20260930-05/report.json`, with a retained source
digest matching the implementation. It used FreeCAD 1.1.3, configured Gmsh and
Octave, and a dedicated persistent FreeCAD GUI process which was closed afterwards.
The public service inspected `finishedVolume` as 995.707963267949 mm³.
Two workflow states verified twenty artifacts and reused all six jobs. Altered
publication/readback and failed-producer checks all passed.

The full host suite passed **856 tests with 22 expected skips**, no failures or
errors (259.068 seconds). Its transcript is retained beside the native report as
`host-tests.log`. The existing solid conformance and lifecycle checks passed again
at `evidence/freecad-measurements-conformance-20260930-06/qualification.json`; that
scoped current-source receipt was registered. This does not refresh assembly or
other adaptors' qualification claims.

The workflow example combines two analytic states with FreeCAD STEP and named
value handoffs to Gmsh and Octave. Gmsh target sizes must equal 0.4 times the measured
CAD height; its imported CAD volume must match the measured finished volume.
Octave's independently read CSV must contain the measured volume, four times the
height, and the explicitly converted volume in cm³. Resume must reuse all six
jobs across the two states.

Negative checks alter published values while updating their publication hash,
alter native measurement readback, and request an ambiguous source edge set.
The first two must fail verification; the ambiguous producer must prevent its
consumer from succeeding. A persistent GUI test changes dimensions while keeping
native object identities, then verifies transaction rollback after an invalid
measurement selector. Public service execution and bounded measurement inspection
are also exercised.

This evidence does not claim a second independent BREP kernel, material mass,
clearance, wall thickness, manufacturing constraints, MPI or exhaustive native
coverage. The geometric quantities use explicit mm-derived units; consumers own
any conversion and interpretation.
