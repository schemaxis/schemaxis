# Implemented first template contract

The initial implementation captures a manifest and one confined workflow file,
then binds a captured case atomically. It launches no native applications. It does
not yet provide resource binding, selectors, authored feedback or a creator GUI.

## API and identity

`workflow_templates.load_template(path)` returns `template`, `workflow` and
`digest`. The digest is the existing canonical `storage.digest` of the object
containing only `template` and `workflow`; all supported manifest metadata is
included. Files are read as strict UTF-8 JSON. Duplicate keys, nonfinite numbers,
absolute workflow paths, traversal, and symlinks within the workflow path are
rejected. Caller-supplied manifest paths also reject parent traversal and symlink
ancestors before normalization. The loader returns captured JSON; later file
edits cannot change it.

`bind_values(bundle, values)` accepts the parsed `schemaxis.workflow-values/1`
object. Its `template` identity must exactly match the captured ID, positive
integer revision and digest. Unknown case keys and parameters are errors. The
returned object contains:

- `document`: the ordinary, bound `schemaxis.workflow/1` document;
- `template`: its captured template identity;
- `values`: all applied values, including defaults;
- `bindings`: one source-map entry per parameter, recording `parameter`, `target`,
  `source` (`case` or `default`), `previous` and `value`;
- `digest`: the canonical digest of the effective document;
- `run`: the validated case run options (see below), or `{}`.

`prepare_template(path, values, planning=False)` performs both operations. With
`planning=True`, it additionally returns `plan` from the shared workflow planner.
Both preparation forms validate the effective host plan. Downstream native plans
may remain explicitly deferred until producer artifacts and values are verified.
A successful binding is not native validation or a successful execution.

The APIs do not mutate their inputs, including on failure. In-memory inputs must
be JSON data, not Python tuples or objects. File and in-memory JSON nesting is
bounded to 64 levels; cyclic in-memory objects produce structured faults.
The digest is rechecked before binding.

## Parameter subset

Each parameter requires `label`, `kind` and `target`, and may have `help`, `units`,
`constraints` and `default`. Its ID starts with a letter and then contains letters,
digits, `_`, `.` or `-`. Without a default, a case must supply a value. A supplied
value always takes precedence over the default. There is no implicit null or
fallback to the workflow's old value. Defaults and the existing target value must
also satisfy the declared parameter contract.

| Kind | Value | Supported constraints |
| --- | --- | --- |
| `number` | Finite JSON number, excluding booleans | Inclusive `minimum`, `maximum` |
| `integer` | JSON integer, excluding booleans | Inclusive `minimum`, `maximum` |
| `boolean` | JSON boolean | None |
| `string` | JSON string | Nonnegative `minLength`, `maxLength`, counted in Unicode code points |
| `enum` | A declared scalar choice | Required nonempty `enum` list, all one scalar type, with unique choices |
| `vector` | Numeric array | Required fixed `length` from 1 to 1024; optional inclusive component `minimum`, `maximum` |

For enum purposes, integer and floating-point numbers share one type; booleans
are distinct. Constraints not listed here fail explicitly. This is a documented
schema subset, not a complete JSON Schema implementation.

Units apply only to number, integer and vector parameters. Plain numbers use the
declared units. Quantity objects, conversions and dimensional consistency analysis
are not implemented; `{"value": 1, "units": "m"}` is rejected even if a target
declares `mm`. Expressions and analytics cannot be supplied as parameter values.

Targets have exactly `scope: "workflow"` and an RFC 6901 `pointer` below
`/dimensions`, `/definitions` or `/settings`. Every target must already exist.
Pointers use strict `~0` and `~1` escapes and canonical nonnegative array indices.
Duplicate targets and ancestor/descendant overlaps fail. Operation-local targets,
whole-workflow replacement and operation-array addressing are unsupported.

## Manifest and output subset

The manifest requires `version`, `id`, `revision`, `title`, `workflow`,
`parameters` and `outputs`. Only `requirements` is optional in this milestone.
Fields proposed for later stages (`assets`, `selectors`, `study`, `ui`) are rejected
rather than silently ignored. Likewise resource and selection parameter kinds,
and case-level `resources`, are unsupported.

`requirements` supports `providers` and `qualification`. When supplied, providers
must exactly match the distinct providers derived from registered workflow document
versions. Qualification remains descriptive metadata, not execution evidence.

Output aliases require an existing `operation` ID, a nonnegative `artifact` index,
and nonempty `kind`, with optional RFC 6901 `pointer` and `units`. Static validation
does not assert that the native artifact exists, has the advertised kind or units,
or contains a selected value. Those assertions require the run's verified receipt.
This milestone does not resolve or publish output aliases.

## Case run options

A case may carry an optional `run` object with run preferences:
`outputDirectory` (nonempty path string), `workers` (integer from 1 to 64) and
`naming` (`pattern` and `indexWidth` from 1 to 12, as in `output_naming`).
Unknown keys fail. `bind_values` validates and returns them unchanged as `run`
(`{}` when absent). They are not template metadata and never enter the template
digest; global presentation choices, such as image size, remain ordinary
template parameters.
