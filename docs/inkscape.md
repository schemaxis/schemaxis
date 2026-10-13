# Measured technical diagrams with Inkscape

`schemaxis.inkscape/1` declares `blockDiagram`: a page in mm, named labelled
rectangles, and directed links. The examples provide a straight connection and a
changed output position with an orthogonal dogleg. Planning and discovery use only
standard host Python; native Inkscape runs in isolated command visits.

Choose this route for a small editable technical block diagram. Declare `width`,
`height` and `boxes`; each box has `id`, `label`, `x`, `y`, `width`, `height` and an
optional `colour` (`blue`, `green`, `amber`). `links` name `source` and `target`
boxes. Coordinates, dimensions, `margin` (default 5), `clearance` (5), `padding`
(2) and `fontSize` (3) are mm. `dpi` defaults to 96. Each rectangle has a fixed
0.4 mm stroke. Labels are escaped single-line plain text in native sans-serif.

The page must preserve the declared margin outside every stroked rectangle.
The minimum Euclidean separation between stroked boxes must reach `clearance`.
A connector leaves the source right edge, turns vertically at the horizontal
midpoint and reaches the target left edge. It must run left-to-right with at
least 3 mm clear separation for its 2 mm arrow. Segments and the filled arrow envelope must avoid unrelated
boxes; the arrow occupies the final 2 mm of the already clear approach. Link
crossings with other links are allowed and are not assessed. This is explicit
geometry, not an automatic routing solver.

Native `--query-all` measures the durable SVG in one fresh process. Its CSS-pixel
bounds at 96 dpi are converted to mm with 25.4/96, independently of PNG DPI. Its visual
rectangle, connector and arrow bounds must match analytic geometry within
0.015 mm (enough for decimal CLI reporting, small relative to the 0.4 mm stroke).
Actual text extents must stay inside the box minus its padding. The fixed text
baseline is an authoring convention; text fits only if native measurements prove
it. `INVALID_LAYOUT` identifies invalid authored geometry before launch;
`LABEL_OVERFLOW` identifies a font-dependent layout failure and records measured
bounds. Resize/reposition boxes, shorten the label or lower `fontSize`, then run
in a fresh directory. Failed measurements and logs are retained.

A separate native process exports the entire page as non-interlaced RGBA8 PNG on
opaque white. Verification decodes the PNG, checks page dimensions, and probes
white page corners and each box interior away from its border and label. These
are bounded raster checks; they do not establish whole-image visual fidelity,
legibility, aesthetic quality, colour management or the exact installed font.

The three publications have stable ordering: `diagram.svg` (text), `diagram.png`
(image, index 1), `diagram-measurements.json` (text). SVG retains editable named
rectangles, text, connector paths and arrow polygons; PNG loses that structure.
No authored SVG, CSS, scripts, arbitrary commands, imported documents, images,
filters, PDF conversion or live native editor synchronisation are supported.
The exact generated SVG is reconstructed independently during verification, so
changed geometry or inserted scripting fails even if a publication hash is
updated. Native bounds, decoded probes, measured JSON, hashes, authored input,
plan and successful result must agree. Native receipts are preserved evidence;
verification does not rerun Inkscape or certify another installed runtime.

Workflow execution is scheduled and self-contained; `reusableInputs` supplies
an empty external-source map. The scheduler can reuse a complete job after
rechecking authored identity and all outputs. Shared composition and expressions
resolve before these checks. Edit the public example using shared JSON pointer
patches; there is no adaptor-specific scripting language.

Run `tools/qualify_inkscape.py --output-directory evidence/inkscape-check
--executable /absolute/inkscape` for fresh native baseline/variant, integrity,
timeout and cancellation checks. Native layout negative cases distinguish a
long label that plans successfully from a measured overflow, and demonstrate
recovery by shortening it. The example page 120 x 60 mm at 96 dpi rounds to
454 x 227 pixels; its boxes have 34.6 mm stroked clearance. The changed vertical
position preserves that clearance but introduces a measured 15 mm vertical
connector segment. Host conformance uses literal independent expectations.

Public native API references:
[Inkscape manual](https://inkscape.org/doc/inkscape-man.html),
[command-line usage](https://wiki.inkscape.org/wiki/Using_the_Command_Line), and
[1.4.4 release notes](https://inkscape.org/doc/release_notes/1.4.4/Inkscape_1.4.4.html)
and the [official 2026-05-06 release announcement](https://lists.inkscape.org/hyperkitty/list/inkscape-docs@lists.inkscape.org/thread/OCEYDBJCKK2ZF65O3FNKZOSTL7JBTZND/).
The route targets stable 1.4.x and was newly qualified on 1.4.4. The wiki 1.4.4
notes still carry stale draft wording; the dated official release announcement
and stable PPA runtime establish the observed release. The exact bounded receipt
and limitations are linked from the adaptor upstream metadata.

## Intent-driven dependency flows

Choose `flowDiagram` when the intent is named steps and directed dependencies.
The [branch/merge example](../examples/schemaxis/inkscape-flow.json) declares
`boxes` containing only `id`, `label`, and optional `colour`, plus `links` with
`id`, `source`, and `target`. It requires no native x/y placement. Manual card
coordinates and dimensions are rejected in this operation's closed authoring
schema. The existing `blockDiagram` contract retains explicit geometry.

The deterministic `dag-longest-path/1` policy assigns each root rank 0 and each
other step one rank beyond its highest predecessor. Within a rank, lexical box
IDs choose vertical lane order, independent of input box/link array ordering.
Columns run left-to-right and the complete graph is centred horizontally on the
page; each column's lanes are centred vertically. Reordering authored arrays
preserves derived geometry; renaming IDs can change lexical lane assignment.
A DAG may contain disconnected roots, and the policy places those as separate
lanes in rank 0. Duplicate dependencies and missing endpoints are rejected.

Declare uniform `boxWidth` (default 26 mm), `boxHeight` (14 mm), `rankGap`
(15 mm between stroked card columns), and `laneGap` (8 mm between stroked cards).
Page `width`, `height`, `margin`, `clearance`, `padding`, `fontSize` and `dpi`
have the same meaning as explicit diagrams. Both gaps must reach `clearance`;
rank gaps also need 3 mm for arrows. For R ranks and L lanes in the largest rank,
the required stroked content span is
`R*(boxWidth+0.4)+(R-1)*rankGap` by
`L*(boxHeight+0.4)+(L-1)*laneGap`. Add twice the margin to obtain the minimum
page budget. A 1e-10 mm arithmetic epsilon absorbs only binary float roundoff
at exact page/clearance budgets; the separate native readback bound remains
0.015 mm. Native label bounds still independently determine actual font fit;
no automatic font shrinking hides a failed legibility or geometry requirement.

`FLOW_CYCLE` reports unresolved steps (including steps downstream of a cycle),
`FLOW_PAGE_OVERFLOW` reports required and actual page dimensions plus rank/lane
counts, and `FLOW_ROUTING_COLLISION` identifies a dependency whose deterministic
connector intersects an unrelated card. Such failures occur before native launch.
The bounded midpoint router does not solve arbitrary acyclic layouts: long edges
that skip ranks may collide. Change the graph/layout choice or use `blockDiagram`
for explicit placement. Link/link crossings are still allowed and not assessed.

The generated card geometry then passes through all existing margin, clearance,
connector and arrow validators and the same independent native text-fit and
rendered-page checks. Published measurements add the replayed `layout` record:
algorithm, ranks, lane counts, required size, card size and gaps, all in mm.
Verification derives it again from authored dependency intent and reconstructs
the SVG. Refreshing hashes after changing derived card geometry cannot establish
acceptance. Artefact ordering remains SVG, PNG, measured JSON.

The baseline has four cards in ranks `[1,2,1]`, required content 109.2 x 36.8 mm,
and a 150 x 90 mm page. A changed dependency graph adds a validation rank before
publication: five cards in ranks `[1,2,1,1]`, content 150.6 x 36.8 mm on a
180 x 100 mm page. These native acceptance cases independently check ranks,
counts, page pixels and all native geometry/text bounds. Cycle, oversized page
and obstructed-route examples deliberately fail planning. An 80-character label
plans but fails actual native `LABEL_OVERFLOW`; shorten it, lower font size, or
increase the uniform card budget, then recheck all page constraints.

Shared expressions, document references and finite analytics can vary uniform
card budgets. Every state is planned before any native launch: a later state
whose required page overflows prevents the entire study from starting.
`tools/qualify_inkscape.py` also executes a two-state 26/28 mm card-width study,
checks both measured layouts and verifies common receipts independently.

## Isolated native visits and concurrency

Every version/query/export process has an adaptor-derived unique application-ID
tag and a private profile beneath its attempt directory. The documented
`--app-id-tag` is also supplied through upstream `INKSCAPE_APP_ID_TAG` before
startup: Inkscape 1.4.4 constructs and probes the default D-Bus application before
parsing CLI flags, so a CLI flag alone cannot isolate that constructor probe.
`INKSCAPE_PROFILE_DIR` confines native preferences to the visit. Shared timeout
and process-tree cancellation remain in force; concurrent workflows retain their
parallel scheduling. Independent verification checks all exact trusted command
arguments and stage tags. A native acceptance stress case runs three rounds of
four distinct jobs, mixing explicit and derived diagrams, under the existing
desktop session. No authored field controls application IDs, profiles or commands.
The implementation basis is the
[official 1.4.4 application source](https://gitlab.com/inkscape/inkscape/-/blob/INKSCAPE_1_4_4/src/inkscape-application.cpp)
and [public CLI manual](https://inkscape.org/doc/inkscape-man.html).
