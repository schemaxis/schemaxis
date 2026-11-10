# FreeCAD strategic mechanical-design foundation — 4 November2026

This is a verified programme milestone, **not completion of the FreeCAD adaptor**.
The whole-application denominator and important stable gaps remain in
[the family inventory](../docs/freecad-capabilities.md). The existing `/1` part
format and legacy origin-based documents are retained.

## Delivered behaviour

- Independent Body ownership, ordered Group/Tip histories and explicit current
  base continuation, including multiple Pads and multiple Bodies.
- Named line/circle/arc sketches with typed relations; fully constrained
  rectangle/circle and capsule-slot intent; native slot span/radius drivers.
- Explicit orthonormal profile frames, arbitrary editable datum axes and checked
  native planar-face attachments with direction, extreme position and anchor
  intent. Missing/ambiguous faces fail rather than choosing the first face.
- Native additive/subtractive revolutions, Body fillets/equal-distance chamfers,
  linear/polar/mirror feature patterns and additive/subtractive lofts.
- A parameter-driven enclosure/cavity/four mounting bosses/four bores and a
  separate ventilated lid Body, with independent STEP/STL publications and native
  history retained in FCStd. Native wall/floor/height/boss edits propagate through
  attachment and expression links.

## Evidence and acceptance

Development native runs against upstream stable1.1.4 passed14 independent
analytic feature-family models, then arbitrary datum rotation and standalone
sketch cases. A separate enclosure/lid qualification passed baseline geometry,
eight refreshed-digest saved-setting/geometry/link attacks and native parameter
edit → save → fresh-process reopen → second edit. Both edited enclosure and lid
volumes, support heights, native expression relationships and attachment links
were independently checked. Capsule-slot constraint verification discriminates
native tangency settings and geometry; high-level slot geometry does not require
authored native constraint indices.

`tools/qualify_freecad_histories.py` is the repeatable current acceptance entry
point. It includes the enclosure/lid lifecycle and the analytic cases in
`tools/freecad_history_cases.py`; independent edit probes are in
`tools/qualify_freecad_histories_native.py`. The current frozen-source run and
canonical route receipts are recorded separately by integration; earlier
successful development evidence is not relabelled as qualification of a different
source revision.

The143 FreeCAD host tests at the first checkpoint passed. Changed rejection
fixtures now positively check supported extra Bodies/placed sketches while
retaining stale-base, reused-profile and cross-Body negatives. New host cases
cover immutable planning, frames, history ownership, named relations, independent
geometry residuals, closed inputs and storage-roundoff discrimination. The later
integration note supplies final host/Studio/generator/admission results after
combining independent programme owners.

## Checklist review

| Item | Review |
| --- | --- |
| Registration/schema | Existing route/version; finite typed constructor/property policies; schema and planning share declarations; no authored native reflection/Python. |
| Semantics | Ownership/current-tip/unused-profile constraints, orthonormal frames, exact semantic selection, positive material changes and one-solid outcomes. |
| Native mapping | FreeCAD1.1.4 public Sketcher/PartDesign API; native properties/links/types/constraints/geometry read back; saved XML independently checked. |
| Execution | Existing isolated build/reopen processes, total deadline, retained logs/digests and export checks; no native imports during host discovery/planning. |
| Discovery/guidance | Curated named-geometry, slot, datum, turned-feature and pattern terms; reviewed concept/field guidance; previous guidance addresses remapped by operation identity. |
| Help/examples | General history guide, editable enclosure/lid and housing examples, Studio wall-thickness starter; integration regenerates shared references and Help. |
| Tests/qualification | Independent analytic volumes, two native editing processes, saved semantic attacks; canonical receipts and source identities remain separate evidence. |
| Maintenance | Stable upstream basis retained; current source assessment refreshed; important absent stable families remain explicit programme gaps. |

## Limits and next families

General conic/spline/external sketches, richer datums/attachments, Hole, pipes,
shell/thickness, draft/helix, further extents, multitransforms, broad surfaces/BRep
and imported FCStd editing remain open. Pattern axes/planes use Body origins;
only revolutions/grooves currently accept arbitrary datum axes. Native topological
face links can fail after edits changing topology. One selected final tip exports
one solid even when FCStd retains multiple Bodies. Native drivers are lengths;
general angular/expression/coordinate driving and reverse synchronisation remain
open. Live Body sessions and scalar PartDesign design studies remain unsupported.

Assembly mechanisms, native CAM/FEM and other stable bundled workbenches are
important further work. Drawings and sourced-assembly admission have independent
owners and cannot be claimed complete by association with this modelling review.
No exhaustive API, manufacturing quality, structural strength or solver-physics
claim follows from geometric qualification.

Primary sources reviewed: [FreeCAD stable1.1.4 announcement](
https://freecad.github.io/Website/news/freecad-1-1-4-released/),
[Sketcher scripting](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Sketcher_scripting.md),
[Pad](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/PartDesign_Pad.md)
and [versioned constraint types](https://raw.githubusercontent.com/FreeCAD/FreeCAD/1.1.4/src/Mod/Sketcher/App/Constraint.h).
