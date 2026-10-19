# Pandoc structured reports

The `schemaxis.pandoc/1` document route publishes a small declared report as
standalone HTML5 and editable Word DOCX. Use it to package measured results with
an outline, explanatory paragraphs, text tables and a local figure. Pandoc runs in
isolated processes; host discovery and planning require no Pandoc import.

## Start and run

Copy [the calibration report](../examples/schemaxis/pandoc-report.json), replace
`/sections/1/content/1/source` with the absolute path of a plain PNG, then run:

```sh
schemaxis plan report.json
schemaxis run report.json --pandoc /absolute/path/to/pandoc --output-directory output/report
schemaxis verify output/report
```

The bundled fixture is `examples/schemaxis/fixtures/pandoc/calibration.png`, a 48
by 24 RGB PNG with blue, green and red vertical bands. Qualification binds this
repository-relative fixture automatically. Configure the executable through
`schemaxis configure` or supply `--pandoc`; no user PATH changes are needed. The
targeted and bounded native-qualified version is recorded in `upstream.json`.

## Report fields

`title` is required plain text, displayed at the start of both reports and used as
the HTML browser title. It is limited to 160 characters. `sections` is an ordered
list of 1–32 section records. Every section requires `heading` (up to 160
characters), an optional `level` (default 1, levels 1–3), and 1–32 `content`
blocks. The first section starts at 1; a later heading increases by at most 1.
Decreasing levels can skip levels. The report permits 128 content blocks total,
65536 text characters and 8 images. Headings do not imply hidden nesting or page
breaks.

Content blocks have one of these closed forms:

| Kind | Fields and meaning |
| --- | --- |
| `paragraph` | Required `text`, at most 2048 characters, rendered as one paragraph. |
| `table` | Required 1–8 `columns` are the single header row. Required 1–64 `rows` contain exactly that many text cells. Each cell is nonempty and at most 256 characters. Numeric-looking cells remain text; formulas, merged cells and nested content are unsupported. |
| `image` | Required `source` is an absolute local `.png` path; required `alt` is plain descriptive text up to 256 characters. `widthMm` defaults to 80 and accepts 10–150 millimetres; the native image aspect ratio is retained. |

All authored text uses single ordinary spaces, no leading/trailing whitespace,
control characters or line breaks. XML/HTML punctuation such as `<`, `&` and `>`
is literal text, escaped by the writers. It is never parsed as markup. Rich text,
links, citations, formulas, lists, user templates, reference documents, filters,
scripts and raw HTML/Markdown are excluded rather than silently approximated.

PNG sources are at most 4 MiB each and 8 MiB combined, 8-bit non-interlaced RGB or
RGBA, dimensions 1–2048 per axis and at most 1048576 pixels. Only IHDR/IDAT/IEND
chunks are accepted; export a plain PNG without auxiliary metadata. Source bytes
are captured once, checksummed and embedded in a trusted JSON AST as data URIs.
Both writers use Pandoc's `--sandbox`, with no network or external document
resources. The source path is retained as provenance; later verification uses the
captured copy and still works if the original is moved. Workflow reuse hashes the
current source bytes so a changed image at the same path triggers a fresh run.

## Native mapping and verification

The public [Pandoc JSON
AST](https://github.com/jgm/pandoc-types/blob/master/src/Text/Pandoc/Definition.hs)
maps section headings to `Header`, paragraphs to `Para`, rectangular cells to
`Table` rows/cells and PNGs to `Image`. Text is built from `Str` and `Space`. The
API version is obtained from the selected executable's empty JSON conversion, not
guessed from its release number. The closed CLI selects `html5 --standalone
--embed-resources` and `docx`, followed by a fresh `docx` reader to JSON with
[extracted media](https://pandoc.org/MANUAL.html#option--extract-media). [Sandbox
limitations](https://pandoc.org/MANUAL.html#option--sandbox) are respected by
embedding captured media in the AST. No authored option becomes an argv flag.

Independent host parsers compare complete ordered heading levels/text, paragraph
text, table cells and image alt text. HTML must contain PNG data URIs; OOXML must
contain internal media relationships with exact PNG bytes and declared physical
width. A fresh native DOCX-to-AST conversion repeats the semantic check and
compares extracted image bytes. The HTML must contain exactly the reviewed default
stylesheet from qualified Pandoc 3.12.1. Its SHA-256 fingerprint is held in trusted
adaptor code, so a refreshed run receipt cannot approve CSS that hides content. An
upstream release that changes this stylesheet fails verification until its default
styles have been reviewed and the native route requalified. This checks actual documents against authored
values, beyond file existence, a native exit code or a producer summary.

The published artifacts are `report.html`, `report.docx` and
`report-summary.json`. The summary reports the title and content counts plus the
explicit loss policy. Retained evidence includes authored/effective plans, trusted
JSON AST, captured images/source digests, runtime, native submissions,
stdout/stderr, fresh readback JSON/media and verification digests. Failures keep a
failed result and their completed stage evidence. One total timeout covers all
stages and final inspection; each Pandoc process has a 512 MiB heap cap; shared
cancellation terminates owned processes.

Typography, pagination and the placement of page boundaries use Pandoc defaults.
This integration does not certify exact page layout, accessibility, colour
management, PDF output or conversion of arbitrary existing documents. A visual
review of a bounded fixture is recorded separately from semantic qualification.

## Fault recovery and examples

`INVALID_REPORT_TABLE` identifies a ragged row: supply one text cell per column.
`INVALID_HEADING_ORDER` identifies an outline jump: begin at 1 and add at most 1.
`INVALID_REPORT_TEXT` needs plain single-space text; do not put line breaks or
markup instructions in a text field. `INVALID_REPORT_IMAGE` needs a regular plain
PNG within the documented limits; symlinks, URLs and unsupported PNG chunks are
rejected. `REPORT_RESOURCE_LIMIT` needs a smaller report. `VERIFICATION_FAILED`
requires retaining the attempt and investigating the document/readback mismatch;
changing a receipt is not recovery. `INTERPRETER_NOT_FOUND` needs an absolute
working executable. Timeout/cancellation requires a fresh output directory.

[The variant](../examples/schemaxis/pandoc-report-variant.json) changes a measured
cell to 12.5, image width to 90 mm, the image to a partially transparent purple
square, and the outline to levels 1, 2 and 3. [The invalid
example](../examples/schemaxis/pandoc-table-invalid.json) intentionally omits a
cell; planning must reject it before native execution. Studio includes an editable
calibration-report template with the same required image placeholder.

`tools/qualify_pandoc.py --pandoc /absolute/path/to/pandoc --output-directory
PATH` runs bounded native acceptance and hostile evidence/lifecycle cases. A
receipt qualifies only these cases and the recorded source/runtime, not every
Pandoc reader/writer or arbitrary future report.
