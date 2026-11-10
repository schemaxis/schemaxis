# Persistent FreeCAD design parameters

A shared stock thickness can drive both a plate and the tool that drills through
it. `parameters` names that design dimension; each feature's `drive` records its
relationship. The published FCStd retains those relationships, so changing the
native parameter recomputes both features after the document is reopened.

```json
{
  "version": "schemaxis.freecad/1",
  "parameters": {
    "thickness": {"kind": "length", "value": 5, "minimum": 2, "maximum": 10}
  },
  "nodes": [
    {"id": "blank", "filter": "box", "options": {"length": 80, "width": 50},
     "drive": {"height": {"terms": {"thickness": 1}}}},
    {"id": "drill", "filter": "cylinder",
     "options": {"radius": 3, "origin": [40, 25, -1]},
     "drive": {"height": {"terms": {"thickness": 1}, "offset": 2}}},
    {"id": "plate", "filter": "cut", "inputs": {"base": "blank", "tool": "drill"}}
  ],
  "output": "plate"
}
```

Previously, a shared `$ref` or `$expr` supplied numbers to these options for each
run. Those common expressions still initialise parameter `value` fields, but
`drive` explicitly preserves the feature relationship in FreeCAD. Schemaxis
does not infer persistent relationships from resolved numbers.

## Supported relationships

| Feature | Driven options | Native properties |
|---|---|---|
| `box` | `length`, `width`, `height` | `Length`, `Width`, `Height` |
| `cylinder` | `radius`, `height` | `Radius`, `Height` |
| `extrude` | `length` | `LengthFwd` |
| `rectangle` | `width`, `height` | Named Sketcher constraints |
| `circle` | `radius` | Named Sketcher constraint |
| `pad` | `length` | `Length` |
| `pocket` with `extent: "length"` | `length` | `Length` |

A binding evaluates `offset + sum(coefficient × parameter)`. Coefficients are
dimensionless; parameter values, bounds and offsets are millimetres. For example,
`{"terms":{"stock":1,"clearance":2},"offset":1}` gives stock plus twice the
clearance plus 1 mm. Negative coefficients are permitted when the resulting
length remains positive throughout every independent parameter's declared bounds.

Declare 1–32 parameters and use each in at least one binding. Names begin with a
letter and contain at most 64 ASCII letters, digits or underscores. Each requires
`kind: "length"`, `value`, `minimum` and `maximum`, with
`0 < minimum < maximum <= 100000` and the initial value inside the bounds.
Each binding contains 1–4 terms; coefficients must be finite, nonzero and at most
1,000,000 in magnitude. The optional offset defaults to zero and has the same
absolute limit in mm. There are at most 128 driven feature dimensions.

All corner extrema of the affine relationship must give a positive length no
larger than 100,000 mm. Each driver's response across its bounds must exceed eight
times the verification tolerance (the larger of 0.000001 mm and 0.0000001 times
the largest bound result). This rejects relationships too small to establish
independently, including coefficients whose effect underflows to zero.
Do not also put a driven dimension in `options`, even with the same number;
Schemaxis rejects competing declarations before applying defaults.

Bounds validate the declared family of affine lengths. They do not prove every
boolean, fillet or topology will be valid across that family, and are not native
editing limits. FreeCAD edits outside the declared bounds require a new authored
input and qualification; native GUI editing does not reverse-sync the JSON.

## Native editing and evidence

The saved document contains one hidden `App::VarSet` named
`SchemaxisParameters`, labelled **Design parameters**. The `thickness` driver is
a typed length property named `dim_thickness` in the **Design parameters** group;
the deterministic `dim_` prefix avoids collisions with native property names and
unit tokens. Other names map identically, without truncation. Native expressions
refer to these properties and include explicit `mm` units for constant offsets.

A run checks typed driver readback, exact parameter/object membership, every
expression assignment, driven property values and feature validity. A separate
FreeCAD process reopens and recomputes the saved document. Host verification also
reads parameter metadata and expressions from FCStd's `Document.xml`; matching
geometry alone cannot substitute for a missing or changed relationship. FreeCAD
renders expression literals with 15 significant decimal digits and stores typed
length values with 16 fractional decimal places. Verification recognises those
specific representations, checks the exact original driver before saving and its
exact serialized value after reopening, and still checks target lengths and
geometry independently. A positive driver value or bound that would serialize to zero is
rejected as `UNREPRESENTABLE_PARAMETER`.

Publication positions stay unchanged: STEP is artifact 0, STL 1, FCStd 2, and
optional measurements JSON 3. STEP and STL retain the resulting geometry but do
not carry the native parameter relationships. Existing inputs without
`parameters` retain their original plans and verification contract.

## Variants and reuse

[The finite variant example](../examples/schemaxis/freecad-parameters-variant.json)
sets the thickness `value` to `{"$analytic":{"type":"values","values":[5,8]}}`.
Each visit has its own verified FCStd and explicit persistent relationship.
[The workflow example](../examples/schemaxis/freecad-parameters-workflow.json)
passes the measured plate height to another CAD operation through artifact 3.
An unchanged verified workflow can be resumed. Invalid native evidence forces
the CAD operation and dependent consumer to rerun while an independent operation
is reused. Changing an authored driver requires a fresh workflow directory;
resuming a changed authored workflow is rejected as `RESUME_MISMATCH`.

Run the [plate](../examples/schemaxis/freecad-parameters.json) or
[extrusion](../examples/schemaxis/freecad-parameters-extrude.json) example through
the normal `schemaxis plan`, `run` and `verify` commands. The
[invalid example](../examples/schemaxis/freecad-parameters-invalid.json) demonstrates
`CONFLICTING_BINDING`. `INVALID_PARAMETER`, `INVALID_BINDING` and
`UNOBSERVABLE_BINDING` identify invalid declarations and unverifiable responses.

This increment supports batch parts and finite variants. Native drivers are
explicitly rejected by live sessions (`UNSUPPORTED_LIVE_INPUT`) and by the scalar
`designStudy` route (`UNSUPPORTED_PARAMETER_STUDY`). The [mechanical-part workflow](freecad-part-design.md) combines these drivers with
constrained sketches, a Body, first Pad and finite-depth or through-all Pockets.
Finite depth may use a persistent length driver; it is blind only while stock
remains thicker than that depth. Angular parameters, nonlinear expressions, feature-to-feature
references and assembly constraints are outside this increment. Existing
assembly and import/export capabilities remain documented separately.

## Qualification

`tools/qualify_freecad_parameters.py --directory NEW_EVIDENCE_DIRECTORY
--executable FREECADCMD` exercises native build/reopen, each driver's independent
minimum/maximum perturbation, a saved edited copy reopened in another process,
negative and multiple coefficients, maximum-length names, finite variants,
workflow reuse/invalidation and existing solid/measurement regressions. Independent
plate expectations are `V = (4000 − 9π)t` and
`A = 2(4000 − 9π) + (260 + 6π)t`. Extrusion volume is `200 × depth`.
The qualification also rejects saved-file alterations that preserve current
geometry but remove or alter declared intent. This is bounded qualification,
not an exhaustive claim for FreeCAD or all permitted geometric combinations.

For native engineering tables, mixed-unit inputs and formula chaining, see
[Spreadsheet dimensions](freecad-spreadsheets.md). Choose one storage contract
per document; the original VarSet input remains unchanged.
