# ImageJ measureRegions repair review

Date: 2026-10-26 (local, America/Winnipeg). Scope: repairs to the `measureRegions`
operation of the `schemaxis.imagej/1` route after an independent review of the
[2026-10-25](2026-10-25-imagej-regions.md) note, which is kept unchanged as history. The
motivating workflow is a product hypothesis, not demonstrated customer demand.
`analyzeParticles` and its 2026-10-16 qualification records (OpenJDK 21) are historical
and are not relabelled.

## Runtime

- ImageJ 1.54t (`ij.jar`, official stable release; a local SHA-256 is recorded and no
  independent publisher checksum was located, so none is claimed).
- OpenJDK 25.0.4.1 for the `measureRegions` native runs of 2026-10-26; Linux x86-64,
  serial, headless, private `user.home`/`tmp`/`plugins`.
- Calc handoff: LibreOffice 26.8.1.1; ODF and OOXML cells read independently.
- `absorbedVersion` stays 1.54t. No qualification record is registered by this note.

## What the repair checks

| Area | Check |
| --- | --- |
| Timeout and cancellation | `regions.run` itself, host (stubbed runner) and native: its own total deadline before launch, before the measure stage, during the measure and reopen processes and after verification; cancellation before launch, before the measure stage, while the measure and reopen processes are live and before publication. Each needs the precise `RUNNER_TIMED_OUT` or `RUNNER_CANCELLED`, a retained failed `result.json`, no publication, and (native) the owned process ID gone. This does not rely on the particle kit lifecycle. |
| Tamper probes | Each probe asserts the exact message and location, not only the code. Probes are separated into refreshed-semantic (every ordinary digest and binding recomputed, so only the semantic check can object, including publication and evidence membership), digest-only (receipt digest of an ordinary log) and contract controls (readback field contract, incomplete result). Native stdout/stderr logs are digest-only: a refreshed receipt hides an edit to them, and no result is read from them. |
| Fault locations | Most config, table, summary, receipt and stage-readback faults name the retained file or field (for example `reopen-readback.txt/region.1`). Some runtime-identity faults use `$`, and retained frame-decode faults may use an authored frame location. |
| Fractional means | New 9x6 8-bit and 16-bit planes (formula in the fixtures README) with odd-sum 3-pixel rectangles (means 368/3 and 111185/3), compared as exact Fractions with ImageJ's double mean within 1e-12 relative. Original integer-mean ramps are unchanged. |
| Non-unit area | Calc handoff at 0.5 x 1.5 um (0.75 um^2 per pixel): every workbook area cell is checked as count x 0.75 and differs from the count; a changed pixel at the same source path invalidates and propagates. Changed authored calibration and time are exercised in a fresh workflow. |
| Duplicate sources | Aliases (`./`, `..`) and hard links of one file are refused by file identity before capture; distinct files with identical pixels are accepted. |
| Budgets | The byte total is decided from `fstat` before any frame is read; pixel and visit totals from bounded headers before any frame is decoded. |
| Recorded fields | `jarSha256` is cross-checked against the digest of the jar the native process loaded, as consistency between retained observations rather than publisher authentication or protection against rewriting all those records together. The stored-file calibration is checked against ImageJ's default only for files without resolution or description tags, and otherwise for agreement between stages (an ImageJ observation, not an independent decode). |
| Fixtures | The primary qualifier runs the series fixture generator `--check` and refuses stale fixtures. |

## Limits

- Synthetic analytic and formula planes only; no experimental data and no claim of
  suitability for any specific study.
- No review overlay and no editable ImageJ ROI set are produced or claimed; no sum or
  centroid is published.
- Typed Calc handoff only; R and Pandoc handoffs for regions were not run and are not claimed.
- The Calc typed reader is a provisional dependency whose own review is separate.
- One ImageJ release and one Java version for regions; sources are not re-qualified for others.
- Native results are retained privately and re-reviewed independently; this note states
  the checks and limits and records no result of its own.
