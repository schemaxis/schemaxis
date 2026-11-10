# Zstandard: checked compressed files and reusable dictionaries

Use this adaptor to compress a scientific result, restore a captured stream,
learn a dictionary from related records, encode one snapshot against another,
join complete frames, or compare format and compression-level choices. Its
runtime baseline is Zstandard 1.5.7. Planning and Studio authoring require no
codec library; execution and verification require the configured native CLI.

```sh
schemaxis configure zstandard /absolute/path/to/zstd
schemaxis run compress.json --output-directory /absolute/path/to/new-run
schemaxis verify /absolute/path/to/new-run
```

The `schemaxis.zstandard/1` document selects one operation. Start with:

```json
{"version":"schemaxis.zstandard/1","operation":"compress",
 "source":"/absolute/path/to/results.bin","level":6,"checksum":true}
```

`compress` publishes `payload.zst` by default. Select `format` as `gzip`, `xz`,
`lzma` or `lz4` for compatibility; their permitted level range is 1–9. Zstandard
supports levels 1–22, or a positive `fast` acceleration instead of an explicit
level. Higher levels trade CPU and memory for size; they do not change decoded
content. `threads` is 1 or 2. `singleThread` selects the native single-thread
I/O implementation and requires `threads: 1`; this differs from one compression
worker with asynchronous I/O.

For Zstandard, `checksum` controls the content checksum and `dictionaryID`
controls whether a dictionary identifier is written. `longWindowLog` enables
long-distance matching with a window of 2 to that power in bytes. `rsyncable`
makes block boundaries more suitable for changed-file transfer. `literals`
chooses automatic, compressed or raw literal coding. The optional `tuning`
object exposes named window, chain, hash and search logs, minimum match length,
target length and strategy. These are expert overrides to the selected level;
start with the level alone. A chain table requires an explicit non-fast strategy;
search effort requires an explicit strategy beyond fast/doubleFast. Minimum match
lengths 4–6 are universally available; three requires an optimal binary-tree
strategy and seven requires fast. Known ignored/clamped combinations are refused,
including equivalent benchmark settings. Compatibility codecs refuse Zstandard-only controls.

`chunkBytes` creates independently compressed chunks and joins their complete
Zstandard frames, at most 256. Zero makes one frame, including for empty input.
`streamInput: true` feeds the captured content through standard input, so its
frame normally omits a known content size. `pledgedBytes` supplies the exact
captured byte count for one frame; a mismatch is refused before native execution.
`contentSize` selects `automatic`, `omit` or `require`; requiring size for stream
input needs a pledge. `sizeHintBytes` instead supplies an approximate planning
hint. It cannot accompany a pledge. Actual decoded size stays bounded in every
mode. This is a finite captured stream.

`targetBlockBytes` asks for an approximate compressed block target; it does not
guarantee exact block sizes. `jobBytes` sets worker compression jobs of at least
512 KiB; `tuning.overlapLog` sets preceding history reuse. The typed `ldm*`
tuning controls require explicit `longWindowLog`. A nonzero `targetLength`
requires explicit `fast`, `btopt`, `btultra` or `btultra2` strategy because other
strategies ignore it. `adaptive: {"minLevel": 1, "maxLevel": 9}` lets the native
compressor vary effort within bounds containing the initial level. Adaptive
encoding is not reproducible: content and frame policy are verified, while
`adaptiveLevelHistoryVerified` remains false. Jobs, overlap and adaptation need
worker-based I/O.

`restore` publishes `restored.bin`. `inspect` publishes a summary without a
second copy of the decoded bytes. Both accept a captured `dictionary` or delta
`reference`, and `maxDecodedBytes` caps the actual output, including streams
that omit their content size. The decoder also caps the window at 256 MiB and
disables pass-through of uncompressed files. Zstandard inspection reports every
frame's offset, encoded size, declared content size, window, dictionary ID,
block layout and checksum. Skippable frames are retained in frame inspection
but contribute no decoded content; a valid skippable-only stream restores zero
bytes. `sparseOutput` allows native sparse writes for zero runs. Logical bytes
are verified, while physical allocation depends on the filesystem. Other codecs report detected format,
decoded length and SHA-256; their internal block metadata is not interpreted
by the host reader.

`trainDictionary` captures 8–128 sample files and publishes `dictionary.zdict`.
Use representative training records and test on held-out records. `algorithm`
selects `fastCover`, `cover` or `legacy`; `maxDictionaryBytes` bounds the result
and `id` fixes its public identifier. Cover algorithms use `segmentSize`,
`dmerSize`, `steps` and `trainingFraction`; the fraction has whole-percent
precision and must leave at least five training samples. FastCover additionally
uses `frequencyLog` and `acceleration`. Cover supports `shrink`; legacy uses
`selectivity`. `trainingLevel` controls native candidate evaluation;
`sampleBlockBytes` divides large samples into records. Cover's
`shrinkRegression` sets its permitted performance loss in percent when shrinking.
Parameters belonging to another algorithm are refused. A
dictionary's identifier is not a cryptographic identity: captured SHA-256 and
fresh decoding bind the actual dictionary bytes. For untrained history bytes,
select `dictionaryMode: "raw"` alongside `dictionary`. Raw dictionaries must be
nonempty and omit the trained magic header; their numeric identifier is zero.
A dictionary and a delta reference cannot be used together.

`inspectDictionary` takes an external dictionary as `source`, with
`dictionaryMode` selecting trained or raw history bytes. It publishes
`dictionary.json` with byte length, SHA-256, representation and numeric ID.
The exact bytes must also load in fresh native compression and decoding of an
independently known empty payload. This checks trained entropy-table validity;
it does not claim compression gains on an unseen corpus.

`encodeDelta` uses `source` as the new snapshot and `reference` as the earlier
snapshot. It publishes one Zstandard frame. The reference is a required durable
dependency, not an embedded full copy. Keep the captured reference for future
restoration. `concatenate` takes an ordered `sources` list of complete Zstandard
streams and publishes `payload.zst`. It verifies each input and the joined
decoded order; compressed files are not filesystem archives.

`compareProfiles` takes 1–4 named `profiles`, each with `id`, `format` and
`level`. It publishes each compressed candidate and `profiles.json`. Sizes and
exact recovered content are checked again later. `elapsedSeconds` records local
producer wall time; `timingVerified` is false because a later run cannot
authenticate historical timing. Compare timings only under controlled local
conditions. This operation makes no hardware-independent throughput claim.

`benchmark` runs the actual native in-memory compression/decompression benchmark
over captured content. Choose `firstLevel` and `lastLevel` for up to four
consecutive levels, `minimumSeconds` from 1–3 per measurement and optional
`benchmarkBlockBytes` for at most 256 independent blocks. Dictionary and typed
match-finder choices remain available. Independently created CLI frames and
exact restoration check reported sizes. `benchmarkDecode` measures an existing
compressed stream, optionally with its exact dictionary. Both publish checked
`benchmark.json` and native `benchmark.txt`; later verification reruns native
measurements and checks sizes and ratios, while `timingVerified` stays false.

`compressFiles` and `restoreFiles` select one reusable `fileSet`. Either provide
`root` with `recursive`, `include` and `exclude`, or list explicit `files` with
absolute `source` paths and relative `name` values:

```json
{"version":"schemaxis.zstandard/1","operation":"compressFiles",
 "fileSet":{"root":"/absolute/path/to/campaign",
            "include":["*.bin","*.csv"],"exclude":["temporary/*"]},
 "level":6}
```

Directory patterns are case-sensitive shell-style patterns over whole relative
names; `*` also matches separators. Matching excluded directories are pruned.
Selected symbolic links and special files are refused. A selection examines at
most 4096 directory entries, 16 path components and 32 files. Explicit named
inputs can combine different directories while keeping distinct names such as
`run-A/data.bin` and `run-B/data.bin`.

Publication uses `files/` plus checked relative names, with a `files.json`
manifest. Compression appends the codec suffix. Restoration strips recognised
suffixes, translating shorthand tar suffixes such as `.tgz` to `.tar`, or appends
`.decoded` for an unrecognised name. Case collisions, duplicate outputs,
file-versus-directory collisions and traversal names are refused. Publish
outside a selected root. The captured selection and bytes remain sufficient for
fresh verification after the original directories disappear.
Retained selections also obey excluded ancestor directories. Names are valid
UTF-8 with at most 1024 bytes and 255 bytes per component. Each output leaf
reserves 32 additional bytes for shared metadata and atomic publication;
the actual destination filesystem name/path limits are checked before capture
or native work. Names are never truncated to make them fit.

File sets share aggregate limits: 64 MiB raw compression input, 72 MiB compressed
input/output and one `maxDecodedBytes` budget for all restored files, including
unknown-size frames. The compressor can retain dictionaries, chunking and other
typed controls. A required content size for streamed file-set compression derives
each exact pledge from its captured member. File names and content are retained;
permissions, ownership and timestamps are not archived.

Every operation also publishes `summary.json`. The run retains `authored.json`,
the effective `plan.json`, bounded captured inputs and their membership record,
stage stdout/stderr, launchers, process submissions, a verification inventory
and a successful or failed `result.json`. A fresh verifier uses the trusted
configured executable, copies only current retained bytes to a fresh workspace,
checks content and frame checksums, and reconstructs deterministic compression
and dictionary training. Original input files are not consulted. Captures are
unsigned local provenance; coordinated replacement of intent, captures and all
results is not an authenticated historical claim.

Use workflow artifact bindings to feed a file or text publication into `source`,
`dictionary`, `reference`, or an element of `sources`/`samples`. Input digests
participate in reuse identity. Edit the authored parameters or change the source
bytes to request a new result; keep the parent run for comparison. Native
commands share one deadline and process-group cancellation, with actual native
output size and address-space limits. Publication uses a fresh directory.

Common recovery paths:

- `INVALID_ZSTANDARD_OPTION`: select controls applicable to the chosen codec or
  training algorithm; choose fast acceleration or an explicit level.
- `INVALID_ZSTANDARD_SOURCE` / `RESOURCE_NOT_FOUND`: select an absolute regular
  local file with no symbolic-link components.
- `INVALID_ZSTANDARD_FILE_SET`: choose a root or named files, correct relative
  names or selection patterns, resolve output collisions and publish outside
  the selected source root.
- `ZSTANDARD_BUDGET`: reduce captured bytes, frame count, native memory demand
  or decoded output; a missing content-size header never removes the cap.
- `INVALID_ZSTANDARD_FRAME`: inspect truncation, block types and frame headers;
  do not repair a corrupted stream by changing its receipt.
- `ZSTANDARD_NATIVE_FAILED`: inspect the stage stderr for a wrong dictionary,
  stale reference, insufficient training corpus or unsupported runtime build.
- `VERIFICATION_FAILED`: retain the failed run for diagnosis and rerun into a
  new directory from trusted intent and dependencies.

The bounded stable Zstandard 1.5.7 CLI content scope has passed independent
whole-inventory review and integrated engineering acceptance. The dated
`verification/2026-11-05-zstandard.md` records the supported workflows, reviewed
exclusions and source-bound native, Studio and package evidence. This acceptance
does not authorise a public release.


An explicit `jobBytes` also needs `tuning.windowLog` or `longWindowLog` so
Schemaxis can bound native history overlap before launch. Jobs must cover at least
512 KiB and the selected overlap; automatic `overlapLog: 0` reserves the entire
window. Omit `jobBytes` to retain native automatic scheduling.

When restoring a directory of published files, select compressed suffixes such as
`fileSet.include: ["*.zst"]`. Shared publication metadata companions are JSON
records and are not compressed streams. Selection remains explicit: a file called
`*.metadata.json` can still be ordinary user data in a compression file set.

`encodeDelta` derives its native history window from captured input sizes.
Explicit `tuning.windowLog`, `longWindowLog` and `jobBytes` overrides are refused
for that task: the native patch encoder replaces the requested window, which can
also raise its minimum worker job size. Worker counts and applicable matching
controls remain available; restoration still proves exact snapshot bytes.

## Pinned workflow inputs

A workflow can read an immutable snapshot produced by `schemaxis input adopt`.
Adopt the completed source file first, then place the command's emitted
`reference` object in `source`, `dictionary`, `reference`, an individual `sources`
or `samples` entry, or a named `fileSet.files` entry's `source`. The chosen task
must actually consume that field. A member selected from a captured directory
is also a file input. These records belong in a workflow document; standalone
literal input still uses local paths.

For a complete directory capture, use `schemaxis input adopt SOURCE SNAPSHOT
--kind directory` and place its emitted reference in `fileSet.root`. Only its
captured data directory is scanned; snapshot metadata is outside the selection.
Existing recursion, include/exclude, regular-file, aggregate byte and collision
limits remain in force. A directory cannot be substituted for an individual
file or dictionary.

The pinned digest is checked before consumption and during workflow verification.
Changing captured bytes is refused, including on resume; deliberately adopt a new
snapshot and update the authored reference to use new content. Removing the
original source after adoption does not change the snapshot. Units and coordinate
frames are not inferred from compressed bytes.
