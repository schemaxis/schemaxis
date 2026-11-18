# Root replacement review for library templates and snippets

Copyright (C) 2026 David L. F. Gaden.

This note resolves the shared library replacement gap recorded in
[shotcut-singleton-discovery.md](shotcut-singleton-discovery.md), whose text is
kept as the historical record. It is shared Studio authoring behaviour, bounded
host and browser evidence only: it does not complete the Shotcut owner, add Name
or reference-aware renaming, or qualify native output.

## Behaviour

The shared library classifies the planner's own sequential actions. The planner
annotates each resolved action with its actual effect: replacing an existing
value (including the document root), inserting a member or array item, or
merging. A request needs review only when a value replaces the editor's scope
root, or a value containing it. That covers templates, literal empty-pointer
values, migrated singular inserts, empty-object documents, root+append
composites and `@cursor` values that resolve to the scope. Root merges, ordinary
appends, YAML whole-source rewrites of nested insertions, widened JSON containers
and array insertion at the scope position are not reviewed. Labels, titles and
textual edit spans are not used.

Before any decision is awaited, the library prepares one immutable scoped
request and its planned edit, including final namespaced fill fields and
pointers. The editor owns the prepared edit, consumes it on any commit attempt,
and commits only when its text, monotonic text version, format, indentation,
owner scope and, for caret-dependent plans, caret are unchanged. Schema Editor
supplies its resolved nested base and schema; Workbench supplies its record and
operation. A JSON root replacement now replaces only the root value, preserving
surrounding whitespace and the final newline.

The review names the item, scope and document-version change, lists the planned
changes and shows the changed text before and after. Cancel is focused; Cancel,
the close button, Escape and the backdrop leave source, selection, Undo history,
recent items and fill state unchanged. A second insertion, library metadata
replacement, window deactivation or disposal closes the review without editing.
An approved review commits one draft edit; one Undo/Redo restores either end.
While a review is open, notification toasts stay beneath its backdrop so an
earlier refusal cannot cover its decisions; the refusal remains in the
notification history and reappears above the workspace when the review closes.

## Route reconciliation

`library-replacement-corpus.test.mjs` reads every projected library through the
real `StudioApplication.studio_adaptor` route filter with plugins disabled:
51 runtime providers and 62 runtime routes plus `workflow/1` and
`workflow-design/2` give 64 surfaces, including the empty Blender render and
Inkscape surfaces. Of 657 item appearances, 328 replace the root (279 template
and 49 snippet appearances, 307 unique items), 9 merge at the root, 12 use
`@cursor` (10 values, 2 merges) and 308 target other literal pointers. Every root
and cursor appearance is planned through the shared classifier as a local input
and as a nested operation whose sibling stays unchanged. Primary routes also list
owner templates for secondary versions; the review discloses the resulting
version change. A declarative plugin-shaped library, including a migrated v1
singular insert, uses the same path. Installed external plugins are not
qualified.

## Checks

```sh
node --test src/schemaxis/studio_ui/tests/library-replacement.test.mjs \
  src/schemaxis/studio_ui/tests/library-replacement-corpus.test.mjs
node --test src/schemaxis/studio_ui/tests/library-replacement.browser.test.mjs \
  src/schemaxis/studio_ui/tests/library-replacement-studio.browser.test.mjs
```

The pure tests use the actual Shotcut snippet and template. The component
browser test drives main cards, tray mouse and keyboard, the contextual section
shortcut and the command palette, all four dismissals, stale edits, format and
indentation contracts, competing previews, second invocations, metadata
replacement, disposal and YAML. The Studio test uses a named Shotcut input with
two ordered assets and repeated clips in Workbench, and a workflow design with
two Shotcut operations, another provider and outer definitions in Schema Editor.
Public editor and window APIs are used only for setup and labelled contract
changes; the invocation and decision gestures are real.
