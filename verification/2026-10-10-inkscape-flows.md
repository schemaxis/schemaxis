# Inkscape dependency intent and concurrent native qualification — 2026-10-10

`flowDiagram` adds domain intent to the existing explicit `blockDiagram` route:
named labelled steps and directed dependencies determine an editable diagram.
No manual x/y coordinates are present in the authored flow examples. A bounded
longest-path DAG policy assigns horizontal ranks, sorts lexical IDs into vertical
lanes and centres uniform cards under explicit mm page/card/gap budgets.

The baseline branches one input into Model/Simulate and merges their outputs:
four cards, four links, ranks `[1,2,1]`, 109.2 x 36.8 mm required content on a
150 x 90 mm page, native 567 x 340 RGBA8 PNG at 96 dpi. A graph variant adds a
Validate rank before Result: five cards/five links, ranks `[1,2,1,1]`, content
150.6 x 36.8 mm on a 180 x 100 mm page, native 680 x 378 pixels. Literal
expectations check rank assignments, lane/card/link counts, required spans and
page pixels. Native stroked card/connector/arrow bounds and actual glyph padding
are independently checked against reconstructed geometry. Input array order does
not affect layout; lexical renaming intentionally changes lanes. Rendered pages
were visually inspected as an additional bounded check.

Cycle, undersized-page and acyclic-but-obstructed-route examples fail before
native launch with `FLOW_CYCLE`, `FLOW_PAGE_OVERFLOW` and
`FLOW_ROUTING_COLLISION`. Duplicate dependencies and unknown endpoints also fail.
An 80-character plain label passes geometric planning but fails native
`LABEL_OVERFLOW`; shortening it yields a verified result. Changing derived card
width in the SVG and refreshing its publication hash still fails semantic replay,
then restoration verifies. Shared expressions/references and 26/28 mm finite
card-width analytics execute two native states with independently checked required
content widths 109.2/115.2 mm. Invalid later analytic page budgets block all native
states before launch. An explicit 1e-10 mm host arithmetic epsilon absorbs only
binary-float roundoff at exact budgets; native geometry tolerance stays 0.015 mm.

A root concurrent integration exposed a native 1.4.4 startup fault:
`Gio::DBus::Error` during its constructor's default-application registration.
The [official 1.4.4 application source](https://gitlab.com/inkscape/inkscape/-/blob/INKSCAPE_1_4_4/src/inkscape-application.cpp)
shows this probe precedes CLI processing. Each trusted native visit now supplies
an adaptor-derived unique `INKSCAPE_APP_ID_TAG` before construction, its matching
public `--app-id-tag` and a private `INKSCAPE_PROFILE_DIR`. Exact stage commands
and tags are independently rechecked. No authored field controls these values;
parallel workflow scheduling remains enabled and user desktop preferences stay
outside visit profiles. Twelve distinct native runs, mixed explicit/flow diagrams,
passed across three rounds of four concurrent jobs under the existing desktop.

Fresh native 1.4.4 recipe evidence is retained in
`evidence/2026-10-10-inkscape-flow-native-2`; the successful four-case kit receipt
is registered in the adaptor's qualification bundle. Seventeen focused host tests,
host conformance, readiness admission and conceptual coverage pass. The guidance
contains 86 reference records, zero pending and zero stale addresses; it is not
claimed human-reviewed. All standard publication/authored/plan integrity, timeout
and pre-launch cancellation probes remain passing.

Artefact ordering stays SVG text, PNG image, measured JSON text. Flow measurements
include the replayed policy/ranks/budgets. Existing explicit geometry and the
400 x 200 image handoff contract are retained. This is a bounded diagram policy,
not general graph drawing, arbitrary acyclic routing, graph-layout optimisation,
font-size optimisation, whole-image certification, imported SVG support or live
native editing. Long edges can require an explicit collision rejection; link/link
crossings remain allowed and are not assessed.

A later independent review found that the public capability-query hook treated
the finite-study plan envelope as a literal diagram plan. The hook now collects
the unique operations from all planned visits. A public `registry.query`
regression checks a two-state card-width study and confirms that an invalid later
page budget still fails before native execution. All seventeen focused host tests
pass. Fresh source-current evidence in
`evidence/2026-10-10-inkscape-query-native-1` reruns all four native acceptance
cases, their publication/authored/plan integrity probes, timeout and pre-launch
cancellation. The prior flow-label recovery, refreshed-hash semantic tamper,
two-state native analytics and twelve-job concurrency results above remain
historical coverage of unchanged native execution and verification code; those
extended checks were not repeated for this host-only query correction.
