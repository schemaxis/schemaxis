# QPDF page assembly

Use `schemaxis.qpdf/1` to build a **new PDF from selected pages of one to four PDFs**:
pick pages in the order you want, repeat a page by listing it again, and turn any listed
page clockwise by a quarter turn. Each source is captured before execution. After assembly,
the captured sources and the published PDF are reopened with QPDF and MuPDF in fresh
processes, and every output page must match its source page exactly. This complements
[MuPDF review](mupdf.md), which renders pages; QPDF assembly changes which pages a PDF has.

This is **bounded page assembly**. It is not a PDF sanitiser, repair tool, editor or
malware boundary, and it does not describe the whole PDF grammar. PDFs outside the
stated envelope are refused rather than altered.

## Setup

Configure the **QPDF 12.4.2 executable** with `--qpdf`, `schemaxis configure` or
`SCHEMAXIS_QPDF`, and the shared **MuPDF 1.28.5 `mutool`** with `--mupdf`,
`schemaxis configure` or `SCHEMAXIS_MUPDF`. Both are required to run *and* to verify:
a missing, relative-path or different-release executable is a fault, never a skipped
check. Receipts never supply an executable. Discovery and planning need only
Python 3.10+; the applications run in separate processes on POSIX. QPDF's official
Linux release zip is relocatable (`bin/qpdf` finds `lib/` beside it); extract it with
`unzip`, because a Python `zipfile` extraction drops symbolic links and execute bits.

```json
{
  "version": "schemaxis.qpdf/1",
  "operation": "assemble",
  "sources": [
    {"name": "cover", "path": "/absolute/path/to/cover.pdf"},
    {"name": "report", "path": "/absolute/path/to/report.pdf"}
  ],
  "pages": [
    {"source": "cover", "page": 1},
    {"source": "report", "page": 2},
    {"source": "report", "page": 1},
    {"source": "report", "page": 3},
    {"source": "report", "page": 3, "rotate": 90}
  ]
}
```

The [editable baseline](../examples/schemaxis/qpdf-assemble.json) reorders and repeats pages
of two small hand-built PDFs ([cover](../examples/schemaxis/fixtures/qpdf/cover.pdf),
[report](../examples/schemaxis/fixtures/qpdf/report.pdf)). Replace both paths, then:

```sh
schemaxis plan assemble.json
schemaxis run assemble.json --output-directory output/packet --qpdf /path/to/qpdf --mupdf /path/to/mutool
schemaxis verify output/packet
```

The [variant](../examples/schemaxis/qpdf-assemble-variant.json) reverses the order and turns
repeats of one page differently. In Studio choose **QPDF → Assemble pages from PDFs**.
See the [generated operation reference](generated/qpdf-operations.md).

## What the fields mean

| Field | Meaning |
| --- | --- |
| `sources` | 1–4 entries `{name, path}`. `name` is 1–24 characters (lowercase letter, then lowercase letters, digits, hyphens) and is how pages refer to the file. `path` is an absolute local `.pdf`. Each PDF is listed once. |
| `pages` | 1–200 output pages **in list order**. Repeats are independent pages. |
| `pages[].source` | A declared source name. Every declared source must supply a page. |
| `pages[].page` | One-based **physical** position in that PDF (not the printed page label), 1–500. |
| `pages[].rotate` | 0, 90, 180 or 270 (default 0): extra **clockwise** quarter turn *added to the page's effective rotation*. |

There is no page-label option: page labels are always removed. Unknown fields, including
`pageLabels`, are rejected.

### Order, repeats, rotation, boxes and resources

* **Order and repeats.** Output page *k* is `pages[k-1]`. A repeated page is a distinct output
  page that shares the original content; each repeat rotates independently.
* **Rotation.** The final `/Rotate` is (the source page's effective rotation + `rotate`) mod 360.
  Effective rotation includes a value inherited from the page tree; −90 and 450 normalise to 270
  and 90. A rotation that is not an integer multiple of 90 is refused (QPDF and MuPDF read it differently).
* **Geometry.** Only MediaBox, CropBox, Resources and Rotate inherit through the page tree.
  UserUnit, BleedBox, TrimBox and ArtBox are page-local, and page-tree nodes carrying them are
  refused. MediaBox must exist; CropBox defaults to MediaBox and must lie inside it; local optional
  boxes must lie inside MediaBox; rectangles must be ordered and non-empty. Origins may be
  negative or fractional. An explicit `UserUnit` of 0, a negative number or a string is refused.
  Only indirect `/Parent` references are followed when resolving inherited values. All boxes
  and UserUnit are preserved and re-checked in the output.
* **Resources.** Content, fonts and images are carried unchanged and are not recompressed. QPDF
  drops resources a selected page does not use, and repeated pages share one copy.
* **What the appearance check does not see.** It compares the 36 dpi view of each page's CropBox
  and its extracted text. Changes outside the CropBox, clipped-away marks and unreachable objects
  can leave both comparisons unchanged and pass verification. Independent synthetic fixtures detected
  added invisible text through the text comparison and a 0.005-point mark through the raster
  comparison. Detection depends on the content and its position; no minimum detectable mark size
  is guaranteed.

## What is supported and what is refused

The envelope is deliberately narrow. Selected page dictionaries may contain only `Type, Parent,
Resources, Contents, MediaBox, CropBox, Rotate, BleedBox, TrimBox, ArtBox, UserUnit`, and `Annots`
only if absent, null or empty. Page-tree ancestors of a selected page may contain only `Type,
Parent, Kids, Count, MediaBox, CropBox, Rotate, Resources`. Only the pages you select and their
effective resources are examined; other pages of the same PDF are not.

QPDF's UTF-8 JSON observation is limited to 64 MiB and 128 nested containers before
decoding, independently of the Python version. Brackets inside strings do not
count. A larger or deeper observation fails with `PDF_STRUCTURE_LIMIT` for both
source admission and final-output verification.

| Refused | Fault |
| --- | --- |
| Encrypted PDFs, including empty-user-password and owner-restricted files | `ENCRYPTED_PDF` |
| PDFs QPDF cannot read at all without recovery (for example a missing xref or `startxref`) | `INVALID_PDF_SOURCE` |
| PDFs that read but make QPDF raise warnings (malformed tokens, damaged page tree) | `PDF_REPAIRED` |
| Forms, signatures, optional-content layers, tagged structure, output intents, threads, associated files, extensions in the catalogue; unknown catalogue entries | `PDF_CATALOGUE_UNSUPPORTED` |
| Selected pages with other keys (e.g. structure parents, beads, transitions, page metadata, page actions, **transparency groups (`/Group`)**) or page-tree ancestors with other keys | `PDF_PAGE_FEATURE_UNSUPPORTED` |
| Selected pages with annotations such as links | `PDF_ANNOTATIONS_UNSUPPORTED` |
| Resource categories outside Font, XObject, ColorSpace, Pattern, Shading, ExtGState, Properties, ProcSet | `PDF_RESOURCE_UNSUPPORTED` |
| Actions, file specifications, embedded files, optional-content references, rich media, and external-file or external-reference stream entries (`/F`, `/FFilter`, `/FDecodeParms`, reference XObjects `/Ref`, `/OPI`) reachable from the selected pages' resources | `PDF_FEATURE_UNSUPPORTED` |
| Invalid or unsupported geometry (missing, reversed, empty or out-of-range boxes, odd rotation, invalid UserUnit) | `PDF_GEOMETRY_UNSUPPORTED` |
| Physical page side over 8192 points (UserUnit included) | `PDF_GEOMETRY_LIMIT` |
| A page number past the PDF's page count; over 500 pages | `PDF_PAGE_RANGE`, `PDF_PAGE_LIMIT` |
| A 36 dpi verification raster over 4096 pixels per side or 16,777,216 pixels over all output pages, repeats included (A4-size pages use about 125,000 pixels each, so more than 133 do not fit) | `PDF_PIXEL_LIMIT` |
| Oversized or too-deep structure | `PDF_STRUCTURE_LIMIT`, `PDF_PAGE_TREE` |

Many ordinary PDFs (hyperlinked, tagged, form or layered documents, and pages with a transparency
group, which several common producers emit) therefore refuse. Supporting a page `/Group` would be
a separately reviewed extension, not a change to this route version. That is the honest first
release, not a defect to be worked around by editing the request.

Admission resolves inherited values from the page upwards through `/Parent`; QPDF assembles
top-down through `/Kids`. If a malformed PDF's `/Parent` does not lie on its `/Kids` path, the
page can pass admission, be assembled, and then fail the fresh verification with
`VERIFICATION_FAILED`. The same happens when a page's `/Rotate` is an indirect reference to null (or to
a missing object) while a page-tree node supplies a rotation: QPDF's JSON omits such a key, so admission
sees the inherited value, but MuPDF reads the page as unrotated and the two readers disagree about the
source rotation. In these cases the failed run directory may contain an `assembled.pdf`; its
`result.json` says `failed` and there is no receipt, so it is not a verified publication.

The scan is a bounded allow-list over QPDF's parsed structure. It checks field names, `/Type`,
`/Subtype` and `/S` values separately and ignores the arbitrary names used as keys of resource
maps. It does **not** inspect content-stream operators, fonts, images or colour management.

## Document-level losses

The output is a new document. The following are discarded, and the request records them:
document information, XMP metadata, outlines (bookmarks), named destinations, open actions,
document-level actions and JavaScript, viewer preferences, page layout and mode, language and
attachments; **page labels are always removed**. No link annotation can survive because
pages with annotations are refused. The published PDF is not encrypted and not linearised.

## Verification contract

`schemaxis verify` is not offline from the native applications: it needs the configured QPDF and
MuPDF, resolved from stored configuration, the invocation context or the documented environment
variables, **never from the receipt**. It reads the captured sources and published PDF once and
applies the same capture policy a run applies (standard `%PDF-` header, 16 MiB each, 32 MiB together;
a violation is `VERIFICATION_FAILED`), makes private copies of those exact bytes, and then, in
fresh bounded processes:

1. re-runs `qpdf --check` without recovery and bounded `qpdf --json` on every captured source and
   re-applies the admission above, then on the published PDF;
2. checks the published PDF's catalogue (only the page tree), trailer, page-tree membership and
   order, and each page's allow-listed keys, boxes, UserUnit and `Rotate = (source + rotate) mod 360`;
3. with MuPDF, renders each *captured source page* with its page-local `Rotate` overridden **in
   memory** (nothing is saved) and renders each published page, and requires identical 36 dpi RGB
   rasters, identical extracted text, identical native bounds and sizes, and agreement between QPDF and
   MuPDF about each source's original rotation. Raster sizes are predicted from the typed geometry
   and enforced before any raster is allocated.

The decision comes only from the authored request, the captured sources, the published bytes and
these fresh observations. Retained files are *consistency diagnostics*, and exactly these are
checked: `plan.json` equals the recomputed plan; `capture.json` matches the captured bytes;
`verification.json` lists exactly `assembled.pdf` and `assembly-summary.json` with their
current digests; `assembly-summary.json` equals the freshly recomputed summary; and the
digests of the retained evidence files are unchanged. The retained files are the authored input, plan,
capture record, captured sources, and the logs, launchers, input bindings and submissions of the run's
assembly-side stages only: the two version checks, each source's `qpdf --check` and JSON reads, and the
assembly. They are provenance, hash-bound but not re-interpreted. The observation stages (the published
PDF's check and JSON reads and the two MuPDF observers) run in a temporary directory that is removed, in
the run and in every verification, so their logs, scripts and rasters are **not** retained; only the
summary and any fault message survive.

What this proves: the current published bytes satisfy the captured request within the stated
envelope and appearance contract (bounded exact raster, text and geometry at 36 dpi, plus QPDF
structure checks). It does not prove full semantic equivalence, accessibility, colour management
or PDF conformance, is not a signature, and is not historical attestation: someone who rewrites the
request, the captured sources and the output consistently produces a new valid run. A missing or
wrong runtime, a timeout, or a cancellation faults (`INTERPRETER_NOT_FOUND`, `UNSUPPORTED_RUNTIME`,
`RUNNER_TIMED_OUT`, `RUNNER_CANCELLED`); none returns `verified`.

### The published summary and source identity

`assembly-summary.json` (`schemaxis.qpdf.summary/2`) is the per-page identity map handed to later
steps. Each entry of `sources` carries the authored `name`, the captured `bytes` count and `sha256`
of exactly the file the run captured, the page count and any discarded document data; each page
entry names its source, source page, rotation, geometry, 36 dpi raster digest and text length. Two
inputs that render identically but differ in bytes therefore publish different summaries, and a
consumer can match a page to its source by digest without reading the run's evidence folder.
Verification recomputes the summary from the captured bytes and requires equality, so a changed
digest, a missing digest or an unknown summary version is `VERIFICATION_FAILED`. Runs made before
this field existed publish `schemaxis.qpdf.summary/1` (no `bytes` or `sha256`); they are still
verified against the earlier shape and are not rewritten. The digest identifies the captured source
bytes; it is not a signature and not historical attestation.

## Limits, lifecycle and reuse

* Sources ≤ 16 MiB each, ≤ 32 MiB together, ≤ 500 pages each; ≤ 4 sources; ≤ 200 output pages; QPDF JSON
  ≤ 64 MiB, 128 nested containers and 200,000 objects; chains of objects that are only references ≤ 16, and references
  dereferenced along one resource path ≤ 32 deep.
* Every native stage runs under the shared cancellable runner with POSIX address-space (1 GiB QPDF,
  2 GiB MuPDF), file-size (64 MiB) and CPU (120 s) caps. A run's `--timeout` covers every launch
  including the post-assembly observation; standalone verification has its own cumulative 120-second
  budget, checked before each launch and after its final host work.
* **Cost of repeated fresh observation.** For *S* sources a run makes 2*S*+7 native launches and every
  fresh verification 2*S*+6. A normal run is also verified again by the shared runtime, so it makes about
  twice that; a scheduled workflow job adds a third pass and `schemaxis verify` of the workflow a fourth. The
  passes are deliberate (each reopens the actual bytes) and every one counts against the run's deadline: with
  two sources a run takes a few seconds and a standalone verification about two seconds on the tested
  machine, so size `--timeout` for the repeated passes.
* A run's `--timeout` may not exceed 3600 seconds (a larger or non-finite value is refused with
  `INVALID_ARGUMENT` before any effect). A finite study passes its remaining total budget to each visit, so
  a QPDF study should use a total timeout of at most 3600 seconds.
* Output is byte-deterministic for the same inputs and runtimes (`--deterministic-id`).
* Captured source bytes (not only paths) determine reuse: a changed file at the same path invalidates
  a reused workflow job.

## Workflow and handoff

[QPDF → MuPDF](../examples/schemaxis/qpdf-to-mupdf.json) binds the assembled `pdf` publication to a
MuPDF review through an artifact reference, so MuPDF reviews exactly the verified output.
[QPDF → QPDF](../examples/schemaxis/qpdf-chain.json) assembles from an earlier verified assembly (each hop
is re-captured and re-admitted). Shared expressions, references and finite visits are resolved
before planning.

## Maintenance

`upstream.json` targets QPDF's latest stable release (12.4.2 at the time of writing) and keeps the
absorbed version unset until bounded native acceptance and integration review pass. Qualification
covers the cases and runtimes named in the receipt, not all PDFs.
