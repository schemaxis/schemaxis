# whisper.cpp offline transcription completion review

Route: `schemaxis.whispercpp/1`, initial `transcribe` document. Scope is a local
PCM16 mono 16000 Hz WAV (at most 600 s and 32 MiB), a local ggml model pinned by
SHA-256 (at most 4 GiB), one serial CPU native thread and whisper.cpp default
decoding. Outputs are `segments.json` (closed integral-millisecond contract),
`transcript.txt`, `captions.srt` and `captions.vtt`. No model download, remote
service, prompt, translation, diarisation, VAD, language detection, word timing or
authored native flag exists. Host discovery and planning use the Python 3.10+
standard library only; the native tool runs in tracked isolated processes.

**Recognition accuracy is not certified.** Structure, hashes and byte agreement
prove consistent derivation from a recorded native run, not correct words. Every
published result carries `accuracyCertified: false` and `humanReviewRequired: true`.

## Checklist review

| Item | Result and retained evidence |
| --- | --- |
| registration | Manifest declares the document route, runtime family 1.9.5, `whisper-cli` executable, `--whispercpp` option, workflow/composition and audio/model byte reuse hooks. Unsupported optional features have explicit scope decisions. The shared registry was not edited. |
| schema | Typed nested `audio`, `model`, `language` declarations, literal schema and common authored schema agree on two valid examples and two schema-valid semantic rejections. Hex pins, absolute paths, suffixes and language form are semantic checks because the declaration grammar has no patterns. |
| semantics | Absolute parent-free local `.wav`/`.bin` paths, lowercase SHA-256, language form, distinct audio/model, canonical PCM16 mono 16 kHz, 600 s/32 MiB audio bound, 4 GiB model bound, segment/character budgets and the timing policy are enforced before publication. Exact faults/locations have host tests. |
| native-mapping | Official v1.9.5 `examples/cli` options `-m`, `-f`, `-l`, `-t 1`, `-p 1`, `-ng`, `-oj`, `-osrt`, `-of` map through trusted argument arrays. The JSON member set was read from the public CLI source and is enforced as a closed contract. The model is passed as the already-hashed descriptor `/proc/self/fd/N`, so loaded bytes equal hashed bytes. Linux-specific. |
| execution | One deadline covers capture, model hashing, version, loader dependency trace, transcription and verification; CPU/address-space/file limits and shared cancellation bound native processes. Captures, plans, launchers, input bindings, model and runtime identity (executable plus every resolved dynamic dependency, hashed before and after), submissions, logs, native JSON/SRT and publications are retained. Verification reopens retained evidence without the original audio or model. |
| discovery | Six reviewed cases (speech transcription, captions, SRT subtitles, Whisper, audio to text, negative OCR) pass the capability search check. Phrases describe bounded offline transcription, not general audio editing. |
| guidance | All 11 records reviewed: operation plus every root/nested field; text covers pins, formats, defaults, language/model coupling and the accuracy limitation. |
| help | Local `docs/whispercpp.md` covers scope, version honesty, fields, segment/timing policy, evidence, accuracy, fault recovery and public sources. Root owns regenerated references and packaged contextual Help. |
| examples | Baseline public sample, held-out eight second excerpt, relative-path and uppercase-hash semantic rejections, and a Studio starter. Examples use a fixed generic staging directory that the qualifier creates, because the sample audio and model must not be committed. |
| tests | 18 host tests (`tests/unit/test_whispercpp.py`): common conformance/discovery/guidance, defaults, exact faults, hostile WAV/JSON/timing/text cases, deterministic captions, trusted launcher, a deterministic native test double through the real runner/verifier, 17 rehashed/receipt forgeries, model/executable change during a run, version strings, cancellation, deadline and in-flight timeout. The test double is never counted as native acceptance. |
| qualification | Separate native run below; the framework receipt is not registered by this assignment and will be stale after root generation. |
| maintenance | Latest stable is v1.9.5 (commit d1be6fd, tagged 2026-10-06); `upstream.json` records absorbed version 1.9.5 and the acceptance recipe. Installed v1.9.4 was not modified and is refused with `UNSUPPORTED_NATIVE_VERSION`. |

Optional native inspection, MPI, time batches, live editing, native project save
and conversion are unsupported. The route has no graph/node ports.

## Native identity

An isolated official v1.9.5 CPU build (`GGML_CUDA=OFF`, `GGML_NATIVE=ON`, Release)
was made from a shallow clone at tag `v1.9.5`; `git rev-parse HEAD` was
`d1be6fde11ac6e0407606b4e42fe72d34add8037` (`whisper : bump version to 1.9.5`), exactly
the release commit, with a clean tree. The CLI reports `whisper.cpp version:
1.9.5-dev` because the upstream CMake option `WHISPER_BUILD_IS_DEV` defaults to ON;
the earlier installed build reports `1.9.4-dev` in the same way. The adaptor accepts
`1.9.5` and `1.9.5-dev` exactly and records the observed string. A version string
alone cannot prove the commit; the qualifier recorded the commit separately.
Executable SHA-256: `a5f51cb9fc47d3a782e80369868ecd379cdea8c69be761c337c69f7824714217`.
Fixtures: public `jfk.wav` (SHA-256 `59dfb9a4…ba7860e`, 176000 frames, 11 s) from the
whisper.cpp repository, its first 128000 frames (`43e6a960…c47f591`), and
`ggml-base.en.bin` (`a03779c8…6c6d002`, 147964211 bytes). None is committed.

## Native result and narrow accuracy scope

Fresh bounded run (`tools/qualify_whispercpp.py`, 28.7 s): the two common native
cases passed with runtime `whisper.cpp 1.9.5-dev`, plus common timeout and
pre-launch cancellation checks.

- Full sample: one segment, 0–11000 ms, text `And so my fellow Americans, ask not
  what your country can do for you, ask what you can do for your country.` The
  qualifier's own reader checks audio duration, normalised words against the public
  quotation, SRT block timing/text against segments, WebVTT header and transcript
  lines, independently of the adaptor's parsers.
- Held-out excerpt (first 8 s): one segment, 0–8000 ms, `And so, my fellow
  Americans, ask not what your country can do for you.` The comma differs from the
  quotation; the literal registered text is the observed model output and the
  qualifier separately checks word identity.
- 17 rehashed or receipt-level forgeries on a real run were rejected: caption,
  WebVTT timing, transcript, segment and review-warning edits, native JSON timing/text,
  native SRT disagreement, captured audio, model identity, runtime version, launcher,
  missing/extra evidence, publication membership, runtime identity and a stray file.
- Pre-native refusals: audio/model pin mismatch (no native launcher created), absent
  model, relative audio, bad language form, 8000 Hz audio. Non-model bytes with a
  matching pin fail with a structured runner fault and publish nothing.
- Workflow: unchanged inputs reuse; a one-bit same-path audio change does not.
  In-flight timeout and cancellation terminate the owned child process.

Accuracy limits observed in the same session: a 6 s cut of the same recording
transcribed as `ask not what you are coming to do` (a wrong sentence), and 4 s of
digital silence produced the verified, structurally valid text `You`. These are
retained as reasons for the review warning. No accuracy claim exists beyond the two
named fixtures with this model and runtime, and no claim for GPU backends, other
models, languages, long or noisy audio or other operating systems.

## Limits and handoff

- Not run: handoff from the SoX or FFmpeg adaptors (no configured executable was
  supplied to the qualifier); `--source-directory` identity needs a release checkout.
- The common framework receipt requires fixtures to be named in committed cases.
  The examples therefore reference a generic `/tmp` staging directory, and the
  receipt's document digests depend on those literal paths and pins. This works but
  is unusual; the root may prefer a shared optional-fixture mechanism.
- The model is not copied and is hashed three times per run (about 0.15 s for
  base.en). In-place modification while the model is read is detected afterward,
  not prevented.
- Verification checks retained runtime hashes and does not re-hash the installation.
- Root owns shared generated references, packaged Help, final search regression and
  receipt registration after generation: run `tools/qualify_whispercpp.py ... --register`.

## Commands run

```sh
PYTHONPATH=src python3 -m unittest tests.unit.test_whispercpp
PYTHONPATH=src python3 tools/studio_guidance.py --app whispercpp --check
PYTHONPATH=src python3 -m schemaxis readiness --app whispercpp --admission --check
PYTHONPATH=src python3 tools/qualify_whispercpp.py --whisper-cli /absolute/path/to/whisper-cli \
  --model /absolute/path/to/ggml-base.en.bin --sample /absolute/path/to/samples/jfk.wav \
  --source-directory /absolute/path/to/whisper.cpp-v1.9.5 --output-directory evidence/whispercpp-native
```

## Master closeout

Native cue ends must now stay within ceil(audio duration in milliseconds), with
no additional 100 ms slack. Angle-bracket cue text is refused rather than publishing
SRT markup as literal speech. Exact declared framework sidecars and regular files
are checked; arbitrary metadata filenames are refused. Retained JSON is strict,
and the complete typed result including accuracy/review flags is recomputed and
compared. Model/runtime numeric identities are bounded. Added regressions cover
these trust boundaries; fresh final native qualification follows shared generation.
