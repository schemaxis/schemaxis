# SymPy `isolateRealRoots` completion review (2026-10-24)

Scope: the new `schemaxis.sympy/1` route, operation `isolateRealRoots`: exact real-root isolation of one
univariate polynomial with literal rational coefficients (degree 1-12), by isolated SymPy 1.14.0
`sympy.intervals([poly], strict=True)`, certified by an independent standard-library host verifier (Yun square-free
decomposition and Sturm sequences in `Fraction`). Serial only; no MPI. Reviewed by the implementing worker;
domain and editorial review by a person is still outstanding (see Unresolved).

Native runtime observed: SymPy 1.14.0, mpmath 1.3.0, Python 3.14.4, Linux, in a venv created with
`pip install sympy==1.14.0` from PyPI. The host interpreter never imports SymPy.

## Checklist

| ID | Result |
| --- | --- |
| registration | `adaptor.json` route `schemaxis.sympy/1`, runtime family `1.14.0`, workflow/scheduled true, compose false, `--sympy` option and `SCHEMAXIS_SYMPY`. MPI, native inspection, time batches, live editing, conversion, native save and composition are explicit `unsupported` decisions with reasons. |
| schema | Typed declaration `coefficients` (2-13 strings) and `maximumIntervalWidth` (default `1/1000`); authored JSON schema generated from it. Literal grammar, zero leading coefficient and width range are semantic faults with located paths. |
| semantics | Closed literal grammar (sign, <=40 digits, optional /denominator); expressions, decimals, exponents, names, spaces, non-ASCII digits refused as data and never evaluated; width within [1e-30, 1]; deterministic immutable plans with reduced fractions. |
| native-mapping | `sympy.intervals([Poly(list of Rational, Symbol x, domain=QQ)], eps=Rational, strict=True)`, `all=False`, `sqf=False`; SymPy 1.14.0 enforced, endpoints must be `sympy.Rational`; separate readback process. `Poly.count_roots` and `is_sqf` are diagnostics only. API citations are in `readiness.json` `development.api` and `docs/sympy.md`. |
| execution | Isolated `-I -B` worker with address space, CPU and file-size caps, one total deadline, retained submissions/stdout/stderr/fault records, run-relative worker, consumed-input digest bindings, host-owned `roots-verification.json`, `verify` recomputes everything. |
| discovery | `capabilities.py`, `search-cases.json` (synonym, multiword, ambiguous and two negative cases). Native-free discovery/planning tested in a fresh interpreter. |
| guidance | `guidance.json`: operation plus all 6 route field addresses, status `reviewed` (AI-authored, see Unresolved), sources into `docs/sympy.md`. |
| help | `docs/sympy.md` with fault table and API links. Packaged Help, generated reference and the workflow route-choice guidance are shared outputs left to the master (see report). |
| examples | Baseline `sympy-sqrt2`, variant `sympy-repeated-roots` (exact roots with multiplicity), `sympy-no-real-roots`, `sympy-rational-roots`, workflow, and two schema-valid invalid cases. Three Studio templates and two snippets. |
| tests | `tests/unit/test_sympy.py` (19 host tests, no SymPy); `tools/qualify_sympy.py` (native). |
| qualification | See below. Receipt registered only where stated in the worker report. |
| maintenance | `upstream.json`: latest-stable, GitHub release source, absorbed 1.14.0 after the acceptance below. |

## Observed checks (this session)

- `python3 -m unittest tests.unit.test_sympy`: 19 tests passed.
- `tools/qualify_sympy.py --sympy <venv python>`: passed. Conformance kit (baseline, variant, native timeout, pre-launch
  cancellation); 17 constructed-root cases; 6 refused inputs; unsupported-runtime refusal using a launcher whose `sympy`
  reports 1.13.3; 32 hostile saved-evidence mutants rejected; CLI plan/run/verify of four examples with tamper and forged-table
  rejection through `schemaxis verify`; workflow with identical-resume reuse and `RESUME_MISMATCH` for an edited workflow;
  in-flight timeout and cancellation with the owned child gone.
- Constructed cases cover exact point roots (linear, x^7, mixed multiplicities, rational fractions, Wilkinson degree 12,
  quadruple roots), roots 1e-20 apart, irrational roots at width 1e-30, 40-digit coefficients, no real roots, and a repeated root.
- The 12 forged-table mutants carry a self-consistent table, summary and every refreshed hash; only the Yun/Sturm
  certification rejects them (missing, phantom, wrong multiplicity, off-root point, interval missing a root, two roots in
  one interval, too wide, touching, unordered, half of an irrational pair, irrational root claimed exact).

## Limits and unresolved work

- Coefficient and degree bounds are the contract, not exhaustive coverage; no larger polynomial, Windows or macOS, or other
  SymPy release has been run. The system `/usr/bin/python3` was observed to report SymPy 1.14.0 as well; it was not used.
- Serial only. No claim about numerical conditioning of problems that produced the coefficients.
- Guidance and search phrases are AI-authored and await domain/editorial review.
- Packaged Help, generated references and workflow route-choice guidance still need regeneration by the master.

## Independent review and supervisor corrections

Independent review accepted the exact host certificate and identified touching
native intervals near an exact rational root. Both reported cases were reproduced
through the actual route before repair. The native worker now uses the public
list-isolation API with one polynomial and `strict=True`, checks its multiplicity
map, and retains the unchanged host rule for disjoint closed intervals. Three
real route run/verify regressions pass: irrational roots near zero at the default
width, the same configuration at width one, and irrational neighbours of root one.
The qualification recipe now retains all three alongside its original 17 cases.

A separate standard-library check certified 62 analytically constructed polynomials
and rejected 120 forged lists; no SymPy import was used for those host decisions.
Official SymPy 1.14.0 release and polynomial API links were checked during integration.
