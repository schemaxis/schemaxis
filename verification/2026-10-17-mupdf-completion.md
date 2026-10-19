# MuPDF completion review — 17 October 2026

MuPDF adds a bounded passive PDF review workflow: captured unencrypted local PDF
bytes, explicit ordered page selection, density and additional clockwise rotation
produce PNG previews, UTF-8 text and crop/rotation metadata. The document is
expressed through normal Schemaxis planning, execution, verification, workflow
reuse and finite composition. No authored native scripts or arbitrary commands
are exposed. Initial runtime scope is MuPDF 1.28.5, serial POSIX.

## Checklist review

| Item | Result and evidence |
| --- | --- |
| registration | Active `schemaxis.mupdf/1` document route after supervisor approval. Manifest owns executable/configuration flag, declarations, workflow/composition/resource/reuse hooks and explicit supported/unsupported feature decisions. Native imports are absent from host discovery/planning. |
| schema | Complete closed literal schema/declarations cover required source and ordered page array, nested page items, DPI and quarter-turn rotation with typed defaults. Common authored wrappers/composition use the framework. Scoped host conformance validates defaults, immutable/deterministic plans and distinct effective acceptance documents. |
| semantics | Absolute regular local PDF snapshot <=16 MiB; 1–128 whole-document pages, <=16 distinct one-based selected pages; 36–300dpi; true integer enum rotations. Native preflight checks parsed encryption, repair, actual page membership, crop geometry and whole-input/output budgets before render. Output dimensions <=4096, combined 16,777,216 pixels; text caps 1,048,576/page and 4,194,304 combined. Missing, unsupported and invalid states remain distinct faults at authored fields. |
| native-mapping | Fixed trusted MuPDF public PDFDocument/PDFPage/Pixmap/StructuredText APIs. Effective CropBox incorporates native MediaBox intersection, inherited rotation/UserUnit and nonzero origins; additional clockwise rotation follows. Metadata retains raw boxes, raw inherited integer quarter turns (including negative/>360 multiples), UserUnit and normalized bounds. Pixel bounds round outward with 0.001 tolerance; PNG pHYs is explicitly set/read back and checked against requested DPI. |
| execution | One total deadline and shared owned process-tree cancellation, POSIX AS 1 GiB / FSIZE 64 MiB / CPU 120 s caps. Source bytes plus every trusted script are hashed immediately before native exec and retained with commands/logs/submissions. Fresh native reopening emits PNM/text/metadata; independent standard-library PNG decoding compares all RGB pixels. Exact artifact/evidence/page membership is checked, allowing only exact framework publication sidecars. Source schema capture/verification uses the common store automatically. |
| discovery | Curated PDF-preview/rasterize/review terms, purpose, limits, native names and examples. Owned reviewed multiword/synonym/ambiguous/negative cases cover CLI/agent, adaptor selection, Add and Help. Capability matching/admission passed; actual shared Studio search regression is supervisor-owned. |
| guidance | All nine literal route/schema addresses and the review operation have authored reviewed conceptual guidance; 0 pending/stale. Source path ownership, one-based order, density units/default/cost, rotation convention, passive processing and text limits are explicit. Shared expression guidance remains framework-owned. |
| help | Local guide, generated reference/Help targets, fault recovery and reviewed official version-specific API/release links. Root owns reference/Help regeneration and freshness checks. |
| examples | Baseline [2,1,3]/72dpi/0°, variant [3,2,1]/144dpi/90°, semantic duplicate-page invalid example, editable Studio starter and explicit PDF-page→FFmpeg lossless video workflow. File resources are ordinary conformance bindings; no new parameter language. |
| tests | Eight focused host tests plus normal shared host/native conformance. Native acceptance checks literal fixtures, refreshed-hash forged raster/text/native bounds/list/boolean/script/source evidence, extra page, encryption, structural repair, malformed input, missing page, whole-page/pixel caps, lifecycle, same-path byte reuse invalidation, composition and actual artifact handoff. |
| qualification | Native results below are separately identified from host/admission and independent fixture checks. Source-bound shared qualification is recorded only after final common generation and supervisor review; exact receipt freshness is checked through normal readiness. No exhaustive PDF/font/action/colour/Unicode correctness claim. |
| maintenance | Latest stable 1.28.5 (2026-09-25), checked 17 October 2026 on official release history. `upstream.json` records bounded API/acceptance scope and only advances absorption after successful native qualification and review. No second runtime family, system installation or PATH change. |

## Independent fixture and native evidence

`tools/qualify_mupdf_fixtures.py` builds the retained PDF with standard-library
literal objects, streams, xref offsets and trailer, without a PDF library or
native application. Its three unequal pages have nonzero MediaBox/CropBox origins,
parent `/Rotate 90`, page overrides 0/270, page 3 `/UserUnit 2`, four literal colour
quadrants and literal text including WinAnsi café. The oracle independently
computes expected view sizes, page order and quarter-turn quadrant permutations;
it checks exact dimensions, text and 100 known interior RGB samples per page.
Expectations are authored literals rather than copied native observations.

Baseline first page (original page 2) is 216×144 at 72 dpi. Variant first page
(original page 3 with UserUnit 2) is 384×576 at 144 dpi with additional 90° rotation.
Native development and final acceptance rendered these cases and checked both the
independent oracle and full source-bound native RGB/text readback. Visual review
of the resulting unequal/rotated pages found expected geometry, quadrant placement,
legible text and no fixture layout defects.

Retained ignored evidence:

- `evidence/programme-20261017/mupdf-provenance.json`: official release/archive,
  SHA-256, native executable SHA-256/build command/runtime identity.
- `evidence/programme-20261017/mupdf-host-02/`: shared host conformance passed;
  eight `test_mupdf.py` host tests passed; guidance audit 9 reviewed/0 pending/stale.
- `evidence/programme-20261017/mupdf-native-02/acceptance.json`: verified bounded
  acceptance with both native cases, independent oracle, nine refreshed-hash
  refusals, encryption/repair/malformed/range failures, timeout/prelaunch and
  active-render-dispatch cancellation, workflow reuse/invalidation and 2 states.
- `evidence/programme-20261017/mupdf-input-extra-01/`: additional native whole-page
  and pre-render pixel-budget refusal probes.
- `evidence/programme-20261017/mupdf-handoff-01/`: actual verified 2-job workflow,
  selected page PNG to native FFmpeg 9.0.2 through explicit artifact binding. FFV1
  output holds 2 frames for 1 second with zero verified mean RGB error; 4 publications.
- Final source-bound qualification receipt and acceptance directory are appended
  below after supervisor generation/review. Earlier development receipts are
  intentionally unregistered and do not qualify changed source.

Official [release history](https://mupdf.com/releases/history) identified 1.28.5 as
latest stable. Official source archive SHA-256:
`98a5c10cda20c3992cdf76ff6b2a1149c32bd79cc796d3f703230b1185b7e934`.
The isolated `mutool` was built from that archive with bundled native dependencies,
`make -j4 build=release HAVE_X11=no HAVE_GLUT=no USE_TESSERACT=no build/release/mutool`.
Full build output was appended to the required session home log. Installed
`mutool 1.23.10` was detected and deliberately not used for qualification.

## Limits and review conclusions

General PDF verification is source-bound native consistency, not a second PDF
implementation. Offline verification does not rerun MuPDF or establish fresh
native proof. It cannot cryptographically attest evidence against an attacker who
rewrites every mutually consistent record. Native semantic correctness is
independently qualified only for the literal fixture's geometry/colour/text scope.

Passive scripts do not enable PDF JavaScript, invoke actions, follow links,
extract attachments or request network access. The integration is neither a PDF
sanitizer nor an OS sandbox. Encrypted PDFs (even empty-password encryption),
malformed PDFs and PDFs requiring native structural repair are rejected; render
resource exhaustion remains a possible native failure within bounded input size.

Text uses native content order/font mappings; no OCR, universal Unicode, layout,
reading-order or accessibility guarantee. PNG is opaque 8-bit DeviceRGB View
appearance with annotations/widgets, losing vectors/editability/transparency/links
and source colour space. No PDF/A or print-fidelity certification. MPI,
interactive native inspection, time batches, live editing, edited native PDF save
and general conversion are explicitly unsupported. Cross-adaptor handoff is
qualified for a single page PNG of compatible size to FFV1; it does not normalize
unequal multipage rasters automatically.

Supervisor review found a real truncated-native-page-list gap in the initial zip
comparison. The implementation now requires exact full list membership and closed
field/type/finite-box metadata before comparisons; refreshed-hash truncation and
boolean-page probes explicitly fail. Framework metadata sidecars are allowed by
exact expected publication names only. PNG chunks must have correct CRCs/order,
contiguous image data, one valid density tag and bounded inflation.

## Final integration result

After supervisor review and common reference/Help generation,
`tools/qualify_mupdf.py --mupdf <official-1.28.5-mutool> --ffmpeg <native-9.0.2-ffmpeg>
--output-directory evidence/programme-20261017/mupdf-native-final --register`
completed successfully. Its `acceptance.json` reports `verified: true`, including
both independent cases, all nine strengthened tamper probes, native input/page/pixel
refusals, lifecycle, workflow/composition and the actual page-to-video handoff.
The registered shared receipt records runtime `mutool version 1.28.5`, timestamp
`2026-10-17T23:37:45.427254+00:00`, and source digest
`sha256:05bcd8d609e4c17cf61f42880d931297f7c1ccb878a4712226ac916c855336c3`.
The current source digest matched this receipt at final review. Later common-source
changes must mark it stale and require the normal refresh; the receipt does not
imply qualification of future source.

`upstream.json` now absorbs 1.28.5 after that successful host/native acceptance and
supervisor review. Final required admission passed in
`evidence/programme-20261017/mupdf-admission-final.json`; eight scoped host tests
and the nine-record guidance audit passed again. Supervisor-owned wider Studio
search and generation checks remain part of programme integration.
