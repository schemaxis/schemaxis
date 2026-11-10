# Adaptor layout and discovery

Use the [authoritative completion checklist](adaptor-completion.md) for new adaptors
and changes to existing operations, fields and routes.

All routes receive [common expressions, references and analytic iteration](adaptor-runtime.md)
through the registry. Native modules implement literal kernels; built-in Python
entry points also bind the shared boundary for direct callers.

Use [adaptor readiness](adaptor-readiness.md) to audit delivery materials and apply
the opt-in structural admission gate over the extension contract below. The
[current audit](design/adaptor-framework/AUDIT.md) records gaps across installed
routes; [growth readiness](design/adaptor-framework/GROWTH-READINESS.md) describes the
remaining development-kit and qualification work.

Application code and application-specific policy belong in
`src/schemaxis/adaptors/<app>/`. This includes declarations, schemas, launch arguments,
resource rules, native execution, verification, console defaults and native data
mappings. Shared graph evaluation, scheduling, IPC, artifact hashing/packaging,
authoring, cameras and session persistence live in `src/schemaxis` (and retained
shared utilities in `src/schemaxis/core`). Adaptors may use the framework; they must not use
another adaptor as a utility library.

`schemaxis.adaptors.registry` scans the **installed** adaptor package directories for
`adaptor.json`, in deterministic order. It reads metadata without importing native
applications. There is no generated registry or index to update. The manifest is
trusted installed code configuration, never authored workflow input. Adding or
removing a folder takes effect in a fresh process. A running process keeps its
registry snapshot; hot installation/uninstallation is not supported.

Existing top-level application module names are compatibility aliases. Likewise,
`schemaxis.core.runners` retains lazy compatibility exports for discovery now implemented in
`schemaxis.adaptors.paraview.mvp.runners`, and `schemaxis.data_contracts.paraview_traits` forwards to the
ParaView adaptor. These aliases contain no application implementation and must
not be used by new framework code. `schemaxis/1` remains the historical shared graph
format and ParaView document version; it is retained for saved-input compatibility.

Adaptor-owned [strength assessments](adaptor-assessments.md) provide optional,
explicitly subjective whole-application breadth and supported-workflow abstraction
estimates. `schemaxis assessments` aggregates the same registry, counting providers
and authorable routes separately. Missing, invalid or stale editorial metadata
does not change executable contracts or native qualification.

## Add an application

Create this package (include `__init__.py`, even if empty):

```text
src/schemaxis/adaptors/someapp/
    __init__.py
    adaptor.json
    adaptor.py
    native.py             # optional, imported only inside the application process
```

A minimal registration is:

```json
{
  "id": "someapp",
  "version": "someapp/1",
  "routes": {
    "someapp/1": {
      "module": "schemaxis.adaptors.someapp.adaptor",
      "schema": "schemaxis.adaptors.someapp.adaptor:schema"
    }
  }
}
```

The default declaration binding is `schemaxis.adaptors.someapp.adaptor:DECLARATIONS`;
the default console module is `schemaxis.adaptors.someapp.adaptor`. Override these
with `declarations` and `adaptor` when necessary. Supply `runtimeFamily`,
`executables`, `keywords` and `execution` to make discovery useful. Binding paths
must belong to the adaptor's own package. Duplicate IDs, document versions and
schema-section names fail with `INVALID_ADAPTOR`.

Implement these host-safe entry points in `adaptor.py`:

```python
DECLARATIONS = {...}  # existing typed operation declaration grammar

def schema():
    ...  # JSON Schema for this document version

def plan(document):
    ...  # validate input, return a JSON-serialisable plan

def run(document, directory, *, executable=None, timeout=300):
    ...  # launch the native process, retain input and evidence, verify outputs

def verify(directory):
    ...  # independently recheck saved evidence and actual artifacts
```

`declarations` may alternatively bind a zero-argument callable returning the
catalogue. Imports for discovery, declarations, schemas and planning must never
load `bpy`, ParaView, FreeCAD or other native application modules. Keep those
imports in explicit native entry points.

The folder is then available through `discover`, `describe --provider someapp`,
`query`, `schema`, `plan`, `run`, `verify`, reference generation and the basic
multi-document console. Use `run INPUT --executable /absolute/application/path`;
no app-specific CLI flag is required. Existing convenience flags are declared in
their owning adaptors' `cliOptions`. Python callers pass
`locations={"someapp": "/absolute/application/path"}` to registry/workflow execution.

Python packages and adaptor JSON/text resources are included automatically in the
wheel and recursive native runtime archive. Additional resource types need package
data configuration. Register `runtimePackages` only if native replay also needs a
separate installed companion package. Regenerate **documentation**, not runtime
routing, with `python3 -m schemaxis reference`.

## Progressive capability metadata

Every primary-route declaration is automatically available through
`schemaxis capabilities`. Optional `capabilities: "schemaxis.adaptors.someapp.capabilities:catalogue"`
in the manifest adds a trusted host-only zero-argument metadata function. Its
binding must belong to the adaptor package, just like schema/declaration bindings.
It returns `groups`, `operations`, `requirements` and `references`; all are optional.

A group maps an adaptor-local slug to `label`, `purpose` and a domain slug. Operation
metadata keys must name existing declarations. Each can contain `purpose`, `groups`,
`keywords`, `related` (local operation names), `semantics` and `examples`. Examples
have a `purpose` and a `document` or repository `reference`. Adaptor-level
`requirements` and `references` are string arrays. Unknown operation/group/related
IDs fail with `INVALID_CAPABILITY_METADATA`. See the small FreeCAD and ParaView
`capabilities.py` files for concrete examples.

Keep application-specific units, purposes and semantic guidance here. Do not copy
option schemas into this metadata, add framework application-name branches or
promote native inventories to declared operations. The service derives stable IDs,
links and schemas from the current registry; schema fragments preserve the exact
source schema. Missing metadata leaves an operation directly discoverable, with
unknown status where evidence has not been checked. See
[the CLI/service contract](capability-discovery.md).

## Explicit optional capabilities

A route describes one document version. Add routes in the same manifest for
additional app formats; do not teach the framework their version strings.
Capabilities are opt-in. Registration does not imply support for inspection,
workflows, live editing, MPI or native save.

| Route field | Meaning |
| --- | --- |
| `planIndex` | Select the public plan from a legacy tuple return; omit for a plain plan. |
| `compose` | Supports authored document composition. |
| `graph` | Uses the shared graph and inline/analytic authoring schema. |
| `expand` | `identity`, `composition`, `plannedNodes`, or `graph`; default is `graph` for graph routes, otherwise `identity`. |
| `workflow` | Supports verified workflow execution and artifact handoffs. |
| `scheduled` | Use the dependency scheduler; set true for new workflow adaptors. False retains the older serial receipt format. |
| `timeBatches` | Supports explicit finite time-list chunking. |
| `acceptedArtifacts` | Allowed incoming artifact kinds; default is none. |
| `graphEditing` | Set false for non-node documents such as assemblies. |
| `schemaName` / `referenceName` | Stable names for schema sections and generated files. |
| `runOptions` | Additional native-run keyword to configured-location-key mappings. |

`hooks` maps the following names to `module:function` bindings in the app package.
Only provide hooks whose behaviour differs from the common defaults.

| Hook signature | Responsibility |
| --- | --- |
| `resources(document, execution, operation_id)` | Validate native resource requirements; return default `threads` and minimum `gpus`. Generic budget checks still apply. |
| `provisionalResources(document, execution, operation_id)` | Optional host-only reservation check for documents that still contain producer references. Return only known `threads` defaults and minimum `gpus`; omit unknown requirements. Never fabricate input files or launch native code. |
| `validateExecution(document)` | Validate a requested multi-rank pipeline; absent means MPI is unsupported. |
| `reusableInputs(document)` | Return `{absolute_path: digest}` for complete input provenance, or `None` to disable reuse. Default is `None`. |
| `retainedInputs(directory, document)` | Optional saved-input provenance: after successful native verification, return `{original_absolute_path: sha256}` bound to the verified retained capture and effective document, or `None` when complete captured provenance is unavailable. Never read the original inputs or trust an unchecked `job.json`. Its keys and digests must equal the `reusableInputs` map captured at execution time. Fresh execution/reuse still checks current inputs. Common studies aggregate their verified child maps. |
| `validateHandoff(producer, consumer, operation_id)` | Additional producer-specific restrictions before execution. |
| `verify(directory)` | Override the module's verification entry point. |
| `verifyAttempt(directory, expected_document)` | Additional attempt-evidence checks; otherwise the ordinary verifier is used. |
| `verifyLegacy(directory, effective_document, outcome, operation_id)` | Validate the historical serial workflow receipt format. New adaptors should use scheduled execution. |
| `query(document)` | Return `(operation_names, report_flags)` when requirements are not just node filters. |
| `expandedSchema(schema)` | Refine the version's expanded schema in place. |
| `inspect(document, node, directory, *, locations, timeout, visit)` | Custom native inspection implementation. |
| `inspectionSetup(document, locations)` | Shared graph inspection: return `(master, interpreter, launch_arguments)`. |
| `nativeInspection(document)` | Called only inside the app: return `(master, backend)`. |

Workflow-enabled adaptors must retain `authored.json` and `verification.json` with
an `artifacts` array containing absolute file paths, kinds and digests. Verification
must detect missing, changed or mismatched results. Successful process exit or file
existence alone does not establish correctness. The scheduler rechecks authored
inputs, handoff evidence, resources and adaptor verification before reuse.

`publication-metadata.json` is reserved for the shared publication manifest in
every run and nested run directory. Adaptors must not use that name for their own
artifacts or unrelated data. See the [output metadata contract](output-metadata.md).

Producer-dependent documents defer their complete input and resource validation
until the producer receipts are verified. `provisionalResources` can still derive
reservations from independent settings, such as declared render threads and device.
It receives the unchanged input, including unresolved references. Without this
hook, explicit reservations or conservative scheduler defaults apply. After
resolution, the complete `resources` hook and planner must pass against the
reservation before dispatch; deferred planning never enlarges the resource budget.

Other manifest bindings are `registerFunctions`, `runtimeSchema`, `optionSchema`,
`sections`, `referenceSettings` and `coverage`. These expose app-owned extensions
to the shared typed function/schema/reference mechanisms.

## Console and live clients

A basic node console needs only a plan function. `consoleTemplate` defines its
empty input. `consoleOutput` marks an output-node field; `nativeExtension` declares
single-file saves. `consoleCapabilities` advertises available features.

`consoleHooks` supports `validate(document, draft=True)`,
`add(document, id, operation, renderable)`, `show(document, id, renderable)`,
`command(session, command, args, original_line)`, and
`live_save(session, directory, applied, geometry, document)`. A command hook returns
`None` when it does not recognise the syntax. Mutating hooks operate on a candidate;
the shared session validates and commits it, retaining undo/recovery semantics.
App-specific command help belongs in `consoleCommands`.

Persistent native graph workers reuse `schemaxis.live_runtime.GraphWorker` and
`schemaxis.live_transport.ProcessSession`. The adaptor supplies `liveGraph(document)`
and native lifecycle methods. `liveArguments`, `liveExecutable`, `liveModule`,
`liveSaveName` and `nativeExtension` keep startup and save policy in the adaptor.
An adaptor may instead supply its own `LiveSession` transport.

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
PYTHONPATH=src python3 -m schemaxis discover
PYTHONPATH=src python3 -m schemaxis reference --check
```

`test_adaptor_architecture.py` checks import boundaries and installs a test-only
adaptor folder into an isolated package copy. It exercises discovery, CLI,
schemas, queries, console, workflow execution, verification and resume without
editing any framework file. Existing native correctness checks remain required
for each real app; this extension test does not qualify native behaviour.

## Package migration

Application implementations now live under `schemaxis.adaptors.<app>`. Shared
utilities use `schemaxis.core`; the retained ParaView MVP uses
`schemaxis.adaptors.paraview.mvp`, including its `python -m` entry point. The synthetic
provider is `schemaxis.adaptors.fixture_geo`. Update old `schemaxis_core`,
`schemaxis_paraview`, `schemaxis_fixture_geo` and `schemaxis.adaptors` imports. The
old sibling package directories are removed. Existing top-level forwarding modules
remain small compatibility aliases, with all implementation in the app silo. Saved
workflow document versions and provider IDs are unchanged. Historical verification
receipts retain their original paths and are not rewritten as new evidence.

Release-specific qualification metadata belongs to each app's `upstream.json`;
see [latest-release maintenance](updates.md). Optional runtime compatibility profiles
there compare observed application releases with exact, evidenced baselines; see
[runtime compatibility profiles](updates.md#runtime-compatibility-profiles).
Machine-specific application locations
belong in [private configuration](installation.md), never in repository guidance.

For bounded procedures driven by verified output measurements, see
[feedback studies](feedback-studies.md). Installed adaptor policies own scientific
criteria and proposal rules; the shared controller owns attempt ordering, stopping,
verification and publication. Gmsh is the first qualified policy.

GUI authoring readiness also requires the [Studio adaptor contract](studio-adaptor-contract.md): complete Add coverage, option forms, Help and located diagnostics.

GUI delivery also requires adaptor-owned conceptual text preserved in
`guidance.json`. The [Studio contract](studio-adaptor-contract.md) defines complete
operation/field coverage, human contribution, schema annotations and admission
checks; native property bindings alone are insufficient user guidance.
