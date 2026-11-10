# Place an editable Body in world coordinates

Give a `body` an explicit `options.frame` to arrange a complete part without
moving every sketch separately. The Body can start with a Pad, revolve or other
admitted first feature, or with checked imported stock through `bodySeed`.
Profiles and features remain in the owning Body's local coordinates.

```json
{
  "id": "part",
  "filter": "body",
  "options": {
    "frame": {
      "origin": [7, -11, 13],
      "xAxis": [0.6, 0.8, 0],
      "normal": [0.48, -0.36, 0.8]
    }
  }
}
```

`origin` is the world position of the local origin in millimetres. `xAxis` and
`normal` are perpendicular unit vectors; local Y is `normal cross xAxis`. Omit
`frame` for the earlier identity layout. Invalid/nonorthogonal axes refuse
planning. A frame does not add material, create an import, change units or permit
arbitrary Placement expressions.

The [placed plate](../examples/schemaxis/freecad-placed-body.json) has an asymmetric
through bore and a separate oblique profile frame. Its
[attached variant](../examples/schemaxis/freecad-placed-body-attached.json) places
the bore on the selected extreme right face using a native centroid attachment.
The [multi-Body case](../examples/schemaxis/freecad-placed-bodies.json) retains a
second independently placed Body while publishing the selected first Body's final
tip. Studio's **Place an editable Body** template exposes thickness and world
origin; edit the complete frame for another orientation.

## Profile, Body and assembly frames

For Body-owned profiles, `plane`, `origin`, explicit profile frames and semantic
attachment directions describe **Body-local** geometry. A right-face attachment
selects the extreme local +X face, even when Body layout points +X elsewhere in
world space. Curved or rotated support faces that do not match an admitted
Cartesian selector remain unsupported; changing Body layout does not broaden
face selection or repair broken topology.

Let a profile map be S, Body layout B and assembly component placement C. The
part exports a point as `B * S * p`. A sourced assembly uses `C * S * p`, with
mounts in that same Body-local system. Rotation order matters. Applying B again
to a component would double the producer layout. Component links deliberately
ignore that layout while the copied editable history retains it.

A final explicitly placed Body tip is exported through its Body carrier to world
STEP/STL and native geometry. Unframed ordinary histories retain their earlier
native output names; intermediate feature references remain references to those
features. The authored `output` is still a final solid feature ID, not a Body
container. All authored Bodies remain in the FCStd, including nonselected ones.

[Named measurements](freecad-measurements.md) have their own documented coordinate
contract. A feature's native local Shape is distinct from the world export;
named coordinate measurements apply its containing frame exactly once. The
examples measure both the final tip and an intermediate Pad in world coordinates,
and select the intermediate Pad's four extrusion edges by their world direction.
Volume and area alone cannot establish the correct placement.

## Edit, copy and retire sources

Thickness and other declared dimensions remain editable native parameters. A
face-attached profile follows its support after a dimensional edit. Changing Body
Placement moves the part layout; it does not move Body-local geometry or rename
mounts. Repeated assembly instances still share one copied source definition.

A native design edit no longer verifies as the original authored run. Keep the
old result, update the typed dimensions/frame and build a new publication.
[Portable Body captures](freecad-body-history.md) retain complete typed intent and
native history, so a sourced assembly can verify after its whole producer is
unavailable. An unchanged save must match one complete reachable trusted SDK
state within the existing verification budget. Editing receipts, omitting another
Body or refreshing a file hash cannot substitute for that binding.

The focused reproducer is:

```bash
python3 tools/qualify_freecad_body_frame.py \
  --freecad /path/to/freecadcmd --freecad-gui /path/to/freecad \
  --output-directory /path/to/new/body-frame-proof
```

It creates only its own projects. `--examples-directory` selects another public
fixture directory. Results retain source/runtime/tool/input identities and partial
failures. Native and STEP geometry, independent STL pose/material checks, actual
attachments, saved states, copied edits, source retirement and refreshed authority
attacks are separate checks. A successful invocation qualifies these cases;
whole FreeCAD, general topology repair and arbitrary native edit adoption remain
unfinished.
