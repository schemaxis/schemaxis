# ExifTool metadata workbench, objective E1 (read, audit and compare): completion note

Status: **E1 implemented; individual native checks passed; integrated acceptance is pending.** This note covers
`inspectMetadata`, `auditMetadata` and `compareMetadata` on route `schemaxis.exiftool/1`. The earlier `inventoryPhotos`
operation is unchanged (its plan hashes and trusted launchers are byte-identical to the 71 foundation; see the parity test)
and is not re-reviewed here. Nothing in this note is an independent acceptance, a native-qualified label or a claim about the
whole application.

## What E1 delivers

| Area | Delivered |
| --- | --- |
| Catalogue | `fields.json`: 40 typed fields in 7 profiles, each with sources (EXIF IFD tag, XMP property, IPTC dataset or JPEG frame), codec, native anchor key, privacy class and a reviewed description. A validator rejects unknown codecs, duplicate sources, bad locations and missing descriptions. |
| Readers | Shared standard-library TIFF/EXIF IFD walker (IFD0, ExifIFD, GPS, IFD1), hardened bounded XMP reader (DOCTYPE and entity declarations refused before parsing), IPTC-IIM reader with explicit 1:90 charset handling, JPEG locator (any coding process; notes for extended XMP, ICC and trailers) and XMP sidecar locator. A payload failure makes only the affected fields unreadable. |
| Records | Per-field states `present`, `absent`, `unreadable`, `unsupported`, `ambiguous` (unassessed means not requested); per-source states and codes; literal concordance (`single-source`, `consistent`, `partially-assessed`, `conflicting`, `ambiguous-source`, `derived`); derived `capturedUtc` and `gpsUtc`; embedded XMP and an adjacent sidecar are separate sources. |
| Media sets | Explicit list or bounded folder; deterministic scan; no symbolic link followed; depth, count and size limits; every scanned entry in `manifest.json` with a reason; per-item faults; `complete`/`partial` status; an all-failed set fails the run; folder re-scan after capture (`MEDIA_FOLDER_CHANGED`). |
| Native | Fixed `-json -a -G0:1:4 -n -e -u -q --System:all` listing (no authored value reaches the command), instance-preserving key parsing, strict bounded JSON, two-process repeat, anchors for every independent source (mismatch refuses the item), optional `native-observations.json` at the native-observed proof level. |
| Verification | Offline re-derivation of every independent value and every publication from the retained bytes; fresh replay of the native listing with the configured trusted runtime; `NATIVE_REPLAY_UNAVAILABLE` (never `verified: true`) for a native listing without that runtime. |
| Reports | `metadata.json`, `manifest.json`, typed `profile-<name>.csv`, `audit.json`/`findings.csv`, `comparison.json`/`differences.csv`, `native-observations.json`. |
| Discovery, Help, Studio | Capability metadata for four operations, reviewed positive and negative search cases (as first recorded for the four read operations: geotag, rename, strip, edit and write verbs were negative; since the E2 write family offers `editMetadata` and `removeMetadata`, edit, write, strip and minimise queries find them, and only geotag, rename and time-shift verbs remain negative), 119 reviewed guidance records, four Studio templates, generated reference and packaged Help. |

## Primary sources read for this objective

- CIPA DC-008-2012 (Exif 2.3), fetched as a public PDF: GPS IFD conventions (references, unsigned degrees/minutes/seconds, altitude reference,
  UTC stamps, direction and its reference, map datum). The `OffsetTime*` tags are not in that edition; they are taken from the ExifTool 13.55 tag table.
- Metadata Working Group "Guidelines for Handling Image Metadata" (public archive copy): property correspondences, IPTC coded character set rules.
  **No MWG compliance is claimed and no MWG precedence rule is implemented**; E1 reports every source and literal concordance.
- ExifTool 13.55 `html/` documentation in the private runtime tree (read as text only; no upstream code copied).

## Checks and how to reproduce them

Everything below runs from a repository checkout with Python 3.10 or later; a native ExifTool 13.55 and a Calc runtime are configured with `schemaxis configure`
or passed explicitly. The measured results are dated and scoped; none of them is a qualification label, an independent acceptance or a claim about the whole application.

Host checks (no native process unless `SCHEMAXIS_EXIFTOOL` names an absolute ExifTool 13.55 path, which also enables the real run and verify tests):

- `PYTHONPATH=src python3 -B -m unittest tests.unit.test_exiftool_workbench tests.unit.test_exiftool` plus the adaptor-generic suites (architecture, assessments, readiness,
  capability declarations, progressive capabilities, references, Studio guidance, native Help, CLI discovery, console references). They pin the catalogue, every presence state with
  hand-written literal values, hostile XMP/IPTC/TIFF/JPEG payloads, a 400-case deterministic mutation run, media-set manifests, planning faults, audit and comparison outcomes, native-key
  parsing, anchors against hand-written native JSON and the legacy plan and launcher parity. The test file's header states that native JSON used by the host tests is written by hand from the
  fixture table.
- The `generate_*` tools in `--check` mode for the reference, packaged Help, assessment index and guidance, `python3 tools/studio_guidance.py --app exiftool --check`,
  `schemaxis readiness --app exiftool --admission --check` and the Studio search acceptance regression.
- A syntax check of every changed Python file against the Python 3.10 grammar (`ast.parse(..., feature_version=(3, 10))`), because the host runtime must stay 3.10 compatible.

Native checks (serial only; no MPI claim; each needs the configured runtime). Replace `EXIFTOOL` and `SOFFICE` with absolute executable paths and choose a fresh, nonexistent output directory for each command:

- `python3 tools/qualify_exiftool_workbench.py --exiftool EXIFTOOL --calc SOFFICE --output-directory DIR` is the whole-workbench qualifier. It runs real ExifTool 13.55 for every operation, a
  metadata-first exact semantic mutation set (each mutant refreshes the bindings and the publication metadata and must still be refused by `verify` with the exact code and location),
  a separate set of integrity probes, a forged unanchored native tag caught only by a fresh trusted replay, live timeout and cancel on the real ExifTool process (the report records the
  process and group and fails if a safety-net kill was needed), the Calc handoff, and the `native-controls` case: a real native disagreement (`padded-make.jpg`), GPS references,
  near-zero rationals, mixed readable and malformed sources and repeated GPS reference tags. It uses the shared fixed staging path and must be serialized with the legacy qualifier by a caller-held lock; the script does not acquire that lock itself.
- `python3 tools/qualify_exiftool.py --exiftool EXIFTOOL --calc SOFFICE --conform --output-directory LEGACY_DIR` runs all seven shared kit conformance cases, including the legacy inventory and new read-family cases. It needs the same caller-held lock as the workbench qualifier.
- `python3 tools/qualify_exiftool_agent_loop.py --exiftool EXIFTOOL --output-directory AGENT_DIR` and `python3 tools/qualify_exiftool_folder_reuse.py --exiftool EXIFTOOL --calc SOFFICE --output-directory REUSE_DIR` use unique private fixture folders and
  need no lock: the first checks that an agent can discover, plan, run and verify from the public interface and that a changed folder is refused; the second checks folder-set reuse, invalidation
  and the Calc handoff of each scenario.

What the Calc handoff checks: the producer CSV bytes are the consumer's captured bytes, and both native workbooks are read back by an independent oracle (`tools/qualify_calc_typed.py` parsing, literal rows
written in the qualifier). Every Data cell that holds a value is compared by type and value, every Summary label, metric value and formula is compared, the Summary cell set is exact and the eight Summary header cells
(`Column`, `COUNT`, `SUM`, `AVERAGE`, `MIN`, `MAX`, `STDEV`, `MISSING`) are compared by text. The reported 212 cells of the exposure handoff are the two formats added together: 106 per format
(50 Data cells that hold a value plus 56 Summary cells, of which 8 are the header). The folder-reuse counts 212, 226 and 190 are also two-format totals (106, 113 and 95 per format). Before the header text was asserted
the same counts were reported but those 16 header cells were counted by position only; two artifact-header probes (one changed header cell per format, labelled separately from the production mutants) now show that the oracle refuses a changed header text.

Measured results, 2026-10-26 (ExifTool 13.55 with Perl 5.40.1, Python 3.14.4, Calc 26.8; the bytes of the first review-driven pass): the whole-workbench qualifier, the shared kit conformance (all seven cases),
the agent loop and the folder-reuse check exited 0 with `verified: true`; the focused host run was 319 tests with one skipped (the optional YAML extra) and all generation, guidance, admission, search and grammar
checks passed. The bytes of the later passes below were re-run in full by the same commands; their results are reported with that review and are not restated here, so that this note does not change after the final run.

## Review-driven repairs

An early independent review of the first E1 snapshot found five issues, each repaired and then re-reviewed: a partial set (one item refused after the native cross-check) failed verification because the replay listed only the surviving
items while the retained listing covers every admitted capture (the replay now takes the names fixed before anchoring); numeric anchors used an absolute floor (they now accept exactly the 10-significant-digit serialisation of
ExifTool 13.55, the composed GPS rounding bound, and require exact zero); GPS signs were never anchored (the reference tags are now compared natively, and a missing altitude reference must stay absent); a readable source beside
an unreadable or unsupported one was reported `single-source` (now `partially-assessed`, with `unassessedSources`, and `unreadableValues` names the malformed source); and an unused, unbounded
`xmpRational` helper was removed, with ASCII-only digit patterns. A real native disagreement (`padded-make.jpg`) is part of the qualifier.

A final review then reproduced one more reachable fault with real ExifTool 13.55: a file that repeats a GPS reference tag (`GPSLatitudeRef`, `GPSLongitudeRef` or `GPSAltitudeRef`) made the whole run fail with
`NATIVE_EXECUTION_FAILED` and publish nothing, even for valid photos in the same set, because the repeated companion was anchored as if the main tag had repeated. A repeated reference is now its own source state,
`EXIF_COMPANION_REPEATED` (with `companion` and `instances`): only that field is `ambiguous`, the other fields of the photo and the other photos are published, and the native copies (ExifTool lists the last copy as the main tag and the
earlier ones as `Copy1`, `Copy2`) are anchored by count and by value and kept as ambiguous native observations. A repeated main tag keeps `EXIF_TAG_REPEATED`. The regression tests fail against the previous bytes
(a real run and verify ends in `NATIVE_EXECUTION_FAILED` with the message `'instances'`) and pass now; the qualifier's `native-controls` case runs the three repeated references with real ExifTool.

Known limits that remain documented rather than changed: a derived `capturedUtc` is published as `derived` even when its local-time input is only `partially-assessed`; `compare` treats a zero coordinate with opposite references as the
same canonical value; and any non-Schemaxis exception inside a phase of a native run is reported as `NATIVE_EXECUTION_FAILED` with its message (this follows the older adaptor), so it is a reachable-bug label rather than proof of a native fault.

## Completion checklist items

| ID | Result |
| --- | --- |
| registration | Same route and manifest; three operations added through the existing declaration and `oneOf` schema; no framework edit. |
| schema | Per-operation authored and expanded schema regenerated; invalid examples fail with exact codes (host test). |
| semantics | Planning refuses unknown keys, bad IDs, duplicate IDs and sources, relative paths, bad limits, inconsistent audit options and an unknown baseline before any native process. |
| native-mapping | Fixed command, fixed environment, anchors against 13.55 output; mapped fields listed in the catalogue. Bounded native acceptance is the qualifier named above; no kit receipt is claimed. |
| execution | Run, retained evidence, trusted launchers, runtime identity and fresh-replay verification are implemented and exercised by probes. Live timeout and cancel on the new native process are part of the qualifier. |
| discovery | Reviewed positive and negative cases; capability matching check passes. |
| guidance | Every schema address has a reviewed record; each catalogue field has a reviewed description (meaning, units, absence, privacy class, proof level). |
| help | Local guide (`docs/exiftool.md`), generated reference and packaged Help regenerated. |
| examples | Folder and item baselines, an exposure workflow to Calc, four Studio templates and four invalid cases. Native cases with hand-written expected values are in the qualifier; the shared kit `cases` in `readiness.json` also carry five literal items, audit and compare cases (the kit binds single files, so folder sets are covered by the qualifier, the agent loop and the folder-reuse check; the legacy cases still use the fixed staging path, so `adaptor conform --native` needs the native lock). |
| tests | See above. Assessment index regenerated; its parity test is part of the final gate. |
| qualification | **Not registered or labelled qualified.** A native qualifier exists (see the checks above); the parent gate decides any label. |
| maintenance | `upstream.json` retains the production 13.55 policy and records the scope absorbed through reviewed integration; assessment text rescoped (read family: coverage 10 %, abstraction 60 %; after the write family and minimise: coverage 10 % (unchanged on the five-point rubric), abstraction 65 %, both subjective). |

## Remaining work (E1) and later families

E1 remaining: independent review of the final bytes, a fresh run of the commands above over the exactly frozen bytes in the integrated union (the shared-staging qualifiers and `adaptor conform --native` need the native-qualification lock),
and parent integration. Found by the public agent loop: a workbench-shaped document with an unknown operation was reported as unsupported keys (now `UNKNOWN_OPERATION` at `$.operation`), and natural phrases such as "compare photos" found nothing
(three curated phrases and reviewed search cases added; discovery still matches every query token, so a long sentence can find nothing). No framework generic-directory-fingerprint hook is missing: `reusableInputs` already carries a folder manifest
digest. The assessment fingerprint must be regenerated after any further adaptor-package edit.

Planned families: E2 write and remove on captured copies (editMetadata and removeMetadata, including a rendering-preserving minimise, offered for JPEG; see the section below); E3 time correction and location (not started); E4 sidecar export/copy and naming; E5 TIFF/DNG, PNG, WebP and HEIC containers.
Outside the plan: video and RAW maker notes, C2PA validation, reverse geocoding, configuration and custom tags.

## Write family (editMetadata, removeMetadata): host and native checks

Added on 2026-10-26. These are checks a reader can repeat; they are not an acceptance, a count or a qualification label.

- Host tests (no native process): `PYTHONPATH=src python3 -m unittest tests.unit.test_exiftool_write tests.unit.test_exiftool_workbench`.
  The native class of `tests.unit.test_exiftool_write` runs only when `SCHEMAXIS_EXIFTOOL` names an absolute ExifTool 13.55 script.
- Native qualification of the write family, in its own fresh directories (it does not use the shared native-qualification lock, which only the
  legacy `tools/qualify_exiftool.py --conform` kit and the shared-fixture workbench qualifier need, and which the caller holds):
  `PYTHONPATH=src python3 tools/qualify_exiftool_write.py --exiftool /absolute/path/to/exiftool-13.55/exiftool --output-directory /fresh/empty/directory`.
  It runs the native flows of the test class: edits with exact Unicode, creator lists, language alternatives and legacy IPTC; progressive,
  restart and multi-scan JPEGs; stable partial-set artifact slots; removal with absence proofs and the residual inventory; exact semantic and
  integrity mutants against `verify`; and the public workflow chain from a produced image into `inspectMetadata`.
- Compatibility: the plan hashes of the six retained read and inventory examples were computed with the accepted read-family source before the
  write family existed and are hard-coded in the test module; they are unchanged. `fields.json` is byte-pinned; the MWG creator reading is the separate
  internal `fields-2.json`, selected only by `creatorInterpretation: "mwg"`.
- Generation and discovery: `python3 -m schemaxis reference --check`, `python3 tools/generate_studio_help.py --check`,
  `python3 tools/generate_adaptor_assessments.py --check`, `python3 tools/studio_guidance.py --app exiftool --check`,
  `python3 -m schemaxis readiness --app exiftool --admission --check` and `node --test src/schemaxis/studio_ui/tests/search-acceptance.test.mjs`.

Completion (same day, E2 continuation). Added: the rendering-preserving `minimise` category (closed block deletions, never a bare `-all=`: a probe against
ExifTool 13.55 showed a bare delete-all re-chunks the ICC profile and flips the Exif byte order), a precise per-item refusal when a rewritten XMP value carries
qualifiers (`XMP_QUALIFIERS_WOULD_BE_LOST`), an independent comparison of every untargeted Exif entry and the maker note (`EXIF_NONTARGET_CHANGED`,
`MAKERNOTE_CHANGED`), an IPTC coded-character-set check that covers records 1 to 6 as ExifTool 13.55 decodes them, and a repair of refusals that raised a keyword
collision instead of their stable code. Checks to repeat:

- `PYTHONPATH=src SCHEMAXIS_EXIFTOOL=/absolute/exiftool python3 -m unittest tests.unit.test_exiftool_write tests.unit.test_exiftool_write_complete`
  (the second module: host tests, a ten-item minimise run, metadata-first refreshed mutants through the public `verify`, and the live write-stage timeout and cancel).
- `tools/qualify_exiftool_write.py` (above) runs both modules' native classes; `tools/qualify_exiftool_write_loop.py --exiftool EXE --output-directory DIR` runs the
  public agent loop (author, plan, run, small-page inspection, verify, stale-revision refusals) and a workflow with two image producers, unchanged resume, invalidation
  by changed bytes and by changed folder membership, and the refused-slot and out-of-range bindings. Both use fresh private directories and need no shared lock.
- Retained read runs: runs made by the accepted read-family source through `schemaxis run` verify with this source through `schemaxis verify`.

The native tests assert the exact semantic code and location of each metadata mutant only after every ordinary binding was refreshed and `publication_metadata.verify`
passed; integrity mutants (a changed capture, hard link, symbolic link, tampered publication) are tested separately. The live lifecycle holds a genuine Perl write
process with a test-owned SIGSTOP after its inputs were bound, then lets the operation's own timeout or cancel end it: it shows the process and its group are gone and
nothing is published, not that the signal arrived inside ExifTool's parser. Report any newly run result separately from this note.
Review repair (same day, E2). Added: native cases for keyword `add` and `remove` (three items with literal after-values and one conflicting-base item refused before any native process),
for the typed companion loss at the IPTC By-line limit (34 and 33 bytes are removed and reported, 32 bytes are written complete, a multi-creator list loses its whole IPTC form, the old
companion value is gone, and the IIM character-set declaration is the same as before) and for NFC and NFD exactness, all in `tests.unit.test_exiftool_write_complete.NativeFamily` and
read back from the output bytes by local IIM and XML parsers; the read-family agent loop now reads the qualification state through the public scalar `/qualification/status` pointer and
pages the whole object when a large registered receipt makes it a members page (`--discovery-only` runs that part without a native runtime), and its search and invalid-draft
assumptions about the write operations were replaced by checks of the offered operations, keeping the geotag, rename, time-shift, unknown-profile and raw-argument negatives.

Production review repair (same day, E2): an independent review showed that a maker note ExifTool recognises was exempt from the independent byte comparison, so unreferenced bytes of such a note could change
silently (a real edit replaced 8 trailing bytes with a footer and the item was published with no record). The exemption is gone. A changed maker note is now proved by a relocation-aware local parser
(Canon-style plain IFD) or refused with `MAKERNOTE_CHANGED`; replaced unreferenced bytes are a declared per-item side effect `S8-makerNoteRebuilt` with hashes and ranges; the Interop IFD is compared by a local
parser; Sub-IFDs remain native-diff only. Native and host cases: `tests.unit.test_exiftool_write_complete` (`MakerNoteRelocation`, `NativeFamily`). The four class-level temporary directories of the two write
test modules are removed after the class.

Not claimed: whole ExifTool coverage, Metadata Working Group compliance, privacy or anonymity certification, image authenticity, time and location writes, XMP sidecar
writing, preservation of XMP qualifiers (such items are refused), absolute-offset maker notes that ExifTool does not recognise, or any container other than JPEG. A refused or failed item is reported
per item with a stable code; the proofs are byte-level and listing-level statements, not pixel statements.
