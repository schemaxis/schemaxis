# Pandoc earlier-report verification repair — 25 October 2026

Scope: maintenance of the existing `schemaxis.pandoc/1` report route, not a new adaptor or allocation. `schemaxis verify` again
accepts a genuine report written by the earlier code, whose one-cue machine-draft provenance paragraph said "1 cues". No plan,
field, native mapping, option or authored input changes, and new reports are written exactly as before. Earlier reviews:
[transcript block](2026-10-25-pandoc-33.md), [time format](2026-10-25-pandoc-47.md).

## Fault and cause

Before the change, a read-only `verify` of a genuine allocation-33 report (one cue, machine draft, no `timeFormat`, no cue-length
target) failed with `VERIFICATION_FAILED` "trusted AST differs from authored report"; its tree was unchanged. The retained
`report-input.json` has "Language en; 1 cues; …" while the development baseline since the committed grammar fix (and the current
code) writes "1 cue". Nothing else differs: the same report's captured source, plan wording, HTML, DOCX and readback are earlier-code
output. A second genuine report (three cues, cue-length target) already verified. Source counts: one of two genuine allocation-33
reports failed; this does not claim to cover every historic report.

A separate genuine allocation-38 report with a corrected (reviewed/1) transcript also fails, because its paragraph has the older
`Review note: …` wording rather than `Review note (author's words): "…"`. That is a different earlier wording, outside this repair, and is
not bypassed.

## Decision

`verify` replays the cue-count grammar the report was written with, and only that:

- The earlier "N cues" text is recognised only for a transcript that is a one-cue machine draft, has no `timeFormat` and no cue-length
  target, in a report whose stored plan carries the earlier transcript loss wording, and only when the stored AST is exactly the
  earlier-grammar AST. HTML, DOCX, readback and the report summary are then checked against that same model, so a mixed or partial
  claim fails there.
- A report with two one-cue drafts must use the earlier grammar for both. A one-cue draft beside a multi-cue draft changes only the
  one-cue paragraph.
- Reviewed/1, reviewed/2, timecode, explicit milliseconds, segmented and multi-cue transcripts, and every current report, compare
  exactly as before. Recognition is at verification only: planning, the run, the plan, captures and published text are unchanged, and
  there is no input flag. Original plans, hashes and artifact bytes are never rewritten.
- A coherently rewritten exact earlier-grammar report is accepted as equivalent semantic content (the captures are not
  authenticated against the original recording, as before). Changed words, status, times, counts, digests, provenance fields or partial
  HTML/DOCX/model variants are refused even when every ordinary receipt hash is recomputed.

Changed code: `adaptor.py` (`legacy_cue_grammar`, `transcript_content(legacy_plural)`, `earlier_cue_prepared`, the `verify` wiring) and one
limit paragraph in `docs/pandoc.md`. `inspection.py` is unchanged.

## Evidence (run 25 October 2026; earlier receipts are not reused)

- Read-only before/after probe of the genuine one-cue report: failed before, verifies after; 71 files, bytes and modification times unchanged
  (tree digest prefix `08ca25e71e6126f4` identical before and after). The three-cue genuine report and the accepted publishing-chain,
  corrections and workflow reports still verify unchanged.
- `tests/unit/test_pandoc_legacy_transcript.py` (11 tests; the genuine case reads the report named by
  `SCHEMAXIS_GENUINE_PANDOC_REPORT` and is skipped otherwise): 3 failures and 4 errors against the baseline adaptor, all pass after. Together with the
  other Pandoc host suites, 151 tests pass. The absent-`timeFormat` fingerprints equal the pinned earlier values.
- `tools/qualify_pandoc_legacy_transcript.py` with the official Pandoc 3.12.1 binary (bounded below 180 s; completed in about three seconds):
  the current writer publishes "1 cue" in HTML, DOCX and readback (also with `timecode`); an earlier-grammar control written by the real
  Pandoc verifies; twelve refreshed-hash forgeries of it (wrong count, status, word, digest, HTML/DOCX grammar or count, plan wording,
  claimed `timeFormat`, changed captured words) are each refused as `VERIFICATION_FAILED`. DOCX is inspected from its ZIP/XML with the
  standard library; no Word rendering is claimed.

Not run: the full host suite, generation checks, qualification registration, and Studio tests. The Pandoc qualification receipt is not refreshed.
