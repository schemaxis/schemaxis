# eSpeak NG narration draft

Use `schemaxis.espeakng/1` to turn a short plain-text script into a **synthetic voiceover draft**: one
canonical PCM16 mono 22050 Hz WAV (`narration.wav`) plus a JSON `espeakng-summary.json`. It has one operation,
`narrate`. The existing audio adaptors prepare recordings ([SoX](sox.md) `conform`), transcribe them
([whisper.cpp](whispercpp.md)) and publish transcripts ([Pandoc](pandoc.md)), but none can *create* narration. This
adaptor closes that gap with the offline [eSpeak NG](https://github.com/espeak-ng/espeak-ng) synthesizer. The need is a
product judgement from inspecting the existing adaptors, not demonstrated customer demand. By default the voice is the
fixed English (United States) voice; an optional `voice` selects one of four listed voices (see [Voices](#voices)).

The result is a **draft**. It is synthetic speech from a small formant synthesizer, not a human recording, and nothing
here certifies intelligibility, pronunciation, accent or accessibility. A person must read the words and listen to the
sound before publishing it.

## Setup

A run needs one eSpeak NG 1.52.0 `espeak-ng` executable **with its matching native data**: `--espeakng` (or
`schemaxis configure espeakng`, or `SCHEMAXIS_ESPEAKNG`). Verification needs the **same trusted `espeak-ng`** because the
host has no speech synthesizer. `schemaxis verify OUTPUT` takes only the directory, so it finds `espeak-ng` from
`SCHEMAXIS_ESPEAKNG` or a stored `espeakng` location in the git-ignored private configuration
(`{"version": 1, "locations": {"espeakng": "/path/to/espeak-ng"}}` in `.schemaxis.local.json`, or the file named by
`SCHEMAXIS_CONFIG`). The `PATH` is never searched and a receipt never supplies an executable. A missing,
relative-path or non-1.52.0 executable is a fault, never a skipped check. Discovery and planning need only
Python 3.10+. The tested runtime is a private file-output-only build of the official source tag
(see [Native mapping](#native-mapping)).

```json
{
  "version": "schemaxis.espeakng/1",
  "operation": "narrate",
  "text": "Welcome to the plant tour. Please wear your safety glasses and stay behind the yellow line."
}
```

```sh
schemaxis plan narrate.json
schemaxis run narrate.json --output-directory output/narrate --espeakng /path/to/espeak-ng
SCHEMAXIS_ESPEAKNG=/path/to/espeak-ng schemaxis verify output/narrate
```

The [baseline](../examples/schemaxis/espeakng-baseline.json) narrates a literal script at the default 175 words per
minute; the [variant](../examples/schemaxis/espeakng-variant.json) narrates a three-line UTF-8 file
([fixture](../examples/schemaxis/fixtures/espeakng/script-numbered.txt), with accented letters) at 140;
[fast](../examples/schemaxis/espeakng-fast.json) uses digits at the 240 maximum. The
[speech workflow](../examples/schemaxis/espeakng-speech-workflow.json) conforms the narration to PCM16 mono 16 kHz with
SoX, the [archive workflow](../examples/schemaxis/espeakng-archive-workflow.json) stores it as lossless FLAC and the
[transcript workflow](../examples/schemaxis/espeakng-transcript-workflow.json) speaks a whisper.cpp transcript file. The
[`en-gb`](../examples/schemaxis/espeakng-voice-en-gb.json), [`fr-fr`](../examples/schemaxis/espeakng-voice-fr-fr.json) and
[`es`](../examples/schemaxis/espeakng-voice-es.json) examples select a voice, and the
[French archive workflow](../examples/schemaxis/espeakng-voice-archive-workflow.json) narrates French, conforms it with SoX
and stores it as lossless FLAC. In
Studio choose **eSpeak NG → Narrate a short script**.

## What the fields mean

| Field | Meaning |
| --- | --- |
| `version` | `schemaxis.espeakng/1`. The document contract, not the eSpeak NG release. |
| `operation` | `narrate`, the only operation. |
| `text` | The script as a literal string, 1 to 1024 Unicode code points and at most 8 KiB of UTF-8. Exactly one of `text` and `source`. |
| `source` | The script as an absolute local `.txt` file (UTF-8, at most 1024 code points and 8 KiB). A verified `file` or `text` artifact from an earlier workflow step is also accepted. Exactly one of `text` and `source`. |
| `rateWpm` | Speaking rate in approximate words per minute, an integer from 120 to 240. Default 175 (the eSpeak NG default). |
| `voice` | Optional: `en-us`, `en-gb`, `fr-fr` or `es` and nothing else. Absent means the original fixed `en-us` voice with unchanged plans and receipts. See [Voices](#voices). |

Pitch (50) and amplitude (100) are fixed and not authored. Voice names or paths other than the four `voice` choices,
variants, flags, SSML, phoneme codes, gaps, capitals and punctuation options, a network, playback, language detection and
translation are not available; unknown names are rejected as unknown arguments and a `voice` outside the four choices (or
of another type) is `INVALID_ARGUMENT` before any native process or output directory exists. SSML, other markup and phoneme escapes written inside the script text are not
arguments: they are refused as `INVALID_ESPEAKNG_TEXT` (see the table below).

## Supported subset and refusals

The script is **captured as immutable UTF-8 bytes** before anything runs and is refused, never rewritten. The plain-text
profile accepts any Unicode text except the refusals listed in the table below; it is not limited to letters, digits,
punctuation, spaces and line feeds. Symbols (such as `$`, `%` and `+`), combining marks and unassigned code points other
than the two internal ones are not refused by Schemaxis. The synthesizer itself may still ignore a character, expand
numbers and abbreviations ("Dr.", "$5", "10") or read a symbol aloud by its own rules; those are native behaviours, not
Schemaxis edits, which is why the words must be reviewed.

| Input or situation | Result |
| --- | --- |
| Neither or both of `text` and `source`; relative path, URL, prefix or a name that does not end in `.txt` | `INVALID_ESPEAKNG_SOURCE` |
| Missing, symlinked, non-regular or unreadable script file | `INVALID_ESPEAKNG_SOURCE` at `$.source` |
| Empty script; any control character except a line feed (tab, carriage return, form feed, NUL, escape); byte-order mark, soft hyphen or other invisible format character; private-use, line-separator or paragraph-separator character; a lone surrogate; the two code points eSpeak NG uses internally (U+0530, U+0557) | `INVALID_ESPEAKNG_TEXT`, with the code point and its index |
| `[[` or `]]` phoneme escapes | `INVALID_ESPEAKNG_TEXT` (phoneme code is not supported) |
| SSML or other markup (`<` followed by a letter, `/`, `!` or `?`; `&#` or `&name;` references) | `INVALID_ESPEAKNG_TEXT` |
| Text with no letter or digit (spaces and punctuation only) | `INVALID_ESPEAKNG_TEXT` |
| A script file that is not valid UTF-8 | `INVALID_ESPEAKNG_TEXT` (re-save it as UTF-8 without a byte-order mark) |
| More than 1024 code points or 8 KiB, or a finished narration over 120 seconds or 8 MiB | `ESPEAKNG_BUDGET` (the output budget is judged on the finished file) |
| Native output that is silent (every PCM sample zero) or absent | `ESPEAKNG_SILENT_OUTPUT` |
| Native WAV that is not the canonical PCM16 mono 22050 Hz layout | `ESPEAKNG_OUTPUT_REJECTED` |
| `espeak-ng` not 1.52.0, the selected voice not listed exactly (missing, a different name or file), or incomplete native data for that voice | `UNSUPPORTED_RUNTIME` |
| Executable absent, relative or not executable | `INTERPRETER_NOT_FOUND` |
| Output directory already exists | `OUTPUT_EXISTS` |
| Native failure, timeout, cancellation | `NATIVE_EXECUTION_FAILED`, `RUNNER_TIMED_OUT`, `RUNNER_CANCELLED` |
| Different PCM on re-synthesis, a changed script, a changed WAV, forged receipt or summary, retained JSON with duplicate keys, `NaN`/`Infinity`, a number that overflows (`1e400`) or a changed type (`true`→`1`, `175`→`175.0`) | `VERIFICATION_FAILED` |

A literal `text` longer than 1024 code points is judged while planning; a script file is read when the run starts, so
planning never reads a file. Silent output is a PCM check, not a missing-file check: eSpeak NG writes a WAV of
zeros for some inputs (observed for spaces, dots and underscores, which the profile already refuses), so a nonzero signal is
required as an independent guard. None of the letter-bearing scripts probed (Latin, Cyrillic, Greek, Arabic, Thai, Hangul,
Han, Ethiopic, runic, hieroglyphs) produced silence. The speaking time depends on the words: 93 ten-digit numbers
(1023 code points) last about 72 s at the default rate, while 512 spaced zeros (1024 code points) reach about 198 s at 120
words per minute and are refused by the output budget.

## What is published

`narration.wav` (kind `file`: the exact native PCM in a canonical 44-byte header) and `espeakng-summary.json` (kind
`text`). The summary (`schemaxis.espeakng.summary/1`) records the script bytes, SHA-256, code points and lines, the
requested voice with its listed name and file (for the default `English_(America)`, `gmw/en-US`: the **requested** voice, not a
certificate of the accent heard), rate, pitch, amplitude and input encoding, the audio geometry and duration, PCM byte
count, SHA-256, peak and nonzero-sample count, the WAV bytes and SHA-256, the normalised runtime identity
(`eSpeak NG 1.52.0`) and a fingerprint of the chosen native data files of the voice, the readback record and the
review statement. It contains no path. Both artifacts bind into other steps like any recording.

## Native mapping

The native tool is `espeak-ng` 1.52.0. Release and API facts below were rechecked on 25 October 2026: the GitHub
[releases/latest](https://github.com/espeak-ng/espeak-ng/releases/latest) endpoint returns tag `1.52.0` (release 1.52,
published 12 December 2024, not a draft or prerelease), the tag's commit is `4870adfa25b1a32b4361592f1be8a40337c58d6c`
and the source archive
(`https://codeload.github.com/espeak-ng/espeak-ng/tar.gz/refs/tags/1.52.0`) has SHA-256
`bb4338102ff3b49a81423da8a1a158b420124b055b60fa76cfb4b18677130a23`. No signature was verified. The command line is read
from the [manual source](https://github.com/espeak-ng/espeak-ng/blob/1.52.0/src/espeak-ng.1.ronn) and
[`espeak-ng.c`](https://github.com/espeak-ng/espeak-ng/blob/1.52.0/src/espeak-ng.c) at that tag; the
[user guide](https://github.com/espeak-ng/espeak-ng/blob/1.52.0/docs/guide.md) at 1.52.0 covers installation only. The
options are fixed and never authored:

| Stage | Command (the working directory is a private run directory) |
| --- | --- |
| version | `espeak-ng --version`, which must read `eSpeak NG text-to-speech: 1.52.0  Data at: DIRECTORY` |
| voices | `espeak-ng --voices=en` for the default and `en-us`, which must list `en-us` as `English_(America)`, `gmw/en-US`; `--voices=en-gb`, `--voices=fr-fr` or `--voices=es` for the others (see [Voices](#voices)) |
| narrate | `espeak-ng -vVOICE -sRATE -p50 -a100 -b1 -w native.wav -f captured.txt` with `VOICE` `en-us` for the default and for an explicit `en-us`, and the fixed voice-file identifier `gmw/en`, `roa/fr` or `roa/es` for an explicit `en-gb`, `fr-fr` or `es` (see [Voices](#voices)) |

* `-w` writes a WAV file and so selects the file-output (synchronous) path with no audio device or playback. The
  adaptor never passes `-d`, `--stdout`, `--stdin`, `-m` (SSML), `-x`, `-X`, `--ipa`, `--punct`, `-k`, `-g` or `-l`.
* `-b1` is the documented UTF-8 input encoding (`1=UTF8`; the API value is `espeakCHARS_UTF8` in `speak_lib.h`). Without
  it the library guesses between UTF-8 and an 8-bit set.
* `-f` reads the whole captured file. The default synthesis flags of `espeak-ng.c` include phoneme input, so `[[ ]]` would
  be interpreted as phoneme codes; the plain-text profile therefore refuses them. SSML is only interpreted with `-m`,
  which is never passed, but markup is refused anyway so that nobody believes it is honoured.
* If the selected voice file is missing, eSpeak NG silently falls back to another voice (an unknown `-v` name exits 0 and
  speaks with something else; observed with 1.52.0). The fixed `--voices` query is why the exact listing is checked, and why
  the summary records it.
* The speed-up path that needs the optional Sonic library engages only above 350 words per minute (`setlengths.c`), well
  beyond the 240 maximum, so a build without Sonic is not a different synthesizer at the supported rates. This was
  checked by reading the source, not by comparing builds.
* The launcher gives the process a minimal environment (`LANG`, `LC_ALL`; no `HOME` or `ESPEAK_DATA_PATH`), so the data
  directory is the one compiled into the binary. The adaptor never passes `--path`: `--version` ignores `--path` and would
  announce a different directory from the one synthesis reads, whereas `ESPEAK_DATA_PATH` and `HOME` are honoured by both.
* Output is PCM16 mono at the library's 22050 Hz sample rate in a 44-byte header; the host requires exactly that.

The data fingerprint is the SHA-256 of the hashes of the chosen files of the selected voice in the data directory the
runtime announces: for `en-us`, `phontab`, `phonindex`, `phondata`, `intonations`, `en_dict` and `lang/gmw/en-US` (unchanged
from before the voice option, so older fingerprints stay valid); for the other voices the same four tables, the voice's own
dictionary, `en_dict` and the voice file (see [Voices](#voices)). It covers those chosen files, not the entire set of files
the synthesis may read (the voice lookup and `--voices` also scan the data tree, and text may switch to another language
by native rules); the PCM comparison, not the fingerprint, decides whether the sound is accepted. The directory path itself stays in private evidence
(`version.stdout`) and is never published.

## Voices

`voice` is optional and closed: `en-us`, `en-gb`, `fr-fr` or `es`. Nothing else is accepted: no other voice name, voice file
path, variant (such as `en-gb-x-rp`, `fr-be` or `es-419`), `+` variant suffix, MBROLA voice, phoneme table, language
detection or translation. The need for more than the default English voice is a product judgement (a French or Spanish
draft narration should not need an English voice), not demonstrated customer demand, and no claim is made that availability of
a voice means the pronunciation or language is accurate.

| `voice` | Fixed `--voices` query | Fixed narrate `-v` value | Required listing (language, name, file) | Chosen native files fingerprinted |
| --- | --- | --- | --- | --- |
| absent (legacy) | `--voices=en` | `-ven-us` | `en-us`, `English_(America)`, `gmw/en-US` | `phontab`, `phonindex`, `phondata`, `intonations`, `en_dict`, `lang/gmw/en-US` |
| `en-us` | `--voices=en` | `-ven-us` | same as the default | same as the default |
| `en-gb` | `--voices=en-gb` | `-vgmw/en` | `en-gb`, `English_(Great_Britain)`, `gmw/en` | the four tables, `en_dict`, `lang/gmw/en` |
| `fr-fr` | `--voices=fr-fr` | `-vroa/fr` | `fr-fr`, `French_(France)`, `roa/fr` | the four tables, `fr_dict`, `en_dict`, `lang/roa/fr` |
| `es` | `--voices=es` | `-vroa/es` | `es`, `Spanish_(Spain)`, `roa/es` | the four tables, `es_dict`, `en_dict`, `lang/roa/es` |

* **The new voices are selected by the file identifier, not the language name.** For `en-gb`, `fr-fr` and `es` the adaptor passes the
  fixed identifier of the voice file the exact listing names (`gmw/en`, `roa/fr`, `roa/es`). The mapping is in the host code: an authored `voice` is
  one of the four closed values, and no authored path, file identifier or flag exists (`roa/fr` as a `voice` is refused). The reason is the native lookup
  (`SetVoiceByName` and `LoadVoice` at 1.52.0): a `-v<name>` is first tried as `voices/<name>` and `lang/<name>`, then matched against voice names and the
  ends of identifiers. If that fails, the CLI calls `SetVoiceByProperties` to select by a language score that also counts the *Other Languages* column. Extra voice files in a modified
  data directory could therefore make `-vfr-fr` load a file that the adaptor neither inspected nor hashed, while the exact listing still passed. A
  fixed identifier is tried as `voices/<identifier>` and then `lang/<identifier>`, the file the adaptor reads, checks and hashes. Unlike the name, no language score,
  voice-name match or other file name can redirect it (observed natively, see the [verification note](../verification/2026-10-25-espeakng-57.md)); a `voices/<identifier>`
  file, which would be read first, is refused. The exact listing is still required exactly once as a consistency check of the runtime; its *Other Languages* column
  never chooses a profile. The legacy `en-us` keeps `-ven-us` unchanged. This relies on the trusted native program and its data: it claims no filesystem race protection, no closure over every
  native dependency, no proof that the files are the official ones, and nothing about the accent heard.

* **Absent voice is the original behaviour.** The plan, launchers, captured-text record, summary (including its review
  text), result, receipt and native-data fingerprint of a document without `voice` are byte for byte what they were before
  the option existed, so earlier narrations still verify. This includes the retained plan wording that says only one
  fixed voice exists: that sentence describes the default narration and is kept so that the record stays identical.
* **An explicit `en-us` is not silently dropped.** It is recorded as the author's choice and uses the same native stages and
  fingerprint as the default; only the plan wording, the review text, the captured-text record, the receipt and the result
  additionally carry the `voice` claim. The `voice` claim is added only for an explicit selection, and verification requires
  it to equal the authored choice, so a record cannot be switched between voices by editing one file.
* **The exact listing is required, exactly once.** Only the language column of `--voices=LANGUAGE` selects a row; the *Other
  Languages* column and variants never do. A voice that is not listed, is listed with a different name or file, or is listed
  more than once (identical or conflicting rows: it is then ambiguous which voice file is read) is `UNSUPPORTED_RUNTIME` even
  though eSpeak NG itself would run and speak with a fallback voice. The real 1.52.0 listings have one row per voice. This also
  applies to `en-us` and to a document without `voice`: earlier code accepted an identical repeated `en-us` row, which no real
  1.52.0 listing contains and no recorded narration depends on.
* **Dictionaries, and the voice file check.** A voice takes its dictionary from the first `language` line of its voice file
  (`voices.c` at 1.52.0), so French has `fr_dict` and Spanish `es_dict` as the primary dictionary, each with the English dictionary as an additional fallback.
  The English dictionary is also consulted by the non-English voices for characters and words that name English (`numbers.c`
  and `readclause.c`), so it is fingerprinted with them. The files are fixed names inside the data directory the trusted
  runtime announces; no authored path is involved. For `en-gb`, `fr-fr` and `es` the adaptor also reads the selected voice
  file once (a regular file, not a symlink, within the 4 MiB native-data limit), checks it, and hashes those same bytes:
  the first `language` line must be exactly the listed language (`en-gb`, `fr-fr`, `es`), so the dictionary stem is `en`,
  `fr` or `es`, and a `dictionary` line may only repeat that stem. Otherwise the run or verification stops with
  `UNSUPPORTED_RUNTIME` before the voices or synthesis stage. A `voices/` entry of the same name, which `LoadVoice` would read
  instead of `lang/`, is refused. The check follows what `LoadVoice` and `fgets_strip` do with those two attributes (a line
  starting with `#` is blank, `//` ends a line, the attribute name is case-sensitive and ends at the first whitespace so an
  indented line is ignored, only the first `language` line counts, further `language` lines such as `language en 2` are
  secondary) and refuses what it cannot decide: a missing or argument-less `language` or `dictionary`, a malformed code, a name
  of 40 bytes or more or a line of 160 bytes or more (a conservative adaptor policy cap below the 190-byte minimum native line buffer, not the native limit), a NUL byte or bytes that are not UTF-8.
  **Limits:** it inspects only those two attributes. It is not a parser of the other voice options (`phonemes`, `replace`,
  `dictrules` and so on), not a check of every native data file, and it does not claim the files are the official ones; the
  fingerprint and the PCM comparison remain the evidence. The legacy `en-us` voice (and a document without `voice`) keeps its
  original six-file fingerprint: `lang/gmw/en-US` is hashed, as before, and is not parsed.
* **The script is not checked for its language.** Write the script in the language of the voice. A voice reads whatever it is
  given by its own rules: an English script read with `fr-fr` is spoken with French rules, and nothing is translated or
  corrected. The same plain-text profile applies (UTF-8, accented letters and `¿`, `¡` and similar punctuation are accepted).
* **The label is the requested voice.** The summary records the requested voice and the name and file the runtime listed for
  it. It does not certify the accent or pronunciation heard, the language of the script, any translation or an original speaker.
* **Verification is per voice.** The fresh re-synthesis uses the same voice, in the trusted `espeak-ng`, so a changed voice
  (a different `voice` in a forged plan, summary or launcher with every hash refreshed) yields different PCM and fails.

## Verification contract

There is **no host speech synthesizer** in Schemaxis, and the adaptor does not claim host-independent verification of the
sound. `schemaxis verify` **needs the trusted `espeak-ng`** (explicit argument, stored configuration or
`SCHEMAXIS_ESPEAKNG`; never the receipt or `PATH`). Without it the answer is `INTERPRETER_NOT_FOUND`, never success. It then:

1. reads every retained JSON file strictly (no duplicate keys, `NaN`/`Infinity`, numbers that overflow to infinity or
   excess depth) and compares the plan, capture record, summary, native input bindings and the result's claims, as a
   closed set, in typed canonical form, so `true` is not `1` and `175` is not `175.0`; it refuses unreferenced files in
   the publication directory;
2. rereads the captured script, requires it to match the capture record (and, for a literal, the authored text) and
   applies the plain-text profile again;
3. copies the captured bytes to a **private temporary directory outside the submitted run** and runs the same three
   fixed stages, with the same selected voice, with the trusted `espeak-ng`, in fresh bounded processes under the run's remaining deadline and
   cancellation;
4. compares **every PCM byte** and the sample count, rate and channels of that fresh synthesis with the published WAV
   and the run's own native output, and rebuilds the canonical 44-byte-header WAV itself with `struct`, cross-checked
   against the standard `wave` module, which must be byte-identical to `narration.wav`;
5. requires the runtime identity and native-data fingerprint of the verifying `espeak-ng` to equal those recorded;
6. checks the receipt's membership and digests, retained evidence digests, each native launcher, input binding, exit
   record and silent log. Receipt executables are inert provenance and are never launched.

The decision comes from the captured bytes and a fresh synthesis, not from stored digests, so a writer who replaces the
WAV with different sound, or who changes the rate or words in the plan, is caught even when every receipt hash is refreshed.

Limits of that claim:

* It proves that this WAV is the synthesizer's output for the captured text at the declared rate. It is not an
  authenticity certificate for the text. The captured text is retained in the same writable publication directory, so a
  writer who consistently rewrites the capture, the plan, the audio and every derived record and digest is not detected: the
  captured text is an unauthenticated trust anchor.
* Re-synthesis determinism was observed only for bounded cases (see the
  [verification note](../verification/2026-10-25-espeakng.md)). A different `espeak-ng` build, version or native voice
  data can legitimately produce different samples, so an older proof may fail with the matching-runtime hint instead of
  succeeding. Verify with the matching runtime and data, or run again to record a new narration; the PCM comparison is
  never weakened to tolerate a difference.

## Workflows

`narrate` followed by SoX `conform` (see the [speech workflow](../examples/schemaxis/espeakng-speech-workflow.json)) turns
the 22050 Hz narration into PCM16 mono 16 kHz for transcription or assembly; the WAV is always within the SoX conform
limits. [FLAC](flac.md) `encodeLossless` can archive the narration (see the
[archive workflow](../examples/schemaxis/espeakng-archive-workflow.json)). `source` accepts a verified `file` or `text`
artifact, so a [whisper.cpp](whispercpp.md) `transcript.txt` can be narrated (see the
[transcript workflow](../examples/schemaxis/espeakng-transcript-workflow.json)); the transcript must still satisfy the
plain-text profile. Text that a tool wrote with other control characters (for example the page text that `mutool` prints
for a PDF ends in a form feed) is refused with the offending code point; clean it with a tool you control and capture the result.

## Limits and not claimed

Other eSpeak NG releases, voices other than the four listed, regional or variant voices, other languages and accents, SSML, phoneme input, MBROLA voices, playback, streaming,
non-local sources, language detection and translation are out of scope. Source-archive signatures are not verified. The
tested runtime is a private build with PCAudio, asynchronous mode, MBROLA and Sonic disabled; a distribution build that
enables them is not claimed to be identical. The narration is not certified for intelligibility, pronunciation, accent,
accessibility or any use that needs a human voice. No MPI, network or batch use is supported.
