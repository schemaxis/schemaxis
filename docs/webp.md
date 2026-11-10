# WebP publication: lossless, bounded lossy for opaque images, and decode to PNG

Use `schemaxis.webp/1` to **publish one PNG as a WebP** for a web page, with one of two operations,
or to **decode one static WebP back to a PNG** with a third ([`decodeToPng`](#webp-to-png-decodetopng)).
`encodeLossless` captures the PNG, encodes it with libwebp's `cwebp -lossless -exact`, and decodes the
published bytes again with a separate `dwebp` process: every red, green, blue and alpha sample must
match the PNG, including the colour hidden under fully transparent pixels. It suits illustrations,
logos and transparent assets reused without any pixel change.

`encodeLossy` is the explicit alternative for **opaque photograph-like images**, where a bounded loss
of accuracy buys a smaller file. You author an integer quality, a mean-error budget and, optionally, a
byte budget; the adaptor publishes only a file whose fresh `dwebp` decode stays inside both budgets
([lossy publication](#lossy-publication-encodelossy)). Neither operation resizes, animates, retains
metadata or accepts authored encoder flags, and neither guarantees a smaller file than the PNG.
Lossless is the right choice for transparency, drawings and exactness; lossy needs an opaque source
and a quality/size tradeoff that you choose. `decodeToPng` is the reverse handoff for an existing web
asset: it needs only `dwebp` and publishes a canonical PNG that Pandoc and other PNG consumers accept.

## Setup

A run needs **two** libwebp 1.6 executables, from the same build: `cwebp` with `--webp` (or
`schemaxis configure webp`, or `SCHEMAXIS_WEBP`) and `dwebp` with `--dwebp` (or a `dwebp` entry in your
private configuration's `locations`, or `SCHEMAXIS_DWEBP`; `schemaxis configure` only names adaptors).
Verification and `decodeToPng` need only `dwebp`. The `--webp` and `--dwebp` flags belong to `schemaxis run` and
`schemaxis inspect`; bare `schemaxis verify OUTPUT` accepts only the directory, so it finds the decoder
from `SCHEMAXIS_DWEBP` or a stored `dwebp` location. A missing, relative-path or non-1.6 executable is a
fault, never a skipped check. Receipts never supply an executable.
Discovery and planning need only Python 3.10+. Official libwebp tools are built from the
[official source archive](https://storage.googleapis.com/downloads.webmproject.org/releases/webp/index.html);
a build without libpng is fine because the adaptor passes pixels through a canonical PAM file
(`cwebp` and `dwebp` document PNM/PAM support).

```json
{
  "version": "schemaxis.webp/1",
  "operation": "encodeLossless",
  "source": "/absolute/path/to/illustration.png"
}
```

```sh
schemaxis plan publish.json
schemaxis run publish.json --output-directory output/webp --webp /path/to/cwebp --dwebp /path/to/dwebp
SCHEMAXIS_DWEBP=/path/to/dwebp schemaxis verify output/webp
```

To verify without the environment variable, store the decoder once in the git-ignored
`.schemaxis.local.json` in the current working directory (or the file named by `SCHEMAXIS_CONFIG`):
`{"version": 1, "locations": {"dwebp": "/path/to/dwebp"}}`. Without either, `schemaxis verify` reports
`INTERPRETER_NOT_FOUND` and never a verified result.

The [baseline](../examples/schemaxis/webp-baseline.json) publishes a 7×5 RGBA swatch with
transparent pixels that carry colour ([fixture](../examples/schemaxis/fixtures/webp/swatch-rgba.png));
the [variant](../examples/schemaxis/webp-variant.json) publishes a 96×64 flat-colour landscape; the
[opaque case](../examples/schemaxis/webp-opaque.json) publishes a 5×3 RGB image. In Studio choose
**WebP → Publish a lossless WebP** or **Publish a bounded lossy WebP**. See the [generated operation reference](generated/webp-operations.md).

## What the fields mean

| Field | Meaning |
| --- | --- |
| `version` | `schemaxis.webp/1`. The document contract, not the libwebp release. |
| `operation` | `encodeLossless`, `encodeLossy` or `decodeToPng`. |
| `source` | Absolute local `.png` (`.webp` for `decodeToPng`). A verified image artifact from an earlier workflow step is also accepted. |
| `quality` | `encodeLossy` only, required: integer 0–100 passed to `cwebp -q`. 100 is **not** lossless. |
| `maxMeanRGBError` | `encodeLossy` only, required: finite number 0–255, the largest accepted mean absolute RGB error. |
| `maxBytes` | `encodeLossy` only, optional: integer 1–16,777,216, the largest accepted `image.webp` size. Omitted, the global 16 MiB cap applies and the plan records that default. |

`decodeToPng` takes `source` only and rejects every other field. Authored encoder flags, near-lossless levels, automatic quality or size targets, resize, crop,
metadata and animation fields are rejected as unknown arguments, and `encodeLossless` rejects the
three lossy fields. Booleans, strings and decimals where an integer is required, `NaN`, infinity and
out-of-range values are `INVALID_ARGUMENT`; a missing `quality` or `maxMeanRGBError` is
`MISSING_ARGUMENT`.

## Supported subset and refusals

| Input or situation | Result |
| --- | --- |
| Non-interlaced 8-bit RGB or RGBA PNG, untagged or sRGB, ≤ 2048 per side, ≤ 1,048,576 pixels, ≤ 8 MiB | Accepted. RGB gains alpha 255. |
| Relative path, URL, prefix, non-`.png` name | `INVALID_WEBP_SOURCE` at `$.source` |
| Missing, symlinked, non-regular or oversized file | `INVALID_WEBP_SOURCE` |
| Truncated, corrupt, palette, greyscale, 16-bit, interlaced or tRNS PNG | `INVALID_WEBP_PNG` |
| Larger than the pixel budget | `WEBP_PIXEL_BUDGET` (checked from the header before decompression) |
| Embedded ICC profile (`iCCP`), `cICP`, or `gAMA`/`cHRM` other than sRGB | `WEBP_COLOUR_UNSUPPORTED` |
| Animated PNG | `WEBP_ANIMATION_UNSUPPORTED` |
| cwebp/dwebp not 1.6 | `UNSUPPORTED_RUNTIME` |
| Executable absent, relative or not executable | `INTERPRETER_NOT_FOUND` |
| Output directory already exists, including one created between the check and creation | `OUTPUT_EXISTS` |
| Published `image.webp` is well framed but `dwebp` cannot decode it | `VERIFICATION_FAILED`; `cause` carries the original `NATIVE_EXECUTION_FAILED` fault |
| Retained JSON with duplicate keys, `NaN`/`Infinity`, a number that overflows (`1e400`), excess depth, or a changed type (`true`→`1`, `66`→`66.0`) | `VERIFICATION_FAILED` (duplicate or malformed `authored.json` may first be refused as `INVALID_SCHEMA_SNAPSHOT` by the shared schema-snapshot layer) |
| Native failure, timeout, cancellation | `NATIVE_EXECUTION_FAILED`, `RUNNER_TIMED_OUT`, `RUNNER_CANCELLED` |

The shared PNG decoder ignores ancillary colour chunks, so the adaptor scans them itself rather than
silently dropping a profile. An untagged PNG is **treated as sRGB**, the web convention; the WebP
carries no colour profile either. Ancillary chunks such as text, EXIF, physical size and timestamps
are dropped and listed in `webp-summary.json` (`droppedAncillaryChunks`).

## Lossy publication (`encodeLossy`)

```json
{
  "version": "schemaxis.webp/1",
  "operation": "encodeLossy",
  "source": "/absolute/path/to/photo.png",
  "quality": 80,
  "maxMeanRGBError": 3,
  "maxBytes": 524288
}
```

The native command is `cwebp -q 80 -m 6 -alpha_q 100 source.pam -o image.webp`, with `-m 6` (slowest,
smallest) and `-alpha_q 100` fixed, no `-lossless` and no `-near_lossless`. `-q` is libwebp's
**lossy** compression factor for the RGB channels; the official
[cwebp](https://developers.google.com/speed/webp/docs/cwebp) documentation and libwebp 1.6.0's own
`cwebp` manual page describe a small value as a smaller, lower-quality file and a value of 100 as the
best lossy quality. `-q 100` still discards information. The adaptor never searches for a quality: if a
result misses a budget, choose another value and run again.

**Requirements and decision.** Every source pixel must have alpha 255. A partly or fully transparent
pixel is refused with `WEBP_ALPHA_UNSUPPORTED` (observed pixel counts and a recovery text naming
`encodeLossless`); nothing is composited or discarded silently. After encoding, the published bytes
are checked for strict simple-format framing (RIFF, exactly one `VP8 ` chunk, displayed key frame,
start code, unscaled dimensions within the pixel budget; `VP8L`, `VP8X`, `ALPH`, animation, ICC, EXIF
and XMP are refused), then decoded by a fresh trusted `dwebp -pam` in a private directory. The host
compares **every R, G and B sample** with the PNG-decoded source: the exact integer sum of absolute
differences over `width × height × 3` samples, divided by that count. That mean is compared with
`maxMeanRGBError` as an exact rational, and the file size with `maxBytes`. The budget is taken as the
decimal written in the document (the shortest decimal that reproduces the number, so `0.3` is exactly
3/10, not the nearby binary fraction): an error of exactly 18/60 meets a budget of `0.3`, 19/60 does not.
The refusal message names the exact fraction and the authored budget, so two equal-looking numbers
cannot be reported as one exceeding the other. Dimensions must equal the source and every decoded alpha sample must be 255. Zero is a
legitimate budget; it refuses any decode that is not bit-identical.

**Over budget.** A correct file that misses either budget fails with `DELIVERABLE_NOT_MET`, location
`$.maxMeanRGBError` or `$.maxBytes`, `observed.assessment` (measured sum, samples, mean or bytes, the
budgets and quality) and a recovery text. The run is recorded as `failed`, `verified: false`; the
encoded file, native logs and decode are retained as evidence, but no summary or receipt is written
and nothing is published. `schemaxis verify` refuses such a directory (`INCOMPLETE_EXECUTION`), and
editing `result.json` to claim success does not help: verification recomputes the decision from the
retained bytes, source and the authored request, so an over-budget decode is again
`DELIVERABLE_NOT_MET` and edited plans, summaries or claims are `VERIFICATION_FAILED`.

**What the number means.** It is a mean absolute difference in 8-bit RGB levels against the trusted
`dwebp` run with its default options (the official dwebp documentation and libwebp 1.6.0's `dwebp.c` leave
dithering off unless `-dither` or `-alpha_dither` is given). Only that decode is compared; it is not a
perceptual score, hides local damage behind an average, and does not describe other decoders or viewers. There is no guaranteed
compression ratio: smooth gradients and photographs often shrink a great deal, while flat charts, line
art and screenshots can come out both **larger and less accurate** than lossless. The two bundled
examples show both outcomes, measured with libwebp 1.6.0 (see the
[verification note](../verification/2026-10-25-webp-43.md)): a 96×60 gradient
([example](../examples/schemaxis/webp-lossy-gradient.json)) is 18,085 bytes as PNG and 442 bytes lossy
at `-q 80` with mean error 2.30, whereas a 96×64 colour chart
([example](../examples/schemaxis/webp-lossy-chart.json)) is 335 bytes as PNG and 1,768 bytes at
`-q 90` with mean error 8.79. A [tight budget](../examples/schemaxis/webp-lossy-tight-budget.json) and a
[translucent source](../examples/schemaxis/webp-lossy-translucent.json) demonstrate the two refusals.
Native acceptance: `tools/qualify_webp_lossy.py`.

Lossy summaries (`webp-summary.json`) add `request` (quality and both budgets), `error`
(`sumAbsoluteRgb`, `samples`, `meanAbsoluteRgb`, `withinBudget`) and a `readback` with
`allAlpha255`. The container is `RIFF WEBP simple format, one VP8 chunk`. `request.quality` repeats
the authored request: it is a requested setting, not something recovered or authenticated from the
pixels or bitstream (the same holds for `-m` and `-alpha_q`). What the native pixel error and byte count
establish is that the published file is within the authored budgets against `dwebp`; a different valid
VP8 file inside both budgets, with every record rewritten to agree, also verifies. Verification cannot prove
which encoder, quality or history produced the bytes.

## WebP to PNG (`decodeToPng`)

```json
{
  "version": "schemaxis.webp/1",
  "operation": "decodeToPng",
  "source": "/absolute/path/to/asset.webp"
}
```

```sh
schemaxis run decode.json --output-directory output/png --dwebp /path/to/dwebp
SCHEMAXIS_DWEBP=/path/to/dwebp schemaxis verify output/png
```

The WebP is captured once (at most 16 MiB), its RIFF framing is read by the host, and
`dwebp captured.webp -nodither -pam -o decoded.pam` decodes it in a separate bounded process. The host writes
those samples as `image.png` and publishes it with `webp-summary.json`. **Only `dwebp` is needed**; `cwebp` is
neither required nor launched, and `--webp` is ignored. Demand for this direction is unproven; it is offered as a
practical handoff so existing static web assets can enter reports and other PNG-only tools.
The [lossless](../examples/schemaxis/webp-decode-lossless.json), [RGB](../examples/schemaxis/webp-decode-rgb.json)
and [lossy](../examples/schemaxis/webp-decode-lossy.json) examples use fixtures made by libwebp 1.6.0
(`examples/schemaxis/fixtures/webp/decode-literal-rgba.webp`, `decode-swatch-rgb.webp` and `decode-gradient-lossy.webp`
in that directory): the first encodes a hand-written 4×3 RGBA literal with partial alpha and RGB hidden under alpha 0.

**Accepted input (the closed simple profile).** A RIFF/WEBP file of exactly one `VP8L` chunk (lossless, alpha hint set
or not) or exactly one `VP8 ` chunk (opaque lossy), correct RIFF and chunk sizes, zero padding, no trailing bytes,
at most 2048 pixels per side and 1,048,576 pixels. A lossy frame must be a displayed key frame of profile 0–3 with the
`9d 01 2a` start code, a first partition that fits the chunk and non-zero dimensions. The two upscaling bits at the top
of each VP8 width and height field are a display hint that libwebp 1.6 ignores (it decodes the coded size, and so does
this adaptor), so a frame that sets them is accepted and the PNG has the coded dimensions. All of this is judged before
any native process runs:

| Input | Result |
| --- | --- |
| Relative path, URL, non-`.webp` name | `INVALID_WEBP_SOURCE` at `$.source` |
| Missing, symlinked, non-regular or over 16 MiB | `INVALID_WEBP_SOURCE` |
| Not RIFF/WEBP, truncated, trailing or extra chunks, bad sizes, bad VP8L/VP8 header, other first chunk | `INVALID_WEBP_IMAGE` |
| `VP8X` with the animation flag | `WEBP_ANIMATION_UNSUPPORTED` |
| Other `VP8X` (ALPH alpha, ICC, EXIF, XMP) | `WEBP_FORMAT_UNSUPPORTED` |
| Beyond 2048 per side or 1,048,576 pixels | `WEBP_PIXEL_BUDGET` |
| Well framed but `dwebp` cannot decode it | `INVALID_WEBP_IMAGE`, original fault in `cause` |
| Alpha hint absent but a decoded alpha sample is not 255 | `WEBP_ALPHA_MISMATCH` from a run; the same contradiction found while verifying a retained run is `VERIFICATION_FAILED` with the original fault in `cause` |
| `dwebp` not 1.6, absent or relative | `UNSUPPORTED_RUNTIME`, `INTERPRETER_NOT_FOUND` |

**The PNG.** 8-bit non-interlaced, exactly `IHDR`, one `IDAT` of filter-none rows and `IEND`: no `sRGB`, `gAMA`,
`iCCP` or text chunk. It is untagged, which by web convention means sRGB; the accepted WebP profile has no colour
profile or metadata to carry. Pandoc's report image rule accepts exactly these chunks. It is RGBA when the VP8L alpha
hint is set and RGB otherwise (always RGB for lossy). Samples are written verbatim, so RGB under alpha 0 survives.
The `IDAT` bytes come from the host zlib (level 9), so the PNG file digest can differ between zlib builds while every
sample does not; verification therefore compares structure and samples, not recompressed bytes.

**What the decode is.** Lossless input decodes exactly. A lossy WebP becomes the output of libwebp 1.6 `dwebp` with
its default options. The
[official dwebp documentation](https://developers.google.com/speed/webp/docs/dwebp) states that `-pam` retains alpha, that dithering is
off by default (`-nodither`, which the adaptor passes explicitly; in the native acceptance run the default and
`-nodither` and `-dither 0` gave identical bytes) and that animated files are not handled. Fancy upsampling stays at its
default; `-nofancy` gives different lossy samples, so another decoder or viewer may differ slightly from the PNG. Nothing
claims the PNG equals the picture the WebP was made from.

**Verification** (`schemaxis verify`, needs the trusted `dwebp` as above) holds one read of each retained file and:
reads retained JSON strictly with typed, closed claims; rereads `captured.webp` against `captures.json` and the
framing; copies those bytes to a private directory and decodes them with a fresh `dwebp`; requires dwebp's own
one-line report (dimensions, lossless or lossy, alpha) to agree with the framing; requires the run's `decoded.pam`
to equal that decode; reads `image.png` with a strict canonical reader **and** with the shared bounded PNG decoder and
requires every RGBA sample, dimensions and colour type to match; recomputes the summary; and checks the receipt's
membership, evidence digests, launchers, input bindings and exit records. Replacing `image.png` (one hidden-RGB sample,
dropped alpha, an extra `tEXt` chunk, filtered rows, trailing bytes, truncation) is refused even after every hash,
the summary and the receipt are rewritten. **The original source path is never read again**: verification still
succeeds if it was moved or changed after capture.

**Limits of the claim.** `dwebp` is the decoder oracle: this is semantic agreement with libwebp 1.6, not an independent
host WebP decoder. It does not authenticate the WebP: someone who replaces the captured WebP, the readback, the PNG,
the summary and the receipt consistently produces a new valid run. Receipts never supply the executable. Nothing here
certifies compression, quality or appearance under colour management.

Pandoc accepts the published `image.png` by path or, in a workflow, as a typed image reference
such as `{"$artifact": "decode", "index": 0}` at an image `source`.
See [images from an earlier workflow step](pandoc.md#images-from-an-earlier-workflow-step)
for examples and the consumer's stricter byte budget. The original decoder acceptance used a
PNG path ([note](../verification/2026-10-25-webp-51.md)); the later handoff acceptance checks
HTML, DOCX and optional EPUB copies against the verified producer's PNG.

## What is published

For `decodeToPng` the publications are `image.png` and `webp-summary.json` (source and PNG bytes and SHA-256, container,
alpha hint, pixel and hidden-RGB counts, dwebp's report, the decoded RGBA SHA-256).
For the encode operations: `image.webp` (a RIFF/WebP file with exactly one `VP8L` chunk; one `VP8 ` chunk for `encodeLossy`) and `webp-summary.json`
(`schemaxis.webp.summary/1`): source and WebP byte counts and SHA-256, dimensions, colour
declaration, dropped chunks, the VP8L alpha flag, pixel counts (opaque, partial alpha, transparent,
and transparent pixels that still carry non-zero RGB), and the SHA-256 of the exact decoded RGBA.
Inspect the summary before replacing a PNG: if `image.bytes` is not smaller, keep the PNG.

## Verification contract

The steps below are those of `encodeLossless`. `encodeLossy` follows the same structure (strict JSON
and typed claims, captured PNG, receipt, launchers, digests, trusted `dwebp` from outside the receipt,
fresh private decode of the actual bytes) with VP8 framing and the error and byte judgement described
above in place of byte equality; the literal `-q` argument vector is rebuilt from the authored quality
and compared with the retained launcher.

There is **no independent host WebP decoder** in Schemaxis. The host can check the file's RIFF and
VP8L framing and read a PAM exactly, but only libwebp can decode lossless data, so
`schemaxis verify` **needs the trusted `dwebp`** (resolved from the invocation context, stored
configuration or `SCHEMAXIS_DWEBP`, never from the receipt; not `cwebp`). Offline it can prove nothing about
whether the retained bytes decode to the source, and it says so with `INTERPRETER_NOT_FOUND`
rather than reporting success. It then:

1. reads every retained JSON file strictly (no duplicate keys, `NaN`/`Infinity`, numbers that overflow
   to infinity, or excess depth) and compares the plan, capture record, summary, native input bindings and
   the result record in typed canonical form, so `true` is not `1` and `66` is not `66.0`. The result is a
   **closed set** of claims: every key except `status` is compared, so an extra, missing, promoted or
   mistyped field (`lossless: true`, `perceptual: true`, a compression ratio, a changed count) is
   `VERIFICATION_FAILED`. Only the text of `runtime.freshDecoder` may differ, because it is the identity
   of whichever trusted `dwebp` verifies; it must still be present and a libwebp 1.6 identity string;
2. rereads the captured PNG, requires it to match the capture record, decodes it with the shared
   bounded decoder, applies the colour/animation policy, and rebuilds the canonical PAM bridge;
3. reads the actual `image.webp`, requires exactly one `VP8L` chunk with consistent RIFF and chunk
   sizes (lossy `VP8 `, extended `VP8X`, `ALPH`, `ICCP`, `EXIF`, `XMP `, `ANIM` and trailing bytes are
   refused) and the PNG's dimensions;
4. copies exactly those bytes to a private directory and runs `dwebp -pam` in a fresh bounded
   process, parses its PAM strictly, and compares **every RGBA byte** with the captured PNG. A payload
   that is well framed but that `dwebp` cannot decode is `VERIFICATION_FAILED` (the original fault is kept
   as its `cause`); an unavailable decoder, wrong version, timeout or cancellation keep their own codes;
5. requires the run's retained `reopened.pam` to equal the fresh decode, the encode log's reported
   size to equal the actual file size, and the retained summary to equal the recomputed one;
6. checks the receipt's publication membership and digests, retained evidence digests, the observed
   libwebp 1.6 versions, and each native launcher, input binding and exit record. `image.webp` is read
   once: the receipt's digest and the decode-input binding are checked against the very bytes that were
   decoded, not against a second read.

A changed `image.webp` therefore cannot be hidden by refreshing artifact hashes: the decision comes
from decoding the current bytes. In the native acceptance run, replacement files made by real
libwebp (lossless without `-exact`, which zeroes hidden RGB; lossy with alpha; a different image of
the same size; an added EXIF chunk; truncated; trailing bytes) and a file with a valid frame but a
zeroed bitstream were rejected even after the receipt, evidence digests and shared publication manifest
were rewritten to agree. The summary was rewritten as well wherever the forged file could be
summarised (lossless without `-exact`, different pixels, the zeroed bitstream, an equivalent
re-encode); for lossy, EXIF, truncated and trailing-byte files it could not be, so the old summary was
kept and the framing check rejected them. Retained JSON that changed only a type, repeated a key or
held `NaN` or `1e400` was refused with every ordinary hash refreshed too.

Retained logs and launchers are hash-bound provenance and are not re-executed. What this proves: the
bytes read during the verification call decode, in libwebp 1.6, to exactly the captured PNG's
samples. It says nothing about changes made to the directory after the call returns: verification
reads a snapshot and does not lock or guard the files against a concurrent writer. It does not prove
those bytes came from the recorded `cwebp` command: a different valid lossless encoding of the same
pixels is accepted once a forger also rewrites the receipt, summary, result record and manifest (the
acceptance run confirmed this, and that a stale summary or result record alone is refused; the pixels
are identical, so the claim above still holds). For `encodeLossy` the corresponding claim is weaker and
different: a valid VP8 encoding at another quality, `-m` or `-alpha_q` whose decoded pixels and size are
inside both budgets verifies after the same rewrite, because the pixel error and byte count against `dwebp`
are what is judged, not the encoder settings, `request.quality` or the file's history. It is not a signature and
trusts `dwebp` as the decoder oracle. Someone who rewrites the request, capture and output
consistently produces a new valid run.

## Limits, lifecycle and reuse

* ≤ 2048 per side and ≤ 1,048,576 pixels (the pure-Python PNG decode, PAM comparison and fresh
  verification scale with pixels); source ≤ 8 MiB; WebP ≤ 16 MiB; logs ≤ 1 MiB.
* `decodeToPng`: WebP ≤ 16 MiB, PNG ≤ 5 MiB; no encoder launch. Counted with a real `dwebp` behind a logging wrapper:
  the low-level run makes four `dwebp` launches (version and decode, then the same two again in its own built-in
  verification); the shared entry point (`schemaxis run`, `adaptor.run`) adds the shared runtime's verification, so six per
  run; a stand-alone verification makes two. One total deadline covers every launch of a run.
* One serial native process at a time under the shared cancellable runner with POSIX address-space
  (2 GiB), file-size and CPU (120 s) caps and a minimal environment. `--timeout` covers every
  launch including verification (maximum 3600 s); standalone verification has its own 120 s budget.
  A run makes four native launches and its verification two more; the shared runtime verifies again.
* Fixed effort (`-z 6` lossless, `-m 6` lossy); output is deterministic for the same input and libwebp build.
* The captured PNG bytes, not only the path, determine workflow reuse.

## Workflow and handoff

[ImageMagick → WebP](../examples/schemaxis/webp-publish-workflow.json) prepares an exact PNG detail
([ImageMagick](imagemagick.md)) and binds its verified `image` publication to this adaptor. This
file is planned on the host; the native acceptance run did not execute ImageMagick, so the
combined route is not native-qualified. The encode operations publish a WebP as a terminal asset;
`decodeToPng` reads an existing static WebP by absolute path and is how a WebP re-enters a PNG workflow. This page
makes no claim about how other adaptors treat WebP.

## Native mapping and sources

`dwebp captured.webp -nodither -pam -o decoded.pam` (`decodeToPng`; the host writes the PNG), `cwebp -lossless -exact -z 6 source.pam -o image.webp` (lossless) or `cwebp -q N -m 6 -alpha_q 100 source.pam -o image.webp`
(lossy) and `dwebp image.webp -pam -o reopened.pam`
follow the official [cwebp](https://developers.google.com/speed/webp/docs/cwebp) and
[dwebp](https://developers.google.com/speed/webp/docs/dwebp) documentation: `-exact` preserves RGB
values in transparent areas, `-z` selects a lossless level (6 is the documented good default),
`-pam` retains alpha. Metadata is not copied (`-metadata none` is the default). The container is
described in the [WebP container specification](https://developers.google.com/speed/webp/docs/riff_container)
and the lossless bitstream header in the [lossless specification](https://developers.google.com/speed/webp/docs/webp_lossless_bitstream_specification).

## Maintenance

`upstream.json` targets libwebp's latest stable release (1.6.0 at the time of writing, from the
official download index). The absorbed version stays unset until source-current native acceptance
is recorded after integration. Qualification covers the cases and runtimes named in its receipt,
not all PNGs.

`tools/qualify_webp_decode.py` is a standalone native probe for `decodeToPng`; it is not an `adaptor.json` hook (the
hooks are `query`, `resources` and `reusableInputs`) and is not wired into `schemaxis adaptor conform`. Its output is a
private probe record with local executable paths, command lines and process IDs, not a public receipt. A public
registration must be written from that record without the local paths, and a source-bound generic conformance receipt
is still to be added after integration. The tool needs `--dwebp`, and `--webp` (cwebp) because it makes its inputs
with the real encoder; a `decodeToPng` run or verification itself needs only `dwebp`. Process IDs are recorded for
the `dwebp` launches that go through its logging wrapper and for its direct probes; the verification-only, legacy and
command-line launches use the plain `dwebp` and are not counted by process ID.
