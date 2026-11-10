# Octave planning checks and fault recovery

The full operation table and Calc/Octave workflows are in the
[numerical analysis guide](numerical-analysis.md). This page records when each
numerical constraint is enforced.

## When a document is rejected

`schemaxis plan` runs the independent host arithmetic on every node whose values are
known without reading a file: `samples`, `sequence`, `wave` and anything computed
from them. A document that cannot satisfy the numerical contract is refused at
planning, before any output directory exists and without starting Octave.

Nodes downstream of `readCSV` depend on file contents, which planning never reads.
They are checked by `schemaxis run` after the CSV is captured and validated and
before Octave is launched. Either way the fault names the node as its `location`.

| Fault code | Cause | Recovery |
| --- | --- | --- |
| `INVALID_SAMPLING` | x not strictly increasing for `resample`, `derivative` or `integral`; `fft` input not uniform, or not 4 to 8192 samples in a power of two; smoothing window larger than the sample count | Correct the x values, sample count or window, then plan again |
| `SINGULAR_FIT` | `linearFit` on a single abscissa | Provide x values that vary |
| `INVALID_TABLE` | Unequal x/y lengths, nonfinite or out-of-range values, absent CSV column | Provide at least two finite numbers within ±1e100 and existing column names |
| `RESOURCE_LIMIT` | More than 100000 intermediate samples, or a CSV over 8 MiB | Reduce sample counts or node count |

Verification is unchanged: results are recomputed independently and compared
with relative tolerance `2e-8` and absolute tolerance `2e-9`. Do not widen
tolerances to hide a disagreement. Runs already published verify as before.
