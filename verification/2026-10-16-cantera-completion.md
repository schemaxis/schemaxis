# Cantera reactor-history completion review (2026-10-16)

**Architect closeout:** shared reference/Help generation, catalogue and workflow
guidance integration, admission checks, the full host suite and final native
qualification are complete. A fresh receipt is registered against the final
source. See the [integration verification](2026-10-16-architecture-integration.md).
The implementation-agent handoff below records its earlier state; its pending
central-integration items are now resolved. Application scope limits remain.

Scope: route `schemaxis.cantera/1` gains the operation `reactorHistory`, one closed,
adiabatic, homogeneous ideal-gas reactor (`IdealGasConstPressureReactor` or
`IdealGasReactor` in a `ReactorNet`) for the existing ten-species, 29-reaction
`h2o2.yaml` `ohmech` mechanism. The `gas`, `thermoSweep` and `equilibrate` operations are
unchanged apart from stricter receipt-table checks. Their guidance was edited only
where it named the available operations. This review does not re-review them.

## Upstream basis

- Latest stable upstream checked on 2026-10-16: Cantera v3.2.0 (GitHub
  `releases/latest`, published 2025-11-18; PyPI latest 3.2.0). `absorbedVersion`
  stays at 3.2.0.
- The v3.2.0 `data/h2o2.yaml` download and the installed wheel's copy have the same
  SHA256 as the pinned mechanism. Its 29 reaction records are copied
  unchanged into `kinetics.json` (upstream units cm/mol/s/cal, BSD licence already
  retained). Stoichiometry is parsed from each equation and cross-checked by a test.
- Public API: Cantera 3.2 `zerodim` (`IdealGasConstPressureReactor`,
  `IdealGasReactor`, `ReactorNet.rtol/atol/max_steps/advance/step`). The reactor
  reference pages give the governing equations. With no walls, flow or heat transfer
  they reduce to m·cp·dT/dt = −Σ h_k ṁ_k,gen (constant pressure) and
  m·cv·dT/dt = −Σ u_k ṁ_k,gen (constant volume). `clone=True` is passed
  explicitly because the 3.2 default is deprecated.

## Ignition-delay criterion

`ignitionTemperatureRise` (default 400 K) defines the reported delay: the first time
T ≥ T0 + rise, with linear interpolation in time between consecutive accepted
integrator steps. The worker gets these steps from a second `step()` pass with the
same settings, capped at 200000 steps. A crossing after the last sample time is
`null`. The host applies the same rule to its own trajectory. Other definitions
(peak OH, peak dT/dt) are not offered.

## Independent verification evidence

- Rates: host mass-action, three-body, Troe falloff and NASA7 reverse rates
  agree with Cantera `net_production_rates` within 2.1e-14 of the gross rate. The
  test used 300 random states (300–3500 K, 1e3–1e7 Pa, including zero species).
- Integrator: Shampine four-stage L-stable Rosenbrock. Fixed-step error ratios
  are about 15–16 per halving on linear-stiff and nonlinear tests (fourth order).
- Native and host trajectories, stoichiometric H2/air at 1000 K, 1 atm:

  | Native settings | Ignition-delay difference | Notes |
  | --- | --- | --- |
  | rtol 1e-9, atol 1e-15 (default) | 3.8e-6 relative | Sampled T within 0.1 K at the steep front and 1e-3 K elsewhere. |
  | rtol 1e-8, atol 1e-12 (loosest allowed) | ≤ 1.2e-3 | |
  | rtol 1e-6 (rejected at planning) | −0.87% (constant P), −0.94% (constant V) | Native conservation drift also fails verification. |

  This is why authored tolerances are limited to rtol ≤ 1e-8 and atol ≤ 1e-12.
- Energy: the largest NASA7 range-boundary enthalpy jump at 1000 K is 0.186 J/kg
  (N2). A 1000 K start shows a constant 0.14 J/kg offset that does not depend on the
  tolerances. The energy tolerance adds the jump only when the sampled temperatures
  straddle a boundary.
- Fractions: across 15 native runs, including the loosest and rejected tolerance
  settings, the minimum mole and mass fractions were exactly 0. The strict bound
  0 ≤ X, Y ≤ 1+1e-12 is retained.
- Reference cases: constant-pressure 20 ms states equal the existing HP-equilibrium
  route from the same initial states (2692.8133 vs 2692.8134 K from 1000 K;
  2763.3197 K for both from 1200 K). The final chemical-potential residual is
  below 3e-14 RT. Pure argon stays at 1500 K and 101325 Pa (analytic h and cp).
- Temperature sensitivity, constant pressure, 400 K rise: 900 K 0.237 s; 925 K
  0.065 s; 950 K 8.95 ms; 1000 K 0.311 ms; 1100 K 0.089 ms; 850 K and below
  do not ignite within 1 s.
- Host verification cost is about 2 s per reactor plan, cached per plan. Bounded
  extremes take at most 2.5 s: 100 samples to 1 s at 800 K/10 MPa, 2000 K/1000 Pa,
  900 K and 300 K. The host integrator stops after 50000 steps.

## Receipt falsification

The verifier rejects all of the following with `VERIFICATION_FAILED`, even when the
digest manifest is refreshed to match the change:

- reopened rows that are empty, short or extra;
- a boolean or non-finite cell in a row, rate, mass, volume or step record;
- missing, empty or short rate vectors;
- a thermodynamically consistent but time-shifted state (rejected by the
  kinetics window check);
- step times scaled by 1.02 (rejected by the ignition check);
- a 5% change to the H + O2 rate, which also moves the host delay by more than 1%;
- a solver-readback mismatch, a mass change of 1e-6, a changed volume, or a rate
  change of 0.1%.

An architect reviewer reported two holes, which are fixed: empty reopened rows and
a boolean rate both passed before the fix. Every published column perturbation is
also rejected.

## Commands and results (this session)

- `PYTHONPATH=src python3 -m unittest tests.unit.test_cantera_reactor tests.unit.test_cantera_admission`: 29 tests OK.
- `schemaxis adaptor conform schemaxis.cantera/1`: host verified, 10 cases plus
  the invalid `unordered-reactor-times` example (`INVALID_TIMES`).
- `schemaxis adaptor conform schemaxis.cantera/1 --native`: verified on the
  final tree. All 10 cases passed, plus integrity probes, the native-runner timeout
  and pre-launch cancellation. The receipt stays in the evidence folder and is not
  recorded, because concurrent shared changes alter the source digest.
- `tools/qualify_cantera.py`: verified on the final tree. It covers:
  - the thermo Calc handoff at two pressures;
  - constant-pressure and constant-volume reactor Calc handoffs (time column,
    held pressure or density, full reuse on resume);
  - the changed-mechanism probe;
  - all 10 cases through the public agent tools (246 requests);
  - the human console edit, with stale-plan rejection.

  Calc ran from a private copy of an existing runtime. An earlier run from the
  shared historical copy changed two directory timestamps there through transient
  LibreOffice lock entries; directory contents were unchanged. This is reported to
  the architect.
- Capability search cases: complete (4 kinds, 4 surfaces, no failures).
  `search-acceptance.test.mjs` passes every Cantera Studio assertion except the
  Help topic for `reactorHistory`, which needs shared regeneration.
- `tools/studio_guidance.py --app cantera --check`: 38 reviewed, 13 reference,
  0 pending, 0 stale.

## Checklist

| ID | Result |
| --- | --- |
| registration | `reactorHistory` declared (native `cantera.ReactorNet`). Manifest execution text updated; `equilibrium` moved from the manifest's keywords to the application and operation metadata. Unsupported features have stated reasons in `completion.notApplicable`. |
| schema | Closed typed options with bounds and defaults; literal schema `oneOf/3`. `INVALID_TIMES` is located at `options.times`. |
| semantics | Strictly increasing times; tolerance bounds justified by measurement; maxSteps bound. Out-of-range temperatures fail with `UNSUPPORTED_STATE` in the worker and again in verification. |
| native-mapping | Reactor class, rtol, atol, max_steps, energy and chemistry flags are read back before integration; initial mass/volume and per-sample mass, volume and rates are retained. |
| execution | Existing isolated runner, deadline and cancellation. Fresh-process reopen recomputes properties and rates from the saved CSV. |
| discovery | Operation keywords and nine reviewed cases, including ambiguous `adiabatic` and negative `flame speed`/`methane`. |
| guidance | All new addresses reviewed. Gas, document, nodes, pressure, composition and output text updated for the third operation. Stale source line ranges remapped by content or replaced with symbol citations. |
| help | `docs/cantera.md#reactor-time-histories`. Generated reference and packaged Help are **pending shared regeneration**. |
| examples | `cantera-reactor.json`, Studio `reactor-ignition` template and `reactor-history` snippet, invalid `unordered-reactor-times`, and four native cases (constant P, constant V, hotter start, inert argon) with literal expectations from host NASA7 or the host integration. |
| tests | `test_cantera_reactor.py` (planning, kinetics, integrator order, conservation, falsification and offline receipts) plus the recorded native fixture `tests/fixtures/cantera-reactor-native.json`. |
| qualification | Native acceptance passed on the current tree. Recording is **deferred** until shared sources are final; the registered receipt is stale. |
| maintenance | `upstream.json` scope and acceptance updated; absorbed version unchanged (3.2.0). Requalify if `h2o2.yaml` bytes change. |

## Remaining gaps

The model has no heat loss, walls, inflow, flames, transport or other mechanisms.
The ignition delay is a model quantity, not an experimental value. Samples are
not interpolated between rows. The host verifier checks numerical agreement with
the stated mechanism, not the mechanism itself. MPI is not supported, and the
serial run does not qualify it. Native acceptance used a single Linux runtime,
Cantera 3.2.0. Shared reference and Help regeneration, and receipt recording, are
left to the integrating architect.
