# FreeCAD semantic selection verification — 2026-09-30

The solid route now accepts geometric edge selectors for fillets/chamfers, in
addition to explicit indices. Predicates conjoin curve type, straight direction,
world-coordinate plane and length interval. Exact expected cardinality is
mandatory. The native application resolves selectors on every apply; fresh-process
readback repeats selection and checks the actual native edge assignments. Host
verification replays predicates against retained geometric observations.

## Native serial checks

`tools/qualify_freecad_selections.py` runs with the configured FreeCAD 1.1.3 runtime.
The final acceptance passed at `evidence/freecad-selections-20260930-04/report.json`.
Its source digest is retained in the report and matches this implementation.
The existing native solid conformance cases and cancellation/timeout checks also
passed in `evidence/freecad-conformance-20260930-05/qualification.json`; that scoped
receipt was registered for the solid route. The assembly receipt is not refreshed
by these solid-route checks.

The full host suite passed: **852 tests run, 22 expected skips**, no failures or
errors (233.286 seconds). The transcript is retained beside the final native
report as `host-tests.log`. Generated schemas and module references were refreshed.

Independent geometry expectations for four rounded vertical edges use cross-section
area `L*W - (4-pi)*r^2`, perimeter `2*(L+W)-8*r+2*pi*r`, volume `area*H` and
surface area `2*area+perimeter*H`. Chamfered corners use area `L*W-2*d^2` and
perimeter `2*(L+W)-8*d+4*sqrt(2)*d`. These expectations do not reuse native volume
or area calculations.

Passed native cases:

- A 20×10×5 mm box with four 1 mm vertical fillets: 995.707963267949 mm³.
- A translated 30×12×7 mm variant: 2513.991148575129 mm³, with the same semantic
  intent resolving again; volume and surface area match analytic expectations.
- Four 1 mm vertical chamfers: 990 mm³, also matching analytic area.
- STEP export/reimport of the source, followed by geometric re-selection and the
  same independent rounded-prism checks.
- The top circular edge of a cylinder selected by curve and plane. Its measured
  source edge length equals `2*pi*5` and its bounds lie on Z=10 mm.
- Two analytic heights (5 and 7 mm), independently selected and verified, plus
  native inspection of visit 1 returning the 1400 mm³ unrounded source.
- Deliberately empty, ambiguous and insufficient matches, with distinct structured
  faults. Applying the same expected count after upstream finishing changes
  topology and is rejected as ambiguous.
- Altered build/reopen selection records rejected; restored evidence verifies.
- Verified workflow reuse on an unchanged repeat.
- A dedicated persistent FreeCAD GUI process applied both dimensions while
  retaining the same process and object identities. An ambiguous live edit raised
  the selection fault, rolled back the native transaction and preserved the
  previous geometry and revision. The owned process was closed afterwards.

Host tests use generated analytic edge coordinates to check translation, dimension,
edge-enumeration, direction-sign and direction-scale invariance; conjunctive
predicates; empty/ambiguous/missing matches; invalid declarations; analytic
inspection preparation and replay corruption. Discovery remains native-import-free.

## Boundaries

The evidence concerns bounded geometric re-selection, not persistent topology
identity, general CAD constraints, MPI or exhaustive curve/kernel coverage. Equal
cardinality alone cannot prove semantic identity; predicates must discriminate the
intended geometry. World-plane coordinates do not implicitly move with a part.
Manual native edits do not promise re-evaluation of the authored selector. BREP
geometry observations rely on native readback; independent analytic fixtures
provide additional scientific checks.

Reproduce with:

```sh
PYTHONPATH=src python3 tools/qualify_freecad_selections.py \
  --config /path/to/private-config.json --output-directory new-cad-selection-proof
```

Pass `--freecad-gui /absolute/gui/launcher` to additionally test persistent object
reuse and transaction rollback after an ambiguous live edit.
