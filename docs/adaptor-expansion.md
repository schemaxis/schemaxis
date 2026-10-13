# Geometry adaptor expansion — September 2026

The new operations remain within each app's adaptor package. Discovery, planning,
option validation and schema generation work without native application imports.
Latest-release checks and AI repair briefs now include Octave and Calc as well.

## Blender 5.2.2

Five new operations bring the Blender catalogue to 37:

| Operation | Contract |
| --- | --- |
| `grid` | XY quad grid; width/height and 1–256 subdivisions per direction |
| `disk` | Filled XY polygonal disk with 3–256 perimeter vertices |
| `polylineTube` | Native beveled POLY curve converted to a mesh; 2–1024 3D points, radius, resolution, closure and caps |
| `curveFromCSV` | The same tube from named numeric CSV columns; z defaults to zero |
| `lathe` | Revolve 2–128 `[radius, height]` pairs about Z; 3–256 radial segments and optional caps |

Lathe radii are positive and heights strictly increase. The resulting object is a
solid of revolution when capped, not a hollow vessel. Tubes reject zero-length
segments; closed tubes need three distinct consecutive positions and omit a repeated
closing point. Neither tube contract promises freedom from self-intersection for
arbitrary paths and radii. Material assignment, centre offsets, smooth shading and
ordinary downstream modifiers use the existing graph lifecycle.

Materials now expose transmission, coat weight/roughness and emission colour/strength.
Native Principled BSDF sockets are explicitly assigned and read back. The renderer
and geometry adaptor require the qualified Blender 5.2.2 release; previous 4.5.x
support is replaced under the latest-stable policy. Existing live-edit tests,
render groups, geometry sweeps and CAD/ParaView exchanges were rerun on 5.2.2.

```bash
schemaxis run examples/schemaxis/blender-procedural.json --output-directory procedural
schemaxis run examples/schemaxis/blender-lathe.json --output-directory lathe
schemaxis run examples/schemaxis/analysis/octave-to-blender.json --output-directory data-curve
```

The procedural example saves geometry without rendering. The other two produce
images and editable scenes. Native tests check grid/disk topology and independently
calculate the volume of a straight tube and segmented rotational profile.

## FreeCAD 1.1.3

`loft` creates a native `Part::Loft` solid from an ordered `sections` list of 2–32
profiles. `ruled` selects straight interpolation between sections. `multiFuse`
creates a native `Part::MultiFuse` from 2–32 solids, with an optional `refine` flag.
Lists must contain distinct earlier nodes of the correct kind. Native settings and
list ordering are verified after reopening the editable FCStd file. The existing
one-valid-solid output contract still applies; disjoint unions fail it.

```bash
schemaxis run examples/schemaxis/freecad-loft.json --output-directory loft
schemaxis run examples/schemaxis/freecad-multi-fuse.json --output-directory union
schemaxis run examples/schemaxis/expanded/lofted-connector.json --output-directory connector
schemaxis inspect examples/schemaxis/freecad-loft.json --node transition --output-directory loft-topology
```

The acceptance frustum has volume `7000π mm³`; the three overlapping boxes have
union volume `2000 mm³`. Native topology inspection now traverses list inputs too.
The lofted-connector workflow combines both new operations, cuts a through-bore,
and renders the exported solid in Blender with explicit millimetre-to-metre scaling.
Live qualification also checks profile edits, native object reuse and rollback of a
disconnected union. No new assembly motion or FEM support is implied.

## Godot 4.7.2

The 13-operation catalogue now includes capsule and torus meshes, omni lights and
spot lights. Geometry accepts explicit degree rotations and positive per-axis scale.
Host verification independently calculates Godot's YXZ rotation basis and transforms
local bounds; both the basis and bounds are checked after saving and reopening.
Light range, attenuation, energy, colour, shadows and spot cone settings are read back.

```bash
schemaxis run examples/schemaxis/godot-lighting.json --output-directory lighting
```

Set `preview: true` to request the existing native PNG preview path. It needs a
working graphical runtime; headless scene creation/reopening does not. The example
uses mixed-axis rotation and nonuniform scaling to exercise more than axis-aligned
shapes. Invalid capsule proportions and inverted torus radii fail during planning.

## Data analysis

See [numerical and spreadsheet workflows](numerical-analysis.md) for the Octave and
Calc adaptors, CSV contracts and bridges to Blender. The new features are bounded
native qualifications, not claims of full application parity. Exact versions,
checks and retained evidence are in the
[qualification summary](../verification/2026-09-25-adaptor-expansion.json).
