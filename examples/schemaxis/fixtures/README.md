# Native acceptance fixtures

`blender-cube.blend` is a self-contained Schemaxis scene produced from
[`blender-admission.json`](../blender-admission.json) by the primary Blender route
on Blender 5.2.2. It contains the analytic side-length-2 cube, declared material,
camera and trusted Schemaxis node/visibility metadata. No external libraries or
unpacked images are required. Its publication was independently verified and
reopened before being copied here. This fixture is input data, not executable code;
the saved-scene runner disables automatic scripts.

To regenerate, run the JSON example into a fresh directory using the configured
Blender runtime, verify it, then copy its single scene publication here. Review
changed geometry and native version before replacing the fixture. Source-bound
qualification includes these exact bytes, so replacement invalidates the saved-scene
receipt. Do not regenerate solely to silence a stale qualification check.
