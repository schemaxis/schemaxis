# ExifTool metadata workbench: design direction

Status: design direction. It describes intended work and marks what has shipped; [docs/exiftool.md](../exiftool.md) and the
adaptor's `assessment.json` describe what ships. The shipped `inventoryPhotos` operation is unchanged by this document.
Objective E1 (the read, audit and compare family) is implemented and host-tested; its native qualification is recorded in the
verification notes and is not a qualification label.

## Purpose

Help a person or agent understand, audit, correct and organise the metadata that their photographs (and, later, other media) carry
about themselves. Authors state intent as typed domain declarations: which photos, which kinds of information, later which
corrections or naming rule. Schemaxis chooses the ExifTool invocation. Each published value says how it was established.

Non-goals: a general ExifTool front end; passing through tag names, command-line options, `-if`/`-p` expressions, Perl, `-config`
files or `-api` settings; certifying capture truth, authorship or location; certifying that a file is private or anonymous;
validating C2PA signatures or other provenance; editing a user's original files; claiming Metadata Working Group compliance.

## 1. Two named proof levels

| Level | Meaning | What verification establishes | What it does not establish |
| --- | --- | --- | --- |
| `independent` | Schemaxis's standard-library reader located the bytes and decoded the value under a catalogue rule, and ExifTool agreed on the same bytes when the value was produced. | The value is what these bytes encode under the documented rule, re-derived from the retained bytes at verification. | That the camera or author recorded the truth. |
| `native-observed` | The pinned ExifTool 13.55 reported the value for exactly these captured bytes. | A fresh process of the configured trusted runtime lists the retained captured bytes again and the output equals the retained listing. | That ExifTool's interpretation is correct. A same-engine replay is reproducibility, not independent semantic truth. |

Rules that follow from this:

- **A retained JSON file and its hash cannot establish what ExifTool reported.** Verification of a native listing replays it with the
  configured trusted runtime (never a receipt executable, never PATH). Without that runtime the outcome is `NATIVE_REPLAY_UNAVAILABLE`,
  not `verified: true`.
- **Anchoring.** Every independently decoded source of a file is compared with the native listing of the same bytes; any mismatch
  (a value, a missing or extra value, a different instance count) refuses that file. It never lowers a proof level.
- The native command is a constant (`-json -a -G0:1:4 -n -e -u -q --System:all`): volatile filesystem tags are excluded, real
  warnings and errors are kept, unknown tags are listed, and repeated names keep their instance number. Names and values it reports are
  observations, never declarations.

## 2. Presence states

`present`, `absent` (the family was understood and has no value), `unreadable` (present but malformed), `unsupported` (outside the
reader), `ambiguous` (duplicate locations or conflicting sources) and `unassessed` (not requested). They are never merged. Concordance
between EXIF, IPTC, XMP and sidecar sources is the literal equality of canonical values: no source is preferred and no
reconciliation standard is claimed.

## 3. Reusable abstractions (E1: shipped)

1. **Media set**: explicit items or one bounded folder, a complete inclusion/exclusion manifest, per-item faults, deterministic order,
   folder re-scan after capture, no symbolic link followed, originals never modified.
2. **Field catalogue** (`fields.json`): semantic ID, type, unit, privacy class, source locations per metadata family, codec, native anchor
   key and a reviewed description. Adding a field is catalogue data plus a fixture.
3. **Container locators** (JPEG, XMP sidecar) and **shared payload decoders** (TIFF/EXIF IFD walker, hardened bounded XMP reader, IPTC-IIM
   reader with explicit coded character set). A new container costs one locator; a new payload family costs one decoder.
4. **Typed records** with per-source states and derived fields, **audit rules** (closed set) and **comparison** over those records.
5. **Typed profile tables** for a spreadsheet, with a State column beside every value column.

Planned abstractions (not started): edit set, output copy, before/after record, time evidence and plan artifacts.

## 4. Capability families and status

| Family | User intent | Operations | Status |
| --- | --- | --- | --- |
| F1 Inspect | "What do these files say?" | `inspectMetadata` (closed profiles, optional native listing) | E1 implemented |
| F2 Audit and compare | "What differs, what conflicts, what is missing?" | `auditMetadata`, `compareMetadata` | E1 implemented |
| F3 Edit | "Set rights, captions and keywords on copies" | `editMetadata` | E2 implemented for JPEG copies (nine fields, set/clear/list add-remove, languages, creator lists, loss policy) |
| F5 Remove and minimise | "Share copies without location or device identity" | `removeMetadata` | E2 implemented for JPEG copies (six categories and a rendering-preserving minimise); removal is not privacy certification |
| F6 Time | "Fix the camera clock; align devices" | `reconcileTime`, `correctTime` | planned (E3) |
| F7 Location | "Where do the files say they were?" | `locate`, `setLocation`, `geotagFromTrack` | planned (E3) |
| F4 Copy and sidecars | "Carry metadata to another file or sidecar" | `copyMetadata`, `exportSidecar`, `applySidecar` | planned (E4) |
| F8 Naming | "Name and file copies by capture time and camera" | `planNames`, `organiseCopies` | planned (E4) |
| Containers | TIFF/DNG, PNG, WebP, HEIC read, then write | locators | shipped (E5) |

Every write operation will also prove preservation: image data byte-identical between input and output, non-target metadata changed only
as the catalogue declares, with an independent readback of every written field. Writing is limited to what the independent reader can read back.

## 5. Conventions and primary sources

- GPS conventions come from the EXIF specification (CIPA DC-008-2012, Exif 2.3): unsigned degree/minute/second rationals with N/S and E/W
  references, an altitude reference flag (0 above, 1 below sea level), UTC time and date stamps, an image direction with a true/magnetic
  reference, and a free-text map datum whose recording is only recommended. Schemaxis reports signed decimal degrees with the recorded
  datum text, converts nothing between datums and never infers WGS-84. The `OffsetTime*` tags are not in Exif 2.3 and come from the
  ExifTool tag table.
- The Metadata Working Group guidelines were read for property correspondences and the IPTC coded character set rule only. Reconciliation
  precedence is not implemented and compliance is not claimed.
- Location, device identity and creator fields carry privacy classes in every publication.

## 6. Coverage and measurement

Product completion is the set of planned families with shipped operations, honest evidence and a published matrix of
family × container × field, plus the list of remaining upstream gaps. It is not whole-application coverage: the ExifTool file-type and
tag tables are far larger than the catalogue, so the assessment keeps a low, subjective whole-application estimate and a separate
declared-workflows abstraction estimate. The catalogue size and the bounds (items, bytes, tags) are engineering judgements about resource
cost, not demand evidence.

Abstraction questions to keep asking: do authors state intent with catalogue IDs, profiles, rules and baselines rather than tags and
options; can a field be added with catalogue data alone; does every value carry its proof level and source locations; are the presence
states distinct; does any input accept a raw tag name, option, expression or configuration (it must not).

## 7. Compatibility

`schemaxis.exiftool/1` `inventoryPhotos` keeps its plan hash, trusted launchers, publications and verification byte for byte (a test pins the
plan hashes and a comparison against the foundation sources confirmed them). The new operations are additive alternatives in the same
route schema.

## 8. Time and location (E3: shipped contract)

E3 ships `reconcileTime`, `locate`, `correctTime`, `setLocation` and `geotagFromTrack`; [docs/exiftool.md](../exiftool.md#time-and-location-workflows) is the
operation guide. The decisions that shape the design are recorded here.

- **Declared intent, never native expressions.** Authors state device groups, true times, offsets, shifts, positions and tracks. The operation selects an internal expanded
  field catalogue (`fields/3`, add-only over `fields/1`, so every earlier field identity and plan hash is unchanged) and a closed write catalogue; no catalogue, overlay,
  tag, flag or expression key exists in a public option. Native writes are fixed numeric assignments (`-n`, an empty `-config`) of values computed by exact host arithmetic.
- **A clock model with explicit evidence.** Skew is recorded minus true, in exact rationals. Groups carry states (`anchored` by references, `insufficient` evidence, `conflicting`; an assumed-correct group is labelled as declared),
  drift is evaluated at each photo's instant and bounded by span, and a declaration (reference, assumed offset, assumed-correct group) is labelled and never verified. A recorded
  but unreadable offset is not an absent one.
- **Positions are exact decimals with a stated bound.** Coordinates are stored as degrees, minutes and seconds rationals; the independent readback must recover the declared
  decimal within 2e-10 degrees, which is a serialisation bound and never accuracy. Seconds of exactly 60 are an exact non-canonical form, and exact zero stays exact zero.
- **Altitude meaning is a typed fact.** The height reference follows the metadata edition (Exif 3.x explicit references; a GPS-only 2.4 block inferred and labelled; legacy 0 and 1
  unspecified). No vertical datum is converted and no `ExifVersion` is promoted or demoted. ExifTool adds `ExifVersion` when a write creates an Exif directory, which would change the
  reading of a GPS-only height without changing its bytes; a typed height-preservation proof (`ALTITUDE_MEANING_CHANGED`) and a creation guard (`EXIF_CREATION_UNVERIFIED`) refuse
  such an item. The same guard is intended for any later operation that creates an Exif directory.
- **Tracks are untrusted input.** A GPX file is captured, scanned for markup declarations before any parser runs, parsed within depth, element, point and text limits, and
  interpolated by Schemaxis great-circle slerp with gap, overlap (pairwise agreement) and speed rules. The native geotag feature is deliberately not used and not compared.
- **Plans and partial results.** `apply: plan` publishes a plan that records the capture hashes and exact arguments; applying it later is refused when it was edited, its
  catalogue is unknown or a capture changed. Every item keeps a stable artifact slot, and a run can be partly successful with a truthful per-item outcome.

Not provided by E3: copying metadata between files (exposure or location transfer), sidecar writes, renaming, reverse geocoding, vertical datum conversion and other containers (section 9 describes the
copy, sidecar and naming operations that E4 adds; reverse geocoding, vertical datum conversion and other containers stay unprovided).

## 9. Copy, sidecar and naming (E4: shipped contract)

E4 adds five operations on the same capture, independent-reader and fixed-listing machinery, with no second writer and no authored native name. The design choices that the code and the
tests hold to:

- **Typed snapshots are the only input of a transfer.** A snapshot decodes a closed field set from one capture or sidecar and keeps present, absent, ambiguous, unreadable and
  unsupported distinct; a value is present only when every source that records it agrees, no source is preferred, and an unreadable source value is never treated as absent. Values are
  raw decoded literals: exact text, the exact language set, list order and exact numerator and denominator pairs (10/30 and 1/3 stay different values).
- **Transfer reuses the E2 copy writer.** The planner turns snapshot decisions (write, clear, unchanged, keep, skip, or a precise refusal) into the E2 edit plan for the descriptive,
  rights, rating and place fields and into a small pinned table of EXIF destinations (`writes/2`) for camera, lens, serial and exposure values. Nothing is copied as a block, MakerNote or
  unknown tag and `-tagsFromFile` is never used. A transfer never creates an Exif block or ExifIFD, so the native writer cannot add the `ExifVersion` that changes what an untouched
  GPS-only height means; the typed height is still read again after the write.
- **Mixed selections compose parts into one write.** The planner yields the E2 edit plan, the extras, an E3 time plan (the shared `time_plan` with an internal absolute captured-time set: the source's exact local time, fraction digits and offset, also into a destination that records none, in one carrier that needs no new block; no invented zone and no authored option) and an E3 location plan (rounded coordinates, typed altitude reference); one native process writes all parts and the same output bytes are proved by the E2 and E3 readbacks, one closed native diff over the union of every part's declared targets and proof T. A single captureTime or location selection takes this route too, so proof T runs for every item. A refusal of any selected part (a conflicting, unreadable or unrepresentable value, an offset the source lacks, a different fraction precision, an Exif block that would have to be created) refuses the whole item.
- **Proof T is two readings.** T-host compares the raw decoded literal of the source with the output (a captured time exactly; a position within the declared nine-decimal half-even quantisation, with its typed altitude and datum) and checks every kept, skipped or cleared field against its plan decision, with expectations that never come from the planner's own request;
  T-native compares the fixed native listings of source and output key by key, so a reader that normalises both sides cannot make a changed value look equal.
- **The sidecar is a host serializer, not a copy.** `exportSidecar` writes a closed set of 29 XMP properties in a fixed order from selected present facts. Proof S re-runs the serializer,
  re-reads the bytes with the hardened reader and anchors every property against a fresh native listing under a pinned property-to-key map. The Exif 3.x altitude reference is written as
  `exifEX:GPSAltitudeRef`, which ExifTool 13.55 lists literally but whose Composite altitude inverts the sign for code 2; that residual is published. Coordinate precision is stated: the
  stored value, the written decimal-minutes value and their difference in arc seconds.
- **Names are a closed vocabulary.** `planNames` has tokens and literals, no template language, expression or arithmetic; the sanitiser, truncation, reserved names, collisions (including
  a file and a directory, and an image and its sidecar as one unit) and fallbacks are declared per item. A name plan carries the capture hash of every item, so a plan made for other bytes is stale.
- **Organising copies is the only full binary clone.** `organiseCopies` creates exact copies inside the run, create-only, without following links and one directory level at a time; proof C
  recomputes hashes, paths and the tree and refuses any extra, linked or altered entry. Stable slots are fixed by item and kind.

Not provided by E4: full-block or MakerNote transfer, XMP structures, merging or editing an existing sidecar, a naming template language, delivery outside the run
directory, and containers other than JPEG.

## 10. Containers: TIFF, DNG, PNG, WebP and HEIF (E5: shipped)

Shipped: container profiles as pinned data (`containerprofiles.json`) and one bounded locator per family that returns the `containers.locate` shape plus slot states, an offset-free
protected fingerprint, write admissibility with precise refusals and published limitations; the shared TIFF walker and the XMP and IPTC readers decode every payload. One generalised
preservation proof P (`e5proof.preserve`, with the AM-16R WebP layout proof and the relocation-aware maker-note comparison) is judged independently of the native writer, whose output must also pass the
shared readback R and the closed native diff N. The shared copy writer and planners are unchanged in kind: `editMetadata`, `removeMetadata` (including PNG and WebP `minimise`, AM-17),
`correctTime`, `setLocation`, `geotagFromTrack`, `copyMetadata` and `applySidecar` write TIFF, DNG, PNG, WebP and (existing items) HEIF captures named by what they are, through the same time planner
(`e3time`, `e3write`) and transfer evaluator (`e4copy`) as JPEG, with their own T-host and T-native proofs; there is no second writer and no native passthrough. `exportSidecar`, `planNames` and
`organiseCopies` are host-only and work for every container. One item is bounded by 256 MiB for TIFF and DNG and 64 MiB for the rest.

Named limits that remain (each is a precise refusal, never a silent gap): TIFF and DNG `minimise`, thumbnails outside JPEG, HEIF removal and minimise (native `all=` leaves empty-extent items),
creating a HEIF Exif or XMP item (a measured, not reproducible, native 13.55 behaviour over 20 runs, so it is refused instead of attempted; items that exist are edited), a changed maker note that the
relocation-aware check cannot show equal (`MAKERNOTE_CHANGED`), BigTIFF, maker raw formats, JPEG XL and GIF. Reads and writes are separate decisions: a file can be fully readable
while a write is refused before any native process runs. The per-container field matrix, proof meaning and every named limit are in `docs/exiftool.md`.
