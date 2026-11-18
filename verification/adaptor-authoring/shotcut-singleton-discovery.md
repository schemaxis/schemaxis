# Shotcut singleton discovery and Add bounds

Copyright (C) 2026 David L. F. Gaden.

Reviewed support is limited to singleton classification, discovery and shared
Add cardinality protection. Its implementation remains partial and not natively
qualified; this does not complete the Shotcut semantic owner.

The literal node projection now supplies the sole `operation:editTimeline` entry.
The redundant Shotcut `studioCatalogue` contribution is removed, preserving its
readable title and the operation's decision-oriented guidance. The former
`operation:editTimeline@2` inventory row and its duplicate-ID gap retire because
they described that same source operation, not a second supported timeline. The
route retains its declaration, two nested asset/clip units and all literal fields;
only its duplicate catalogue projection disappears. Custom non-node hooks in
other adaptors remain supported.

The shared catalogue projects a closed literal parent-array bound. The shared
form and insertion transaction enforce it without application-name branches.
An empty Shotcut document can Add its one timeline; a populated document receives
an explanatory refusal pointing to Edit settings. Cancellation and stale capacity
refuse without source or Undo changes. Ordinary settings edits retain the user
Name, asset order, repeated clips and unrelated options. No claim is made that
changing an existing Name through the legacy form updates references.

Host checks: `tests/unit/test_studio_collection_limits.py` covers real discovery,
declarations/guidance, parent schema derivation, forged metadata refusal, real
custom hook preservation, literal template ranges, repeated clip planning and
the bounded ledger disposition. `collection-limit.test.mjs` covers generic limits
and malformed/stale collection shapes. The real Chromium
`shotcut-singleton.browser.test.mjs` exercises the Add toolbar and existing
Settings with cancellation, refusal, stale capacity and one-step Undo. Existing
`add-catalogue.browser.test.mjs` covers unbounded multi-node Add and custom scene
entries. Independent verification passed 27 focused host tests, 3 JavaScript
tests and both real Chromium browser tests, with no skips. The complete inventory
module subsequently passed 48 tests with no skips, including a controlled
duplicate-catalogue fixture and exact review-credit reconciliation. These are
bounded host/browser results, not new native or full-owner qualification.

Only multi-mode suitability is assessed here: this is a singleton timeline with
ordered nested collections, not independent sibling timelines. Its shared Add
protection is partial authoring support. Meaningful Name suggestions, checked
timeline/local asset renaming, declared clip reference ownership, ordered nested
editing, subset provenance/gestures, batch/history behavior and current native
MLT/video/bundle qualification remain required. The trim/reorder template now
truthfully describes literal zero-based frames 3–5 followed by 0–1. Existing
planner/native behavior and historical qualification are unchanged.

## Shared bound projection scope

The current built-in runtime catalogue projects the following literal bounds.
This is 11 affected runtime adaptors out of 51 registered runtime adaptors; the
complete authoring inventory separately includes 54 owners and 67 routes. These
shared Add refusals follow existing schemas and grant no new owner or native
qualification credit. All other existing ledger records remain unchanged.

| Adaptor | Exact route | Collection | Maximum |
| --- | --- | --- | ---: |
| aseprite | `schemaxis.aseprite/1` | `/nodes` | 256 |
| blender | `schemaxis.blender/1` | `/scenes` | 1 |
| calc | `schemaxis.calc/1` | `/nodes` | 1 |
| cantera | `schemaxis.cantera/1` | `/nodes` | 2 |
| ffmpeg | `schemaxis.ffmpeg/1` | `/nodes` | 1 |
| freecad | `schemaxis.freecad/1` | `/nodes` | 200 |
| gmsh | `schemaxis.gmsh/1` | `/nodes` | 2 |
| godot | `schemaxis.godot/1` | `/nodes` | 128 |
| octave | `schemaxis.octave/1` | `/nodes` | 64 |
| qgis | `schemaxis.qgis/1` | `/nodes` | 32 |
| shotcut | `schemaxis.shotcut/1` | `/nodes` | 1 |

The Gmsh host control checks its actual registered route schema and catalogue
projection at maximum 2. The generic JavaScript checks exercise maximum 0, 1
and 2, insertion counts, unavailable/non-array parents and existing invalid
collections. Shotcut's real browser check covers singleton Add and Settings;
ParaView's existing browser check covers unbounded Add and custom scene entries.
These controls are not browser or native qualification of every affected route.

Local-reference bounds are conjunctive: a referenced maximum of 1 plus sibling
maximum of 2 still projects 1. Finite integral numeric bounds are normalized;
unsupported structural reference siblings refuse with
`INVALID_STUDIO_CATALOGUE` instead of replacing referenced properties/items.
This deliberately bounded projection supplies a necessary literal `maxItems`
ceiling, not a complete effective-capacity solver or full schema validation.
Other schema constraints can impose tighter limits. Unsupported structural
reference siblings can refuse the entire catalogue; external schema shapes are
not qualified. The host tests cover the admitted grammar without a runtime
schema solver or native imports.

## Remaining root-snippet replacement problem

The separate legacy **Trim and arrange clips** snippet inserts at the document
root. On populated input it can replace the entire source via the snippet tray
or command palette, and its preview text does not reliably disclose that
replacement. This predates the Add change and is not fixed here. It remains
required owner work: truthful replacement preview and a safe, consistent explicit
replacement action across both entry points, with cancellation and Undo checks.
The Add-cardinality guard neither covers nor grants acceptance to root snippets.
