# MuPDF PDF review

Use `schemaxis.mupdf/1` to capture a local PDF and publish a chosen sequence of
page PNG previews, per-page UTF-8 text and `review-summary.json` metadata. This
supports archival previews and bounded document review with reproducible source
bytes. Configure the **MuPDF 1.28.5 `mutool` executable on POSIX**, or pass
`--mupdf /absolute/path/to/mutool`. Discovery and planning need only Python 3.10+;
the application runs separately. No Python PDF package is required.

```json
{
  "version": "schemaxis.mupdf/1",
  "operation": "review",
  "source": "/absolute/path/to/review.pdf",
  "pages": [2, 1, 3],
  "dpi": 72,
  "rotation": 0
}
```

The [editable baseline](../examples/schemaxis/mupdf-review.json) selects page 2
first. Replace its source path with the absolute path to the
[three-page fixture](../examples/schemaxis/fixtures/mupdf/review.pdf), then run:

```sh
schemaxis plan review.json
schemaxis run review.json --output-directory output/pdf-review --mupdf /absolute/path/to/mutool
schemaxis verify output/pdf-review
```

The [variant](../examples/schemaxis/mupdf-review-variant.json) changes page order,
doubles density and turns the raster clockwise. In Studio choose **MuPDF → Review
selected PDF pages**, fill the PDF path and ordered pages, and use the shared
forms for density and rotation. The operation and every field have contextual Help.
See the [generated operation reference](generated/mupdf-operations.md).

## Page geometry and text

`pages` contains 1–16 unique **one-based** page numbers, in publication order.
The entire PDF must contain 1–128 pages. `page-001.png` and `page-001.txt` always
represent the first selected page, regardless of its original page number.

The native effective **CropBox** is used, including MuPDF's MediaBox intersection,
inherited PDF `/Rotate`, `/UserUnit` scaling and nonzero box origins. The summary
retains raw inherited MediaBox/CropBox values (`null` if a raw box is absent), raw
inherited rotation, normalized native crop bounds and observed RGB dimensions.
Raw PDF boxes use PDF coordinates; normalized bounds use MuPDF's top-left view
coordinates. No authored crop, box override or original-document edit is offered.

`dpi` is pixels per inch, from 36 to 300; omission selects 72. At ordinary
`UserUnit=1`, 72dpi maps one PDF point to one pixel. Additional `rotation` is
**clockwise**, one of 0/90/180/270 degrees, default 0, applied after the native crop
and inherited rotation. A quarter turn exchanges width and height. Pixel bounds
round outward with MuPDF's 0.001-pixel tolerance (`floor(min+0.001)`,
`ceil(max−0.001)`), avoiding spurious pixels at floating-point boundaries. PNG density tags are set
from the requested DPI via `Pixmap.setResolution` and checked at the nearest
whole pixels-per-metre value, together with native resolution readback.

PNG images are opaque 8-bit DeviceRGB with a white background, using native
**View** appearances including annotations/widgets. Vector geometry, transparency,
editable forms, links, layers and source colour spaces do not survive rasterization.
This does not certify colour-managed print fidelity or PDF/A compliance.

Text is MuPDF `toStructuredText("preserve-whitespace").asText()` output encoded
as UTF-8. It follows native content order and may include native line breaks;
page order follows the authored selection. Output rotation affects the preview,
not text order. Font mappings determine Unicode. There is no OCR, reading-order,
layout, accessibility or universal Unicode guarantee. A scan may yield empty text.

## Capture, verification and limits

The input is captured once from a regular file, up to 16 MiB, with its source path,
size and SHA-256 retained. Native stages consume only this owned `source.pdf` and
adaptor-authored fixed scripts; authored JavaScript, arbitrary commands, passwords,
URLs, external resource directories and native reflection are not exposed.
Malformed PDFs and PDFs requiring native structural repair are rejected via
`wasRepaired()` (including repairs discovered lazily). Encrypted PDFs, including
empty-password encrypted files, are rejected using the
native parsed trailer's Encrypt entry. File bytes are never searched as a pretend
PDF security parser. No PDF JavaScript is enabled, actions executed, links followed,
attachments extracted or network fetch requested. Passive rendering **is not a PDF
sanitizer or an operating-system security sandbox**; use source documents you are
prepared to process with the configured native library.

Each output dimension must be at most 4096 pixels; all selected pages together may
contain at most 16,777,216 pixels (48 MiB decoded RGB). Effective native crop
width/height must be positive and at most 14400 points. Native parsing/rendering
has per-process POSIX limits of 1 GiB address space, 64 MiB per output file and
120 CPU seconds, together with text limits of 1,048,576 characters per page and
4,194,304 combined and one total caller timeout and owned process-tree
cancellation. These are rejection bounds, not guarantees that every PDF within
those bounds will render. Complex compressed content can exhaust native limits.
Failed/incomplete results and native logs remain available.

Every PNG is decoded with a bounded standard-library CRC/zlib/filter reader and
compared pixel-for-pixel with a **fresh native reopening** of the captured PDF to
PNM. Text/metadata/order are compared across the separate native stages. The
verifier also checks the captured-source binding at each execution, trusted
scripts/launchers/command arrays, runtime identity, publication/evidence membership,
required files and hashes, effective plan and common schema reference. Added page
outputs are rejected. Source byte changes invalidate normal workflow reuse.

Offline `verify` uses retained evidence and never silently launches MuPDF. Its
native readback proves consistency with the recorded native execution; it is not an
independent implementation of PDF semantics or a cryptographic attestation against
an attacker rewriting every evidence file. The separate
[fixture oracle](../tools/qualify_mupdf_fixtures.py) constructs its own literal PDF
without a PDF library and independently checks exact dimensions, ordered text
(including café), inherited/overridden rotations, nonzero boxes, page3 UserUnit=2 and known colour
regions. The native baseline/variant do not establish correctness for every font,
PDF feature, annotation or colour profile.

The shared workflow/composition infrastructure supports source-byte reuse,
source-change invalidation and finite parameter studies. Publications can be
selected as verified image/text artifacts by subsequent jobs; no automatic
format conversion or arbitrary PDF import by another adaptor is claimed. The
[page-to-video workflow](../examples/schemaxis/mupdf-to-ffmpeg.json) hands the
first verified page PNG to FFmpeg through an explicit artifact binding, holding
it for two frames in a lossless one-second FFV1 video. Multipage size
normalization is outside this example. Shared
schema capture and verification use the framework store automatically.

## Recovery

- `INVALID_PDF_SOURCE`: choose an absolute local regular `.pdf` file with the
  standard PDF header and size at most 16 MiB; leaf symlinks and URLs are refused.
- `INVALID_PDF_PAGES` / `PDF_PAGE_RANGE`: use distinct one-based page numbers
  within the actual document's page count.
- `ENCRYPTED_PDF`: obtain an authorized unencrypted source copy; no password
  interface is exposed.
- `PDF_TEXT_LIMIT`: select fewer pages or a smaller source text payload.
- `PDF_REPAIRED`: supply a structurally intact PDF; native repair is unsupported.
- `PDF_PAGE_LIMIT` / `PDF_GEOMETRY_LIMIT` / `PDF_PIXEL_LIMIT`: choose a smaller
  source, fewer pages or lower density, according to the stated bounds.
- `UNSUPPORTED_RUNTIME` / `INTERPRETER_NOT_FOUND`: configure the exact qualified
  MuPDF 1.28.5 executable; older installed runtimes are not accepted silently.
- `RUNNER_TIMED_OUT` / `RUNNER_CANCELLED`: inspect retained logs, simplify the
  input, and rerun in a fresh directory after resolving the cause.
- `VERIFICATION_FAILED`: inspect the named missing/changed evidence; regenerate
  from the original authored input rather than editing verification hashes.

## Native API and maintenance

The initial supported runtime is **MuPDF 1.28.5**, the latest stable release
reviewed on 17 October 2026 from the official
[release history](https://mupdf.com/releases/history). The adaptor uses the public
[PDFDocument](https://mupdf.readthedocs.io/en/1.28.5/reference/javascript/types/PDFDocument.html),
[PDFPage](https://mupdf.readthedocs.io/en/1.28.5/reference/javascript/types/PDFPage.html),
[Pixmap](https://mupdf.readthedocs.io/en/1.28.5/reference/javascript/types/Pixmap.html)
and [StructuredText](https://mupdf.readthedocs.io/en/1.28.5/reference/javascript/types/StructuredText.html)
interfaces through a fixed `mutool run` script. `upstream.json` records absorption
only after host checks, meaningful bounded native acceptance and integration review.
The [completion review](../verification/2026-10-17-mupdf-completion.md) records the
actual qualification, provenance and limits. MPI, interactive inspection, live
editing, native PDF saves and general conversion are unsupported.
