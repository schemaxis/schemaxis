# Distribution boundary

Schemaxis core and Studio use Apache License 2.0. Third-party material retains
its own notices and licences in `NOTICE` and `LICENSES/`.

## Included in the core

- Declarative inputs, discovery, planning, execution and verification.
- Studio, authored workflow templates, ordinary local case files, saved
  execution receipts, resume and basic scheduling.
- Explicit inspection, backup, archive and restore of selected local cases.
- Geometry, meshing, post-processing and general-purpose application adaptors.
- Database adaptors that treat a database as a workflow input/output application,
  such as SQLite summaries, and table interchange through Apache Arrow.

These features remain available without any private service or plugin. A saved
JSON state file or a workflow receipt does not itself introduce an integrated
case-history database.

## Maintained separately

An integrated database service would own a durable catalogue across cases and
workflows: ingestion and indexing of runs, historical parameter/result queries,
cross-case relationships, retention and reuse of accumulated workflow knowledge.
That service belongs in a separate repository and distribution. It is not
implemented or bundled in the 0.4.0 public preview. Core must not import it,
require its database, or include its credentials or customer data.

CFD solver execution and CFD-specific boundary conditions and case preparation
also belong in separately distributed integrations. Geometry and mesh generation,
including mesh groups, and reading CFD results for post-processing remain in core.

Separately distributed application adaptors use the existing
`schemaxis.adaptors` entry-point mechanism; see
[adaptor development](adaptor-development.md). A future database service should
consume documented inputs and retained artifacts or use an explicitly designed
extension interface. No database-service plugin API is promised by this release.

## Release checks

Build the public wheel and source distribution only from this repository. Check
both with `tools/release_gate.py`, retaining the third-party notices. Install the
wheel into a fresh environment and check that core discovery works without
private packages. Keep commercial terms, private repositories, customer data,
machine configuration and bulk local execution evidence out of public artifacts.

Contributions follow `CONTRIBUTING.md`. Separate components keep their own
licensing terms; the core licence does not grant rights in those components.
