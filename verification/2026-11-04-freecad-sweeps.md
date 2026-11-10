# FreeCAD sweep and persistent-centroid milestone

This work extends the existing strategic mechanical foundation with typed native
additive/subtractive Pipe, high-level dimensioned bend paths, orientation guides,
world binormals and varying sections. The representative workflow is an editable
hollow elbow with two attached flanges and machined bores. It does not close the
whole FreeCAD application or general 3D surface/path families.

Development native controls on stable1.1.4 cover analytic toroidal tubes at
60/90/210/359°, normal/Frenet/binormal, both auxiliary equivalence modes, a fixed
oblique sweep, rectangular and annular sections, closed ring and varying-section
additive/subtractive frusta. Each control builds actual native histories and
publishes FCStd/STEP/STL. A translated/rotated binormal control checks actual
world/local vector conversion. The independent oracle uses volumes, centres,
point interiors/exteriors, exact bounds and geometric surface equations.

The moving-flange edit exposed a real earlier attachment defect: FlatFace projects
the support object's origin onto the plane; a static offset cannot retain a
moving face centroid. A native AttachEnginePoint/CenterOfMass probe follows bend
radius10→12 and flange dimensions, and saves/reopens/recomputes with the same
engine/mode and independently expected volume880.795798992594mm³. New plans mark
this materialisation explicitly; retained old plans remain distinguishable.

Two upstream behaviours are kept explicit. Auxiliary sweeps may export toroidal
geometry as B-spline patches: the oracle checks the implicit torus equation rather
than assuming an analytic STEP class. Generic BoundBox can be wrong for a complete
torus; optimalBoundingBox agrees with analytic extrema and independent meshing,
and the provider already uses that public API. Transformed sharp corners can
lose a leg, so they require tangent continuity. Rounded sharp circular corners
can change volume on STEP export (500.365738317 native versus466.855417570 STEP
in the20mm-leg/radius2 control); the existing strict export verifier rejects them.
No geometric tolerance or expected value was relaxed to accept that handoff.

Frozen family qualification passes21geometrycases,23refreshed-digest saved attacks,
three native workflows with two successive edits/save/fresh reopening, verified
workflow reuse/changed-intent refusal/corrupt-history rebuild, and five explicit
native negatives. The negatives cover disconnected paths, open sections, sharp
transformed corners, rounded corner STEP loss and non-removing subtraction.
Source identity: `sha256:65fb8e27e0c44cdca9976ff4c8ea21d6b79b57bc3581f748490ad3bc2329f1b2`.

The FreeCAD host suite passes179tests (including six sweep tests); assessment
checks pass20tests. Guidance has987reviewed/61reference records and no pending or
stale fields; private generation/check passes174reference artifacts. The broad
Studio run reaches94tests with one known shared workflow-choice method failing
49route-order subtests and one missing-index error after the earlier FEM route
insertion. Root already repaired that shared dependency in37856d1; it is not
claimed fixed in this owner branch. Analysis/assembly structural admission pass;
main-route admission awaits coherent shared reference/Help generation, because
the retained Help tree predates the new operations. Owner shared generated files
are restored for root integration. Full modelling canonical qualification passes all34cases plus
timeout/cancellation, against that same source identity; the successful receipt
is registered. The first canonical run caught a standaloneSketch/noBody regression
in the new attachment check; c0b61ee fixes explicit per-node identity, and both
family and full canonical runs were repeated successfully after that fix.

Two additional rectangular-section controls distinguish auxiliary correspondence
physically. A straight20mm spine and curved60°guide in a tilted plane produce
transported basis X=N/|N|, Y=(Zspine×N)/|Zspine×N| and Zsection=X×Y. With
r(t,u,v)=P(t)+uX(t)+vY(t), the independent Jacobian is
Zsection·(P′+uX′+vY′). Integrating exact rectangle area/second moments with
256→512interval convergence below1e-8 predicts arc-length matching volume
79.1421736308313mm³ and centre(0.001350935889,0.005150247265,10.009789480929)mm;
plane matching gives80mm³ and centre(0,0,10)mm. Native STEP differs by less than
2e-8mm³/8e-9mm, and independent transported-section interior/exterior samples
pass. These cases use an explicitly finer0.01mm tessellation deflection; the
ordinary export allowance is unchanged. They establish actual orientation and
correspondence effects beyond equal-looking circular parallel-guide examples.
