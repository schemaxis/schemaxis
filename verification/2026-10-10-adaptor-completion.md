# Adaptor completion framework verification — 2026-10-10

Scope: application-independent completion admission, scaffold, discovery projections,
offline guidance/Help links and search acceptance. Representative node integration:
Gmsh. Representative document integration: ngspice. Native behaviour is unchanged.
The canonical checklist is [adaptor completion](../docs/adaptor-completion.md).

## Review scope

Registration, schemas, semantics, native mapping, execution and independent native
verification are preserved from the existing bounded integrations. This change
reviews their documentation/search authoring path, not a new upstream release or
native qualification. Existing explanations retain reviewed/reference status and
provenance; no mass-generated prose was promoted. Fields, defaults, nested circuits,
inputs/outputs, examples, assumptions/limits and recovery remain in guidance and
the linked [Gmsh](../docs/gmsh.md) and [ngspice](../docs/ngspice.md) guides.
Search phrases use domain terminology already supported by the declared operations.
Gmsh's cuboid/STEP/tetrahedralisation terms distinguish construction, import and
meshing. ngspice's Bode/charging/voltage-sweep terms distinguish AC, RC step and DC.
Ambiguous phrases intentionally find multiple operations; negative cases do not
promise unsupported flow solving or digital logic. Public API links remain
attributed, syntax-checked offline; external availability/relevance was not retested.

No new native support, runtime availability or latest-stable compatibility is
claimed. Pending review questions and provenance remain honest. Native examples
and maintenance recipes remain applicable only to their recorded bounded scope.
Source digests change with shared sources and metadata; old receipts may become
stale without changing runtime execution support.

## Checks and migration audit

The audit covers 18 adaptors, 20 routes and 771 primary operations. Gmsh and
ngspice pass the stronger completion gate; 18 other routes remain incomplete.
All routes preserve their existing development bundles and host conformance
obligations. Ordinary registry discovery/planning/execution remains available.


| Adaptor | Operations without curated terms | Other completion gaps |
| --- | ---: | --- |
| aseprite | 8 | scoped review record, application purpose/terms, search acceptance cases |
| blender | 37 | scoped review record, application purpose/terms, search acceptance cases |
| calc | 2 | scoped review record, application purpose/terms, search acceptance cases |
| calculix | 0 | scoped review record, application purpose/terms, search acceptance cases, Studio library |
| cantera | 3 | scoped review record, application purpose/terms, search acceptance cases |
| ffmpeg | 2 | scoped review record, application purpose/terms, search acceptance cases |
| freecad | 13 | scoped review record, application purpose/terms, search acceptance cases |
| gmsh | 0 | No objective completion gaps in this scope |
| godot | 13 | scoped review record, application purpose/terms, search acceptance cases |
| inkscape | 0 | scoped review record, application purpose/terms, search acceptance cases, Studio library |
| ngspice | 0 | No objective completion gaps in this scope |
| octave | 11 | scoped review record, application purpose/terms, search acceptance cases |
| paraview | 649 | scoped review record, application purpose/terms, search acceptance cases, purpose for pvMultiResGenericIO |
| premiere | 1 | scoped review record, application purpose/terms, search acceptance cases |
| qgis | 5 | scoped review record, application purpose/terms, search acceptance cases |
| r | 1 | scoped review record, application purpose/terms, search acceptance cases, Studio library |
| shotcut | 1 | scoped review record, application purpose/terms, search acceptance cases |


Across the catalogue, 751 operations have no curated keyword list. That objective
count does not judge their existing descriptions or the adequacy of prose. All
existing guidance addresses/statuses and resolvable local provenance pass the
strengthened audit. Twelve ParaView citation occurrences were mechanically formatted
as URL plus parenthesised native method, preserving their attribution and prose.
No scientific explanation was generated or promoted during this work.

The old ten-step scaffold list and separate Studio acceptance list now point to one
canonical checklist. New `guidance.json` skeletons inventory exact node/document
schema addresses with pending questions; Studio starters/snippets are explicitly
unimplemented. Search metadata projects through the actual capability, Studio and
Help paths. Search tests retain each surface's matching and ordering behaviour.
Packaged guides reuse readiness metadata or the adaptor-owned Studio `helpGuide`,
which preserves ParaView's existing default user guide without a shared app map.

## Checklist evidence for representative integrations

| Checklist item | Evidence and review boundary |
| --- | --- |
| registration | Gmsh/ngspice manifest routes and existing support decisions; registry and native-free admission tests. |
| schema | Existing typed node and circuit schemas; scaffold inventories; schema/parser and Studio coverage tests. |
| semantics | Existing exact-fault valid/invalid fixtures; fresh host conformance for both routes. Scientific constraints are preserved, not independently rederived here. |
| native-mapping | Existing declarations and `development.api` links preserved. URL syntax checked offline; no new mapping or upstream API review claimed. |
| execution | Existing isolated runners/verifiers unchanged. Host tests exercise entry-point/fixture boundaries; no new native success claimed. |
| discovery | Five adaptor-owned phrases per integration, including synonyms, multiword, ambiguous and negative cases; actual CLI/agent/Studio paths exercised. |
| guidance | Preserved reviewed/reference operation and nested field explanations; pending scaffold records; provenance and stale-address checks. Editorial/scientific judgement remains explicit. |
| help | Every representative Add operation resolves its own packaged topic; browser inline references; local file/anchor/JSON-pointer checks and generated drift tests. |
| examples | Existing editable Gmsh/node and ngspice/document workflows plus Studio starters plan. Browser document selector preserves the circuit while replacing the operation. |
| tests | New malformed/pending cases, misleading matches, local-link/Help failures, drift checks and host/Studio regression results below. |
| qualification | Fresh host-only receipts; 18 registered native route receipts are stale after shared-source changes, two are unknown (case preparation and Premiere). No native receipt was refreshed or silently promoted. |
| maintenance | Existing upstream policies, absorbed versions and native recipes unchanged; new checklist links the maintenance duties. No new release absorption or latest-stable compatibility claim. |

No core completion item is waived. Unsupported features remain explicitly scoped
in each development bundle; runtime unavailability is not a not-applicable pass.
The review is bounded to these authoring/discovery changes and the preserved
representative materials, not a mass re-review of every existing integration.

## Checks run

- Final complete host suite: `PYTHONPATH=src python3 -m unittest discover -s tests/unit -v` passed all 1,267 tests with 31 existing skips. Full transcript: `evidence/adaptor-completion-host-tests-final.log`. This rerun used the final library schema and full-address provenance assertions.
- `git diff --check` passed. Work stayed on `main`; unrelated website edits and untracked files were preserved. Nothing was pushed.
- Representative completion admission: `readiness --app gmsh --app ngspice --admission --check` passed.
- Fresh CLI host conformance for `schemaxis.gmsh/1` and `schemaxis.ngspice/1` passed; receipts are under `evidence/adaptor-completion-01a12869/` and are explicitly host-only.
- `tools/studio_guidance.py --check` passed for 18 adaptors and the two shared guidance owners, including local provenance and stale-address checks.
- `schemaxis reference --check` verified 71 generated artifacts; ParaView reference `--check` passed; packaged Help `--check` verified 989 topics.
- Studio broad run: 236 tests, 228 passed, five failed, three skipped. Failures exposed two obsolete assumptions (13 adaptors and all fixtures being schema-valid), an introduced default Help-guide regression, and editor timing under parallel load. The stale tests now compare the registry and adaptor-owned schema expectations; the Help guide is preserved through adaptor metadata.
- Focused serial Studio recheck: all 38 tests passed, including the editor timing test, both shell themes, generated Help, realistic search cases and representative rendered Add/contextual Help. Three broad-suite skips are native/browser-setup tests and are not counted as qualification.

Native acceptance was not run: no native execution behaviour changed. External
page availability/relevance and complete scientific/editorial re-review were not
performed. Wider prose/search-case/Studio-library migration is intentionally left
as the explicit bounded queue above. Keep the full audit and bulk transcripts in
`evidence/`; this note retains the compact reviewable result.
