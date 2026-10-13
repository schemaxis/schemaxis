# Consistent adaptor naming

The project now uses **adaptor** throughout its own prose, paths, Python modules,
class names, manifest fields, faults and public response keys. Twenty-nine files
were renamed, including all ten `adaptor.json` manifests, implementation modules,
extension fixtures, development documentation and qualification tools. Generated
references and internal links were updated together. No dual-spelling aliases are
retained. Python consumers and manifest/query clients must use the new identifiers.
Actual third-party API names and external URLs retain their authoritative spelling.

Verification: **747 unit tests passed, 22 skipped**, 165.939 seconds. The three
architecture/extension checks pass, including isolated installation of a new
adaptor. All 47 generated references pass. A case-insensitive scan of project
source, tests, tools, documentation and verification records found no residual
use of the alternate spelling. Historical numeric evidence and source digests
were not recomputed to disguise the rename: previous source-bound native receipts
are stale and will be replaced only by fresh acceptance runs during migration.

Full unit log: `evidence/adaptor-kit/spelling-unit.log`.

Native migration subsequently caught one required external Godot API name changed
by the mechanical rename. That third-party call was restored, and both Godot
native cases plus public-agent execution now pass. Project-owned names remain
consistent; native API identifiers are never respelled.
