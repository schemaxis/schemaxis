# FreeCAD 1.1.4 checked STL preparation — owner qualification passed

This change adds explicit-unit STL-to-faceted-Part preparation, optional linked
refinement, editable Part machining and a closed saved reconstruction boundary.
It does not close the Mesh/ReverseEngineering workbench or the whole adaptor.

Focused parser, source-capture, frame, geometry-bijection and saved-record controls
have passed. Exploratory native cases cover a box, tilted cavity and boolean cut.
A frozen verifier snapshot also passed an independent peer's bounded read-only
review and 26 host controls. This is not final source-current lifecycle acceptance.

The owner qualifier is `tools/qualify_freecad_mesh.py`, with independent
three-region bracket, dimensional variant, offset cavity, native edits/fresh
reopen, saved-state alterations, exact facet ceiling and linked drawing workflow.
The fresh `completion5-mesh-full-native-r3` passed at `5fc1e0e`, source identity
`sha256:62f5e7220e08363c840448aead4d38f54bd10fe9291d91d79bb75e6c1ee3e1e7`.
It ran with private FreeCAD 1.1.4 CLI/GUI workers. Three fresh projects passed
independent native persisted/recomputed/STEP volume, COM, bounds, sections and
material-point controls. An unchanged actual native save passed. Bracket and
rotated/offset cavity each passed two actual native edits and fresh reopening
after each edit. Twelve altered saved-file controls were refused with refreshed
artifact/common metadata, and the restored positive passed. Actual timeout and
cancellation workers stopped. The exact 20,000-facet public construction and
independent neutral/native check passed in 384 seconds. The drawing workflow
passed four views and three measured dimensions, verified reuse, drawing damage
rebuilding only its consumer, changed-intent refusal and original-source removal.
The final unchanged source identity assertion passed.

All 290 FreeCAD host controls, the actual Studio form/insert/undo test, reviewed
guidance, readiness/schema/template controls and 357 host conformance cases passed.
Independent peer review covered the frozen saved-verifier code and focused host
controls, including exhaustive flag and composed-spelling distinctions. These
are subset owner proofs: parent independent integration review, common generated
Help/assessment assets and final installed-package acceptance remain open. No
whole-workbench or whole-adaptor acceptance is implied. The immutable private
programme evidence manifest is `evidence/freecad-mesh/manifest.json`; original
failed runs below are retained. No user FreeCAD settings were migrated.

The first frozen lifecycle run at `5344439` passed three fresh construction,
native/STEP material, section and placement controls, then refused an unchanged
native reopen/save. The sole payload difference was 256 imported source face
flags changing `0101000` to `0111000`. OCCT's
[flag writer/reader](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_8_1/src/TopTools/TopTools_ShapeSet.cxx)
identifies the third field as Checked; V1 reading calls the per-shape check, whose
[face implementation updates the face](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_8_1/src/BRepTools/BRepTools_ShapeSet.cxx).
The narrowly scoped repair accepts only newly set Checked bits at face flag
positions in the trusted regenerated V1 source BREP. Every other byte and flag
remains bound. It applies only after independent source facet/placement checks,
only to the authored importMesh source's Shape payload; the generic history
comparator is unchanged. Other flag, geometry, reference and scope controls are
required alongside the unchanged actual save. No metric tolerance changed.
The actual save also serializes a formerly omitted zero property status as
Touched (1); canonicalization treats these equally while retaining every other
status bit. FreeCAD 1.1.4's
[PropertyContainer writer](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/App/PropertyContainer.cpp)
omits the status attribute only for zero. The first focused actual-archive probe
exposed this second difference after the BREP comparison passed; it remains in
the evidence alongside the original lifecycle failure.

The next frozen run at `cbf167f` passed these controls, two native edits and
fresh reopen each for bracket and cavity, twelve altered saved-file refusals,
actual stopped timeout/cancellation workers, and the exact 20,000-facet public
build plus independent saved/recomputed/STEP check (392.9 seconds for that case).
The linked drawing then refused one native decimal-zero sign rewrite in a
cylindrical surface record. Its local comparator now treats complete decimal
zero tokens with the same precision equally in either sign, retaining nonzero
values and every other byte/flag. The actual retained drawing passes its entire
independent verifier after this repair; near-zero, precision and other-flag
controls remain distinct. The shared geometry comparator is unchanged.

Peer review also identified a conservative source-payload refusal when the
already permitted one-way negative-zero spelling and Checked transition occur
together. Source comparison now uses trusted regenerated line/flag positions
and complete line counts, followed by the unchanged strict whole-stream
comparator, allowing those two precise exceptions to compose. Exhaustive peer
flag probes and new composed-spelling host controls cover this distinction;
no general topology/numeric normalization was introduced. A fresh final full
run is required after the assessment fingerprint refresh and these repairs.

General mesh repair, scan registration/fitting/reconstruction, recovered analytical
surfaces and a PartDesign Body/assembly-history bridge remain missing.
