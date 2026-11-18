# Checked core identity preview evidence

Copyright (C) 2026 David L. F. Gaden.

The statements below describe this slice at its acceptance. See the subsequent
[durable Console and geometry support](04-durable-identity.md) for its separately
scoped implementation and verification.

The pure `schemaxis.identity_rename.rename_identity` API provides partial node
renaming support. Its exact ParaView `schemaxis/1` policy covers ordinary explicit
node identities in standalone inputs and embedded workflow/design operation
scopes. It returns a cloned candidate and digest-bound change records. No saved
Name control or durable session mutation uses this API yet. See the
[contract and limitations](../../docs/identity-authoring.md).

## Scoped acceptance

Independent host review accepted the bounded pure core preview after the
reference, schema and resource-limit counterexamples were repaired and rechecked.
The final focused command
`PYTHONPATH=src:tests/unit python3 -m unittest test_identity_rename test_adaptor_authoring_inventory.IdentityPolicyDrift test_adaptor_authoring_inventory.TrackedInventory -q`
passed **44 tests**. An additional 31 before/after schema cases found no admitted
rename that made a valid fixture invalid; compatible wildcard, open-object and
recursive JSON cases were retained. Unsupported schema forms still refuse
conservatively, as the contract describes. This review does not accept durable,
resident or browser mutation, or complete adaptor authoring compliance.

## Host coverage

`tests/unit/test_identity_rename.py` exercises all 601 ordinary ParaView
declarations as both rename targets and consumers, and all 44 writer declarations
for resource-reference projection. This is host policy coverage, not native
qualification of those operations. It also checks:

- identity and consumer schema constraints (including ancestors and local schema
  references and reachable runtime marker schemas, including wildcard ownership),
  stale input, destination capture,
  duplicate namespaces, identical
  inline reuse, owner-derived descendant refusals and unchanged caller input;
- scalar/list/resource/node-port references, scene map keys, ordering, observation
  markers and checked extents calls, preserving unrelated matching strings;
- workflow scope isolation, relative and qualified document pointers, moved
  reference sites, affected borrowed typed-reference refusals, harmless metadata
  imports, contract-valid unchanged design targets and output-contract refusals;
- incomplete options and supported reference placeholders, explicit refusal for
  unresolved graph discriminators/input containers, unrelated semantic diagnostics,
  whole-input expression syntax, unresolved importing scopes, full error locations,
  bounded JSON composition and aggregate escaped provenance-address limits;
- package-local plugin admission, non-mutating invalid-policy-data faults, retained
  binding-failure quarantine, actual declaration
  changes projected without a copied operation list, and no native/session imports.

The document resolver, runtime context, workflow, workflow-fill, workflow-design
and adaptor-plugin regression suites pass with these changes. The inventory's
identity-policy drift test changes selectors, name constraints and reference
shapes while retaining the same addresses; route and applicable item fingerprints
change. Merely adding a hook does not change implementation status.

## Bounded serial pipeline preservation

`tests/conformance/test_paraview_element_multi_mode.py` passed with ParaView
5.13.3 in serial mode. Before execution, the API renamed a sphere source, its
group producer, and one published extract. The executed input retained four
independent block selections and one two-block selection. Fresh artifact
verification passed; the previous extract identity was absent from the receipt.

| Published identity | Block names | Points | Cells | X centre |
| --- | --- | ---: | ---: | ---: |
| `renamed_internalMesh` | `internalMesh` | 530 | 1,056 | 0 |
| `extractBlock_WT_wall_XP` | `WT_wall_XP` | 530 | 1,056 | 4 |
| `extractBlock_WT_wall_XM` | `WT_wall_XM` | 530 | 1,056 | 8 |
| `extractBlock_Inlet` | `Inlet` | 530 | 1,056 | 12 |
| `bothWalls` | `WT_wall_XP`, `WT_wall_XM` | 1,060 | 2,112 | 6 |

Independent artifact inspection checked every recorded file hash, multiblock
names, cell counts and decoded raw VTK coordinates against the expected bounds.
The grouped artifact spans the two wall blocks; its cell count equals their sum.
This is fresh evidence for this serial pipeline class. It does not replace the
separate global qualification record or qualify every generated operation, MPI,
resident worker reuse or browser authoring.

## Required remaining acceptance

The ledger records `extractBlock` renaming as **partial**, with the bounded core
preview **accepted**, and **not qualified** for complete authoring compliance. Applicable operations expose
their exact policy projection in the inventory without inheriting this judgement.
Other adaptors and nested identities remain unassessed until audited.

Required follow-ups include durable selection/observation/resident handle and
read-counter preservation; both local editor and workspace Undo/Redo histories;
saved row and Properties edits; simultaneous batch edits, remembered membership
and deletion protections; source-specific subset choices, authored selection
ordering and unambiguous full block selectors. Anonymous descendant preservation,
affected cross-scope borrowed recipes, inline/nested targets and runtime output
identity contracts remain explicit
unsupported boundaries. These are required support work, not immutable-name or
not-applicable exemptions. Browser and resident acceptance must precede enabling
saved-name mutation through a durable endpoint.
