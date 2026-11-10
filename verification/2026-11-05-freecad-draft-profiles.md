# Editable Draft polygon qualification

FreeCAD baseline remains stable 1.1.4 (native release 4fd3bf3). The owner subset
is an editable straight-edged Draft Wire with finite Points/Placement intent,
Part extrusion and booleans. The application-wide inventory remains incomplete;
broader Draft operations, curved profiles, PartDesign seeding and sourced-history
copying are missing. Owner qualification now comprises the explicitly labelled
phases below. Parent review and exact integrated-source/Help/package acceptance
remain pending.

The native constructor is the installed `draftobjects.wire.Wire` with a compiled
`Part::AttachExtensionPython`. Every option, proxy state and extension binds a
fresh typed reconstruction. Geometry-only saved BREP inspection independently
binds vertices, edge pairs, winding, plane, frame, area and perimeter. Submitted
FCStd objects are never restored by the public verifier.

Exploratory public controls and 295 FreeCAD host tests passed at the foundation
checkpoint. Lifecycle r1 exposed missing minimal GUI visibility persistence;
r2 exposed two additional related StringIDs after unchanged native recompute/save.
R3 passed the complete L lifecycle but exposed exact tilted-frame BREP axis/sign
serialization changes. All failures are retained. Shared map/SID readers and
geometry/export tolerances were unchanged.

Runtime 314c27b lifecycle r4 passed three fresh projects: drilled concave L,
clockwise L and translated/clocked YZ U extrusion. Independent disjoint-rectangle
or outer-rectangle-minus-slot oracles checked persisted/recomputed/STEP volume,
centre, bounds, area, planar sections and material points. L and U each passed
three consecutive actual native unchanged saves and public verification, with
restored initial-state verification between saves. All non-XML archive members
were byte-identical between saves one, two and three. Each case also passed two
actual Points/Placement edits and independent fresh reopening/STEP checks.

The repair reproduces only one first-reopen/recompute/save reference, from its
own freshly generated trusted graph. Each comparison binds an entire reference
archive: no fields, maps, strings or geometry are combined across references.
An independent peer's 12 host controls on actual r4 archives passed eight
initial/repeated-save positives and four mixed-map refusals. Both individual
half-transitions in the L Cut map were refused against both complete references.
This review was read-only and host-only; it did not confer final acceptance.

The final qualifier additionally requires saved semantic/proxy/role/extension/
payload/string/map attacks with refreshed transport hashes, a restored positive,
pre-open unsupported-history refusal, actual deadline/cancel controls, private
GUI first-open visibility and a dimensioned drawing workflow with reuse, damage,
changed-intent refusal and producer removal. Its exact final commit and digest
must be recorded after that complete proof; earlier evidence is not relabelled.

## Retained phase qualification and current regression repair

Runtime `171838d`, source digest
`sha256:743dc60a84cbef1b8b955b4915bf3994cb74d3b3eb071ba75396ef22e254080e`,
passed these recorded phases in `final-r3` (qualifier commit `2a047c8`):

- Six fresh public/native projects: drilled concave L, clockwise L, clocked YZ
  U, independently placed XZ U, the 256-vertex ceiling and a ruled triangular
  frustum from two Draft profiles. Literal rectangle partitions, regular-polygon
  formulae and integrated frustum moments supply independent volume, area,
  centre, bounds, cross-sections and material-point expectations.
- Three consecutive unchanged native saves for each L and YZ U, with full public
  verification and restored-initial verification between states; two actual
  Points/Placement edits and fresh native/STEP reopening per design.
- Eighteen refreshed-artifact saved-state refusals, restored positive and
  unsupported assembly-history admission before any subprocess. Attacks include
  Points payload, Python proxy, extension/transient/property roles, expressions,
  native settings/links, source BREP, mixed reference maps, unused StringID,
  foreign GUI state and unreferenced archive payload.
- Actual first-worker and second trusted-reference-worker timeout/cancellation,
  with original structured fault codes and stopped native PIDs.
- Private GUI first-open inspection: only the selected Cut is visible, the
  installed Wire restores, and the retained image visibly shows the correct L
  bracket and bore. Private preferences, display and refusal of CAM migration
  are recorded; no desktop settings or user assets are used.

The original aggregate `final-r3` receipt remains **failed**: the workflow harness
used the obsolete damaged drawing directory after successful regeneration.
Tool-only `d7d7a81` corrects that reference. Labelled continuation `tail-r5`
checks the unchanged runtime digest, native/oracle helper hashes and all six
original archive hashes before reusing those completed phases. Its actual full
workflow passed initial drawing, reuse, damaged-SVG drawing-only rebuild,
changed-intent refusal and standalone drawing verification with its producer
temporarily removed. That aggregate then caught a real cross-family regression:
the extracted Mesh observation wrapper lacked its placement-helper import.

Runtime repair `ec0c840` restores that explicit import and adds an independent
analytic-box observation regression; all 296 FreeCAD host tests pass. Only
`mesh_verify.py` and the assessment fingerprint differ in the runtime tree from
the Draft epoch. Draft/native/Part reconstruction/GUI algorithms, source admission,
maps and numerical tolerances are unchanged. The older Draft phases retain their
original source labels; they are not relabelled as new-runtime executions.

Current `current-r6` passes at
`sha256:a9bafe8a4611c57d7e489901b5275aaa9f94660ddf4792b412cb22bea06a3b0b`:
fresh trusted reconstruction and verification of all six unchanged Draft
archives; three **fresh** Mesh constructions/reopenings with independent native
and STEP physical geometry; twelve refreshed Mesh attacks and restored positive;
actual timeout/cancel with stopped PIDs; and an unchanged final source assertion.
The source-labelled manifest retains all phase reports, failures, tool hashes and
small representative outputs without runtime ZIPs or source-tree copies.

Product checks passed 23 shared readiness/schema/template tests, 371 production
conformance checks, 1174 reviewed guidance records plus 62 reference records
(zero pending/stale), and the actual Studio starter/search/nested-point/frame
form, validation and atomic undo. Private generated reference/Help checks pass;
the shared packaged artifacts remain the integration owner's responsibility.
Independent read-only review of the finite GUI/post-worker fault delta passed
against its pinned source and scoped native phase evidence. The complete-reference
binder also passed independent unchanged-save and mixed-map controls. Integrated
source, package and whole-adaptor acceptance remain separate open gates. Whole
Draft and whole FreeCAD are incomplete.
