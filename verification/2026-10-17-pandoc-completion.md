# Pandoc structured-report completion review — 17 October 2026

The initial `schemaxis.pandoc/1` document route publishes a useful bounded report
as standalone HTML5 and editable Word DOCX. Sections carry ordered heading levels,
paragraphs, rectangular text tables and local PNG images. Authoring remains
structured data; no raw document AST, Markdown/HTML, scripts, filters, styles,
reference documents or arbitrary native arguments are accepted.

## Checklist review

| Item | Result and evidence |
| --- | --- |
| registration | Manifest-discovered document route; isolated process mode, workflow/composition and source-byte reuse; optional unsupported features have explicit reasons in readiness. `--pandoc` is discovered through manifest CLI options. |
| schema | Closed typed section/content alternatives, required title/text/cell/image fields and level/width defaults. Host conformance checks literal/authored schema, immutable deterministic planning, unknown root fields and exact semantic invalid example. Seven scoped host tests pass. |
| semantics | Level 1–3 outline starts at 1 and increases by at most 1; rectangular nonempty text cells; plain single-space text; report text/block/image budgets; regular local PNG captures, CRC/scanline/dimension/decompression validation and 4 MiB per-image/8 MiB combined byte limits. Located faults precede native writing. |
| native-mapping | Public `Header`, `Para`, `Table`, `Image`, `Str` and `Space` constructors through JSON AST; native API version 1.23.1.2 observed from selected 3.12.1 executable. CLI selects html5/docx writers and fresh docx reader, with sandbox, isolated empty data directory and 512 MiB native heap cap. Captured data URIs allow image embedding under sandbox. |
| execution | Shared owned subprocess timeout/cancellation and bounded retained regular descriptors. Per-stage trusted launchers bind actual consumed AST/DOCX bytes. Independent HTML, ZIP/OOXML headings/cells/internal image relationships/alt/physical geometry and fresh native DOCX-to-AST/media readback compare with authored values. Exact output/evidence membership and digests are checked. |
| discovery | Reviewed Word report, DOCX synonym, standalone HTML, ambiguous document and negative OCR scanned PDF cases pass scoped capability search. Production Studio adaptor/Add matches pass; contextual Help depends on coordinating generation below. |
| guidance |26/26 operation/field records reviewed; no pending/stale/link problems. Nested alternatives/cells/units/defaults, supported PNG limits and common mistakes are explained in owned guidance. |
| help | Local guide, API links and stable fault recovery are complete. Shared generated references and packaged operation Help are owned by the programme coordinator. Initial admission's only required gap was missing packaged `operation/pandoc/report`; production Studio Help assertions likewise failed until that generation. These are integration prerequisites, not native failures. |
| examples | Editable baseline/variant/invalid examples and Studio template. Case resources bind portable RGB 48×24 and RGBA 32×32 fixtures; variant changes table 12.0→12.5, image bytes/alt/width 60→90 mm and outline 1/1/2→1/2/3. Invalid ragged row rejects with `INVALID_REPORT_TABLE`. |
| tests | Seven focused host tests pass. Native qualification baseline/variant, timeout and cancellation pass on 3.12.1. Twelve refreshed-hash probes reject altered HTML cells, fresh AST, DOCX cells, trusted AST, hidden HTML, event attrs, meta refresh, external CSS/media and stale readback binding. Workflow unchanged input reuses; changed valid PNG bytes invalidate; two finite width visits with a shared title verify. |
| qualification | Latest-stable native acceptance passed with actual official 3.12.1 binary, separate native writer/readback processes and independent host inspectors. Receipt registration is source-bound: any subsequent shared source/Help generation makes it stale and requires the coordinator's final rerun/register. Historical acceptance remains evidence, not a current-source claim. |
| maintenance | Official release page reviewed 17 October identifies 3.12.1 released 7 October 2026. Absorbed version advanced only after host and actual bounded native acceptance. `upstream.json` records exact slice, official release source and repeat recipe. |

## Acceptance and limits

Commands actually run from the public checkout:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_pandoc*.py' -q
PYTHONPATH=src python3 tools/studio_guidance.py --app pandoc --check
PYTHONPATH=src python3 tools/qualify_pandoc.py --pandoc /absolute/isolated/pandoc --output-directory evidence/programme-20261017/pandoc-final-native --register
PYTHONPATH=src python3 -m schemaxis readiness --app pandoc --admission --check
node --test src/schemaxis/studio_ui/tests/search-acceptance.test.mjs
```

The final two commands expose the central packaged-Help dependency above and must
be repeated after coordinated generation. Earlier actual acceptance runs are
retained in ignored programme evidence; corrected development failures were not
rewritten as successes. A first trial correctly failed because sandbox omitted
local image references; the trusted embedded-media design fixed that limitation. A
later qualifier incorrectly compared the common `states` list with an integer; its
already verified two-state result prompted an assertion correction and fresh full
rerun. Source-stability checks are retained by the common native kit.

The baseline DOCX was rendered through the bundled LibreOffice/Poppler runtime and
its one-page PNG visually inspected: title, three headings, all rows, three-colour
figure and explanatory text are legible, with no overlaps or clipping. This is a
bounded fixture review, not an exact-layout contract. Artifacts retain native DOCX
editability and standalone HTML image bytes. Width rounding permits two OOXML EMU
(1/18000 mm); native JSON width is checked within 0.001 mm and aspect ratio is
checked independently from captured PNG dimensions.

No exact page layout, rich text, numerical spreadsheet semantics, general document
conversion, PDF output, accessibility conformance or colour-management claim is
made. No MPI, live native editing/save, native-inspection session, time batches or
general conversion route is supported. The source PNG need not survive after a run
because verification uses the captured copy; changing original bytes prevents
workflow reuse. Native output/source bindings are audit evidence, not signed
attestations against an adversary replacing all trusted code and receipts.

Public API sources reviewed separately from offline admission:

- [Pandoc release history](https://pandoc.org/releases.html)
- [Public AST definitions](https://github.com/jgm/pandoc-types/blob/master/src/Text/Pandoc/Definition.hs)
- [Standalone resources](https://pandoc.org/MANUAL.html#option--embed-resources)
- [Sandbox and supported IO boundary](https://pandoc.org/MANUAL.html#option--sandbox)
- [Fresh extracted media](https://pandoc.org/MANUAL.html#option--extract-media)

The public AST source and method-level manual were successfully read. A Hackage
rendered API endpoint failed; the upstream public source definitions provided the
constructor contract instead. The isolated official binary is local ignored
qualification infrastructure, not a redistributed runtime or changed user install.

## Follow-up: default stylesheet integrity

Root review reproduced a misleading-output gap: adding `body { display:none }` or
`p { opacity:0 }` to the default stylesheet passed semantic verification when ordinary
artifact/publication hashes were refreshed. Both positive reproductions were retained
in ignored programme evidence before repair.

Verification now requires exactly one stylesheet with the trusted fingerprint of the
reviewed Pandoc 3.12.1 default: 2701 UTF-8 bytes, SHA-256
`9466a348764bb1184fd84927af08d92a0b7a72627a5a27f374c1cdb7c34d5714`.
The independently generated native baseline and variant have the same fingerprint.
This permits the qualified default rather than attempting a CSS property blacklist.
A changed upstream default needs deliberate review and fresh native qualification;
receipts cannot approve a new stylesheet.

Seven amended focused host tests pass. All twelve refreshed-hash probes pass against
the retained actual native baseline, including both stylesheet hiding cases, and the
unaltered native report still verifies. The full native qualifier now contains these
additional probes. The coordinator must repeat native qualification after final
shared generation; this follow-up does not claim a fresh registered native receipt.
