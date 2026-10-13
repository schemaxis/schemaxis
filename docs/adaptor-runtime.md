# Common adaptor runtime

All thirteen adaptors and fifteen application routes accept document references,
closed expressions, pure value functions and finite analytic studies through the
CLI, registry and direct Python `plan`, `run` and `verify` entry points. New plugins
receive the common boundary automatically through the registry. Native kernels
remain host-safe planners plus isolated application executors.

The framework treats an application as a logical live black box: supply a complete
input state, execute, independently verify its outputs, then advance to the next
state. ParaView and Blender retain their existing incremental native graph workers
for supported graph studies. Other routes use **isolated native processes per
visit**. This does not promise a persistent GUI or native process for every app.
A failed transition poisons its session; completed visit evidence is retained.

## Inputs and finite iteration

`dimensions`, `definitions` and `settings` are common authoring context. Use the
existing `$document`, `$expr` and `$value` syntax in any typed native input:

```json
{
  "dimensions": {
    "coarse": {"$analytic": {"type": "values", "values": [4, 3, 2], "sync": "resolution"}},
    "fine": {"$expr": {"op": "divide", "args": [{"$document": "/dimensions/coarse"}, 2]}}
  }
}
```

This fragment is authoring context, not a complete application document. A Gmsh
size can reference `/dimensions/fine`. The expression is evaluated separately for
every visit; it does not freeze its first value. Repeated references to one analytic
source share that binding. Equal `sync` names coordinate equal-length sequences;
independent groups form a Cartesian product, first encountered group fastest.
Definition-site relative references retain the existing JSON-pointer semantics.

Common studies also accept explicit `axes` with `values` or `series`, and `$axis`
member references. Workflow axes and each operation's axes have separate name
scopes, so the same axis name in two operations does not accidentally synchronize
them. Use a shared document reference or an explicit `sync` name to coordinate values. `maxStates` defaults to 10000 and cannot exceed 10000 in the
common executor; expanded input is bounded to 64 MiB. Every statically known state
is typed and validated before native execution. Dynamic axis membership/count is
rejected. Native app limits still apply to each state. Orbit analytics produce
camera lists. Existing graph camera/appearance sequences retain their separate
publication loops. Constructor changes use isolated visits rather than assigning
an immutable native property in place.

Common `plan` returns `schemaxis.study.plan/1` for an analytic study, with ordered
visits, inputs, indices and native plans. `schema --expand` returns a
`schemaxis.study/1` expansion report for common analytic states or deferred
workflow values. Workflow visits list `deferredReferences` explicitly; these inputs
become literal only after producer verification. The report is an inspection
result, not another authored application version.

Execution retains the original `authored.json`, aggregate verification and numbered
`state-00000` directories. Each state retains the native adaptor's original evidence
and publications. Verification reconstructs the requested states, rechecks every
native result and rejects altered inputs, indices, membership or artifacts.
The common timeout covers the entire study, and cancellation is checked between
visits as well as inside native dispatch. Workflow resume retains ordinary immutable
attempts and input provenance. No native objects cross process boundaries.

## Connections between adaptors

A workflow keeps each operation's ordinary local document scope. References may
also select another operation's authored input:

```json
{"$document": "/dimensions/thickness", "operation": "design"}
```

`{"$document":"/dimensions/thickness","scope":"workflow"}` selects shared
workflow context. References are evaluated at the source definition site; missing
values and reference cycles fail. Referencing an input does not imply that the
producer must execute, because this is authored data, not a native result.

A value reference selects **verified output** from an earlier operation:

```json
{"$value": "mesh", "artifact": 3, "path": "/volume"}
```

Here `artifact` selects the producer's JSON publication by its documented artifact
order. Numeric CSV publications expose `columns` and `rows`, allowing a pointer
such as `/rows/0/1`. Without `artifact`, `path` selects the verified native receipt.
Do not infer scientific units from a number; keep the producer's documented units
or explicitly convert them in a closed expression.

Value references can appear inside `$expr` and pure `$value` function arguments.
The two `$value` forms are distinguished by `path` (operation result) versus
`args` (registered function). JSON and numeric-table extraction is bounded to 8 MiB;
no arbitrary file reads, native reflection or scripts are introduced.

The scheduler adds the producer dependency, verifies its artifacts, resolves the
selected value, then validates and executes the consumer. An analytic range or
value sequence may itself depend on a producer result; its expansion and limit
checks are deferred until that value is available. Plans explicitly defer
unknown result-dependent values; they never substitute invented numeric defaults.
Handoff evidence retains the value and producer receipt digest. A multi-visit
producer requires explicit `visit` selection unless the enclosing workflow study
already provides a single producer execution in each state. Every reference is
rechecked on verification and resume.

Workflow-level analytics bind the entire workflow, coordinating references between
operation documents. Ordinary native graph studies retain their specialised loops
when no outer common study is needed. Existing `$artifact` references continue to
transfer files, subject to the consumer's declared accepted artifact kinds.
FreeCAD assemblies can participate in scheduled workflows.

## Extension and verification

`schemaxis.adaptor_runtime.InputProgram` owns common state preparation.
`AdaptorSession` owns the apply/verify/close lifecycle. The registry is the canonical
integration boundary; existing built-in Python modules use `bind(globals())` to
expose the same preparation for direct callers. `_native_plan`, `_native_run` and
`_native_verify` retain literal kernel entry points and are implementation details.

Run `tests/unit/test_adaptor_runtime.py` for all-route planning, synchronization,
reference scoping, deferred dependencies, native-double execution, resume and
corruption checks. Native qualification is reported separately in verification
records; registration and shared syntax do not imply native availability.

## Runnable examples

- [Gmsh analytic study](../examples/schemaxis/gmsh-analytic-study.json) varies the
  solid extent and mesh size together in two independently verified states.
- [Gmsh to Octave analytic workflow](../examples/schemaxis/workflow-analytic-values.json)
  passes measured mesh volume into a numeric table, derives a scaled value with an
  expression, and takes mesh size directly from the Gmsh authored document.

Use `schemaxis plan <example>` before `schemaxis run <example> --output-directory
<fresh-directory>`. Configure each required native application as usual.

See the [2026-09-30 verification record](../verification/2026-09-30-common-adaptor-runtime.md)
for the host suite, fourteen native route qualifications, cross-adaptor values and
resume checks.
