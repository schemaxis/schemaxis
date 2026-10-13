# Adaptor development kit

Use the [authoritative completion checklist](adaptor-completion.md) for new adaptors
and changes to existing operations, fields and routes.

An adaptor delivers a bounded, editable, inspectable and independently verified
workflow. Registration alone is not admission. Use the same published context and
JSON contracts for an agent and a human; native handles stay in the application
process. The host runtime remains dependency-free.

## Delivery and admission

Generate a reviewable source overlay for a new provider:

```sh
PYTHONPATH=src python3 -m schemaxis adaptor scaffold someapp \
  --output-directory evidence/someapp-scaffold --model nodes
# For a non-node input contract use --model document.
```

The overlay contains the package, manifest, host/native stubs, context bundle,
editable example, generated host test, acceptance launcher and a development
checklist. It does not install anything or overwrite an existing directory.
Merge the reviewed new files into the repository, replace the illustrative
operation with the real capability, and complete every TODO. Native stubs fail
with `ADAPTOR_NOT_IMPLEMENTED`; qualification starts unknown and admission fails
until the delivery contract is complete. Both generated document models are
tested in an isolated package copy without editing framework routing.

Start from the [extension contract](adaptors.md), then provide the versioned
[readiness bundle](adaptor-readiness.md). The `development` section adds the
following obligations without duplicating operation schemas or native bindings:

| Material | Required content |
| --- | --- |
| `api` | Public native API URLs. References are data and are never fetched or executed during discovery. |
| `lifecycle` | Timeout scope, cancellation behaviour, retained logs and the independent verifier's method. |
| `data` | Unique IDs, input/output direction, artifact kind, format, traits, explicit losses and supported scope. Null traits mean unknown. |
| `inspection` | Trusted shared panel IDs with interpretation scope and bounds. No adaptor-supplied UI code. |
| `authoring` | `nodes` or `document` model matching the route, a valid editable example ID and reuse instructions. |
| `features` | A supported/unsupported/unknown decision and scope for every optional feature in the kit. Existing manifest claims must agree. |
| `cases` | At least two distinct effective inputs: a baseline and a variant, with independent literal expectations. |

Optional feature decisions cover workflows, native inspection, composition, MPI,
reusable inputs, time batches, source/property authoring, live editing, native save
and conversion. Unsupported is a valid decision. Supported features need their
existing registry flags/hooks, scoped documentation and appropriate behavioural
checks. A decision does not qualify that feature; the native receipt lists exactly
what ran. Batch CAD cases do not qualify MPI, live editing or every CAD operation.

Data contracts describe both preservation and loss. Reuse `data_contracts.assess`
for observed trait compatibility; missing traits stay unknown. Matching artifact
kinds are insufficient. Conversions must be named operations with explicit losses
and acceptance; the kit does not insert automatic conversions or promise universal
lossless interchange. Keep normative constraints in planners/native validators.

```sh
PYTHONPATH=src python3 -m schemaxis readiness --app octave --admission --check
PYTHONPATH=src python3 -m schemaxis adaptor context schemaxis.octave/1
PYTHONPATH=src python3 -m schemaxis adaptor context schemaxis.octave/1 \
  --pointer /materials/development/data --max-bytes 8192
```

The public agent method is `adaptor_context(version, pointer, offset, limit,
max_bytes, revision)`. It uses the shared bounded JSON observation protocol: follow
member pointers instead of truncating content. The revision hashes the complete
response data. Route context works for non-node documents as well as primary
operation catalogues. The [generated index](generated/adaptor-delivery.md) links
all installed routes and their complete development materials.

## Reusable conformance

Install `jsonschema` in the **developer** Python environment for schema conformance;
it is not required for ordinary discovery, planning or execution. Missing developer
dependencies produce an explicit unavailable fault, never a skipped success.

```sh
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.octave/1 \
  --output-directory evidence/my-adaptor-host
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.octave/1 --native \
  --output-directory evidence/my-adaptor-native --timeout 120
```

Host conformance checks the real authored schema, valid/invalid fixtures, exact
fault codes, deterministic plans, unchanged caller input, undeclared root fields,
valid option defaults and distinct effective acceptance plans. Invalid examples can
set `schemaValid: false` when they intentionally violate JSON Schema; otherwise
schema acceptance defaults to true, allowing meaningful semantic rejections.
Fixture conformance does not establish equivalence for every possible input.

A case selects an existing example and applies ordinary shared JSON patches:

```json
{
  "id": "box-variant",
  "example": "analytic-box",
  "edits": [{"op": "replace", "path": "/nodes/0/options/height", "value": 7.5}],
  "scope": "Analytic box volume and reopened publications, not arbitrary topology.",
  "checks": [{"file": "verification.json", "format": "json",
              "pointer": "/native/volume", "expected": 1500,
              "relative": 0.00000001, "absolute": 0.000001}]
}
```

Cases that consume files can add a `resources` map from an existing JSON pointer
to a repository-relative fixture, for example:

```json
{"resources": {"/nodes/0/options/files/0": "examples/schemaxis/catalogue-texture.png"}}
```

After applying `edits`, conformance replaces each named value with the absolute
local fixture path. References must remain inside the matching repository, including
symlink resolution. Fixture bytes participate in source freshness; the case digest
uses the relative reference and bytes, so equivalent checkouts have the same input
identity. This materialisation belongs to the acceptance recipe, not a new authored
parameter language. For production handoffs use the existing artifact/resource
binding contracts.

Assertions support bounded JSON, numeric CSV (`columns`/`rows`) and UTF-8 text.
Expected values are reviewed fixture literals. Do not copy them from the producer's
observed output or use an exit status/`verified` flag as a correctness criterion.
Supply physical/analytic/reference justification in the case scope and guide.
Tolerances must be explicit and appropriate to the domain.

Native mode is opt-in. It uses configured application locations, fresh directories,
existing registry runners and independent expectations. It requires observed runtime
identity, rechecks verification, temporarily removes/corrupts every publication and
authored/plan evidence, restores each original in `finally`, and tests timeout and
pre-launch cancellation. Only its newly created run directories are mutated.
Each case runs in a separate host process with an independent `--wall-timeout`
(default 300 seconds). A runner or verifier that ignores its own timeout is stopped
by the shared process-tree supervisor and fails with `CONFORMANCE_WATCHDOG`; that
failure cannot count as a successful adaptor timeout test. Negative lifecycle
probes get at most ten seconds each. Logs and incomplete evidence remain available.
In-flight cancellation and process-tree handling also need shared runner/service
conformance; a pre-launch cancellation result does not establish those behaviours.

`qualification.json` is retained on success or failure. Successful receipts bind
the exact case and source digests, runtime observations, expectations and negative
checks. A source change makes registered qualification stale. The digest includes
shared framework sources/assets, the owning adaptor's code and delivery bundle,
and referenced JSON and binary fixtures in the matching checkout. Missing checkout fixtures
change the digest rather than silently retaining qualification. It excludes other
adaptors, generated documentation, upstream policy and receipt files. This is
conservative freshness, not a signature or proof against a dishonest package author.

```sh
PYTHONPATH=src python3 -m schemaxis adaptor record \
  evidence/my-adaptor-native/qualification.json
```

Recording is explicit and refuses unsuccessful, host-only, incomplete or stale
receipts. Context reports source-current/stale/unknown independently of local
runtime availability. A source-current receipt applies only to its named cases and
observed runtimes; it does not prove compatibility with another installed release.
Do not change `upstream.json`'s absorbed version without the existing upstream
maintenance acceptance process.

## Completion evidence

See [growth readiness](design/adaptor-framework/GROWTH-READINESS.md) for the exit
criteria, source-bound receipts, public agent and human reuse proof, and scoped
qualification boundaries. `tools/qualify_adaptor_growth.py` retrieves bounded published
context, authors both document models, runs baseline/variant cases, inspects results,
and checks invalid input and unavailable routes/runtimes through the public agent
protocol. It is a deterministic client, not an evaluation of an autonomous model.

## Existing-adaptor migration

The earlier fifteen-route migration completed its development bundles and host
conformance. The registry has since grown to eighteen adaptors and twenty routes.
The stronger [completion audit](../verification/2026-10-10-adaptor-completion.md)
reports current documentation/discovery gaps and source-bound qualification status.
Development conformance alone does not establish complete product documentation. Reproduce the catalogue-wide host
check with `tools/qualify_adaptor_migration.py --output-directory NEW`. Add `--native`
and repeated `--app` selections for configured runtimes; failures are retained and
never counted as successful skips. `--record` is an explicit opt-in to registering
successful native receipts. The user's configuration can be selected with `--config`.

`tools/qualify_migrated_context.py` exercises the seven newly qualified routes
through published context and public agent tools. See the
[migration evidence](../verification/2026-09-28-existing-adaptor-migration.md) for
native scope, unavailable environments and the distinction between conformance
expectations and bounded public resource inspection.

[Gmsh](gmsh.md) is the first new provider delivered through the completed kit,
including a qualified FreeCAD/ParaView handoff and public source/property reuse.

[Cantera](cantera.md) adds a second provider through the kit, with independent
thermochemistry/equilibrium verification, a Calc handoff and shared agent/console reuse.

[ngspice](ngspice.md) proves the non-node document route on a new native provider,
with verified linear circuit tables, a Calc handoff and shared terminal patch reuse.

## Preserve conceptual guidance during development

Maintain the adaptor’s `guidance.json` alongside every declaration and schema
change. Explain purpose, field meaning, units, defaults, assumptions and useful
examples as implementation decisions are made. Run the coverage audit from the
[Studio contract](studio-adaptor-contract.md#conceptual-guidance-is-an-adaptor-deliverable);
new forms must not depend on someone reconstructing these meanings from native
bindings later. Ask a domain reviewer to fill or correct pending text before GUI
admission. This is an authoring requirement, separate from native qualification.

## External adaptor packages

An adaptor can ship as its own installable distribution, for example a private or
commercially licensed integration, without any change to the core. The registry
loads built-in folders first, then every installed entry point in the
`schemaxis.adaptors` group. The entry-point name is the adaptor ID; the value is an
importable package that contains `adaptor.json`:

```toml
[project]
name = "acme-schemaxis"
requires-python = ">=3.10"
dependencies = ["schemaxis>=0.4,<0.5"]

[project.entry-points."schemaxis.adaptors"]
acme = "acme_schemaxis"

[tool.setuptools.package-data]
acme_schemaxis = ["*.json", "studio/templates/*.json"]
```

The package uses the built-in layout, so `adaptor.json`, `adaptor.py`,
`guidance.json`, `readiness.json`, `studio.json`, `upstream.json` and
`qualification.json` sit beside its `__init__.py`. Every binding in the manifest
must start with the package name (`acme_schemaxis.adaptor:schema`, not a
`schemaxis.` path). Discovery reads resources with `importlib.resources`, which
imports only the package `__init__.py`; keep that file empty or trivial so
discovery never loads native applications or heavy modules.

Native runtime archives (`runtime.zip`, used by shared inspection, live sessions
and native jobs) always bundle every admitted plugin package, plus any companion
packages it lists in `runtimePackages`. The archive also records the admitted
plugins in `schemaxis/adaptors/runtime-plugins.json`. When the core is imported
from the archive, the registry reads that host-written list instead of the
interpreter's installed metadata. An application's embedded Python therefore
sees exactly the plugins the host admitted, and never another plugin installed
only in the application's environment. Each archive carries the core's
`LICENSE`, `NOTICE`, `COPYRIGHT` and `LICENSES/*` under `schemaxis-licences/`,
read from the source checkout or from the installed distribution's metadata.
The licence files that an installed plugin distribution records go under
`schemaxis-licences/plugins/<distribution>/`.

The optional manifest key `display` sets the Studio identity of any adaptor:
`{"name": "Acme Solver", "mark": "AS", "colour": "#2a6f97"}`. `name` is 1-64
characters, `mark` 1-3 characters and `colour` a `#rrggbb` value; `mark` and
`colour` are optional. Without it, the Studio generates a stable name, mark and
colour from the ID.

The registry rejects a plugin with `INVALID_ADAPTOR` in any of these cases:

- its ID collides with a built-in or another installed plugin (all claimants
  are named and excluded);
- its entry-point name differs from the manifest `id`;
- a binding leaves its package (this includes `documentValidation` and
  `liveModule`);
- it reuses a document version, schema section or route `schemaName`;
- it claims `default` or `defaultConsole`;
- its package cannot be imported or read.

Framework identities are reserved. A plugin may not use:

- the IDs `workflow` or `workflow-design`, or any folder name below
  `schemaxis/adaptors`;
- any version of a framework document, such as `schemaxis.workflow/1`,
  `schemaxis.workflow-design/2`, `schemaxis.study/1` or `schemaxis.plan/2`
  (`FRAMEWORK_DOCUMENTS` in the registry lists them);
- the framework schema sections and names `camera`, `series`, `workflow`,
  `execution`, `operation-execution`, `composition` and `analytic`.

A plugin version in the `schemaxis` namespace must be its own, for example
`schemaxis.acme/1` or `schemaxis.acme.mesh/1`; versions outside that namespace,
such as `acme/1`, are free.

`cliOptions` entries contain `flag` (`--lower-case-name`), an identifier `dest`,
`help`, and an optional `action` of `store` or `append`. Each flag and each
`dest` must be new. Flags may not repeat a framework option on `run`, `inspect`
or `console` (such as `--executable`, `--output-directory` or `--help`) or
another adaptor's flag. Destinations share one location namespace with adaptor
IDs, so a `dest` may not repeat a framework destination, another adaptor's
`dest` or another adaptor's ID. When two plugins collide, the one with the
earlier ID keeps the name. Built-ins follow the same `cliOptions` rules; a faulty
built-in still stops loading.

Admission reads manifests only. A plugin binding that fails when first resolved
(for example a missing `declarations` module or attribute) excludes the plugin
for the rest of the process. Its fault joins `pluginFaults`, and `discover`,
`query --operations`, the workflow and umbrella schemas, capability browsing
and typed functions continue with the built-ins. Selecting the excluded plugin
explicitly fails with `INVALID_ADAPTOR` or `UNKNOWN_PROVIDER`. A faulty plugin is excluded and its fault is
reported in `schemaxis discover` under `pluginFaults` and as a Python warning, so
the built-ins stay usable. `SCHEMAXIS_ADAPTOR_PLUGINS=off` loads built-ins only.
Each provider in `discover` names its `source`: `builtin` or
`plugin:<distribution>`.

Trust model: only installed distributions can add adaptors, so the operator who
controls the Python environment decides which code runs. Authored documents still
select registered IDs and versions, never packages, modules or folders. A plugin
is ordinary trusted Python code with the same access as the core; review it as
you would any dependency.

Versioning: the manifest keys, binding signatures and framework modules used by
adaptors are the plugin contract. During 0.x, pin the core minor version
(`>=0.4,<0.5`) and release a plugin update with each core minor release. Plugin
routes follow the built-ins in workflow and umbrella schemas, so built-in
schema positions and their guidance do not move when plugins are installed.
Workflow guidance for an embedded plugin route stays pending in the core.
`schemaxis reference` refuses to rewrite the core `docs/generated` while
plugins are loaded; use `--output-directory` to generate a plugin's reference
in its own repository.

Test a plugin without installing it by patching
`schemaxis.adaptors.registry.plugin_entry_points` and calling `load_registry()`,
or by placing a `*.dist-info` folder with `entry_points.txt` on `PYTHONPATH` in a
fresh process, as `tests/unit/test_adaptor_plugins.py` does.
