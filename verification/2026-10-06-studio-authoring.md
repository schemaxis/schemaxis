# Studio complete Add catalogue, Help and diagnostics — 2026-10-06

ParaView authoring now exposes all 655 declared operations plus 16 document and
presentation controls (671 Add entries). The catalogue projects literal schemas,
with application-owned scene/image/appearance targets supplied by a confined
manifest hook. Readers, generated sources, filters, writers and presentation
controls have searchable, paginated Add menus shared by Workbench and Schema
Editor. Exact title matches rank first.

Configuration forms expose required and optional fields, enums, nested objects,
arrays and proxy alternatives. Unchecked optional settings remain omitted; blank
included values become typed persistent placeholders. Required skeleton insertion,
reference suggestions, explicit scene/image/node targets, stale-input protection,
preview/undo integration and cancellation use the existing editor transactions.
Single-choice proxy discriminators are literal values. Question marks show plain
constraints and defaults; full operation Help expands inside the window.

Help starts with a Studio guide and directs application context to the appropriate
application guide or operation reference. Packaged Help contains 950 topics from
186 linked repository files. The Studio adaptor contract documents complete
catalogue coverage, forms, Help, diagnostics and acceptance requirements.

Host faults retain provenance and gain JSON pointers, source line/column and the
nearest existing source value for missing keys. ParaView scene, image, camera and
writer validators now retain list indices. Editor diagnostics and Problems show
addresses and coordinates, including Unicode-aware syntax positions.

Large authored schema export no longer recopies each descendant subtree at every
recursive level. Annotation ownership is retained and generated schema/reference
output remains unchanged. A separate workflow-design schema check produced a
6,717,969-byte JSON representation in 2.104 seconds on this workstation.

Checks newly run:

- Full Python host suite: **1,088 tests, successful; 22 skipped** (498.317 seconds).
- Browser-independent JavaScript suite: **157 tests, successful**.
- Real-server Add browser check: successful for required placeholders, optional
  radius configuration, proxy choices, inline operation Help, cancellation, undo,
  missing targets, appearance/image insertion and the shared Schema Editor menu.
  The resulting image workflow passed host validation.
- Real-server Help browser checks: successful in light and dark themes, including
  search, navigation, context, copying, unsaved source preservation and restoration.
- Packaged Help freshness check and `git diff --check`: successful.
- Wheel build: successful; current catalogue, adaptor hook, configuration form,
  Help index and packaged UI assets present; browser harnesses excluded.
- Light-theme configuration screenshot inspected for layout and readable Help.

An earlier broad run found stale generated module references and a schema HTTP
request timeout. References were regenerated and redundant schema copying was
fixed; the final full run above passed. No test timeout or verification requirement
was relaxed. These are host/UI checks, not new native ParaView qualifications.
Existing native qualification status and known coverage gaps remain visible.
