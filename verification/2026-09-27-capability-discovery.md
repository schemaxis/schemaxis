# Progressive capability discovery — 2026-09-27

M1 is implemented as `schemaxis.capabilities.CapabilityCatalogue`, with CLI
`schemaxis capabilities browse|search|describe|schema`. This runtime work is
separate from the authoring-workspace HTML prototype. No runtime dependency or
native operation was added, and existing discovery/query/describe/schema behaviour
is retained.

The catalogue addresses all **755 declarations across 10 adaptors**. The first
curated purpose map contains seven FreeCAD and six ParaView operations, six groups
and two domains. A group is navigation metadata, not a new execution backend.
The service never turns inventory-only native features into declared operations.

## Changes

- `src/schemaxis/capabilities.py`: registry snapshots, canonical IDs, parent/related
  links, deterministic scoped search and facets, byte/item bounds, revision-bound
  cursors, recovery faults, complete contract sections, digests and schema fragments.
- `src/schemaxis/__main__.py` and `adaptors/registry.py`: additive CLI surface and
  adaptor-owned capability metadata binding validation.
- FreeCAD/ParaView `capabilities.py` and manifest entries: small purpose maps,
  semantic guidance, embedded examples and declaration/documentation provenance.
- Unit and conformance tests, including extension through an isolated fixture
  adaptor with the built-in adaptors removed.
- `tools/qualify_capability_discovery.py`: reproducible host acceptance and optional
  bounded serial native refinement using existing registry run/verify.
- CLI/adaptor/agent documentation and regenerated module indexes. Existing schemas
  did not change.

## Checks and actual scope

The regression results are also recorded in the accompanying
[machine-readable record](2026-09-27-capability-discovery.json).

- Full repository unit suite: **645 tests run, 22 skipped, no failures or errors**
  (195.636 seconds). The skips retain their existing runtime/environment conditions;
  they are not native qualification. Log: `evidence/capability-discovery-2026-09-27/unit-final.log`.
- Progressive-discovery focused tests: **19 passed**. These cover recovery,
  ambiguous/unknown paths, page limits, cursor reuse/mismatch/staleness, section
  caching, declaration/schema parity, returned-object isolation, example planning
  and schema pointers. A complete FreeCAD authored schema is reconstructed exactly
  from byte-bounded fragment/member responses.
- Host conformance: **2 passed**, covering every declared operation. Complete
  returned declarations, literal option schemas, checks and requirements match
  existing authoritative exports. Application search reaches each operation once.
- A fresh Python process blocks native imports and process creation while exercising
  the new CLI, existing commands, schema fragments and planning a box constructed
  from the retrieved declaration. This passes without native application imports.
- `schemaxis discover` passes. `schemaxis reference --check` verifies all **46**
  generated files. Whitespace checks pass.
- The initial full unit run exposed generated module-index drift; the indexes were
  regenerated. During development, the selected-node pointer test was strengthened
  to reject a discriminator-only `if` guard and require the actual node schema.
  The final focused run passes with that correction.

Bulk command transcripts, full schemas, plans and native artifacts remain under
`evidence/capability-discovery-2026-09-27/`. The final acceptance responses and native
runs are under `verified-acceptance/`; earlier development runs are not the final
measurement record. No local runtime location is added to tracked configuration.

## Measured context and navigation

Before measuring, the default listing budget was set to **8,192 bytes / 12 items**.
These are UTF-8 bytes of indented CLI JSON including its newline, not estimated
model tokens. Complete detail sections have no hard byte cap and are never silently
truncated. A caller can request individual sections. Schema navigation is byte-bound.

| Request/path | Requests | Response bytes |
| --- | ---: | ---: |
| Progressive root | 1 | 5,365 |
| Existing flat `discover` | 1 | 32,934 |
| Root → geometry → solids → box detail | 4 | 15,529 |
| Direct box detail | 1 | 6,412 |
| Root → data analysis → sampling → slice detail | 4 | 22,559 |
| Direct slice detail | 1 | 13,315 |
| Box schema root, required fields and selected node | 3 | 5,358 |
| Slice schema root, required fields and selected node navigation | 3 | 3,077 |

The last two rows measure selected guidance; they do not claim to include every
referenced definition. The slice node response has child links because its whole
schema exceeds the default budget. Clients follow pointers and `$ref` values from
the original document root. No required constraints are deleted.

For an explicit full-schema comparison, all three paths below include the same
complete declaration, literal options schema and entire authored document schema.
Progressive detail additionally includes semantic guidance, examples and provenance.
The flat comparison assumes the operation name is already known.

| Target | Breadcrumb: requests / bytes | Direct: requests / bytes | Flat: requests / bytes |
| --- | ---: | ---: | ---: |
| FreeCAD box | 5 / 234,553 | 2 / 225,436 | 4 / 253,573 |
| ParaView slice | 5 / 19,929,767 | 2 / 19,920,523 | 4 / 19,946,746 |

The full authored ParaView schema is **19,907,208 bytes** and dominates that
comparison. Its plan response is also large (**2,076,498 bytes** for the exercised
slice). This motivates bounded schema navigation now and bounded plan/observation
summaries in M2. Neither this measurement nor the scripted proof establishes an
improvement in AI task success.

## Host planning and native proof

The acceptance client constructs a fresh box document using the returned operation
key, defaults and version, then changes dimensions to 20 × 10 × 5 mm. Host planning
passes. It also changes the plane origin in the returned ParaView wavelet/slice
example and successfully plans that real document. ParaView native execution was
not part of this new qualification.

The optional client then executes **two serial FreeCAD 1.1.3** attempts through the
existing registry. Each native stage has a 120-second timeout; there are at most two
attempts, and any failed run or verification stops the proof. Both attempts retain
authored documents, plans, native observations, publication artifacts and receipts.

1. The 5 mm-high box reopens and verifies with observed volume
   **999.9999999999998 mm³**, matching the independent analytic 1,000 mm³ expectation.
2. The client computes a revised height from returned volume to target 1,500 mm³.
   At approximately 7.5 mm high, the second box reopens and verifies at
   **1500.0000000000002 mm³**, matching the analytic expectation and requested target.

Both runs verify **three artifacts** (FCStd, STEP and STL), using the existing
geometry/reopening checks and digest verification. This is actual newly run native
evidence, separate from historic qualification. It establishes only this serial
box/refinement case, not MPI, all FreeCAD operations, a cross-adaptor handoff or a
model-driven agent evaluation.

## Limitations and next M2 integration

- Runtime availability, qualification and input compatibility remain independently
  `unknown` in discovery. The native proof does not promote the general catalogue's
  status. Source declaration annotations remain retrievable.
- Only primary document-route operations receive canonical operation IDs. Other
  routes remain available through existing commands and exact-version schemas.
- Search is deterministic keyword/facet search; task groups are a small curated
  starting set. Missing output kinds and examples remain explicit.
- Catalogue digests cover declarations/metadata, and contract digests include the
  authored schema digest. They do not certify planner code or installed binaries.
- Full declarations and schemas still load inside the host. The byte bounds apply
  to responses, not host memory or startup cost. No hot installation is supported.
- The schema-fragment endpoint returns exact pieces with original-root reference
  semantics. A fragment alone is not necessarily a standalone validation schema.
- YAML, GUI authoring, resource-specific inspection and an agent transport remain
  outside this slice. The extraction adaptor still awaits real extraction tools.

M2 should reuse this catalogue together with existing session/job ownership,
revision checks, registry execution, structured faults and verification receipts.
Add small plan/execute/observe/verify envelopes, durable resource/artifact IDs,
bounded observations, cancellation and explicit iteration budgets. Then qualify a
supported cross-adaptor handoff through declared artifacts and a deliberate agent
refinement, without a parallel execution engine or ad hoc conversion scripts. The
scripted native proof here supplies a reproducible starting case, not that complete
M2 service.
