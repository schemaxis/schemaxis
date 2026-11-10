# FreeCAD mould-release Draft — verified subset

The fixed baseline is FreeCAD 1.1.4. Typed `bodyDraft` continues a Body's current
solid tip, selects exact measured planar/cylindrical faces, references an earlier
same-Body neutral profile plane and optionally a native pull datum. Native and
saved readback bind its slope, reversal, suppression, references and fixed kernel
policy. Broader surface selectors, neutral-face references and feature extents
remain missing; this is separate from Draft workbench 2D drafting.

The repaired full qualifier passed at commit `0c1aa8c`, FreeCAD 1.1.4, with
source digest `sha256:fb4f529dcd4fe407268cf6ef17f408be6a685a32c766c70294b20b44822b8037`.
Its qualifier SHA256 is `349e3c3fdcca15360bd6a4eae68d5cd1d31e21e1774e4ce8e950b36974f6e5e7`;
independent geometry expectations are in `tools/freecad_draft_cases.py`, whose
SHA256 is `f1b1dc4665c2df8982262e35d1878a283a4e4e66ddc24b6f444fa4113fd4e84a`.
The bounded job `completion3-draft-full-native-r8` records the runtime archive,
inputs, native process identities and unchanged final source digest.

Three projects pass independent native/STEP volume, centre, bounds, section and
point checks: a driven moulded enclosure with bosses/bores/lid, a translated
cylindrical cup and a tilted-frame solid. Ten saved semantic mutations with
refreshed artifact hashes are refused, followed by the unchanged positive
control. Two actual angle/wall/height/boss/bore edits, each saved and reopened in
a fresh process, retain analytic geometry and lid parameter propagation.

The actual workflow embeds the drafted source histories with shared instances.
Copied histories pass height edits at 22 and 24 mm and fresh process reopening;
native PIDs are respectively 945293/945337 and 945346/945391. Independent checks
cover both shared housing geometries, centres and solved lid mounts. A standalone
copy reopens while producer inputs are unavailable. This establishes native
portability; Schemaxis provenance verification still needs pinned producer
artifacts. Foreign saved properties and Python restoration content are refused
before any native process starts, with unchanged source planning as the control.
Full workflow reuse, rebuilding only the damaged assembly, and refusing changed
authored intent also pass.

Independent review reopened the earlier positive result: changing the saved
Draft face reference while swapping corresponding entries in both editable
inventories could pass when artifact and publication metadata were refreshed.
Verification now measures the saved base BREP in a fresh installed, configured
worker. The same public-verifier attack is refused, and the restored control
passes. Enclosure, translated cup and tilted-frame controls establish that saved
BREP geometry already carries its placement; no extra transform is applied.
This establishes selection against stored base geometry, not canonical
authenticity of the entire cached history. Whole-history regeneration remains a
separate review question.

The native reopening stage records observations; mandatory host verification
runs after that worker exits and before successful publication. An initial repair
attempt tried to repackage an imported runtime ZIP inside FreeCAD and failed;
that epoch is retained. The final host boundary avoids nested native launches.
Actual saved-BREP reader timeout/cancellation controls pass at the same source
digest: native PIDs 951529/951575 stop and retain their original structured fault
codes. Verification without a configured runtime reports
`VERIFICATION_RUNTIME_REQUIRED`.

Native face counts are bounded before allocating inventories; generated receipts
have explicit byte limits and a strict finite JSON object decoder. Independent
review repeats the original coforged-selector attack and closes that defect.
These resource guards preserve the geometry and selection tolerances.

Earlier failures remain recorded: the first independent STEP inspector treated
a one-solid Compound as a Solid; the Draft source policy initially missed three
native transient fields; two subsequent attack harness assertions rejected the
correct earlier guards. Repairs preserve exact source admission and geometry
tolerances. No general source-copy binder was changed for this feature.

The full FreeCAD host suite passes 262 tests. Actual Studio authoring covers
the starter, planar/cylindrical choice fields, references and atomic undo;
discovery, guidance and host route conformance pass. Exact integrated Help,
packaging and independent master review remain required. Broader extents,
neutral-face/surface selectors and application-wide completion remain open.
