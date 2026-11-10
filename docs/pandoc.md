# Pandoc structured reports

The `schemaxis.pandoc/1` document route publishes a small declared report as
standalone HTML5 and editable Word DOCX, and optionally EPUB 3 (see [EPUB 3 publication](#epub-3-publication)). Use it to package measured results with
an outline, explanatory paragraphs, text tables and a local figure, or a timed
transcript or caption table (see [Transcripts and captions](#transcripts-and-captions)),
or a retained whisper.cpp transcript (see [Publishing a whisper.cpp transcript](#publishing-a-whispercpp-transcript)). Pandoc runs in
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
65536 text characters, 8 images and 2 transcripts. Headings do not imply hidden nesting or page
breaks.

Content blocks have one of these closed forms:

| Kind | Fields and meaning |
| --- | --- |
| `paragraph` | Required `text`, at most 2048 characters, rendered as one paragraph. |
| `table` | Required 1–8 `columns` are the single header row. Required 1–64 `rows` contain exactly that many text cells. Each cell is nonempty and at most 256 characters. Numeric-looking cells remain text; formulas, merged cells and nested content are unsupported. |
| `image` | Required `source` is an absolute local `.png` path; required `alt` is plain descriptive text up to 256 characters. `widthMm` defaults to 80 and accepts 10–148 millimetres with at most five decimal places; the native image aspect ratio is retained. |
| `transcript` | Required `segments` object: required absolute `.json` `path` of a retained whisper.cpp `segments.json` and optional lowercase `sha256` pin, plus an optional `timeFormat` (`milliseconds` or `timecode`). Read at run time, never when planning; published as a provenance paragraph and a `Start`/`End`/`Text` table of integer milliseconds or HH:MM:SS.mmm (see [Publishing a whisper.cpp transcript](#publishing-a-whispercpp-transcript)). At most 2 per report. |

The 148 mm ceiling and five-decimal precision are what both publications can carry as authored: Pandoc 3.12.1's DOCX
writer clamps pictures to its page text width (148.17 mm) and its HTML writer keeps five decimals, so a wider or more
precise value could never be verified after a native run and is refused at planning instead. A report retained under the
earlier 150 mm ceiling is re-planned under that ceiling by `schemaxis verify`; its document evidence is still checked
exactly as before.

All authored text uses single ordinary spaces, no leading/trailing whitespace,
control characters or line breaks. XML/HTML punctuation such as `<`, `&` and `>`
is literal text, escaped by the writers. It is never parsed as markup. Planning
refuses a short explicit list of unsupported formatting characters:
bidirectional embeddings, overrides and isolates (U+202A–U+202E, U+2066–U+2069),
word joiner and invisible operators (U+2060–U+2064), byte order mark, the Mongolian
vowel separator, interlinear annotation, stray tag characters and noncharacters.
Ordinary multilingual text is accepted: the joiners and directional marks that
Persian, Hebrew, Arabic, Indic and emoji text rely on (U+200C ZWNJ, U+200D ZWJ,
U+200E LRM, U+200F RLM, U+061C Arabic letter mark); a zero-width space (U+200B)
only between Thai, Lao, Myanmar or Khmer characters, where it marks word breaks;
and well-formed emoji subdivision flags (U+1F3F4, three to six tag letters or
digits, U+E007F — England, Scotland and Wales). A zero-width space elsewhere, or a
tag character outside such a flag, is refused. This is a documented list of
unsupported formatting, **not** a Unicode-safety, confusable or anti-spoofing
policy: other invisible or lookalike characters (soft hyphen, Hangul fillers,
homoglyphs) are not detected, and no claim is made about how a viewer shapes,
reorders or falls back fonts for these characters. Rich text,
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

### Images from an earlier workflow step

In a workflow, an image block `source` may be the typed `image` artifact of an earlier
step instead of a path. [The decode example](../examples/schemaxis/pandoc-image-artifact.json)
decodes a WebP file with the WebP route's `decodeToPng` and publishes the verified PNG
(index 0 of that route) with `{"$artifact": "decode", "index": 0}` at the image `source`;
[the EPUB variant](../examples/schemaxis/pandoc-image-artifact-epub.json) adds an EPUB 3.
The report's publications are `report.html` (index 0), `report.docx` (1), the summary (2)
and, with `epub`, `report.epub` (3). Only the decoder (`--dwebp`) and Pandoc are needed;
no WebP encoder is involved.

The hand-off changes only how the path is supplied. The PNG is captured and held to every
limit above exactly like a path: plain 8-bit RGB/RGBA, at most 4 MiB (8 MiB in total),
2048 pixels per axis and no auxiliary chunks. The workflow checks the artifact *kind*, not the
field: an artifact of another kind (a table, audio, an archive, video, geometry or a generic
file) is refused with `TYPE_MISMATCH` before the report starts, a `text` artifact at an image
`source` is refused as `INVALID_REPORT_IMAGE` because it is not a `.png`, and a PNG that is too
large or not plain is refused, never rescaled or truncated. The WebP route may publish a PNG
of up to 5 MiB, so a large decoded picture can exceed the 4 MiB image limit and is then
refused. Place an image reference only at an image `source`; at another string field it
may be written as path text, while path fields retain their own checks: a PNG at transcript `segments.path` is refused as `INVALID_TRANSCRIPT_SOURCE`. The captured bytes come from the verified
producer publication, which is verified again, so a changed producer artifact is refused and a
changed source or producer output starts a fresh report run. This is semantic consistency with
the producing step, not signed authenticity of the picture, and transparency, colour and
rendering in Word or an e-reader are not certified.

## Transcripts and captions

A literal transcript or caption set needs no special field: to publish a retained
whisper.cpp transcript from its file, use the `transcript` block described in
[Publishing a whisper.cpp transcript](#publishing-a-whispercpp-transcript). Otherwise use one table whose header
row names the units and whose rows are utterances in time order, for example
[the transcript example](../examples/schemaxis/pandoc-transcript.json) with
`Start (ms)`, `End (ms)` and `Text` columns and cells `0`, `1250` and
`Good morning, and thank you for joining us.`. Times are text: write literal
elapsed milliseconds as digits, and say so in the header and an introductory
paragraph. The route never parses, converts, rounds, pads or reorders a time, and
it does not check that times ascend or that segments do not overlap; that belongs
to the producer. `007`, `1.50` and `1e3` are all kept exactly as written. Caption
cue timing in WebVTT or SRT form, speaker diarization and word-level times are
outside this contract.

[The multilingual transcript example](../examples/schemaxis/pandoc-multilingual-transcript.json)
keeps a Hebrew right-to-left mark, a Persian ZWNJ, an Indic ZWJ, a Thai zero-width
space and England, Scotland and Wales flag sequences. Its native acceptance
compares the retained HTML, DOCX and fresh DOCX readback with literal expectations
in the qualifier, which confirms the characters survive as text; it does not
establish how any viewer renders, shapes or reorders them.

Each cell holds one utterance of at most 256 characters in one line. Line breaks,
tabs and other control characters are refused rather than flattened, so split a
long or multi-line utterance into several rows. A table has at most 64 rows and a
report 128 content blocks and 65536 characters; divide a long transcript across
sections and several reports. Verification (below) rejects a publication whose
header row was demoted to a data row, whose cell was split over paragraphs or
changed by a character, or whose times or unit labels differ from the authored
values.

## Publishing a whisper.cpp transcript

A `transcript` content block publishes one retained
[whisper.cpp](whispercpp.md) `segments.json` without retyping it:

```json
{"kind": "transcript", "segments": {"path": "/absolute/path/to/segments.json", "sha256": "optional 64 lowercase hex digits"}}
```

[The artifact example](../examples/schemaxis/pandoc-transcript-artifact.json) shows the
block in a report; [the workflow example](../examples/schemaxis/pandoc-whisper-workflow.json)
transcribes a recording and passes the verified `segments.json` on with
`{"$artifact": "transcribe", "index": 0}` at `segments.path`. Index 0 is the whisper.cpp
route's `segments.json`; its `transcript.txt` (also a text artifact) is refused as
`INVALID_TRANSCRIPT_SOURCE` because its path does not end in `.json`. Other JSON text artifacts are parsed and refused with a `TIMED_TEXT_*` fault if they do not match the timed-transcript contract. The Pandoc route accepts the `text` artifact kind only for
this purpose (and the `image` kind only for an image `source`, below), but the workflow checks a handoff by kind, not by field, so a text artifact
reference placed at another string field of a report would be written as that field's
path text; use it only at `segments.path`.

**Planning reads no file.** Native-free planning checks only that `path` is an absolute
`.json` path without parent references and that an optional `sha256` is 64 lowercase
hexadecimal digits (`INVALID_TRANSCRIPT_SOURCE`, `INVALID_SHA256`). At most 2 transcript
blocks are allowed in a report (`REPORT_RESOURCE_LIMIT`). A valid plan therefore does not
prove the file exists.

**The run captures and validates the file.** The source is opened once, without following
links, and must be a regular file of at most 4 MiB. A missing file is
`TRANSCRIPT_SOURCE_MISSING`; a directory, link, special or oversize file is
`TRANSCRIPT_SOURCE_INVALID`. The bytes are checked against the optional pin
(`TIMED_TEXT_DIGEST_MISMATCH`), parsed as strict UTF-8 JSON and validated against the
closed contracts in `schemaxis.core.timed_text`: exactly the
`schemaxis.whispercpp.segments/1` members at every level, or exactly the `schemaxis.timedtext.reviewed/1` members (an extra or missing member, another
`version`, or any review status other than the uncertified machine draft on the machine version is refused as
`TIMED_TEXT_UNKNOWN_KEY`, `TIMED_TEXT_INVALID`, `TIMED_TEXT_UNSUPPORTED_VERSION` or
`TIMED_TEXT_REVIEW_UNSUPPORTED`), integral-millisecond cues with `0 <= startMs < endMs`,
non-overlapping and ordered inside the recorded audio duration (`TIMED_TEXT_TIMING`),
and nonblank plain cue text (`TIMED_TEXT_CUE_TEXT`). The producer's optional
`segmentation` cue-length target is accepted as its own closed member. Each fault carries a
location (for example `$.sections[0].content[1].segments.segments[3].text`) and recovery text.
Cue text must also pass this route's plain-text rule (single spaces, no unsupported
formatting characters), so a cue the route could not publish exactly is refused with its
location (`INVALID_REPORT_TEXT`) and is never altered. Nothing is repaired, dropped or
truncated.

**Budgets.** 4 MiB per document, 512 cues in total in a report, 256 characters per cue and
32768 cue characters per document, in addition to the report's 128 blocks and 65536 text
characters (the provenance paragraph and every table cell count). These are stricter than
the producer's limits; over-budget input is refused (`TIMED_TEXT_RESOURCE_LIMIT`,
`REPORT_RESOURCE_LIMIT`), so shorten the recording or split the transcript.

**What is published.** One provenance paragraph, then one table with the columns
`Start (ms)`, `End (ms)` and `Text`, using only the existing paragraph and table writers.
The paragraph states `Status: machine-draft`, that a person has not reviewed the
transcript and its accuracy is not certified, the language, cue count, audio duration, the
SHA-256 of the segments file, audio and model, and, when present, the cue-length target and
how many cues exceed it. Times are the exact integers from the file. **A machine draft is always
published as `Status: machine-draft`.**

**Time format.** `timeFormat` is optional on each transcript block. Leave it out, or write `"milliseconds"`, for the
columns above exactly as before: `Start (ms)`, `End (ms)` and the integer milliseconds recorded in the file. Write
`"timecode"` to publish every cue start and end as elapsed `HH:MM:SS.mmm` (hours, minutes, seconds and milliseconds
from the start of the recording) under the headers `Start (HH:MM:SS.mmm)` and `End (HH:MM:SS.mmm)`; the provenance
paragraph then shows the audio duration in the same form and says so. The conversion is integer division of the
recorded milliseconds, so `5410` is `00:00:05.410`, `3599999` is `00:59:59.999`, `3600000` is `01:00:00.000` and
`360000000` is `100:00:00.000` (hours are not capped or wrapped at two digits; the separator before the milliseconds
is a dot). Nothing is rounded or truncated, and the cue order, text, provenance, status and every source rule and
budget are unchanged; timecode text is longer than the integers, so it counts toward the report's 65536 characters
and a report that just fits in milliseconds can be refused with `REPORT_RESOURCE_LIMIT` as timecode. Each block
chooses on its own, so two blocks over the same pinned source may use different formats in one report ([the mixed
example](../examples/schemaxis/pandoc-transcript-mixed-formats.json); [the timecode
example](../examples/schemaxis/pandoc-transcript-timecode.json)). Any other value (a boolean, a number, another
name) is refused at planning as `INVALID_ARGUMENT` at `<transcript block>.timeFormat`, before any file or native
step. An explicit `timecode` adds one loss sentence to the plan (a reading format for the same cue times, not a
wall-clock time, caption file or accuracy, timing, readability or accessibility claim). The chosen format is retained
in `authored.json`, the plan, `captures.json` (as `timeFormat`, only when written) and, when any block wrote it,
`report-summary.json` (`transcriptTimeFormats`, one entry per transcript block in order, an absent field counting as
`milliseconds`) and the verification result. Without the field none of these changes by a byte.

**A reviewed transcript.** The block also accepts the `reviewed-segments.json` that the host-only
[whisper.cpp corrections route](whispercpp.md#human-corrections) publishes under the separate closed contract
`schemaxis.timedtext.reviewed/1` (the machine version still refuses review keys). Its paragraph states
`Status: human-corrected` or `Status: human-reviewed-unchanged`, that the status is declared by the author of the
corrections, the machine-draft basis SHA-256, how many cues were replaced and their indexes, the author's note in quotes,
and that who reviewed it, whether the audio was heard and whether the words are accurate are **not verified or
certified**. The cue table, times, language and digests are published as for a draft. Pandoc makes no accuracy,
identity or accessibility claim for either kind. [The corrected publishing workflow](../examples/schemaxis/whispercpp-corrections-workflow.json)
hands the corrections artifact to this block. The route adds one more transcript-loss sentence for new plans; plans
written before reviewed documents were accepted verify, including genuine machine-transcript runs whose report summary holds the earlier
sentence: that sentence is accepted only when every captured transcript is a machine draft, the stored losses are what the summary is
checked against, and a reviewed transcript carrying the earlier sentence is refused. The author's note is checked as Pandoc plain text
at `<transcript block>.segments.review.note` (an `INVALID_REPORT_TEXT` there is a note the corrections route would also refuse; the Pandoc
native contract itself is unchanged). The notes in the shipped examples are illustrative author declarations, not evidence that a
person reviewed the recording.

One earlier-grammar limit applies to verification only. A report written before the cue count was singular wrote "1 cues" in a
one-cue machine draft's provenance paragraph; `schemaxis verify` accepts that exact text for a transcript that is a one-cue
machine draft with no `timeFormat` or cue-length target, beside the earlier transcript loss wording stored in the report's plan, and
only when the retained AST, HTML, DOCX and readback all carry it. Every other difference still fails, whatever hashes are
recomputed; new reports always write "1 cue", and nothing in a retained report is rewritten.

**A reviewed/2 transcript.** The block also accepts `schemaxis.timedtext.reviewed/2` from the
[`correct/2` route](whispercpp.md#cue-deletion), which can delete cues. Its paragraph additionally states how many cues of the machine draft
the author deleted and their source indexes; the table lists only the retained cues, with their unchanged times. When the author deleted every
cue the document holds no cue, the paragraph says so (the author deleted every cue, so no cues are retained and no spoken words are published,
which is the author's declaration and not evidence that the recording holds no speech) and **no table is published**: the native readers require
a table to hold a header and a data row, so a header-only table is neither written nor accepted, and nothing is invented in its place. The
transcript loss sentence of the plan is unchanged and does not mention deletions, because planning never opens the file; the published paragraph
carries the facts. That literal sentence (one provenance paragraph and one three-column table) describes a machine draft, a reviewed/1 document
and a reviewed/2 document that keeps at least one cue; it is **not true of a reviewed/2 document whose every cue was deleted**, which publishes no
table, and the plan cannot know which case applies. The actual publication is therefore stated in `report-summary.json`: when at least one captured
transcript is reviewed/2, the summary gains `transcriptObservations`, one entry per such transcript in document order, each naming the block
(`$.sections[i].content[j]`), the source cue count, how many the author deleted, how many remain, and either that one table of the retained cues
follows the paragraph or that no table is published. `inspect` builds it from the validated retained document during both `run` and `verify`, and
`verify` compares the summary exactly, so an edited, added or removed observation fails with `VERIFICATION_FAILED`. The observations are authoritative
for the actual shape of a reviewed/2 report; the `tables` count in the same summary agrees with them. Summaries of machine-draft and reviewed/1
reports have no such member and are byte-for-byte what they were. A reviewed/2 transcript is never accepted with the earlier machine-draft loss sentence.

Pandoc trusts the reviewed/2 mapping as declared. It reads closed, typed JSON and checks that the document is internally consistent (the deleted
and retained source indexes partition the stated cue count, the counts agree, the status fits), which is semantic consistency of that one file only; it does not
open the original machine draft and does not authenticate the mapping to it, and the captured file sits in the same writable directory as the
rest of the report. A hand-written but consistent reviewed/2 file would therefore be published as "N of M deleted by the author". Only replaying the
correction job (verifying the `correct/2` job directory replays from its captured draft), or a workflow that reopens the retained original `draft.path`, ties the
deletion to the machine draft. The same trust model applies to reviewed/1. Pandoc makes no accuracy, identity or
accessibility claim for it. The [every-cue](../examples/schemaxis/whispercpp-deletions-workflow.json) and
[partial](../examples/schemaxis/whispercpp-deletions-partial-workflow.json) workflows hand the artifact to this block.

**A reviewed/3 transcript.** The block also accepts `schemaxis.timedtext.reviewed/3` from the [`correct/3` route](whispercpp.md#cue-timing-edits),
which lets the author state new cue times. Its paragraph keeps the reviewed/2 facts and additionally says, when any time was edited, that
N cues were given author-edited start and end times (their source cue indexes) and that the times shown for them are edited times recorded in
this document as the author's, not the machine draft's, and that the original machine times are not shown in the report; the other retained cues
are said to show the original machine times as recorded in this document. When none was edited it says the author edited no cue times and the times
shown are the machine draft's originals as recorded in this document, which Pandoc did not check against the draft file; when every cue was deleted no
time is shown and none is described. These statements describe what the validated reviewed document records, not an authenticated link to the
machine draft. It never says the machine timing was preserved, and when any time is shown it states that whether any time is synchronized with the
audio is neither verified nor certified. The table lists the retained cues in published order with the exact edited integer milliseconds (or the
`HH:MM:SS.mmm` form under `timeFormat: "timecode"`); the HTML, DOCX and optional EPUB tables carry those exact values. For a reviewed/3 transcript the
`transcript` summary entry gains `sourceCues`, `deletedCues`, `timingEditedCues` and `timingEditedSourceIndices` (integers), and `transcriptObservations`
gains an entry that branches on the edit count: with edits it names the edited source cues as recorded in the document, with none it says no cue
times were edited by the author, and when every cue was deleted it says no cue times are shown. The plan's transcript loss sentence is again unchanged, so a stored plan keeps verifying; summaries of
machine-draft, reviewed/1 and reviewed/2 reports are byte-for-byte what they were. The trust model is that of reviewed/2: Pandoc checks the file's
internal consistency (the recorded original times, the edited indexes and the published times agree) but does not open the machine draft, so only replaying
the correction job ties the edited times to it.

**Binding and verification.** The captured bytes are retained as `transcript-<section>-<block>.json`
and their SHA-256, size, cue and character counts are recorded in `captures.json`. Verification
re-validates the retained bytes, compares them with the capture record and the pin, rebuilds the
paragraph, table and trusted AST from them, and checks HTML, DOCX and fresh Pandoc readback
against those exact cells and times. A changed capture, record, pin, plan or output fails as
`VERIFICATION_FAILED`. Workflow reuse hashes the current source bytes, so a changed
`segments.json` forces a fresh run. Reports without a transcript block, and transcript blocks without `timeFormat`, plan and verify exactly
as before.

Limits: only the plain text and times of the cues are published (no speakers, word times,
confidence or caption cue formats), cue text is published as written (a doubled space is refused,
not collapsed), and Pandoc typography and pagination remain defaults. The qualified source is
whisper.cpp 1.9.5 evidence with Pandoc 3.12.1; a changed producer document needs a reviewed
contract update.

## EPUB 3 publication

Add the optional `epub` object to also publish `report.epub`:

```json
"epub": {"language": "fr-CA"}
```

`language` is required whenever `epub` is present, and it is the only field
accepted. It is a plain ASCII language tag: a two or three letter primary subtag and
up to three hyphen subtags of two to eight letters or digits, at most 35 characters
(`en`, `fr-CA`, `zh-Hans-CN`). It is your declaration of the language of the text;
the route does not detect the language, check that the text is in it or certify its
accuracy. Covers, fonts, styles, templates, filters and paths are refused, not ignored, and
`epub` itself accepts no authors or metadata: credit the report with the report-level
[`metadata`](#authors-and-description) object instead. See [the example](../examples/schemaxis/pandoc-report-epub.json)
and, for the refusal, [an invalid language](../examples/schemaxis/pandoc-report-epub-invalid.json).

Without `epub` nothing changes: the plan, capture records, summary, result,
`report.html`, `report.docx` and the artifact order are exactly those of a report
that never had the field. With it, `report.epub` is appended as the fourth artifact,
after the HTML (index 0), DOCX (1) and `report-summary.json` (2). It is written by
the official Pandoc EPUB 3 writer from the same trusted JSON AST as the other two
files, so the title, headings, paragraphs, tables, embedded PNG images and
transcripts (including the empty and timecode forms) appear in authored order, one
chapter file per level 1 section, with Pandoc's default stylesheet and navigation.
The text and image budgets are the report's existing budgets (at most 32 sections, 128
blocks, 65536 characters, 8 images of 4 MiB each and 8 MiB combined). The package is
refused, never truncated, beyond 96 members, 32 MiB uncompressed, 8 MiB per text part
and 4 MiB per image; those limits only guard against tampered or unexpected writer
output, which a report within its budgets does not reach.

The package is then inspected by independent host code and by a fresh Pandoc reader
(`-fepub -tjson --sandbox`), whose JSON is retained as evidence and is not a
publication. The host reads the actual ZIP bytes, not only the central directory: no
prefix, suffix or hidden bytes (the members tile the file exactly from offset 0 to the
central directory, which is directly followed by the end record); every local header
repeats its central entry (version, flags, method, time, name, CRC-32 and sizes, with a
lawful data descriptor allowed), with no extra fields, comments or ZIP64; a stored
`mimetype` first at offset 0 with exactly
`application/epub+zip`; bounded, regular, unique members with safe names (no symlinks,
encryption, backslashes or parent paths); a closed member set; the pinned writer
parts; the container, the OPF identifier, title and language, manifest, spine and
navigation cross-references; and the XHTML chapters, whose headings, paragraphs,
table cells and image elements must equal the authored values exactly, with each PNG
compared byte for byte. Scripts, external resources, DTDs and entities, comments,
SVG, fonts and edited styles are refused; only the exact HTML5 doctype that the writer
emits is accepted. Pandoc writes its own fixed 1970-01-01 dates and default
accessibility metadata, which are not claims by Schemaxis.

This is a bounded package and content proof only. It is not EPUBCheck conformance,
reading-system or device rendering, accessibility conformance, or a language
accuracy claim, and no Calibre or other converter is involved. As for the other
publications, the retained run directory is an unauthenticated trust anchor:
recomputing every receipt and evidence digest coherently is not detected as
tampering by verification alone.

## Authors and description

The optional report-level `metadata` object credits the report with ordered authors and a short
description, carried consistently by `report.html`, `report.docx` and, with `epub`, `report.epub`:

```json
"metadata": {"authors": ["A. Example", "B. Auteur"], "description": "Measured calibration readings for three temperatures."}
```

[The example](../examples/schemaxis/pandoc-report-metadata.json) publishes HTML and DOCX;
[the EPUB variant](../examples/schemaxis/pandoc-report-metadata-epub.json) changes the authors, their order and
the description and also publishes an EPUB 3. Both fields are optional but an empty object is refused (omit `metadata`
instead), and no other key is accepted.

**Contract.** `authors` is a list of 1–8 names; each is plain Unicode text of 1–100 characters under the report's
text rule (single spaces, no leading or trailing space, no controls, line breaks or tabs, none of the unsupported
formatting characters listed above). Order is kept exactly as written and is the order of publication. Names are compared
exactly (case, accents and spacing included): the same name twice is refused, so tell two people with one name apart
in the text. A semicolon is refused inside a name, because Word stores the creator list as one string joined with
semicolons and a name containing one could not be told from two authors. `description` is one plain-text paragraph of
1–1000 characters under the same rule; a semicolon is allowed there. Characters, not bytes, are counted. Types are strict:
booleans, numbers, `null`, objects and empty strings are refused (`INVALID_ARGUMENT` at the offending value, for example
`$.metadata.authors[2]`), a key other than `authors` and `description` is `UNKNOWN_ARGUMENT` at `$.metadata`, an empty
object is `MISSING_ARGUMENT`, and text that breaks the plain-text rule is `INVALID_REPORT_TEXT`. Text is never parsed:
`<`, `&`, quotation marks, Markdown and URLs are literal characters, with no markup, links, scripts, identifiers,
dates, rights, keywords or other metadata fields. The authors and description count toward the report's 65536 text
characters, so a report that just fits without them can be refused with `REPORT_RESOURCE_LIMIT`.

**What is published.** Pandoc 3.12.1's writers receive `author` (a list) and `description` in the report's trusted JSON
AST metadata and write: in HTML, one `author` and one `description` meta element in the head and one visible
`<p class="author">` line per author in the title block (the description is not shown in the body text); in DOCX, the core
properties creator (authors joined with `; `) and description, and one `Author`-style paragraph per author between the title and the
first section; in EPUB, one `dc:creator` per author (Pandoc adds the `marc:relators` role `aut`), one `dc:description`, and one
author line each on the title page. Pandoc's other fixed output (generator name, 1970-01-01 dates, default EPUB accessibility
metadata) is Pandoc's own and not an author declaration.

**What is verified.** Verification does not merely reread what the writer wrote. Independent host parsers read the HTML
head and title block, the DOCX `docProps/core.xml` and body, and the EPUB OPF and title page and require exactly the declared
authors in order, the declared description, and nothing else: a missing, extra, stale, reordered, restyled or linked author, a
changed or removed description, an injected keyword or an undeclared creator in a report without the field are all refused,
even when every receipt hash is recomputed. The fresh Pandoc DOCX and EPUB readbacks are compared too. The DOCX reader returns the
authors but not the description, so the description is checked in the document properties only; Pandoc 3.12.1's EPUB reader returns
creators in reverse of their package order, which the check requires explicitly (the package order is verified independently).
The capture record `captures.json` gains a `metadata` member (the exact text, its character count and the SHA-256 of its canonical
JSON), `report-summary.json` gains `metadata` (author count, whether a description was declared, characters and the formats read
back) and the run result repeats it, and the plan gains one loss sentence; a changed author, order or description changes the
plan, capture, summary and every publication.

**Declarations, not claims.** The authors and description are declarations by whoever wrote the report. Nothing
verifies who the authors are, that they wrote or approved the report, or that the description is accurate, and the description
implies no accessibility, review or peer review. Which application shows, sorts or indexes the creators or description is outside
this route, and none was tested.

**Compatibility.** Without `metadata` nothing changes: the plan, capture record, summary, result, commands, launchers, trusted AST,
publications and artifact order are byte for byte those of a report that never had the field, and earlier retained runs verify as
before (a retained run is not made to verify as one that declared metadata, and a forged `metadata` in an earlier run is refused). The
document, plan and summary versions are unchanged because the field is an additive optional member: a report that declares it is
refused with `UNKNOWN_ARGUMENT` by an earlier Schemaxis, never silently published without its credits, and no historical receipt is
rewritten. [An invalid semicolon](../examples/schemaxis/pandoc-report-metadata-invalid.json) and [a boolean
list](../examples/schemaxis/pandoc-report-metadata-type-invalid.json) are refused at planning. `tools/qualify_pandoc_metadata.py` runs the
bounded native acceptance; see [the verification note](../verification/2026-10-26-pandoc-62.md).

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
text, table cells and image alt text. Text is compared exactly, with no whitespace
normalisation. Tables must be one header row of header cells followed by one body
group of data cells: HTML needs one `thead` row of `th` and a `tbody` of `td` with
text-only cells; DOCX needs a flagged first header row, unflagged data rows, the
declared grid width and exactly one plain-text paragraph per cell; the fresh native
readback needs one head row, one body, no footer and no row-head columns. DOCX
paragraphs may carry only a style, bookmarks and runs of plain text, with
no run properties other than Pandoc's East Asian font hint. A drawing is accepted
only in a declared image paragraph: one run holding exactly one inline picture with
one plain blip (no anchored or floating shapes, transparency or other blip children),
never in a text paragraph, title or table cell, and the whole document's drawings
and blips must equal the declared images. The only relationship reference in the
body is each picture's `r:embed`. HTML must contain PNG data URIs; OOXML must
contain internal media relationships with exact PNG bytes and declared physical
width. Pandoc stores byte-identical images once, so pictures may share a media part. A fresh native DOCX-to-AST conversion repeats the semantic check and
compares extracted image bytes. The HTML must contain exactly the reviewed default
stylesheet from qualified Pandoc 3.12.1. Its SHA-256 fingerprint is held in trusted
adaptor code, so a refreshed run receipt cannot approve CSS that hides content. An
upstream release that changes this stylesheet fails verification until its default
styles have been reviewed and the native route requalified. This checks actual documents against authored
values, beyond file existence, a native exit code or a producer summary.

Verification also treats the retained directory as untrusted. Standalone HTML
must be exactly one `html` with a `head` and `body`: no comments, processing
instructions, stray text or elements outside the reviewed structure (text beside
`body`, `header`, `table` and row containers is refused because browsers still
display it), and element nesting is bounded. A DOCX package is closed: exactly
Pandoc's writer members plus the declared PNG media (no macros, embedded objects,
custom XML, headers/footers, orphan or extra parts); every relationship has one of
the reviewed types with Pandoc's fixed target, once, and no external or re-pointed
targets; the content-type defaults and overrides are exact (media is `image/png`);
`docProps/core.xml` holds only the report title; and the styles, theme, settings,
numbering, font table, web settings, footnote, comment and application/custom
property parts must equal the reviewed Pandoc 3.12.1 bytes (SHA-256 fingerprints
held in trusted code, like the HTML stylesheet), because those parts decide fonts,
colours and visibility. Encrypted or unsupported-compression members are refused.
These are XML and package checks; they are not a rendering check, and no visual,
Word-application or layout behaviour is certified. Retained JSON is read with duplicate keys, non-finite constants and
excessive nesting refused. The output directory must hold only declared
publications, native evidence and the common publication metadata, and the
extracted `reopened/` media must be exactly the images found in the readback.
Any other exception raised while inspecting retained bytes is reported as a
structured `VERIFICATION_FAILED` rather than escaping. These package and HTML
shapes are reviewed against Pandoc output, so a release that emits new package
parts or HTML structure fails verification until reviewed and requalified.

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
`INVALID_REPORT_TEXT` needs plain single-space text; do not put line breaks,
unsupported formatting characters (bidirectional overrides, embeddings or isolates, word
joiner, a zero-width space outside Thai, Lao, Myanmar or Khmer text, stray tag
characters), or markup instructions in a text field (the location names the table cell, so a multi-line utterance becomes rows). `INVALID_REPORT_IMAGE` needs a regular plain
PNG within the documented limits; symlinks, URLs and unsupported PNG chunks are
rejected. A `widthMm` with more than five decimal places is refused at the same code (its location ends in `.widthMm`); round it. `REPORT_RESOURCE_LIMIT` needs a smaller report (fewer transcripts, cues or characters, noting that timecodes are longer than milliseconds). An `INVALID_ARGUMENT` whose location ends in `.timeFormat` needs `milliseconds` or `timecode`. An `INVALID_ARGUMENT` at `$.epub.language` needs a plain ASCII tag such as `en` or `fr-CA` (no underscores, spaces, booleans or full language names); an `UNKNOWN_ARGUMENT` at `$.epub` means a field other than `language` was supplied; omit `epub` to publish no EPUB. `TRANSCRIPT_SOURCE_MISSING`, `TRANSCRIPT_SOURCE_INVALID` and `INVALID_TRANSCRIPT_SOURCE` mean the named segments.json is absent, unusable or not an absolute `.json` path; the `TIMED_TEXT_*` codes mean the file is neither the unedited machine-draft document nor a valid reviewed document described above, and their location names the member or cue to correct at the producer. `VERIFICATION_FAILED`
requires retaining the attempt and investigating the document/readback mismatch;
changing a receipt is not recovery. `INTERPRETER_NOT_FOUND` needs an absolute
working executable. `INVALID_ARGUMENT` at `$.metadata`, `$.metadata.authors` or one author or the description needs the documented type and length, no semicolon in an author and no repeated author; `UNKNOWN_ARGUMENT` at `$.metadata` means a key other than `authors` and `description`; `MISSING_ARGUMENT` there means an empty object (omit `metadata`); `INVALID_REPORT_TEXT` there needs single-space plain text. `UNSUPPORTED_NATIVE_BUILD` means the selected Pandoc cannot
write the closed report under `--sandbox` because its default data files are not
embedded, as in some distribution packages (the message reports `Could not find
data file`); select the official self-contained binary. The route never relaxes
the sandbox or points Pandoc at a user or system data directory, and the failed
attempt is retained. Timeout/cancellation requires a fresh output directory.

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

Unmapped floating-table, section/page-size, hidden-picture and picture-crop
controls are refused in retained DOCX. These are bounded XML checks of the
qualified writer's output, not a proof of Word rendering, pagination or font
availability on a recipient's machine.
