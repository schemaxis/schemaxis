# Flat filename-property viewer collection

Replaced the earlier folder/companion-labelled acceptance collection with one
flat directory of 51 media payloads. Every payload is named by the actual shared
`OutputSequence`/`stem` implementation. Slice properties are produced by the same
`image_properties` helper used by the ParaView adaptor; no ParaView application
is imported or run by the generator.

The 36 slices cover U/p, X/Y/Z, three irregular positions and model on/off.
The remaining outputs cover photos, time frames, STL/OBJ, CSV/TSV, text and WebM.
Companions contain matching SHA-256 and spatial evidence where applicable, with
no `group`, `properties` or `sequence` fields supplying the grouping. The ordinal
ledger is excluded from viewing and packaging. README remains a support file.
All data is synthetic; no solver or native ParaView run was performed.

Browser acceptance checks the actual encoded filenames, single-folder layout,
`var → axis → model` hierarchy, intersecting var/axis/model selections, matching
selection, 36 registered planes, photo playback, text and tables/video. A separate
check removes every companion and demonstrates both `var → axis → model` and
`axis → var → model` hierarchies and a three-image key intersection. The portable
ZIP test loads the same corrected collection under isolated Python with the real
loopback server and content security policy.

The adaptor naming audit examined Python imports under all 51 adaptor manifests.
Only ParaView directly uses the shared naming helper for publication paths.
Blender and NumPy retain their existing numeric and fixed semantic basenames.
This is a static adoption audit, not native acceptance of the other adaptors.
User-authored filename decorators are not currently implemented. Documentation
now explains that distinction and how ParaView obtains fields from resolved
colouring styles, with native array-selection readback before image publication.

Checks:

- Four corrected-fixture/portable browser checks pass.
- Seven artifact naming host checks pass, including process-safe numbering and
  the mocked native publication loop producing U/p filename properties.
- Full viewer/Studio Results JavaScript suite: 36 passed, two optional external
  fixture checks skipped. The independent portable-package host check also passes.
- Release gate: zero hits. `git diff --check`: clean. Logs are recorded in
  `evidence/viewer-filename-groups`, alongside screenshots and the adoption audit.

`dist/artifact-viewer.zip` is regenerated with the corrected collection and docs.
The viewer remains independent; only fixture generation imports Schemaxis source
so it can exercise the real producer naming implementation.
