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
  start with a letter, and have at most 32 characters. The name `gnd` is reserved
  in any letter case: ngspice lowercases the deck and rewrites a whole `gnd` token
  to ground node `0` (`inp_fix_gnd_name` in `src/frontend/inpcom.c`, unless
  `no_auto_gnd` is set), which would simulate a different circuit from the
  planned one. Planning refuses it at the exact terminal or probe with
  `INVALID_CIRCUIT`; write `0` for ground or choose another name. `gnd1`,
  `ground` and `agnd` are not rewritten and remain valid.
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
  The optional spacing field selects linear (default), decade or octave frequency grids; see electrical characterisation below. Phasors use exp(+jωt).
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
Phase/dB requirements follow the principal relative-phase and zero-response
policy in electrical characterisation below. There are no arbitrary requirement expressions or native scripts.

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
automatic component-tolerance model, parasitic model, nonlinear behaviour or nonlinear device-current
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
angle. No inductor DC sweep, RLC transient, transformer or nonlinear device-current
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
at zero. DC voltage tolerance is 1e-9 V + 1e-7 times expected magnitude. AC uses the
normalised electrical-characterisation policy below. RC allows
2e-6 times max(|amplitude|, 1) V for integration and interpolation error. These are
numerical checks on an ideal model, not a claim about physical circuit performance.
A successful simulator exit or existing raw file alone never establishes success.

`INVALID_CIRCUIT` at a `gnd` node needs `0` for ground or another node name;
nothing is normalised. `FLOATING_CIRCUIT` requires a resistor/inductor reference path; `ILL_CONDITIONED_CIRCUIT`
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

## Electrical characterisation of linear AC networks

The [filter characterisation](../examples/schemaxis/ngspice-filter-characterisation.json)
combines gain, phase, loading and resistor heating requirements on a logarithmic
frequency grid. The [resonator power study](../examples/schemaxis/ngspice-resonator-power.json)
shows passive inductor/capacitor reactive power under an explicit RMS excitation.
The [octave filter](../examples/schemaxis/ngspice-octave-filter.json) demonstrates a
partial final octave. Studio includes an editable filter-characterisation starter.

`spacing` is `linear` (default), `decade` or `octave`. With linear spacing,
`points` is the total number including endpoints. For logarithmic spacing it is
**nominal samples per decade/octave**, matching ngspice 47 `ac dec`/`ac oct`.
The actual grid must contain 3–512 samples; planning computes and checks every
frequency before running. Octaves use ratio `2**(1/points)`; a partial last octave
stops below `stop`. Shorter-than-decade spans use `10**(1/points)` and may similarly
stop below `stop`. Ngspice 47 redistributes longer decade spans over
`floor(points*log10(stop/start))` intervals to include both endpoints, so the
spacing density may be slightly larger than requested. The independent host grid
matches that documented native policy; `frequencyGrid` records actual count and
last frequency. Choose a density that resolves your engineering features.

`amplitudeConvention` is `peak` (default) or `rms`. It declares the interpretation
of all native AC voltage/current phasor magnitudes. Native ngspice AC analysis is
linear and does not choose this physical convention for you. Peak phasors use
`S = V*conj(I)/2`; RMS phasors use `S = V*conj(I)`. Average active power is `real(S)`
in watts, reactive power is `imag(S)` in var, and apparent power is `abs(S)` in VA.
Changing this convention preserves native voltages/currents and changes power by
a factor of two. Changing the source amplitude from 1 to -2 multiplies currents
by -2 and powers by four at the same convention. No factor is inferred from a
waveform or hidden in requirements. The summary retains the convention and factor.

AC `circuit.branchProbes` optionally lists up to eight existing component names,
default `[]`. Each adds current real/imaginary/magnitude/phase and active/reactive
power. These currents are **derived from verified native terminal voltages**:
`I=(Va-Vb)/R`, `I=jωC(Va-Vb)` or `I=(Va-Vb)/(jωL)`. They are not independent native
device-current observations. Current is positive from authored terminal `a` to
`b`; branch power uses the passive drop `Va-Vb`. Reversing terminals reverses
current and voltage drop while preserving absorbed power. Ideal resistor active
power is nonnegative, ideal capacitor reactive power is negative, and ideal
inductor reactive power is positive with exp(+jωt).

Optional root `portMetrics: true` additionally stores native `i(vdrive)` in both
ASCII raw data and native/reopened tables. Ngspice defines voltage-source current
into its positive terminal; input current entering the passive network is
`-i(vdrive)`. Verification compares this native observation to independently solved
network current **and** KCL reconstructed from checked native terminal voltages.
The published `$input` columns provide this native-observed input current phasor,
`Zinput=Vsource/Iinput` in ohms, and input active/reactive/apparent power. Impedance
and power are derived quantities. Input current at or below 1e-30 A, or severe cancellation below 1e-14 of the
sum of absolute branch currents, makes
input impedance undefined or ill-conditioned and planning refuses portMetrics
with `UNDEFINED_OBSERVABLE`; disable it or add a physical load. Source-current
verification requires relative error at most 1e-7 against both independently solved
current and native-voltage KCL, with no absolute-current allowance; zero observed
current is refused before impedance division. AC voltage checks use an
excitation-scaled floor of 1e-12*abs(amplitude) V plus 1e-7*abs(expected voltage);
nonzero gain/phase requirements additionally require relative voltage agreement
within 1e-7. Tiny source amplitudes cannot hide gross ratio or sign errors.

All outputs together must fit 64 columns: one frequency, four per voltage probe,
six per branch and ten for port metrics. Reduce selections on `RESOURCE_LIMIT`.
Unselected node voltages are still independently verified.

Additional AC requirement quantities are:

| Quantity | Probe selection | Units and policy |
| --- | --- | --- |
| `gain_dB` | Published voltage node | `20*log10(abs(Vprobe/Vsource))`, dB; signed bounds. |
| `phase_deg` | Published voltage node | Principal phase of **Vprobe/Vsource** in [-180,180] degrees, signed bounds. |
| `currentMagnitude_A` | Published branch or `$input` | Nonnegative amperes; `$input` requires portMetrics. |
| `activePower_W` | Published branch or `$input` | Signed absorbed average watts. |
| `reactivePower_var` | Published branch or `$input` | Signed absorbed reactive var. |
| `impedanceMagnitude_Ohm` | `$input` | Nonnegative input impedance magnitude; requires portMetrics. |

Phase acceptance uses relative transfer phase, whereas legacy node CSV
`*_phase_deg` remains the absolute native voltage phasor angle. Current CSV phase
is absolute current angle. Zero transfer magnitude (at or below 1e-30 V/V) makes
phase and dB undefined; use magnitude acceptance for that situation. Bounds do
not wrap: to assess a response crossing the ±180° branch cut, split it into
frequency windows with meaningful principal-phase bounds. Neither the phase
branch cut nor any numerical solver tolerance relaxes a user performance bound.
Sampled dB/phase/current/power/loading bounds retain signed worst conditions and
ordinary performance/reuse gates. No expressions or arbitrary native code are
accepted.

## Capability-family map

| Upstream family | Supported product scope and verification | Remaining breadth |
| --- | --- | --- |
| Linear circuit authoring | Bounded declared R/C and AC-only uncoupled L with one grounded voltage source; independent nodal checks. | Multiple/controlled/current sources, coupling, imported schematics/netlists. |
| DC | Resistor-network sweeps, capacitor open circuit, signed sampled voltage requirements. | Nonlinear bias, DC inductors, transfer/sensitivity analyses. |
| AC electrical characterisation | Linear/log frequency grids, node gain/relative phase, native input current/KCL, derived branch current/passive power and input loading; sampled performance gates. | Noise, distortion, pole-zero analysis, continuous extrema and tolerance envelopes. |
| Transient | Analytic first-order initially uncharged RC step with uniform readback. | General multi-state transient, arbitrary waveforms and initial conditions. |
| Device/modelling ecosystem | Ideal declared components only. | Semiconductors, vendor models, behavioural/mixed-signal/TCAD models and subcircuits. |
| Workflow and results | Isolated batch execution, raw reopening, independent parsing/equations, editable Studio/standalone studies, CSV/summary/netlist and verified workflow reuse. | Interactive native control language, arbitrary reflection/scripts, hardware control. |

This change completes the declared frequency-characterisation family and its
engineering checks. It does not complete the whole ngspice application. The
whole-application assessment retains a separate, explicitly bounded denominator.
