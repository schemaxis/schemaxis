# pyproj routeStations completion review — 19 October 2026

Scope: `schemaxis.pyproj/1`, operation `routeStations`. It stations an ordered WGS84
longitude/latitude route at geodesic distances, continuously across turning points, with
labelled station and leg tables, station and route GeoJSON, a host-owned summary and an
independent verification record.

The native target is exactly pyproj 3.8.0 with PROJ 9.9.0 on Python 3.12.15 (POSIX, one thread,
network disabled). Host discovery, planning and verification use only the standard library.

This note records the owner's implementation and focused qualification. It is **not** a delivery
or integration acceptance. Root still owns three things:
- the generated reference and packaged Help;
- independent review;
- final source-bound qualification registration.

## Twelve-item review

| Item | Result and evidence |
|---|---|
| registration | `adaptor.json` declares:<br>- a document route, isolated process runtime, scheduled workflow and composition;<br>- the `--pyproj` interpreter option;<br>- hooks `query`, `reusableInputs`, `retainedInputs` and `resources`.<br>`readiness.json` records unsupported decisions for native inspection, MPI, time batches, live editing, conversion and native save. There are no framework edits and no imports from other adaptors. |
| schema | All fields are declared in the closed declaration grammar, and the schema derives from the declarations. Spacing and requirement bounds are normalised to binary64. Unknown keys fail. Tests cover schema/declaration parity, required fields, defaults and immutable planning. |
| semantics | Before any native launch:<br>- explicit WGS84 and lonLat, with a sphere or latitude-first input refused;<br>- a strict CSV grammar with line locations;<br>- band and antimeridian rules;<br>- coincidence and closure ambiguity;<br>- rigorous chord and surface bounds for leg, total and row limits;<br>- the endpoint-gap domain, which is applicable to open routes only.<br>Native exact refusals are accepted only after the independent oracle reproduces them. |
| native-mapping | `Geod(ellps='WGS84').inv` per leg (and for a requested gap) in both back-azimuth modes, and `Geod.fwd` per fixed station. Chainage uses correctly rounded prefix sums. Merges are bitwise only. Waypoint rows republish the captured binary64 values. Azimuths are in [0, 360), with the back azimuth equal to the end azimuth − 180°. Runtime identity, `a`/`f` readback and API network disable/readback are checked natively and bound on the host. |
| execution | The trusted worker is copied into the run and launched as `python -I -B native-worker.py STAGE` (run-relative). It runs with POSIX resource caps, an empty run-private HOME/XDG/PROJ directory and `PROJ_NETWORK=OFF`. One total deadline covers host prechecks, both native stages and host verification, with checkpoints inside verification and before publication, and owned process-group cancellation. Captured source, configuration, implementation fingerprints, consumed-input bindings, submissions, logs, native result and readback records are retained. |
| discovery | 11 reviewed adaptor-owned cases cover all four kinds and surfaces, including negatives for `reproject`, `buffer polygon` and `UTM grid distance`. The shared capability matching check passes: complete, no failed cases. Studio Add/Help search regressions need root's shared generation and Studio suite. |
| guidance | The operation and all 14 schema addresses are reviewed (`studio_guidance.py --check`: 15 reviewed, 0 pending, 0 stale). The records give units, defaults, domain limits, the merge consequence and the meaning of numerical agreement. |
| help | `docs/pyproj.md` covers the contract, domain, chainage and the one-ulp merge example, outputs, requirements, the endpoint gap, the numerical model, saved verification and export, workflows, faults, API links and limits. Packaged Help and `docs/generated` are pending root's shared generation. |
| examples | Readiness cases with independent expectations:<br>- Winnipeg baseline and closed-loop variant, with oracle lengths and azimuths to 2τ and 1e-8°;<br>- an exact equatorial case (a·Δλ).<br>Also two planner-invalid examples (a gap on a closed route; minimum ≥ maximum), host-planned QGIS and Calc workflows, and two Studio starters with a CSV picker. |
| tests | `tests/unit/test_pyproj.py` has 25 host tests. Real-runtime acceptance is in `tools/qualify_pyproj.py`. The tests cover:<br>- grammar, CSV and precheck faults with locations;<br>- merge rules and three-state bands;<br>- oracle analytic anchors, guards and the 36-pair 1 mm transition regression;<br>- an ODE anchor;<br>- adequacy injection for every category;<br>- refusal confirmation;<br>- an oracle-backed fake runtime for the full run/verify plumbing: hostile evidence, requirement outcomes, retained inputs with the original removed or changed, a forged resume `job.json`, an exported and re-exported workflow verified after source removal with forged `result.json` and `job.json` hashes, and deadline and cancellation inside host verification.<br>`tests/studio/pyproj.browser.test.mjs` is authored but not executed (see limits); the same validation diagnostics were checked through the host authoring path. |
| qualification | `tools/qualify_pyproj.py` passed on the frozen source with the real runtime (see "Verification performed"). A follow-up made full `registry.verify` of every canonical export and re-export mandatory, with no native-only fallback, and added a targeted `--phase portability` that runs the same acceptance functions (see "Portability gate follow-up"). The receipt is not registered; root registers the final receipt. |
| maintenance | `upstream.json`: latest-stable from PyPI, with 3.8.0 absorbed for exactly this bounded scope. Other pyproj or PROJ builds are refused (`UNSUPPORTED_GEOD_RUNTIME`) and need fresh bounded acceptance. |

## Root decisions applied (implementation decision 0016)

1. **Identity and scope.** The route is a distinct `schemaxis.pyproj/1` with the exact runtime
   and explicit WGS84/lonLat, spacing and closure. The repaired bounds are unchanged: no polar,
   antimeridian, cross-track or chainage-origin support.
2. **Endpoint gap.**
   - It is computed only when requested; otherwise it is published as `null`.
   - It is refused with `ENDPOINT_GAP_OUTSIDE_DOMAIN` at `$.requirements.endpointGap_m` before
     any comparison. The refusal comes from host conclusive bounds, the native exact check, or
     saved verification (oracle cap and vertex).
   - The 1 mm local-metric regime is kept and named in `numericalModel`, and the
     `*NumericalBand_m` field names are used.
3. **Conditional numerical model.** It is published in the summary and guide: parsed binary64,
   qualified local shortest solution, rounding and libm engineering estimates, numerical
   agreement only. There is no survey, datum, measured-position, physical or regulatory claim.
4. **Exact merge.** Merging is bitwise only. The summary reports
   `presentation.adjacentRowsWithIdenticalLabels`, and the guide gives the one-ulp example
   (final interval 7.276e-12 m, repeated label `33+092.270`).
5. **Saved verification.** Retained host evidence is compared bitwise after full recomputation.
   Native commands are run-relative. Canonical `export_run` followed by normal `registry.verify`
   passes with the original sources removed. Cross-host or cross-libm verification is stated as
   unqualified.
6. **Requirements.** The host decides requirements. Unmet or indeterminate results retain
   evidence but fail as `ROUTE_REQUIREMENT_NOT_MET` or `ROUTE_REQUIREMENT_INDETERMINATE`, saved
   verification reproduces the fault, and an unmet producer blocks its consumer. The native
   output carries no decision.
7. **Executable adequacy.** Each evaluation must resolve to τ/10 at its own scale:
   - legs: τ(leg)/10;
   - station forwards: direct residual + rounding estimate + propagated leg inverse error,
     against τ(leg)/10;
   - consecutive inverses: τ(step)/10;
   - the requested gap: τ(gap)/10.
   If any fails, the whole run fails with `VERIFICATION_INDETERMINATE`, even without
   requirements. Root's two reproduced omissions (a consecutive inverse at 5× its budget, and a
   1 m station direct residual) are both now rejected, in unit tests and on real native runs.
8. **Provenance and guards.**
   - **Bindings:** source, parsed waypoints, plan, native configuration, native files, runtime
     observation, interpreter-path digest, implementation and summary.
   - **Strict guards:** readback, JSON and arithmetic guards; unstructured native failures map
     to `NATIVE_EXECUTION_FAILED`.
   - **Inputs:** `retainedInputs` authenticates the retained capture; current-source changes
     still invalidate reuse.
   - **Deadline:** one whole-run deadline, with no per-stage reset.

## Verification performed (actual native executions, frozen source)

| Group | Outcome |
|---|---|
| Shared kit | 3 native cases (baseline, variant, equator) with 33 independent checks and 54 integrity mutations; native timeout and pre-launch cancel. |
| Endpoint gap | Review R1 (13,454 km) and the near-antipodal R2 refused on the host. The same R1 route without the requirement is accepted with gap `null`. A regional 36.34 m gap is met. Gaps of 5000 km − 0.1 m and − 1 mm are accepted; + 0.1 m and + 1 mm are refused natively. A band exit is refused natively. A 38 km gap across 180° is refused on the host, while the 13,299 km route itself is accepted. A one-ulp gap is met for a 1 m bound and indeterminate for a 0 bound; 5 mm is met; 0.5 µm is indeterminate for a 0.1 µm bound and met for 10 µm. |
| Requirements | met, unmet (`$.requirements.totalLength_m`), indeterminate at the bound, and a met range. |
| Merge | Exact merge (kind 3, interval 0); one ulp below (two rows, one repeated label, 7.276e-12 m); one ulp above. |
| Analytic and geography | Exact equator, meridian against quadrature, and a spherical discriminator (3.7e7 τ). Southern/eastern, east of 179° E, a route to 74.70° N, centimetre legs, and 9,977 rows. |
| Refusals | Host: latitude 80°, an antimeridian leg, coincidence, closure ambiguity, a latitude-first header, a capture over 1 MiB (no native launch). Native, each confirmed by the oracle: leg too long, row limit, total too long, latitude excursion, leg too short. |
| Adequacy injection | 1 m station residual; consecutive, leg and gap inverses at 5×; an unresolved rounding model. Each fails the run with `VERIFICATION_INDETERMINATE`. |
| Worker mutants | Sphere, GRS80 on continental legs (ratio 6.2), constant station azimuth, lon/lat-linear stations and six-decimal stations: all rejected by the oracle. A benign computation from the leg end is accepted. |
| Hostile export mutants (hashes refreshed) | Summary or decision flip, a foreign host record, station shifts of 1e-8° and 1e-10°, a truthy readback, a runtime change, absolute or non-isolated commands, changed worker bytes, a written private home and a rehashed capture: all rejected. A refreshed-only control is accepted. That run's refresh helper also rebased the recorded artifact locations; the review follow-up below corrected this and reran the cases with locations preserved. |
| Workflow and study | Unchanged input is reused. After a source change, a forged resume `job.json` is not reused, because the retained capture differs. An unmet producer blocks its QGIS consumer (no consumer launched). The QGIS and Calc handoffs are host-planned. A two-state spacing study is verified, and its aggregated `retainedInputs` is checked. |
| Export | Canonical export of the baseline and variant, original CSVs removed, full `registry.verify` passes. Reuse after removal gives `INVALID_ROUTE_SOURCE`. |
| CLI | `schemaxis run … --pyproj` and `schemaxis verify` exit 0. |
| Lifecycle | In-flight native timeout and cancel (owned child gone). A deadline set to the measured native time + 0.4 s expires inside host verification of 9,977 rows; `result.json` is failed and no summary is published. |
| Consumers | Host contracts only: Calc tables, a Gnuplot chainage profile, QGIS readVector plan and inputs. No native consumer was run. |

112 native pyproj processes were launched (each PID recorded) and none remained afterwards.

## Portability gate follow-up

This follow-up changed only the acceptance tool, one host test and the documentation; the
adaptor source is byte-identical. It closes an acceptance-gate gap. Earlier, a canonical export
refused by the shared layer could still produce a top-level `verified: true`, because only the
native layer and the original run were asserted. The earlier full run had in fact passed full
verification. Now every export and re-export must pass full `registry.verify`, and any refusal
fails the tool.

The targeted portability phase was run with the real runtime (18 native processes, none
remaining) and covered:
- **Single runs:** the baseline and variant exported and re-exported, verified with the
  originals removed.
- **Workflow and study:** a scheduled workflow of two independent pyproj routes and a two-state
  common study, each verified in its original, exported and re-exported copies, both after
  physical source removal and after a source change.
- **Forged hashes:** forging both `result.json` and `job.json` input hashes fails saved
  verification on the original and on a re-export, and resume makes fresh attempts with the
  same source path, effective document and handoffs.
- **Negative control:** a simulated shared refusal of an exported copy now fails the tool.

No native cross-application consumer was run in that owner follow-up. The full mathematics
gate was not repeated.

## Later integration probe: QGIS consumer

A separate supervisor probe executed the shipped pyproj-to-QGIS workflow with pyproj 3.8.0,
PROJ 9.9.0 and QGIS 4.2.3. Both jobs completed and the QGIS project was reopened. The captured
producer GeoJSON was byte-identical to the published route. Independent decoding of the actual
GeoPackage found two EPSG:4326 LineStrings whose 44 coordinate pairs exactly matched the
producer GeoJSON. All four native processes exited. This is one vector handoff fixture;
it does not qualify Calc, raster or point-cloud consumers, GUI editing, or unsampled geodesic
geometry. It also predates final generated Help and qualification registration.

## Review follow-up (F1–F4)

The independent implementation review found no blocking adaptor defect and confirmed that all
eight implementation decisions are applied. It raised four owner items, resolved here without
any change to the adaptor modules, manifests or numerical semantics:

- **F1 (qualifier helper):** the hostile-evidence `refresh()` helper in `tools/qualify_pyproj.py`
  and in the unit test used to replace the receipt's recorded artifact locations with the mutant
  copy's own paths. It now refreshes digests only:
  - recorded artifact file strings, kinds and order, the receipt executable, native submissions
    and the publication manifest's first recorded origin are preserved;
  - every hostile case asserts this before verification;
  - mutants are canonical `export_run` copies;
  - each of the 12 qualifier cases must fail with its exact intended code and message;
  - two valid controls (an unmodified export, and an export with digests refreshed and locations
    preserved) must verify.

  Host-only rerun on canonical copies of the retained baseline and variant runs (no native
  process): all 12 cases were rejected for their intended reasons, both controls verified, and
  the recorded locations still named the original run. A negative control showed that the old
  rebasing helper is now rejected by the gate itself. The unit test has the same structure, with
  11 cases and two controls; 25/25 host tests pass.
- **F2 (`retainedInputs`):** the guide now states that the hook is a provenance lookup used after
  ordinary native verification, not a standalone authenticator.
- **F3 (`executablePathDigest`):** the guide now states that it hashes the interpreter path string
  (provenance only). Runtime observation and trusted-worker checks are bounded evidence, not
  cryptographic proof.
- **F4 (implementation binding):** the guide now states that any edit to the five bound modules,
  including comments, makes older runs fail saved verification, so they must be rerun.

## Limits and pending work

- **Accuracy claims.** Numerical agreement only, with conditional engineering bands; no
  certified intervals. Saved verification is qualified on the producing host and libm only.
- **Runtime and domain.** Exact runtime only, within the domain above.
- **Consumers.** The later QGIS vector handoff above has native evidence. Other consumers
  remain host-contract only, and GeoJSON lines are not geodesic.
- **Browser test.** The owner authored it but did not execute it. The independent review records
  that root's Studio run executed it; final Studio and browser gates remain root's.
- **Review history:** design review and design repair; independent implementation review (no
  blocking adaptor defect, F1–F4 resolved in the follow-up above). The overall delivery is not
  accepted.
- **Pending gates (no acceptance or credit yet):**
  - root validation of the F1–F4 follow-up;
  - regenerate `docs/generated` and packaged Help, then run the `--check` commands;
  - run the Studio search and browser regressions;
  - full integration suites;
  - a final source-current qualification and receipt registration by root.
- **Hook review status:** the shared `run_paths` / `retainedInputs` logic and this adaptor's hook
  have both been reviewed; the hook's role is documented as a lookup used after verification
  (F2).

Reproduce with:

```sh
PYTHONPATH=src python3 -m unittest tests.unit.test_pyproj -q
PYTHONPATH=src python3 tools/studio_guidance.py --app pyproj --check
PYTHONPATH=src python3 tools/qualify_pyproj.py --pyproj /absolute/pyproj-env/bin/python --output-directory fresh-evidence
PYTHONPATH=src python3 tools/qualify_pyproj.py --phase portability --pyproj /absolute/pyproj-env/bin/python --output-directory fresh-portability-evidence
PYTHONPATH=src python3 tools/qualify_pyproj.py --phase hostile --baseline-run verified-baseline-run --variant-run verified-variant-run --output-directory fresh-hostile-evidence
```
