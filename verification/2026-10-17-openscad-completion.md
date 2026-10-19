# OpenSCAD completion review — 17 October 2026

Scope: new `schemaxis.openscad/1` plate/spacer document route. One responsible
implementation owner; coordinating review approved the bounded design and read
both critical geometry/execution modules. Independent Claude Fable 5.1 review completed. Its six findings were reconciled
below. The follow-up implementation and regression checks passed; final source-bound
registration must be refreshed after this review change and shared generation.

## Native evidence

Official latest-release API returned `openscad-2021.01`; the official stable
AppImage reports `OpenSCAD version 2021.01`. It runs in an isolated ignored
runtime directory, without system installation or user configuration changes.
Official downloads, release page, documentation index and cheat sheet were
reviewed for cube/cylinder/difference/translate/import, `$fn` and CLI export.
The binary's own `--help` confirms explicit `--export-format binstl` support.

Three registered conformance cases construct then freshly reopen geometry in separate native
processes. An independent binary-triangle determinant oracle measured:

| Case | Literal bounds (mm) | Measured volume (mm³) | Relative analytic error |
| --- | --- | --- | --- |
| Two-hole plate | (0,0,0)–(40,30,3) | 3477.674604345566 | 1.31e-9 |
| Translated 32-segment variant | (20,-10,5)–(60,20,10) | 5797.1060670247925 | 3.32e-10 |
| Annular spacer | (-10,-10,0)–(10,10,10) | 2634.7006408364905 | 3.47e-8 |

Additional native cases passed: plain 2×3×4 mm plate (24 mm³); 0.5 mm cube
translated to (100,-100,100), volume 0.125 mm³; maximum 16 holes × 256 segments,
16,460 triangles, Euler -30, 29.96 seconds total; non-round 199.123/198.123 mm
outer/bore minimum-wall spacer with nonzero translation and 0.531 mm height;
and 1.5/0.5 mm diameter, 0.5 mm height, 16-segment spacer.

The maximum case includes generation, native reopening and repeated independent
verification within a 120-second complete-run deadline. An XY index accelerates
boundary tests without removing any overlapping contour checks. This single
machine observation is not a universal timing guarantee.

Eighteen adversaries fail after applicable artifact/evidence and consumed-input
hashes are refreshed: shift, wrong units, equal-volume changed outline, reflected
hole layout, inward normals, missing/duplicate/degenerate triangles, side crossing,
normal-only corruption, altered SCAD/launcher/summary, unlisted `part*` output,
missing/extra evidence, publication membership and runtime identity. Geometric
mutations change both native STL representations, so a readback/hash mismatch
alone cannot account for their rejection. A restored run verifies afterwards.
Owned slow subprocess probes confirm inflight timeout and cancellation terminate
the child and retain failed status. Those wrappers test lifecycle, not native CAD.

The maintained `tools/qualify_openscad.py` full registered recipe passed: three
kit cases, all independent/hostile/limit/lifecycle checks, verified summary-height
handoff, unchanged reuse, corrupt producer-and-consumer invalidation, changed-input
resume refusal, fresh changed-height propagation and a two-state dimension study.
The optional `--kernels-only` mode supports isolated development without registering
qualification. Retained bulk evidence is ignored; portable conclusions and
maintained scripts are the public record.

## Completion checklist

| ID | Review and current evidence |
| --- | --- |
| registration | Manifest, version, runtime family, process isolation and explicit feature decisions implemented; coordinator activated manifest and guide together; readiness admission passes. |
| schema | Two closed operation declarations, typed nested dimensions/holes, conditional matching object, defaults, finite range guards; immutable planning and exact rejection tests pass. |
| semantics | Explicit mm, inscribed polygon semantics, half-millimetre nominal clearance, dimensions/translation bounds and resource caps; no authored source/code/reflection. |
| native-mapping | Fixed trusted cube/cylinder/difference/translate source; public API reviewed, actual stable native export and fresh import/reexport passed. Binary STL readback is used, not OFF. |
| execution | Total deadline/process caps/logs/consumed-input binding, exact publication membership, independent geometry and adversarial evidence passed; no arbitrary geometry trust. |
| discovery | Curated plate/hole/sleeve/washer/CSG/ambiguous/negative phrases and host, actual CLI/agent and all three production Studio search surfaces pass. |
| guidance | All 28 operation/field/structural records explicitly authored; no missing/pending/stale addresses. Guidance link audit passes. Coordinating and independent final editorial review remain distinct from automated coverage. |
| help | App guide, generated reference and packaged operation Help present; all Add operations resolve their own Help. Real browser operation and field Help passed. |
| examples | Baseline, translated/coarse variant, spacer and exact invalid-clearance fixture present. Native primary/limit cases passed; typed Studio template planning passes. Real Chromium/Studio typed field fill, cancellation, Add replacement, validation, required placeholders and atomic undo passed. |
| tests | Eight focused host tests pass, including geometry adversaries and no-native planning. Real native kernel acceptance passed. Registered native kit, readiness admission, eight production Studio search/context tests and one real browser authoring test passed. No test skips. |
| qualification | Registered native conformance produced a successful receipt. Later owned documentation/test edits make it historical; final source-current registration belongs to the coordinator after shared generation freezes. |
| maintenance | Latest-stable GitHub release source and bounded acceptance recipe preserved. Native 2021.01 observed; no claim for nightly or other versions. |

## Scope and integration

This route supports only dimensioned polygon extrusions with convex outer outline
and separated regular-polygon through-holes. It verifies their specific boundary,
orientation/topology and geometry, not arbitrary mesh repair, material mechanics,
printing suitability or general constructive geometry. Circle approximation error
is separate from numerical verification tolerance. STL has no embedded units;
consumer mm selection is mandatory.

The actual OpenSCAD-to-PrusaSlicer example passed with OpenSCAD 2021.01 and
PrusaSlicer 2.9.6: two native jobs/seven artifacts, verified workflow, 40×30×3 mm
source, 532 triangles, 3477.674604345566 mm³ model volume and 15 toolpath layers
ending at 3 mm. Both jobs reused on an unchanged run. The coordinator corrected
the existing slicer manifest to accept geometry artifacts after reviewing its STL
source contract. The earlier attempt had correctly failed `TYPE_MISMATCH`; no
consumer restriction was bypassed. No printer control occurred.

## Reproduction

Run focused host tests with `PYTHONPATH=src python3 -m unittest discover -s
 tests/unit -p test_openscad.py -v`; guidance and readiness checks use `--app openscad`.
Run `node --test tests/studio/openscad.browser.test.mjs` and the existing production
search suite with `--test-name-pattern=openscad` after packaged Help generation.
Run the full native recipe with explicit `--openscad`, optional `--prusaslicer`
and a fresh `--output-directory`. Final qualification registration must follow
shared source generation; do not replace a stale digest with a claimed fresh run.

## Independent review reconciliation

| Finding | Decision and evidence |
| --- | --- |
| Crossing/enclosure checks may be redundant | Keep every defensive check and the existing XY index in this change. Corrected the comment: directed edges, complete walls and end-face orientation also establish the geometry; the local contour tests alone do not reject all hole triangles. A new native-fixture adversary inserts an upward triangle wholly inside a hole and confirms directed-edge rejection. Removing checks remains a separate reviewed optimisation. |
| Exact float volume equality on native reopening | Fixed. Both independently verified solids must now have exactly equal sorted oriented triangle-coordinate multisets, normalising record order and cyclic vertex starts. Their summed volumes use only 1e-12 relative/absolute arithmetic tolerance; analytic tolerance remains unchanged. An independent non-round translated box demonstrates differing ordinary-accumulation sums and now passes reorder/cyclic-start checks. Changed facet triangulation still fails closed. |
| Fixed caps could exclude maximum | Existing actual maximum 16-hole/256-segment run passed within the 2 GiB/60 CPU-second caps and 120-second overall deadline in 29.96 seconds. No caps or advertised limits changed. The retained maximum also has identical canonical native/reopened triangle sets. This is bounded observed qualification, not a timing guarantee on every machine. |
| Absolute-path evidence prevents relocation | Documented as an explicit limitation. Exported geometry is portable; retained run verification is location-bound. A copied native run at a different directory is rejected. Native HOME points to the run, so any native settings/cache remains there. No relocation support is claimed or improvised. |
| Exact native banner rejects extra messages/suffixes | Kept deliberately fail-closed and documented. Host regressions accept the qualified banner and surrounding whitespace, reject a distribution suffix, extra diagnostic line and different version. Rejection calls for investigation, not a claim that a different build is geometrically incompatible. |
| Boolean-as-number preflight concern | Framework already rejects booleans. New explicit plate width/height, hole diameter/centre, translation and spacer bore tests confirm `INVALID_ARGUMENT` before any native launch. |

The numerical regression explicitly exercises ordinary accumulation used by older
supported hosts. This verification machine runs Python 3.12.3, whose improved
built-in summation otherwise hides that last-bit ordering example. The independent
2.3×3.7×4.1 mm translated box gives 34.89100362579537 versus
34.89100362579536 mm³ under the two accumulation orders. The tolerance does not
permit coordinate or facet changes: exact oriented facet identity is checked too.

Post-review verification: 11 focused host tests passed, including real CLI/agent
search parity. Three fresh native construct/reopen cases and all 18 existing hostile
probes were rerun after the implementation change. The maintained qualification
recipe now includes representation-order acceptance, a hole-chord adversary and
relocated-evidence rejection. Final source-current registration belongs to the
coordinator after generated references and Help are refreshed.
