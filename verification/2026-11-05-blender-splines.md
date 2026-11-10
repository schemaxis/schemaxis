# Editable classic splines — qualified construction scope

Execution provider `a971edd362c12b8da9a7097ab31e7dbfad123b23` targets Blender
5.2.3 LTS. Source fingerprint
`sha256:adfec6f5067011a123a8c38fab421e49ab1d0353fb9bf7964dfb6b563c33645d`
and runtime archive
`85a2a65f23478f4d42e38c0462096c3c481813f309a864ea3aac21b03de28793`
were pinned throughout the current qualification, with qualifier and executable
hashes checked before and after. This qualifies a bounded construction scope;
whole Blender completion and integration acceptance remain open.

Current native qualification passed six components: 38 constructor projects and
11 refusals, 17 refreshed-hash semantic mutations with nine unchanged-save
controls, six lifecycle projects with a captured-profile mutation/control,
two early-admission refusals with a reachable small control, a builtin-font
Object-profile positive with an expansion refusal, and private Help verification.
The executable SHA256 is
`b8b07a190fb25db76aae6de08dbc6c2b3d64e22e82bed6ba90de9545859f3431`.

Host delivery checks passed 131 native-enabled Blender tests without skips, five
schema/parser parity tests, production conformance, three actual Studio browser
cases, and 5,717 reviewed plus 246 reference guidance records with no pending or
stale fields. Private Help contained 1,524 topics from 687 files and passed ten
search cases. Shared generated Help, installed-package checks, full integrated
host/Studio gates and parent acceptance remain pending.

Independent numeric expectations include cubic Bezier and rational samples,
periodic quadratic and Bezier-knot spans, weighted rational orders four through
six with per-spline sampling, planar offset area 6.25, distinct winding-fill areas,
gasket extrusion volume, explicit quarter-profile areas, scaled Object sections,
point-radius/taper frusta, tilt, distinct trimmed taper ranges and fixed path
positions. Three trim-mapping choices are qualified on a straight single segment;
this does not prove every nonuniform mapping combination. Native path/deformation
settings are persisted and read back; a general typed Curve-deform modifier is
still missing.

The runnable millimetre gasket has volume 1,200 mm³. An independently parsed GLB
has 32 triangles, physical bounds 40 × 20 × 2 mm and volume 1.2e-6 m³. Two distinct
Curve collection instances additionally retain their literal geometry across five
exchange formats. Lifecycle checks edit native rational/profile controls, adopt
new source files, reopen packed projects without originals, refuse receipt
verification until originals return, and exercise captured-profile mutation.

Production verification observes reviewed native controls and actual profile/
taper pointers against fresh trusted constructors. Automatic handles are a native
policy, separately qualified with analytic fixtures; stored companion records do
not establish control geometry. Position checks retain a whole-spline bound and
independent adjacent-edge, cyclic-join and explicit handle-offset precision.
Native float underflow or local feature collapse refuses with recovery guidance.

The full 16-component regression epoch at `06341ce51b342a0f3183b7624a98f5ce12d56e74`
passed mesh editing, fields/UVs, render budgets, node groups, assets, motion,
collections and geometry resources, including retained CAD inputs. Its archive
`f85d955f21a2108c1065581357ce5915253848ba3a2e9e618dae8beeca55aa55`
remains a separate source epoch. Whole-archive comparison proves the subsequent
change consists only of spline host admission and four delivery JSON files;
native execution modules are identical. Those unaffected regressions are reused
under their original source, not relabelled as current execution.

Several failures materially strengthened this scope:

- Initial native UI preset assignment produced identical geometry for different
  preset labels. It was removed before acceptance. Explicit normalized quarter
  controls now produce independently distinct diamond, square and chamfer sections.
- The first frozen epoch passed native producer/readback checks but doubled Curve
  GLB geometry. The independent physical-volume oracle caught the error. The
  resolver now consumes the generated Mesh component once and preserves distinct
  instances; old doubled bytes and the failed epoch remain retained.
- Evaluation-order review found mesh-data operators and material resolution could
  evaluate scene curves before resource admission. Early admission and a second
  check after hierarchy now precede those boundaries. Native marker controls
  detect the previous provider and preserve a reachable small positive.
- Independent peer review found a distant control in one spline could hide a
  collapsed short edge. The old native constructor and observation reproduced
  that acceptance. Local edge/handle checks now preserve representable 128-unit
  features beside a 1e9-unit span and refuse collapsed open, cyclic and handle
  variants. Final repair re-review remains a separate pending gate.
- Additional variants isolated a native partial-trim defect: varying point radii
  can retain both interpolated and untrimmed endpoint rings, even without caps.
  Planning refuses that combination. Full variable-radius sweeps and partial
  constant-radius taper-remapping controls pass. Earlier two-point taper
  expectations wrongly assumed continuous resampling and remain recorded as
  failed expectations, not accepted evidence.

The [guide](../docs/blender-splines.md), standalone starter, Studio template,
conceptual guidance and discovery metadata accompany the construction route.
Surface grids, metaballs, modern Curves, broad curve editing, per-spline material
assignment, independently readable FREE/ALIGN quarter-profile handles and broader
scene-wide instance/export memory admission remain unfinished. Native cap winding
and NONZERO extrusion can affect solid validity; no arbitrary valid-solid proof
is claimed. No major capability family has been excluded to reach this checkpoint.

The fixed public API basis includes
[Curve RNA](https://github.com/blender/blender/blob/v5.2.3/source/blender/makesrna/intern/rna_curve.cc),
[CurveProfile RNA](https://github.com/blender/blender/blob/v5.2.3/source/blender/makesrna/intern/rna_curveprofile.cc)
and the [5.2 Curve API](https://docs.blender.org/api/5.2/bpy.types.Curve.html).
