# Preserved adaptor concepts and GUI guidance — 2026-10-07

All 13 registered adaptors now carry versioned, data-only guidance.json files.
The inventory covers every declared operation and every literal schema address
of every registered route, including secondary Blender render and FreeCAD
assembly models. Schema traversal includes definitions, alternatives, objects,
arrays and map entries. The audit distinguishes reviewed, reference and pending
text, and detects stale operations, routes and schema addresses.

The initial corpus contains 5 reviewed entries, 4,835 reference entries and
22,978 pending records. These are records, including structural schema nodes,
not unique scientific concepts. Address completeness is not prose completeness.
Uncertain meanings were not invented. Existing capability purposes, assumptions,
examples and application requirements are projected into forms with provenance.

Shared guidance reaches Add forms and property Help; descriptions remain through
authored schema wrapping for editor hover/schema views. The ParaView foam help
moved out of its Python hook into the preserved corpus. Its camera and appearance
entries reuse annotated schema fields. Literal projection now ignores annotated
runtime alternatives correctly. Non-graph node adaptors gain complete projected
Add catalogues; non-node controls and secondary routes use their actual schemas.

Users can copy scoped help requests. tools/studio_guidance.py seeds without
replacing existing records, audits coverage, exports pending review subsets and
validates/merges contributed records. Unknown/stale targets are rejected before
any contribution files are written. The full review is in local evidence; a
six-field ParaView review subset is prepared for the current CFD authoring context.

The Studio adaptor contract, development/readiness requirements and repository
AGENTS.md now require preserving conceptual meaning during adaptor development.
The readiness check studio.guidance becomes required under --admission. Its
unknown status and the guidance audit's --check failure currently expose pending
work; existing runtime support is retained during the migration.

Checks newly run:

- Studio host suite: 55 tests passed at the migration checkpoint.
- Final guidance suite: 6 tests passed, including all-route/operation inventories,
  constraint-preserving authored annotations, non-graph/secondary catalogues,
  human merge validation and rejection of unsupported/stale requests.
- Readiness host suite: 15 passed.
- Browser-independent JavaScript suite: 160 passed.
- Final Add/foam/Schema Editor browser run: 8 passed. A separate conceptual-help
  browser check passed for an Octave form and scoped clipboard contribution.
  Add and conceptual-help checks rerun successfully after final form changes.
- Wheel build passed; all 13 guidance files and shared guidance/runtime UI assets
  present. No native processes were invoked.
- 951 packaged Help topics regenerated and freshness checked; git diff --check passed.

The first annotated catalogue browser run exposed runtime-reference alternatives
whose exact-dictionary comparison failed after annotation. The projection now
checks the actual $ref identity and the final regression passed. Complete prose
coverage, fresh native qualification and a full repository test run are not claimed.
