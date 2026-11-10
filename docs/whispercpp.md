# whisper.cpp offline transcription

The `schemaxis.whispercpp/1` document transcribes one local speech recording into
checked millisecond segments, plain text, SRT captions and WebVTT captions. The
native [whisper.cpp](https://github.com/ggml-org/whisper.cpp) command-line tool runs
offline in its own process. The document supplies the audio, a pinned model and a
language and, optionally, a caption review report and a cue segmentation target; it never supplies prompts, native flags or code.

**Recognition accuracy is not certified.** Hashes, strict structure, timing bounds
and exact file agreement show that the published files were derived consistently from
one recorded native run. They do not show that the words are right. A person must
review the transcript and captions against the audio before relying on them.

## Requirements and scope

The native runtime is the `whisper-cli` executable of
[whisper.cpp 1.9.5](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5),
the latest stable release checked on 24 October 2026 (tag `v1.9.5`, commit
`d1be6fd`). Configure an absolute executable with the shared configuration, pass
`--whispercpp`, or set `SCHEMAXIS_WHISPERCPP`. Host planning, discovery and Studio use
the Python 3.10+ standard library only and never import or probe the native tool.

The tool reports its version as `whisper.cpp version: 1.9.5-dev` when built from the
`v1.9.5` tag with upstream defaults, because the upstream CMake option
`WHISPER_BUILD_IS_DEV` defaults to on. A build with that option off reports `1.9.5`.
This route accepts exactly those two strings and records the observed one in its
receipt; a version string cannot by itself prove which commit was built. Other
releases, including 1.9.4, are refused with `UNSUPPORTED_NATIVE_VERSION`.

Audio must be a canonical little-endian RIFF WAV with signed 16-bit PCM, one channel
and exactly 16000 Hz, at most 600 seconds and 32 MiB. The model is an explicit local
ggml `.bin` file of at most 4 GiB. Nothing is downloaded, and no remote service is
contacted. Convert other formats/rates/channels with an explicitly selected external audio
tool first. The current SoX adaptor edits PCM16 sample frames; it does not resample
or mix channels. Transcription uses the CPU, one thread, one processor and whisper.cpp
default decoding. Prompts, translation, diarisation, voice-activity detection,
grammar constraints, language detection, word timestamps and authored native flags
are not supported. The one option that changes the native command line is the
optional [`maxSegmentLength`](#caption-segmentation-target) target.

## Document fields

Set `operation` to `transcribe`.

`audio.path` is an absolute `.wav` path. `audio.sha256` is an optional lowercase
SHA-256 of the exact WAV bytes; when given, a mismatch stops the run with
`AUDIO_HASH_MISMATCH`. The runner captures the audio before native execution and the
native tool reads only the captured copy.

`model.path` is an absolute `.bin` path and `model.sha256` is required. The model is
not copied. The runner hashes it, the trusted launcher hashes it again and passes the
native tool the already-opened file descriptor, so the bytes hashed are the bytes
loaded, even if the path is later replaced. The runner hashes the model a third time
after the run and records size, inode and modification time before and after. Any
difference is `MODEL_CHANGED`. Modifying a file in place while it is being read is
detected, not prevented.

`language` is one of the 100 canonical lowercase codes in `g_lang` of whisper.cpp
v1.9.5 (`schemaxis.adaptors.whispercpp.languages`), default `en`. The set is static and
release-bound: planning and discovery read no model, run no native code and use no
network. Anything else is refused as `INVALID_LANGUAGE` at `$.language` before any
file is read: an unknown code such as `zz` or `zzz`, a full name (`english`), uppercase
(`EN`), `auto` (no language detection), padding, and any non-string including `null`
and booleans. No alias mapping is applied; upstream lists `he` (Hebrew, not `iw`),
`jw` (Javanese) and `yue` (Cantonese). The native CLI refuses an unknown code only
after the inputs are prepared, and exits 0 without writing results, so the host
refuses it first.

A listed code means only that this whisper.cpp release knows it. It does not certify
that the selected model is multilingual or that recognition in that language is
accurate. The native JSON must report that same language and no translation. An
English-only (`.en`) model cannot transcribe other languages.

## Segments and captions

The closed `schemaxis.whispercpp.segments/1` contract records `index`, `startMs`,
`endMs` and `text` for each segment, in integral milliseconds, plus the audio and
model hashes, the audio duration and a review block that states that accuracy is not
certified. The host parses whisper.cpp's JSON strictly: UTF-8 without a byte-order
mark, no duplicate keys, no non-finite numbers, and exactly the expected members at
every level. Timestamp text must equal the integer offset formatted by the host.

Timing policy: `0 <= startMs < endMs`; each start is at or after the previous end;
each end is at most the audio duration rounded up to a millisecond (no additional timing slack). Empty,
unordered, overlapping, zero-length or beyond-duration segments are refused and never
repaired. At most 2000 segments and 262144 characters are accepted. Segment text has
surrounding spaces removed and must be non-empty, free of control, line-separator and
replacement characters and free of angle brackets, braces, bidirectional overrides/isolates and the caption marker `-->` (SRT players may interpret markup or positioning commands). A run with no speech
segments fails with `TRANSCRIPT_EMPTY`; no empty captions are published.

A cue must also show something. Text made only of spaces, zero-width or other format
characters, soft hyphens, fillers (Hangul filler, Braille blank), variation selectors
or combining marks with no base character is refused as `TRANSCRIPT_INVALID`.
Cues made only of private-use or noncharacter code points are also refused; those
code points remain legal beside ordinary visible text, preserving the existing
UTF-8 contract. Format characters stay legal inside visible text (for example the
joiner in an emoji sequence). Unassigned code points count as visible. Newly
assigned marks or format characters can therefore be classified differently across
hosts with different Unicode databases; this is not a font or rendering test. Non-speech annotations
such as `[BLANK_AUDIO]` are visible text and are published unchanged; deciding
whether to keep them is an editing task. The fault's `location` is the cue
(`$.transcription[N].text`) and `observed` lists its first code points as `U+XXXX`.

`transcript.txt` has one line per segment. `captions.srt` and `captions.vtt` use LF
line endings and UTF-8. WebVTT escapes `&`, `<` and `>`. All three are generated by the
host from the checked segments, not copied from the native tool. The native tool's
own SRT file is compared byte-for-byte with an SRT reconstructed from its own JSON,
which cross-checks the two native outputs and the host's formatting.

## Caption review

`captionReview` is an optional boolean, default `false`. Omitted or `false`, the run
publishes exactly the four files above. Omitting the option preserves the previous
plan, receipt and result; explicit `false` is retained in the plan and disables the
report. When `true`, one more publication, `caption-review.json`
(`schemaxis.whispercpp.caption-review/1`), is generated by the host from the checked
segments and is listed fifth in the receipt's artifacts. It never changes words,
timing, `segments.json`, the transcript or either caption file, and it adds no native
option: the native command is unchanged.

Each cue gets `index`, `startMs`, `endMs`, `durationMs`, `codePoints`,
`codePointsPerSecondMilli` and `flags`. Three fixed flags exist, in this order:

| Flag | Raised when |
|---|---|
| `short-duration` | `durationMs < 1000` |
| `long-duration` | `durationMs > 7000` |
| `dense-text` | `codePoints > 20` per second, that is `codePoints * 1000 > 20 * durationMs` |

`codePoints` is the number of Unicode code points in the published cue text, counting
spaces and punctuation once each. It is explicitly **not** a count of grapheme
clusters or display width: a combining sequence counts each mark, an emoji sequence
counts each scalar, and wide scripts are not weighted. `codePointsPerSecondMilli` is
`floor(codePoints * 1000000 / durationMs)`, an integer, so the report holds no floating
point and the flag comparison is exact. The report also states the policy, the
counts per flag, the SHA-256 of the canonical `segments.json` it was derived from and
a review block with `passCertified`, `accuracyCertified`, `accessibilityCertified` and
`readabilityCertified` all `false` and `humanReviewRequired` `true`.

**These thresholds are our editorial defaults.** They are not requirements of SRT,
[WebVTT](https://www.w3.org/TR/webvtt1/) (a W3C Candidate Recommendation Draft at the
time of writing, May 2026) or any accessibility standard, and no source is claimed for
the numbers. They are not configurable: a fixed policy keeps reports comparable and
the independent check simple. Treat a flag as a place to look first. Zero flags is not
a pass and does not mean the captions are accurate, readable or accessible; human
review is always required. In the two qualified samples whisper.cpp emitted one cue of
8 to 11 seconds each, which the long-duration flag reports. The optional
[`maxSegmentLength`](#caption-segmentation-target) asks whisper.cpp to split such a
cue at word boundaries; otherwise splitting it is an editing task this adaptor does not do.

Verification rebuilds the report from the independently checked segments and requires
the retained file to match it byte for byte after a strict check of member names and
JSON types, so a forged metric, flag, count, policy value or review claim fails even if
every hash is refreshed. The file must be present exactly when the authored plan asks
for it: a stray report in a run without the option, or a missing report in a run with
it, is `VERIFICATION_FAILED`. The result then also carries a `captionReview` object of
counts only (`cues`, `flaggedCues`, `flagCounts`), never an overall verdict. Up to 2000
cues keep the report well within the 4 MiB JSON budget.

## Caption segmentation target

`maxSegmentLength` is an optional integer from 16 to 200. Omitted, nothing changes:
no `-ml` or `-sow` is passed, and the plan, launcher, segments, receipt and result are
byte-for-byte those of earlier runs. When authored, the native command gains
`-ml N -sow` (always together, so splits are word-aware), the effective plan keeps the
value and one more loss statement, `segments.json` gains a `segmentation` member, and
the result gains a `segmentation` object. Booleans, decimals, text, `null` and values
outside 16 to 200 are rejected with `INVALID_ARGUMENT` at `$.arguments.maxSegmentLength`.

**It is a target, not a guaranteed maximum.** The semantics below were read from the
official `v1.9.5` source (`src/whisper.cpp` `whisper_wrap_segment` and `utf8_len`;
`examples/cli/cli.cpp` option help) and observed with the native CLI:

- **Unit.** The CLI help says "maximum segment length in characters". The count is of
  UTF-8 *characters*, not bytes: for each token it counts the bytes that are not
  UTF-8 continuation bytes (`10xxxxxx`), that is Unicode code points. It is not a count
  of grapheme clusters or display width, and it includes the leading space that
  whisper.cpp keeps at the front of most words.
- **Where it splits.** Walking a segment's tokens, whisper.cpp starts a new cue before
  token *i* when the running count plus that token's count is above N, *i* is not the
  first token, and, because of `-sow`, the token's text starts with a space. A word is
  therefore never split. A single word longer than N, or any stretch with no
  space-led token, stays in one cue longer than N.
- **Unspaced scripts.** Chinese, Japanese, Thai and similar text rarely has space-led
  tokens, so cues in those languages can be far longer than N. This follows from the
  source; no multilingual model was run for this option, and no multilingual
  recognition claim is made.
- **Why `-sow` is always on.** Without it whisper.cpp may split between tokens inside
  a multi-byte character, which would produce invalid UTF-8. Schemaxis does not offer
  that mode.
- **Timing.** `-ml` turns on whisper.cpp's experimental token-level timestamps, and
  the cue boundaries come from them. The option can also shift the start and end of
  cues that are not split. The host still applies its full timing policy (ordered,
  non-overlapping, positive duration, within the audio) and refuses violations; it
  cannot show that a boundary is aligned with the audio. Treat timing as native
  observed, not certified.

The host never refuses a cue for exceeding N. `segmentation` in `segments.json` records
`maxSegmentLength`, the native options, `enforced: false`, the counting rule, the number
of cues and `cuesOverTarget`, the number of published cues whose code point count
(surrounding spaces removed) is above N. Because whisper.cpp also counts each leading
space, its own count is never lower, so a cue over the target here was over it
natively too. The count is an observation, not a check. Verification rebuilds the
member from the checked segments, so a forged target, count or `enforced` claim fails
even with refreshed hashes, and the argv with `-ml N -sow` must match the authored
value exactly.

Observed with whisper.cpp 1.9.5 (reported as `1.9.5-dev` by the upstream build) and
ggml-base.en on the public sample: without the option, one cue of 11000 ms. With
`maxSegmentLength: 42`, three cues (0 to 5410, 5410 to 9040, 9040 to 11000 ms), each under
42 code points. This shows what the option did for this fixture, model and runtime; it
does not certify accuracy, readability or accessibility, and the words remain an
unreviewed machine draft that a person must check against the audio. It combines with
`captionReview`, which then reports on the shorter cues; the review flags and their
fixed thresholds are unchanged.

## Human corrections

`schemaxis.whispercpp.correct/1` is a separate route of the whisper.cpp provider. It is
**host-only**: `whisper-cli` is never launched, and no audio file, model or recognition run
is read. It takes one retained machine `segments.json` (the file the transcription route
published, or any other copy with the same bytes), pins its SHA-256, applies authored
per-cue text replacements, and publishes the result under a new contract. It has no
native qualification record. Provider-level transcription qualification
says nothing about it, so its native axis stays unknown. Its proof is the host tests,
the replay below and a bounded acceptance (`tools/qualify_whispercpp.py --corrections-only`).

```json
{"version": "schemaxis.whispercpp.correct/1",
 "draft": {"path": "/abs/segments.json"},
 "basisSha256": "<sha256 of that exact draft>",
 "review": {"status": "human-corrected", "note": "Illustrative example declaration; no person reviewed this recording for it."},
 "corrections": [{"index": 0, "text": "And so, my fellow Americans: ask not what"}],
 "captionReview": true}
```

- `draft.path` and `basisSha256`: the draft is captured at run time and its bytes must hash
  to `basisSha256`. A different draft is `CORRECTIONS_STALE`, never corrected silently.
  Planning checks shape only and never opens the draft. A workflow may supply the path with
  `{"$artifact":"transcribe","index":0}`, but the pin is a literal you copy from the draft you
  reviewed.
- `review.status`: `human-corrected` needs at least one correction; `human-reviewed-unchanged`
  needs none. Anything else is refused. **The status is a declaration by whoever authored
  the document.** Schemaxis does not verify who reviewed the transcript, that the audio
  was heard, or that any word is right. The status is provenance, not accuracy, identity or
  accessibility certification.
- `review.note`: required plain text, 1 to 500 characters, single spaces, no markup brackets,
  controls, line breaks or the caption arrow. The note is also published as Pandoc plain text, so
  it is stricter than a cue: the only whitespace is a plain space (no tab, no-break space or
  ideographic space) and format controls (zero-width joiners, word joiner, byte order mark,
  bidirectional marks), private-use characters and noncharacters are refused with
  `CORRECTIONS_NOTE_INVALID` at `$.review.note`. Cue text keeps the wider Unicode the machine
  contract allows; Pandoc checks a published note again at `<transcript block>.segments.review.note`.
- `corrections`: `{index, text}` entries only; no other key, so timings cannot be edited. Each
  index is unique and must exist in the draft; each text must differ from the cue it replaces,
  have visible content and no surrounding space, and meet the same cue rules as the
  machine contract (at most 256 characters per cue, 32768 in total). When the corrected cues
  would exceed the total, the refusal is `TIMED_TEXT_RESOURCE_LIMIT` at the `$.corrections[n].text`
  that adds the most characters, judged on the finished cue list, so shortening any other
  replacement also resolves it. Splits, merges and insertions are out of scope, and this route cannot delete a cue (a
  blank replacement is refused); explicit deletion is the separate [`correct/2` route](#cue-deletion).
- `captionReview`: optional; recomputes the editorial duration and density flags on the
  corrected text. It is triage, not a pass.

The route publishes, in this order: `reviewed-segments.json` (kind `text`, artifact index 0),
`transcript.txt`, `captions.srt`, `captions.vtt`, `corrections.json` and, with `captionReview`,
`caption-review.json`.

`reviewed-segments.json` uses the new closed contract `schemaxis.timedtext.reviewed/1`,
read by the shared validator (`schemaxis.core.timed_text`). It carries the draft's language,
audio and model provenance and every timing unchanged, the corrected cues, and a closed
`review` object: `status`, `accuracyCertified: false`, `identityVerified: false`, the note,
the machine-draft `basis` (version, SHA-256, bytes), `correctionCount` and
`correctedIndices`. A cue-length `segmentation` member, when the draft had one, is kept and
`cuesOverTarget` is recounted on the corrected text. The machine version
`schemaxis.whispercpp.segments/1` is unchanged and still refuses every review key. A
reviewed document is not accepted as a draft (`DRAFT_NOT_MACHINE_DRAFT`); the original
machine draft is never modified, and a second round of edits starts from that draft again.

`corrections.json` (`schemaxis.whispercpp.corrections/1`) is the exact ledger: status, note,
the draft SHA-256 and bytes, the SHA-256 of `reviewed-segments.json`, counts, and for every
changed cue its index, millisecond times, original text and replacement text. It proves
what changed against which draft, not that the replacements are right.

Every run and every verification replays the derivation from the captured draft bytes
and the authored edits and compares all publications byte for byte, so rewriting a
file and refreshing its recorded hashes still fails with `VERIFICATION_FAILED`. Membership is
exact, and any launcher, submission or native log in the directory is itself a failure. This route never
creates a `.dispatch` directory, so a planted `.dispatch` member (for example
`.dispatch/transcribe/replay-x.py`) is an unexpected member and is refused; verification never reads or runs it.
The result reports `runtime: "host-only"`, `nativeProcesses: 0`, `accuracyCertified: false`
and `identityVerified: false`.

Faults, each with a location and recovery: `CORRECTIONS_STALE` (basis differs),
`CORRECTION_INDEX_INVALID`, `CORRECTION_DUPLICATE`, `CORRECTION_NOOP`,
`CORRECTION_TEXT_INVALID` (blank, surrounding space, control, markup or caption arrow),
`CORRECTIONS_NOTE_INVALID`, `CORRECTIONS_STATUS_CONFLICT`, `DRAFT_NOT_MACHINE_DRAFT`,
`DRAFT_SOURCE_MISSING` (the draft file or a directory on its path does not exist),
`INVALID_DRAFT_SOURCE` (not an absolute local `.json` path, a symbolic link, a directory, not a
regular file or over the byte budget), `INVALID_SHA256`, `MISSING_ARGUMENT` (an absent
`draft`, `draft.path`, `basisSha256`, `review`, `review.status` or `review.note`),
`UNKNOWN_ARGUMENT` / `INVALID_ARGUMENT` for unrecognised or mistyped members, and the shared `TIMED_TEXT_*` faults for a draft that
breaks the timed-text contract or budgets.

**Known limit: workflow verification reopens the original draft.** The correction route has no retained-input hook, so
`schemaxis verify` of a workflow that contains it falls back to the workflow's reusable-input record, which reopens the
original `draft.path` and hashes it. If that file was moved or deleted (the examples stage it under `/tmp`), workflow
verification fails with `DRAFT_SOURCE_MISSING` (a missing path) or `INVALID_DRAFT_SOURCE` even though the job directory
holds `captured-draft.json` with the exact bytes. Verifying the job directory itself (`schemaxis verify` on the correction
run) replays from the captured bytes and does not need the original. Pandoc and transcription behave the same way. Keep
the draft at its authored path while the workflow is verified or reused.

**The shipped review notes are illustrative.** Every `review.note` in these examples and in this page is an
author's declaration written for demonstration: no person reviewed the recording for them, and they are not
human-review evidence. A real publication needs a real reviewer and note, and Schemaxis still only records the
declaration. Publishing the example through Pandoc therefore shows `Status: human-corrected` beside an
illustrative note, nothing more.

[The correction example](../examples/schemaxis/whispercpp-corrections.json), the
[unchanged-review example](../examples/schemaxis/whispercpp-corrections-unchanged.json)
and the [publishing workflow](../examples/schemaxis/whispercpp-corrections-workflow.json)
read a real native draft kept at
`examples/schemaxis/whispercpp-corrections-fixtures/jfk-short-cues-segments.json`
(three cues, SHA-256 `0fb466ae...ba04`); stage a copy at the example path under
`/tmp/schemaxis-whispercpp-corrections/`. The
[blank-text example](../examples/schemaxis/whispercpp-corrections-blank-invalid.json)
fails planning with `CORRECTION_TEXT_INVALID`; the
[stale-basis example](../examples/schemaxis/whispercpp-corrections-stale-invalid.json)
plans but fails the run with `CORRECTIONS_STALE`. The workflow hands
`reviewed-segments.json` to [Pandoc](pandoc.md), whose transcript block shows the
author-declared status in its provenance paragraph.

## Cue deletion

`schemaxis.whispercpp.correct/2` is a separate, host-only successor route for the case that text replacement cannot
handle: a cue that should not be published at all. The motivating case is real: whisper.cpp 1.9.5 with `ggml-base.en`
transcribed a two second silent recording as one cue, "You", which `correct/1` can only replace with other visible text,
never remove (blank text is refused). `correct/1`, its plans, `schemaxis.timedtext.reviewed/1` and every publication
described above are unchanged; the new version never rewrites them. This is a practical editorial judgement, not evidence
of customer demand.

The document is the `correct/1` document plus one member:

- `deletions`: optional array of unique integer **source** indices of the pinned machine draft, for example `[1]` or `[0, 2]`.
  Replacement and deletion are distinct members: `corrections` entries keep their exact `{index, text}` shape (no
  delete flag), and an index in both lists is `CORRECTION_DELETION_CONFLICT`. A repeated index is `DELETION_DUPLICATE`,
  an index the draft does not have is `DELETION_INDEX_INVALID` at run time, and entries that are not bare integers are
  `INVALID_ARGUMENT`. Indices always name cues of the draft, never the renumbered publication.
- `review.status`: `human-corrected` needs at least one replacement **or** deletion; `human-reviewed-unchanged` needs
  neither. A declaration with no edit is never `human-corrected`.
- `basisSha256` pins the draft exactly as before (`CORRECTIONS_STALE`), and the draft must still be an unedited machine
  `schemaxis.whispercpp.segments/1`: a reviewed document of either version is refused (`DRAFT_NOT_MACHINE_DRAFT`), and an
  original draft with no cues is refused by the shared reader (`TIMED_TEXT_INVALID` at `$.draft.segments`). Nothing here
  relaxes either refusal.

The route publishes the same files, with the retained cues renumbered contiguously from zero as published: `reviewed-segments.json`
(artifact index 0, the new closed `schemaxis.timedtext.reviewed/2`), `transcript.txt`, `captions.srt`, `captions.vtt`,
`corrections.json` (`schemaxis.whispercpp.corrections/2`) and, with `captionReview`, `caption-review.json`. Retained cues keep their
timings, language and provenance. The reviewed/2 `review` object adds to the reviewed/1 members the pinned draft's `basis.cueCount`,
`deletionCount`, `deletedSourceIndices` and `retainedSourceIndices` (the source index of every published cue). The shared validator
requires the deleted and retained source indices to partition the draft's cues exactly and the corrected indices to be retained cues.

The ledger records every cue of the draft: `replacements` (source and published index, times, original and replacement text),
`deletions` (source index, times and original text) and `retained` (published index, source index, times, original text, final text
and whether it was edited), so the original draft path is never needed to read what was removed. The pinned draft itself stays the
authority: the ledger proves what was removed against which draft, not that a removal was right.

**Deleting every cue.** Listing every source index of a nonempty draft is the only way to publish no cue. The reviewed/2 document then
holds `segments: []` and `segmentCount: 0`, `transcript.txt` and `captions.srt` are empty files, and `captions.vtt` is exactly the
header `WEBVTT` and a blank line. The shared reader accepts an empty cue list **only** for reviewed/2 and only when `deletionCount`
equals `basis.cueCount` (at least one), the status is `human-corrected` and no cue is corrected; the machine draft and reviewed/1 still
refuse it. `captionReview` is refused (`CAPTION_REVIEW_EMPTY`) when nothing is retained, because a report of no cues would read as a pass.
An empty publication records the author's declaration that nothing remains; it is not evidence that the recording is silent, that no one
speaks, or that the deleted text was wrong.

Every run and every verification replays the whole derivation from the captured draft bytes and the authored edits, exactly as for
`correct/1`, so refreshed ordinary hashes cannot hide a restored cue, a moved deletion index, a forged empty state or an altered file.
Faults beyond those above: `CORRECTION_NOOP`, `CORRECTION_INDEX_INVALID`, `CORRECTION_TEXT_INVALID`, `CORRECTIONS_NOTE_INVALID`,
`CORRECTIONS_STATUS_CONFLICT`, `TIMED_TEXT_RESOURCE_LIMIT` (judged on the finished retained cues) and `VERIFICATION_FAILED`. The status is the
author's declaration; reviewer identity, hearing the audio, accuracy and accessibility are neither verified nor certified.

**Limits.** No timing edits (those exist only in the separate [`correct/3`](#cue-timing-edits) route), splits, merges, insertions or import of an edited transcript; a second round starts again from the original
machine draft, so every intended replacement and deletion goes in one document. The route is host-only and has no native
qualification; the retained-input limit described under [Human corrections](#human-corrections) applies unchanged (workflow verification
reopens the original `draft.path`, and verifying the job directory itself does not).

Examples (all notes are illustrative declarations; no person reviewed any recording for them), reading the genuine native drafts
under `examples/schemaxis/whispercpp-corrections-fixtures/` staged at the path inside each example: the
[partial deletion](../examples/schemaxis/whispercpp-deletions-partial.json) (replace cue 0, delete cue 1 of the three-cue sample),
the [every-cue deletion](../examples/schemaxis/whispercpp-deletions-all.json) (the silent recording's "You", fixture
`silence-hallucinated-segments.json`, SHA-256 `ce623bde...27be`), the
[unchanged review](../examples/schemaxis/whispercpp-deletions-unchanged.json), three plan- or run-time invalid cases
([conflict](../examples/schemaxis/whispercpp-deletions-conflict-invalid.json), [duplicate](../examples/schemaxis/whispercpp-deletions-duplicate-invalid.json)
and [range](../examples/schemaxis/whispercpp-deletions-range-invalid.json), which plans and fails the run with `DELETION_INDEX_INVALID`),
and the publishing workflows for [every-cue](../examples/schemaxis/whispercpp-deletions-workflow.json) and
[partial](../examples/schemaxis/whispercpp-deletions-partial-workflow.json) deletion. The [Pandoc](pandoc.md) transcript
block publishes a reviewed/2 document with the deletion facts in its provenance paragraph and, when no cue remains, no table. The Pandoc
report's `report-summary.json` states that actual shape in `transcriptObservations`; the plan's transcript-loss sentence is unchanged and is not
true of an every-cue-deleted report. Pandoc checks the reviewed/2 mapping for internal consistency only and does not open the machine draft, so the
mapping is trusted as declared unless the correction job itself is replayed (see [Pandoc](pandoc.md)).

## Cue timing edits

`schemaxis.whispercpp.correct/3` is a separate, host-only successor route for the case that neither text replacement nor deletion can
fix: a cue whose machine timing is wrong and whose correct interval the author knows. Experimental token-level boundaries are
often a little early or late, and moving them by hand is ordinary caption-publishing work. `correct/1` and `correct/2`, their plans,
`schemaxis.timedtext.reviewed/1` and `reviewed/2`, and every publication described above explicitly promise the original machine
timestamps and are unchanged; timing edits are a new protocol version rather than a looser old one. This is a practical editorial
judgement, not evidence of customer demand.

The document is the `correct/2` document plus one member:

- `timings`: optional array of `{"index": N, "startMs": S, "endMs": E}`, at most 512, with `index` an **original source** index of the
  pinned machine draft and both ends stated: each entry replaces the whole interval of one retained cue, as integer elapsed
  milliseconds from the start of the recording. A shift or duration is not a member (`UNKNOWN_ARGUMENT`), floats and booleans are
  `INVALID_ARGUMENT` and never rounded, `startMs` must be before `endMs` (`TIMING_INTERVAL_INVALID`), an index may appear once
  (`TIMING_DUPLICATE`) and not also in `deletions` (`TIMING_DELETION_CONFLICT`), an index the draft does not have is
  `TIMING_INDEX_INVALID` at run time, and an entry equal to the cue's existing interval is `TIMING_NOOP`. After deletions, source
  indices stay the draft's: with cue 0 deleted, the draft cue 2 is still index 2 although it is published as cue 1.
- `review.status`: `human-corrected` needs at least one replacement, deletion **or** timing edit (a timing-only pass is
  `human-corrected`); `human-reviewed-unchanged` needs none, and declaring it beside `timings` is `CORRECTIONS_STATUS_CONFLICT`.
- `basisSha256` and the draft are exactly as for `correct/2`: a changed draft is `CORRECTIONS_STALE`, a reviewed document of any
  version is `DRAFT_NOT_MACHINE_DRAFT`, an original draft with no cues is refused. The 512 cue, 256 character, 32768 character, 4MiB source
  and 500 character note limits are unchanged.

**The finished set is validated, not the edit order.** After every edit is applied, the retained cues, in source order, must each
satisfy `0 <= startMs < endMs <= audio duration` (the draft's recorded duration, rounded up to a whole millisecond exactly as the shared
reader does) and no cue may start before the previous retained cue ends. Touching intervals (one ends where the next starts) are valid, and
a cue may use time that a deleted cue held in the draft. A violation is `TIMING_OVERLAP` or `TIMING_AFTER_AUDIO`, located at the offending
`$.timings[n]`; nothing is clamped, reordered or rounded, the audio is never changed, and cues are never added, split or merged.
Because only the finished set is judged, listing a later cue's move before an earlier cue's move cannot cause a false overlap refusal, and
the same edits in any order publish identical bytes.

The route publishes the same files: `reviewed-segments.json` (artifact index 0, the new closed `schemaxis.timedtext.reviewed/3`),
`transcript.txt`, `captions.srt`, `captions.vtt` carrying the new times, `corrections.json` (`schemaxis.whispercpp.corrections/3`) and, with
`captionReview`, `caption-review.json`, whose duration and density flags are recomputed from the **edited** durations. The reviewed/3 `review`
object carries every reviewed/2 member plus `timingEditCount`, `timingEditedIndices`, `originalTimings` (the pinned draft's start and end of
every retained cue, by source index), a `timingPolicy` text and `synchronizationCertified: false`. The shared validator requires the edited
indices to be exactly the retained cues whose published interval differs from the recorded original, so a document cannot claim an edit it
did not make or hide one. In the `corrections/3` ledger every section uses the same two pairs of names: `originalStartMs` and `originalEndMs` are
always the pinned machine draft's times, and `startMs` and `endMs` are always the published (possibly author-edited) times. So `replacements`
(source and published index, both pairs, original and replacement text), `timingEdits` (source and published index, both pairs, text) and
`retained` (every retained cue, both pairs, original and final text, whether it was edited and whether it was retimed) show a cue that was both
reworded and retimed with its original and published times side by side. A deleted cue has no published time, so `deletions` records only
`originalStartMs`, `originalEndMs`, the source index and the original text. The `corrections/1` and `corrections/2` ledgers are unchanged and
keep `startMs`/`endMs` for the draft's times, which were always the published times there.

Every run and every verification replays the whole derivation from the captured draft bytes and the authored edits, so refreshed ordinary
hashes cannot hide a restored original time, a moved edit, a forged empty state or an altered file. This is replay, not signed authenticity:
the reviewed document is a claim bound to the pinned draft bytes, not a proof of who made it.

**What an edit is not.** The status and every edited time are the author's declaration. Schemaxis does not listen to the audio, does not
measure whether an edited interval is better aligned than the machine's, and does not verify who reviewed anything, so the review, the
ledger and the result say `accuracyCertified`, `identityVerified` and `synchronizationCertified` are all `false`. Caption review flags
are fixed editorial heuristics and are not readability or accessibility certification. The route never starts whisper-cli (a fake executable
placed on the path or named as the executable is never run), so planning, running and verifying need no native process.

Faults beyond those above are the `correct/2` faults (`CORRECTION_*`, `DELETION_*`, `CORRECTIONS_*`, `CAPTION_REVIEW_EMPTY`,
`TIMED_TEXT_RESOURCE_LIMIT`, `VERIFICATION_FAILED`). Examples (every note is an illustrative automated declaration; no person listened
to or reviewed any recording for them), reading the genuine native draft under `examples/schemaxis/whispercpp-corrections-fixtures/`: the
[timing edit](../examples/schemaxis/whispercpp-timing-edit.json) (cues 0 and 2 retimed), the
[combined edit](../examples/schemaxis/whispercpp-timing-combined.json) (replace cue 0, delete cue 1, retime source cue 2), the invalid
[unchanged-with-timings](../examples/schemaxis/whispercpp-timing-unchanged-conflict-invalid.json) declaration, two run-time refusals
([overlap](../examples/schemaxis/whispercpp-timing-overlap-invalid.json) and
[after the audio](../examples/schemaxis/whispercpp-timing-after-audio-invalid.json)) and the
[publishing workflow](../examples/schemaxis/whispercpp-timing-workflow.json) that hands artifact index 0 to the [Pandoc](pandoc.md)
transcript block with `timeFormat: "timecode"`. Pandoc says the times were author-edited, with the count and source indexes, and never
that the machine timing was preserved; `tools/qualify_whispercpp_timing.py` reads the native Pandoc 3.12.1 HTML, DOCX and EPUB tables back
against hand-written expected intervals. That readback is a publishing handoff check, not speech-recognition requalification, and the
correction route itself has no native qualification.

**Limits.** Whole-interval edits of existing retained cues only: no splitting, merging, insertion, audio changes, offset or stretch
operations, import of an edited transcript, or second round on a reviewed document (start again from the machine draft with every
intended edit in one document). The route is host-only, and the retained-input limit described under [Human corrections](#human-corrections)
applies unchanged.

## Caption line layout

Every caption publication above puts one cue on one line, even after correction. `schemaxis.whispercpp.captions/1` is a separate,
host-only route that breaks each cue into explicit lines for SRT and WebVTT. It is reusable caption preparation, a practical
editorial judgement rather than evidence of customer demand. It never launches whisper-cli, reads no audio or model and never changes
a word or a time. `correct/1`, `correct/2`, `correct/3`, the transcription route, their plans, results and publications, and the shared
timed-text contract are unchanged.

```json
{
  "version": "schemaxis.whispercpp.captions/1",
  "operation": "layout",
  "source": {"path": "/absolute/segments.json"},
  "sourceSha256": "64 lowercase hexadecimal digits",
  "maxLineCodePoints": 42,
  "maxLines": 2
}
```

- `source.path`: an absolute local `.json` path of a machine `segments.json` or of a `reviewed-segments.json` (`reviewed/1`, `/2` or
  `/3`), or a workflow text artifact with `{"$artifact":"correct","index":0}`. It is read once by the shared closed timed-text validator
  (at most 4 MiB, 512 cues, 256 characters per cue, 32768 in total); the final path component must be a regular file, never a link, device,
  directory or FIFO. A reviewed document with every cue deleted is accepted and yields an empty SRT, a WebVTT header and a summary of zero
  cues; no cue is invented.
- `sourceSha256`: required pin of the exact source bytes (`LAYOUT_SOURCE_STALE` when they differ). The held bytes are the only input; the
  file is read again after the publications are written and a change is `LAYOUT_SOURCE_CHANGED`. In a workflow the pin of an upstream
  artifact is that artifact's digest, so changing the upstream job invalidates the pin until the new output is reviewed and the pin is updated.
- `maxLineCodePoints` (8 to 80) and `maxLines` (1 to 3): both required integers; booleans, floats and strings are `INVALID_ARGUMENT`.

**The layout.** A line break replaces one isolated ordinary space (U+0020), a single space with no ordinary space next to it, and nothing else. Per cue the layout is chosen by three
fixed rules: the fewest lines (a cue that already fits is never broken), then the smallest sum of squared line lengths, so lines are as even
as the words allow, then the earliest first break and, if still equal, the earliest second break. For example, with 14 code points and
`one two three four` the choice is `one two` / `three four` (7 and 10) rather than the greedy `one two three` / `four`; with 16 and
`The quick brown fox jumps`, `The quick` / `brown fox jumps` and `The quick brown` / `fox jumps` have equal evenness, so the earlier break wins. The
search is a dynamic program over at most 128 words, at most three lines and at most 40 words per line, so its work is bounded by the shared
cue budget. Joining the published lines of a cue with one space restores the source text exactly. A run of two or more adjacent ordinary spaces is never
broken, trimmed or normalised: it stays inside one unbreakable run together with the characters around it, so `two  spaces here` with 12 code points per
line is `two  spaces` / `here`, and a cue that fits on one line is published as it is. A no-break or ideographic space is likewise part of its run, not a
break opportunity.
Every cue index, start and end millisecond, the order and the count are carried over exactly, and nothing is split, merged, retimed or reordered.

**Bounds are refusals, not suggestions.** An unbreakable run (a word, or words joined by a no-break space or by two or more adjacent ordinary spaces)
longer than `maxLineCodePoints` is `LAYOUT_WORD_TOO_LONG` and a cue that needs more than
`maxLines` is `LAYOUT_TOO_MANY_LINES` with `linesNeeded`; both name the cue (`$.source.segments[n].text`) and nothing is split inside a run,
truncated or widened automatically. Lengths count Unicode code points of the source text, spaces, punctuation and combining marks once each.
They are not grapheme clusters, display width, font metrics, readability or accessibility guarantees. A script written without spaces
(for example a run of Chinese characters) is one word and can be refused although it looks narrow.

**Publications**, in artifact order: `captions.srt` (kind `file`, index 0), `captions.vtt` (`file`, index 1) and `caption-layout.json`
(`text`, index 2). The SRT payload is plain text exactly as in the other SRT publications: nothing is escaped or marked up, and how a player
interprets the text is not certified. In the WebVTT every line escapes `&`, `<` and `>` exactly once (`&amp;`, `&lt;`, `&gt;`; the shared validator already refuses `<` and `>` in source
text) and line breaks are kept; no cue settings, styles, voices or speaker labels are written. The bound counts the source text, never the escaped
text. The summary `schemaxis.whispercpp.caption-layout/1` is closed: the source version, byte count, SHA-256 and, for a reviewed source, its basis
digest; the source's declared status, language, audio and model digests and duration; the two bounds and the policy text; and for every cue its index,
times, original text, lines, code-point length of each line and whether it was reflowed, with the counts of cues, reflowed cues and lines. Its `review`
member says `humanReviewRequired: true` and `accuracyCertified`, `readabilityCertified`, `accessibilityCertified`, `synchronizationCertified` and
`identityVerified` all `false`. The review status of the source (`machine-draft`, `human-corrected` or `human-reviewed-unchanged`) is the source author's
declaration, carried unchanged and never promoted, and the summary says nothing about who reviewed any recording. Original file paths are not
published; the retained `captures.json` evidence records the source path.

**Verification** derives every publication again from the captured source bytes and the authored bounds and compares each file byte for byte, then
checks the typed plan, receipt (`runtime: host-only`, no executable or profile), membership (any native launcher, submission or log, link or planted
`.dispatch` content is a failure), source capture binding and result. No stored claim or hash is trusted, so refreshing every ordinary hash cannot hide an altered
line, time, status or claim. A coherent rewrite of the source capture, authored document, publications and receipt is only new consistent data: the
verification is replay, not signed authentication of the source. The run honours the shared deadline (`timeout`, at most 3600 seconds) and cancellation,
requires a fresh output directory. A failed run keeps a failed `result.json` and no `verification.json`, but files written before a late failure (for
example a changed source or the final deadline check) can remain in the directory: they are unverified, must not be published, and `verify` refuses the directory.

**Consumers.** Some consumers are stricter than this route and this route does not change them. The [FFmpeg](ffmpeg.md) review movie accepts only plain SRT
of at most four lines and 500 characters per cue, and refuses the characters `<`, `>`, `{`, `}` and backslash and control, format (including the zero-width
joiner), separator and unassigned characters, so a source with a no-break space or a backslash lays out here but is refused there. The WebVTT mapping follows the
W3C WebVTT candidate recommendation draft of 20 May 2026 (cue payload text with `&` and `<` as character references, no ` --> `); a native WebVTT proof is
not a certification of any player. SubRip has no normative standard cited here.

Examples (the source is the genuine native draft under `examples/schemaxis/whispercpp-corrections-fixtures/`; every note is an illustrative automated
declaration and no person listened to or reviewed any recording): the [three-line layout](../examples/schemaxis/whispercpp-caption-layout.json) (16, 3), the
[two-line layout](../examples/schemaxis/whispercpp-caption-layout-two-lines.json) (24, 2), two run-time refusals
([word too long](../examples/schemaxis/whispercpp-caption-layout-word-invalid.json) and
[too many lines](../examples/schemaxis/whispercpp-caption-layout-lines-invalid.json)), two planning refusals
([relative path](../examples/schemaxis/whispercpp-caption-layout-relative-invalid.json) and
[four lines](../examples/schemaxis/whispercpp-caption-layout-bounds-invalid.json)) and the
[workflow](../examples/schemaxis/whispercpp-caption-layout-workflow.json) that corrects a draft with `correct/1` and lays out the reviewed document with a
literal pin of its digest. `tools/qualify_whispercpp_caption_layout.py` hands the published SRT of a layout to the FFmpeg review movie and reads the Matroska
file back independently; that is a publishing handoff check, not speech-recognition requalification, and the layout route itself has no native qualification.

**Limits.** Line breaks only: no splitting, merging, retiming, cue positioning, styling, speaker labels, hyphenation, language-aware or grapheme-aware breaking,
reading-speed analysis (use [caption review](#caption-review) for flags) or second round on a laid-out document. Source text that needs correction is corrected
first with `correct/1` to `correct/3`.

## Examples and Studio

The examples use a fixed staging directory, `/tmp/schemaxis-whispercpp-acceptance/`,
which `tools/qualify_whispercpp.py` creates. [The public sample](../examples/schemaxis/whispercpp-jfk.json)
is the 11 second `jfk.wav` from the whisper.cpp repository; it is not committed here.
The [excerpt](../examples/schemaxis/whispercpp-excerpt.json) is its exact first 128000
frames. Both pin a base.en model. The
[caption review example](../examples/schemaxis/whispercpp-caption-review.json) is the
11 second sample with `captionReview` enabled. The
[short-cue example](../examples/schemaxis/whispercpp-short-cues.json) is the same sample
with `maxSegmentLength` 42. The
[relative-path example](../examples/schemaxis/whispercpp-relative-invalid.json) and the
[uppercase-hash example](../examples/schemaxis/whispercpp-hash-invalid.json) are valid
against the schema but rejected by semantic validation before any file is read.
Studio provides one transcription starter with placeholder paths and a placeholder
hash; replace all three before running.

## Execution, handoff and verification

One deadline covers capture, model hashing, the version check, a dependency trace,
transcription and verification. Each native process has CPU, address-space and
file-size limits; shared cancellation terminates the owned process group. The runner
retains the authored and effective plans, the captured audio, model and runtime
identity, trusted launchers, input bindings, submissions, stdout and stderr, the native
JSON and SRT, and the four publications (five with the caption review; `maxSegmentLength` adds no file). `runtime.json` records SHA-256 values for the
executable and for every dynamic dependency the loader resolved before and after the
run. Verification checks the retained records and does not re-hash the live
installation.

Verification then rechecks everything it can independently: the audio WAV by its own
reader; model and audio hashes; exact command, launcher and input bindings; the strict
native JSON and the timing policy against the audio duration; and the byte-exact
regeneration of every publication from the checked segments. A rehashed receipt cannot
hide a caption that disagrees with its segments. Exact evidence and publication
membership are enforced. The result carries `accuracyCertified: false` and
`humanReviewRequired: true`.

The route accepts `file` artifacts, so a WAV produced by an earlier verified job can
be supplied with `{"$artifact":"earlier","index":0}` at `audio.path`. The file must
still satisfy the 16000 Hz mono contract. Qualification covers the named fixtures, the
base.en model and the observed runtime only. It does not cover other models,
languages, noisy or long recordings, GPU backends or other operating systems.

## Accuracy and human review

Recognition output is probabilistic and can omit, repeat or invent words, mislabel
language, or place a timestamp awkwardly. In qualification, cutting the same public
recording at six seconds instead of at the end of the sentence produced a different
and wrong transcript, and four seconds of digital silence produced the structurally
valid text `You`. Treat every result as a draft. Check names, numbers, quotations
and anything with legal, medical or safety consequence against the audio, and correct
captions with an editor. Transcription publishes each cue on one line and produces no readability or speaker labels; the host-only
[caption line layout](#caption-line-layout) route only moves line breaks between words and certifies nothing; the optional caption review only flags cue duration and density by fixed
editorial thresholds and certifies nothing, and `maxSegmentLength` is a native
target whose cue timing is experimental.

## Fault recovery

`INVALID_AUDIO_SOURCE` and `INVALID_MODEL` mean a path is not an absolute local regular
file of the required type. `INVALID_AUDIO_DATA` means the WAV is not canonical PCM16
mono 16000 Hz; re-export it. `AUDIO_RESOURCE_LIMIT` means the audio is too long; split
it. `INVALID_SHA256`, `INVALID_LANGUAGE` and an out-of-range or non-integer `maxSegmentLength` (`INVALID_ARGUMENT`) are authoring errors. `AUDIO_HASH_MISMATCH`
and `MODEL_HASH_MISMATCH` mean the file bytes differ from the pin; restore the file or
change the pin deliberately. `MODEL_CHANGED` and `RUNTIME_CHANGED` mean bytes changed
during the run; rerun into a fresh directory. `UNSUPPORTED_NATIVE_VERSION` means the
executable is not whisper.cpp 1.9.5. `TRANSCRIPT_EMPTY` means no speech segments were
reported. `TRANSCRIPT_INVALID` and `TRANSCRIPT_TIMING` mean the native output broke the
contract (including a blank-looking or non-text cue); inspect `native.json` at the
reported cue and rerun with cleaner or trimmed audio or another pinned model; nothing is
repaired, dropped or published. If `maxSegmentLength` was set, retry with it omitted or larger. A changed artifact or evidence file gives
`VERIFICATION_FAILED`; keep the evidence and rerun from the declared input. When
reopening retained evidence fails because the native evidence itself breaks the
contract, the `VERIFICATION_FAILED` fault keeps the specific fault under
`observed.cause`, with its own location and recovery.

Caption layout faults (`schemaxis.whispercpp.captions/1`): `LAYOUT_SOURCE_STALE`: review the current source and copy its sha256 into `sourceSha256`. `LAYOUT_SOURCE_CHANGED`: the source changed or vanished while the layout ran; rerun from the current document. `INVALID_SOURCE`: the path is relative, has parent references, is not `.json`, or is a link, device, FIFO, directory or over 4 MiB; `SOURCE_MISSING`: the file or a directory on its path does not exist. `TIMED_TEXT_*`: the source breaks the shared timed-text contract or budgets and is never repaired. `LAYOUT_WORD_TOO_LONG`: raise `maxLineCodePoints` or correct the unbreakable run (a word, or words joined by a no-break space or by two or more adjacent ordinary spaces); `LAYOUT_TOO_MANY_LINES`: raise `maxLines` or `maxLineCodePoints`. `INVALID_ARGUMENT` at `$.maxLineCodePoints` or `$.maxLines`: use integers 8 to 80 and 1 to 3. `RUNNER_CANCELLED` and `RUNNER_TIMED_OUT`: nothing was verified, and any file already written is unverified and must not be published; rerun into a fresh directory. `VERIFICATION_FAILED`: a retained file differs from independent replay; rerun from the declared input.

The native qualifier exclusively creates its generic temporary staging directory
and refuses every pre-existing path there, including same-user directories. It
does not overwrite or unlink another run's fixtures. Inspect an interrupted
run before removing its own stale staging directory.

This route requires Linux with glibc, `/proc/self/fd` and POSIX resource limits.
Native qualification used a shared-library CPU build with `GGML_BACKEND_DL=OFF`
and `GGML_CPU_ALL_VARIANTS=OFF`; dynamic backend plug-ins are not qualified.
Later verification checks retained model/runtime bindings and derived artifacts;
it does not re-hash an external model or re-run recognition. Keep the original
model separately if replay is needed. Run-directory relocation is not qualified.
The framework owns `.dispatch` as scratch: its contents are outside publication
membership; the entry must be a regular directory.

Recordings not aligned to the native 10 ms timestamp grid can be refused if
whisper.cpp emits a cue end beyond the exact audio bound. The adaptor refuses
that output and never silently shortens a cue. A native 8005 ms excerpt probe is
recorded separately from the two qualified speech fixtures.
Transcript publishing tools also have their own plain-text and table limits; a
structurally valid transcription is not automatic admission to every downstream
report format. The Pandoc handoff must pass its independent input validation.
