# Studio native authoring follow-up — 2026-10-08

The preceding Studio/content audit was committed as `011d19e`. This follow-up
addresses the everyday reader → filter authoring workflow.

## Changes

- Shared Add forms assign editable names, infer the primary required input from
  selection and declared kinds, and provide a searchable pipeline picker.
  Names, constant operation tags and reference prose no longer obscure the
  input/options task. Snippet ID fields and prefixes are also assigned; partial
  string templates keep their remaining placeholders.
- Pipeline Duplicate/Delete work in both editors, including nested documents.
  Copies get fresh names. Deletion lists dependent nodes before removing them
  and known publication references; the whole change is undoable. Properties
  input choices exclude self and dependent nodes.
- Browse invokes a normal existing-file desktop dialog through Zenity when
  available. The in-app folder browser remains a fallback. No shell command is
  constructed from the selected path and files are not uploaded or copied.
- ParaView-owned reader preparation detects OpenFOAM case layout, available
  regions, fields and time. Defaults become explicit authored settings; user
  choices and existing document times are preserved. Native runtime defaults
  themselves are unchanged.
- Curated Extract Block offers a named native hierarchy with checkboxes in Add
  and Properties. Selected native paths are written automatically. Inspection
  prunes unfinished downstream nodes and uses an isolated worker, protecting
  the displayed live preview. Port selection is validated by the native backend.
- Schema annotation now separates aliased schema dictionaries, fixing help
  addresses/descriptions that could previously overwrite one another.

## Evidence

- 92 targeted Python host tests: Studio catalogue/library/templates/schema/help,
  HTTP authentication and jobs, native-free adaptor boundaries, input browsing,
  upstream pruning, and shared live transport contracts.
- 34 JavaScript unit tests: name/connection defaults, kind filtering, collisions,
  references, dependent deletion, nested scope, fill markers, editor insertions
  and schema/property handling.
- Nine browser acceptance tests across Add catalogue, OpenFOAM guidance, native
  pipeline authoring, spatial controls, comprehension and fill workflows. These
  use real Studio servers and headless Chromium; the native-authoring test uses
  a generated analytic OpenFOAM mesh/fields and the configured ParaView.
- Two new native serial acceptance tests on ParaView 5.13.3: hierarchy selectors
  really extract a smaller nonempty dataset; active preview inspection is
  rejected without changing its status; filename setup yields real regions,
  arrays and an available time while preserving explicit settings.
- Packaged Help regenerated and checked: 952 topics. Whitespace and Python
  compilation checks pass.

The complete browser case chooses a file, receives `foam1`, automatically connects
`extractBlock1`, checks the real `walls` block, reopens its Properties chooser,
changes and undoes selection, duplicates and deletes nodes, cancels dependent
deletion, confirms it, and undoes it. Final authored input passes validation.
Browser interaction with the OS chooser is stubbed; the Python chooser contract
tests check native argument construction, selected existing files, cancellation,
unavailability and invalid paths. A physical desktop dialog was not automated.

## Scope

Inspection is serial, configured-native and limited to one explicit state,
200 upstream nodes and 10,000 hierarchy entries, without authored plugins or
publications. This is not MPI/large-case qualification. The generated case is an
analytic fixture, not a solver result or private customer dataset. Only curated
`foam` receives automatic reader preparation and curated `extractBlock` receives
the hierarchy widget; shared naming, pipeline references and editing are
adaptor-independent. Other adaptors' native property-domain widgets remain
separate work. Existing broader content-audit limitations still apply.
