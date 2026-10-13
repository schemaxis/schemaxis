# Illustrative bundle

`reentrant/template.json` and its two values files use the first implemented
template contract. The workflow body uses existing `schemaxis.workflow/1` syntax.
CLI binding and planning are host-only; native template acceptance is pending.

The four operations are:

1. FreeCAD constructs a box from workflow-wide dimensions and measures its height.
2. Gmsh consumes the STEP artifact and uses the measured height to set mesh size.
3. Octave tabulates mesh volume divided by the declared base area, giving height
   in mm. Two identical samples satisfy the current table source's minimum length.
4. A separately named FreeCAD operation uses that tabulated height in a new box.

This is a small data-dependency example, not a physical optimisation. It demonstrates
returning to an adaptor in a later operation; it does not reuse the first FreeCAD
process or mutate its original model. Native output acceptance remains pending.

The case files change initial height and length. Their digest is
`schemaxis.storage.digest({"template": manifest, "workflow": body})`, sufficient
for this two-file example with no additional assets. A production bundle digest
must include every declared dependency as specified in the architecture.

Bind and plan from a source checkout (or omit `PYTHONPATH=src python3 -m` when
using an installation containing this milestone):

```sh
PYTHONPATH=src python3 -m schemaxis template inspect docs/design/workflow-templates/examples/reentrant/template.json
PYTHONPATH=src python3 -m schemaxis template bind docs/design/workflow-templates/examples/reentrant/template.json --values docs/design/workflow-templates/examples/reentrant/values-small.json
PYTHONPATH=src python3 -m schemaxis template plan docs/design/workflow-templates/examples/reentrant/template.json --values docs/design/workflow-templates/examples/reentrant/values-tall.json
```

`bind` emits the effective document, template identity, values, source map and
document digest. `--document-only` emits an ordinary workflow suitable for the
existing `plan`/`run` commands. Keep the full binding record alongside any saved
effective document when provenance is needed; automatic run provenance integration
and named output resolution remain later work.

The service/JSON-lines method is `prepare_template`, with `filename`, parsed
`values`, and optional boolean `planning`. It uses the same preparation function
as the CLI. It creates no execution task, plan record or native job by itself.

The historical `check_examples.py` and `design-checks.json` preserve the review
baseline at `4487292`, including the artifact-only STEP planning defect. Current
coverage is in `test_workflow_templates.py`, `test_template_entrypoints.py` and
`test_deferred_workflow_handoffs.py`; the defect is corrected by explicit deferral
and resolved-input validation. Do not overwrite the old design evidence to claim
it passed originally.

The example's result-dependent operations remain deferred until verified producer
outputs exist. Host checks do not qualify FreeCAD, Gmsh or Octave execution.
