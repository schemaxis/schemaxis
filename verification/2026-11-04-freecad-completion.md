# FreeCAD finite-depth machining completion, 4 November 2026

Scope: `schemaxis.freecad/1` adds finite-depth Pocket length and persistent depth
bindings, completing editable blind-recess and counterbore machining intent from
an origin XY face. This does not claim whole-FreeCAD or workbench completion.
Final acceptance results are recorded below after the stable-source checks.

## Checklist review

| Item | Delivered scope and review |
| --- | --- |
| registration | Existing 1.1.x isolated batch solid route retained; one Body/first Pad/current-tip Pocket history, same-Body constrained profiles; existing Part and assembly routes remain available. |
| schema | `pocket.extent` throughAll or length; positive optional length without a default; typed affine drive.length. Literal and authored schemas generated from existing declarations; host cross-field rules require length only for finite extent. |
| semantics | Explicit `INVALID_POCKET_EXTENT` for missing depth or throughAll with depth; no conflicting literal/driver; dimensions and affine bounds validated before native assignment; each cut must remove material and leave the supported solid. No promise that a finite depth is blind in thinner stock. |
| native-mapping | Public PartDesign::Pocket Type Length/ThroughAll, Length, Reversed, SideType, Profile/BaseFeature; normal native observations and independent saved XML enforce mode and finite length. App::VarSet/ExpressionEngine retains depth intent across native edits/reopening. |
| execution | Existing isolated build/reopen, timeouts/cancellation, logs and source/publication checks retained; STEP/STL geometry checks and FCStd ownership/constraints/expressions remain mandatory. Dedicated geometric oracle does not derive expectations from producer measurements. |
| discovery | Reviewed blind pocket, counterbore and finite depth search cases; purpose/keywords and nearby Body/Pad relationships distinguish machining intent. Existing ambiguous and negative cases retained. |
| guidance | Reviewed operation and every new length/drive schema field; explicit units, defaults, required pairing, bound limits, stock/depth relationship and user mistakes; zero pending/stale records required. |
| help | Mechanical-part guide and parameter target table updated; contextual packaged Help/reference generated and checked locally. Native public documentation and release URL checked deliberately; admission remains offline. |
| examples | Standalone counterbore baseline/variant, blind pocket, invalid cross-field intent, workflow resume handoff and Studio depth starter. Independent literal analytic expectations registered in canonical conformance. |
| tests | Focused host semantics/schema/guidance/Studio/search/admission; canonical host/native conformance and dedicated native analytic/edit/tamper checks. Shared generated assessment parity is checked on actual regenerated output, then shared generated files are left for integration. |
| qualification | New source-bound batch receipt covers named canonical cases and lifecycle probes; dedicated acceptance covers the new family more deeply. Unrelated earlier live/assembly/import receipts are not relabelled as fresh acceptance. |
| maintenance | Latest stable 1.1.4 verified from primary GitHub release API, published 28 September 2026; new acceptance uses actual native 1.1.4. Existing local launcher initially reported 1.1.3; a separately checksum-verified 1.1.4 installation was used without changing the user's launchers. Assessment date/source/rationale reviewed with scores retained, prior dated baselines preserved; capability-family map records FEM/CAM/TechDraw/surfacing/general history gaps. |

## Public upstream basis

- [Latest release API](https://api.github.com/repos/FreeCAD/FreeCAD/releases/latest),
  checked 4 November 2026, selected
  [FreeCAD 1.1.4](https://github.com/FreeCAD/FreeCAD/releases/tag/1.1.4).
- [PartDesign Pocket](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/PartDesign_Pocket.md):
  finite length versus through all, direction and sketch-based material removal.
- [Public Pocket implementation](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/PartDesign/App/FeaturePocket.cpp)
  and [profile-based feature properties](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/PartDesign/App/FeatureSketchBased.cpp).

The primary SHA256 release checksum matched the downloaded x86_64 AppImage.
Observed native identity is 1.1.4, 20260928, commit
`4fd3bf320d9566a27e60069fc8387448aaa3a094`.

## Verification results

The following checks passed on the reviewed branch. Generated shared assets were
created for actual parity checks and then restored for the integrating owner to
regenerate together with the other adaptors; source-bound qualification must be
refreshed after that shared integration.

- Focused FreeCAD host tests: **135 passed**; existing main modelling tests:
  **7 passed**.
- Assessment metadata and actual generated-index parity: **20 passed**;
  `tools/generate_adaptor_assessments.py --check` passed after real regeneration.
  Scores remain 25% whole-application breadth and 75% supported-workflow abstraction.
- Studio templates **3 passed**, guidance **20 passed**, readiness **15 passed**;
  production Studio search **516 passed**, including all new machining phrases.
- New finite-depth Studio browser acceptance **1 passed**: explicit optional
  options/extent/depth controls, history-preserving insertion, reused-profile
  semantic fault and atomic undo. The new counterbore template passed the existing
  template fill/schema/plan validation suite.
- Guidance audit: **408 reviewed, 61 attributed, 0 pending, 0 stale**.
- `schemaxis reference --check` checked **166 files**;
  `generate_studio_help.py --check` verified **1477 topics**;
  route admission `readiness --app freecad --admission --check` passed.
- Canonical host conformance passed. Canonical native conformance:
  **9 cases**, plus actual timeout and pre-launch cancellation probes, passed
  against FreeCAD 1.1.4. Cases cover the six retained baseline/variant primitive,
  parameter and through-all examples and the three new finite machining cases;
  this is not an exhaustive legacy live/import/assembly requalification.
  Registered receipt source identity before shared-asset restoration:
  `sha256:59d140fde1ab34d7ec1931cedc8c444c271f32e73877eb423dc45b7bf47afc19`.
- Dedicated native acceptance uses separate build/reopen workers plus independent
  analytic oracles and direct native-edit/fresh-reopen workers. Counterbore,
  changed stock/depth/radius, blind circular recess, finite depth beyond stock,
  literal histories and rectangular blind recess are checked. The rectangular
  oracle uses literal 47200 mm³ volume, 11360 mm² area and 286400/47200 mm axial
  centre; circular cases use independently authored analytic formulae.
- Saved XML extent, length, property type, expression, direction and base-link
  forgeries are rejected after refreshing the FCStd publication hash, for driven
  and literal histories. Native ThroughAll substituted for an initially identical
  finite cut is rejected; a thicker-stock native edit distinguishes their geometry.
  That last control deliberately exceeds the example's stock bound to challenge
  the intent distinction; it is not a newly qualified authored parameter range.
- Finite depth analytic visits, stock/depth/radius bounds, unbound sketch-centre
  edits, saved/reopened expressions and independent STEP volume are checked.
  Nonintersecting material removal is rejected as `INVALID_GEOMETRY`.
- Workflow baseline and measurement handoff verify; unchanged resume reuses all
  three jobs; corrupted native history reruns CAD and its consumer while reusing
  the independent operation. Changed depth refuses resume with `RESUME_MISMATCH`
  and succeeds in a fresh workflow directory.

Bulk receipts are ignored under `evidence/cae5-freecad-*`: final canonical receipt
in `cae5-freecad-canonical-final/qualification.json`, dedicated acceptance in
`cae5-freecad-qualified2/report.json`, with independent worker reports beside it.
No source build was needed. Earlier fixture-only oracle repair used the solid's
centre of mass rather than the outer Compound container; final acceptance does
not weaken geometric tolerances. Existing assembly/live/STEP-specific receipts
retain their original source identity and scope. Broader workbench and side-mode
gaps remain explicit in the capability-family map; no new MPI, GUI-editor,
manufacturing or solver qualification is claimed.
