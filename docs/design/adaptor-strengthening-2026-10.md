# Adaptor strengthening: October 2026

This work follows the [candidate catalogue](adaptor-candidates.md) and the
[domain-model framework](../feedback-studies.md). Strength applies to a named,
bounded workflow; it is not a percentage of a native application's API exposed.

## Acceptance bar

An addition must make the user's intent explicit, report what the native
application actually achieved, and explain whether the result meets the declared
requirements. Shared expressions and analytic iteration remain available through
the common runtime. Application-specific controls, observations and decisions
belong in the owning adaptor.

Each milestone requires:

1. Host-safe discovery, a closed authored schema and deterministic planning with
   useful, located faults. No arbitrary native commands or authored scripts.
2. An editable starting document and a meaningful rejected document, conceptual
   guidance, capability metadata and complete delivery materials.
3. Distinct baseline and variant acceptance cases with independent expectations.
   Native results must be read back; process completion alone is insufficient.
4. Verification of authored intent, effective plan, publication membership,
   semantic content and retained evidence. Altered files and plausible but
   incorrect observations must fail even when ordinary hashes are refreshed.
5. Bounded execution, cancellation, retained failure evidence and a clear
   distinction between invalid input, unavailable runtime, execution failure and
   an unmet deliverable requirement.
6. Explicit interchange limits and workflow reuse checks where handoffs are
   supported. Native qualification states exactly which runtime and cases ran.

The work proceeds on `main` in independently reviewable commits. Bulk runs and
downloaded runtimes remain in ignored `evidence/`; compact results belong in
`verification/`. Historical receipts are not presented as newly run checks.

## Selected slices

These are implementation scopes, not claims of completed qualification. The
owning adaptor guide and verification record establish delivered behaviour.

| Provider | Domain intent | Required observation and decision |
| --- | --- | --- |
| FFmpeg | Publish a media deliverable with explicit dimensions, timing, size and reconstruction-error requirements. | Inspect the native stream and fully decode it; compare against captured source frames and assess every authored requirement. |
| Inkscape | Produce an editable technical diagram from explicit geometry or named dependencies within a declared page and layout budget. | Derive deterministic DAG ranks and lanes; check box/connector geometry, native text extents and exported raster evidence; explain routing, page and text-fit failures. |
| Shotcut | Assemble named video sources into an ordered timeline using explicit frame ranges. | Inspect sources, reconstruct the expected frame sequence, reopen/render the MLT project and compare decoded output; preserve a portable project/media bundle with explicit editing limits. |
| ngspice | Accept a circuit response only when named voltage or gain requirements hold at the declared samples. | Independently validate native circuit values, report the worst sampled condition and margin for each bound, and block downstream publication for unmet requirements. |
| Adobe Premiere Pro | Inspect an existing sequence against declared timing, profile and clip-placement requirements through a bounded read-only UXP companion. | Bind observations to a fresh request and re-evaluate requirements; require a real Premiere installation before claiming native qualification. Host tests and plugin doubles cannot establish that result. |
| CalculiX | Evaluate a slender, rectangular, linear-elastic cantilever against declared deflection and sampled interior normal-stress limits. | Check native displacement against beam theory, axial and transverse mesh refinement separately, reaction force and moment equilibrium, and interior Gauss-point stress. Re-execute the retained fine-mesh deck before accepting its evidence. |
| R | Fit a bounded additive numeric linear model and assess declared training or held-out observations. | Compare coefficients and predictions with an independent column-scaled QR solve, reject rank/conditioning failures, reopen the retained R model in a fresh process, and measure named error or prediction requirements. |
| Calc | Accept a numeric workbook only when named cell bounds and reconciliations hold. | Independently check recalculated data, summaries and formulas in both XLSX and reopened ODS; evaluate requirements from those native values and retain actionable unmet assessments. |

Premiere Pro was the editor discussed in the preceding product conversation.
Shotcut is an additional open-source implementation target for native testing on
Linux, not a substitute claim about Premiere support. Premiere's UXP API is
versioned separately from document contracts; native action and transaction
semantics must be checked against the selected release.

The Premiere integration is experimental while that native environment is absent.
It does not count as a natively qualified editor. Project creation, clip edits,
export and image/audio fidelity need separate implementation and acceptance.

## Integration exercise

The [integration case](../diagram-video.md) publishes two diagram PNGs from
Inkscape, encodes them with FFmpeg, and cuts/reorders the resulting video in Shotcut.
It retains verified producer/consumer lineage, exercises resume, rejects changed
producer evidence and requires a failed media requirement to block the downstream
edit. This is a technical-visualisation workflow, not a claim of
creative editorial quality, audio support or professional colour management.

The second tranche connects a regression's observed/predicted/residual table to
Calc. The producer must meet its declared fit limits before a workbook can run;
the workbook then applies its own cell checks. A failed producer and a failed
consumer are distinct decisions. Units survive as declared labels in the
regression summary; a plain numeric CSV does not carry unit semantics, and a
workbook reconciliation must state compatible units through its authored intent.

## Follow-on selection

Prefer additions that make a useful decision visible. The candidate catalogue
remains the source for new applications. Further candidate slices include bounded
KiCad board inspection with declared manufacturing requirements. Existing
providers can extend their measured decisions through the common analytic
iteration model, with independent acceptance for each extension. A finite sampled
check must never be described as a proof over all frequencies or component tolerances.

The beam slice does not establish general finite-element model validity or root
stress/yield certification. Finite held-out regression rows do not establish
statistical inference, causality or future predictive accuracy. Native numerical
agreement and a satisfied user requirement answer different questions, and both
must remain visible in discovery, reports and verification.

Broader native API coverage, extra providers and more elaborate feedback policies
follow completed verification rather than replacing it. Runtime availability and
domain evidence govern the qualification boundary.
