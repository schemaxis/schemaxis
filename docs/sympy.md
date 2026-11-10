# SymPy exact real-root isolation

Use `schemaxis.sympy/1` with `operation: isolateRealRoots` to find **every real root**
of one univariate polynomial whose coefficients are exact rational numbers. The route
asks isolated SymPy for isolating intervals with `sympy.intervals([poly], strict=True)`, and publishes them as
disjoint closed rational intervals, each holding exactly one distinct root, together
with the root's multiplicity. A rational root appears as an exact point interval
(`lower == upper`). The host then re-proves the result from the coefficients alone, so
the answer is accepted because it was independently certified, not because SymPy
returned it.

This is one bounded capability, not a computer algebra system. There is no expression
parser, no symbolic simplification, integration, equation solving, factorization
output, complex-root location or numerical approximation of roots beyond the interval
width you request.

## Start with the square root of two

[sympy-sqrt2.json](../examples/schemaxis/sympy-sqrt2.json) isolates the roots of
`x² − 2`:

```json
{
  "version": "schemaxis.sympy/1",
  "operation": "isolateRealRoots",
  "coefficients": ["1", "0", "-2"],
  "maximumIntervalWidth": "1/1000"
}
```

```sh
schemaxis plan examples/schemaxis/sympy-sqrt2.json
schemaxis run examples/schemaxis/sympy-sqrt2.json --output-directory runs/sqrt2 --sympy /absolute/isolated/python
schemaxis verify runs/sqrt2
```

The run publishes `real-roots.csv` (the table), `roots-summary.json` (native evidence)
and `roots-verification.json` (the host certificate). With SymPy 1.14.0 the table is
the two intervals `[-58/41, -41/29]` and `[41/29, 58/41]`, each 1/1189 wide. Because √2
is irrational, no point interval could be certified; the interval endpoints are
algorithm-dependent, so only the counts are fixed expectations.

More examples, all planned and (for the first four) executed by the qualification tool:

| Example | Polynomial and what it shows |
| --- | --- |
| [sympy-repeated-roots.json](../examples/schemaxis/sympy-repeated-roots.json) | `(x−1)³(x+2)²(x²+1)`: exact point roots −2 (multiplicity 2) and 1 (multiplicity 3) and a complex pair |
| [sympy-no-real-roots.json](../examples/schemaxis/sympy-no-real-roots.json) | `x⁴/2 + 3`: no real roots; an empty table is a certified answer |
| [sympy-rational-roots.json](../examples/schemaxis/sympy-rational-roots.json) | `6x³+17x²−31x−12`: exact roots −4, −1/3 and 3/2 |
| [sympy-two-polynomials-workflow.json](../examples/schemaxis/sympy-two-polynomials-workflow.json) | two independent runs in one verified workflow, with resume reuse |
| [sympy-expression-invalid.json](../examples/schemaxis/sympy-expression-invalid.json) | `"x**2"` is refused as data (`SYMPY_INVALID_COEFFICIENT`) |
| [sympy-zero-leading-invalid.json](../examples/schemaxis/sympy-zero-leading-invalid.json) | a zero leading coefficient is refused (`SYMPY_ZERO_LEADING_COEFFICIENT`) |

## Coefficients and width

`coefficients` lists the coefficients from the **highest power down**. The list length
is the degree plus one, so degree 1 to 12 needs 2 to 13 entries. The first entry
multiplies `x^degree` and must be nonzero; zero coefficients inside the polynomial are
written out (`x³ − x` is `["1", "0", "-1", "0"]`).

Each entry is a string: an optional sign, 1 to 40 ASCII digits and an optional `/` with
1 to 40 digits and a nonzero value. `"-3/2"`, `"7"` and `"+4/6"` are accepted;
the plan shows them reduced (`"-3/2"`, `"7"`, `"2/3"`). These are refused with
`SYMPY_INVALID_COEFFICIENT` and a located `$.coefficients[i]`:

- decimals (`0.5`), exponents (`1e3`), `nan`, hexadecimal and digit separators;
- names and calls (`x`, `pi`, `sqrt(2)`), arithmetic (`1+1`), spaces and newlines;
- non-ASCII digits, more than 40 digits, a zero denominator.

Nothing is evaluated: the host reads each entry with a closed grammar, and the worker
constructs only `sympy.Rational` values and a coefficient list for `sympy.Poly`. No
string is passed to SymPy's parser or to `eval`.

`maximumIntervalWidth` (default `1/1000`) is the widest interval you accept, as an
exact fraction in `[1/10^30, 1]`. Exact point roots have width 0 whatever you choose.
Native work grows only slowly as the width narrows, but the endpoints get longer.

## What the verifier proves

The standard-library host verifier never imports SymPy and never reruns it. It reads
the published table and the coefficients and, in `Fraction` arithmetic:

1. rebuilds the **square-free decomposition** (Yun's algorithm), requiring
   `lc · ∏ aᵢⁱ` to equal the polynomial exactly, so each factor `aᵢ` holds the distinct
   roots of multiplicity `i`;
2. builds a **Sturm sequence** for each factor and counts its real roots from the sign
   variations at ±∞, giving the independent number of distinct real roots of each
   multiplicity;
3. checks that every interval is ordered, narrower than `maximumIntervalWidth`, strictly
   disjoint from its neighbours (closed intervals may not touch), and contains **exactly
   one** root of **exactly one** factor, and that this factor's multiplicity is the
   published one (a point interval must be an exact root);
4. checks the total: the number of published intervals, and per multiplicity, equals the
   Sturm counts, so no root is missing and none is invented.

Any failure is `SYMPY_CERTIFICATION_FAILED` with the first located interval or `$.roots`.
`roots-verification.json` records the degree, the square-free factor degrees, distinct
and with-multiplicity real root counts, the implied complex root count, and for each
interval its width, point-root flag and Sturm count, bound to the plan, the publication
digests, the observed runtime and the implementation digests. Saved verification
(`schemaxis verify`) recomputes the whole record and also rejects altered, missing or
foreign evidence, a changed worker, native command or runtime identity, and any
publication or evidence whose digest differs.

## Outputs

| Publication | Kind | Content |
| --- | --- | --- |
| `real-roots.csv` | table | `index,lower,upper,multiplicity,pointRoot`, ascending; rationals as `p` or `p/q` text; header only when there are no real roots |
| `roots-summary.json` | text | native runtime identity, call record, intervals and diagnostics; no decisions |
| `roots-verification.json` | text | the host certificate above |

The table holds rational text, not numeric columns. A consumer that needs floating-point
values must convert them and own that rounding. The route accepts no incoming artifacts;
workflow use means independent verified runs. Resuming an unchanged workflow reuses every
verified run; resuming an edited workflow is refused with `RESUME_MISMATCH`, and a fresh
directory runs it afresh (there are no input files).

## Limits and losses

- Exact rational coefficients only, degree 1 to 12, numerators and denominators of at
  most 40 digits, width within `[1/10^30, 1]`, at most 12 published intervals.
- Real roots only; complex roots are counted (`complexRootsWithMultiplicity`), not located.
- The certificate is about the stated polynomial. It says nothing about the numerical
  conditioning of a physical or computed problem that produced the coefficients.
- Closed intervals: a root may sit on an interval endpoint, as for point intervals. Two
  intervals never share an endpoint.
- Only the checks and cases listed in the completion review were run; large-degree,
  larger-coefficient and exhaustive random coverage are not claimed.
- Serial, single native process; no MPI.

## Faults and recovery

| Fault | Meaning and recovery |
| --- | --- |
| `SYMPY_INVALID_COEFFICIENT` | Write each coefficient as an exact fraction string such as `"-3/2"`; no expressions or decimals. |
| `SYMPY_ZERO_LEADING_COEFFICIENT` | Drop leading zeros; the list is in descending powers and the first entry is nonzero. |
| `SYMPY_INVALID_WIDTH` | Use an exact fraction within `[1/10^30, 1]`. |
| `INVALID_ARGUMENT`, `UNKNOWN_ARGUMENT` | Use 2 to 13 coefficients and only the declared fields. |
| `SYMPY_CERTIFICATION_FAILED` | The independent check rejected the native output or a saved table; the evidence is retained but is not an accepted result. Rerun, and report it if reproducible. |
| `SYMPY_UNSUPPORTED_RUNTIME`, `INTERPRETER_NOT_FOUND` | Configure an isolated Python with exactly SymPy 1.14.0. The first means the interpreter imported a different SymPy release. |
| `SYMPY_RUNTIME_UNAVAILABLE` | The configured interpreter started but could not import SymPy or mpmath (the fault location is `$.runtime`). Point `--sympy` or `SCHEMAXIS_SYMPY` at an isolated Python that has exactly SymPy 1.14.0 installed. Nothing is published and the run is recorded as failed. |
| `SYMPY_NATIVE_RESULT_INVALID` | SymPy returned something the contract does not allow, such as a non-rational endpoint. Rerun once; if it repeats, report the polynomial and SymPy release. |
| `VERIFICATION_FAILED` | Retain the evidence and investigate; never relabel it verified. |

Timeout and cancellation stop the owned native process group. Retry in a new output
directory.

## Runtime, public API and maintenance

Configure an isolated Python containing SymPy with `schemaxis configure sympy
/absolute/python`, `--sympy /absolute/python` or `SCHEMAXIS_SYMPY`. Do not install SymPy
into the Schemaxis host environment: discovery, planning and verification never import
it. The worker runs with `-I -B`, SymPy's cache disabled, a 4 GiB address space, 60 CPU
seconds and 16 MiB per output file, under one total deadline (default 60 seconds).

Exactly SymPy 1.14.0 (with mpmath, which SymPy requires) is qualified, and it was
exercised with Python 3.14.4 on Linux; any other release is refused with
`SYMPY_UNSUPPORTED_RUNTIME` rather than assumed compatible. The native mapping is
[`sympy.intervals`](https://docs.sympy.org/latest/modules/polys/reference.html#sympy.polys.polytools.intervals)
on a `Poly` built from a list of `sympy.Rational` coefficients over `QQ`, with `eps`
set to the width, `all=False` and `sqf=False` (so multiplicities are returned). The
native readback and the diagnostic
[`count_roots`](https://docs.sympy.org/latest/modules/polys/reference.html#sympy.polys.polytools.Poly.count_roots)
are evidence only. The latest stable release is listed on the SymPy
[releases page](https://github.com/sympy/sympy/releases). A new release needs fresh
bounded native acceptance with `tools/qualify_sympy.py` before the pinned identity changes.

See the [completion review](../verification/2026-10-24-sympy-completion.md) for
verification scope, and the generated operation reference for the complete schema.

Native isolation uses the public list API with one constructed polynomial and
`strict=True`. This refines touching intervals, including irrational roots near an
exact rational root, into disjoint **closed** intervals. The independent host
certificate still refuses touching endpoints and counts every root with exact
rational arithmetic; no tolerance or certificate rule is relaxed.
