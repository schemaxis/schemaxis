# Adaptor completion checklist

This is the authoritative completion checklist for **new adaptors and every addition
or change to an existing adaptor**, including new operations, fields, routes,
publications and native options. An adaptor is a product integration: executable
contracts, native mapping, discovery, explanations, Help, examples, verification
and continued upstream maintenance all belong to its delivery.

Use this checklist with the [development kit](adaptor-development.md). Detailed
contracts below remain authoritative for their own data; this checklist does not
redeclare schemas, operations or a second registry. Record the changed scope and
item-by-item results in a compact `verification/` note, referenced by the affected
route's `readiness.json` `completion.review`. Keep bulk transcripts in `evidence/`.

## Completion items

| ID | Deliverable and authoritative source | Completion check and reviewer | Retained evidence | Legitimate not-applicable |
| --- | --- | --- | --- | --- |
| registration | Version, routes, runtime family, bounded scope, hooks and support decisions in [adaptor.json](adaptors.md). | Registry/dependency boundary and readiness checks (automated); scope review (editorial). | Host results, route IDs and support decisions. | Required for all adaptors. Unsupported optional features require explicit decisions. |
| schema | Complete typed declarations and literal/authored route schemas, including nested alternatives, arrays, maps, defaults, commands and document controls. [Schema contract](schema-guide.md). | Schema/declaration and planner parity, invalid/default cases, generated-output checks (automated); input design review (domain). | Changed addresses, host tests and generated diffs. | Node ports/graph controls only if the route is a document model; its fields still need coverage. |
| semantics | Dependency, cross-field, units, supported-subset and resource validation before native assignment. [Extension](adaptors.md) and [runtime](adaptor-runtime.md) contracts. | Meaningful exact-fault rejection and deterministic immutable planning tests (automated); scientific constraints (domain). | Valid/invalid fixtures, fault locations and rationale. | No exemption from semantic validation; individual constraints may be irrelevant with stated scope. |
| native-mapping | Public API identity, constructor/property paths, readback, ordering, native-version basis and losses. Declarations plus `development.api`; [kit](adaptor-development.md). | Mapping/readback and bounded native acceptance (automated); current API interpretation (domain). URL syntax is only an offline check. | Public sources, mapped fields, observed runtime and scoped acceptance. | An unsupported setting is excluded and documented, never advertised as mapped. |
| execution | Isolated runner, timeout/cancellation, configuration, logs, provenance, publication membership and independent reopening/verification. [Execution contracts](adaptor-runtime.md). | Host/service tests, timeout/tamper probes and native cases (automated); verifier independence/tolerances (domain). | Logs, authored/plan/artifact hashes, qualification receipt. | Native environment unavailable means **unqualified**, not complete native acceptance or a successful skip. |
| discovery | Useful app/operation purpose, distinguishing scope and curated domain terms, verbs, synonyms, acronyms, native names and user phrasing. Existing capability binding; [search authoring](adaptor-discovery-authoring.md). | Metadata/case validation, actual CLI/agent and Studio search regressions (automated); usefulness and misleading matches (editorial/domain). | Adaptor-owned search cases and observed results, including ambiguous/negative cases. | A particular synonym/acronym may be irrelevant; explain this in the review rather than stuffing every operation with generic terms. |
| guidance | Operation purpose/use, inputs/outputs, assumptions/limits and meaningful examples; every field's meaning, units/conventions, omission/default, valid choices and mistakes. `guidance.json`; [Studio contract](studio-adaptor-contract.md#conceptual-guidance-is-an-adaptor-deliverable). | Address/status/provenance/link audit (automated); prose sufficiency and scientific truth (editorial/domain). | Reviewed or attributed records, sources and unresolved questions. | Unitless fields say so where useful. Structural `$ref`/wrapper records may derive meaning with provenance. Nested and non-node fields are never exempt. |
| help | Local guide, generated reference, contextual operation/field Help, stable faults and actionable recovery, relevant public API links. [Studio contract](studio-adaptor-contract.md). | Local files/anchors, packaged operation targets and generation drift (automated); external availability/relevance and useful recovery (review). | Generated artifacts, Help tests, review source/date and fault examples. | External sources are never fetched during normal admission. Unavailable upstream pages retain uncertainty and a repair task; placeholders do not count. |
| examples | Editable standalone and Studio starters, meaningful baseline/variant and invalid cases, prerequisites and independent literal expectations. `readiness.json`, `studio.json`; [kit](adaptor-development.md). | Schema/host plan, placeholder/insert/undo/Help tests and bounded native runs (automated); realism and expectations (domain). | Example IDs, fixture files, expectation rationale and exact executed scope. | Resource/native prerequisites may prevent local execution; retain a usable host example and explicit unavailable result. |
| tests | Changed host, schema, scaffold, discovery, guidance, reference and Studio behaviour; negative, stale and misleading cases. [Conformance](adaptor-development.md#reusable-conformance). | Execute appropriate suites and generated checks (automated); coverage adequacy (review). | Actual commands, results, skips/failures and limitations. | Native requalification is unnecessary for documentation/search-only behaviour changes; shared source changes still make old receipts stale. |
| qualification | Separate implementation, documentation coverage, local runtime availability and source-bound native qualification. [Readiness axes](adaptor-readiness.md#report-contract). | Conformance/record freshness and observed runtime checks (automated); interpretation of bounds (review). | Native receipt and exact cases/features/runtime, or explicit unknown/stale/unavailable. | No receipt is legitimate for an experimental host-only route, but it must never be labelled native-qualified. |
| maintenance | Latest-stable release source, absorbed version, acceptance recipe, provenance and repair obligations in `upstream.json`. [Updates](updates.md). | Updates/host/native acceptance when absorbing a release (automated plus domain review). | Release source, repair brief, successful bounded evidence and unresolved work. | Manual upstream source checks need an explicit reason. Never advance absorbedVersion from documentation or host checks alone. |

## Recording decisions and review

Add `completion` to each changed route in its existing `readiness.json`:

```json
{"completion": {
  "scope": "Operations/routes/fields changed; what the review covers.",
  "review": ["verification/YYYY-MM-DD-someapp-completion.md"],
  "notApplicable": {"mpi": "This integration explicitly supports serial execution only."}
}}
```

`notApplicable` keys name optional `development.features` explicitly marked
`unsupported`; admission validates the reason and decision together. Record other
item-specific rationales in the review note against the checklist ID. Core duties
cannot be waived. For a later addition, update the affected records and retained
review scope; do not claim that unrelated legacy operations have been re-reviewed.
A review link proves only that evidence exists, not that its conclusions are true.

`pending` guidance/questions and search cases remain gaps. Boilerplate, native names,
generated type descriptions and placeholder URLs are not reviewed explanations.
`reference` records retain attribution and still require editorial judgement.
Normal discovery/admission stays offline, native-free and dependency-free. Native
conformance and deliberate external source review are separate steps.

## Authoring and verification sequence

1. Scaffold or identify the existing affected route. Implement declarations,
   schemas, semantic validation and native mapping together.
2. Maintain capability metadata, guidance and Studio starters during development.
   Seed addresses, edit the review subset, apply it and derive structural records
   using [guidance tooling](studio-adaptor-contract.md#conceptual-guidance-is-an-adaptor-deliverable).
3. Author realistic [search cases](adaptor-discovery-authoring.md), including
   neighbouring operations and negative assertions. Review phrases and prose.
4. Generate references and packaged Help, then run their `--check` modes. Run
   affected host/Studio tests and scoped conformance. New native behaviour requires
   bounded native acceptance; documentation-only work does not qualify a runtime.
5. Record every checklist result, justified exceptions and unresolved work. Run
   `readiness --app APP --admission --check`; failed documentation admission leaves
   existing discovery/planning/execution available. Keep wider migrations bounded.

```sh
PYTHONPATH=src python3 tools/studio_guidance.py --app APP --check
PYTHONPATH=src python3 -m schemaxis reference
PYTHONPATH=src python3 tools/generate_paraview_guide.py
PYTHONPATH=src python3 tools/generate_studio_help.py
PYTHONPATH=src python3 -m schemaxis reference --check
PYTHONPATH=src python3 tools/generate_paraview_guide.py --check
PYTHONPATH=src python3 tools/generate_studio_help.py --check
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
node --test src/schemaxis/studio_ui/tests/search-acceptance.test.mjs
PYTHONPATH=src python3 -m schemaxis readiness --app APP --admission --check
PYTHONPATH=src python3 -m schemaxis adaptor conform VERSION --output-directory evidence/APP-host
# Native changes, with a configured environment and a fresh evidence directory:
PYTHONPATH=src python3 -m schemaxis adaptor conform VERSION --native --output-directory evidence/APP-native
```

See [Gmsh](gmsh.md) (node) and [ngspice](ngspice.md) (document) for preserved
conceptual explanations and examples plus curated search cases and contextual Help.
The [completion audit](../verification/2026-10-10-adaptor-completion.md) records
current gaps and the checks run for this framework change.
