# GetDP bounded-product completion — 3 November 2026

Scope: new `schemaxis.getdp/1` document route, `steadyHeat` and `steadyCurrent`.
This completes the declared layered constant-area steady scalar-conduction
product. It does not complete the GetDP application: the capability-family map
in [the guide](../docs/getdp.md#capability-family-map-and-boundaries) distinguishes
supported workflows from transient, nonlinear, harmonic, vector electromagnetic,
multiphysics, general geometry, interactive authoring and MPI exclusions.

Public primary sources reviewed on 3 November 2026: [upstream](https://getdp.info/)
identifies stable 3.5.0 (13 May 2022) and a separate development snapshot; the
[3.5.0 manual](https://getdp.info/doc/texinfo/getdp.html) documents Form0/BF_Node,
FemEquation, volume Jacobians for one-dimensional domains, Gauss line/point
integration, Resolution, PostProcessing, Gmsh scalar/vector line records and
native degree-of-freedom `.pre` / static solution `.res` formats. Native binaries
stay external under their upstream licence. The authored JSON cannot supply
arbitrary formulations, command arguments, includes or scripts.

| Checklist | Review / evidence |
| --- | --- |
| registration | Manifest-only registry discovery, document route, stable runtime family, serial process execution, no app-name framework branch or cross-adaptor import. Workflow/composition/source/property/reuse supported; other optional features explicitly excluded. |
| schema | Typed closed layer, boundary, area and sampled-limit records; complete literal JSON schema. Required/optional fields, defaults, finite bounds and semantic boundary alternatives covered by host/schema conformance. No node ports because this is a document route. |
| semantics | Unique layers, 512 total cells, bounded stiffness contrast, thermal kelvin including exact interior quadratic extrema, anchored field, electrical convection exclusion, ordered limits and boundary key exclusivity validated before native launch. Unhashable operations return structured faults. |
| native-mapping | Deterministic generated Gmsh MSH 2.2 line mesh and GetDP `.pro`; no Gmsh runtime. Scalar diffusion weak form maps positive source, outward flux and thermal Robin conditions; native fixed-dof/equation mapping and actual fields are independently read back. |
| execution | One deadline, shared process-tree cancellation, failed evidence and logs retained. Fresh native process uses retained `reopen.pro` with `-name model` to reload `.pre/.res`. Offline verifier rebuilds sources, parses native fields/raw dofs and exact continuum, checks interface/global balance and table/summary membership. |
| discovery | Curated application/operation intent and four reviewed search kinds (Fourier synonym, heat-loss phrase, ambiguous conductivity, excluded superconducting hysteresis) cover capabilities, selection, Add and Help. |
| guidance | 27 reviewed operation/schema addresses, zero pending/stale, explicit defaults and operation-dependent SI units, flux signs, source meaning and sampled-limit scope. |
| help | Local guide explains physical model, limitations, field meanings, examples, exact verifier, meaningful faults and public API sources. Root integration generates shared reference and packaged Help so no concurrent shared-file edit is included here. |
| examples | Five standalone/Studio starters, changed conductivity native case, invalid fixtures, explicit three-conductivity finite study and optional field-to-Calc workbook handoff. Inline source/property edits retain the same durable draft; stale plans are rejected. |
| tests | Focused host tests cover analytic resistance/source/convection/current, immutability, structure/resource/semantic faults, literal limits, below-zero interior Kelvin, corrupted raw markers and conservation. Native qualification independently checks six literal kit cases and all shared tamper/lifecycle probes; adversarial refreshed hashes do not conceal native result/field/mesh or missing raw-section corruption. |
| qualification | Stable GetDP 3.5.0 native cases ran in fresh directories, with no skipped native success. Source-bound receipt names exact cases and runtime; integration changes require root rerun/record. Serial only; prelaunch cancellation does not establish an additional independent in-flight cancellation experiment. |
| maintenance | Latest-stable upstream pattern, stable release/manual URLs, bounded acceptance recipe and scoped assessment supplied. Whole-application coverage and workflow abstraction are editorial estimates, independent from qualification. |

Native kit literal expectations derive independently from Fourier/Ohm resistance
`sum(L/k)`, the exact source parabola and outward-flux/convection balance:
5000 W baseline, 2500 W changed conductivity, 5000/11 W composite wall, 312.5 K
internally heated maximum, 320 K imposed-flux/convection maximum and 5000 A DC
current. The additional two-convection case is 5000/3 W. No expectation is copied
from a producer observation. Limits use the literal sign of the measured margin,
without silently applying physics-comparison tolerances.

Retained local native evidence is under `evidence/getdp-native-final2`;
The programme resource envelope records commands and process results separately.
The final integration owner reruns shared generated documentation, full host and
Studio search tests, admission, native conformance and qualification recording.

Executed validation: 11 focused host tests and reusable host conformance passed.
The final native launcher exercises all six kit cases, additional boundary/sign
cases, literal unmet limit, refreshed-digest corruption, raw missing-section
faults, deterministic public-agent/terminal same-draft reuse, ordinary workflow
resume and a three-conductivity native finite study. An exploratory optional
Calc handoff reached the external LibreOffice conversion but did not complete
within its deadline; no Calc handoff qualification is claimed from it. Its failed
evidence remains under `evidence/getdp-native-2026-11-03-2`. The standalone
optional handoff remains an editable host-planned example.

Final native launcher completed successfully: six native kit cases, all shared
negative/lifecycle probes, six additional adversarial checks, 29 public transport
requests (28,346 response bytes), same-draft 5000 W → 2500 W edit, stale/unanchored
rejections, complete workflow reuse and three independently verified study states.
No skips occurred in the GetDP native acceptance. The optional external Calc
consumer is excluded from this completed qualification scope.
