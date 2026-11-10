# Shared local results viewer — 2026-11-05

The standalone artifact viewer and Studio now use the same browser assets,
collection library and streaming media transport. Case Runner embeds the complete
completed-run collection; native Workbench runs/previews open Results while
retaining Workbench's reference/picking panels. Studio's existing running process
must be restarted to load these backend changes.

Implemented:

- Light, dark and system themes. Studio and embedded viewers synchronise theme
  changes in both directions. Standalone theme/sidebar settings persist with
  recent folder references across server launches.
- A local directory chooser with explicit Open and Add folder actions. Open
  replaces; Add appends. Paths, not media bytes, are submitted to the loopback
  service. Folder actions avoid the browser's directory-upload confirmation.
- Include subfolders controls the displayed level. A folder tree, breadcrumbs,
  relative file paths and child-folder navigation retain access to descendants
  and empty folders. A browser-only directory-handle fallback remains available.
- All outputs in a scrolling gallery, type/group filters, responsive row/sequence/
  collection checkboxes with mixed states, individual checkboxes and global
  Select everything / Deselect everything. Hidden previews retain filenames.
- A collapsible sidebar for collections, folders, recent runs and recent
  collections. Schemaxis membership markers identify standalone run folders;
  Studio hands off known publication digests and inventories metadata companions
  and supporting files without changing run output paths or artifact indices.
- Media byte ranges, selected-file snapshots, digest checks on known Studio
  publications, metadata matching and independent spatial-frame boundaries.
  This presentation does not independently verify every supporting file or add
  scientific meaning absent from metadata.

Verification:

- 19 JavaScript/model/browser checks pass, including the real local folder
  chooser, Open/Add semantics, same-named folders, refreshed metadata, empty
  folders, scrolling beyond 120 files, shallow folder navigation, types, recent
  collections, responsive row selection, pinned location, 3D textures and Studio
  theme synchronisation.
- Eight viewer HTTP/library checks and 21 Studio HTTP checks pass. The case
  workflow handoff test uses the existing host native fixture and confirms that
  actual workflow output, companion metadata, authored input and receipts reach
  the shared inventory; changed publications block restoration. The complete
  14-test case suite passed with one optional YAML test skipped.
- Runner unit/browser checks and existing Workbench browser checks were run.
  One Workbench save timed out under concurrent load and passed in isolation.
  Native FreeCAD acceptance remained skipped; no native scientific application
  acceptance is claimed here.
- The broad host run completed 1,989 tests with 33 skips. Its only failures were
  two generated module-index comparisons for the new Studio module. The indexes
  were regenerated and the generated-reference drift check then passed. The
  broad suite was not repeated after that generated-document correction.
- Light/dark desktop and narrow layouts were visually inspected. The live local
  viewer and its path chooser were exercised. Wheel packaging, packaged-source
  checks, release scanning and whitespace checks were also performed.
