# Conceptual-help migration and contribution

The preserved guidance inventory covers every registered adaptor route and the
shared Studio documents (`schemaxis.workflow/1` and `schemaxis.workflow-design/1`
and `/2`). Counts include schema containers, alternatives, array/map entries and
leaf fields, plus declared operations; they are not counts of unique scientific
concepts. Shared documents own their envelope and the `$` authoring-marker
definitions; their embedded adaptor documents use each adaptor's own records.

<!-- inventory:start -->
Inventory before and after the 2026-10-10 completion (0 stale in both):

| Inventory | Before: reviewed / reference / pending | After: reviewed / reference / pending |
| --- | ---: | ---: |
| aseprite | 0 / 41 / 81 | 97 / 25 / 0 |
| blender | 0 / 263 / 1,153 | 1,176 / 240 / 0 |
| calc | 0 / 42 / 0 | 14 / 28 / 0 |
| calculix | 0 / 21 / 0 | 21 / 0 / 0 |
| cantera | 0 / 16 / 20 | 26 / 10 / 0 |
| ffmpeg | 0 / 32 / 0 | 16 / 16 / 0 |
| freecad | 0 / 99 / 211 | 249 / 61 / 0 |
| gmsh | 0 / 16 / 42 | 48 / 10 / 0 |
| godot | 0 / 66 / 120 | 146 / 40 / 0 |
| inkscape | 0 / 86 / 0 | 40 / 46 / 0 |
| ngspice | 0 / 205 / 0 | 97 / 108 / 0 |
| octave | 0 / 56 / 46 | 68 / 34 / 0 |
| paraview | 55 / 6,877 / 18,336 | 17,444 / 7,824 / 0 |
| premiere | 0 / 14 / 0 | 11 / 3 / 0 |
| qgis | 0 / 26 / 44 | 54 / 16 / 0 |
| r | 0 / 34 / 0 | 11 / 23 / 0 |
| shotcut | 0 / 21 / 0 | 13 / 8 / 0 |
| workflow | not inventoried | 897 / 0 / 0 |
| workflow-design | not inventoried | 124 / 0 / 0 |
| **Total** | 55 / 7,915 / 20,053 | 20,552 / 8,492 / 0 |

The workflow and workflow-design inventories were added in this completion.
<!-- inventory:end -->

**Reviewed** records were explicitly authored in October 2026 by AI agents from
each adaptor's implementation, tests and documentation, the ParaView 5.13.3
server-manager XML and VTK/ParaView source, and official application manuals,
with the sources cited on each record. Samples of every batch were checked by an
independent AI reviewer against the same sources. They have not all been
reviewed by a human domain expert; treat them as authored explanations and use
**Copy help request** to correct them. **Reference** records carry text from
documented sources (mostly ParaView's own property documentation) with
provenance. Records whose last source is `guidance:<address>` share another
record's meaning and are refreshed by `--derive`.

Omission wording distinguishes a Schemaxis default (always assigned) from an
inherited native default. Generated ParaView operations assign nothing for an
omitted option, so ParaView's initial value applies; where ParaView may derive
that value from the input (bounds, array ranges or array lists), the help says
so rather than stating a fixed value. Open questions that need native checks or
an owner's decision are listed in the completion evidence, not hidden.

## Import installed ParaView documentation

Use the configured, matching ParaView executable explicitly; do not modify PATH.
The capture reads public prototype and property documentation without executing
filters. Run these from the repository root, substituting its configured
`pvpython` path:

```sh
PYTHONPATH=src /path/to/pvpython tools/capture_paraview_context.py evidence/paraview-context.json --properties
PYTHONPATH=src python3 tools/import_paraview_guidance.py evidence/paraview-context.json
PYTHONPATH=src python3 tools/import_paraview_guidance.py evidence/paraview-context.json --apply
```

Review the capture before applying. The importer checks operation inventory and
native version, preserves existing prose, and only imports unambiguous direct
Python-property bindings. It records XML property names for provenance, but
matches their Python names: for example XML `InitialIntegrationStep` corresponds
to Python `InitialStepLength`. Nested proxy properties still require separate
review. No native qualification or adaptor version is promoted by this import.

## Review and contribute

Run `PYTHONPATH=src python3 tools/studio_guidance.py --review evidence/guidance-review.json`
to export all pending records. Work on a small subset: delete unrelated records
from the exported copy, add `explanation`, `units`, `defaultMeaning`, `pitfalls` or
`examples`, and change `status` to `reviewed` after checking the meaning. Apply the
subset with `--apply-review PATH`; unknown operations, routes and schema addresses
are rejected before files change. Existing adaptor guidance is preserved.

A form's question mark also offers **Improve this explanation → Copy help request**.
Send that record with your prose in the chat; its adaptor, route and schema address
identify where the explanation belongs. For an operation, include the operation
name and adaptor. Native defaults and validation constraints remain authoritative.

Inventory completeness and conceptual quality are checked separately:
`tools/studio_guidance.py --check` fails while any record is pending or stale,
and `schemaxis readiness --admission` treats remaining gaps as a required
unknown. A complete inventory does not prove that every explanation is right;
keep correcting records as adaptors and native versions change.
