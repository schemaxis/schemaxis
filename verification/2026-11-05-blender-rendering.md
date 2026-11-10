# Blender rendering and display controls

Owner qualification targets Blender 5.2.3 LTS, build `e13b728c6880`, execution
commit `830a89d2bca2447bab7baafeffbda5224933534b`. Source fingerprint is
`sha256:432e069fd52148849be8ebe32d9fef1d8ce44f94c2575d49f6dfba17e4d10e63`;
runtime archive SHA256 is
`3c37893768fa34d759b1e95496374316a8bade3f0a859293b15bc72154d8aad5`.
Independent integration acceptance remains pending. Whole Blender and the broader
rendering family remain incomplete.

The nine-component source-bound native proof passed:

- Nineteen engine/display assignment and save/reopen cases.
- Twenty-one rendered colour/composition cases: independent piecewise sRGB and
  one-stop exposure expectations, material/object/attribute distinctions,
  different active/render colour selectors, backface visibility, instances,
  uniform output, authored DAG and captured saved-scene routes. Tone-map variants
  establish actual settings and distinct effects, without claiming an exact
  independent implementation of each tone mapper.
- Twenty-one refreshed-hash settings/graph/selector refusals and six unchanged
  native-save positives.
- Nine captured-source refusals, including replacement stored fidelity after
  changed colour payload, integer identifier value/type and custom-double
  metadata. An unchanged-save positive and two authorised field/edit overlays pass.
- A technical enclosure with independently checked forty GLB triangles, bounds
  of 40 by 30 by 30 millimetres, volume 11688 cubic millimetres and a nontrivial
  384 by 288 PNG.
- Independent gamma-two expectations for all three engines: piecewise sRGB
  conversion followed by the square root agrees with decoded RGBA bytes.
- Existing asset eight-case, resource-asset eight-case and collection ten-case
  regressions, including eight collection refusals.

The preceding `ff5a21b` epoch passed fifteen existing-family regression components.
Its exact source identity is retained. Archive comparison limits subsequent
runtime changes to typed asset comparison, its native import and three delivery
metadata files; the affected asset families repeat on the current source. Older
geometry checks are not relabelled as fresh current-source executions.

Host verification passed 142 native-enabled Blender tests with zero skips, five
schema/parser parity tests, production conformance, 6239 reviewed and 246 reference
guidance records with none stale/pending, and private Help generation/search
(1526 topics, 689 files, eleven queries). Four actual Studio browser checks retain
their earlier renderer source identity; the integrity repairs change no declarations
or UI. Shared generated Help, exact integrated full suites, installed packaging and
independent master acceptance remain pending.

Held-out review reopened earlier checkpoints. Per-output colour override and
Workbench wireframe mode changed pixels unnoticed; imported selectors were
unbound; replacement stored asset fidelity could conceal changed source data.
The repair binds scene-following colour and surface mode, observes mesh selectors,
and reconstructs authorised asset state from captured inputs before opening the
submitted project. Later peer review found tolerance admitted changed large
integer IDs/types and small custom-double edits at the provider verification
boundary with replaced readbacks. Stale outer publication metadata separately
refused that attack. Current asset comparison preserves exact integer types/values
and recursively typed custom metadata; native floating-point settings retain
rounding tolerance. These failures and repairs remain separate source epochs.

General image verification decodes bounded PNG bytes, checks dimensions and declared
native state; it does not independently rerender arbitrary images. See
[rendering guidance](../docs/blender-rendering.md). Missing workflows include
Workbench texture-preview intent, MatCap flip, authored viewport opacity/material
roughness/metallic, captured custom OCIO/LUTs, EEVEE probe/cache authoring and render
layers/AOVs/EXR. Native API research does not count as delivered coverage.
