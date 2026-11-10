# Graphviz directed graph layout

Declare dependency topology and let Graphviz place fixed boxes and route edges.
Use this for branching build tasks, data lineage or feedback flows where manually
placing every node is tedious. Inkscape diagrams offer explicit visual placement;
this route expresses topology and checks an automatic native layout.

The document contract is `schemaxis.graphviz/1`; the qualified native target is
Graphviz **16.1.0**, from the [official stable source listing](https://graphviz.org/download/source/).
The host uses Python 3.10+ standard library only. Native `dot` runs in its own
process; discovery, planning, forms, schema and Help need no Graphviz installation.

## A branch and reconvergence

Open [the editable baseline](../examples/schemaxis/graphviz-baseline.json):

```json
{
  "version": "schemaxis.graphviz/1",
  "operation": "layout",
  "nodes": [
    {"id": "extract", "label": "Extract 01"},
    {"id": "build", "label": "Build"},
    {"id": "check", "label": "Check"},
    {"id": "publish", "label": "Publish"}
  ],
  "edges": [
    {"source": "extract", "target": "build"},
    {"source": "extract", "target": "check"},
    {"source": "build", "target": "publish"},
    {"source": "check", "target": "publish"}
  ]
}
```

`rankDirection` defaults to `TB` (top to bottom); choose `LR` for left to right.
`graphPolicy` defaults to `dag`: cycles fail before launching native code. Select
`cyclic` explicitly for feedback flows. Cyclic mode never promises every edge
moves forward through the ranks. The variant adds a downstream archive task;
the LR example changes orientation; the cycle example adds a feedback edge.

Run through the normal CLI with `--graphviz /absolute/path/to/dot`, or configure
that executable with `schemaxis configure`. Select a fresh output directory and
use the normal verify command to recheck retained evidence. See
[generated field reference](generated/graphviz-operations.md) and
[shared CLI help](user-guide.md) for the current command syntax.

## Input meaning and limits

- `nodes` contains 2–200 objects. `id` is a distinct unitless lowercase ASCII
  identifier (`[a-z][a-z0-9_]{0,31}`) used by edges; labels do not identify nodes.
  `label` is visible text: 1–24 ASCII characters, beginning with a letter/digit,
  followed by letters/digits/spaces or `._:/()+-`. Numeric labels remain literal.
- `edges` contains 1–500 unique directed source/target pairs. Endpoints must name
  declared IDs. Reversing endpoints reverses the dependency. Self-edges and
  duplicate pairs fail. Opposite edges are allowed only with cyclic policy.
- `rankDirection` and `graphPolicy` are layout intent; neither changes topology.
  Disconnected nodes are allowed. They remain visible and count in membership.
- Native nodes are fixed 2.5 by 0.5 inch boxes. Native defaults for routing remain
  part of the qualified release, while rank spacing is fixed at 0.5 inch and
  node spacing at 0.25 inch. There is no authored coordinate or unit setting.

This is a closed simple directed graph model. It accepts no arbitrary DOT,
HTML/escape labels, native flags, executable text, images, URLs, custom attributes,
clusters, ports, parallel edges, edge labels or font/style controls. Generated DOT
can be edited externally; those edits are outside a verified Schemaxis run.

## Publications, checking and ownership

Each run publishes `graph.svg`, editable trusted `graph.dot`, raw native
`graph.plain` and host-inspected `layout.json`. Plain/JSON geometry is in inches
from the lower left; SVG uses 72 points per inch and inverted y. Cubic control
points describe the edge body, with arrowheads excluded in the plain format.

The verifier compares exact literal node/edge membership and labels against the
authored graph, checks positive finite bounds, fixed boxes, nonoverlapping box
interiors, attached spline endpoints and the declared DAG direction. It parses a
closed SVG element/attribute grammar: extra overlays, hidden content, links,
scripts and opacity changes fail. Every node polygon and cubic control point is
compared with native plain geometry. Native plain uses five significant figures;
coherence tolerance is 0.02 point plus 5e-5 relative for coordinate rounding. SVG
viewports round to whole points and have a separate 0.51 point bound. Normal arrow triangles have a 10 point length and 7 point base, within 0.25/0.1 point rounding tolerances; their base midpoint lies within 0.5 point of the clipped spline endpoint. Their axis aligns with the terminal spline tangent to cosine greater than 0.98, allowing curved clipping. Arrow tips touch the target box within 2 points.

Literal topology is an independent expectation. SVG/plain coherence uses two
outputs of the same Graphviz engine and cannot establish optimality. This release
does not measure rendered typography, font substitution, crossing minimisation,
layout quality or complete visual equivalence. Native CPU is capped at 30 seconds,
address space at 512 MiB and each native file at 8 MiB; each retained file read is
bounded to 4 MiB. One total deadline includes version, layout and final inspection.
The shared runner owns cancellation of its process group. No native handles
cross workflow boundaries.

Authored/effective plans, generated DOT, input hashes, exact launchers, command
submissions, stdout/stderr, publication digests and an explicit success/failure
record are retained. Shared schema snapshots follow the framework store contract.
Reopening verifies captured data and never executes externally edited DOT.

## Workflow reuse and handoff

The normal workflow route supports document references, verified JSON result
values and finite studies. A producer's `layout.json` can supply `rankDirection`
to a consumer using `$value`, artifact index3 and `/rankDirection`; verification
runs before that value is accepted. Unchanged declared graph inputs reuse verified
results. Resume rejects a changed authored workflow; choose a fresh output directory after editing topology, labels, policy or direction. Corrupt cached output is independently rejected and rerun before downstream handoff.
There are no external file inputs. Handoff SVG/DOT as explicit output artifacts;
this route does not import an untrusted arbitrary DOT file.

A finite study over `rankDirection` values `TB` and `LR` produces separate isolated
native visits. Scheduling is the common batch workflow facility; this route has
no MPI, live native editing, reverse synchronisation or time-batch semantics.

## Recovery and maintenance

`GRAPH_CYCLE` at `$.graphPolicy` means remove a feedback edge or explicitly select
`cyclic`. `INVALID_GRAPH_EDGE` identifies dangling, duplicate or self endpoints;
correct IDs/pairs. `INVALID_GRAPH_NODE` means use distinct lowercase identifiers.
`INVALID_GRAPH_LABEL` means shorten text or remove unsupported punctuation.
`INTERPRETER_NOT_FOUND` means configure an absolute dot executable.
`UNSUPPORTED_NATIVE_VERSION` means use 16.1.0 or qualify a newer stable release.
`NATIVE_LAYOUT_WARNING` requires inspection of retained stderr; warnings never
silently count as verified. `VERIFICATION_FAILED` means retained evidence differs
or violates geometry/topology checks; rerun into a fresh directory after repair.
Reopening distinguishes malformed from unsupported evidence: retained JSON that is
unreadable, over-nested or not a Graphviz version line is `VERIFICATION_FAILED`;
a well-formed Graphviz identity for another version is `UNSUPPORTED_NATIVE_VERSION`,
only for an intact retained identity consistent with its receipt. Genuine 16.1.0 receipts are
unchanged.

Official mapping: [DOT grammar](https://graphviz.org/doc/info/lang.html),
[dot layout](https://graphviz.org/docs/layouts/dot/),
[rankdir](https://graphviz.org/docs/attrs/rankdir/),
[plain output](https://graphviz.org/docs/outputs/plain/), and
[SVG output](https://graphviz.org/docs/outputs/svg/).
Review the latest stable release and rerun `tools/qualify_graphviz.py` before
advancing `upstream.json`. Qualification covers named baseline/variant/LR/cycle
cases, hostile evidence, lifecycle and common workflows; it is never exhaustive.
