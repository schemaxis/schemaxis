# Declared linear circuits with ngspice

`schemaxis.ngspice/1` generates inspectable netlists and runs **ngspice 47** in
isolated batch processes with startup files disabled. It supports ideal resistor
and capacitor networks with one grounded ideal voltage source, uncoupled ideal
inductors in AC sweeps, and a bounded first-order RC transient. The host has no
ngspice or numerical-library dependency.
The bridge and two-stage RC ladder examples also exercise multiple unknown nodes.
This is a circuit simulation provider; it does not import KiCad boards/schematics,
load vendor models, accept arbitrary netlists or control physical hardware.

The [official release page](https://ngspice.sourceforge.io/news.html),
[control-language tutorial](https://ngspice.sourceforge.io/ngspice-control-language-tutorial.html)
and [native documentation](https://ngspice.sourceforge.io/docs.html) define the
upstream CLI and analysis commands. Ngspice has BSD-style licensing; see its
[source distribution](https://ngspice.sourceforge.io/download.html) for notices.

## Shared document authoring

Start from the [divider](../examples/schemaxis/ngspice-minimal.json),
[RC frequency response](../examples/schemaxis/ngspice-rc-frequency.json) or
[RC step response](../examples/schemaxis/ngspice-rc-step.json).
For inductive circuits use the [RL low-pass](../examples/schemaxis/ngspice-rl-frequency.json),
[series RLC resonance](../examples/schemaxis/ngspice-rlc-resonance.json) or
[parallel LC band-pass](../examples/schemaxis/ngspice-rlc-parallel.json).
This route uses a document, not a node graph. Shared source and JSON-pointer
property edits, history, undo and revision checks remain available.

Every input declares `version`, `operation` and `circuit`. The circuit contains:

- `source`: the driven node, default `in`; the ideal source's other terminal is
  ground node `0`. Other names use lowercase ASCII letters, digits and underscores,
  start with a letter, and have at most 32 characters.
- `resistors`: 1–64 `{name, a, b, resistance}` objects, resistance in ohms,
  range 0.001–1e9. `a` and `b` are distinct node names.
- `capacitors`: 0–64 `{name, a, b, capacitance}` objects, capacitance in farads,
  range 1e-12–1. Component names must be unique.
- `inductors`: AC only, 0–64 `{name, a, b, inductance}` objects, inductance in
  henries, range 1e-9–1000. No coupling, winding resistance, core or saturation
  model. Names are unique across all component types. Omit this field for DC/RC
  transient documents; those operations reject it, including an empty array.
- `probes`: selected non-ground voltage nodes, default `["out"]`. At most sixteen
  non-ground nodes are allowed; AC selects at most fifteen probes to keep its
  four columns per probe within the shared numeric-table limit. Every node must have
  a resistor/inductor path to ground or the source for the DC operating point;
  capacitive-only references are rejected. Ideal-inductor loops and inductive
  shorts across the source are rejected because they lack a unique DC operating
  point. Floating/ill-conditioned networks fail.

Operation fields are at the document root:

- `dcSweep`: `start` and `stop` in source volts (default 0 and 5, range ±1000),
  `points` (2–512, default 101). Capacitors are open at DC.
- `acSweep`: positive `start`/`stop` in Hz (range 0.001–1e9, defaults 1/10000),
  `points` (3–512) and nonzero `amplitude` in volts (default 1, range ±1000).
  Frequencies are linearly spaced, including endpoints. Phasors use exp(+jωt).
  Inductor admittance is 1/(jωL). Every requested frequency is checked before
  native execution, including singular undamped resonances inside the sweep.
- `rcStep`: exactly one resistor between source and response node and one capacitor
  between response and ground. `amplitude` is the step in volts; capacitor voltage
  starts at zero. `stop` is seconds (1e-9–1e6) and must be 0.01–20 RC time constants.
  `points` selects uniform output times. General transient networks are rejected.

Sweeps require `stop > start`. The qualified ngspice 47 linear AC command returns
only one sample when requested with two points, so the host explicitly requires
at least three AC points and verifies exact sample counts. Native transient integration uses a maximum internal
step no greater than RC/1000 before uniform resampling. Point counts bound published
results; the RC duration bound also caps integration work. Use a fresh output
directory and configure ngspice or pass `--ngspice /absolute/ngspice`.

## Publications and independent verification

1. `results.csv`, kind `table`: source volts, frequency Hz or time seconds followed
   by selected voltages. AC supplies real/imaginary volts, magnitude volts and
   principal phase in degrees. Phase wrapping at ±180° is a representation choice.
2. `circuit-summary.json`, kind `text`: topology, output columns, first/last sample,
   maximum independent voltage error, RC time constant and declared limits.
3. `circuit.cir`, kind `text`: the deterministic generated simulation netlist.

## Named sampled performance requirements

An optional root `requirements` array declares 1–32 named performance checks.
Each selects a published `probe`, `quantity`, sample `axis`, inclusive two-value
`window`, and at least one inclusive `minimum` or `maximum`. Names are unique
lowercase identifiers. The explicit quantity and axis names carry their units:

| Analysis | Quantity | Sample axis | Interpretation |
| --- | --- | --- | --- |
| DC sweep | `voltage_V` | `sourceVoltage_V` | Signed probe voltage in volts versus signed source voltage. |
| AC sweep | `magnitude_V` | `frequency_Hz` | Absolute probe phasor magnitude in volts versus frequency in Hz. |
| AC sweep | `gainMagnitude` | `frequency_Hz` | Dimensionless `abs(Vprobe)/abs(Vsource)` in V/V; a negative source does not invert this magnitude. |
| RC step | `voltage_V` | `time_s` | Signed probe voltage in volts versus time in seconds. |

For example, the [RC filter requirement](../examples/schemaxis/ngspice-ac-requirements.json)
checks the measured gain at three declared frequencies between cutoff and twice
cutoff. The ideal response `1/(1+jωRC)` has gain `1/sqrt(2)` at cutoff and
`1/sqrt(5)` at twice cutoff, so this requirement passes the nominal circuit:

```json
"requirements": [{
  "name": "filter_gain", "probe": "out", "quantity": "gainMagnitude",
  "axis": "frequency_Hz", "window": [159.15494309189532, 318.30988618379064],
  "minimum": 0.44, "maximum": 0.72
}]
```

A window must lie inside the declared analysis interval and contain a declared
sample. Equal endpoints select a single sample. Endpoint comparisons allow eight
floating-point representable steps at the largest absolute interval/window
coordinate; the summary records this `endpointTolerance` in the axis units.
Selection uses the declared sample coordinates, avoiding native accumulation
roundoff; both declared and native coordinates are retained for the worst sample.
This endpoint allowance never relaxes voltage or gain bounds. Performance bounds
apply directly to measured native values, independently of the existing solver
correctness tolerances. Use meaningful bounds with room for numerical precision.
Magnitude/gain bounds must be nonnegative; voltage bounds preserve polarity.
Phase requirements are not supported, avoiding wrapping and zero-magnitude angle
ambiguities. There are no arbitrary requirement expressions or native scripts.

`circuit-summary.json` retains `performance.accepted`, each requirement's observed
minimum/maximum, checked sample count and bound checks. A lower-bound check uses
the smallest signed voltage (not its absolute value); an upper bound uses the
largest. Signed `margin` is observed-minus-minimum or maximum-minus-observed, so
a negative margin identifies a violation. Every bound reports its worst sample
index and operating coordinate. An unmet requirement suggests inspecting that
condition and revising components, excitation or the stated bound.

Solver correctness is verified first through native raw readback and independent
equations. A physically verified ideal circuit that misses its stated performance
requirements fails with `PERFORMANCE_NOT_MET`, retaining the native files, CSV,
summary and explained checks. It is not a successful workflow publication and
cannot be resumed as a success. Invalid names, axes, probes, windows and
contradictory bounds fail during planning as `INVALID_REQUIREMENT` (typed violations
use `INVALID_ARGUMENT`). Native computation failures retain their existing faults.
Offline verification reconstructs performance from authored requirements and
checked native voltages, so refreshing publication hashes cannot hide forged
assessments.

The [divider requirement](../examples/schemaxis/ngspice-dc-requirements.json) and
[settling requirement](../examples/schemaxis/ngspice-step-requirements.json) supply
DC and RC examples. Doubling the filter capacitor reduces its sampled gain below
the stated minimum; doubling the step resistor delays reaching 4.7 V in the
selected window. [The capacitance study](../examples/schemaxis/ngspice-capacitance-study.json)
uses the existing `$analytic` finite-values mechanism to compare 0.98, 1 and 2 µF.
The last visit is deliberately unmet and retains its evidence; this is not an
automatic tolerance optimiser. Smaller component changes are not independently
modelled uncertainties unless authored as separate visits.

These assessments cover only the finite declared samples and component values.
They do not prove behaviour between frequencies/times, exact crossing/settling
times, continuous-band extrema or every value within a manufacturing-tolerance
range. Narrow resonances can lie between samples. Add justified sample locations
or separate parameter visits; the adaptor does not invent continuous-envelope or
physical-device guarantees.

```sh
PYTHONPATH=src python3 tools/qualify_ngspice_performance.py \
  --executable /absolute/ngspice --output-directory new-performance-acceptance
```

Keep the summary and netlist with CSV. There is no schematic layout, PCB geometry,
automatic component-tolerance model, parasitic model, nonlinear behaviour or general device-current
publication. The editable [ngspice → Calc workflow](../examples/schemaxis/ngspice-to-calc.json)
checks numeric workbook readback. Reuse on unchanged workflow resume remains
subject to ordinary artifact and authored-plan verification.
The [RLC → Calc workflow](../examples/schemaxis/ngspice-rlc-to-calc.json) preserves
frequency, real/imaginary voltage, magnitude and phase in an editable workbook.

## Analytic inductive examples

The RL example has series L=1 H and shunt R=1000 Ω. Its resistor voltage is
`H=1/(1+jωL/R)`, giving `(1-j)/2` at 159.15494309189532 Hz and `(1-2j)/5`
at twice that frequency. Reversing an uncoupled inductor's terminals does not
change node voltages; reversing source amplitude reverses the voltage phasors.

The series RLC example uses R=1000 Ω, L=1 H and C=1 µF, with output across C.
Writing `x=ω/1000`, its transfer function is `H=1/(1-x²+jx)`. At resonance
`x=1`, the output is `-j` V for a 1 V source; at `x=2` it is `(-3-2j)/13` V.
Doubling L gives `H=1/(1-2x²+jx)`, so at the original resonance it becomes
`(-1-j)/2` V. Splitting L into series 0.25 H and 0.75 H coils preserves the
response while exercising an additional internal node.

The parallel example drives a parallel 1 H / 1 µF tank through 1000 Ω. Its
transfer function is `H=1/(1+j(x-1/x))`: the response leads below resonance,
equals unity at resonance, and lags above it. These closed-form functions supply
the reviewed acceptance literals independently of both native and host solvers.
Phase at exactly zero magnitude is undefined; do not interpret it as a physical
angle. No inductor DC sweep, RLC transient, transformer or general device-current
claim is made.

## Verification and recovery

A separate host solver builds complex nodal equations and uses partial-pivot
elimination to verify every native node voltage for DC/AC, including unselected
nodes. RC transient voltage is checked against V(1−exp(−t/RC)). All sample coordinates
and CSV phasor conversions are checked. A host ASCII raw parser independently reads
saved native values; a second ngspice process also reloads them. Digests, exact
netlists, runtime identity, authored/plan agreement and summary values are checked
on every offline verification.

Sample-coordinate roundoff uses the full sweep interval, including sweeps ending
at zero. DC/AC voltage tolerance is 1e-9 V + 1e-7 times expected magnitude. RC allows
2e-6 times max(|amplitude|, 1) V for integration and interpolation error. These are
numerical checks on an ideal model, not a claim about physical circuit performance.
A successful simulator exit or existing raw file alone never establishes success.

`FLOATING_CIRCUIT` requires a resistor/inductor reference path; `ILL_CONDITIONED_CIRCUIT`
requires damping or better-bounded component ratios. `INVALID_SWEEP` requires valid increasing
endpoints. `UNSUPPORTED_CIRCUIT` needs the documented RC topology or removal of an
ideal-inductor/source loop. Native failures, timeouts and cancellation retain stage logs and partial evidence. Correct the
input and run a fresh attempt; do not loosen verification to accept disagreement.

```sh
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/ngspice-rc-frequency.json \
  --ngspice /absolute/ngspice --output-directory new-frequency-response
PYTHONPATH=src python3 tools/qualify_ngspice.py \
  --config /path/to/private-config.json --output-directory new-acceptance
```
