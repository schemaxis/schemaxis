# Named flat tools and drilling cycles — scoped qualification

This milestone adds reusable named flat-endmill tools, explicit per-operation
tool selection, source-XY hole layouts and G81/G82/G83/G73/G85 drilling cycles.
It extends the existing `schemaxis.freecad.cam/1` document with an internal
compiled plan/2; legacy single-tool face/pocket plan/1 remains supported.
Whole CAM and whole FreeCAD completion remain open. This named-tool/drilling
milestone passed integrated source and installed-package acceptance; broader
application acceptance remains pending.

The fixed native baseline is FreeCAD 1.1.4, observed build
`4fd3bf320d9566a27e60069fc8387448aaa3a094`, with OCCT 7.8.1. The independent
cycle reader uses the explicitly documented default
[LinuxCNC 2.9.4 cycle semantics](https://github.com/LinuxCNC/linuxcnc/blob/v2.9.4/src/emc/rs274ngc/interp_cycles.cc).
This checks programmed motion and material, rather than executing a controller
or certifying machining safety, fixtures, servo behaviour or physical timing.

## Authority and physical distinctions

The constructor compiles named tools and every selected hole from typed intent.
It explicitly restores final tool-table order and per-operation assignments
after the native first-used-tool construction sequence. Complete current trusted
reconstruction from captured source bytes binds XML, dependencies, expressions,
proxies, string IDs, element maps, all local postfix dictionary entries and
native payloads before submitted CAM restoration. A checked digest survives
host admission, private copying and native reopen; source inputs are re-admitted
after use. Editable readbacks are witnesses, not constructor authority.

An independent NC parser expands tool-specific motions and cycles. G98 comes
from actual preceding NC position and persists through an active cycle; G99
returns to R. G83/G73 use the declared fixed 0.254 mm default backoff. G85 feeds
to R before a possible rapid return to the initial plane. The six-decimal saved
native Path binding is distinct from the prospective eight-decimal posted-word
geometry bound. No geometric comparison tolerance was widened.

Material replay retains each cutter radius and depth. In particular, a large
shallow counterbore and a small deeper hole at the same XY position do not become
one large deep cylinder. Exact circular/capsule/arc XY coverage is integrated
through depth slabs, with target sections, remaining material, residual and
gouge checked independently of the native toolpath report. Pointed drill cones
are not represented by this flat-tool model.

## Source-labelled native and product evidence

Evidence is retained by execution epoch; a failed aggregate report does not
become a passed report after a later repair.

| Source epoch | Executed proof and result |
| --- | --- |
| `74f046a` | Native mixed face/drill/pocket construction and reopen pass after removing the default diameter-driven PeckDepth expression. The preceding native result exposed Q2.5 being overwritten by 3 and remains a failed epoch. |
| `f71df4c` | Translated concentric D6/depth2 and D2/depth8 source passes independent volume, centre and three literal section areas: 720, 720−pi and 720−9pi; removed volume is 24pi. Actual G98 initial5/R3/return5 differs from G99 return3. Publication-change and private-copy-change controls refuse before submitted document open. |
| `c7eb3fe` | Public construction/fresh verification passes for G82/G73/G85 with T2→T1→T2. Q0.137 produces a backoff above R, the final partial peck is distinguished, and G85 feed return differs from rapid return. The preceding host assertion incorrectly fixed the native enum to G98; actual native G99 was correct. |
| `2663085` | Three public native constructions, separate reopen/material workers and fresh verification pass: concentric counterbores, the reversed-first-used tool/cycle case, and fractional D3.175 pitch-circle drilling with an implicit single tool. Aggregate qualification later fails because its adversary expected a metric change inside the existing absolute 1e−6 comparison to refuse. That failed oracle and its original runtime remain retained. |
| `9f59a2f` / `2cb1bcd` | Exact runtime comparison against the preceding epoch changes only `cam_checks2.py` and assessment metadata. Current fresh verification of all three historical constructions passes. Semantic material counters now require exact integer types/values; metric tolerances are unchanged. Fourteen refreshed provider attacks and restored control, controlled private GUI peck/plunge edit-save and separate GUI reopen, exact repost against fresh typed edited construction/material, physical cutter checks, workflow reuse/damage/recovery, original-source retirement, actual timeout/cancellation and wholly current recovery construction pass. A separate actual CAD-producer-packet retirement control passes standalone public verification. |
| `a755403` | Complete CAM-local postfix dictionary binding closes the independently reproduced unused-entry defect. Exact runtime delta from `9f59a2f` is only `cam_state2.py` and assessment metadata. Current verification of the three historical cases, a wholly current public construction/reopen/material/fresh verification, four refreshed dictionary mutations and restored public verification pass. Forty-two focused CAM host tests pass. |

The private GUI edit output is explicitly pinned by the host for the controlled
separate reopen. It is not a generic externally edited CAM-project adoption API.
The edited repost equals a fresh typed edited construction; selected Source,
Clone and final cutter BREP bytes are checked separately. The rendered GUI
screenshot shows the normal visible stock/path view, not a claimed finished-solid
thumbnail. Native API and receipt/helper failures are retained with their exact
phase boundaries; corrected reporting tails do not repeat or relabel previously
completed native phases.

Product checks pass for the named-drilling starter, all FreeCAD starter planning,
CAM conformance, reviewed guidance with zero pending/stale entries, five schema
parity checks and actual Chromium forms for named/legacy tools, cycle-dependent
dimensions, hole layouts and atomic undo. A private fresh Help build contains
1601 topics and passes structural readiness without writing shared generated
assets. These product checks were executed at `9f59a2f`; their schema, guidance,
examples, Studio, documentation and Help-source bytes are unchanged by the
subsequent CAM-local map repair. Final integrated generated Help remains a root
integration gate.

## Independent review and repaired counterexample

A separate reviewer constructs a translated asymmetric five-hole pitch circle
with a 17-degree phase, D4/depth3.5 counterbores and D1.5 extensions to10.25,
T2→T1→T2 and Q0.193. Independent literal removed volume
`88.984375*pi`, source centre and all three depth sections pass. Posted tool
order, small-Q backoff, final partial peck and distinct return planes pass.
Twelve refreshed native/proxy/expression/resource/source/NC attacks refuse.
A different real hole pattern with unchanged scalar mass/bounds is refused by
full trusted Source payload comparison. Original-source/producer retirement and
restored public controls pass.

That review reproduces a P2 at `2cb1bcd`: adding an unreferenced local postfix
definition with a foreign owner to `Clone.Shape.Map.txt`, then refreshing native,
material, bundle and publication hashes, passes public verification. No geometry
or execution bypass is established; the accepted entry violates the complete
closed-inventory contract. `a755403` compares the full semantic multiset of every
local dictionary entry under the complete object-ID/StringID mapping, preserving
multiplicity while allowing allocation order. Shared parsing and tolerances are
unchanged. Independent current public verification of the labelled historical
held-out construction passes; five refreshed foreign-owner, missing-StringID,
extra, changed and duplicate unused-entry attacks refuse; restored verification
passes. The P2 is closed in this scoped review. The reviewer authored part of the
older CAM1 foundation; this relationship is disclosed separately from the new
CAM2 implementation and held-out review.

Reproduce the public qualification from the checkout root:

```bash
PYTHONPATH=src python3 tools/qualify_freecad_cam_drilling.py \
  --directory /absolute/path/to/a/new/qualification-directory \
  --executable /absolute/path/to/freecadcmd \
  --gui /absolute/path/to/freecad
```

The command creates synthetic fixtures and mutates only its own packets. Native
execution must use the applicable resource envelope and private application
configuration. Its source digest binds that new execution, not the historical
phase-labelled evidence above.

## Integrated source and installed-package acceptance

The combined source `0dc9648821dd4818a471d985bc72d79048354f78` retains all
111 FreeCAD provider Python files byte-identical to reviewed owner `e4fe711`.
Shared reference, assessments, Studio Help and admission assets were regenerated.
All 338 FreeCAD host tests, 87 relevant shared/readiness tests, guidance and
structural admission checks for all four programme adaptors, source private
release checks and both Body-seed/CAM browser tests pass. These are scoped
milestone gates; final whole-application host/Studio acceptance remains open.

The public drilling qualifier passes on this exact integrated source, digest
`sha256:834e2c2cd89da0ed7093490836552987d22614b1a28602d3f6b25ad436331ce7`.
It covers all three variant constructions and independent geometric/controller
expectations, refreshed dictionary/proxy/tool/NC/material attacks, restored
controls, controlled separate GUI edit/reopen/exact repost, workflow reuse,
damaged-output rebuild, producer and original-source removal, actual timeout,
cancellation and successful current recovery. No tolerance changed.

A fresh locally built wheel has SHA256
`44a0a5363b042a4f6527f8c6296600cf4f2dc6c579c6a5002355cbcf404a6bad`.
All 2973 packaged files match the integrated source and every runtime Python
module is included. Clean installation passes all four adaptors' discovery,
starter planning and bundled Help without importing native modules. Actual
installed execution passes the two-job CAD-to-named-drilling workflow with
literal removed volume `24*pi` and three depth sections, fresh verification,
complete reuse and standalone CAM verification after producer retirement.
Installed HDF5 exact uint64/NULL/selected-field and Zstandard round-trip/source
removal checks also pass. The unchanged private wheel gate passes.

The first installed aggregate fails only in the browser phase because its empty
private workspace lacks the explicitly declared starter STEP fixture. Native,
discovery and API phases had already passed. Supplying the declared fixtures at
the authored relative paths allows the same wheel, environment and browser tests
to pass for named CAM and Zstandard; no source or assertion was changed. Both
phase-labelled results are retained. The integrated native and installed records
are archived with per-record hashes and independently decoded/rehashed before
scratch cleanup. This closes the scoped milestone, with the limitations below.

## Remaining required breadth

Supported tools are centre-cutting flat endmills whose cutting length reaches
the entire blank and whose shank is no wider than the cutter, even for shallow
operations. Pointed drills, conical floors, full-diameter versus tip depth,
short-tool per-operation reach, wider shanks and holder/fixture clearance remain
required missing capabilities. Stock has zero side/bottom allowance and a fixed
top-centre +Z setup. Exterior profiles/holding, surfacing, ramps/helices, adaptive
strategies, probing, multi-axis and other posts remain required open breadth.
Generic foreign or externally edited CAM FCStd adoption is not offered. These
limits leave the application-wide capability inventory incomplete; this note
qualifies only the named flat-tool/drilling milestone.
