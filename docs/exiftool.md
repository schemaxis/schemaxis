# ExifTool photo-metadata workbench

`schemaxis.exiftool/1` reads, audits, compares, edits and removes the metadata that photographs declare about themselves, so a
person can reconcile photos with field observations in an editable workbook and publish corrected copies. It offers four read-only
operations: `inventoryPhotos` (the original fixed selected-field inventory of 1 to 16 baseline JPEGs), and the metadata workbench read
family `inspectMetadata`, `auditMetadata` and `compareMetadata` over a bounded media set of JPEG, TIFF, DNG, PNG, WebP and HEIF photos and XMP sidecar files (see
[the workbench](#metadata-workbench-inspect-audit-and-compare)); and the writing operations `editMetadata` and `removeMetadata`, which write new copies of JPEG, TIFF, DNG, PNG and WebP files and of HEIF files whose metadata items exist (see [editing and removal](#metadata-editing-and-removal) and [containers](#containers-tiff-dng-png-webp-and-heif)). Five more operations analyse and correct capture clocks and
positions: `reconcileTime` and `locate` read, and `correctTime`, `setLocation` and `geotagFromTrack` write new copies of the same container as the item (JPEG, TIFF, DNG, PNG, WebP, or HEIF with existing items; see
[time and location workflows](#time-and-location-workflows)). Nothing ever modifies an original, rotates, strips or decodes
an image. It reports what the files say; it does not say when, where or by whom a photograph was taken, and neither a clean audit nor a
removal is privacy certification.

## Operation `inventoryPhotos`

```json
{
  "version": "schemaxis.exiftool/1",
  "operation": "inventoryPhotos",
  "photos": [
    {"id": "north_gate", "path": "/absolute/north-gate.jpg"},
    {"id": "river_bend", "path": "/absolute/river-bend.jpg", "sha256": "…64 lowercase hex digits…"}
  ]
}
```

- `photos` holds 1 to 16 entries; their order is the row order of every publication.
- `id` is your stable human link: 1 to 32 ASCII letters, digits or underscores starting with a letter, unique in the
  document. The file path is never published.
- `path` is an absolute local regular `.jpg`/`.jpeg` file without parent references or symbolic-link final component.
- `sha256` optionally pins the photo bytes; a mismatch is `PHOTO_HASH_MISMATCH` at `$.photos[i].sha256`.
- No ExifTool option, tag list, configuration file, expression or script can be authored.

## Selected fields and what is not read

| Field | Source | Notes |
| --- | --- | --- |
| `width`, `height` | JPEG frame header (SOF0) | Positive integers; ExifTool must agree. |
| `orientation` | IFD0 Orientation (SHORT, 1-8) | The stored code only; pixels are not rotated. |
| `cameraMake`, `cameraModel` | IFD0 Make/Model (ASCII) | Printable ASCII, 1-64 characters, no leading/trailing blanks, never normalized. |
| `capturedLocal` | ExifIFD DateTimeOriginal | `YYYY-MM-DDTHH:MM:SS` wall time **without a zone**, calendar-validated; never labelled UTC. |
| `utcOffset` | ExifIFD OffsetTimeOriginal | `+HH:MM`/`-HH:MM` within -12:00..+14:00. `+00:00` is a recorded zero offset and is accepted; `-00:00` (RFC 3339 for an unknown offset) is refused as `INVALID_EXIF_VALUE` rather than published as UTC. |
| `capturedUtc` | arithmetic | Only when the same file records both time and offset. |

Each missing selected tag is a separate explicit null (`\N` in the CSV): the adaptor never substitutes filesystem
times, CreateDate or a zero, and never infers a device time zone. GPS, thumbnails, MakerNotes, XMP, IPTC, ICC, sub-second
fields, lenses, serial numbers and every other tag are **unassessed**: they are neither extracted nor claimed absent.

## Limits

- Baseline sequential 8-bit three-component JPEG/JFIF only; progressive, extended, lossless, arithmetic, one- and
  four-component, multi-frame, multi-scan and trailing-data files are refused (`UNSUPPORTED_JPEG`). Entropy data is
  scanned for a well-formed end but never decoded: success certifies marker and length structure only, not image quality.
- Each authored photo is a distinct source file. Two photos that reach the same file (the same normalised path, an ancestor symlink alias or a hard link: same device and inode) are refused before any file content is read or ExifTool starts, with `DUPLICATE_PHOTO_SOURCE` at the second `$.photos[i].path`; a symbolic link as the final path component is refused as `INVALID_PHOTO_SOURCE`. Distinct regular files with identical bytes stay allowed: an authored photo identity is its authored `id` and source file, nothing is deduplicated by content, and nothing claims the photos record different or the same real-world events. Photo IDs must also be unique (`DUPLICATE_PHOTO_ID`).
- At most 8MiB per photo, 16MiB in total (every selected file is examined with `lstat` and the sizes summed against both budgets before any file content is read; the open file's size, identity and bounded read are checked again), 128 segments, 256 IFD entries per IFD, IFD0 plus at most one further IFD.
- Refused before ExifTool starts, naming `$.photos[i].path` and the photo: duplicate selected tags
  (`DUPLICATE_EXIF_TAG`), more than one Exif segment (`AMBIGUOUS_EXIF`), cyclic or over-long IFD chains, bad offsets or
  counts, truncation (`INVALID_EXIF_STRUCTURE`, `INVALID_PHOTO_DATA`), wrong types, orientation outside 1-8,
  calendar-invalid dates and unsupported offsets including `-00:00` (`INVALID_EXIF_VALUE`).
- A Calc typed-table handoff needs at least two photos and at least two present orientation codes, because every
  number column needs two present values.

## Publications

1. `metadata.json` (`text`): photo count, per-photo ID, order, SHA-256, bytes, frame size, observed values, the scoped raw
   ExifTool observations, the scope statement, losses and a review block.
2. `inventory.csv` (`table`, format `schemaxis.calc.typed-csv/1`, null token `\N`): columns `id` (text), `width`,
   `height`, `orientation` (numbers), `cameraMake`, `cameraModel`, `capturedLocal`, `utcOffset`, `capturedUtc` (nullable
   text). Text is always quoted, so a formula-looking camera model such as `=SUM(1+1)` stays literal text.

## Verification

ExifTool 13.55, the production release, runs through `/usr/bin/perl` with a clean fixed environment and no user
configuration (`-config ''`), with `-json -n -a -G1:4 -e -q` and exactly the selected group-qualified tags (`-G1:4`
exposes an earlier duplicate as a `Copy1` key, which is refused). Its JSON is parsed strictly (duplicate keys are
errors; number tokens keep their exact text) and compared per tag, per presence and per JSON type with an independent
standard-library byte reader; a second fresh process must repeat the first byte for byte. Every publication is rebuilt
from the independent reader. The script, every file of its `lib` directory, the Perl binary, loaded libraries and
eagerly loaded Perl modules are hashed before and after the run. Modules Perl loads lazily are not enumerated.

Agreement shows only that the bytes say what the publications say. Cameras can record wrong clocks, zones, makes and
orientations, so no capture time, location or authorship is certified and a person must review the inventory.

## Calc handoff

Pass `{"$artifact": "inventory", "index": 1}` to a Calc `readTypedCSV` node with the nine declared columns (see
`examples/schemaxis/exiftool-calc-workflow.json`). Photo bytes changed at the same path invalidate producer and
consumer; unchanged photos reuse both.

## Running

The workbench operations are qualified natively by `tools/qualify_exiftool_workbench.py` (hand-written literal expectations, semantic mutants with refreshed bindings, a no-runtime control, live timeout and cancel on the new native process, and an exposure-profile handoff to Calc in both workbook formats); run it under the shared native-qualification lock because it stages fixed fixture paths. Its first measured results are in the verification note and are not a qualification label. It also runs real-ExifTool controls over private copies of the repair fixtures (a genuine native disagreement and its verified partial set, GPS references, repeated GPS reference tags, near-zero rationals, a readable XMP capture time beside a malformed EXIF one). Its Calc handoff reads both workbook formats back independently and compares every Data cell, every Summary label, value and formula and the text of the eight Summary header cells; the cell counts it reports are two-format totals with the per-format split beside them.

Two companion checks use only unique private fixture folders under their own evidence directory, so they need no shared fixed staging path and no qualification lock. `tools/qualify_exiftool_agent_loop.py` drives the public agent transport against a real ExifTool 13.55: discovery (queries for editing, writing, stripping and minimising find the write operations; geotagging, renaming and time-shift queries find nothing), adaptor context (the qualification state is read through the scalar `/qualification/status` pointer, and the whole object is paged when a large registered receipt makes it a members page), valid and invalid drafts with exact fault codes and locations (unknown operation, unknown profile, unauthored arguments, read-only arguments on a write operation, a write operation without its edits or categories, relative folder, required field without its rule), baseline and edited folder and item documents for all three operations, paginated `inspect_resource` of every table row and the native listing, byte-exact `resource` reads, revision-bound `verify` including a fresh native replay, stale-draft, wrong-task-revision, wrong-execute-revision and wrong-observation-revision refusals, folder selection (depth, exclusions, count limit, partial and all-failed sets), a run-level `MEDIA_FOLDER_CHANGED` control (the folder is changed at a deliberate owned boundary after the first item is captured, and no native stage may have started) and a second agent without a configured ExifTool, for which an independent-only run still verifies and a native-listing run is refused with `NATIVE_REPLAY_UNAVAILABLE`. `tools/qualify_exiftool_folder_reuse.py` runs the workflow scheduler (ExifTool folder inspect to Calc `readTypedCSV`) over one private folder: an unchanged folder reuses both jobs; same-path byte changes, an added or removed matching file, a rename that changes the item ID and byte order, and even an unrelated added file re-run the producer and, as observed, the consumer; a change to the authored document itself is refused on resume (`RESUME_MISMATCH`) and needs a fresh workflow directory. Every Data and Summary cell of both workbook formats is read back against hand-written rows. Neither tool certifies photographs, and neither qualifies any other application.

Configure the ExifTool script with `--exiftool` or `SCHEMAXIS_EXIFTOOL` (an absolute path with its `lib` directory
beside it). Provision the 13.55 production release privately; do not use a development release by recency.
`tools/qualify_exiftool.py` runs the bounded native qualification, including a full public-agent loop (`python3 -m schemaxis agent`): author, atomic edits, plan, run, `inspect_resource` of `inventory.csv` and `metadata.json` with pointer, paging and revision pins, byte-exact `resource` reads, a duplicate-source fault edit and `verify`. The original CLI `schemaxis inspect` requires `--node` for node-native inspection and is a different feature that this non-node route does not offer. Studio template insert, undo and Help rely on the shared parent UI checks (no new controls); an isolated browser run was not made.

Live lifecycle claim: `extract-inputs.json` is written by the launcher before `execve`, so it shows the input bindings only, not that ExifTool read or parsed an image. The qualifier observed a genuine ExifTool process with the captured inputs bound and then applied a SIGSTOP race hold before the timeout or cancel; nothing claims the signal arrived inside the Perl parser.

## Metadata workbench: inspect, audit and compare

The workbench operations share one pipeline. Items are captured into the run, the host's own standard-library
readers locate and decode the metadata payloads into typed, catalogued fields, and ExifTool 13.55 lists the same
captured bytes with a fixed argument list so every independent value can be anchored against it. You declare **what you
want to know**, using catalogue IDs; you never write a tag name, option, expression, script or configuration.

```json
{
  "version": "schemaxis.exiftool/1",
  "operation": "inspectMetadata",
  "media": {"folder": {"path": "/absolute/shoot-folder", "depth": 1, "sidecars": "adjacent"}},
  "profiles": ["capture", "device", "location"],
  "nativeListing": false
}
```

| Operation | Purpose | Extra fields |
| --- | --- | --- |
| `inspectMetadata` | A typed record per item for the selected profiles, one typed CSV per profile and optionally ExifTool's complete native listing. | `profiles` (required), `nativeListing` (default false) |
| `auditMetadata` | Findings from a closed rule set over the typed records. | `profiles`, `require`, `rules`, `gpsToleranceSeconds` |
| `compareMetadata` | An item-by-field matrix against one named baseline item. | `baseline` (required), `profiles`, `fields` |

### Media sets

`media` is either `{"items": [...]}` (1 to 512 explicit entries `{id, path, sha256?, sidecar?}`) or `{"folder": {...}}`.

- Every item has a stable `id` (1 to 32 ASCII letters, digits or underscores starting with a letter) and an absolute
  `path` (`.jpg`, `.jpeg`, standalone `.xmp`, or one of the container suffixes `.tif`, `.tiff`, `.dng`, `.png`, `.webp`, `.heic`, `.heif`, `.avif`: the container is always detected by signature, never by suffix). `sha256` pins the bytes. `sidecar` names an XMP sidecar for a JPEG.
- A `folder` has an absolute `path`, `extensions` (default `.jpg`, `.jpeg` and `.xmp`; list the container suffixes to include those files), `depth` 0 to 2 (default 1), `maxItems` (default 64,
  at most 512) and `sidecars` (`adjacent` pairs `name.xmp` or `name.jpg.xmp` with the image; `none` does not).
- A folder scan is deterministic (names in byte order), follows no symbolic link, skips hidden entries, never leaves the
  selected root and lists **every scanned entry** in `manifest.json` as included or excluded with a reason:
  `extension`, `hidden`, `symlink`, `not-regular`, `too-large`, `count-limit`, `invalid-id`, `duplicate-id`,
  `ambiguous-sidecar`, `unreadable-entry`, `directory-scanned` and `directory-beyond-depth`. Item IDs come from the file stem
  (non-identifier characters become `_`).
- Per-item problems are item faults and the run continues; the set status is `complete` only when every included item
  succeeded and nothing eligible was excluded for a limit or safety reason (otherwise `partial`). A set in which every
  item failed is a failed run (`NO_USABLE_ITEMS`), not a success. The folder is scanned again after capture; a change is the
  structural fault `MEDIA_FOLDER_CHANGED`. Budgets: 512 items, 64 MiB per item, 1 GiB in total, 4096 scanned entries.
- Originals are only read. Hashes identify the captured bytes, not their origin. Publications name items by ID and show only a file name (explicit items) or a path relative to the scanned folder (folder sets); the absolute authored paths stay in the run's `authored.json` and `captures.json`, never in a publication.

### Field catalogue

The catalogue (`fields.json`) is the single place that says where a field lives and how it is decoded. Adding a field is a
catalogue entry plus a fixture, not a new operation. Profiles select fields: `capture`, `device`, `exposure`,
`description`, `rights`, `location` and `rendering`.

| Field | Profile | Meaning, units, absence, privacy and proof | Type (unit) | Source locations | Privacy class |
| --- | --- | --- | --- | --- | --- |
| `capturedLocal` | capture | When the file says the photograph was taken, as camera-recorded wall time without a zone (YYYY-MM-DDTHH:MM:SS), from EXIF DateTimeOriginal, XMP photoshop:DateCreated and IPTC 2:55 with 2:60. Absent means no source records it; a wrong camera clock is still a well-formed value. Cross-source disagreement makes it ambiguous. Independent proof: decoded from the bytes and anchored to ExifTool. | localDateTime | EXIF ExifIFD 0x9003; XMP `photoshop:DateCreated`; IPTC 2:55 | capture-time |
| `capturedSubSecond` | capture | The decimal digits after the second of the capture time (EXIF SubSecTimeOriginal or the XMP fraction), kept as text so leading zeros survive. Absent when no source records a fraction. It is not added to capturedLocal. | digits (decimal fraction of a second) | EXIF ExifIFD 0x9291; XMP `photoshop:DateCreated` | capture-time |
| `capturedOffset` | capture | The UTC offset the file records for the capture time, as +HH:MM within -12:00 to +14:00 (EXIF OffsetTimeOriginal, XMP date suffix, IPTC 2:60). -00:00 means unknown and is unreadable rather than UTC. Absent means no offset is recorded and no zone is inferred. | offset (hours:minutes from UTC) | EXIF ExifIFD 0x9011; XMP `photoshop:DateCreated`; IPTC 2:60 | capture-time |
| `capturedUtc` | capture | The capture instant in UTC, derived by exact arithmetic only when capturedLocal and capturedOffset are both present and agree across sources. Absent when either is missing; ambiguous or unreadable inputs make it the same. It inherits the doubts of a camera clock. | utcInstant | derived from capturedLocal and capturedOffset | capture-time |
| `digitizedLocal` | capture | When the file says it was digitized or created as a digital file (EXIF DateTimeDigitized, XMP xmp:CreateDate), local wall time without a zone. It can differ from the capture time for scans. Independent proof. | localDateTime | EXIF ExifIFD 0x9004; XMP `xmp:CreateDate` | capture-time |
| `modifiedLocal` | capture | When the metadata says it was last modified (EXIF DateTime in IFD0, XMP xmp:ModifyDate), local wall time without a zone. It is a recorded value, never a filesystem time. | localDateTime | EXIF IFD0 0x0132; XMP `xmp:ModifyDate` | capture-time |
| `cameraMake` | device | The camera manufacturer text recorded in the file (EXIF Make, XMP tiff:Make), exactly as written. Device identity class: it can narrow who took a photo. Absent when not recorded; XMP and EXIF disagreeing makes it ambiguous. | text | EXIF IFD0 0x010F; XMP `tiff:Make` | device-identity |
| `cameraModel` | device | The camera model text recorded in the file (EXIF Model, XMP tiff:Model), exactly as written. Device identity class. Absent when not recorded. | text | EXIF IFD0 0x0110; XMP `tiff:Model` | device-identity |
| `software` | device | The software text in EXIF Software (often an editor or firmware string). It shows what last wrote the tag, not who edited the image. Device identity class. | text | EXIF IFD0 0x0131 | device-identity |
| `lensMake` | device | The lens manufacturer text in EXIF LensMake. Device identity class. Absent when the camera does not record it. | text | EXIF ExifIFD 0xA433 | device-identity |
| `lensModel` | device | The lens model text in EXIF LensModel. Device identity class. Absent when the camera does not record it. | text | EXIF ExifIFD 0xA434 | device-identity |
| `bodySerialNumber` | device | The camera body serial number in EXIF BodySerialNumber. Device identity class: it can link photos to one body and owner; consider it before sharing. Absent when not recorded. | text | EXIF ExifIFD 0xA431 | device-identity |
| `lensSerialNumber` | device | The lens serial number in EXIF LensSerialNumber. Device identity class; it can link photos to one lens. Absent when not recorded. | text | EXIF ExifIFD 0xA435 | device-identity |
| `exposureTime` | exposure | Exposure time in seconds (EXIF ExposureTime), a positive rational published as a number with an exact n/d text. Unitless-looking values are seconds. A zero denominator is unreadable. | rational (seconds) | EXIF ExifIFD 0x829A | none |
| `fNumber` | exposure | The aperture f-number (EXIF FNumber), a rational such as 2.8. It has no unit. Absent for lenses that do not report it. | rational (f-number) | EXIF ExifIFD 0x829D | none |
| `isoSpeed` | exposure | The ISO speed rating (EXIF ISOSpeedRatings / PhotographicSensitivity), one integer. One integer; several values are unreadable rather than guessed. | integer (ISO speed rating) | EXIF ExifIFD 0x8827 | none |
| `focalLength` | exposure | The actual focal length in millimetres (EXIF FocalLength), a rational. It is not the 35 mm equivalent. | rational (millimetres) | EXIF ExifIFD 0x920A | none |
| `focalLength35mm` | exposure | The 35 mm-equivalent focal length in millimetres (EXIF FocalLengthIn35mmFormat), one integer, as recorded. | integer (millimetres (35 mm equivalent)) | EXIF ExifIFD 0xA405 | none |
| `exposureBias` | exposure | Exposure compensation in EV steps (EXIF ExposureBiasValue), a signed rational; negative is darker. | rational (EV) | EXIF ExifIFD 0x9204 | none |
| `title` | description | A short title (IPTC 2:5 ObjectName, XMP dc:title x-default). Descriptive text: it can name people or places. Only the x-default language is read; other languages alone are unsupported. | text | IPTC 2:5; XMP `dc:title` | descriptive-text |
| `description` | description | The caption or description (EXIF ImageDescription, IPTC 2:120, XMP dc:description x-default). Descriptive text that can name people or places. Disagreeing sources make it ambiguous; none is preferred. | text | EXIF IFD0 0x010E; IPTC 2:120; XMP `dc:description` | descriptive-text |
| `keywords` | description | Keywords as a list (IPTC 2:25 repeated, XMP dc:subject), order preserved and not de-duplicated. They can name people or places. Equal lists in the same order are consistent; any difference is a conflict. | textList | IPTC 2:25; XMP `dc:subject` | descriptive-text |
| `rating` | description | The XMP xmp:Rating integer, as recorded (the value is not range-checked). Not an authenticity or quality claim. | integer (XMP rating value) | XMP `xmp:Rating` | none |
| `creator` | rights | The creator names as a list (EXIF Artist as one entry, IPTC 2:80 repeated, XMP dc:creator). Personal identity class: it names a person. A recorded creator is a claim by the file, not proof of authorship. | textList | EXIF IFD0 0x013B; IPTC 2:80; XMP `dc:creator` | personal-identity |
| `copyright` | rights | The copyright notice (EXIF Copyright with its strings joined by a line feed, IPTC 2:116, XMP dc:rights x-default). Personal identity class. A notice is not a licence or proof of ownership. | text | EXIF IFD0 0x8298; IPTC 2:116; XMP `dc:rights` | personal-identity |
| `rightsUrl` | rights | The rights web statement URL (XMP xmpRights:WebStatement), text as recorded; it is not fetched or checked. | text | XMP `xmpRights:WebStatement` | none |
| `gpsLatitude` | location | Latitude in signed decimal degrees, north positive, from three unsigned degree/minute/second rationals and the N/S reference (EXIF GPS IFD, CIPA DC-008). A missing or invalid reference is unreadable. Location class. The datum is the separate gpsDatum field; nothing is converted. | degrees (signed decimal degrees (north positive)) | EXIF GPS 0x0002 | location |
| `gpsLongitude` | location | Longitude in signed decimal degrees, east positive, from three unsigned degree/minute/second rationals and the E/W reference (EXIF GPS IFD). Location class. The datum is gpsDatum; nothing is converted. | degrees (signed decimal degrees (east positive)) | EXIF GPS 0x0004 | location |
| `gpsAltitude` | location | Altitude in metres: negative when GPSAltitudeRef is 1 (below sea level), positive when 0 or when the reference is absent (the Exif default). The file does not say which sea level. Location class. | meters (metres relative to the recorded reference (negative below sea level)) | EXIF GPS 0x0006 | location |
| `gpsDirection` | location | The direction the camera faced, degrees clockwise from 0 up to but not including 360 (EXIF GPSImgDirection). Read it with gpsDirectionReference. Location class. | degrees (degrees clockwise from the reference north) | EXIF GPS 0x0011 | location |
| `gpsDirectionReference` | location | Whether gpsDirection is relative to true north (T) or magnetic north (M), published as true or magnetic. Absent means the file did not say, not that it is true north. | enum | EXIF GPS 0x0010 | location |
| `gpsDatum` | location | The geodetic datum text the GPS receiver recorded (EXIF GPSMapDatum, for example WGS-84), exactly as written. Absent means unspecified: Schemaxis never infers WGS-84 and never converts datums. | text | EXIF GPS 0x0012 | location |
| `gpsUtcDate` | location | The GPS date stamp (EXIF GPSDateStamp, UTC) as YYYY-MM-DD, calendar-validated. Location class because it ties the file to a GPS fix. | date | EXIF GPS 0x001D | location |
| `gpsUtcTime` | location | The GPS time stamp (EXIF GPSTimeStamp, UTC) as HH:MM:SS. Fractional-second components are unsupported rather than rounded. Location class. | time | EXIF GPS 0x0007 | location |
| `gpsUtc` | location | The GPS UTC instant, derived only when gpsUtcDate and gpsUtcTime are both present. It is the receiver's clock, which can differ from the camera clock; the audit compares them. | utcInstant | derived from gpsUtcDate and gpsUtcTime | location |
| `locationCity` | location | The named city text (IPTC 2:90, XMP photoshop:City). Location class and descriptive: it is text a person or software wrote, not a verified place. | text | IPTC 2:90; XMP `photoshop:City` | location |
| `locationCountry` | location | The named country or primary location text (IPTC 2:101, XMP photoshop:Country). Location class; it is not verified against the GPS position. | text | IPTC 2:101; XMP `photoshop:Country` | location |
| `orientation` | rendering | The stored EXIF orientation code 1 to 8 (IFD0 Orientation, XMP tiff:Orientation) with its label. Pixels are not rotated by reading it; a viewer that ignores it shows the image sideways. | code (EXIF orientation code 1-8) | EXIF IFD0 0x0112; XMP `tiff:Orientation` | none |
| `imageWidth` | rendering | The frame width in pixels from the JPEG frame header (not EXIF PixelXDimension). Unsupported for an XMP sidecar, which has no frame. | integer (pixels) | JPEG frame width | none |
| `imageHeight` | rendering | The frame height in pixels from the JPEG frame header. Unsupported for an XMP sidecar, which has no frame. | integer (pixels) | JPEG frame height | none |

Times are camera-recorded wall times without a zone (`capturedLocal`, `digitizedLocal`, `modifiedLocal`). `capturedUtc` is
derived only when the same file records a valid offset; `gpsUtc` only from the GPS date and time stamps. Rationals are
reported as numbers with an exact `n/d` text where it differs. Lists (`creator`, `keywords`) are JSON arrays; in a CSV
they are JSON text.

### Presence states

Each assessed field has exactly one state, and states are never merged or replaced by filesystem times or inferred values.

| State | Meaning | Typical recovery |
| --- | --- | --- |
| `present` | At least one source holds a well-formed value (all present sources agree). | none |
| `absent` | Every source family was understood and none records the value. | add the metadata if you need it |
| `unreadable` | Every source that holds a value holds a malformed one (bad date, bad reference, bad charset, refused XMP). A malformed source beside a readable one leaves the field `present` and `partially-assessed`; the audit still names it. | repair the file or its writer; see the source `code` |
| `unsupported` | Well-formed but outside the reader (structured XMP, language-only text, reduced-precision date, fractional GPS time, a field the container cannot carry). | read it natively in `native-observations.json` |
| `ambiguous` | Duplicate locations, a repeated tag (including a repeated GPS reference tag), or two sources that disagree. No source is preferred. | decide which source is right and fix the others |
| `unassessed` | Not in the requested profiles or fields. Not claimed either way. | add the profile or field |

A field's `reconciliation` is `single-source`, `consistent`, `partially-assessed`, `conflicting`, `ambiguous-source`, `derived` or `none`. Concordance
is the literal equality of canonical values across EXIF, IPTC, XMP and an adjacent XMP sidecar; it is **not** Metadata
Working Group reconciliation and no preferred value is chosen. `single-source` means the other sources were understood and hold no value.
When one source is readable and another is `unreadable` or `unsupported`, the field keeps the readable value but is `partially-assessed`,
because agreement with the unread source was never established; its `unassessedSources` list names each such source with its state and code.

### Proof levels and native verification

- `independent`: the host reader located and decoded the value from the captured bytes under the catalogue rule, and ExifTool
  agreed when the run produced it. A disagreement refuses that item (`NATIVE_ANCHOR_MISMATCH`); it never downgrades a proof level. The numeric anchors are exactly as wide as ExifTool
  13.55 serialises: a RATIONAL64 is printed as its fraction rounded to 10 significant digits (a wrong last digit is a disagreement, and zero must be an exact zero),
  and a GPS coordinate is the sum of three such rounded parts (within 5e-10 of the exact value, relative, with no absolute floor). The signed GPS values are
  also anchored against the native `GPSLatitudeRef`, `GPSLongitudeRef` and `GPSAltitudeRef` tags (a missing altitude reference must stay absent), because the
  native coordinate values are unsigned. A GPS reference tag that the file repeats makes only that field `ambiguous`, with the source code `EXIF_COMPANION_REPEATED`
  (`companion` names the repeated tag and `instances` the copies; a repeated main tag keeps `EXIF_TAG_REPEATED`). Native must list exactly those copies (ExifTool prints the last as the main tag and the
  earlier ones as `Copy1`, `Copy2`), by count and by value in any order, and the copies stay in `native-observations.json` as ambiguous observations; the other fields of the photo and the other photos are unaffected. A refused item leaves a verified `partial` set for the others; the native replay still lists every admitted capture,
  because the retained listing was made over all of them. A real example is `padded-make.jpg`: its Make was edited in place from `Northfield` to `Northfiel `
  followed by a space, which ExifTool trims and the independent reader keeps.
- `native-observed`: ExifTool's own report of exactly those bytes (only in `native-observations.json`, when `nativeListing` is true).
  A repeat of the same engine is reproducibility, not independent semantic truth.
- `verify` re-derives every independent value from the retained bytes, rebuilds every publication, and replays the native
  listing with the **configured trusted runtime** (`--exiftool`, `schemaxis configure exiftool` or `SCHEMAXIS_EXIFTOOL`; a
  receipt executable is never launched and PATH is not consulted). With `nativeListing` true and no trusted runtime the outcome is
  `NATIVE_REPLAY_UNAVAILABLE`: never `verified: true`. Without a native listing the result states
  `nativeReplay: not-replayed` and publishes no native-observed value.

### Native listing

The fixed command is `perl exiftool -config '' -json -a -G0:1:4 -n -e -u -q --System:all captured/…`. `--System:all` removes
volatile filesystem tags so two fresh processes list the same bytes identically; real native warnings and errors are kept,
unknown tags are listed, and a repeated name keeps its instance number (`instance` above 0, `ambiguous: true`). A name that
appears under two groups is two observations. Bounds: 4096 tags per file, 64 KiB per value, 4096 list elements, 64 MiB in total;
exceeding one is a per-item fault (`NATIVE_LISTING_BOUND`). Native names and values are observations, never declarations.

### Audit rules

`rules` is a closed set (default: all, with `requiredFields` only when `require` is given):

| Rule | Reports |
| --- | --- |
| `requiredFields` | each `require` field that is not `present`, with its state |
| `sourceConflicts` | ambiguous fields: conflicting sources or duplicate locations, with each source value |
| `unreadableValues` | fields with a malformed source, with the source codes, even when another source of the field is readable (`fieldState` says which) |
| `timePlausibility` | GPS UTC more than `gpsToleranceSeconds` (default 300) from the capture instant; digitization before capture; an offset without a time; GPS time that cannot be compared without an offset |
| `privacyInventory` | which `location`, `device-identity` and `personal-identity` fields each file records (information, not a verdict) |
| `duplicateContent` | distinct sources with identical bytes |

Findings are observations, not proof of tampering; a file without findings is not certified.

### Comparison

`compareMetadata` compares every other item with the named `baseline` for each assessed field: `same`, `different`,
`missing-in-item`, `missing-in-baseline`, `both-absent` or `not-comparable` (an ambiguous, unreadable or unsupported side).
Equality is exact on canonical values; nothing is rounded.

### Workbench publications

All three write `metadata.json` (per-item typed records, every source, states and the review block) and `manifest.json` (the
complete media-set manifest with statuses). `inspectMetadata` adds one `profile-<name>.csv` per requested profile and, when
requested, `native-observations.json`. `auditMetadata` adds `audit.json` and `findings.csv`; `compareMetadata` adds
`comparison.json` and `differences.csv`. A typed CSV has `id`, then for each field its value column and a `<field>State` column;
`\N` means no published value and the State column says why (`present-not-tabular` marks a present text a typed table cannot
carry: empty, control characters or over 1024 characters). Only successful items are rows. Calc `readTypedCSV` needs at least two
present values in every number column and at least one row, so a profile such as `exposure` hands off only when two photos record
exposure; the CSV is published either way and the consumer refuses an unsuitable one.

### Faults and recovery

Set-level faults fail the run: `INVALID_MEDIA_FOLDER`, `MEDIA_FOLDER_UNREADABLE`, `MEDIA_FOLDER_LIMIT`, `MEDIA_FOLDER_CHANGED`,
`MEDIA_RESOURCE_LIMIT`, `NO_USABLE_ITEMS`, `INVALID_BASELINE` and native-run faults. Item faults are rows in `metadata.json` and
`manifest.json` with the fault code and location: `INVALID_PHOTO_SOURCE`, `DUPLICATE_PHOTO_SOURCE`, `PHOTO_HASH_MISMATCH`,
`PHOTO_RESOURCE_LIMIT`, `UNSUPPORTED_MEDIA`, `INVALID_PHOTO_DATA`, `INVALID_SIDECAR`, `NATIVE_ANCHOR_MISMATCH`,
`NATIVE_REPORTED_PROBLEM` and `NATIVE_LISTING_BOUND`. Field-level codes (for example `XMP_DOCTYPE_REFUSED`, `IPTC_CHARSET_UNSPECIFIED`,
`GPS_REF_MISSING`, `EXIF_TAG_REPEATED`, `EXIF_COMPANION_REPEATED`, `INVALID_DATE_VALUE`) appear on the source record, not as a fault.

### Privacy

Location, device identity and creator fields can identify a person or place. `privacyInventory` lists what a file carries;
`removeMetadata` removes the listed categories in the understood locations of the copies, but nothing certifies privacy or anonymity.
Synthetic fixtures use an invented open-ocean position and invented names.

### Primary sources and conventions

- GPS conventions were read from CIPA DC-008-2012 (Exif 2.3): latitude and longitude are three RATIONAL degrees, minutes, seconds
  with `N`/`S` and `E`/`W` reference letters; `GPSAltitudeRef` is 0 above and 1 below sea level with an absolute altitude in metres;
  `GPSTimeStamp` is UTC hours, minutes, seconds and `GPSDateStamp` is `YYYY:MM:DD`; `GPSImgDirection` is 0.00 to 359.99 with a `T`
  (true) or `M` (magnetic) reference; `GPSMapDatum` is free ASCII and its recording is only recommended. The `OffsetTime*` tags are
  not in Exif 2.3; they are taken from the ExifTool 13.55 tag table and are labelled as such. Schemaxis reports the recorded datum text and does not
  convert or infer WGS-84.
- Property correspondences (EXIF ImageDescription/Artist/Copyright, IPTC 2:120/2:80/2:116, XMP `dc:description`/`dc:creator`/`dc:rights`,
  IPTC keywords and `dc:subject`, EXIF DateTimeOriginal with IPTC 2:55/2:60 and `photoshop:DateCreated`) and the IPTC coded-character-set rule were read from
  the Metadata Working Group guidelines. The workbench uses them only to decide which sources to compare literally; it makes no
  MWG-compliance claim and implements no MWG precedence rule.
- The pinned runtime is ExifTool 13.55, the production release; 13.59 is a development release and is not used.

### Remaining work

Not yet offered: BigTIFF and maker raw containers (CR2, NEF, ARW and the like), JPEG XL, GIF, video containers, QuickTime, C2PA, reverse geocoding, extended XMP and structured XMP values, preservation of XMP value qualifiers (such an item is refused) and writes
beside an XMP sidecar. Offered for JPEG only: the `thumbnails` category of `removeMetadata`; `minimise` is offered for JPEG, PNG and WebP (not for TIFF, DNG or HEIF). Every other writing operation (`editMetadata`, `removeMetadata`, `correctTime`, `setLocation`, `geotagFromTrack`, `copyMetadata`, `applySidecar`) also writes the other containers (see [containers](#containers-tiff-dng-png-webp-and-heif)).
What is not listed here is not offered; the shipped state is only what this guide describes.


## Metadata editing and removal

`editMetadata` and `removeMetadata` write **new copies** (of the same container as the item) of the items of a media set (the same `media.items` list or `media.folder`
as the read family, JPEG files and, by container, the files described in [containers](#containers-tiff-dng-png-webp-and-heif); no sidecars). An original is captured byte for byte into the run and is never opened for writing,
renamed, linked or overwritten. Each item is written by one genuine ExifTool 13.55 process (its own process group) into a private stage and
is published into the run as `photos/<id>.<canonical extension>` (`.jpg` for a JPEG) only after three independent proofs pass on the written bytes. No ExifTool tag name, option,
configuration, expression or script is ever authored: you name catalogue fields and intent, and the planner chooses the native assignments.

### `editMetadata`

```json
{"version": "schemaxis.exiftool/1", "operation": "editMetadata",
 "media": {"items": [{"id": "ridge", "path": "/photos/ridge.jpg"}]},
 "edits": {"title": {"set": {"text": "Ridge at dawn", "languages": [{"language": "fr", "text": "Crête à l’aube"}]}},
           "creator": {"set": ["Ana Núñez", "李伟"]}, "keywords": {"add": ["alpine"], "remove": ["draft"]}, "rating": {"clear": true}},
 "itemEdits": [{"item": "ridge", "edits": {"description": {"set": "Two hikers.\nSecond line."}}}],
 "policies": {"iptc": "ifPresent", "otherLanguages": "keep", "exifEncoding": "utf8", "companionLoss": "removeCompanion"}}
```

Editable fields: `title`, `description`, `keywords`, `creator`, `copyright`, `rightsUrl`, `rating`, `locationCity`, `locationCountry`. Each
takes exactly one of `set`, `clear` or (keywords only) `add` and `remove`. Capture times, GPS, orientation, dimensions, exposure and device
fields are not editable by `editMetadata` (they are removal-only or preserved; the capture time and the location have their own operations, `correctTime`, `setLocation` and `geotagFromTrack`). `itemEdits` replaces the whole
edit of a named field for one explicit item. Nothing else is written: `edits` and `policies` belong to `editMetadata`, `categories` to
`removeMetadata`, and mixing them is `UNKNOWN_ARGUMENT`.

- **Where a value is written.** XMP is always written. IPTC is written when the file has an IPTC block (`policies.iptc: ifPresent`, the default)
  or always (`always`, which creates a block, declares UTF-8 and refreshes the IPTC digest). EXIF is written only where an Exif segment already
  exists; an Exif segment is never created.
- **Exact text.** Text is Unicode scalar values, never normalised (NFC and NFD stay distinct), trimmed, case-folded, truncated or
  transliterated. Refused: empty or white-space-only values (use `clear`), leading or trailing white space, control characters other than a
  line feed in a description, non-characters and lone surrogates, duplicate list items, duplicate or `x-default` languages.
- **Languages.** A string is the `x-default` text; an object adds other languages. The IPTC and EXIF forms hold the default only. Existing
  languages the edit does not name are kept, removed or refused (`policies.otherLanguages`); `clear` deletes every language and lists them.
  ExifTool may normalise the case of a language tag (`fr-ca` is stored `fr-CA`); readback compares tags case-insensitively and the edit
  never hides it.
- **Creators.** A list: an XMP sequence, repeated IPTC by-lines and the EXIF Artist joined with `"; "` (a name containing `"; "` or starting
  with a quote is quoted, inner quotes doubled). The EXIF Artist is read back with the Metadata Working Group split, and a string that does
  not re-join exactly is reported unreadable. Read operations choose this reading with `creatorInterpretation: "mwg"`; the default
  `literal` keeps the original behaviour and every existing plan hash.
- **Companion losses.** A companion form that cannot hold the value exactly is never truncated: an IPTC byte limit (By-line 32, ObjectName
  64, Keywords 64 each, CopyrightNotice 128, Caption 2000, City 32, Country 64), text when the existing IPTC block has an unknown or unsupported
  character set, non-ASCII EXIF text under `exifEncoding: ascii`, and an EXIF copyright that has an editor part. `companionLoss: removeCompanion`
  (default) deletes that form of that field and reports it per item; `refuse` refuses the item. The XMP value is always complete.
- **IPTC character set.** An existing character set is never reinterpreted: UTF-8 (`1:90`) is declared only when every untouched IPTC text
  is ASCII. Legacy Latin-1 text keeps its bytes and meaning, and the edited field's IPTC form is removed and reported instead. The coded
  character set is shared: ExifTool 13.55 decodes every string dataset below record 7 through it, and the IIM specification applies it to the
  envelope as well, so "untouched text" means any dataset of records 1 to 6 (other than `1:90`) with a byte above 0x7F, not only record 2. Records
  7 to 9 (object data) are never decoded through it. This is conservative: a binary dataset with a high byte also counts, and the cost is an
  IPTC companion that is removed and reported (or the item refused), never a changed meaning. Proof R repeats the check on the output
  (`IPTC_CHARSET_REINTERPRETED`) and compares every untouched dataset byte for byte (`IPTC_NONTARGET_CHANGED`).
- **XMP qualifiers.** A rewritten XMP property whose capture carries qualifiers (attributes on array items, such as `xml:lang` on a keyword, or
  on the property itself) would silently lose them, so the item is refused (`XMP_QUALIFIERS_WOULD_BE_LOST`, with the property and the number of
  qualifiers) instead of being flattened; a qualifier structure makes the value unreadable as a plain list (`EDIT_DESTINATION_UNREADABLE`). `xml:lang` on a
  language alternative is its identity, not a qualifier. Properties the edit does not rewrite keep their qualifiers, and the native diff proves it.
- **Other Exif entries.** Every Exif entry the plan does not name keeps its type, count and value bytes, compared by the independent walker
  (`EXIF_NONTARGET_CHANGED`); IFD pointers and the thumbnail offset move by design and the thumbnail bytes are compared separately. The Interop IFD,
  which the shared walker does not enumerate, is compared by a local parser (`EXIF_NONTARGET_CHANGED`, entry `Interop`). Sub-IFDs (tag `0x014A`) are
  not enumerated: only the native diff proves them. A maker note must be byte-identical. When it changed, the independent proof accepts only a
  relocation of a note that is one plain IFD with TIFF-relative value offsets (the Canon layout): every entry keeps tag, type, count, inline bytes,
  value bytes and relative position, and only its offset fields moved with the note. Bytes that the note's own structure does not reference
  (padding, or a footer that ExifTool 13.55 writes) are not proved unchanged: when they differ the item reports the declared side effect
  `S8-makerNoteRebuilt` with the note's before and after sizes, offsets, and the byte ranges and SHA-256 of those unreferenced regions. Any other
  changed maker note (another layout, a changed entry or referenced value) is refused with `MAKERNOTE_CHANGED`, because this proof cannot show
  that a rebuilt vendor structure kept its meaning; an unrecognised note is copied as an opaque block and offsets inside it that were absolute are
  not adjusted by anyone, which is a limit of every Exif writer.
- **Keywords.** `set` replaces the whole list. `add` and `remove` are resolved against the independently read current list before writing:
  XMP and IPTC must agree (`EDIT_BASE_CONFLICT`), a keyword to remove must be present (`EDIT_ITEM_ABSENT`), a keyword to add must be
  new (`EDIT_ITEM_PRESENT`), and the result may not be empty. The whole list is written back.

### `removeMetadata`

```json
{"version": "schemaxis.exiftool/1", "operation": "removeMetadata",
 "media": {"folder": {"path": "/photos", "extensions": [".jpg"]}}, "categories": ["location", "captureTime", "thumbnails"]}
```

Categories (any combination): `location` (the GPS IFD, XMP `exif:GPS*`, `photoshop` City/State/Country, `Iptc4xmpCore` Location and
CountryCode, the IPTC Extension location structures and IPTC 2:90, 2:92, 2:95, 2:100, 2:101), `captureTime`, `deviceIdentity` (make, model, software,
serial numbers, lens identity and a recognised maker note), `descriptive` (captions, titles, keywords, rating, comments), `rights` (creator,
copyright, credit, source, rights URL) and `thumbnails` (the IFD1 thumbnail and Photoshop thumbnail resources). Native deletions are whole-group
deletes and the group-qualified names of keys the trusted listing of each capture reports; none is authored. Orientation, colour space, ICC profile,
JFIF and Adobe segments are never selected. An unrecognised maker note, an XMP structure ExifTool cannot delete without removing unrelated
properties, and damaged metadata refuse that item (`MAKERNOTE_UNDELETABLE`, `REMOVAL_UNDELETABLE`, `REMOVAL_UNREADABLE`). Minimise deletes a maker note with the whole Exif block.
`residual.json` lists every segment that remains (with hash and role) and the native keys that remain per group. This is removal of the listed
categories in the understood locations: file names, pixel content, unrecognised maker notes, ICC profile contents and embedded content are not
inspected or removed, and nothing is anonymised or certified. Removing rights metadata can remove notices that may be legally required.

#### `minimise`

`"categories": ["minimise"]` (it cannot be combined with another category) writes, for a JPEG, a copy with every EXIF, XMP, IPTC and Photoshop (APP13) block and
every JPEG comment deleted, including the thumbnail, GPS, maker note and device records, while the encoded image, the JFIF, Adobe and ICC segments
stay byte for byte. It is a closed list of known deletions: whole blocks go (`-EXIF:all=`, `-XMP:all=`, `-IPTC:all=`, `-Photoshop:all=`, the comment), never a bare
`-all=`, which a probe against ExifTool 13.55 showed re-chunks the ICC profile and flips the Exif byte order. What decides how the picture is drawn is read independently from the
capture and written back numerically: Exif `Orientation`, `YCbCrPositioning`, `ColorSpace` and an allow-listed `InteropIndex` (`R98`, `R03`, `THM`),
in the capture's own byte order. ExifTool then rebuilds a small Exif block and adds a closed set of mandatory values (resolution values derived from JFIF,
`ExifVersion`, `ComponentsConfiguration`, `InteropVersion`, a `YCbCrPositioning` of 1 when the capture had none); each is a declared, value-aware side effect
proved in the output and in the native diff, and anything else that stays is a fault (`REMOVAL_RESIDUAL`, `MINIMISE_PRESERVED_CHANGED`).

Refused per item: a Gamma tag (`MINIMISE_RENDERING_UNPRESERVED`), a repeated or unknown Orientation, ColorSpace or Interop value
(`MINIMISE_RENDERING_UNPRESERVED`), and an XMP orientation or colour space that disagrees with Exif or has no Exif counterpart, because the XMP block would be deleted
(`RENDERING_REPRESENTATION_CONFLICT`). Unknown application segments (for example vendor APP12) are not deleted: they stay byte for byte and are listed with their hash in
`residual.json`. A capture that is already minimal is copied unchanged (`nothingToRemove`). This is not anonymisation: file names, pixel content, ICC profile
contents and unknown application segments remain, and a viewer that reads a deleted value (a colour space or gamma outside the kept list) may draw differently.

### The three proofs

Every item is recomputed from the retained bytes by `verify`, and a run is verified before it reports success.

1. **R, readback.** Every requested value or absence is read back out of the output with the standard-library readers: the exact text, list
   shape (an XMP sequence for creators, a bag for keywords), language set, absence of cleared forms, source concordance of the field records,
   and unchanged IPTC meaning for datasets and character set the plan does not touch (`READBACK_MISMATCH`, `READBACK_SHAPE_MISMATCH`,
   `CONCORDANCE_MISMATCH`, `IPTC_NONTARGET_CHANGED`, `IPTC_CHARSET_REINTERPRETED`, `EXIF_NONTARGET_CHANGED`, `MAKERNOTE_CHANGED`, `REMOVAL_RESIDUAL`, `MINIMISE_PRESERVED_CHANGED`).
2. **P, preservation.** The bytes from the first scan header to the end (every entropy-coded scan, restart marker, table between scans and the end
   marker), the frame header and coding tables, the JFIF, Adobe and ICC segments and every other non-metadata segment are byte-identical to the
   capture; Exif, XMP and Photoshop segments may differ only as the plan declares, and an embedded thumbnail keeps its bytes
   (`IMAGE_DATA_CHANGED`, `RENDERING_SEGMENT_CHANGED`, `SEGMENT_CHANGED`, `UNDECLARED_SEGMENT_CHANGE`, `THUMBNAIL_CHANGED`). Progressive and multi-scan
   JPEGs are admitted; the walker never mistakes `FF00`, restart markers or fill bytes inside scan data for segments. This is a statement about
   bytes: no decoder runs, and it says nothing about pixels, rendering in any program, authenticity or provenance.
3. **N, native diff.** Fresh ExifTool listings of capture and output, compared key by key (group and tag, copy numbers ignored), differ only
   at the plan's targets and at a closed set of value-aware side effects: the XMP toolkit string when XMP was written, IPTC record versions and
   the character set when the plan assigns them, the IPTC digest equal to the MD5 of the new IPTC block, and the thumbnail offset when the
   thumbnail bytes are unchanged. Anything else is `NATIVE_UNEXPLAINED_CHANGE`; there is no ignored namespace. A listing from the same engine
   that wrote the file is reproducibility evidence, not independent truth, which is why R and P do not depend on it.

Faults in the input or the write are per item: `WRITE_TRAILER_UNSUPPORTED`, `WRITE_TAIL_SEGMENT_UNSUPPORTED`, `JPEG_RESTART_SEQUENCE_INVALID`,
`UNSUPPORTED_JPEG_PROCESS`, `XMP_EXTENDED_UNSUPPORTED`, `JPEG_MPF_UNSUPPORTED`, `WRITE_SIDECAR_PRESENT`, `WRITE_INPUT_NATIVE_WARNING`,
`NATIVE_WRITE_FAILED` and `NATIVE_WRITE_WARNING` (any ExifTool stderr is a fault: no truncation or repair is accepted).

### Publications and stable artifact slots

`photos/<id>.jpg`, `manifest.json`, `edit-plan.json` (the native assignments each item receives, decided before any write) and
`edit-report.json` (or `removal-plan.json`, `removal-report.json` and `residual.json`), plus `outcomes/<id>.json` for each item that was not
written. The receipt lists one artifact slot per item in manifest order first: the published JPEG (`kind: image`, identity
`{format: jpeg, item: <id>}`) or, for a refused or failed item, its truthful outcome document (`kind: text`, never an image). The report
documents follow. With items A (written), B (refused), C (written), slot 0 is A's image, slot 1 is B's outcome and slot 2 is C's image: binding
slot 1 to an image consumer fails (the route accepts image and text artifacts, so the consumer refuses the outcome path with `INVALID_PHOTO_SOURCE` at the bound location) and can never silently select C. A static index means the i-th item of the manifest at
that run, not a permanent identity: a changed folder membership re-runs the producer and its consumers. If no item is written the run fails with
`NO_USABLE_ITEMS` and publishes no image. A produced image can feed `inspectMetadata` or `auditMetadata` through a workflow
`{"$artifact": "<operation id>", "index": N}` binding, which is rechecked against the producer's verified receipt.

### Verification

`verify` re-reads authored input, rebuilds the plan, recomputes the three proofs from the retained captures and published or rejected bytes,
rebuilds every publication and compares it byte for byte, and with a configured trusted ExifTool 13.55 replays the native listings and each
write (the write must reproduce the retained output byte for byte). Without that runtime it fails closed with `NATIVE_REPLAY_UNAVAILABLE`
(the readback and preservation proofs are consistent, proof N is not verified). A coherent rewrite of every retained record verifies as consistency,
not authenticity.



## Containers: TIFF, DNG, PNG, WebP and HEIF

Every operation accepts more than JPEG: the read family, the E2 writes, the E3 time and location writes and the E4 transfer, sidecar and naming operations. Container support is **data** (`src/schemaxis/adaptors/exiftool/containerprofiles.json`, pinned by digest) and **code**
(one bounded locator per container family under `e5*.py`); the existing shared EXIF, XMP and IPTC decoders read every payload, so no format has a private metadata reader.
Detection is by signature, never by suffix (`EXTENSION_MISMATCH` is a note); the default folder scope stays `.jpg`, `.jpeg` and `.xmp`, and the other suffixes are listed explicitly.
The profiles list nothing that is not tested; nothing here decodes a pixel, and nothing says a file is authentic.

| Container | Read (inspect, audit, compare, reconcileTime, locate) | `editMetadata` | `removeMetadata` | `minimise`, `thumbnails` | Time, location, copy writes (`correctTime`, `setLocation`, `geotagFromTrack`, `copyMetadata`, `applySidecar`) |
|---|---|---|---|---|---|
| JPEG | yes | yes | yes | yes | yes |
| TIFF (classic, II or MM; strips or tiles; any compression code) | yes | yes | location, captureTime, descriptive, rights, deviceIdentity | refused (`MINIMISE_UNSUPPORTED_CONTAINER`, `REMOVAL_CATEGORY_UNSUPPORTED_IN_CONTAINER`) | yes |
| DNG (TIFF with `DNGVersion`) | yes | yes | same; MakerNote and DNGPrivateData are kept (residual `makerNoteMayIdentifyDevice`) | refused | yes |
| PNG (including APNG) | yes | yes (XMP and eXIf) | location, captureTime, descriptive, rights, deviceIdentity | `minimise` yes (AM-17 keep-set), `thumbnails` refused | yes |
| WebP (simple, extended, animated) | yes | yes (XMP and EXIF; VP8X predicted and proved) | same as PNG | `minimise` yes (a VP8X is removed or kept exactly as predicted and proved), `thumbnails` refused | yes |
| HEIF/HEIC/AVIF (brands heic, heix, mif1, avif) | yes (bounded ISO BMFF) | **existing Exif and XMP items only** | refused (`HEIF_REMOVAL_UNSUPPORTED`) | refused (`HEIF_REMOVAL_UNSUPPORTED`) | **existing Exif and XMP items only** |
| BigTIFF, maker raw (CR2, NEF, ARW), JPEG XL, GIF | refused per item (`TIFF_BIG_UNSUPPORTED`, `RAW_FORMAT_UNSUPPORTED`, `UNSUPPORTED_MEDIA`) | | | | |

### Field by family by container (`editMetadata`)

Every field always has its XMP form where the container has an XMP slot. `*` marks a destination that is written only when its slot already exists (a JPEG Exif segment or IPTC block, a PNG `eXIf`
chunk, a WebP `EXIF` chunk, a HEIF Exif or XMP item, a TIFF IPTC block). `-IPTC` means the container has no IPTC destination, so the IPTC companion is a declared loss
(`iptcNotAvailableInContainer`), never a native warning.

| Field | JPEG | TIFF | DNG | PNG | WebP | HEIF |
|---|---|---|---|---|---|---|
| `title` | XMP, IPTC* | XMP, IPTC* | XMP, IPTC* | XMP, -IPTC | XMP, -IPTC | XMP*, -IPTC |
| `description` | XMP, EXIF*, IPTC* | XMP, EXIF, IPTC* | XMP, EXIF, IPTC* | XMP, EXIF*, -IPTC | XMP, EXIF*, -IPTC | XMP*, EXIF*, -IPTC |
| `keywords` | XMP, IPTC* | XMP, IPTC* | XMP, IPTC* | XMP, -IPTC | XMP, -IPTC | XMP*, -IPTC |
| `creator` | XMP, EXIF*, IPTC* | XMP, EXIF, IPTC* | XMP, EXIF, IPTC* | XMP, EXIF*, -IPTC | XMP, EXIF*, -IPTC | XMP*, EXIF*, -IPTC |
| `copyright` | XMP, EXIF*, IPTC* | XMP, EXIF, IPTC* | XMP, EXIF, IPTC* | XMP, EXIF*, -IPTC | XMP, EXIF*, -IPTC | XMP*, EXIF*, -IPTC |
| `rightsUrl` | XMP | XMP | XMP | XMP | XMP | XMP* |
| `rating` | XMP | XMP | XMP | XMP | XMP | XMP* |
| `locationCity` | XMP, IPTC* | XMP, IPTC* | XMP, IPTC* | XMP, -IPTC | XMP, -IPTC | XMP*, -IPTC |
| `locationCountry` | XMP, IPTC* | XMP, IPTC* | XMP, IPTC* | XMP, -IPTC | XMP, -IPTC | XMP*, -IPTC |

### Time, location and transfer over the containers

`correctTime`, `setLocation`, `geotagFromTrack`, `copyMetadata` and `applySidecar` write TIFF, DNG, PNG, WebP and HEIF items through the **same** planners, copy writer and proofs as JPEG items: there is no second writer and
no native passthrough. A time correction rewrites every present EXIF, XMP and (TIFF and DNG only) IPTC source of the chosen time fields with the exact arithmetic, clock-plan consistency, offset and fraction rules of the
JPEG route; a position is written as exact decimals into the GPS IFD and the XMP position properties with the typed altitude rules (reference byte, edition, quantisation bound); a transfer carries typed values
between any two admitted items, a JPEG photograph or a container item being a source or a destination, and is proved by the independent T-host and T-native checks. Each written file is proved by independent
read-back (R), the offset-free container fingerprint (P: strips, tiles, chunks and items may move, no protected byte may change) and the closed native before/after diff (N), with metadata-first verification and a
fresh native replay. A destination without an IPTC slot (PNG, WebP, HEIF) declares the loss `iptcNotAvailableInContainer` instead of creating a carrier.

Where a container needs a carrier that does not exist, the write is refused per item, before any native process, rather than invented: a HEIF file never gets a new Exif or XMP item
(`HEIF_METADATA_ITEM_CREATION_UNSUPPORTED`, a conservative, named limit of ExifTool 13.55 on hand-built fixtures: creating items was not reproducible over 20 runs; items that exist are edited and proved normally),
and an IPTC change is refused when the Photoshop resource block ends in opaque bytes (`IPTC_RESOURCE_TAIL_UNSUPPORTED`), when a TIFF carries an IPTC digest that native cannot refresh
(`TIFF_IPTC_DIGEST_UNSUPPORTED`), or when the IPTC of a TIFF lives in a Photoshop resource block (`TIFF_PHOTOSHOP_IPTC_CARRIER_UNSUPPORTED`).

A maker note whose bytes changed because ExifTool moved it is compared by the independent relocation-aware check (a plain IFD whose entries keep tag, type, count, value bytes and relative position; only its own
offset fields move by one delta); a rebuilt note that this check cannot show equal fails with `MAKERNOTE_CHANGED`, so a TIFF or DNG write is never reported verified on an unproven maker note. A kept maker note is
published as the residual `makerNoteMayIdentifyDevice` for every container that holds one.

### Minimise of PNG and WebP (AM-17)

`minimise` (AM-17 semantics, AM-19 method) resets the Exif block with `-EXIF:all=` (only when it holds more than the kept values) and the XMP block with `-XMP:all=`, deletes every PNG text chunk by its `PNG:<Keyword>` key,
never uses `-all=` or `-PNG:all=`, and then writes back only the rendering values of the E2 keep-set that exist, as numeric assignments with the capture's `-ExifByteOrder=` (for example `-IFD0:Orientation#=6`): Orientation,
YCbCrPositioning, ColorSpace and the Interop index. The independent closed residual proof, the native closed diff and the byte-level protection of gamma, colour profile, alpha, animation and image data are unchanged and authoritative. PNG keeps `gAMA`, `iCCP`, `tIME` (residual `pngModificationTimeKept`), every other ancillary chunk and the image data byte for byte; WebP keeps the bitstream, ICC, alpha and
animation chunks byte for byte, and a VP8X is removed or kept with recomputed flags exactly as predicted from the layout (a layout the native writer would leave inconsistent is refused at plan with
`WEBP_METADATA_REMOVAL_LAYOUT_UNSUPPORTED`; the proof of the written file stays authoritative). `MINIMISE_RENDERING_UNPRESERVED` is raised only when a keep-set value is repeated, outside its understood values
or has a conflicting XMP form. PNG-3 calls `eXIf` a historical value, so a kept Orientation is preserved for viewers that honour it, not required by PNG. TIFF and DNG `minimise` (`MINIMISE_UNSUPPORTED_CONTAINER`) and
HEIF removal and minimise (`HEIF_REMOVAL_UNSUPPORTED`) are intended named limits.

### Size bounds

The bound of one item is 256 MiB for a TIFF or DNG suffix and 64 MiB for every other name, applied by name at the stat check, the bounded read, capture, the launcher input check, the output and replay reads and the
stream hash, and again by signature in the locator (a `.tif` that is a 100 MiB PNG is refused `PHOTO_RESOURCE_LIMIT`). The number of items, the total byte budget and the folder depth are unchanged. A 65 MiB TIFF edit
and the 64 MiB boundaries run natively in the test suite. The plan's published `budget` states the bound that applies: `maxItemBytes` (64 MiB) is the bound of every name that is not a large suffix, and a plan whose media can hold
a TIFF or DNG name (an explicit item path or a listed folder extension ending in `.tif`, `.tiff` or `.dng`) adds `maxLargeItemBytes` (256 MiB) and `largeItemSuffixes`. A JPEG-only plan carries neither key, so its budget and plan hash
are unchanged. In a mixed set the bound of each item is decided by its own name, and the native process limit follows the largest bound among the inputs it names.

### What is proved, and by what

Proof **P** (preservation) is the same statement for every container: an offset-free fingerprint of everything that is not an editable metadata slot, so a strip, tile, chunk or item may
move but no protected byte may change, appear, vanish or be reordered. For TIFF and DNG that is every IFD entry (value bytes, never an offset), every strip and tile as its own row, every
sub-IFD, preview and colour tag, DNGPrivateData, and every Photoshop resource other than IPTC and its digest; for PNG every chunk other than the metadata slots, with CRC; for WebP every non-metadata
chunk with its pad byte, and the VP8X by the AM-16R layout proof; for HEIF every non-metadata item payload, the `iprp` property boxes and every other box. Proof **R** reads each requested
value or absence back with the shared independent readers. Proof **N** compares two fresh ExifTool listings and allows only the plan's targets and closed, value-aware side effects
(relocated strip offsets, a rebuilt HEIF media-data box, a created or removed VP8X, a removed Exif block). Native 13.55 is the writer; the independent readers and the fingerprint are the
judges, and a native capability never replaces them.

### Named limits and native capability gaps (published, tested)

- **HEIF metadata item creation (native gap).** Over 20 runs per kind with 13.55, creating an Exif or XMP item in a HEIC that has none gave `Chunk offset in iloc atom is outside media data`
  (no output) in 9 runs and a correct file in the others (random Perl hash seeds); a fixed-seed rerun (seeds 0 to 19) gave 18 of 20 failures for each of those two kinds, and every combined Exif and XMP creation produced a wrong file. An edit that would create an item is therefore refused,
  `HEIF_METADATA_ITEM_CREATION_UNSUPPORTED` (limitation `heifNativeMetadataCreationNotReproducible`); editing items that exist is deterministic (20 of 20 identical) and proved normally. This
  is a statement about 13.55 and hand-built fixtures, not about every HEIF file or version.
- **HEIF empty metadata item.** A `clear` that would leave an existing Exif or XMP item with no metadata at all (the last XMP property, or the last Exif entry) is refused before any native process,
  `HEIF_EMPTY_METADATA_ITEM` (limitation `heifEmptyMetadataItemNotWritable`): native 13.55 writes a zero-length extent, which ISO BMFF reads as the rest of the container. The same shared guard judges
  every plan that deletes (edit and transfer); a clear that leaves another property or entry, and any write into the item, are ordinary.
- **HEIF removal** is refused (`HEIF_REMOVAL_UNSUPPORTED`): native `all=` leaves the Exif and XMP items with extent length 0, which ISO BMFF reads as the rest of the file. The HEIF contract rests on
  the public MPEG drafts and COR1 (limitation `heifSpecDraftOnly`), not on the purchased standard.
- **TIFF IPTC.** Native stores IPTC in tag 0x83BB as a zero-padded LONG array, so it cannot refresh the digest it warns about: no digest is assigned and a TIFF that carries one is refused for IPTC
  changes (`TIFF_IPTC_DIGEST_UNSUPPORTED`). IPTC inside a Photoshop resource block (tag 0x8649) is read but not written: native would add a second carrier (`TIFF_PHOTOSHOP_IPTC_CARRIER_UNSUPPORTED`).
- **Opaque Photoshop resource tail.** A remainder after the last resource that is shorter than a resource header is ignored by the shared reader and dropped by native when the block is rewritten.
  A TIFF or DNG carrying one is refused for writing, and a JPEG is refused for every plan that would rebuild its IPTC (`IPTC_RESOURCE_TAIL_UNSUPPORTED`): an edit, a time correction, a copy of metadata and an applied
  sidecar all meet the same shared guard before any native process. A JPEG plan that leaves its IPTC alone keeps the block and its tail byte for byte. Before this was found, such a JPEG edit, correction or copy was published as verified.
- **TIFF unknown tags.** `tiffUnknownTagSemanticsNotInterpreted`: unrecognised tags are preserved as raw bytes and never interpreted; a file whose unrecognised tag could point at bytes the walker does not
  account for is refused (`TIFF_UNKNOWN_OFFSET_SUSPECT`, `TIFF_UNKNOWN_IFD_POINTER`, `TIFF_OFFSET_TAG_UNSUPPORTED`). The recognised tag set is deliberately conservative (`tiffRecognisedTagSetConservative`).
- **Sizes.** 256 MiB per item for a TIFF or DNG name and 64 MiB for every other name (see [size bounds](#size-bounds)); the number of items, the total byte budget and the folder depth are unchanged.
- **Named limits that remain.** TIFF and DNG `minimise` and `thumbnails` outside JPEG, HEIF removal and minimise, creating a HEIF Exif or XMP item (named capability gap of ExifTool 13.55 on the tested fixtures; items that exist are edited), the relocation-aware maker-note comparison only for a plain IFD note (any other changed note fails closed), and the draft-level HEIF contract (`heifSpecDraftOnly`).
- Not offered: BigTIFF, maker raw formats, RF64, JPEG XL, GIF, video containers.

Refusal codes by container (each is declared in the pinned profile and named in at least one test; a foundation test checks that every code a locator can raise is declared, and a changed DNG private block is reported as `PRESERVATION_MISMATCH`):

| Container | Codes |
|---|---|
| TIFF | `TIFF_BIG_UNSUPPORTED`, `TIFF_LAYOUT_OVERLAP`, `TIFF_IMAGE_EXTENT_INVALID`, `TIFF_IFD_BUDGET`, `TIFF_TYPE_UNSUPPORTED`, `TIFF_UNKNOWN_IFD_POINTER`, `TIFF_UNKNOWN_OFFSET_SUSPECT`, `TIFF_OFFSET_TAG_UNSUPPORTED`, `TIFF_DUPLICATE_METADATA_TAG`, `INVALID_EXIF_STRUCTURE`, `RAW_FORMAT_UNSUPPORTED`, `IPTC_RESOURCE_TAIL_UNSUPPORTED`, `TIFF_PHOTOSHOP_IPTC_CARRIER_UNSUPPORTED`, `TIFF_IPTC_DIGEST_UNSUPPORTED` |
| DNG | `TIFF_BIG_UNSUPPORTED`, `TIFF_LAYOUT_OVERLAP`, `TIFF_IMAGE_EXTENT_INVALID`, `TIFF_IFD_BUDGET`, `TIFF_TYPE_UNSUPPORTED`, `TIFF_UNKNOWN_IFD_POINTER`, `TIFF_UNKNOWN_OFFSET_SUSPECT`, `TIFF_OFFSET_TAG_UNSUPPORTED`, `RAW_FORMAT_UNSUPPORTED`, `IPTC_RESOURCE_TAIL_UNSUPPORTED`, `TIFF_PHOTOSHOP_IPTC_CARRIER_UNSUPPORTED`, `TIFF_IPTC_DIGEST_UNSUPPORTED` |
| PNG | `PNG_CRC_INVALID`, `PNG_TRAILING_BYTES`, `PNG_METADATA_AFTER_IDAT`, `PNG_LEGACY_RAW_PROFILE`, `PNG_DUPLICATE_CHUNK`, `PNG_CHUNK_ORDER_INVALID`, `XMP_BOUND` |
| WebP | `RIFF_SIZE_MISMATCH`, `RIFF_TRAILING_BYTES`, `RIFF_PADDING_INVALID`, `WEBP_EXIF_PREFIX_UNSUPPORTED`, `WEBP_DUPLICATE_METADATA_CHUNK`, `WEBP_CANVAS_MISMATCH`, `WEBP_LAYOUT_UNSUPPORTED`, `WEBP_BITSTREAM_HEADER_SHORT`, `WEBP_METADATA_REMOVAL_LAYOUT_UNSUPPORTED`, `WEBP_LAYOUT_INVALID_AFTER_WRITE`, `WEBP_FLAGS_INCONSISTENT` |
| HEIF | `HEIF_BOUND`, `HEIF_IMPLIED_EXTENT`, `HEIF_EXTENT_OVERLAP`, `HEIF_MULTIPLE_METADATA_ITEMS`, `HEIF_SHARED_METADATA_ITEM`, `HEIF_REFERENCE_INVALID`, `HEIF_PROTECTED_ITEM`, `HEIF_EXTERNAL_DATA`, `HEIF_ITEM_CONSTRUCTION_UNSUPPORTED`, `HEIF_EXIF_HEADER_INVALID`, `HEIF_REMOVAL_UNSUPPORTED`, `HEIF_METADATA_ITEM_CREATION_UNSUPPORTED`, `HEIF_EMPTY_METADATA_ITEM` |


## Time and location workflows

Five operations take the same `media.items` list or `media.folder` as the rest of the family and work on capture clocks and recorded positions:
`reconcileTime` and `locate` only read and report (`time-report.json` with `time-report.csv`, and `location-report.json` with `location.csv`), and `correctTime`,
`setLocation` and `geotagFromTrack` write **new copies of the same container** through the same copy writer, three proofs, stable artifact slots, reuse and invalidation as
[editing and removal](#metadata-editing-and-removal). An original is never modified. No ExifTool tag name, option, configuration, shift or geotag
expression is authored: you declare domain intent (devices, true times, offsets, positions, tracks), Schemaxis computes every new value with exact
arithmetic, and each item receives only fixed numeric assignments that are published in the plan before the write. Everything you declare (a reference
true time, an assumed offset, an assumed-correct group, a position, a vertical reference, a track datum) is published as declared and is never verified.
There is no time zone, daylight-saving rule, leap second, vertical datum conversion, reverse geocoding or place lookup anywhere in these operations.

### `reconcileTime` and `locate`

```json
{"version": "schemaxis.exiftool/1", "operation": "reconcileTime",
 "media": {"items": [{"id": "a1", "path": "/photos/a1.jpg"}, {"id": "b1", "path": "/photos/b1.jpg"}, {"id": "b2", "path": "/photos/b2.jpg"}]},
 "references": [{"item": "a1", "trueUtc": "2026-03-01T11:00:00Z"}, {"item": "b1", "trueLocal": "2026-03-01T12:00:00", "trueOffset": "+01:00"}],
 "simultaneous": [{"items": ["a1", "b1"], "toleranceSeconds": "1"}],
 "model": "constant"}
```

Photos are grouped by the exact recorded make, model and body serial text (or by `groups.members` you declare, with `itemOverrides` for single photos); a missing
or ambiguous identity is reported, never merged or guessed. A group's skew is *recorded minus true*, in exact decimal seconds (a trailing `~` marks a repeating
decimal cut at nine places), derived only from the references you list: a group with none stays `insufficient`, `assumeCorrect` takes the skew as zero by declaration
(refused when a reference contradicts it, `ASSUMPTION_CONTRADICTED`), and references that disagree beyond `toleranceSeconds` make the group `GROUP_CONFLICTING`
with every residual listed. The `linearDrift` model fits a skew that grows linearly between references at least 60 seconds apart, evaluates it at each photo's own
instant and refuses a rate above `maxDriftRate` (`DRIFT_IMPLAUSIBLE`) or an extension outside the reference span beyond `maxDriftExtrapolationSeconds`. A UTC instant
exists only where the same file records an offset or you assumed one (labelled assumed); a recorded but unreadable offset is not treated as absent
(`TIME_SOURCE_UNREADABLE`). GPS time stamps are independent evidence compared with the proposed time within `gpsToleranceSeconds` and never estimate a skew.
A skew belongs to an instant: an item with no recorded or assumed offset has only a constant wall-clock skew where a `trueLocal` reference gives one,
and none under `linearDrift`, so `correctTime` refuses it with `OFFSET_UNKNOWN` exactly where the report proposes nothing. A group that a simultaneity path anchors is
`conflicting` (`REFERENCE_CONTRADICTED`, with every residual) when its own declared references contradict the path.
Nothing is written.

`locate` reports `latitude` and `longitude` as exact signed decimals summed from the stored rationals (seconds of exactly 60 are an exact non-canonical form), the
recorded datum text, the XMP/EXIF disagreement flags and the typed height: its state, exact metres, the reference (`ellipsoidal`, `seaLevel` or `unspecified`),
and the edition evidence. Exif 3.x files record altitude references 0 and 1 (ellipsoidal) and 2 and 3 (sea level); a GPS-only block of version 2.4 is
labelled as inferred; a legacy 0 or 1 is `unspecified`, never converted. A repeated or damaged `ExifVersion` or `GPSVersionID` is unresolved evidence, not an
absent one. `compareTo` adds an approximate great-circle distance on a sphere of mean radius 6371008.8 m, only when the recorded datum matches the declared one.
The stored precision is a serialisation property, not GPS accuracy.

### `correctTime`

```json
{"version": "schemaxis.exiftool/1", "operation": "correctTime",
 "media": {"folder": {"path": "/photos/day1", "extensions": [".jpg"], "depth": 1}},
 "references": [{"item": "a1", "trueUtc": "2026-03-01T11:00:00Z"}],
 "corrections": [{"group": "dev1", "from": "references"}, {"group": "dev2", "shift": {"hours": 1}}, {"group": "dev3", "setOffset": {"offset": "+01:00", "keep": "instant"}}],
 "timeFields": ["captured", "digitized"], "policies": {"sourceConflicts": "refuse", "subSecond": "addIfNeeded", "uncorrectedItems": "copyUnchanged"}}
```

Each correction is exactly one group's change: a `shift` (days, hours, minutes and exact decimal seconds), a skew derived `from: references` (the model, tolerance and
drift options of `reconcileTime` apply), or a `setOffset` that keeps the instant (the wall clock changes) or the wall clock (the instant changes). Every present time
source of the selected `timeFields` (`captured` and `digitized` by default; `modified` is opt-in because it records an edit) moves together: EXIF `DateTimeOriginal`
or `CreateDate` with their sub-second and offset tags, the XMP forms, and IPTC date and time. Disagreeing sources are refused (`TIME_SOURCES_CONFLICT`) or resolved from
the family you name (`preferFamily`); a sub-second the shifted time needs is added or refused (`TIME_SUBSECOND_REQUIRED`); IPTC cannot hold a fraction, so it is
truncated toward the earlier second and listed per item. A result outside the supported calendar is that item's `TIME_OUT_OF_RANGE`. A photo outside every
correction, or already at the corrected value (`CORRECTION_ALREADY_APPLIED` for an already-applied plan), is copied unchanged or gets an outcome document
(`uncorrectedItems: refuseSlot`) and keeps its slot. GPS time stamps are the receiver's clock and are never shifted. Publications are `time-correction-plan.json`,
`time-report.json` (JSON only; the CSV belongs to `reconcileTime`), `write-report.json`, `residual.json` and `manifest.json`.

### `setLocation`

```json
{"version": "schemaxis.exiftool/1", "operation": "setLocation",
 "media": {"items": [{"id": "ridge", "path": "/photos/ridge.jpg"}]},
 "positions": [{"item": "ridge", "latitude": "45.5", "longitude": "-122.25", "altitude": {"meters": "123.4", "reference": "seaLevel"}, "datum": "WGS-84"}],
 "policies": {"staleCompanions": "remove", "xmp": "ifPresent", "createExif": "allow", "altitudeNotExpressible": "refuse", "removeDirection": true}}
```

Coordinates are written from the exact declared decimal as seconds rationals; the independent readback must reproduce the decimal within 2e-10 degrees (a storage
bound, not accuracy), exact zero stays exact zero and the XMP text is the declared decimal. The hemisphere reference is written explicitly and a negative zero is
normalised and reported. An altitude is written only with the reference you declare and only where the file's metadata edition can express it: a sea-level
reference (2 or 3) is written in any edition, labelled as one that legacy readers may not recognise outside Exif 3.x; an ellipsoidal reference (0 or 1) is
written in an Exif 3.x file, in a GPS-only 2.4 file, or into a GPS block that this operation creates in a file without `ExifVersion` (labelled as established by the GPS version only).
An ellipsoidal height in an existing GPS block of a legacy or undeclared edition, or of an edition whose `ExifVersion` or `GPSVersionID` cannot be resolved, refuses the item
(`ALTITUDE_REFERENCE_NOT_EXPRESSIBLE`) or, with `omitAltitude`, writes the position alone and says so. No `ExifVersion` is ever promoted or demoted. Because ExifTool adds `ExifVersion`, `ComponentsConfiguration` and `ColorSpace` when a write creates an Exif directory, and that changes how a GPS-only 2.4
height is read although its bytes are unchanged, every write is checked by a typed height-preservation proof (`ALTITUDE_MEANING_CHANGED`) and creating an Exif directory
under an untouched height is refused (`EXIF_CREATION_UNVERIFIED`). Stale GPS companions (direction, speed, time stamps, other XMP position properties) are removed or kept as
declared, and every removal is planned before the write. Place names (IPTC city, region, country, XMP location) are not updated. Publications are `location-plan.json`,
`write-report.json`, `residual.json` and `manifest.json`.

### `geotagFromTrack`

```json
{"version": "schemaxis.exiftool/1", "operation": "geotagFromTrack",
 "media": {"items": [{"id": "ridge", "path": "/photos/ridge.jpg"}]},
 "tracks": [{"id": "walk", "path": "/tracks/walk.gpx"}],
 "photoTime": {"clockCorrection": {"shifts": [{"group": "dev1", "shift": {"hours": 1}}]}},
 "interpolation": {"maxGapSeconds": 120, "endpointSnapSeconds": 0, "overlapAgreementMeters": "5"},
 "track": {"invalidPoints": "refuse", "zonelessTimes": "asSchema", "elevation": "ignore"},
 "policies": {"gpsStamp": "photoInstant", "uncorrectedItems": "copyUnchanged"}}
```

Each GPX file (1 to 8 files, at most 32 MiB each and 64 MiB in total) is captured byte for byte, checked for a DTD, entity or external reference (`TRACK_DTD_REFUSED`) before any parser
runs, and read with a bounded parser (depth, element, point and text limits; `TRACK_RESOURCE_LIMIT`). The photo instant is the recorded capture wall time minus the recorded
(or assumed) offset, moved by the declared `clockCorrection` (group shifts, or the plan file of a `correctTime` run); the photo's own time fields are not rewritten. A
`correctTime` plan moves the instant by the change between its own before and after states of the captured time, so an offset set keeping the instant moves nothing and one
keeping the wall clock moves the instant. Before it is used, each plan entry is recomputed from the plan's own recorded inputs (its declared correction, assumed offsets, time
fields and policies) and this capture, with the planner that produced it, and compared with what the plan records: the before and after local time, offset and fraction, every
target component, every native assignment in its own family's serialisation (EXIF, XMP, IPTC, sub-second) and the delta must all be the ones the planner produces, otherwise
the item is refused with `PLAN_INCONSISTENT` and nothing is placed. A `from: references` correction takes its wall-clock move from the plan, because the media set that derived the skew
is not available to a geotag run; that move must match the recorded skew and everything else is still recomputed. This establishes that the plan is internally consistent and
reproducible from its recorded inputs, not that it is authentic or that the references behind a skew are right: the plan's device-group label is trusted together with its references skew. An item the plan could not correct (a refused entry, or an unchanged
one other than a zero net change or no correction for its group) is refused with `CLOCK_CORRECTION_UNAVAILABLE` instead of being placed on its uncorrected instant. A recorded offset
that cannot be resolved (`TIME_SOURCE_UNREADABLE`) is never replaced by an assumed one; only a truly absent offset is assumed. When a photograph records no offset and none is assumed, a
plan that sets an offset (`setOffset` keeping the wall clock) still places it: the plan's after state, its wall clock and the offset it sets, fixes the corrected instant (basis
`plannedOffset`), with no before instant, offset or time zone invented, so its `clockCorrectionNanoseconds` is `null` (the amount is unknown) and the placement equals that of the
corrected file. A plan that only shifts the clock of such a photograph still has no offset to place it on (`OFFSET_UNKNOWN`). The basis of every photo instant is published as
`recordedOffset`, `assumedOffset` or `plannedOffset`. A geotag plan pins its track files and its clock-correction plan by SHA-256 (`TRACK_HASH_MISMATCH`, `CLOCK_PLAN_HASH_MISMATCH`).
A photo falling on a fix takes it exactly; between two fixes of one segment it is placed by great-circle interpolation (slerp), at most `maxGapSeconds` apart; within
`endpointSnapSeconds` of a segment end it may snap to the endpoint; elsewhere it is unplaced (`TRACK_NOT_COVERED`) with the reason. Nothing is extrapolated and segments, tracks
and gaps are never bridged. Where tracks overlap, every pair of candidate positions must agree within `overlapAgreementMeters` or the photo is refused
(`TRACK_OVERLAP_CONFLICT`). An elevation is used only with the vertical reference you declare (`track.elevation`). WGS-84 is assumed for GPX 1.1 only; a GPX 1.0 datum must be
declared (`track.datum1_0`). Any other proof failure includes `INTERPOLATION_MISMATCH`, where the independent recomputation of the placement differs from what was written. The native
geotag feature is not used and not compared. Publications are `track-report.json`, `geotag-plan.json`, `write-report.json`, `residual.json` and `manifest.json`.

### Plans, stable slots, reuse and verification

`apply: plan` publishes the plan (`time-correction-plan.json`, `location-plan.json` or `geotag-plan.json`) and the reports without writing a copy; a later run with `plan`
set to that file applies exactly it. The plan carries every other input, so it is refused if combined with them, if it was edited (`PLAN_INCONSISTENT`), if its catalogue is
unknown (`PLAN_CATALOGUE_UNKNOWN`) or if a capture changed since (`PLAN_STALE`). Every item keeps its artifact slot: a published JPEG or a truthful outcome document, and
a slot that no longer holds the item's image is `SLOT_SHIFTED`; if no item is written the run fails with `NO_USABLE_ITEMS`. Reuse is keyed by the captured bytes of every photo, the GPX
files, the plan files and the folder membership, so changed track bytes, a changed reference or a changed plan invalidates reuse while a changed modification time
alone does not. `verify` rebuilds the plan, recomputes the three proofs from the retained captures, recomputes each interpolation independently and, with a configured trusted
ExifTool 13.55, replays every write byte for byte. A coherent rewrite of every retained record verifies as consistency, not authenticity.

The three proofs apply as in editing: **R** reads back every written time, position, reference and absence with the standard-library readers and decodes the stored rationals
(`READBACK_MISMATCH`, `READBACK_NOT_CONCORDANT`, `UNREQUESTED_METADATA_CHANGED`, `EXIF_NONTARGET_CHANGED`, `ALTITUDE_MEANING_CHANGED`); **P** shows the image data and every
non-metadata segment byte-identical; **N** compares fresh native listings and allows only the plan targets and a closed set of declared side effects. Residual limits
(`residual.json`) list what is not interpreted: maker-note, preview and thumbnail Exif, XMP edit-history, sidecar and file-system times and positions, IPTC place names.

### Limits of the time and location workflows

- The tracks and the camera clocks decide where and when: a wrong camera clock or a track from another device gives a wrong position, and no accuracy, confidence or error
  radius is claimed for an interpolated place.
- Positions and times you declare are not verified; a corrected or placed photo is not certified, and nothing here is privacy certification.
- Legacy readers older than Exif 3.0 print altitude references 0 and 1 as above or below sea level and may not recognise the sea-level references 2 and 3. A sidecar altitude is written only by `exportSidecar`, and the transfer of
  an exposure between copies is `copyMetadata` (see the copy, sidecar and naming workflows).
- Copies of the item's own container (JPEG, TIFF, DNG, PNG, WebP, HEIF with existing items); these operations write no XMP sidecar (`exportSidecar` does), and offer no QuickTime or RAW time and location and no GPX 1.0 datum assumption.

## Copy, sidecar and naming workflows

Five operations carry, export and organise the typed metadata of JPEG photos without rewriting any original. They take the same `media` envelope as every other operation
(an explicit list of up to 512 JPEG items or one folder) and use the same capture, independent readers and fixed native listing; the catalogue versions, native tag names and
sidecar property names are internal and automatic. Nothing here accepts an ExifTool tag name, option, configuration, expression or template.

| Operation | What it does | Output |
|---|---|---|
| `copyMetadata` | carries selected kinds of information from a source onto copies of destination photos | new copies of the destination's own container (stable slots) |
| `applySidecar` | applies the information in each photo's XMP sidecar to a copy of the photo | new copies of the destination's own container (stable slots) |
| `exportSidecar` | writes a portable XMP sidecar of selected kinds of information for each photo | one `.xmp` per item (stable slots) |
| `planNames` | plans what the files would be called and where they would go | `names-plan.json`, `names.csv` |
| `organiseCopies` | makes a named, foldered set of exact byte copies | `organised/` tree (stable slots) |

### Transfer groups

`transfer` chooses what is carried, by closed group or field: `descriptive` (title, description, keywords), `rights` (creator, copyright, rightsUrl), `rating`, `place`
(locationCity, locationCountry), `camera` (cameraMake, cameraModel, lensMake, lensModel), `exposure` (exposureTime, fNumber, isoSpeed, focalLength, focalLength35mm,
exposureBias) and `deviceSerials` (bodySerialNumber, lensSerialNumber; never implied by another group). The groups `captureTime` and `location` complete the vocabulary: `exportSidecar` writes both with every other group. `copyMetadata` and `applySidecar` carry each of them through the E3 time or location planner, writer and proofs, and any union of groups and fields may be combined in one request: each part
is planned by its own planner (the E2 edit plan, the extras table, the E3 time planner with an internal absolute captured-time set, the E3 location planner), all parts are written by one native process and proved on
the same output bytes (the E2 proofs, the E3 time and location readback, one closed native diff over the declared targets of every part, plus proof T), and a refusal of any selected part refuses the whole item so that nothing is
written for it; a selected value is never dropped from a successful item, and a single captureTime or location selection takes the same route and the same proofs as a mixed one. A captured time travels as local time, offset and fraction: the source's exact
local time, fraction digits and offset are *set* (not computed as a move from the destination): in every time family the destination records (EXIF, XMP, IPTC), and, when the destination records no captured time at all, in one carrier
that can hold it without creating a block (`ExifIFD:DateTimeOriginal` with its offset and fraction tags in an existing ExifIFD, otherwise `XMP-exif:DateTimeOriginal`, a declared loss `timeCreatedInExifOnly` or `timeCreatedInXmpOnly`). A source offset is set keeping the wall clock,
a destination offset the source does not record is refused (`TRANSFER_TIME_OFFSET_CONFLICT`; an offset cannot be removed here), a destination that would
record the fraction with another digit count than the source is refused (`TRANSFER_TIME_FRACTION_PRECISION`), an ExifIFD is never created (an XMP carrier is used instead), a selected time that no carrier would apply is refused (`TRANSFER_TIME_NOT_APPLIED`, never reported unchanged), and no time zone is ever invented. A position is carried with coordinates rounded half-even to 9 decimal places
(the difference is recorded), an altitude only with its typed reference and when exactly representable, a destination position follows the `existing` policy, removing a destination value is `removeMetadata`
(`TRANSFER_E3_CLEAR_UNSUPPORTED`; an absent source with an absent destination is simply unchanged), and an Exif creation or an altitude the file's edition cannot express is refused exactly as `correctTime` and `setLocation` refuse it.
Not transferable, by design: orientation, imageWidth, imageHeight (rendering facts of the destination pixels), software, modifiedLocal and digitizedLocal
(they describe the process that produced the destination). A field outside the closed list is refused (`INVALID_TRANSFER_SELECTION`).

### `copyMetadata`

`source` is `{"item": id}` (another item of the same run, read from its capture, never from an output), `{"file": {"path", "sha256"}}` (one captured JPEG or XMP file; a
workflow can bind an earlier artifact to `path`) or `{"pairs": [{"from", "to"}]}` (an explicit source for each destination). A destination equal to its own source is
`TRANSFER_SELF`. The destination receives *values*, not blocks: the independently decoded, natively anchored typed values of the source snapshot are re-encoded by the unchanged
E2 copy writer. Nothing runs `-tagsFromFile`, and MakerNotes, unknown tags, thumbnails and XMP structures are never copied.

`policies` are domain decisions: `existing` (`refuseConflict` default, `replace`, `keepDestination`) decides what happens when the destination already has a different value
(`TRANSFER_CONFLICT` names both values; rational values compare by their exact numerator and denominator, so 10/30 and 1/3 differ); `absent` (`leaveDestination` default,
`clearDestination`) decides what a field that the source understood as absent does; `ambiguous` (`refuseItem` default, `skipField`) decides what to do when the sources of the
source disagree. An unreadable or unsupported source value is never absent: it is `TRANSFER_SOURCE_UNREADABLE` unless `skipField`. `loss` carries the editing loss policies
(`iptc`, `otherLanguages`, `exifEncoding`, `companionLoss`). Lists transfer as whole values (there is no merge); language alternatives transfer every language.

No Exif block or ExifIFD is ever created by a transfer: a destination without one is refused per item (`TRANSFER_WOULD_CREATE_EXIF`), because the native writer would add
mandatory values such as ExifVersion that can change what an untouched GPS-only height means. After every write the typed height is read again (`ALTITUDE_MEANING_CHANGED`).
A text keeps its exact leading and trailing spaces (U+0020) in the descriptive, rights and place fields, in the default text and in every language alternative alike, because native 13.55 preserves them in XMP and IPTC (the `editMetadata` input rule is unchanged); a blank or control alternative is refused exactly (`TRANSFER_VALUE_NOT_REPRESENTABLE`), never replaced by a placeholder; other edge white space and
the EXIF-only camera, lens and serial fields refuse an edge-space text (native 13.55 itself lists an EXIF ASCII value trimmed: the probe5 evidence of the final review wrote `OLYMPUS IMAGING CORP.  ` raw and listed `OLYMPUS IMAGING CORP.`; this is the existing E1 anchoring limit, not a reason to normalise a literal). A value that a destination form cannot hold exactly (a rational that does not fit 32-bit parts, an IPTC byte limit under the loss policy, an EXIF text over 255 bytes) is a
declared loss or `TRANSFER_VALUE_NOT_REPRESENTABLE`, never a truncation. An item whose every selected field is equal, absent or kept is refused as `ITEM_UNCHANGED` and no native
process is started for it.

Proofs: the E2 proofs R (independent readback), P (byte-identical encoded image) and N (closed native before/after diff) plus **T**, for every item whatever its selection. T-host compares the raw decoded literal
of the source (exact text, language set, list order, rational pair, captured local time, offset and fraction) with the output, compares the source position with the output position within the declared nine-decimal half-even quantisation
(2e-10 degrees of serialisation on top), the typed altitude (reference, sign, exact metres; an omitted altitude must be a declared loss, `TRANSFER_LOSS_UNDECLARED`) and the datum, and checks every kept, skipped or cleared field against its plan decision; the
expectations come from the source capture and the declared rules, never from the planner's own request. T-native compares the fixed ExifTool listings of the source capture and of the output key by key wherever both carry the key (a captured time as the typed
local time, offset and fraction each listing states, a position numerically at the two GPS keys), so a reader that normalises both sides cannot make a changed value
look equal. A captured time is composed from the carriers of each listing that state a local time (a carrier contributes the offset and the fraction it states together with its own local time: the Exif offset and sub-second beside `ExifIFD:DateTimeOriginal`, the IPTC time beside the IPTC date), in these fixed native keys: `ExifIFD:DateTimeOriginal` (with `ExifIFD:OffsetTimeOriginal` and `ExifIFD:SubSecTimeOriginal`),
`XMP-exif:DateTimeOriginal`, `XMP-photoshop:DateCreated`, and the IPTC pair `IPTC:DateCreated` with `IPTC:TimeCreated`. A photograph often spreads one capture time over such carriers (the camera's Exif local time without an offset, the offset or the fraction
restated by IPTC 2:55 with 2:60, XMP photoshop or XMP exif after an editor touched the file), so each component is composed independently of the others: the value the carriers that state it agree on, no value when no carrier states it (no zone and no fraction is
ever invented, and a `Z` is the offset `+00:00`), and, when carriers state different values of one component, a conflict that never equals a stated value. The same composition is made for the source and for the output and the two are compared, so the output must state
every component any source carrier that also states the local time states (an offset or a fraction that is dropped, changed or added is a mismatch), and a source or an output whose carriers disagree is a mismatch (the planner refuses such a source before any write with `TRANSFER_SOURCE_AMBIGUOUS`). The
composition reads the fixed listing only: it does not call the host reader or the planner. The IPTC pair counts only when both are listed; its offset is the one the time states (a time without one has none), its fraction is whatever the listing states (none for a time written as
`HHMMSS`), and the local time is never shifted. So a time that an output records only in IPTC 2:55 and 2:60 is compared with the time of the source, whichever family carries it there, and a source time that the output lists in no carrier at all is a mismatch.
A source fraction into a destination whose only time is IPTC is still refused before any write (`TIME_SUBSECOND_REQUIRED`).
An offset or a fraction that a carrier states without that carrier's own local time (an Exif `OffsetTimeOriginal` or `SubSecTimeOriginal` without `DateTimeOriginal`, an IPTC time 2:60 without the date 2:55, whatever clock it states) is an orphan component. No carrier stated its association with a local time that another carrier states, and the listing comparison does not make it, so the copy planner does not either: the typed snapshot that `copyMetadata`, `applySidecar`, `exportSidecar` and the names share reads a capture time whose offset or fraction only orphan carriers state as unsupported, and a selected capture time of such a source is refused before any write with `TRANSFER_TIME_COMPONENT_UNANCHORED` at `$.transfer.captureTime` (side `source`, the carrier family, key and value listed), into replaced, timeless and blank destinations alike, single or in a mixed selection, with nothing published and no native write started. Under the `skipField` policy only that field is skipped (reason `sourceUnanchored`) and the rest of the selection is written; an `exportSidecar` item is refused with the same code while its neighbours continue; a name taken from the concordant time (the default source) that uses the offset (a UTC or fixed-offset basis) or the fraction is refused with `NAME_TIME_COMPONENT_UNANCHORED`, and a recorded-local name ignores an orphan offset. An orphan is redundant, and the time is written and verified as before, where an anchored carrier states the same component (an Exif offset beside an XMP photoshop date that states the same offset); carriers that state different values of a component stay `TRANSFER_SOURCE_AMBIGUOUS`, which includes an IPTC time with its date but another clock than the Exif time; a source whose only capture-time statements are orphans states no capture time at all. A destination is held to the same rule where the write would leave the orphan in place: a destination capture time whose offset or fraction only orphan carriers state, or an IPTC time 2:60 without 2:55, is refused before any write (side `destination`, located at the destination file); a destination Exif `OffsetTimeOriginal` or `SubSecTimeOriginal` that the write replaces is written and verified as before. Nothing in the destination is dropped to make a write pass.
A whole-second captured time (no fraction, or no offset) into a destination that has neither an Exif block nor XMP is written into one new XMP carrier. Its read-back is exact: the independent reader describes an XMP date written without a fraction (or without an offset) as that component being absent with the typed code `XMP_NO_FRACTION` (or `XMP_NO_OFFSET`), and the R proof accepts exactly that description of a date the plan wrote itself, where the component was absent without a code before. A component that vanished, a date the plan did not write, a fraction or offset that differs from the source and every other changed source stay mismatches, and no fraction, zone or precision is invented. The untouched-data guards of R and N use the union of the declared EXIF, XMP and IPTC targets of every part. A mismatch is `TRANSFER_READBACK_MISMATCH`. Publications: `transfer-plan.json`, `transfer-report.json` and `manifest.json` after one slot per item.

### `applySidecar`

The same transfer with the source fixed to each item's XMP sidecar: `source: {"sidecar": "adjacent"}` with a `media.folder` (the pairing rule of the media manifest) or
`{"sidecar": "declared"}` with `media.items[].sidecar` (which a workflow can bind to an `exportSidecar` artifact). An item without a sidecar is refused `SIDECAR_ABSENT` and the
others continue; the sidecar is captured, hashed and anchored like an item, is never modified and is never copied. The existing editing refusal of a sidecar beside a JPEG
(`WRITE_SIDECAR_PRESENT`) stays for `editMetadata` and `removeMetadata`; for `applySidecar` the sidecar is the declared source, not a hazard.

### `exportSidecar`

Writes `sidecars/<id>.xmp` for each item from its typed snapshot, in a closed set of 29 XMP properties: `dc:title`, `dc:description`, `dc:rights` (language alternatives,
`x-default` first), `dc:subject` (bag), `dc:creator` (sequence), `xmpRights:WebStatement`, `xmp:Rating`, `photoshop:City`, `photoshop:Country`, `photoshop:DateCreated`,
`tiff:Make`, `tiff:Model`, `exifEX:LensMake`, `exifEX:LensModel`, `exifEX:BodySerialNumber`, `exifEX:LensSerialNumber`, `exif:ExposureTime`, `exif:FNumber`, `exif:FocalLength`,
`exif:ExposureBiasValue`, `exif:FocalLengthIn35mmFilm`, `exifEX:PhotographicSensitivity`, `exif:DateTimeOriginal`, `exif:GPSLatitude`, `exif:GPSLongitude`, `exif:GPSAltitude`,
`exifEX:GPSAltitudeRef`, `exif:GPSMapDatum` and `exif:GPSTimeStamp`. Only selected fields that are `present` are written; text is exact and rationals are the exact `n/d`
pair. A character XML 1.0 cannot carry refuses the item (`SIDECAR_TEXT_NOT_XML`) and is never stripped; one sidecar is at most 1 MiB (`SIDECAR_BOUND`). `policies`:
`ambiguous` (`refuseItem`, `skipField`), `altitude` (`omitUnlessReferenceKnown`, `refuseUnlessReferenceKnown`) and `existingSidecar` (`ignore`, `refuse`); an existing adjacent
sidecar is never merged or edited.

Altitude is written as `exif:GPSAltitude` (the exact magnitude) with the Exif 3.x reference in `exifEX:GPSAltitudeRef` (0 ellipsoidal, 1 ellipsoidal below, 2 sea level, 3 sea level
below) only where the typed height reference is ellipsoidal or sea level with a known sign; an unspecified legacy reference omits the altitude and reports the loss
(`ALTITUDE_REFERENCE_UNSPECIFIED` under `refuseUnlessReferenceKnown`). ExifTool 13.55 lists that literal, but its Composite altitude reads it with legacy 0 and 1 meanings and
inverts the sign for code 2, so a sidecar with code 2 carries that residual. Coordinates use the XMP GPSCoordinate form: `DDD,MM,SSk` only when the stored values are whole and
below 60, otherwise decimal minutes rounded half-even to 8 digits, with the stored value, the written value and the difference in arc seconds published.

Proof **S**: the serializer re-run over the retained captures reproduces every sidecar byte for byte; the hardened XMP reader re-reads exactly the planned typed values and no
extra property; and a fresh fixed ExifTool listing of the produced sidecar carries exactly the expected XMP keys with agreeing values (rationals to 15 significant digits). A
failure is `SIDECAR_NOT_REPRODUCIBLE` or `SIDECAR_ANCHOR_MISMATCH`. Without a configured trusted runtime the proof reports `NATIVE_REPLAY_UNAVAILABLE`. Publications are
`sidecar-report.json` and `manifest.json` after one slot per item (the sidecar as a text artifact, or the outcome document of a refused item).

### `planNames`

A closed, deterministic name plan: `name` is a list of 1 to 12 parts, each a literal or a token (`captureDate` `YYYYMMDD` or `YYYY-MM-DD`, `captureTime` `HHmmss`, `HH-mm-ss`
or `HHmmssSSS`, `cameraMake`, `cameraModel`, `originalStem`, `itemId`, `sequence` with `width`, `start` and `scope`); `folders` is `flat` or up to four levels (`year`, `month`,
`day`, `captureDate`, `cameraModel`, `cameraMake`, a literal). `time` states the basis (`recordedLocal`, `utc` or a `fixedOffset`), the source (`concordantOnly`, `exif`, `xmp` or
`iptc`) and what a missing time or offset means; `text.missing` decides what a missing camera text means; `collisions` is `refuse` or `sequence`; `extension` is `canonical` (by
detected container; a HEIF whose major brand is `avif` is `.avif`, every other HEIF `.heic`) or `keepOriginal`. There is no template language, date arithmetic or regular expression, no system time zone and no file modification time. Disagreeing time
sources are `NAME_TIME_CONFLICT` unless a family is named; an unreadable time is never missing.

The sanitiser is declared per item: NFC, control and bidi characters and `/ \ : * ? " < > |` replaced (runs collapsed), leading and trailing spaces and dots stripped, Windows device
names given a suffix, components limited to 120 UTF-8 bytes and the path to 1024 bytes and 5 components. Two outputs whose names are equal after case folding and Unicode
normalisation collide, including a file and a directory; with sidecars the collision unit is the stem within its folder, so `a.jpg` and `a.xmp` are never separated from each
other. The plan is the artifact `names-plan.json` with the capture hash of every item; `names.csv` is its typed table.

### `organiseCopies`

Creates exact byte copies under `organised/<relative path>` from a rule given inline or from a `planNames` document (`names` can bind that artifact): a plan made for other bytes
is `NAME_PLAN_STALE` for the whole run, before anything is copied. `sidecars` is `carry` (copy each adjacent sidecar beside its image with the same stem) or `omit`. Every copy is
created only inside the run, create-only and without following links, one directory level at a time; a surprise on disk is `ORGANISE_TARGET_EXISTS` or `ORGANISE_PATH_UNSAFE` for
that item and the others continue. Slots are fixed: slots 0..N-1 are the images (or outcomes), slots N..2N-1 the sidecar copies (or a `noSidecar` outcome), then `names-plan.json`,
`organise-report.json` and `tree.json` at 2N, 2N+1 and 2N+2 and `manifest.json`. Proof **C**: every output hashes equal to its capture, paths equal the plan, `tree.json` lists
exactly the produced files and nothing else exists under `organised/` (`ORGANISE_COPY_MISMATCH`).

### Reuse, verification and limits of the copy, sidecar and naming workflows

Reuse is keyed by the captured bytes of every item, sidecar, source and plan file and by the folder membership, so a changed byte, source, sidecar, plan or membership
invalidates it. `verify` recomputes every proof from the retained bytes and, with a configured trusted ExifTool 13.55, replays the native listings and writes; a coherent
rewrite of every retained record verifies as consistency, not authenticity.

- Selected typed values only: no full-block, MakerNote or unknown-tag transfer, no XMP structures (location created, contact, regions, history), and no merge of an existing sidecar.
- `copyMetadata` and `applySidecar` carry the capture time and location groups through the E3 writers, alone or in any union with the other groups (one write, one proof set, whole-item refusal); `exportSidecar` writes both with every other group.
- No free-form naming template, date arithmetic or regular expression, no delivery outside the run directory and no archive.
- JPEG items only: other containers, and the container-specific destinations they need, belong to later work.
- None of this is privacy or provenance certification, and none of it is a claim of ExifTool or MWG completeness.
