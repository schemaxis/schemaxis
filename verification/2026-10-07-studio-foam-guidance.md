# Studio pipeline reference and foam guidance — 2026-10-07

Pipeline reference is now open by default above the outline in Workbench and
above schema selection in Schema Editor. Its conceptual introduction has its own
collapsible disclosure, leaving node rows prominent.

All Add-node forms explain IDs, selected operations, settings and input
connections. ParaView's catalogue hook supplies conceptual foam help for the
marker file, case layout, regions, cell fields and skipping the initial time.
Descriptions are visible beside fields; technical constraints remain under
Schema details. No authored validation constraints or reader defaults changed.

A foam-file Browse control lists local host folders and matching files, retaining
an absolute dataset path. Its authenticated GET endpoint lists names only, never
uploads case bytes, and bounds the listing at 2,000 matching entries. Existing
artifact-byte restrictions remain separate. Relative reader paths inherit the
Studio launch working directory in existing batch and live subprocess launchers.

New verification:

- 160 browser-independent JavaScript tests passed.
- 18 Studio server tests passed, including authenticated file-list route coverage.
- 5 Add-catalogue host tests and 2 new browser/catalogue host tests passed.
- Real-server foam form check passed: visible guidance, folder navigation, suffix
  filtering, absolute marker selection, insertion and refreshed pipeline reference.
- Existing Add-catalogue browser check and compact/reference browser check passed.
- Foam form screenshot visually inspected; no browser errors or CSP violations.
- Packaged Help freshness and git diff --check passed.

The initial browser fixture clicked an offscreen Browse button; it now scrolls
before using a real pointer click. It also now waits for the editor's existing
change settlement before asserting the updated reference. No native ParaView
process was invoked and no new native qualification is claimed.
