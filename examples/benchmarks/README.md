# Reusable multi-case comparison pack

Edit `cases.json`, then prepare the two arms using
[`tools/benchmark_workflows.py`](../../tools/benchmark_workflows.py).

The suite contains RLC-to-workbook, CAD/mesh, CFD slice and table-control tasks.
Each family starts with two cases; revisions change selected parameters and add
one circuit. `templates/` contains existing Schemaxis document formats; generated
analytic CFD and table fixtures are materialised outside the source tree.

See the [benchmark guide](../../docs/benchmarks.md) for preparation, reference
proofs, isolated trial exports, grading, input reuse and known limits. Reference
proofs are not autonomous AI comparisons. Actual trial records begin as `not-run`.
