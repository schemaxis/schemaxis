# FreeCAD semantic edge selections

A finishing operation can select geometric intent instead of storing edge numbers.
The [semantic fillet example](../examples/schemaxis/freecad-semantic-fillet.json)
rounds the four straight edges parallel to the Z axis:

```json
{
  "id": "rounded",
  "filter": "fillet",
  "inputs": {"base": "blank"},
  "options": {
    "radius": 1,
    "edges": {
      "where": {"curve": "line", "parallelTo": [0, 0, 1]},
      "expect": 4
    }
  }
}
```

`chamfer` accepts the same `edges` contract, with `distance` instead of `radius`.
The existing array form, such as `"edges": [1, 3]`, remains available and retains
its original topology-dependent meaning.

## Predicates and limits

All supplied `where` predicates must match. At least one is required.

| Predicate | Meaning |
| --- | --- |
| `curve: "line"` or `"circle"` | Native straight or circular edge geometry; other curve types do not match. |
| `parallelTo: [x,y,z]` | Straight-edge direction parallel or antiparallel to a nonzero vector. Vector magnitude and sign do not matter. |
| `onPlane: {"axis":"z","coordinate":5}` | The entire edge's bounding interval lies on that world-coordinate plane within tolerance. |
| `length: {"minimum":5,"maximum":10}` | Measured edge length lies inside the inclusive interval, with the stated length tolerance. |

`expect` is mandatory, between 1 and 1000, and requires an exact match count.
`tolerance` is in mm, defaults to 0.000001 and lies between 1e-9 and 0.01.
`angularTolerance` bounds the sine of the angle to the requested line direction;
it has the same numeric default/range but is dimensionless. It is neither a degree
nor a millimetre tolerance. `parallelTo` cannot be combined with `curve: "circle"`.
Native selection inventories are bounded to 10000 edges per source.

Expressions and document/value references may supply selector values. Shared
analytic visits resolve them before native validation. A direction selection
survives translation and dimensional changes when the intended set remains
geometrically identifiable. A plane selection uses absolute world coordinates;
reference the same authored dimension/offset when the plane should move with the
model. The adaptor does not infer a moving coordinate frame.

## Resolution, verification and inspection

Each declared application recomputes the source shape, measures its edges and
resolves the predicates. The exact selected indices are assigned to the native
fillet/chamfer. A fresh process opens and recomputes the saved FCStd model,
resolves the predicates again and checks the actual native assignment.

`built.json` and `verification.json` retain `selections`, keyed by finishing node.
Each record identifies the source node, full bounded edge inventory, resolved
indices and applied native edge/radius tuples. Host verification independently
replays the geometric predicates against the recorded data and compares native
readback. It does not implement an independent BREP kernel; acceptance fixtures
add analytic volume and area checks for rounded and chamfered rectangular prisms.

Use ordinary CAD inspection on the source node to inspect edge lengths, centres,
bounds, endpoints and curve types. The `visit` argument to the inspection API
selects a finite analytic input state. The returned inventory belongs to that
resolved state; its edge indices are not persistent IDs.

Empty matches raise `EMPTY_SELECTION`. Too many matches raise
`AMBIGUOUS_SELECTION`; too few nonzero matches raise `SELECTION_COUNT_MISMATCH`.
The structured fault records the selector, expected/actual counts and up to twenty
matched indices. No nearest-edge fallback or arbitrary first match is used.

## Scope

This is bounded geometric re-selection, not general persistent topological naming.
A boolean or finishing operation can split, merge, add or remove edges. If that
changes the matched set, an explicit failure is safer than silently changing the
model's meaning. A predicate can also match a different set with the same count;
users must choose discriminating predicates and inspect changed geometry.

Selectors are re-evaluated when Schemaxis applies the authored document. They are
not saved as arbitrary executable query features in FCStd, and manual native edits
do not promise automatic re-resolution. Source indices, geometric predicates and
native feature-history identities are distinct concepts.

The bounded serial acceptance covers dimension/translation changes, fillets and
chamfers, circular-edge plane selection, STEP export/reimport, changed topology,
missing/ambiguous matches, analytic inspection, evidence tampering and workflow
reuse. See [verification](../verification/2026-09-30-freecad-selections.md).
