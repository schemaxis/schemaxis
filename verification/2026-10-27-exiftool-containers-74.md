# ExifTool containers (TIFF, DNG, PNG, WebP, HEIF), objective E5: verification note

Status: **E5 is implemented in an isolated source for the scope below; the focused host, native, lifecycle, public-loop, workflow and mutant checks listed here were run against a genuine ExifTool 13.55
on the frozen source (their results are retained with the evidence, not repeated in this file). The independent family review and the global union gates (all native qualifiers, the full host suite,
shared fixtures, privacy and package checks) are separate and are not claimed here.** The scope is every operation of route `schemaxis.exiftool/1` over TIFF, DNG, PNG, WebP and HEIF files: the read family
(`inspectMetadata`, `auditMetadata`, `compareMetadata`, `reconcileTime`, `locate`), `editMetadata`, `removeMetadata` (the five categories, and `minimise` for PNG and WebP), the time and location writes
(`correctTime`, `setLocation`, `geotagFromTrack`), the transfer writes (`copyMetadata`, `applySidecar`) and the host operations (`exportSidecar`, `planNames`, `organiseCopies`). No upstream registration or
qualification label is changed by this work, and nothing here certifies photograph provenance, capture time, location, authorship, privacy or pixel content (no pixel is decoded).

## What was checked

| Area | Evidence |
| --- | --- |
| Locators and profiles | `tests/unit/test_exiftool_e5_tiff.py`, `_png.py`, `_riff.py`, `_heif.py`, `_profiles.py`: hand-built literal fixtures (strips, tiles, sub-IFDs, DNG private data, chunks, CRCs, VP8X layouts, HEIF items) and the finite refusal cases; the pinned `containerprofiles.json` digest and its declared codes. |
| Generalised proof P | `tests/unit/test_exiftool_e5_proof.py`: slot changes and moves pass, protected changes, reordering, container identity and the WebP AM-16R layout fail with exact paths. |
| Native structure | `tests/unit/test_exiftool_e5_native.py`: the locators and the proof over genuine ExifTool 13.55 outputs. |
| Write path | `tests/unit/test_exiftool_e5_write.py`: edits and removals over every container, named refusals (HEIF item creation, HEIF removal, minimise and thumbnails per container, TIFF IPTC digest and carrier), the Photoshop resource tail cases of the mailbox check (a TIFF and a JPEG, each with a clean control), verify mutants with the exact path, and a `.tif` that is really a PNG. |
| Positive cases | `tests/unit/test_exiftool_e5_positive.py`, `_ops.py` (time, location, geotag, copy and sidecar application per container), `_matrix.py` (read, host and every removal category per container) and `_minimise.py` (PNG and WebP): one real native run of one declared operation over one container (or category), decoded against hand-written literals; these explicit per-cell rows are the only rows that carry `supported: true`. |
| Residual cases | `tests/unit/test_exiftool_e5_residual.py`: DNG device-identity removal (D-4), the malformed Adobe MakN native warning gate (D-2), the 64 MiB and 256 MiB item bounds including a 65 MiB TIFF edit, and the HEIF grid edit (H-5). |
| Controls | `tests/unit/test_exiftool_e5_controls.py`: plan-only then apply, a forged plan, a stale capture, a symbolic-link and a directory capture, and a paired sidecar, over a TIFF and a PNG. |
| Workflow chains | `tests/unit/test_exiftool_e5_workflow.py`: correctTime, planNames and organiseCopies over a mixed container set; exportSidecar to applySidecar; setLocation to auditMetadata; minimise to organiseCopies; reuse and invalidation, a new folder member, a partial set and an all-refused set. |
| Metadata-first mutants | `tests/unit/test_exiftool_e5_metadata_first.py` and `_ops_mutants.py` (time, location, transfer and minimise runs): every ordinary binding refreshed and `publication_metadata.verify` required to pass before the public `verify` refuses with one exact code, location and message. |
| Lifecycle | `tests/unit/test_exiftool_e5_lifecycle.py` and `_lifecycle_ops.py`: a genuine Perl write process of `editMetadata` over each container, and of `correctTime`, `setLocation`, `copyMetadata` and `minimise` over two containers each, is held, ended by the operation's own timeout and by its cancel; PID equals PGID, the process and its group are gone, no safety-net kill, no success publication, the empty `-config` argument preserved. |
| Public loop | `tools/qualify_exiftool_containers_loop.py`: discovery positives and negatives, public author, source-only planning, run, verify and small-page inspection of the whole family over container sets (including a captured GPX input), a stale-revision control, the named HEIF refusals and the portable workflow chains. |
| Completion repair | `tests/unit/test_exiftool_e5_completion.py`: the JPEG Photoshop tail for every plan that rebuilds the IPTC (`correctTime`, `copyMetadata`, `applySidecar`, each with a tailed block, a clean block and an IPTC-untouched control), the `.avif` canonical name (host and native `planNames` and `organiseCopies`, with a HEIC control and exact copy bytes), the TIFF extent-count bound judged before any array is unpacked (a literal 65,537 and a larger count, the exact bound and ordinary counts, with a small native control), the `HEIF_EMPTY_METADATA_ITEM` refusal (the last XMP property, the last Exif entry, both, a transfer's extras, with the ordinary clear that leaves metadata behind), the published budget (JPEG-only budget and plan hash byte-identical to the retained values, the additive large bound otherwise) and the public text. The metadata-first mutants of `_metadata_first.py`, `_ops_mutants.py` and the `_write.py` mutant assert the exact public location and the structured first problem (the protected fingerprint path, the written source, the stored letter) as hand-written literals. |
| Surfaces | `tests/unit/test_exiftool_e5_surface.py` and `tests/unit/test_exiftool_e5_qualifier_rows.py`: the guide's field matrix regenerated from the data, every refusal code documented, capabilities, search cases, readiness, Studio templates and the report semantics. |

## Reproduce

Host (no native process unless `SCHEMAXIS_EXIFTOOL` names an absolute ExifTool 13.55 script, which also enables the native classes):

- `PYTHONPATH=src python3 -B -m unittest discover -s tests/unit -p "test_exiftool_e5_*.py"` (every E5 module; with the runtime configured this is the native suite of the family, serial).
- the generate tools in `--check` mode (`python3 -m schemaxis.reference --check`, `tools/generate_studio_help.py --check`, `tools/generate_adaptor_assessments.py --check`, `tools/studio_guidance.py --app exiftool --check`).

Native, serial only (no MPI claim). Choose a fresh output directory for each command:

- `PYTHONPATH=src python3 tools/qualify_exiftool_containers.py --exiftool /abs/exiftool-13.55/exiftool --output-directory DIR` runs every native, mutant, lifecycle, workflow and control class and reports one explicit per-cell row for each
  operation and container (92 supported cells, the named refusals and the controls); `verified` is true only when every required cell is covered by a passed, unskipped native test.
- `PYTHONPATH=src python3 tools/qualify_exiftool_containers_loop.py --exiftool /abs/exiftool-13.55/exiftool --output-directory DIR` runs the public agent loop and the portable workflow chains.

## Limits and named native capability gaps

- HEIF metadata items that do not exist are never created: over 20 runs per kind native 13.55 gave no output in 9 or more runs (18 of 20 with fixed seeds 0 to 19) and a wrong file for every combined Exif and XMP creation, on
  hand-built fixtures. This says nothing about every HEIF file or version. HEIF removal and minimise are refused because native `all=` leaves empty-extent items. The HEIF contract rests on the public MPEG drafts.
- Native 13.55 drops an opaque Photoshop resource tail (shorter than a resource header) when it rewrites the block; such a TIFF is refused for writing and such a JPEG for every plan that would rebuild its
  IPTC (an edit, a time correction, a copy of metadata or an applied sidecar: one shared guard, refused before any native process). Before this check an E2 JPEG edit with such a tail was published as verified,
  and the completion repair found the same silent loss in `correctTime` and `copyMetadata` of a JPEG.
- Native 13.55 cannot refresh an IPTC digest in a TIFF and would write a second IPTC carrier beside a Photoshop resource block; both are refused for IPTC changes.
- A TIFF or DNG maker note that the native writer moved is accepted only when the relocation-aware comparison shows its entries equal; any other changed note fails as `MAKERNOTE_CHANGED`.
- TIFF and DNG minimise and thumbnails outside JPEG are not offered. Item bounds are 256 MiB for TIFF and DNG and 64 MiB elsewhere (`mediaset.item_limit`); the published plan budget keeps `maxItemBytes` (64 MiB) and adds
  `maxLargeItemBytes` and `largeItemSuffixes` only when the media set can hold a TIFF or DNG name (a JPEG-only plan and its hash are unchanged). The declared extent count of a TIFF is compared with its bound (65,536) before any array is unpacked.
- PNG and WebP `minimise` uses the AM-19 method: the E2 closed reset (`-EXIF:all=`, `-XMP:all=`, PNG text by keyword) followed by the exact keep-set write-back, under the closed residual proof, the native closed diff and the byte-level
  protection of gamma, colour profile and image data; the first window described it as named-key deletion (AM-17 text), which was not what the code did. The tests assert the literal argument arrays.
- A HEIF edit that would leave an existing Exif or XMP item without any metadata is refused before native (`HEIF_EMPTY_METADATA_ITEM`); the canonical name of an AVIF is `.avif`.
- Not offered: BigTIFF, maker raw formats, RF64, JPEG XL, GIF, video containers.
- Fixtures are hand-built from literal bytes with opaque payloads; no real camera file, codec, conversion or pixel claim is made. This is a bounded synthetic corpus, not exhaustive ExifTool behaviour.
