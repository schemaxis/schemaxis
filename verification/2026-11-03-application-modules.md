# Application modules and reviewed cache cleanup — 3 November 2026

## Scope

Local Linux x86-64 managed worker dispatch in the development checkout. CLI runs
and Studio Case Runner default to packaged modules, with explicit native opt-in.
Discovery/planning remain host-safe. The existing dependency scheduler, immutable
attempts, artifact/value handoffs and resume are retained. Hosted admission,
publication and commercial distribution are separate.

## Fresh bounded native observations

A two-operation workflow used existing independently packaged application images:

- SymPy 1.14.0 isolated the real roots of x² − 2. Its verified JSON publication
  supplied the polynomial degree through a workflow value reference.
- NumPy 2.5.4 used that degree as its retained component count for the sensor CSV
  PCA workload, with an immutable captured copy of the source file.
- Fresh matching workers verified two jobs and nine publications.
- Resume reused both verified attempts without running either computation again.
- After removing the temporary original source CSV, fresh workflow verification
  still passed using the retained input capture.

Exact immutable local content IDs were
`sha256:e95baa695be572c9663c610447ed5e75506981e39419a69722e563ffc888fefc`
for SymPy and
`sha256:d89f01a936306718ce057fdca98c1b43fd4f3cf5a040396ee96fce613ec67e41`
for NumPy. These are local existing-image observations, not published registry
availability or qualification of every possible operation/input/platform.

A real cache exercise saved a 59,701,760-byte SymPy image archive, then applied a
reviewed archive-removal plan. The pre-existing external image remained available;
only the owned saved archive was removed. No pre-existing image, native app,
project, configuration or execution evidence was removed.

## Automated checks

- Fourteen module-management tests cover ownership, shared images, engine changes,
  immutable downloads, stale cleanup plans, active leases/containers, symlinks,
  offline operation, UI administrator policy and explicit native selection.
- Seven runtime tests cover cross-module value handoff, captured inputs, resume,
  original-input absence, output/capture tampering, route refusal and logical
  input validation before capture relocation. These use worker doubles.
- The existing 32 container-executor tests pass independently.
- The full Studio run passed 742 tests with three skips, including the new browser
  cleanup review. Its module actions use a transport double; native observations
  are listed separately above.
- Generated reference and packaged Help checks pass. The wheel builds and installs
  offline in a fresh environment, with working module/cache discovery commands.
- Release scans cover changed/new source, documentation, tests, definitions and
  the built wheel.

Python regression discovery found 5,206 leaves with no loader errors. The main
bounded run reached 4,693 test starts with zero failures/errors and 363 skip
records at the last progress sample. Its owned scope ended at the 1,800-second
limit while working through workflow-design tests; it is not recorded as a
single-process suite pass. All twelve remaining workflow/design/resource/revision,
xarray and YAML modules then passed in a separate bounded batch: 189 tests, ten
skips. The workflow-design module was included again to cover the interrupted
test. Final focused reruns cover subsequent changes, including the new module
tests, revision CLI compatibility and 149 host-only caption-editing checks with
explicit native selection. Class skips and overlap mean these counts must not
be added as if they were distinct passing tests.

## Limits

The generic application Dockerfile adds Blender and batch FreeCAD packaging
locations; their images were not built or qualified in this change. No image
catalogue was published and no desktop installer or container engine was installed.
Directory/implicit-sibling inputs, interactive container GUIs, GPU/MPI operation
and non-Linux/amd64 hosts are not established by these observations. Native Python
APIs, consoles and authoring previews retain their existing execution route.

Runtime clearing preserves module registration, settings, input captures and
results. Restoring the exact runtime may be necessary before native re-verification.
The cache inventory reports image sizes including shared layers, not guaranteed
reclaimable physical bytes. Ownership/removal/refusal races use an engine double;
real removal of an owned image is not claimed by the external-image cache exercise.
