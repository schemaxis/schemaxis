# Lossless FLAC archive and PCM16 decode

Use `schemaxis.flac/1` to move a recording between the PCM16 WAV that Schemaxis edits and the
FLAC file that is the usual lossless archive format. Two operations:

- `encodeLossless` archives **one PCM16 WAV as native lossless FLAC** (`audio.flac`).
- `decodePCM16` decodes **one native FLAC into a canonical PCM16 WAV** (`audio.wav`) that
  [SoX](sox.md) `conform` and the transcription steps accept.

Both publish a JSON `flac-summary.json` and prove the result by decoding the actual FLAC bytes again in
a separate `flac` process. It is a bridge for recordings that arrive or are kept as FLAC, not an audio
editor: there is no lossy mode, resampling, channel change, picture, normalisation or compression-level
setting. The one metadata feature is an optional title, artist and description for an archive
([recording labels](#recording-labels)). Product judgement (not demonstrated demand): the speech-preparation
chain is PCM16-WAV-only, compressed lossless recordings are the usual way such audio is stored, and an archive
that cannot say what it is gets separated from its name.

## Setup

A run needs one FLAC 1.5 `flac` executable: `--flac` (or `schemaxis configure flac`, or
`SCHEMAXIS_FLAC`). Verification needs the **same trusted `flac`** because the host has no FLAC decoder.
`schemaxis verify OUTPUT` takes only the directory, so it finds `flac` from `SCHEMAXIS_FLAC` or a stored
`flac` location in the git-ignored private configuration (`{"version": 1, "locations": {"flac": "/path/to/flac"}}`
in `.schemaxis.local.json`, or the file named by `SCHEMAXIS_CONFIG`). The `PATH` is never searched and a
receipt never supplies an executable. A missing, relative-path or non-1.5 executable is a fault, never a
skipped check. Discovery and planning need only Python 3.10+. The official tool is built from the
[source archive](https://ftp.osuosl.org/pub/xiph/releases/flac/); Ogg, the C++ libraries and shared
libraries are not needed.

```json
{
  "version": "schemaxis.flac/1",
  "operation": "decodePCM16",
  "source": "/absolute/path/to/recording.flac"
}
```

```sh
schemaxis plan decode.json
schemaxis run decode.json --output-directory output/decode --flac /path/to/flac
SCHEMAXIS_FLAC=/path/to/flac schemaxis verify output/decode
```

The [baseline](../examples/schemaxis/flac-baseline.json) archives a 48 kHz stereo WAV of 4099 frames with
asymmetric full-scale extrema ([fixture](../examples/schemaxis/fixtures/flac/stereo-48000.wav)); the
[variant](../examples/schemaxis/flac-variant.json) archives an 8 kHz mono WAV with a `LIST` chunk;
[decode](../examples/schemaxis/flac-decode.json) and [decode-tagged](../examples/schemaxis/flac-decode-tagged.json)
decode 16 kHz stereo FLAC files (the second also carries a seek table, tags and padding). The
[speech workflow](../examples/schemaxis/flac-speech-workflow.json) decodes a FLAC and conforms it to PCM16
mono 16 kHz with SoX; the [archive workflow](../examples/schemaxis/flac-archive-workflow.json) does the reverse.
The [tag-archive](../examples/schemaxis/flac-tag-archive.json) and [tag-unicode](../examples/schemaxis/flac-tag-unicode.json)
examples archive with labels, [tag-invalid-label](../examples/schemaxis/flac-tag-invalid-label.json) shows a refused label, and the
[tag workflow](../examples/schemaxis/flac-tag-workflow.json) conforms with SoX, archives with labels and decodes the archive again.
In Studio choose **FLAC → Decode a FLAC recording to PCM16 WAV** or **Archive a PCM16 WAV as lossless FLAC with title, artist and description**.

## What the fields mean

| Field | Meaning |
| --- | --- |
| `version` | `schemaxis.flac/1`. The document contract, not the FLAC release. |
| `operation` | `encodeLossless` (WAV to FLAC) or `decodePCM16` (FLAC to canonical PCM16 WAV). |
| `source` | Absolute local `.wav` for `encodeLossless`, `.flac` for `decodePCM16`. A verified file artifact from an earlier workflow step is also accepted. |
| `metadata` | Optional, `encodeLossless` only: a closed object of `title`, `artist` and `description` strings (at least one). See [recording labels](#recording-labels). |

Encoder flags, compression level, tag names, pictures, resampling and channel fields are rejected as
unknown arguments, and so is `metadata` on `decodePCM16`.

## Recording labels

`metadata` gives an archive a human-written name that travels inside the file. It is optional and only valid for
`encodeLossless`; without it the archive is exactly the original untagged one (same plan, losses, native arguments, FLAC bytes,
summary, result and claims).

```json
{
  "version": "schemaxis.flac/1",
  "operation": "encodeLossless",
  "source": "/absolute/path/to/recording.wav",
  "metadata": {"title": "Site visit, north bank", "artist": "A. Reviewer", "description": "Field note A=B"}
}
```

| Label | Vorbis comment | Limit (code points / UTF-8 bytes) |
| --- | --- | --- |
| `title` | `TITLE` | 200 / 512 |
| `artist` | `ARTIST` | 200 / 512 |
| `description` | `DESCRIPTION` | 1000 / 3000 |

* The byte limits are deliberate: a title of 200 emoji or about 170 CJK characters exceeds 512 bytes and is refused.
* The object is closed: any other key (including a tag name, flag or file reference), an empty object, or a value that is not a
  string is refused. Each value must be nonempty plain visible text: at least one letter, number, punctuation mark or symbol; no
  control characters (newlines and tabs included), lone surrogates, line or paragraph separators, bidirectional controls, private-use
  or noncharacter code points, or invisible format characters other than the zero-width joiners that some scripts need. These faults
  are `INVALID_FLAC_METADATA` (an unknown key is `UNKNOWN_ARGUMENT`) and are raised during planning, before any native process or
  output directory exists.
* Values are data, never native flags. The adaptor always passes the same three field names, in the fixed order title, artist,
  description, one `--tag=FIELD=VALUE` argument per label (no shell and no `--tag-from-file`). A value containing `=` or non-ASCII text
  is preserved exactly; nothing is trimmed, cropped or Unicode-normalised, so a precomposed and a decomposed accent stay different.
* `--no-utf8-convert` is passed before the tags, but only for a labelled archive. The native process runs with `LC_ALL=C`; observed
  with FLAC 1.5.0, `flac` would otherwise convert the authored UTF-8 from the "local charset" and replace each non-ASCII byte with `#`.
* The labels are **author-declared**, not an identity, rights or provenance certificate. Nothing checks that the artist is the artist.
* Verification does not trust the receipt. The host parses the published `VORBIS_COMMENT` bytes (little-endian lengths, the libFLAC
  vendor string, the entry count, each entry) and requires exactly the authored entries, in fixed order and with exact cardinality,
  next to the usual STREAMINFO and metadata-framing checks; it then still re-decodes the actual FLAC bytes and compares every PCM
  byte. A forged comment is refused even when every hash in the receipt is refreshed. The request, capture record, plan, summary
  and result all carry the labels in a closed typed form, so a result that adds, drops or changes them is refused.
* A writer who consistently rewrites the authored request, the FLAC and every retained record produces another valid archive: that
  is semantic consistency, not authenticity. There is still no independent host FLAC frame decoder.
* `decodePCM16` still drops all tags (it lists `VORBIS_COMMENT` as dropped) and there is no metadata extraction feature: the labels do
  not travel through a decode, and WAV `LIST` and `JUNK` text is never used as labels.

## Supported subset and refusals

Audio is signed 16-bit PCM, mono or stereo, 8000–192000 Hz, at most 600 seconds. The decoded canonical WAV
(44-byte header plus PCM) must be at most 32 MiB, which is exactly the SoX `conform` source limit, so
every decoded file is admissible downstream. (The literal PCM bound is therefore 33,554,388 bytes, 44 bytes
under 32 MiB: a deliberate judgement.) A 192 kHz stereo recording is limited to about 43 seconds and a
48 kHz stereo one to about 174 seconds.

| Input or situation | Result |
| --- | --- |
| Relative path, URL, prefix, wrong extension for the operation | `INVALID_FLAC_SOURCE` at `$.source` |
| Missing, symlinked, non-regular or oversized file (a WAV over 32 MiB, a FLAC over 40 MiB) | `INVALID_FLAC_SOURCE` |
| Corrupt WAV, extra chunk types, non-16-byte `fmt `, 24-bit, float, compressed or more than two channels | `INVALID_FLAC_WAV` |
| Longer than 600 s, STREAMINFO declaring more decoded PCM than fits a 32 MiB canonical WAV, or metadata over 4 MiB | `FLAC_BUDGET` (judged before any native process) |
| `metadata` that is not a closed object of nonempty visible plain-text title/artist/description strings within the limits | `INVALID_FLAC_METADATA` at `$.metadata` or `$.metadata.<label>`, before any native process |
| An unknown `metadata` key, or `metadata` on `decodePCM16` | `UNKNOWN_ARGUMENT` |
| Not starting with `fLaC`, truncated metadata, STREAMINFO missing, duplicated or not first, forbidden or reserved block type, duplicate seek table or Vorbis comment, bad first-frame sync/CRC-8/reserved bits, first frame inconsistent with STREAMINFO | `INVALID_FLAC_STREAM` |
| Ogg FLAC, ID3v2 prefix, STREAMINFO bit depth other than 16, more than two channels, sample rate outside 8000–192000 Hz, unknown (zero) sample count, all-zero MD5 | `UNSUPPORTED_FLAC_FORMAT` |
| Frames damaged, CRC or MD5 mismatch, or a decoded length different from the STREAMINFO count during a `decodePCM16` run | `FLAC_STREAM_REJECTED`; `cause` carries the native fault where there is one |
| `flac` not 1.5 | `UNSUPPORTED_RUNTIME` |
| Executable absent, relative or not executable | `INTERPRETER_NOT_FOUND` |
| Output directory already exists, including one created between the check and creation | `OUTPUT_EXISTS` |
| Published FLAC is well framed but `flac` cannot decode it, or decodes to different PCM | `VERIFICATION_FAILED` (`cause` keeps the native fault) |
| Retained JSON with duplicate keys, `NaN`/`Infinity`, a number that overflows (`1e400`), excess depth, or a changed type (`true`→`1`, `66`→`66.0`) | `VERIFICATION_FAILED` (a duplicate or malformed `authored.json` may first be refused as `INVALID_SCHEMA_SNAPSHOT` by the shared schema-snapshot layer) |
| Native failure, timeout, cancellation | `NATIVE_EXECUTION_FAILED`, `RUNNER_TIMED_OUT`, `RUNNER_CANCELLED` |

`encodeLossless` reads the WAV with its own strict reader (the same subset as the SoX adaptor: a 16-byte `fmt `
chunk, `data`, optional `LIST` and `JUNK`, exact RIFF sizes), so any WAV that SoX publishes is accepted.
`LIST` and `JUNK` chunks are dropped and listed in the summary.

`decodePCM16` accepts native FLAC only. Tags (`VORBIS_COMMENT`), pictures, seek tables, padding,
application blocks and cue sheets are accepted structurally, dropped and listed in
`droppedMetadataBlocks`. The host checks the metadata framing and the **first frame header** (sync, reserved
bits, CRC-8, block size, sample rate, channels and bit depth against STREAMINFO) before any native process; all
later frames are validated only by libFLAC, which runs without `--decode-through-errors`, so damage is refused
rather than concealed.

## What is published

`encodeLossless`: `audio.flac` (native FLAC: STREAMINFO plus a Vorbis comment that is empty, or holds exactly the authored
labels; no padding, no seek table) and `flac-summary.json`. `decodePCM16`: `audio.wav` (canonical 44-byte header, then the exact decoded
PCM) and `flac-summary.json`. The summary (`schemaxis.flac.summary/1`) records the operation, audio geometry
and duration, PCM byte count, SHA-256, MD5 and per-channel minimum and maximum samples, the source bytes and
SHA-256, dropped WAV chunks or FLAC metadata blocks, the output file, the STREAMINFO (block and frame sizes,
sample rate, channels, bits, total samples, MD5) and the readback record. A labelled archive adds a `metadata` record: the mode
(`authoredLabels`), `declaredBy: author`, the Vorbis comment block size and each comment's field, value and UTF-8 byte count as the host read them from
the published file. Both artifacts are of kind `file`,
so they bind into SoX or other steps like any recording.

## Native mapping

The native tool is `flac` 1.5.0 ([manual](https://xiph.org/flac/documentation_tools_flac.html), format
[RFC 9639](https://www.rfc-editor.org/rfc/rfc9639.html), release notes
[changelog](https://xiph.org/flac/changelog.html); all rechecked 25 October 2026 against FLAC 1.5.0, 11 February 2025,
and the local `flac(1)` manual). The options are fixed and never authored. The host supplies **raw PCM**, never a
container, so the native tool never parses a WAV and keeps no foreign metadata.

| Stage | Command (the working directory is a private run directory) |
| --- | --- |
| version | `flac --version`, which must read `flac 1.5.N` |
| encode | `flac -8 -V -s -w --no-padding --no-seektable --no-preserve-modtime --force-raw-format --endian=little --sign=signed --bps=16 --channels=N --sample-rate=R -o audio.flac source.pcm` |
| encode with labels | the same arguments with `--no-utf8-convert --tag=TITLE=... --tag=ARTIST=... --tag=DESCRIPTION=...` (only the authored ones, in that order) before `--channels` |
| decode | `flac -d -s -w --no-preserve-modtime --force-raw-format --endian=little --sign=signed -o reopened.pcm audio.flac` (decode: `-o decoded.pcm captured.flac`) |

`-8` is the highest preset, `-V` has the encoder verify its own output, `-s` silences statistics, and `-w` turns
warnings into errors. There is no `--force`, so an existing output is refused. Each stage runs through a fixed launcher
with address-space, CPU and output-size limits and a minimal environment.

## Verification contract

There is **no independent host FLAC decoder** in Schemaxis, and the adaptor does not claim host-independent
verification of the compressed bitstream. `schemaxis verify` **needs the trusted `flac`** (explicit argument, stored
configuration or `SCHEMAXIS_FLAC`; never the receipt or `PATH`). Without it the answer is `INTERPRETER_NOT_FOUND`, never
success. It then:

1. reads every retained JSON file strictly (no duplicate keys, `NaN`/`Infinity`, numbers that overflow to
   infinity, or excess depth) and compares the plan, capture record, summary, native input bindings and the
   result's claims, as a closed set, in typed canonical form, so `true` is not `1` and `66` is not `66.0`; it refuses
   unreferenced files in the publication directory;
2. rereads the captured input, requires it to match the capture record and re-derives the geometry
   independently (WAV: strict reader and the raw PCM bridge; FLAC: STREAMINFO, metadata and first frame);
3. copies the **actual FLAC bytes** (for `encodeLossless` the published `audio.flac`, for `decodePCM16` the captured
   `captured.flac`) to a private temporary directory and runs `flac -d` in a fresh bounded process under the
   run's remaining deadline and cancellation;
4. compares the decoded PCM: for `encodeLossless` **every byte equals the PCM of the captured WAV** (the identity
   claim), and the STREAMINFO sample count, geometry and MD5 (recomputed by the host over the PCM) match; for
   `decodePCM16` the PCM must equal the payload of the published `audio.wav`, which must be exactly the canonical
   WAV of those samples, and must reproduce the STREAMINFO MD5 and sample count;
5. checks the receipt's membership and digests, retained evidence digests, the observed FLAC 1.5 identity and each
   native launcher, input binding, exit record and silent log. Receipt executables are inert provenance and are never
   launched.

For `decodePCM16` the MD5 and sample-count agreement is **consistency of the file with itself**. It does not certify
that the recording is genuine, complete or unaltered: anyone who rewrites a FLAC can write a matching MD5. For
`encodeLossless` the claim is stronger: it is **exact PCM identity**, the fresh decode of `audio.flac` equals the PCM
of the captured WAV byte for byte. The decision comes from the bytes and a fresh decode, not from stored digests, so
a writer who replaces the FLAC with different PCM is caught even when every receipt hash is refreshed.

Limits of that claim:

* It is identity of the audio, not of the encoder settings. A different valid encoding of the same PCM (for example
  `flac -0`) with a fully rewritten receipt, summary and result **verifies**; verification does not authenticate
  which encoder options produced `audio.flac`.
* The reference PCM is the capture retained in the same, writable publication directory (`captured.wav` and
  `captures.json`). The identity is relative to that capture. A writer who consistently rewrites the capture, the
  raw PCM bridge and every derived record and digest is not detected.
* Nothing here is an authenticity certificate for the recording or for who produced the files.

## Workflows

`decodePCM16` followed by SoX `conform` (see the [speech workflow](../examples/schemaxis/flac-speech-workflow.json)) turns
a FLAC recording into PCM16 mono 16 kHz for transcription; the decoded WAV is always within the SoX conform limits.
`encodeLossless` can archive any SoX output. Both operations accept a verified `file` artifact as `source`.

## Limits and not claimed

Other FLAC releases, Ogg FLAC, 24-bit and multichannel audio, lossy conversion, streaming and non-local sources are out of
scope, as are tag editing of existing FLAC files, other tag fields, ReplayGain, pictures, reading tags back out of a FLAC and any claim
that a label identifies or licenses the recording. Source-archive signatures are not verified. The first frame is the only frame header the host checks; a later
corrupt frame is caught by libFLAC (frame CRC) and by the MD5 and length comparison, not by the host parser.
