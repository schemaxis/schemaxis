# Blender reusable motion and morph acceptance

This continuation adds a strategically useful animation family. It does not
claim that the whole Blender adaptor is complete or near full API coverage.
The whole-application editorial breadth estimate remains conservative.

Qualified runtime: Blender 5.2.3 LTS, isolated background execution with factory
startup, disabled automatic scripts and Python exceptions treated as failures.

Fresh connected acceptance covers:

- A reusable object clip on two objects, weighted additive reference-pose
  composition and reversed, repeated and retimed playback.
- Ordered shared-action layers, all four admitted arithmetic blend modes,
  source trimming and explicit editable influence/fade curves.
- Pose-bone transform, light energy/colour and camera lens/size/focus/aperture
  channels with independent host scalar/vector evaluation.
- Relative shapes with sparse offsets, vertex masks and an earlier relative
  reference, plus full-coordinate absolute shapes and normalized progress.
  Literal deformed bounds prove the actual effect, beyond property readback.
- The same absolute-progress clip applied to meshes with different numbers of
  native Key positions, without exposing the internal ten-unit spacing.
- Editable packed native project reuse preserving complete nested Actions,
  slots, NLA ordering, influence curves, morph coordinates and masks.
- Frame PNGs and evaluated PLY export with ordinary production verification.

Ten native mutation cases refresh the saved-project publication SHA-256 before
verification. Unsampled strip-influence keys, unsampled nested Action keys,
an unsampled interior non-first key interpolation edit, morph-coordinate edits
and disabled reference tracks are rejected in both the
authored and re-imported projects. Original project/receipt bytes are restored.
The pre-existing seven connected production cases also pass again.

Native verification reconstructs finite supported descriptors from current
saved bytes in a fresh trusted runtime. Host verification independently checks
curve membership, timing, reference poses, influence functions and sampled layer
arithmetic. Packed asset fidelity binds complete admitted nested curves, including
unsampled keys and handles. It refuses unknown dependencies rather than reducing
those to scene bounds.

Limits remain explicit: clips admit LINEAR/CONSTANT integer keys, ordinary
CLIP NLA strips and REPLACE/ADD/SUBTRACT/MULTIPLY. Quaternion COMBINE, retargeting,
authored drivers, arbitrary native property paths, custom absolute Key spacing,
META/TRANSITION strips, animated strip time, NLA modifiers, envelope F-curve
control-point payloads and stateful animation caches remain unfinished.
Neutral geometry publications remain static evaluated snapshots; the native
project is the editable animation delivery.

Reproduce with `tools/qualify_blender_motion.py` and
`tools/qualify_blender_motion_tamper.py`, selecting an explicit trusted runtime.
Retained private acceptance records identify the exact local frozen source and
separate host checks, native cases, mutation cases and inherited evidence.

A focused review repair verifies the declared interpolation at every persisted
key, including keys whose following interval contains no sampled scene frame.
The mutation changes frame3 interpolation across all three components while
leaving the surrounding authored keys and sampled values unchanged.

A follow-up audit reran all ten attacks against the current collection-capable
provider through its complete current-byte native verifier, with two unchanged
native open/save controls through that same entry. Both controls pass; attacks
must reach a fresh native readback rejection, with the exact guard message
recorded. Framework companion metadata deliberately continues to describe the
baseline during these isolated provider tests. A metadata hash rejection alone
is insufficient evidence of an animation guard. Product verification retains all
framework checks.
