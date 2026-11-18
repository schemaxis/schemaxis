# Calc table-node identity preview evidence

Copyright (C) 2026 David L. F. Gaden.

This records a bounded, host-only capability. It accepts partial renaming credit
for the four Calc source operations on `schemaxis.calc/1` only. It is not Studio,
browser, durable Console, batch or native qualification. The Calc workbook owner,
including typed column and requirement names, is not complete.

## Contract

`schemaxis.identity_rename.rename_identity` can change the `id` of a Calc
workbook's single table node for `fromRows`, `readCSV`, `fromTypedRows` and
`readTypedCSV`. The preview is digest-checked, returns a new document and leaves
the caller's input unchanged. `identity_transition.proof`, `verify` and `replay`
reproduce the same change and bind it to the admitted policy digest. The
[identity contract](../../docs/identity-authoring.md) and
[Calc guide](../../docs/calc.md#renaming-the-table-node) describe the behaviour.

- **Closed non-graph admission.** Calc declares `graph.inputs: null`. Admission
  requires a non-graph route, zero declared input ports on every operation, no
  writer operations, and closed object variants without an `inputs` property.
  Graph routes and existing policies keep the literal input-container rule.
- **No invented inputs.** The preview never adds an `inputs` container. A node
  with any property its closed variant does not declare refuses at that property.
- **Strict names.** Existing and new names follow the planner's whole-string rule:
  an ASCII letter, then up to 63 letters, digits or underscores. The schema and
  policy pattern end with `(?![\s\S])`, so a final line break is refused. A final
  `$` alone would accept it under Python search semantics.
- **Source-data immutability.** Column labels, CSV paths, cells, requirement names
  and the fixed `Data` and `Summary` sheets keep their literal text even when they
  spell the old name. Host plans before and after differ only by the node id, and
  no authored CSV source is read.
- **Reference scope.** The policy declares no further references. Settings-bound
  expressions keep their binding, `$document` pointers keep their addresses, and a
  same-scope `$document` that reads the node `id` shows the new name.
- **Conservative refusals.** The preview refuses, changing nothing, for:
  - a downstream `$artifact` or `$value` consumer of the workbook operation;
  - a borrowed identity position in another operation;
  - an undeclared `$observe`, `$sample` or `$object` marker that could name the node;
  - an unfilled or invalid existing identity;
  - collisions, stale digests and invalid expression syntax.

## Host evidence

| Check | Result |
|---|---|
| `tests/unit/test_identity_zero_inputs.py` (all four sources, admission negatives, line-break and boundary names, workflow and design scopes, proof, verify and replay, audit-hook guard against writes, CSV reads and processes) | 26 tests passed, 0 skipped |
| Independent rerun of that module on the final production bytes | 26 tests passed, 0 skipped |
| Affected Calc, inventory and schema suites (138 tests) | Failed: 2 subtests of one generated-reference drift method failed on stale module indexes |
| Generated-reference drift method after the module indexes were regenerated | 1 test passed, by both the author and the independent reviewer |
| Earlier identity, durable, live, wire, resident and Calc suites (267 tests, run on earlier bytes) | Passed, 1 skipped; historical |
| `tests/unit/test_adaptor_authoring_inventory.py::Ledger.test_entry_points_accept_only_their_credited_routes` | Exercises each credited ledger record through the public rename and the real Calc planner, and keeps the unsupported-route refusal |

Independent review also checked a 100-case matrix: 25 name spellings across the
four sources. For every case, the actual planner, the admitted policy and the
public preview gave the same verdict. Successful renames also passed proof,
reverse proof and replay. Node.js `RegExp` evaluation of the literal pattern, with
and without the `u` flag, agreed with the planner for all 25 spellings. This is
evidence for the tested Python and Node engines, not for every JSON Schema
implementation.

## Remaining required work

- Studio Name editing, browser history and saved multi-mode membership.
- Qualification of durable Console rename for Calc. It is reachable through the
  generic operation but has not been qualified here.
- Typed column and requirement names, which need a local named-collection contract.
- Source-mode conversion and the rest of the Calc workbook owner.
- An output identity contract for downstream runtime consumers.
- Native LibreOffice ODS/XLSX qualification of renamed workbooks.
