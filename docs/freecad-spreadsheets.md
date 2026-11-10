# Native spreadsheets for editable part dimensions

Use `spreadsheet` when a part needs a visible engineering table whose input cells
and calculated lengths remain editable in FreeCAD. The table drives the same
finite `drive` targets as [native VarSet parameters](freecad-parameters.md),
including sketch dimensions, stock lengths, wall thickness and drilling sizes.
Choose either `spreadsheet` or `parameters` in one document.

The [enclosure](../examples/schemaxis/freecad-spreadsheet-enclosure.json) mixes
centimetres, inches and millimetres. Formula rows derive the outside width and
height; the resulting Body retains its Pad and uniform-wall feature history.

```json
"spreadsheet": {
  "inputs": {
    "width": {"value": 3, "minimum": 2, "maximum": 5, "unit": "cm"},
    "wall": {"value": 2, "minimum": 1, "maximum": 3, "unit": "mm"}
  },
  "formulas": {
    "outside": {"terms": {"width": 1, "wall": 2}}
  }
}
```

A node binds the calculated length with
`"drive": {"width": {"terms": {"outside": 1}}}` and omits the literal driven
option. Main CAD options and published geometry use millimetres. Each input's
value, minimum and maximum use its declared unit: `mm`, `cm`, `m` or `in`.
Coefficients are dimensionless; an optional formula offset has a numeric `value`
and one of those units. The default offset is zero millimetres.

There are at most 32 named input and formula cells. Each formula references one
to four declared aliases. Formulas may refer to other formulas; their graph must
be acyclic. The host expands dependencies to independent inputs when checking
bounds, preserving correlations between calculated cells. Every cell must feed a
driven dimension, and every independent input must have a measurable effect.
All derived lengths must stay positive and at most 100000 mm across the declared
input bounds. Numerically unrepresentable relationships are refused.

## Native editing and reuse

Open the published FCStd and double-click **Design spreadsheet**. Edit the input
cells in column B; calculated rows retain their formulas. Recompute and save to
update linked sketches, Body features and formula-driven assembly mounts. A
native edit creates a changed design: its original Schemaxis receipt does not
certify the edited file. Change the authored input and run in a new directory to
publish and verify the variant.

A verified final Body can feed [sourced assemblies](freecad-assemblies.md). Copied
tables and their dependencies remain inside the assembly; shared instances use
one copied part history. Existing source-copy numeric storage limits still apply:
use literals that survive native serialization at 15 significant digits.

STEP and STL retain geometry; they do not carry the spreadsheet or feature
relationships. Publication positions remain STEP 0, STL 1 and native FCStd 2.

## Verification and current scope

Build and fresh reopening compare actual native cell quantities, units, aliases,
formula contents and feature expressions. Saved XML independently binds the full
compiled table, headers, cell membership and display units. Native computed cell
properties are not persisted caches and cannot substitute for that formula
binding. Source admission checks this closed state before restoring a document;
external references, arbitrary functions, comments and extra cells are refused.
Geometry and neutral exports retain the existing verification limits.

The initial subset covers affine length tables that drive parts. Angular or
nonlinear formulas, general spreadsheet functions, imported tables, cross-document
references, standalone tables, live editing and `designStudy` remain missing.
The full FreeCAD adaptor is incomplete. The dedicated qualifier passes unitful
shelled and tilted parts, actual native cell edits/reopening, saved-state attacks,
shared and distinct-table source-copy histories and workflow reuse/damage checks.
See the [source-bound qualification note](../verification/2026-11-05-freecad-spreadsheets.md).
Independent integration, generated Help and installed-package acceptance remain open.
