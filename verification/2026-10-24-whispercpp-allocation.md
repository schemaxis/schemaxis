# whisper.cpp blank-cue strictness review

Route: `schemaxis.whispercpp/1`, `transcribe`. Scope is one bounded repair to
existing native-cue text handling. No application, native option, mapping, input
format or caption-review field was added, and `absorbedVersion` is unchanged.

**Recognition accuracy is still not certified.** Every result keeps
`accuracyCertified: false` and `humanReviewRequired: true`.

## Defect and repair

Before the repair a native cue whose text had no visible character (only
zero-width space, word joiner, byte-order mark, soft hyphen, Hangul filler,
Braille blank, variation selector, a lone combining mark or a Unicode
noncharacter or private-use code point) passed the strict parser. It was
published as a blank-looking cue in `segments.json`, `transcript.txt`,
`captions.srt` and `captions.vtt`, and verification reopened and accepted it,
although the documented limit says empty cues are refused.

Now `native_segments` refuses such a cue with `TRANSCRIPT_INVALID`, located at
`$.transcription[N].text`, with the cue index and its first code points
(`U+XXXX`) in `observed` and a recovery sentence. Verification reuses the same
parser, so forged retained native evidence is refused too. Format characters
remain legal inside visible text (emoji joiner sequences, tag-flag emoji), and
non-speech annotations such as `[BLANK_AUDIO]` are visible and unchanged.
Private-use and noncharacter code points beside ordinary visible text remain legal;
independent review caught and removed an overly broad first repair. Three positive
mixed-text regressions failed before the integration repair and pass afterwards.
Unassigned code points count as visible; newly assigned marks or format characters
may be classified differently across Unicode database versions. This is a bounded
structural policy, not a rendering or recognition certification.

When reopening retained evidence fails because native evidence breaks the
contract, the `VERIFICATION_FAILED` fault now keeps the specific fault under
`observed.cause` (previously nested one level deeper as `observed.observed.cause`).

## Compatibility

Plan losses and the `segments.json` review policy text are byte-identical to
before, because retained receipts embed them. Four genuine retained runs of the
current contract (two samples, a silence probe and an unaligned-excerpt probe)
verified before and after the change. An older interim run from the same day
fails both before and after because its policy prose ends in `+ 0`; that is a
pre-existing closeout strictness, not changed here.

## Checklist

| Item | Result |
| --- | --- |
| registration, schema, native-mapping | Unchanged. No new field or native argument. |
| semantics | New refusal with exact code, location, observed code points and recovery; invisible-only and nonstandard-only cues; 15 legitimate/mixed texts. |
| execution | Blank cue in a run publishes nothing (both with and without `captionReview`) and records a failed result. Forged retained native JSON/SRT with refreshed hashes is rejected with the cause preserved. |
| discovery, guidance | Unchanged; guidance does not mention cue text rules. |
| help | `docs/whispercpp.md` states the rule, the unassigned-code-point limit and fault recovery; readiness recovery text updated. Shared generated references and packaged Help are not regenerated here. |
| examples | Unchanged; no native option changed. |
| tests | `tests/unit/test_whispercpp_allocation.py` (8 tests) fails before the repair (23 failures, 1 error) and passes after; `tests/unit/test_whispercpp.py` (33 tests) passes. The native test double is host-only. |
| qualification | Not re-registered. A fresh serial native run with the 1.9.5-dev executable passed on the public sample with `captionReview` and re-verified (one cue, 0-11000 ms, long-duration flag). That is a single serial acceptance, not full requalification. |
| maintenance | Latest stable observed on 24 October 2026 is v1.9.5 (commit d1be6fd); `absorbedVersion` stays 1.9.5. |

## Unresolved

- Cues of only punctuation or symbols remain legal and visible; whether to strip
  non-speech annotations is an editing decision left to people.
- Shared reference/Help generation and receipt registration remain with the root.
- Accuracy, other models, languages and operating systems remain unqualified.

## Commands run

```sh
PYTHONPATH=src python3 -m unittest tests.unit.test_whispercpp tests.unit.test_whispercpp_allocation
PYTHONPATH=src python3 tools/studio_guidance.py --app whispercpp --check
PYTHONPATH=src python3 -m schemaxis readiness --app whispercpp --admission --check
```
