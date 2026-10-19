# Aseprite captured PNG cel import review — 17 October 2026

`importImage` places captured PNG artwork in an existing named layer and one-based
frame, giving that cel an exact integer placement and dimension assertion. It
replaces the image rectangle, including transparent erasure; pixels outside the
rectangle survive. Later drawing, normal opaque layer compositing, timed frames,
palettes and tags remain supported. No arbitrary Lua or authored native path
reaches the worker: `Image{fromFile=...}` opens generated capture names only.

| Completion item | Result and retained evidence |
| --- | --- |
| registration | Existing route/runtime family retained; `image` input artifacts declared with the bounded PNG policy. Optional-feature decisions remain explicit. |
| schema | Closed typed source/layer/frame/x/y/width/height options, frame default 1. Declaration appended after existing operations, preserving field addresses. Deterministic pure planning, schema/default/invalid tests and common host conformance pass. |
| semantics | Complete dimension assertions and in-canvas placement; RGBA8 binary alpha; 2 MiB per PNG, 16 MiB total captures and 1048576 imported samples. Unsupported modes, profiles, metadata, interlace, animation, partial alpha, clipping and unsafe files rejected before native launch. Hidden RGB under zero alpha is normalised for comparisons; captured bytes stay exact. |
| native-mapping | Official Image constructor/getPixel/drawPixel/drawImage, Sprite:newCel and Cel.image/position reviewed. Native fresh reopening preserves exact layer/frame cel samples, canvas/layer order, palette, tags and durations. |
| execution | Non-following/nonblocking regular-file reads, generated capture paths and SHA-256 manifest. Original paths never reach native file APIs. Independent Python PNG decoder checks CRC, inflate bounds, all five row filters and full pixel samples; separate integer replacement/compositing oracle checks fresh native cel, preview and sheet readback. Host also decodes both published PNGs directly, detecting misleading receipt/digest updates. |
| discovery | Curated app purpose and per-operation native/domain terms; six reviewed synonym/multiword/ambiguous/negative cases cover capability selection, Studio Add and Help. Production Studio search passed after shared Help corrected substring matching (`place` previously matched `replaces`); no exclusions were weakened. |
| guidance | Import operation and every nested field reviewed, including units, default, dimension/alpha semantics, source ownership, path rules and actionable recovery. Guidance audit: 111 reviewed, 25 attributed references, zero pending/stale/missing sources. |
| help | Local import guide, exact faults, public API links and fixture links supplied; generated reference/packaged Help integrated by supervisor. |
| examples | Import baseline, changed image/placement/duration variant, invalid clipping fixture and real PNG producer/consumer workflow. Studio import snippet instantiates and plans successfully; source chooser declares .png. Synthetic 3×2 PNGs include transparent hidden RGB, differing opaque colours and alpha patterns. |
| tests | Focused suite: 29 tests pass with the actual executable, no skips. Includes unsafe paths/devices/pipes/symlinks, PNG filters/loss rejection, schema/purity/defaults, capture independence, overlap, literal compositing, changed source reuse, native legacy/variant and owned-process cancellation/timeout/failure retention. Common host conformance and structural admission pass. |
| qualification | Common native conformance passes four cases: procedural baseline/colour variant and captured import baseline/source-placement-duration variant. Native timeout and prelaunch cancellation retain structured faults. Custom native qualifier passes import, variant, same-cel overlap, both procedural examples, authored/effective input resolution, source-aware workflow reuse, verified PNG handoff and the pre-capture procedural evidence layout. Native qualification receipts are source-bound; a later source change makes them stale. |
| maintenance | Latest official stable release resolved as v1.3.18.6, published 22 September 2026. Successfully built and tested the unmodified official stable source archive; exact runtime string is `1.3.18.6-dev` because archive CMake falls back to that suffix without Git metadata. This is a stable-archive batch build, not a prebuilt vendor binary or a development-branch snapshot. |

Historical procedural evidence without a capture manifest remains readable only
when its worker matches the exact previously packaged source SHA-256. Its result,
publication, fresh-readback and independent pixel checks remain mandatory.
Current procedural workers require the new manifest; imports cannot downgrade;
a present malformed manifest is always rejected. Three host compatibility probes
exercise old/current/import evidence and altered trusted source. A new native run
using the pinned previous worker also produces and verifies the actual old
procedural evidence layout. This is a compatibility check, separate from native
qualification of the import feature.

The first common native run found an incorrect independent variant expectation:
moving the image left leaves earlier white pixels in column 3 outside the new
rectangle. The literal expected grids were corrected from that geometry; the
verifier stayed exact. The fresh rerun passes both cel and composite literals.

Eleven custom integrity probes reject modified captured PNG, input manifest,
native sprite, preview, sheet, sheet metadata and trusted worker; false cel,
duration and preview receipts with coherently updated receipt hashes; and an
altered publication with both asserted digests updated. Common conformance adds
missing/tampered publication, authored/plan/receipt and lifecycle probes for all
four cases. Offline verification uses retained captures after original sources
are removed; workflow reuse deliberately fingerprints the current originals.

Bulk results are ignored under `evidence/programme-20261017/`:

- `aseprite-focused-native-tests.log`: earlier 26 passing tests; `aseprite-focused-native-tests-final.log`: 29 after compatibility checks.
- `aseprite-import-native-compat/qualification.json`: seven native case families, including pinned pre-capture procedural worker,
  source-aware reuse, PNG artifact handoff and eleven integrity probes.
- `aseprite-legacy-edit-native/qualification.json`: existing procedural icons and
  animation plus editable-copy mutation and another native reopen.
- `aseprite-conform-native-final/qualification.json`: four common native cases,
  exact literals, integrity and lifecycle checks; subsequent integration may
  retain a newer source-bound conformance run.
- `aseprite-host-final/`, `aseprite-readiness.json`: host/admission results.
- `runtimes/aseprite/provenance.json`: official source URL/archive digest, isolated
  extracted dependency package digests, build options and observed version.

Build/runtime files stay inside ignored evidence. Source compilation used four
jobs and explicit timeouts, with complete logs also tee'd to the user-required
session build log. No system package installation, source patches, paid download,
PATH edit or runtime redistribution was used.

Qualification is CPU batch only: no GUI appearance, GPU or exhaustive Aseprite
coverage. No partial alpha, colour transforms/profiles, indexed/gray/16-bit input,
scaling, clipping, general formats or blend-mode expansion. Named layer plus frame
uniquely selects a cel; Aseprite cels have no separate authored name here. MPI,
time batches, native inspection/live editing and general conversion remain
explicitly unsupported. Shared authored composition and workflow execution are
supported and separately exercised. Offline retained-evidence verification is
not a new native reopen or cryptographic attestation against coordinated forgery.

Primary references reviewed: [Image](https://www.aseprite.org/api/image),
[Sprite](https://www.aseprite.org/api/sprite),
[Cel](https://www.aseprite.org/api/cel),
[stable release](https://github.com/aseprite/aseprite/releases/tag/v1.3.18.6).
