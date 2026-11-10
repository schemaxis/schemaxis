# Ngspice linear-frequency electrical characterisation

Review date: 2026-11-03. Runtime observed: ngspice 47, latest stable on the
[official release page](https://ngspice.sourceforge.io/news.html) (47 released
11 August 2026). Supported product scope is bounded ideal linear electrical
characterisation; the capability-family map in [the guide](../docs/ngspice.md)
distinguishes this completed scope from whole-application breadth.

The change adds linear/decade/octave grids; declared peak/RMS phasor convention;
optional native input source current with independent network/KCL checking;
derived passive branch current/complex power and input impedance/power; named
sampled phase/dB/current/power/loading requirements. DC networks and first-order
RC transient retain their prior declared scope. General transient, nonlinear
models, extra source types, imported decks and arbitrary scripts remain excluded.

The public control-language tutorial and documentation remain mapping sources.
The current online PDF labels itself 47+ development, so it is not treated as
proof of release-47 behaviour. Release-47 distributed `acan.c` was inspected for
its frequency policy and fresh native cases verify that policy: longer decade
spans redistribute floored intervals to include stop; octaves and partial short
decades may end below stop. The SourceForge source-browser URL could not be
retrieved through the available browser tool; no new verified-live URL claim is
made for that endpoint. Release distribution and observed native behaviour supply
the implementation basis.

| Completion item | Reviewed result |
| --- | --- |
| Registration | Existing document route/runtime family retained; declared AC scope expanded without framework app branches or native host imports. |
| Schema | Complete AC spacing, amplitudeConvention, portMetrics and branchProbes declarations/schema/defaults; quantity-specific signed/nonnegative/phase constraints. |
| Semantics | SI/topology/resource checks precede native assignment. Actual log sample count 3–512, total output at most 64 columns, component selections and quantity targets validated. Undefined phase/dB and input impedance are refused with structured faults. |
| Native mapping | Generated `ac lin/dec/oct`, saved native `i(vdrive)`, exact raw variable names and expected logarithmic grid metadata; fresh process reload plus independent raw parsing. |
| Execution | Native source current is independently checked against solved-network current and native-voltage KCL before impedance division. Strict 1e-7 relative current checks have no absolute-current floor. AC voltage error scales with excitation; nonzero gain/phase requirements additionally demand 1e-7 relative agreement. Existing timeout/cancellation/publication verification applies. |
| Discovery | Seven new curated AC electrical phrases, including misleading-neighbour exclusions. Host capability matching passes all 12 cases after removing overly broad legacy manifest phrases. Existing ambiguous and negative cases retained. |
| Guidance | 239 field/operation records: 131 reviewed, 108 attributed/reference, 0 pending/0 stale; reviewed explanations include every new field and structural conditional. Explicit branch-derived versus native-input observations, passive sign and RMS/peak convention. |
| Help | Local guide and contextual guidance updated. Shared reference/packaged Help generation and production Studio Help search are integration-owner tasks, since the current parallel work owns shared generators. |
| Examples | Editable standalone logarithmic filter, RMS resonator power and partial-octave examples; filter characterisation Studio template. Four new conformance cases have independent RC/RLC impedance/power literals and frequency counts. |
| Tests |40 focused host tests pass, including immutable plans, defaults, invalid targets, density/resource rejection, sign reversals, RMS scaling, undefined quantities and tiny-signal falsification. Source/template/search host checks are described below. |
| Qualification | Fresh bounded native conformance passes 23 cases plus timeout and cancellation lifecycle probes. Dedicated electrical qualification passes 10 accepted variants, 4 negative controls and workflow reuse. No exhaustive/SPICE/nonlinear/MPI claim. Qualification will be rebound after shared integration. |
| Maintenance | Absorbed stable version remains 47. Upstream recipe/evidence and editorial assessment scope updated; whole-application breadth 15% and supported-workflow abstraction 80% retained as subjective estimates, not test-derived measurements. |

`tools/qualify_ngspice_characterisation.py` independently checks series RC/RLC
impedance/current, summed passive powers, peak/RMS and negative-source scaling;
full/partial decade and octave grids; changed-component performance failure;
workflow verification/resume; tiny 1e-15 V / 1e9 ohm source-current 2x and zero forgery
with refreshed evidence hashes; and tiny relative-voltage corruption. Negative
controls fail with `PERFORMANCE_NOT_MET` or `VERIFICATION_FAILED` as appropriate.
The latter controls close a review finding where a fixed 1e-12 A tolerance could
hide gross impedance errors or reach a zero denominator. User performance bounds
receive no solver-correctness tolerance. Phase uses principal relative transfer
angle with explicit zero-response and branch-cut policy.

Commands used (native jobs run under the repository bounded runner):

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_ngspice*.py' -q
PYTHONPATH=src python3 tools/studio_guidance.py --app ngspice --derive --check
PYTHONPATH=src python3 tools/qualify_ngspice_characterisation.py \
  --executable /absolute/ngspice --output-directory new-electrical-evidence
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.ngspice/1 \
  --native --executable /absolute/ngspice --output-directory new-conformance-evidence
```

Bulk logs/results remain outside the public repository. Root integration reruns
shared reference/Help/assessment generation checks, production Studio search,
admission, release gate, broad host regression and fresh source-bound native
conformance after all five adaptor branches are integrated. This review does not
claim those later shared checks have already passed. Existing optional Calc
handoff is unchanged; the new circuit scope was qualified through native tables
and verified workflow reuse without requiring an unrelated external workbook app.
