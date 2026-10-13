# AC inductors and independently verified RLC responses

The existing `schemaxis.ngspice/1` document route now supports uncoupled ideal
inductors in `acSweep`. No shared runtime source, provider route or host dependency
was added. The latest stable release remains **ngspice 47**, checked against the
[official release page](https://ngspice.sourceforge.io/news.html); the configured
isolated executable reports that version. No native rebuild was needed.

The [guide](../docs/ngspice.md) and operation schemas define inductance in henries,
1e-9–1000 H, at most 64 coils, sixteen non-ground nodes and fifteen AC probes.
DC and `rcStep` reject the inductors field. Mutual coupling, magnetic cores,
nonlinear devices, inductor DC sweeps, RLC transients and arbitrary netlists remain
unsupported. The [editable RLC workbook workflow](../examples/schemaxis/ngspice-rlc-to-calc.json)
uses the existing verified table handoff.

## Independent circuit expectations

All **15 native kit cases** pass, including the preceding nine DC/RC cases and
six new inductive cases:

- RL cutoff: series 1 H and shunt 1000 Ω give `(1-j)/2` at ω=1000 rad/s and
  `(1-2j)/5` at twice that frequency.
- RL polarity: reversing coil terminals preserves response; a -2 V source gives
  `-1+j` V at cutoff.
- Series RLC: R=1000 Ω, L=1 H and C=1 µF give capacitor voltage `-j` V at
  resonance and `(-3-2j)/13` V at twice the resonant frequency.
- Inductance variant: doubling L gives `(-1-j)/2` V at the original resonance.
- Split coil: series 0.25 H and 0.75 H preserve the original response while
  exercising another internal node.
- Parallel LC: a resistor-fed tank leads below resonance, has unity gain at
  resonance, and lags above it. Endpoint phasors are `(4+6j)/13` and `(36-30j)/61` V.

The literal expectations come from closed-form transfer functions in the guide,
not observed simulator output. The host independently stamps `1/(jωL)` into its
complex nodal equations and checks every native voltage, including unselected
internal nodes. A host ASCII parser and a fresh ngspice process both read the
saved raw data. Phase, magnitude, coordinates, sample count and topology remain
part of verification; phase at zero magnitude has no physical interpretation.

Every requested frequency is checked before execution. A permanent negative
fixture demonstrates an undamped LC singularity at the middle of a sweep with
valid endpoints. Retaining uncancelled admittance scales prevents a near-zero
resonant stamp from being mistaken for a well-conditioned one-by-one system.
Inductor-only loops and inductive shorts across the ideal source are rejected
because they lack a unique DC operating point.

All **180 missing/tampered evidence probes** and both timeout/pre-launch
cancellation checks pass. A separately forged raw-data digest still cannot hide
changed variable names. Unit coverage also rejects invalid inductance, injected
identifiers, DC inductors, source loops, wrong complex signs and changed unselected
internal voltages. Successful process exit alone is never accepted as evidence.

## Handoff, public authoring and package execution

Four ngspice → Calc workflows pass complete numeric workbook readback: the two
original divider variants and the RLC circuit with 1 H and 2 H coils. All jobs
reuse on unchanged resume. The RLC phasors are additionally compared to the
closed-form transfer function at every published frequency.

The public context/source/property/plan/execute/inspect sequence checks all fifteen
cases. A real terminal-console patch edits the same durable draft from 1 H to 2 H;
the old plan is rejected as stale and the verified response changes from `-j` to
`(-1-j)/2` V. The deterministic client made **273 requests / 224,713 response
bytes**. This is protocol/procedure evidence, not an autonomous-model evaluation.

The wheel builds and installs into an isolated target. Import location is checked;
that installed package then plans, executes and independently verifies the RL,
series RLC and parallel LC examples against the real ngspice executable.

## Reproduction and catalogue evidence

```sh
PYTHONPATH=src python3 tools/qualify_ngspice.py \
  --config /path/to/private-config.json --output-directory new-acceptance
PYTHONPATH=src python3 -m schemaxis adaptor record new-acceptance/native/qualification.json
PYTHONPATH=src python3 tools/qualify_adaptor_migration.py --output-directory new-host
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
PYTHONPATH=src python3 -m unittest discover -s tests/conformance -p 'test_capability_protocol.py' -q
PYTHONPATH=src python3 -m schemaxis reference --check
```

The ngspice receipt was freshly generated and registered from this implementation.
All **fourteen native receipts remain source-current**, covering **49 cases, 532
integrity probes and 28 lifecycle probes**. Only ngspice native qualification was
rerun in this update; other receipts remain current from the preceding
refresh because no shared or other-adaptor implementation changed. All thirteen
adaptors / fifteen routes pass fresh host conformance. The experimental
case-preparation route remains native unavailable.

Bulk evidence is retained under `evidence/ngspice-rlc-acceptance/` and
`evidence/ngspice-rlc-host/`. The installed-package report is
`evidence/ngspice-rlc-package-check.json`; receipt freshness/counts are in
`evidence/ngspice-rlc-final-status.json`. User native configuration and PATH were
not changed. Earlier acceptance records remain historical evidence, including
the original [nine-case circuit milestone](2026-09-28-ngspice-growth.md).

Final regression: **764 tests passed, 22 skipped (786 total)** in 190.900 seconds.
Both capability protocol tests passed in 54.519 seconds; all **56 generated
references** are current and development admission passes for all fifteen routes.
Logs: `evidence/ngspice-rlc-unit.log`, `evidence/ngspice-rlc-protocol.log`,
`evidence/ngspice-rlc-admission.json` and `evidence/ngspice-rlc-reference-check.json`.
Skipped tests do not establish native qualification.
