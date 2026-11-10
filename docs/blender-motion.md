# Reusable Blender motion and morphs

A production can declare named `clips`, bind their semantic target roles in
ordered `layers`, and author editable `shapeKeys`. The example
[blender-motion-clips.json](../examples/schemaxis/blender-motion-clips.json) combines
object motion, pose bones, camera and light animation, relative masked deformation
and absolute morph interpolation. The saved project retains native Actions, slots,
NLA tracks, strip influence curves and Key blocks for further editing.

A clip addresses roles rather than scene object identities:

```json
{"id":"slide","tracks":[{"target":"part","channel":"location",
  "keys":[{"frame":1,"value":[0,0,0]},
          {"frame":11,"value":[4,0,0]}]}]}
```

A layer binds that role, trims its source interval, and places playback in scene
time. `scale:2` doubles duration; `repeat:2` plays two loops; `reverse:true` starts
at the source interval's last frame. Each interval must fit the scene timeline.
Keys use integer clip-local frames; trim boundaries and playback scale can be
fractional. Native evaluation uses continuous time, while retained independent
samples use integer scene frames at keys, boundaries, midpoints and fade midpoints.

```json
{"id":"left-part","clip":"slide",
 "bindings":[{"target":"part","object":"left"}],
 "start":1,"scale":2,"repeat":2,"reverse":true,
 "blend":"ADD","influence":0.5,"fadeIn":4,"fadeOut":4}
```

Array order is bottom to top. An explicit constant reference-pose action records
the declared static object or data values before the clip layers. This makes
weighted and additive blending preserve, for example, an authored initial
10-unit translation. `REPLACE` interpolates toward the new value; `ADD` adds it;
`SUBTRACT` subtracts it; `MULTIPLY` interpolates toward multiplication. Influence
and fades lower to LINEAR strip influence keys, because Blender ignores the
scalar influence setting when animated influence is disabled. `NOTHING` stops
outside a layer, `HOLD` retains both boundaries, and `HOLD_FORWARD` retains the last.
Boundary influence, including a fade to zero, remains effective when held.

Clip channels are a finite shared catalogue: object and pose-bone location,
Euler rotation in radians and scale; light energy and linear RGB colour; camera
lens, orthographic size, focus distance and aperture; relative shape value; and
normalized absolute morph progress. Clips use LINEAR or CONSTANT interpolation.
Direct scene tracks retain their separate Bezier support. A domain cannot have
both direct tracks and clip layers. A turntable can use a separate parent object.
One clip reuses actions across compatible bindings; normalized absolute progress
lowers to the native Key interval separately when shape counts differ.

Relative morphs supply either all local vertex coordinates in Basis order or
sparse `offsets` entries containing `vertices` and a local XYZ `offset`. Sparse
offsets always start from Basis. `relativeTo` then selects Basis or an earlier
shape for Blender's relative difference. Optional disjoint `mask` entries supply
per-vertex weights; unlisted vertices have zero weight when a mask exists.
Without a mask all vertices have full weight. Initial values and animated values
must lie within the declared `minimum` and `maximum` slider bounds.

Absolute morphs interpolate Basis and the declared shapes in order, at equally
spaced native positions. `progress:0` selects Basis and `progress:1` selects the
last shape. This hides Blender's internal ten-unit Key spacing without promising
arbitrary writable Key positions. Absolute morphs refuse relative references,
vertex masks and relative slider options. Authoring requires owned mesh data;
linked mesh instances must be independent to avoid ambiguous Key ownership.

Verification reconstructs native channels, slots, exact curve/key membership,
NLA order, timing, influence functions, reference poses, morph coordinates,
references and masks from current saved bytes. A host evaluator independently
calculates sampled scalar/vector layer values. Connected acceptance also uses
literal deformed geometry bounds and tests packed native asset reuse. Imported
assets preserve ordinary CLIP NLA tracks and their nested actions and influence
curves. META/TRANSITION strips, animated strip time, NLA strip modifiers, tweak
mode and unreviewed dependencies are refused. Envelope F-curve modifiers also
remain unsupported until their control-point payload has a dedicated mapping.

This completes a useful clip/layer/morph family, not the whole Blender API.
Quaternion-specific COMBINE, retargeting, direct authored drivers, arbitrary
property paths, fractional authored keys, custom absolute Key spacing and
stateful animation caches remain open. Native editable projects retain motion;
evaluated neutral geometry exports remain explicitly static.
