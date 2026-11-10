# Tesseract scanned-page OCR

The `tesseract` adaptor recognizes the text of **one local scanned-page PNG** with
[Tesseract](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html) 5.5.3
and one pinned English LSTM model. It produces a **machine draft**: page text, every
word's box in source pixels with Tesseract's own confidence, and an inspectable
summary. It does not certify what the page says, accessibility or accuracy.

MuPDF extracts a PDF's embedded text but never reads scanned pixels. A scanned PDF
page can be rendered by MuPDF and passed here as an image artifact; this route reads
pixels only.

## Operation `recognizePage`

```json
{
  "version": "schemaxis.tesseract/1",
  "operation": "recognizePage",
  "image": {"path": "/abs/page.png"},
  "model": {"path": "/abs/eng.traineddata", "sha256": "<64 lowercase hex>"},
  "pageSegmentation": "uniform-block",
  "dpi": 200
}
```

| Field | Meaning |
| --- | --- |
| `image.path` (`sha256` optional) | Absolute local opaque 8-bit RGB non-interlaced PNG. In a workflow, an image artifact of an earlier verified step. |
| `model.path`, `model.sha256` | Absolute local `.traineddata`, expected to be an English LSTM model, and its required SHA-256. Captured into the run and hashed before and after. The pin identifies the bytes only: nothing verifies that the model is English, so a renamed non-English model would run and be recorded as `eng`. |
| `language` | `eng` only (default); passed as `-l eng`. It names the model file, and the model's actual language is not checked. |
| `pageSegmentation` | `uniform-block` (`--psm 6`, default) or `single-line` (`--psm 7`). Neither analyses the layout; a mismatched choice can return no words (`OCR_NO_TEXT`) or wrong text. On the qualification fixture, single-line on a two-line page returned no words; that is one observation, not a guarantee. |
| `dpi` | Optional declared density 70-2400 (`--dpi`). Without it the PNG density or Tesseract's estimate applies; the plan states which. It does not resample the file and does not relax the pixel limit below. |
| `origin` | Optional `{kind: "mupdf-review", summary, page}`; see below. |

Fixed and not authorable: engine mode 1 (LSTM), one thread (`OMP_THREAD_LIMIT=1`,
`OMP_NUM_THREADS=1`), `-c tessedit_create_txt=1 -c tessedit_create_tsv=1`,
`--tessdata-dir` pointing at the retained model copy. No configuration files, global
`TESSDATA_PREFIX`, other languages, authored native flags or other output formats.

## Limits

PNG at most 16MiB, 4096 pixels per side and 4,194,304 pixels; model at most 64MiB;
at most 5000 words and 100,000 word characters; native TSV at most 4MiB and text at
most 1MiB; one serial native process under CPU 600 s, address space 8GiB and file
16MiB caps. Alpha (including `tRNS`), palette, grey, 16-bit, interlaced and animated
PNGs are refused as `UNSUPPORTED_IMAGE`, never flattened. A missing or non-regular
source or model is `INVALID_IMAGE_SOURCE`/`INVALID_MODEL`; a wrong runtime is
`UNSUPPORTED_NATIVE_VERSION`; a missing runtime is `INTERPRETER_NOT_FOUND`.

The OCR pixel budget (4,194,304 pixels, about 2048 by 2048) is smaller than the MuPDF
render limit (16,777,216 pixels). A full Letter or A4 page rendered at 300 dpi is
roughly 8.4 to 8.7 million pixels and is refused with `IMAGE_RESOURCE_LIMIT`; about
200 dpi is the most a full Letter page can use (about 1700 by 2200, 3.7 million
pixels). Render the page at that density or lower, or crop it, before recognition. The
declared `dpi` is only a density statement passed to Tesseract and cannot change the
pixel count.

## Publications

`page.txt` (text), `words.json` and `ocr-summary.json` (text artifacts).

* `page.txt` is the TSV lines: words in native record order (block, paragraph, line,
  word), joined by single spaces and newlines.
* `words.json` lists each word with block/paragraph/line/word indices, a
  `left, top, width, height` box and `confidence` (native 0-100 decimal text, up to
  six places). Coordinates have a top-left origin in the **same pixels as the source
  image**; right and bottom edges are exclusive.
* `ocr-summary.json` binds the image (file and RGB-pixel SHA-256, size, declared
  density), model, settings, runtime, counts, confidence range, origin state and the
  review statement.

Every result states `machineDraft: true`, `ocrTruthCertified: false`,
`humanReviewRequired: true`, `accuracyCertified: false` and
`confidenceCalibrated: false`. **Confidence is Tesseract's uncalibrated score, not
accuracy or a probability.** No claim is made for any font, language, layout,
handwriting, multipage input, medical or security use.

## Verification

The native files are untrusted. The strict TSV reader requires the exact twelve-column
header, LF records, a first page record equal to `0 0 width height`, consecutive
block/paragraph/line/word numbering, boxes with positive size inside the image and
their parents, word confidence 0-100, and nonblank words without control or space
characters. The native text file must agree with the TSV words after dropping blank
lines and collapsing space runs (the reading-order policy; paragraph separators and
trailing whitespace are the only tolerated differences). Every publication is
rebuilt from that evidence and compared byte for byte.

Offline `verify` rechecks the retained image, the retained model copy, native
TSV/text, trusted launchers, input bindings, runtime file hashes, plan hash and exact
membership **without launching Tesseract**. A process exit of zero or an existing file
is never sufficient. No words is `OCR_NO_TEXT` (nothing empty is published);
violations are `OCR_OUTPUT_INVALID`.

## Origin and workflows

Without `origin` the result records `origin.state: "unknown"`: pixels have no page
identity. With `origin`, the declared MuPDF `review-summary.json` page entry must have
the same width, height and RGB-pixel SHA-256 as the image (`ORIGIN_MISMATCH`
otherwise); the PDF digest, page number, page count, render density and rotation are
then retained. The MuPDF run itself is not re-verified here.

Workflow handoff uses ordinary `$artifact` references to the producer's verified image
(`examples/schemaxis/tesseract-mupdf-workflow.json`). The qualifier ran a real
producer handoff with Gnuplot rendering a chart PNG
(`examples/schemaxis/tesseract-gnuplot-workflow.json`); a MuPDF 1.28.5 handoff is
attempted by the qualifier only when that runtime is configured, and is otherwise
reported unavailable. Pandoc report ingestion of OCR blocks is **not supported**; the
OCR artifacts are reviewable files, and a separate handoff design is future work.
No timed-text contract is used or imitated.

## Running

```sh
schemaxis plan examples/schemaxis/tesseract-baseline.json
schemaxis run examples/schemaxis/tesseract-baseline.json \
  --output-directory NEW --tesseract /absolute/path/to/tesseract
schemaxis verify NEW
```

The examples read staged files under `/tmp/schemaxis-tesseract-acceptance`;
`tools/qualify_tesseract.py` stages and removes them. See
[the verification note](../verification/2026-10-25-tesseract-63.md) for scope.
