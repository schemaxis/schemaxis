# Graphviz completion review — 17 October 2026

Implemented `schemaxis.graphviz/1` with one `layout` operation: a declared simple
directed graph, automatic native placement/routing, editable trusted DOT, SVG,
native plain layout and independently inspected JSON geometry. The useful scope
is dependency/lineage diagrams with branches and reconvergence, plus explicit
feedback flows. It differs from manually positioned Inkscape diagrams by expressing
named topology and asking native dot to place it. The host stays Python 3.10+
standard library only; native code runs in isolated processes.

Root reviewed the design and critical native/verification code before activation.
No shared registry, framework, generated reference or Help files were edited by
the adaptor owner. Root owns integration/generation and final batch freshness.

| Checklist ID | Reviewed result and evidence |
| --- | --- |
| registration | `adaptor.json` registers a serial document route, CLI/config executable, workflow/composition/reuse/resource hooks, bounded support decisions. Activated by root after critical-code review. |
| schema | Typed declarations and generated literal schema agree for node IDs/labels, edge endpoints, TB/LR and DAG/cyclic policy. Nine host tests plus host conformance **31** checks cover immutable deterministic plans, six valid/invalid fixtures and both typed defaults. |
| semantics | Node identity/label grammars, endpoint membership, exact edge multiplicity, self-edge rejection and DAG cycle detection run before native launch. Semantic invalid fixtures retain exact `GRAPH_CYCLE` and `INVALID_GRAPH_EDGE` faults and authored locations. |
| native-mapping | Reviewed official dot, DOT grammar, rankdir, plain and SVG documentation on 17 October 2026. Generated digraph fixes boxes, spacing, font and arrow design; native version is gated before rendering. Node IDs are safely quoted, including DOT reserved words. All supported label punctuation and numeric zero were executed natively. |
| execution | Owned process-group runner, total deadline, 30 s CPU/512 MiB address-space/8MiB file caps, bounded no-follow regular-file reads and 4 MiB evidence cap. Retains exact trusted launcher/input hashes/submissions/stdout/stderr; raw artifacts, generated source, plan and receipt membership are rechecked. Inflight slow-wrapper timeout/cancellation probes terminated the actual child PID and left explicit failed status. Wrappers qualify lifecycle only. |
| discovery | Five reviewed cases include automatic layout, dependency diagram, directed graph, ambiguous layout and unsupported OCR. Actual CLI/agent catalogue matching passes. Production Studio selection/Add/Help and contextual Help pass 6/6 tests after shared generation; finding this route makes no suitability-ranking promise. |
| guidance | All 14 records reviewed: operation plus 13 literal schema addresses, including array objects and endpoints. Fields explain units, omission/defaults, examples, limits and common mistakes. Guidance audit passes with zero pending/stale records. |
| help | Guide, current official API sources, exact fault/recovery descriptions and generated operation-reference link retained. Root generated operation reference/contextual Help; production search and genuine documentation admission pass. |
| examples | Editable baseline branch/rejoin, LR variant, additional archive node/edge, explicit feedback loop, and two schema-valid semantic-invalid examples. Three self-contained Studio starters need no external source data or fake resource paths. Native expectations include literal node/edge lists and labels; a separate reader checks baseline coordinates. |
| tests | Nine owned host tests pass; actual common host conformance passes 31 checks. Closed SVG tests reject erased text, opacity, paint, hidden font size, external link/script, overlays, transformations and changed path coordinates. Native qualifier adds 14 adversaries that refresh receipt hashes, four-case native integrity probes, numeric-zero disappearance, and workflow/study checks. |
| qualification | Full `tools/qualify_graphviz.py` run passed on actual Graphviz 16.1.0. Four case receipts include 56 missing/tampered artifact/evidence probes and common prelaunch cancellation/timeout. Supplemental native max-size case uses 200 nodes and 500 edges in LR and checks exact input membership. Source-bound registration and a post-configuration shared refresh both pass; freshness must be rechecked after later integrations. |
| maintenance | Latest official stable 16.1.0 source SHA verified before isolated build; `upstream.json` absorbed 16.1.0 only after host/native acceptance and root code review. Release source, scope, repair/requalification recipe and evidence are retained. |

No clusters, ports, parallel edges, edge labels, arbitrary DOT/native flags,
images, URLs, HTML/escape labels, custom styles, MPI, native inspection/live editing,
reverse synchronisation, native save, conversion or time batches are advertised.
The route has no source-file input to capture or hash; the complete declared graph
binds reuse. Shared schema snapshots, metadata and common study/workflow contracts
are exercised through the normal adaptor runtime.

## Native and independent checks

Observed runtime: `dot - graphviz version 16.1.0 (20260904.0139)`.
Official source archive SHA256:
`beea483ab130f456c1c3905f4f2e40778a9c493c3d73ae8012367d552d71ca84`.
Source/build/bulk evidence stays under ignored
`evidence/programme-20261017/graphviz/`; configure, make -j4 and isolated-prefix
installation transcripts append to the session's home build log. No system
installation or PATH modification occurred.

The independent oracle enumerates literal node/edge multiplicity and labels from
authored inputs and computes cycle/topological properties. Native plain geometry
is checked for positive finite bounds, fixed 2.5 by 0.5 inch boxes, nonoverlapping
interiors, attached spline endpoints and DAG TB/LR direction. Cubic extrema are
evaluated analytically: off-curve control points can legitimately lie outside
curve bounds. Baseline raw native centres independently equal extract(2.625,2.25),
build(1.25,1.25), check(4,1.25), publish(2.625,0.25), in inches.

SVG is parsed with a closed role/attribute grammar, not a blacklist. Every box
and spline coordinate agrees with native plain inches at 72 points/inch with y
inversion. Plain has five significant figures; SVG has two decimals, and its
viewport rounds to whole points. Coordinate coherence uses 0.02 point plus 5e-5
relative; viewport uses a separate 0.51 point rounding allowance. Normal arrow
triangles have checked dimensions, base proximity, orientation and target-box
attachment. Arrow shape is measured from already-checked SVG path coordinates,
avoiding amplified plain rounding on the 599.5 inch max-size graph.

SVG/plain coherence shares one native engine and is not an independent layout
algorithm. Native topology and box/direction invariants are independent checks.
No typography, font metrics, optimum/crossing-minimised layout, complete visual
fidelity or exhaustive build/version compatibility is claimed.

The qualifier's extra adversaries refresh artifact/evidence hashes and metadata,
so topology, visibility, geometry, trusted source/command and membership checks
must detect the mutation. All 14 reject; numeric-zero disappearance also rejects
in a separate real-native reserved-ID case. Common four-case integrity adds 56
missing/tampered probes without pretending those are independent layout oracles.

Workflow proof: verified layout JSON artifact 3 `/rankDirection` feeds a consumer;
unchanged resume reuses both jobs; corrupt cached producer output causes producer
and consumer reruns. Editing the authored workflow returns `RESUME_MISMATCH`;
a fresh changed workflow hands LR to its downstream consumer. A two-visit TB/LR
study verifies both isolated visits. Each native fixture uses a fresh output.

## Commands and retained status

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_graphviz.py -q
PYTHONPATH=src python3 tools/studio_guidance.py --app graphviz --check
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.graphviz/1 --output-directory evidence/graphviz-host-fresh
PYTHONPATH=src python3 tools/qualify_graphviz.py --graphviz /absolute/path/to/dot --output-directory evidence/graphviz-native-fresh
node --test --test-name-pattern='graphviz:' src/schemaxis/studio_ui/tests/search-acceptance.test.mjs
PYTHONPATH=src python3 -m schemaxis readiness --app graphviz --admission --check
```

First full acceptance:
`evidence/programme-20261017/graphviz/acceptance-v1/acceptance.json` is verified.
Host conformance is
`evidence/programme-20261017/graphviz/host-active/qualification.json`.
Initial Studio/admission checks identified only absent packaged Help while root's
shared generation was still pending. They are not counted as passes. Final
source generation, production search, admission and fresh registration are
recorded below once complete.

Final local acceptance and registration succeeded at the source epoch
`sha256:53dd569c9ab7cbcb4bb5d10af2526aef07113b98b99569adbe474d80641941a1`.
`evidence/programme-20261017/graphviz/acceptance-final/acceptance.json` is verified;
its `kit/qualification.json` supplied the registered package receipt. Current
source identity matched that receipt immediately after registration. Upstream
16.1.0 absorption followed successful host/native acceptance and critical review.

Production Studio search/contextual Help passes **6/6** tests; all five curated
queries use actual selection/Add/Help functions. The nine owned host tests now
also compare actual CLI and public agent-service results for every query.
`admission-final.json` reports `structurallyComplete: true`, with no required
failure/unknown. Guidance has 14 reviewed records, zero pending/stale records.
Shared reference/Help generation was performed by root before these checks.

Subsequent shared framework/generated-Help changes can conservatively stale this
receipt. Root announced a later generic Python-venv executable configuration fix;
that is separate from this adaptor's native graph scope. Preserve the historical
receipt and refresh common source-bound qualification after root's final source
freeze. Do not rewrite its old digest or claim freshness without the check.


Root completed and tested the shared configuration fix. A single common native
refresh then passed all four cases, 31 host checks, 56 integrity probes and two
common lifecycle checks, and registered the current receipt from
`evidence/programme-20261017/graphviz/common-post-config/qualification.json`.
The package receipt now has source identity
`sha256:3fc71da151b506943dede01cfcfbfeda74b7e515fc1d925b522d8f9c1fdeb2cf`,
which matched current source immediately after registration. The earlier full
acceptance reports retain supplemental lifecycle/workflow/limits/tamper evidence;
none is relabelled as a run against a different source. All adaptor-owned work is
complete, with no running processes or unresolved native failures.
