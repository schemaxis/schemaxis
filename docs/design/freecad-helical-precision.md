# FreeCAD helical features and precision programme

The typed `additiveHelix` and `subtractiveHelix` features are under qualification.
The whole Helix family and the whole FreeCAD adaptor remain incomplete. Current
three-, six-, twelve- and twenty-four-turn precision controls pass for their
qualified inputs. Parameter-wide availability and captured-source portability
remain unfinished. These checkpoints do not
qualify every profile, extent, growth mode or downstream history combination.

## Authored material intent

Both features consume a closed cross-section profile owned by the same Body.
An additive feature can start an empty Body or continue its current solid tip.
A subtractive feature requires that current tip as its `base`. The profile's
offset from the axis establishes the helix radius. Choose section size and pitch
to avoid self-intersection and preserve a single valid solid output.

`subtractiveHelix.material` names the material that remains:
`outsideSweep` removes the swept region from the base, while `insideSweep`
retains the base material inside that region. This expresses geometric intent;
it is not a toolpath or a machining-clearance check.

## Dimensions and orientation

Supply exactly the independent dimensions for the selected mode:

| Mode | Authored independent dimensions | Derived dimension |
| --- | --- | --- |
| `pitchHeight` | `pitch`, `height` | `turns = height / pitch` |
| `pitchTurns` | `pitch`, `turns` | `height = pitch * turns` |
| `heightTurns` | `height`, `turns` | `pitch = height / turns` |
| `heightTurnsGrowth` | `height`, `turns`, `growth` | pitch and cone angle |

Pitch, height and radial growth are in millimetres; turns count revolutions.
In the first three modes, `angle` in degrees controls conicity and radial
growth per revolution is `pitch * tan(angle)`. In growth mode, `growth` specifies
that radial change directly and `angle` must stay zero in authored input. A
zero-height, multi-turn spiral needs nonzero growth. Positive and negative
growth may produce invalid geometry when the section reaches or crosses the axis.

The `axis` option selects a Body-origin X, Y or Z axis. An earlier, same-Body
`datumAxis` supplied through `inputs.axis` replaces that choice. `leftHanded`
selects the screw handedness; `reversed` reverses the axial sweep direction.
Profile and axis coordinates are interpreted in their Body frame.

`drive.pitch` and `drive.height` can retain affine length relationships to
declared parameters only when that dimension is independent in the selected
mode. A derived dimension cannot also be driven. Native property paths,
unrestricted expressions and kernel-tolerance controls are not authored fields.

## Current measurement and verification boundary

The native scene retains editable Body history. STEP and STL handoffs retain
geometry and lose that history. Complete fresh native graph and export-payload
binding establish geometry identity; agreeing volume or centre alone cannot do so.

Helical solid measures use the bounded original-geometry instrument described in
[named measurements](../freecad-measurements.md#coordinate-frames-and-helical-geometry).
Two integration partitions provide empirical resolution controls, not a certified
error bound. Named intermediate and final measurements use the native world
frame, including placed seeded Bodies. Their shared numerical and runtime
budgets remain fixed; unresolved requests refuse.

The selected product method is `schemaxis.freecad.gauss-green/2`. It completes
original face boundaries with typed ribbons, collapsed fans, corner caps and
curved connector patches. The numeric pieces and executable incidence ledger
share their coefficients. Paired traces and vertex endpoints must fit their native
tolerances, and newly introduced UV connectors must pass finite separation checks.
An exact, opposite-oriented affine terminal retrace can be admitted as a zero-area
UV spike: the traced subarc and connector cancel as oriented paths under the same
surface map. This proves cancellation for the exact stored finite law and ideal
connector segment. Native floating evaluation, connector slope subtraction and
rounded subdivision controls are not exact geometric certificates. The public
measurement guide records these arithmetic limits and the native validity and
external mesher resource assumptions.
Original numeric pieces remain intact. The strict subset, endpoint, coefficient,
wire-direction and positive-weight laws are recorded; other spans and connector
pairs still require separation. Whole-edge or ambiguous overlap refuses. The
method never repairs or replaces the saved geometry to make a request pass.

Two isolated auxiliary conic-lens classes additionally admit a single closed
occurrence just over one true period, or an exact terminal tangent contact on an
injective arc shorter than half a period. Bounded outward phase enclosures and
strict support isolation preserve the original curves, parameter domains and
numerical boundary pieces. The sampled chart-density companions use local
winding-difference caps of two and one respectively. They share the existing
joint volume-to-centre propagation and fixed resource limits; they are not error
bounds. Conic-to-token joins and three-dimensional rung/cap gaps remain
unmodelled, and other unresolved configurations refuse. Published chart area is
winding-weighted, with the artificial skin excluded.

The published volume and centre belong to the explicit closed chain. Published
area belongs to the original charts with straight UV connectors, excluding the
artificial skin. Resolution, sampled confinement and coarse winding checks are
empirical. They do not certify error, self-intersection or machine suitability.
A far-UV STEP control now correctly refuses because its reconstructed pcurve and
3D edge disagree beyond the saved tolerance, despite kernel validity; the original
all-positive qualification aggregate remains failed and the new recipe treats
this input explicitly as a refusal control.

The fixed evaluation, depth, numerical and caller deadlines apply to every
request. A particular 24-turn control passes near the fine-level evaluation cap;
the authored 1000-turn limit is not a demonstrated numerical capacity. See the
[numerical scope and resource boundary](../freecad-measurements.md#coordinate-frames-and-helical-geometry).
Captured-source propagation and application-wide qualification remain required.
