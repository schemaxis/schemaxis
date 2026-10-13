# Studio content and authoring audit — 2026-10-08

## Scope and result

Audited all 15 packaged recipe libraries (326 snippets, 57 templates), the
preserved conceptual-help inventory for all 13 registered adaptors, and the GUI
path from Add/search through configuration, Properties, pipeline navigation and
native previews. Reviewed the common ParaView reader/source/filter/output flow
in greater depth, especially Calculator, line sources and Stream Tracer.

The changes fix reproducible defects and improve the common authoring path.
They do **not** constitute scientific review of every property or native
acceptance of every recipe. All 383 recipes pass host planning with their test
fixtures. All registered guidance addresses exist; pending meanings remain
pending. Existing unrelated workspace changes were preserved.

## Findings fixed

| Priority | Finding and consequence | Change / evidence |
| --- | --- | --- |
| P1 | Native line geometry used `vertices`, while Studio rendering and reference resolution expect `points`. Seed lines and streamlines could disappear even after successful native execution. | Corrected the ParaView geometry payload. A real generated flow produces 21 seeds and nonempty streamlines; its payload is accepted by Studio's geometry preparation. |
| P1 | Wall-report templates extracted boundary blocks without first selecting those boundary regions in the OpenFOAM reader. Its default internal mesh could leave the intended walls unavailable. | Added explicit reader mesh-region fields to pressure-coefficient and wall-y-plus templates, distinct from ExtractBlock selectors. Removed unused pressure-template stages. |
| P1 | Cell/point assumptions and demonstration arrays could look like meaningful case settings. In particular y-plus used `RTData`, and contour offered CELLS. | Actual external array names now remain required in ParaView recipes; test arrays live in test fixtures. Y-plus exposes association and requires a case-specific acceptance limit. Contour explains conversion to point data. |
| P1 | Two GIS templates silently used Web Mercator for metric buffering. | Service-zone and parcel-centre templates require an explicit suitable projected CRS, with guidance about coordinate units and local distance distortion. |
| P2 | Generic pending annotations overwrote scoped conceptual Help while resolving schema references and constructing Properties. Existing explanations were therefore hidden. | Preserve the more informative scoped guidance in both projections; browser checks verify Calculator meaning and native binding in Properties. |
| P2 | Authored keys such as `expression`, `result`, `start` and `end` did not expose their native property relationship. | Display native bindings and readable labels in Add, Properties and Help. Calculator distinguishes Function from ResultArrayName; Stream Tracer distinguishes flow from seeds. |
| P2 | Seed placement required handwritten XYZ arrays without spatial context. | Added a shared line selector: XY/XZ/YZ bounds projection, explicit plane depth, start/end clicks, exact XYZ inputs, observed dataset bounds and 3D preview picking. Both endpoints apply atomically. |
| P2 | The original local browser offered little navigation or filtering. | Added breadcrumbs, address entry, Back/Forward/Up, Workspace/Home, local name filtering, hidden files and extension override. Handle `.foam`, `foam`, `*.foam` and compound extensions consistently. |
| P2 | Pipeline Reference and Outline both listed nodes while other document sections were difficult to find. | Pipeline owns node selection and compact connections/options; Document sections owns scenes, settings and workflow structures. Node indices are explicitly zero-based. |
| P2 | Recipe fill controls omitted supplied contextual descriptions. | Show field descriptions and available native binding captions while completing placeholders. |
| P2 | Escape in a nested selector could also close its parent configuration, discarding the larger edit. | Only the top dialog handles Escape; a file chooser can close without closing its form. Browser checks exercise both cases. |
| P3 | Many recipe descriptions were interchangeable, spatial labels were opaque, and demo paths/coordinates implied a universal setup. | Distinguished several adaptor templates, improved all flagged ParaView spatial/array recipe fields, made flow-specific coordinates/lengths/radii explicit, and moved demonstration reader paths into fixtures. |
| P3 | Copying a proposed Help improvement claimed preservation even though it only copied text. | Corrected the message to say that copying does not save or submit the change. |

## Native documentation and conceptual coverage

Read installed ParaView 5.13.3 public prototype/property documentation: 594
operation prototypes and 4,421 property records. The metadata capture executes
no filters. The host importer matches declared Python bindings, preserves
existing prose, and imports only unambiguous direct properties. XML names and
Python names are deliberately kept distinct; Stream Tracer's XML
`InitialIntegrationStep` maps to Python `InitialStepLength`.

Imported reference text into 2,684 previously unexplained fields. Added or
improved reviewed common-operation guidance: 55 records are now reviewed, up
from 5. Across adaptors there are 7,511 reference and 20,252 pending records.
Pending schema entries include 15,777 structural records, 516 discriminators
and 3,958 named fields; one operation also remains pending. Counts include
repeated routes and structural concepts, not just unique scientific parameters.

The import does not promote native qualification. Nested proxy documentation,
method/command explanations and other adaptor meanings still need targeted
review. See [the contribution guide](../docs/studio-guidance-review.md).

## Complete recipe inventory

Every row below was loaded, instantiated with fixture values and host-planned.
The last column counts recipes flagged by the repeatable editorial heuristics:
repeated text, demonstration path defaults or missing spatial/array descriptions.
Flags are review candidates, not an assertion that the recipe is incorrect.

| Library | Snippets | Templates | Editorial candidates remaining |
| --- | ---: | ---: | ---: |
| aseprite | 13 | 3 | 6 |
| blender | 47 | 5 | 11 |
| calc | 8 | 3 | 6 |
| cantera | 8 | 3 | 3 |
| ffmpeg | 6 | 2 | 3 |
| freecad | 44 | 6 | 21 |
| gmsh | 15 | 4 | 4 |
| godot | 22 | 4 | 17 |
| ngspice | 12 | 4 | 8 |
| octave | 15 | 3 | 5 |
| paraview | 100 | 10 | 0 |
| qgis | 15 | 3 | 9 |
| workflow | 10 | 3 | 3 |
| workflow-design | 5 | 2 | 0 |
| **Total** | **326** | **57** | **100** |

Zero editorial flags is not proof of complete semantic quality. Examples still
need native data of the appropriate type. In particular no new native acceptance
was performed for the GIS template edits or the other non-ParaView libraries.

## Remaining work, in priority order

1. **Upstream-aware array and region selection (P2).** Recipe fill has existing
   observation suggestions, but Add configuration does not yet consistently
   filter array names/associations/components by the chosen input port. Expose
   actual reader region names separately from composite block selectors. Never
   use a successful host fixture as evidence that a user's array exists.
2. **Preview before a complete pipeline exists (P2).** The selector consumes an
   explicit saved preview. It does not partially execute just upstream nodes of
   an incomplete template, attach to a ParaView desktop session, or update seed
   coordinates dynamically. Preview the source first or enter bounds manually.
   Nested workflow-operation workbenches currently offer manual placement only.
3. **Scientific/editorial coverage (P2).** Continue with the 3,958 pending named
   fields, prioritising operations users actually select. Native prose is useful
   evidence, but not a substitute for units, conventions, prerequisites and
   meaningful omission/default behaviour. Review repeated non-ParaView recipe
   text and sample input paths; output paths are often intentional defaults.
4. **Legacy recipe targets (P2).** Several older scene/appearance/output snippets
   target `/scenes/0` or a node named `source`. Their prerequisite text warns of
   this; migrate them to explicit target selectors like those in the newer Add
   catalogue. Do not silently modify the first scene when another is selected.
5. **Stable guidance identity (P2).** Numeric `oneOf` schema addresses can still
   point to a different concept after reordered alternatives, even if the
   address remains valid. Add binding/discriminator fingerprints and a migration
   check; the current stale-address audit only detects missing addresses.
6. **Spatial placement coverage (P3).** The reusable selector currently pairs
   line endpoints, including native Point1/Point2 proxy objects. Plane corners,
   clipping boxes, sphere radii and camera controls would benefit from their own
   declared spatial widgets. The 2D view is a bounds projection, not a live mesh
   cross-section; 3D picks existing surfaces/edges/vertices, not fluid interiors.
7. **Large-folder browsing (P3).** Navigation/filtering is improved, but the
   backend retains the 2,000-entry limit. Pagination or server-side search would
   help very large data folders.

## Verification performed

- Complete recipe audit: **383/383 host plans pass**, no stale guidance addresses.
- Python Studio suite: **59 tests pass** before the final recipe/documentation
  refinements. The expanded input-browser suite was then run separately:
  **3 tests pass**, including compound suffixes and invalid extension types.
- Targeted JavaScript suite: **34 tests pass** across geometry selector math,
  operation forms, document navigation, formatting, fill and library behaviour.
- Real-server Chromium checks pass for compact comprehension, conceptual Help,
  OpenFOAM guidance/file selection, line placement and snapshot/3D picking.
  The final selector tests also cover a dataset literally named `preview`,
  cancellation and keeping the parent configuration open.
- Bounded ParaView serial checks: composite geometry edge contract and the new
  generated streamline-placement example both pass. The latter also passes its
  native payload through Studio geometry preparation. An independent native
  observation recorded 21 seed points, 441 streamline points and 42 cells for
  the chosen generated flow. These numbers are example-specific.
- Packaged Help regenerated: **952 topics**, freshness check passes.
- `git diff --check` passes. No full repository suite, MPI qualification or
  native execution of every packaged template is claimed.

## Reproduce and inspect

```sh
PYTHONPATH=src python3 tools/audit_studio_content.py --output evidence/studio-content-audit.json
PYTHONPATH=src python3 tools/generate_studio_help.py --check
node --test src/schemaxis/studio_ui/tests/studio-audit.browser.test.mjs
```

The full per-recipe results and pending-field addresses are in local
`evidence/studio-content-audit-2026-10-08.json`. Native metadata and bounded
observations are retained in `evidence/paraview-property-context-2026-10-08-names.json`,
`evidence/streamline-native-2026-10-08.json` and
`evidence/probe-line-native-2026-10-08.json`. Bulk evidence remains git-ignored.
No private historical session material was added to the repository.

Use [the Studio guide](../docs/studio-guide.md#place-a-stream-tracer-seed-line)
and [generated flow example](../examples/studio/streamline-placement.json) to
exercise the new placement path.
