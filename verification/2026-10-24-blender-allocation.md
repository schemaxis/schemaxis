# Blender handoff and input-provenance boundaries (2026-10-24)

Scope: `schemaxis.blender/1` and `schemaxis.blender.render/1` host planning and
scheduling hooks (`validateHandoff`, `reusableInputs`). No native mapping, option,
format or absorbed version changed. Host-only; native Blender was not run.

## Defects reproduced before repair
- A render job feeding another render job through `sceneFile` was accepted at
  planning, although a render job publishes images only; it failed only after the
  producer had run natively.
- A `prepareOnly` scene without meshes feeding an image consumer was accepted
  although it publishes no images.
- A malformed or unresolved `scenes` value made `validateHandoff` raise a raw
  `AttributeError`.
- A missing or non-file `.blend`, mesh or CSV input made `reusableInputs` raise a
  raw `FileNotFoundError` / `IsADirectoryError` before dispatch.

## Behaviour now
- `UNSUPPORTED_HANDOFF` (with recovery) for the first two; unresolved scene
  declarations are left to the producer's own plan; legitimate handoffs and
  legacy producers without a scene list are unchanged.
- `RESOURCE_NOT_FOUND`, `INVALID_RESOURCE` and `RESOURCE_UNREADABLE` stay distinct,
  carry the absolute input location and a recovery step.

## Checklist
| ID | Result |
| --- | --- |
| registration, schema, native-mapping | Unchanged. No new native mapping. |
| semantics, execution | Earlier, structured planning rejection of two handoffs; scheduled inputs fail with stable faults. Native execution/verification code unchanged. |
| tests | `tests/unit/test_blender_allocation.py`: 8 tests. Before repair 3 failed and 3 errored (2 controls passed); after, all 8 pass. Also passing: `test_blender_live`, `test_media_geospatial`, `test_schemaxis_workflow`, `test_adaptor_architecture` (54 tests, 4 skipped). |
| discovery, guidance, help, examples | Unchanged; shipped workflow examples still validate (tested). Reference/Help were not regenerated. |
| qualification, maintenance | Native unqualified for the current upstream release: the retained runtime is 5.2.2 and the upstream download page lists 5.2.3. `absorbedVersion` stays 5.2.2; no native receipt is claimed. |

## Not addressed
- `render_job.run` records its failed `result.json` fault as plain text, unlike
  the primary route; render verification reports a vanished original scene as
  generic malformed evidence.
- Draft/human-review limits are unchanged.
