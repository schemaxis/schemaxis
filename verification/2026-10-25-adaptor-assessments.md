# Adaptor strength query host acceptance — 25 October 2026

Scope: the registry-based editorial assessment service, 41 adaptor-owned
`assessment.json` resources covering 47 authorable document routes, discovery and
capability summary projections, CLI JSON/text queries and baseline comparison,
validation, maintenance tooling and documentation. This is the first scored
baseline, not a new runtime qualification or an adaptor implementation allocation.

The two scores are subjective, rounded to five points and deliberately use
separate denominators: whole-application breadth and abstraction within the named
supported workflow slice. All records include scope, rationale, estimate
confidence, assessment date/version, source identity, evidence and limitations.
The rubric, score tradeoffs and maintenance instructions are in
[adaptor assessments](../docs/adaptor-assessments.md). The historical programme
assessment links to this replacement without rewriting its dated conclusions.

## Focused host checks

Run from the repository root with `PYTHONPATH=src`:

| Check | Observed result |
| --- | --- |
| `python3 -m unittest discover -s tests/unit -p test_adaptor_assessments.py -q` | 20 passed |
| `python3 -m unittest discover -s tests/unit -p test_progressive_capabilities.py -q` | 19 passed |
| `python3 -m unittest discover -s tests/unit -p test_adaptor_plugins.py -q` | 20 passed after repairing framework protocol reservations |
| `python3 -m unittest discover -s tests/unit -p test_cli_discovery.py -q` | 7 passed |
| `python3 -m unittest discover -s tests/unit -p test_catalogue.py -q` | 4 passed |
| `python3 -m unittest discover -s tests/unit -p test_adaptor_completion.py -q` | 11 passed |
| `python3 tools/generate_adaptor_assessments.py --check` | Passed |
| `git diff --check` | Passed |

The initial plugin-suite failure identified three missing reserved framework
document stems (`adaptor-assessment`, `adaptor-assessments`, `strength-rubric`).
Those stems were added to the existing reservation set and the complete focused
plugin suite passed. No assertions were weakened.

The new tests exercise independent invariants: provider counts versus versioned
routes; corruption of builtin and external-plugin editorial metadata without
removing registration, changing planning or hiding inventory; absent and stale
records; invalid precision/scope/date/reference data; source and route changes;
portable fingerprints through zipped package Traversable resources; immutable
catalogue snapshots with revision changes; comparison with changed denominators
and inventories; blocked native imports during actual CLI calls; generated-file
drift and refusal to overwrite a historical baseline.

## Review corrections and regression controls

Filtered current queries now retain explicit selection provenance and compare
only requested baseline providers. A full baseline's unrequested providers are
listed separately, rather than reported as removals. Filtered baselines likewise
do not manufacture additions in a later full query. Full-inventory comparison
still reports real additions/removals. Baselines without selection provenance
are refused rather than interpreted as evidence of inventory changes.

The shared host suite now compares the actual generated index with the live
report. This regression failed against the old index after metadata/source-scope
changes, then passed after regeneration. The authoritative completion checklist
now requires assessment review, source-freshness handling and generated-index
checks in its maintenance and testing steps. Unreviewed scores can remain visibly
stale; bug fixes and extra tests do not imply higher strength.

Further focused regressions cover all resource extensions (including native
HTML/JSX/GDScript/ImageJ macro and binary files), non-mutating refusal of an
existing baseline, independent invalid state on package import failure,
whitespace-prefixed placeholders, timezone-aware future-date rejection and
historical assessed routes that remain stale without registering anything.
The first repair-regression run reproduced eight assertion failures and two
errors; those failures were repaired without weakening the new assertions.
All 81 focused tests in the table pass after integration hardening. This remains host-only acceptance.

Further integration checks reject comparison snapshots without selection
provenance, remove incomplete baseline files after generator failure and permit
a clean retry. Public generation refuses enabled external plugins before writing
the index or a baseline; ordinary inventory queries still include plugins. The
shared parity test selects builtin providers from the same registry, so a private
installed plugin cannot silently change the public index. Adaptor-local guides
remain within the fingerprint scope; repository guides outside that package are
excluded. No dated baseline or numerical score was changed for this hardening.

The wider fingerprint changes the recorded source identity for ParaView and
Premiere, whose assessment records advance to version `2026-10-25.2`. ParaView's
50% breadth remains low-confidence and is justified explicitly by a connected
set of useful functional families, alongside substantial missing families; it
is not derived from generated-operation counts. No strength score was increased
or reduced during this review correction. The first baseline is a reviewed
candidate on the same local date; future accepted dated snapshots remain
immutable and are created only under fresh names.

## Completion-contract mapping

| Checklist item | Scope and result |
| --- | --- |
| registration | Existing registry is the only provider/route authority. New framework protocol names are reserved. No native route or operation was added. |
| schema | Strict host metadata validation covers the new editorial resource and comparison input. Existing authored schemas/declarations are unchanged. |
| semantics | Closed coarse score range, explicit distinct scopes, subjective status, date/version/evidence and material limitations are enforced. Malformed editorial data becomes an independent visible `invalid` state. |
| native-mapping | Not applicable: no native setting, mapping or callable changed; references to current contracts support editorial assessment only. |
| execution | No new execution path; corrupt builtin/plugin assessment tests prove existing plans remain usable. |
| discovery | Aggregate and selected-provider CLI queries, provider/route counts and compact capability summaries use the existing registry and adaptor package resources. |
| guidance | The rubric defines low/high abstraction and whole-application breadth; per-provider workflow descriptions, rationales and limits explain every score. No authored field or Studio operation guidance address changed. |
| help | Dedicated guide, generated readable inventory, command help, discovery links and historical superseding notice added. |
| examples | Guide includes aggregate, provider, text and baseline-comparison commands. Native authoring fixtures remain unchanged; builtin/plugin planning regression uses existing fixtures. |
| tests | Focused host results above. Full host/Studio/release acceptance and independent review are separate integration gates. |
| qualification | Runtime availability and source-bound qualification remain independent and unprobed. `current` only reports no detected change in the documented adaptor fingerprint scope. |
| maintenance | Each adaptor owns its score resource; version/date/source identity detect review needs. Generator checks current-index drift and exclusively creates new dated baselines. Scope-changing comparisons suppress point deltas. |

The immutable first snapshot is
[2026-10-25-adaptor-assessments.json](2026-10-25-adaptor-assessments.json).
The current generated index can later mark individual assessments stale when
adaptor implementations change. It does not refresh historical native receipts or
advance upstream absorbed versions. These host results do not establish native
availability, latest-upstream compatibility, recognition quality, physical safety
or customer demand. Premiere's pending native qualification and the host-only
whisper.cpp editorial routes remain explicit limitations.
