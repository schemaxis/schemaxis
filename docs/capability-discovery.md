# Progressive capability discovery

`schemaxis capabilities` gives humans and agents a shared, host-only service for
finding current operation contracts. It reads installed adaptor manifests and
executable declarations. It neither starts applications nor treats native inventory
entries as executable operations. Existing `discover`, `query`, `describe` and
`schema` commands retain their behaviour.

```sh
PYTHONPATH=src python3 -m schemaxis capabilities browse
python3 -m schemaxis capabilities browse domain/geometry
python3 -m schemaxis capabilities browse group/freecad/solids
python3 -m schemaxis capabilities describe operation/freecad/box

python3 -m schemaxis capabilities search 'plane' --scope domain/data-analysis
python3 -m schemaxis capabilities search 'extrusion' --input-kind profile --output-kind solid
python3 -m schemaxis capabilities describe operation/paraview/slice --section schema --section requirements
```

Use `PYTHONPATH=src` for each command when running from an uninstalled checkout.
Application navigation covers every primary-route operation in the registry. The
purpose maps cover all 771 declared operations across eighteen adaptors. ParaView
combines curated guidance with attributed native documentation; its generated
bindings remain distinct from native-qualified operations. Domain grouping is
deliberately incomplete. Search uses case-insensitive AND substring matching
against IDs, purposes, native names, adaptor keywords and curated keywords. Results
are ordered by canonical ID, not relevance. Kind facets match declared kinds
exactly; missing kinds are `unknown`, not inferred from application names.

See [discovery authoring](adaptor-discovery-authoring.md) for application metadata,
shared Studio/Help projections, acceptance cases and each surface’s exact matching
and ordering behaviour.

Application summaries also expose route counts and compact links to adaptor-owned
[strength assessments](adaptor-assessments.md). The two subjective percentages use
different explicit scopes: whole-application breadth and abstraction within the
supported workflows. `schemaxis assessments` returns full rationale/confidence and
evidence; `discover` includes aggregate provider and route counts. Editorial
assessment status remains independent of runtime/qualification status.

## Identity, links and bounded listings

Canonical IDs are `app/PROVIDER`, `domain/DOMAIN`, `group/PROVIDER/GROUP` and
`operation/PROVIDER/OPERATION`. The operation segment is percent-encoded. IDs do
not change with labels or category membership. Groups can share a leaf, and
operations always have an application parent. Additional document routes, such as
assemblies, remain available through existing exact-version schemas and commands;
this first catalogue does not invent operation contracts for them.

The default root lists application and domain summaries. Browse/search pages
contain at most 12 items and 8,192 UTF-8 bytes, measured using the CLI's indented
JSON encoding including its newline. Set `--limit 1..100` and
`--max-bytes 2048..65536` to change these bounds. A complete summary is never cut
in half. If one cannot fit, a structured fault suggests increasing the budget or
direct lookup. The full catalogue is still loaded internally; the response bound
is not a claim of constant host memory or startup cost.

`page.nextCursor` is opaque. Repeat the same action, scope, query and facets with
`--cursor VALUE`; page size may change. `page.hasMore`, `total` and `returned`
make remaining results explicit. Pages are deterministic within a fixed snapshot.
Cursors bind to the catalogue revision and request. Stale, malformed and mismatched
cursors produce distinct, recoverable faults rather than silently restarting.
`--revision VALUE` also protects browse, search, describe and schema requests.

Canonical IDs permit direct access without traversal. A unique label is accepted
as a convenience; ambiguous labels such as `box` return canonical alternatives.
Unknown paths return a parent, nearby IDs and a suggested search. Discovery faults
use the normal structured fault envelope and CLI exit status 1.

## Complete details and schema fragments

Operation detail has five separately retrievable sections:

- `declaration`: the complete authoritative declaration, including ports, options,
  defaults, checks, requirements, native bindings and any coverage annotations.
- `schema`: the existing literal option schema, plus the authored document schema's
  digest, full export command, bounded browse command and selected node pointer.
- `requirements`: declared input ports, runtime family, executables, execution
  scope, curated semantic notes and the need for planning/native verification.
- `examples`: available embedded documents or repository references, explicitly
  separate from native qualification. Empty means no curated example is registered.
- `provenance`: authoritative binding paths, documentation and identity scope.

`describe --section NAME` can be repeated. Complete sections have **no hard byte
cap** and are never silently truncated; select only needed sections. The current
operation option schema describes literal options, not a whole authored document.
Required structural constraints remain accessible through the linked schema and
planner. Curated prose is guidance; it does not replace planner validation.

Whole authored schemas can be large, particularly ParaView's shared graph syntax.
Use `capabilities schema` to navigate the original JSON losslessly:

```sh
python3 -m schemaxis capabilities schema operation/freecad/box
python3 -m schemaxis capabilities schema operation/freecad/box --pointer /required
python3 -m schemaxis capabilities schema operation/freecad/box --pointer /properties/output
python3 -m schemaxis capabilities schema operation/freecad/box --pointer '/$defs/composition'
```

If a fragment fits the byte budget, `mode: value` returns its exact value. Otherwise,
`mode: members` returns paged child pointers and container type. This is navigation
data, **not** a weakened or truncated JSON Schema. Follow the pointers, including
the `nodePointer` returned by operation detail, to retrieve complete constraints.
JSON Pointers use RFC 6901 escaping. Local schema `$ref` values always resolve from
the original document root: `#/$defs/composition` is retrieved with pointer
`/$defs/composition`. Never validate a fragment as a standalone schema without
resolving its references. A null node pointer means this operation has no normal
node placement, for example a scene writer; use the full declaration and document
schema to locate its role.

Schema fragments use the same page and byte bounds as browse/search. Even an
unusually large scalar is not truncated: the fault points to the existing full
`schema --authored --version VERSION` export. A client can reconstruct the complete
schema from member/value responses. Conformance checks reconstruct the FreeCAD
schema exactly. This mechanism does not prune legal alternatives or duplicate
schema declarations.

The catalogue revision hashes protocol identity, manifests, declarations and
curated metadata. It does not hash installed native binaries or planner code.
`contractDigest` additionally covers all detail sections and the linked authored
schema digest, independently of requested sections. `--known-digest VALUE` returns
`notModified: true` without sections when unchanged. Only send this digest when the
client has already cached the sections it needs. A schema digest identifies the
complete original schema, not an individual fragment. Restart the service after
changing installed adaptor code; hot reload is not supported.

## Status and verification

Four independent axes appear on operation summaries: declaration, runtime
availability, qualification and input compatibility. Entries here are `declared`;
the other three remain `unknown`. Discovery does not probe installations, consume
historic receipts as current evidence or inspect a supplied resource. Raw
qualification annotations remain available in the authoritative declaration.
Unknown does not mean unsupported, and declared does not mean runnable.

Construct ordinary JSON using the returned operation and document contracts, then
run `schemaxis plan INPUT.json`. Planning checks semantic constraints and graph
relationships that a JSON Schema cannot establish. Execute with configured runtime
locations and a fresh output directory; inspect and independently verify evidence.
A successful process alone does not establish task success.

## Python service and reproducible acceptance

```python
from schemaxis.capabilities import CapabilityCatalogue

catalogue = CapabilityCatalogue()
page = catalogue.search('extrusion', scope='domain/geometry', input_kind='profile')
contract = catalogue.describe(page['items'][0]['id'], sections=['declaration', 'requirements'])
```

The CLI and [local agent transport](agent-service.md) delegate to this service. Future GUI clients can reuse it without
creating another registry. Metadata is returned as data, never evaluated as code
from authored documents or external resources.

```sh
PYTHONPATH=src python3 tools/qualify_capability_discovery.py \
  --output-directory evidence/capabilities-host
# Optional bounded native proof, using private configured FreeCAD location:
PYTHONPATH=src python3 tools/qualify_capability_discovery.py \
  --output-directory evidence/capabilities-native --native
PYTHONPATH=src python3 -m unittest discover -s tests/conformance -p test_capability_protocol.py -q
```

The acceptance tool retains responses, plans and byte/step comparisons against flat
discovery. Its optional native proof allows two attempts with a 120-second runner
timeout per native stage, verifies a box against its analytic volume, adjusts its height
from observed volume, and verifies the revised target. It reuses registry execution
and verification. This is a bounded scripted client proof, not an autonomous-model
success evaluation or the complete M2 job/resource protocol. See the
[verification record](../verification/2026-09-27-capability-discovery.md).
