# YAML, scheduled execution and output metadata — 2026-10-09

Implemented YAML input, scheduled execution and output metadata. Process-history
databases and archival/retention features were not implemented.

## Implemented behaviour

- YAML 1.2 input is normalised into the existing JSON-compatible document model.
  Shared schemas, planning and native execution are reused. Optional host parsing
  uses `ruamel.yaml`; Studio includes an offline MIT-licensed YAML parser. Source
  formats, diagnostics, comments, structured edits, saved revisions and undo are
  supported across the Workbench, Designer and Schema Editor. CLI conversion and
  YAML templates/case inputs are supported. See [YAML](../docs/yaml.md).
- Durable schedules capture a document and its digest, enforce allowed providers,
  and use the existing execution service. Once, interval and local calendar
  triggers support preview, revisioned controls, bounded catch-up/retry, expiry
  and restart recovery. CLI, agent methods and Studio expose controls; an
  independently supervised foreground worker owns execution. See
  [scheduling](../docs/scheduling.md).
- Published artifacts receive size/hash/spatial metadata companions and a
  committed membership manifest. Native verification remains independent;
  companion deletion or tampering prevents verified reuse. ParaView slice images
  record four ordered world-space image-edge intersections with an observed
  planar slice. Other adaptors provide observed bounds, transforms, counts,
  CRS or units where available. Unsupported spatial data remains explicitly
  unknown. See [output metadata](../docs/output-metadata.md).

## Qualification

The complete host suite ran with the optional YAML extra: 1,147 tests, 1,120
passed, 26 skipped and one failure. The failure is the existing adaptor admission
check described below; it also fails on the unchanged starting revision. No new
test failures remain.

The complete Studio suite ran serially: 220 tests, 217 passed, three skipped,
zero failures. The optional YAML browser test was then run with the host YAML
extra and passed, accounting for one of those skips. The two remaining skips
require native qualifications not enabled in that browser run.

The wheel built successfully. Its packaged files include the scheduler,
metadata publisher, host YAML module, offline browser parser and accompanying
MIT licence; its metadata declares the optional YAML extra. Generated module
documentation matches the source, and `git diff --check` passes.

A real serial ParaView run qualified the combined path: YAML load, durable once
trigger, native execution, artifact metadata, execution verification and bounded
agent resource metadata inspection. Both resources verified. All four PNG corner
coordinates lie on the observed slice plane at z=0. The once schedule completed
and its worker closed. This is a native ParaView qualification; it does not claim
fresh native qualification of every installed adaptor or MPI execution.

Local evidence, intentionally ignored by Git:

- `evidence/implementation-20261009-host.log`
- `evidence/implementation-20261009-studio.log`
- `evidence/implementation-20261009-yaml-browser.log`
- `evidence/implementation-20261009-baseline-admission.log`
- `evidence/implementation-20261009-wheel.log`
- `evidence/scheduled-yaml-native-20261009/qualification.json`

The adaptor admission test's required `studio.guidance` unknowns reproduce on a
clean archive of the starting Git revision. No readiness criterion was weakened
to hide this existing failure. Browser tests with stale labels or conceptual-help
selectors were corrected against the current UI; a real source-load projection
race was fixed by synchronously refreshing comprehension after load.

## Operational limits

Install the YAML extra before accepting YAML on the host (`pip install
'schemaxis[yaml]'`, or `pip install '.[yaml]'` from this checkout). JSON-only core
use remains dependency-free. YAML-to-JSON conversion discards comments.

Registering schedules does not start an owner. Run the command shown by Studio's
Worker setup panel or `schemaxis schedule --workspace PATH serve`, with normal
operating-system supervision when restart persistence is required. External input
paths are retained references; their contents are not backed up by scheduling.

Metadata describes published artifacts, excluding its own companions and
execution infrastructure such as logs and temporary runtime packages. Old
publications without companions need migration or rerunning. Manifest-last
publication is a recoverable commit protocol, not an atomic multi-file filesystem
transaction. Image-edge coordinates describe viewport placement rather than
per-pixel surface depth; general renders use the camera focal plane explicitly.
