# Blender curve and font render sampling admission

The fixed baseline is official Blender5.2.3LTS, build e13b728c6880.
Whole Blender, broad curve modelling and richer source topology remain incomplete.

An actual bounded RenderEngine diagnostic exposed a missing resource envelope:
a curved two-point Bézier at preview resolution1/render128 had16 viewport Mesh
vertices and524 render vertices, while the old conservative estimate was32.
A straight VECTOR-handle control had16 in both contexts and would miss this
fault. No huge render was required to demonstrate it. The fixed
[native sampling API](https://docs.blender.org/api/5.2/bpy.types.Curve.html) and
[tagged implementation](https://github.com/blender/blender/blob/v5.2.3/source/blender/makesrna/intern/rna_curve.cc)
distinguish render sampling from preview sampling.

Resource admission now takes the maximum of data preview/render and applicable
spline resolution for Curve geometry, and preview/render for builtin Font
geometry. Existing numeric key/Bezier envelopes apply to render sampling too.
The two-million conservative budget remains unchanged. This closes this known
underestimate; it does not establish exhaustive native curve/modifier coverage.

`tools/qualify_blender_curve_resource_budget.py` checks an admitted curved source
with independently expected viewport bounds and44 vertices, then measures a real
RENDER depsgraph with524 vertices against the4096 conservative ceiling. A builtin
curved S glyph retains the expected±0.1 bevel depth; its actual viewport/render
counts are60/410 within the65536 ceiling. The fixed diagnostic engine changes
only its process memory and never saves the accepted project bytes.

Static1024-point/render1024 Curve, later-key render growth from1 to1024, and
100-glyph/render1024 Font sources refuse before procedural attachment. Their
small preview geometry remains inexpensive; no huge render is allocated.
Refreshed-hash mutations of the imported Curve/Font render resolution must refuse
through fresh native fidelity even though viewport geometry remains unchanged;
identical native open/save positives must pass the same path. Both Curve/Font mutations and unchanged-save controls passed. All five run
archives matched the exact current trusted source bytes. Final source-bound
records use the source fingerprint and runtime archive below.

Source fingerprint: `sha256:624d2516187f151005b05830bec7e349ad2b8acb09dcf615117d9ff9e4891045`.
Runtime archive: `sha256:16350da1d2ccdd3852f6a7a93bb7e45e0c477bbf66ca0928cb94bb3bdb44da86`.

Earlier mesh-edit evidence remains bound to its own649d72a source/archive; this
focused source-curve admission repair changes a separate branch. There is no
retroactive whole-tree relabelling of those receipts. New public control/schema
authoring is unnecessary for this repair: it protects existing typed asset,
whole-collection and procedural resource workflows. Richer Bézier/NURBS/profile/
taper/path authoring remains the next required implementation family.

Frozen source9065dab passed the final nine-component batch: the two native
positives/three refusals, two semantic native mutations/two unchanged saves,
resource regression13 positives/6 refusals, source-topology animation regression,
all119 native-enabled Blender unit tests with zero skips, schema/parser parity5,
production conformance, complete guidance, actual resource authoring browser and
private Help/search9 cases. Qualifier and runtime binary SHA256 were captured
before/after the batch, and the runtime archive stayed byte-identical throughout.
Shared generated Help/readiness/installed-package gates remain integration work.
The first development fixture incorrectly used opposite handle directions while
expecting a one-sided arch; its literal bounds failure was retained and the
fixture corrected. No product tolerance was weakened.
