# ngspice named sampled performance acceptance — 2026-10-10

The ngspice adaptor now accepts optional named requirements on declared sampled
DC/RC signed voltage or AC phasor magnitude and gain magnitude. Requirements carry
explicit probe, axis units, inclusive window and lower/upper bounds. Actual native
values supply observed extrema, signed margins and worst sample coordinates;
negative voltages retain their sign. Eight ULPs at the largest interval/window
coordinate magnitude handle mathematically equal sample endpoints only, without
relaxing performance bounds. Existing independent nodal equations, RC analytic
response, native raw reopen and independent ASCII parser remain prerequisites.
Invalid intent, native/physics faults and physically valid unmet performance have
distinct faults. An unmet requirement retains inspection evidence and blocks
successful publication, downstream execution and reuse. Offline recomputation
rejects forged assessments even after ordinary publication hashes are refreshed.
Public operation discovery now handles finite analytic component studies.

## Runtime and bounded evidence

Observed ngspice **47**, private executable
`evidence/ngspice-runtime/install/bin/ngspice`. The official
[release news](https://ngspice.sourceforge.io/news.html) identifies release 47,
11 August 2026, as current stable; absorbed version remains 47. Accepted Calc
handoffs used `evidence/calc-latest/runtime/opt/libreoffice26.8/program/soffice`.
No user PATH changes, native imports in host planning or arbitrary netlists.

- `evidence/adaptor-growth-20261010/ngspice-performance-final-domain/qualification.json`:
  nominal DC/AC/RC acceptance; explicit resistor/capacitor changes that pass or
  miss requirements; negative-source DC lower bounds and absolute-source AC gain;
  slow RC settling; a three-visit capacitance study whose third visit is unmet;
  forged-summary rejection; accepted producer/Calc handoff reuse and zero consumer
  attempts across two fresh unmet producer attempts.
- `evidence/adaptor-growth-20261010/ngspice-performance-final-native/qualification.json`:
  source-bound native kit, 19 analytic baseline/variant cases, timeout/cancellation
  lifecycle probes and host admission. Four new cases independently check literal
  divider voltage, RC cutoff gain, a -2% capacitance variant and three-to-five time
  constant settling observations.
- `evidence/adaptor-growth-20261010/ngspice-performance-final/report.json`:
  19 public draft/property authoring cases, four DC/RLC Calc handoff/reuse scenarios,
  raw-data tamper rejection, shared console refinement and stale-plan rejection.
- Host regression suite: 25 tests in `test_ngspice_admission.py` and
  `test_ngspice_performance.py` pass. All 202 schema fields and three operations
  have reference guidance; selected-route host conformance passes.

These are finite declared sample/component values. They do not prove continuous
frequency/time extrema, exact settling crossings, every manufacturing-tolerance
value or physical hardware behaviour. Phase acceptance and general nonlinear or
transient circuits remain unsupported. Narrow resonances may fall between samples.
