# Changelog

All notable changes are recorded here. Versions follow
[semantic versioning](https://semver.org/); during 0.x, minor versions may
change input contracts, with migration notes.

## 0.4.0 (unreleased): first public preview

- First public release under the Apache License 2.0.
- External adaptor packages: adaptors can be installed as separate
  distributions through the `schemaxis.adaptors` entry-point group.
- Studio authoring, contextual workflow validation, local case execution,
  scheduling, saved-run portability and explicit storage preservation.
- Expanded application adaptors, including SQLite relational summaries and
  Apache Arrow table interchange, plus bounded FreeCAD, NumPy and pyproj
  acceptance. See the dated verification records for tested versions and limits.
- ExifTool photo-metadata adaptor: typed read, audit and comparison of JPEG and
  XMP sidecar metadata, new JPEG copies with edited, removed or minimised
  metadata, and time and location workflows (`reconcileTime`, `locate`,
  `correctTime`, `setLocation`, `geotagFromTrack`) that analyse capture clocks
  and recorded positions and write corrected times, declared positions or
  positions interpolated on GPX tracks through a plan, with exact arithmetic
  and independent proofs. See `docs/exiftool.md` for the limits.
- ExifTool copy, sidecar and naming workflows (`copyMetadata`, `applySidecar`,
  `exportSidecar`, `planNames`, `organiseCopies`): selected typed metadata is
  carried from a photo or an XMP sidecar onto new copies with exact text and
  exact rational pairs, portable XMP sidecars are exported in a closed
  29-property set, and photo names and folders are planned from recorded
  capture facts and applied as exact byte copies, each with its own proof and
  declared losses. See `docs/exiftool.md` for the limits.
- ExifTool container family (`inspectMetadata`, `auditMetadata`,
  `compareMetadata`, `editMetadata`, `removeMetadata`): TIFF, DNG, PNG, WebP and
  HEIF files are located by signature with bounded readers, read through the
  shared EXIF, XMP and IPTC decoders and edited or cleaned as new copies under an
  offset-free preservation proof, with closed native side effects and named
  refusals. HEIF metadata items that do not exist are never created (a native
  13.55 capability gap) and HEIF removal and minimise are refused. The same
  containers take the time and location writes (`correctTime`, `setLocation`,
  `geotagFromTrack`), the transfer writes (`copyMetadata`, `applySidecar`) and the
  sidecar and naming operations through the same shared planners, proofs and
  writer; PNG and WebP `minimise` resets the Exif and XMP blocks (`-EXIF:all=`,
  `-XMP:all=`), deletes PNG text chunks by keyword and writes the rendering
  values (Orientation, YCbCrPositioning, ColorSpace) back, with the closed
  residual proof and the byte-level protection of gamma, colour profile and image
  data unchanged, and removes a WebP VP8X exactly as predicted; TIFF
  and DNG items may be up to 256 MiB (64 MiB elsewhere; the published budget
  states both bounds). TIFF and DNG `minimise` and thumbnails outside JPEG stay
  named limits. An IPTC change to a JPEG, TIFF or DNG whose Photoshop block ends
  with opaque bytes is refused before any native process, for edits, time
  corrections and transfers alike, instead of silently losing them. A HEIF edit
  that would leave an existing Exif or XMP item without any metadata is refused
  (`HEIF_EMPTY_METADATA_ITEM`), and an AVIF is named `.avif` by the canonical
  naming rule. See `docs/exiftool.md` for the matrix and limits.
- Explicit distribution boundary: general-purpose database adaptors stay in
  core; integrated database services and CFD case/solver integrations remain
  separate. No integrated case-history database is included in this preview.
- Release evidence runner (`tools/release_evidence.py`) for reproducible,
  verified showcase runs.
- Release gate (`tools/release_gate.py`) checks the tree and built archives
  for private or machine-specific content.
