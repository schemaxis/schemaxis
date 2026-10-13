# Adaptor readiness and admission

Use the [authoritative completion checklist](adaptor-completion.md) for new adaptors
and changes to existing operations, fields and routes.

`schemaxis readiness` audits all installed adaptors and document routes using the
existing registry. It reports executable contracts, curated context, delivery
links, planner fixtures, profile claims and historical evidence. It does not
install applications, probe runtimes, fetch URLs or run native acceptance.

```sh
PYTHONPATH=src python3 -m schemaxis readiness
PYTHONPATH=src python3 -m schemaxis readiness --app octave --app ffmpeg --admission --check
PYTHONPATH=src python3 -m schemaxis readiness --repository-root /path/to/schemaxis
```

The default JSON report always returns the audit, including incomplete adaptors.
`--check` is an opt-in structural admission gate: a failed required check or an
unresolved required reference produces `ADAPTOR_NOT_READY`, exit status 1 and the
complete report in the fault's `observed.report`. Add `--admission` for new
adaptors: it also requires a valid `development` contract from the kit. Existing `discover`, routing,
planning and execution continue to accept legacy registrations. Malformed
`adaptor.json` registrations still fail with the registry's `INVALID_ADAPTOR`;
the auditor does not create a second, more permissive registry.

See the [current completion audit](../verification/2026-10-10-adaptor-completion.md)
and [earlier audit and qualification limits](design/adaptor-framework/AUDIT.md).
Octave, FFmpeg and FreeCAD established the initial bundles. Earlier migration
receipts describe the gate and source versions at that time; they do not establish
current completion or native qualification for the expanded registry. The audit remains structural; the
development kit and scoped native qualification are described in the
[development guide](adaptor-development.md).

## Report contract

The protocol is `schemaxis.readiness/1`. Every route has a stable
`route/PROVIDER/PERCENT_ENCODED_VERSION` ID. Check IDs append their stable code.
Checks include `status`, `required`, explanatory `message`, `sources`, and
`recovery` for failures or unresolved work. Status is `pass`, `fail`, `unknown` or
`not-applicable`. Example IDs are adaptor-owned stable slugs.

The independent axes are:

- `structural`: complete or incomplete for the checks implemented here. It checks
  entry-point presence, JSON-serialisable route schemas with the exact version,
  primary declaration option types, contextual coverage, fixture planning and
  delivery links. A pass does not establish the truth or sufficiency of prose.
- `implementation`: reports whether plan/run/verify entry points are present;
  their behaviour remains unreviewed by this structural audit.
- `runtimeAvailability`: unknown; no installation probe runs.
- `nativeQualification`: unknown in this structural report; no native result is
  certified by running the auditor. Use `adaptor context VERSION` for separately
  registered source-current/stale/unknown native receipts and their exact scope.
- Profile `declaration`: declared, unsupported (explicit false), or unknown
  (absent). A missing inspection hook is unknown, not proof of unsupported use.
  Profile qualification remains unknown.

`historicalQualification` preserves the owning adaptor's `upstream.json`
version, scope, receipts and acceptance instructions. Its attribution is explicitly
provider-wide and unreviewed for individual routes/profiles. Linked receipts are
checked for existence, not reinterpreted as new results or proof of freshness.

`gaps` sorts routes by failed-check count, then unknown-check count and stable ID.
It is a work queue, not a support or maturity score. Optional behavioural checks
remain unknown without preventing **structural** admission. These include native
lifecycle conformance and the completeness of artifact traits beyond kind labels.
Schema/planner equivalence over all inputs is not established by this report;
maintain the existing declaration/schema tests and add semantic fixture coverage.

## Required delivery bundle

Add `readiness.json` beside `adaptor.json`. JSON package resources are already
included in installation archives. The file names existing routes; it never
redeclares operations, schemas, runtime versions, native hooks or support flags.
The versioned bundle is deliberately strict about field names to expose typos.

```json
{
  "version": "schemaxis.readiness/1",
  "routes": {
    "someapp/1": {
      "guide": "docs/someapp.md",
      "context": {
        "purpose": "When this bounded route is useful and when it is unsuitable.",
        "assumptions": "Input conventions, units, runtime/API basis and prerequisites.",
        "constraints": "Supported subset, exclusions, losses and limits.",
        "inspection": "What to inspect, independent correctness checks and tolerances.",
        "recovery": "Meaningful failure codes, diagnosis and safe retry choices."
      },
      "examples": [
        {"id": "working-case", "reference": "examples/someapp-valid.json"},
        {"id": "bad-dependency", "reference": "examples/someapp-invalid.json",
         "expect": "invalid", "fault": "INVALID_DEPENDENCY"}
      ],
      "conformance": ["tests/unit/test_someapp.py"],
      "acceptance": ["tools/qualify_someapp.py"],
      "profiles": {}
    }
  }
}
```

All five context fields must contain text. The guide must be local. Provide at
least one valid example and one meaningful invalid example. An example can embed
`document` instead of `reference`; exactly one is allowed. `expect` defaults to
`valid`. Invalid examples must fail the **route planner** with the exact `fault`
code. Invalid JSON, the wrong document version, unavailable references and
unstructured exceptions cannot masquerade as expected semantic rejection.

Planner acceptance is not native success or resource availability. In particular,
the FFmpeg starting document contains a clearly labelled absolute placeholder;
replace it with an actual PNG before executing. Its kit cases provide a
repository-relative resource binding for repeatable native acceptance. Select self-contained examples
where possible. Existing curated capability examples are also planned, so examples
requiring unresolved resource inspection appear as gaps instead of passing silently.

Conformance and acceptance fields link maintained tests and bounded native recipes.
The audit checks the links, not test execution or their quality. A release still
needs appropriate host checks and newly recorded native acceptance when native
behaviour changes. Do not mark an unexecuted recipe as qualification.

## Existing capability metadata

Keep operation selection guidance in the existing adaptor `capabilities` binding.
Readiness validates it through the same capability catalogue and requires a
curated purpose for each primary operation. It checks registered context
references and examples. Route-level assumptions, inspection and recovery remain
in the delivery bundle, linked from capability metadata where available.

Secondary routes use their own schema and route context. The auditor does not
attribute primary node operations to an assembly or saved-scene document. The
kit adds explicit source/property authoring, live editing, native save, conversion
and other feature decisions. Neither those decisions nor the four structural
profiles below establish native qualification.

## Optional profile obligations

Support comes from existing authoritative manifest fields. Add a `profiles` entry
only for a positively declared feature, with a nonempty `scope` and nonempty local
`references` list. A profile entry for an absent or explicitly false feature fails.

| Profile | Authoritative declaration | Obligation |
| --- | --- | --- |
| `workflow` | route `workflow: true` | Describe artifact formats, ordering, provenance, losses and conformance/acceptance evidence. |
| `native-inspection` | route `inspect` or `inspectionSetup` hook | Describe representations, bounds and interpretation limits. |
| `composition` | route `compose: true` | Describe supported binding semantics and fixtures. |
| `mpi` | adaptor `executionCapabilities.mpi: true` or `mpi` in its `modes` | Supply route `validateExecution`, scoped constraints and supporting references. Serial evidence is insufficient. |

Nonempty `acceptedArtifacts` requires a workflow route and a list of kind strings.
Kinds alone never establish units, shape, format compatibility or preservation.
This audit retains that semantic gap as unknown. It does not introduce implicit
conversion or promise that a matching kind is a valid handoff.

## Link rules and migration

References are repository-relative files, optionally with a Markdown heading
slug or a Python `:function`/`:class` suffix. Python suffix checks use static AST
names; Markdown checks support ordinary heading slugs, not arbitrary HTML anchors.
Examples require complete `.json` files without suffixes. Traversal, absolute paths
and symlink escapes are rejected. External HTTP(S) context references remain
unknown and are never fetched; they cannot replace local required delivery files.

Source files and docs are not universally installed in wheels. Use
`--repository-root` with a matching checkout to check them; unavailable required
links remain unknown and prevent the structural gate from passing. A matching
checkout is the caller's responsibility, not an inferred compatibility claim.

Migrate one route at a time: add its delivery bundle, curate missing operation
purposes, link tests and recipes, then run `readiness --app PROVIDER --admission --check` and the kit conformance
commands.
Fix diagnostics without changing existing execution promises. Keep historical
qualification honest while adding fresh evidence in a separately scoped run.

GUI authoring readiness also requires the [Studio adaptor contract](studio-adaptor-contract.md): complete Add coverage, option forms, Help and located diagnostics.

## GUI conceptual-help admission

Every adaptor must preserve conceptual guidance in `guidance.json`, covering all
operations and every field of every registered route. See the
[Studio adaptor contract](studio-adaptor-contract.md#conceptual-guidance-is-an-adaptor-deliverable)
for the format and authoring audit. The readiness check `studio.guidance` reports
reviewed/reference/pending counts and stale addresses. It is required under
`--admission`; pending text does not invalidate existing runtime workflows.

## Completion admission additions

`--admission` also checks curated application purpose and operation terms,
adaptor-owned search-case coverage and actual capability matches, scoped completion
review references, guide navigation, guidance provenance, Studio recipe planning,
Add coverage and packaged guide/operation Help targets. Generated-output freshness
is checked by the separate reference/Help generators’ `--check` commands. Studio
search behaviour requires its regression suite; normal admission starts no external
processes. `documentationCompleteness` reports coverage separately from unreviewed
editorial quality. Missing completion materials remain visible gaps and never change
legacy routing or execution. Historical statements of admission in earlier evidence
refer to the gate at that time; use the current [audit](../verification/2026-10-10-adaptor-completion.md).
