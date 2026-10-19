# Storage and core programme integration — 17 October 2026

This checkpoint covers the shared-storage, CLI/headless, output-analysis,
debt-audit and adaptor work. Five existing adaptors have been improved and reviewed;
four have native qualification and Premiere has explicit host-only verification.
Ten new adaptors have been reviewed and qualified, completing the initial batch.
Further batches remain authorised through 31 December 2026; an active worker or
successful mock is not a delivered adaptor.
No public release, commit, deployment, tag, data migration or cleanup is implied.

## Integrated behaviour

The shared schema store is called from the common adaptor runtime (normal runs and
analytic visits), workflow/study preparation and Studio checkpoint creation.
Verification checks retained dependencies through the registry, bound direct
verifiers, workflow coordinator and Studio artifact boundary. The original exact
snapshot helper and ParaView category bundle remain compatible. Planning-only
legacy console providers without a schema are exempt; declared schema failures
still propagate. Early native failures can retain incomplete evidence without a
schema, as documented.

Added `schemaxis --version`, exact nested command help and keyword search through
the existing capability catalogue. The dependency-free installed CLI is documented
and exercised without display variables, native packages or a GUI server. Storage
inspection and explicit reviewed plans can create portable backups, stored or
compressed ZIP archives and verified restores. Sources remain intact. Installation
ownership/usage, regeneration guarantees and universal run liveness cannot yet be
established, so uninstall, source removal, derived pruning and automatic cleanup
remain explicitly unimplemented.

- [Schema mechanism, coverage and measurements](2026-10-17-schema-storage.md)
- [CLI/headless/storage qualification](2026-10-17-core-usability.md)
- [Current output lifecycle and measured options](../docs/design/output-storage-review-2026-10.md)
- [Evidenced technical-debt plan](../docs/design/code-quality-audit-2026-10.md)
- [Existing adaptor assessment and initial candidate selection](../docs/design/adaptor-programme-assessment-2026-10.md)

## Integration review and checks

The combined framework command passed **99 tests in 117.428 s, one skip**:

```sh
PYTHONPATH=src python3 -m unittest \
  tests.unit.test_schemaxis_parallel tests.unit.test_schemaxis_workflow \
  tests.unit.test_schemaxis_console tests.unit.test_studio_cases \
  tests.unit.test_adaptor_runtime tests.unit.test_schema_storage -q
```

This includes the new normal-run/study corruption regression: five captures from
one standalone run and a three-state study share one generated schema; removing
that disposable dependency makes both verifiers fail predictably. Application
execution in that regression is a host double, not a native qualification claim.
All 20 initial application schemas/22 routes and workflow capture were enumerated
without native imports. New registry providers extend that coverage on future runs.

An earlier boundary run exposed a legacy dynamic plan-only console provider with
no declared schema binding. The shared capture exemption was narrowed to this
legitimate case; the existing console test and new no-schema/broken-schema tests
pass unchanged in their expectations. Invalid module names in an initial test
invocation were corrected; that invocation is not counted as a successful suite.

Independent storage review found and fixed omission of the workflow coordinator
lock and a verification/extraction time-of-check gap. The final implementation
checks `.coordinator.lock`, keeps a ZIP descriptor across verification/extraction,
bounds actual copied bytes and manifests, and rejects a changed source before
publication. Disposable tests also cover path/membership tampering, stale plans,
explicit confirmation and incomplete preservation. This establishes process-level
integrity, not crash-durability, ownership/ACL preservation or arbitrary relocated
native verification.

Targeted worker checks additionally passed 15 new schema-store tests, seven legacy
snapshot tests, five ParaView bundle tests, 23 core/storage tests and 19 capability
regressions. A clean installed wheel passed 26 real command/module entrypoint
cases. These overlap the integrated suite and must not be summed as unique tests.
These targeted checks preceded the repaired full-suite pass reported below. Bulk
logs and recoverable programme state are under the ignored programme evidence
directory.

The supervisor's independent core/storage rerun passed 20 tests in 6.545 s.
An initial Studio run had three new search failures and one browser timeout.
Regenerating stale metadata fixed two search failures. The remaining failure
exposed a real Help-search issue: the query `place image` matched `replaces`
inside rectangle documentation. Prose matching now requires a word start while
retaining word prefixes and partial native-identifier title matching. All 76
Help/search checks pass, including the new regression. An isolated browser rerun
passed eight tests with one explicit native-preview skip, including the previously
timed-out Workbench save. No assertions or timeouts were weakened.

Built-in release scans passed for tracked files and the public source/docs/example/
test/tool/verification trees, including untracked work: zero non-allowlisted hits,
six allowlisted findings, no private patterns loaded. This is not a publication
or a claim that the prohibited private patterns file was inspected.

## Measurements and remaining work

Ten identical schema captures avoid approximately 88–90% of the storage required
for ten full copies, including index/reference overhead. This is not a saving
against old run paths that never captured any schema: automatic capture adds a
retained contract there. One warm ParaView sample needed 10.894 s for generating
and durably storing ten captures and 0.410 s to verify/read one; generation/cache
optimisation remains a measured follow-up.

The retained integration-workspace scan found 91.7 MB logical / 125.2 MB allocated
files and 19.2 MB exact duplication across distinct inodes. The sample includes
build and qualification material; content equality does not authorise deletion.
Compression and runtime-package proposals retain their compatibility/reconstruction
costs in the output review. No broader storage format redesign was performed.

The audit reproduced removable recovery assertions under `python -O`; explicit
runtime validation is a prioritised focused fix. Ownership/lifecycle recording,
relative evidence formats, run-index recovery, runtime bundle reuse and session
journalling remain proposals with concrete verification plans.

## Reviewed adaptor results

| Existing adaptor | Added useful scope | Qualification |
| --- | --- | --- |
| [Godot](2026-10-17-godot-completion.md) | Named transform groups and parented geometry, with composed local/world transforms and bounds | Native scene save/reopen, literal transform expectations and hostile evidence checks |
| [Aseprite](2026-10-17-aseprite-completion.md) | Captured PNG input into named animation cels with explicit replacement semantics | Native import/save/reopen, independent pixels and retained legacy evidence compatibility |
| [FFmpeg](2026-10-17-ffmpeg-completion.md) | Existing video frame selection, retiming and bounded lossless/lossy encoding | Every decoded frame checked; actual edit-list timing, lifecycle and hostile evidence checks |
| [QGIS](2026-10-17-qgis-completion.md) | Typed attribute selection and grouped null-aware summaries | Native project/table reopening, literal grouped results and source-byte invalidation |
| [Premiere](2026-10-17-premiere-completion.md) | Named multitrack clip ranges, gaps and coverage requirements | Host transport and exact-tick observation tests only; native Windows/macOS access unavailable |

| New adaptor counted | Bounded workflow and independent checks |
| --- | --- |
| [Pandoc](2026-10-17-pandoc-completion.md) | Structured report to HTML/DOCX; checked HTML/OOXML, native reopen and exact trusted stylesheet |
| [Gnuplot](2026-10-17-gnuplot-completion.md) | CSV series to SVG/PNG with linear/log axes and error bars; independent geometry and raster samples |
| [SQLite](2026-10-17-sqlite-completion.md) | Typed JSON tables, keys, one relational join/filter and grouped integer totals; independent row oracle and database reopen |
| [MuPDF](2026-10-17-mupdf-completion.md) | Ordered PDF pages to PNG/text/metadata; literal geometry/colour/text fixtures, native source consistency and page-to-video handoff |
| [ImageMagick](2026-10-17-imagemagick-completion.md) | Exact PNG crop/magnification/rotation/alpha and indexed sheets; independent every-channel checks, including two larger supervisor runs |
| [SoX](2026-10-17-sox-completion.md) | Frame-based PCM16 cuts, gain, linear fades and concatenation; 37,540 independent sample checks plus rate/boundary and workflow/lifecycle checks |
| [Graphviz](2026-10-17-graphviz-completion.md) | Named directed graphs to editable DOT, SVG and plain geometry; independent topology/visibility checks, cycles and 200-node/500-edge native boundary |
| [meshio](2026-10-17-meshio-completion.md) | ASCII VTU/VTK triangle and tetra interchange with coordinate units; independent topology, field values, signed geometry and native reopening |
| [GDAL](2026-10-17-gdal-completion.md) | GeoTIFF windows and nearest grid resizing; independent typed pixels, conditioned affine coordinates, CRS/units/nodata and eight additional supervisor grid ratios |
| [OpenSCAD](2026-10-17-openscad-completion.md) | Declarative mounting plates and spacers to editable SCAD/STL; independent contour, topology, orientation, faceted volume and native reopening checks, plus an actual PrusaSlicer handoff |

OpenSCAD's additional independent review and the resulting fixes are integrated.
Reordered triangle records no longer fail because of last-bit summation changes;
exact oriented facet identity and independent shape checks remain required. Its
documented limits include location-bound execution evidence and the qualified
native version banner. Eleven host tests, three fresh native cases, 18 tamper
probes and additional representation checks passed after review. Further batches
remain authorised through 31 December 2026. Delivery requires reviewed
implementation, examples, documentation and meaningful native evidence; pre-existing
uncommitted adaptors and scaffolds are not counted as new deliveries.

Existing-adaptor strengthening is now recurring: one substantive strengthening
assignment for every two new adaptors. FreeCAD is next, with ordered phases for
parametric parts and variants, assemblies/placement/constraints, then import,
geometry preparation and reliable export. Its three phases count as one adaptor
assignment. The primary mechanical-part workflow will use constrained sketches,
a Part Design Body, a Pad and a through-all Pocket, with persistent named
dimensions supporting ordinary native editing. The parameter foundation has
bounded native qualification, including independent edits and fresh reopening;
the feature-history design and native API probes are underway. This work is not
counted as a delivered strengthening yet. The existing Part extrusion/Boolean
route remains useful alongside the planned Part Design route.

## Wider verification checkpoint

The completed first-batch host snapshot ran **1,723 tests in 710.838 seconds**,
with four failures, three errors and 33 skips. Repairs address the PrusaSlicer
typed geometry input contract, ImageMagick's explicit manual update-policy field,
parser-contract inspection of operation-selected declarations, and two stale
executable-path assertions after preserving virtual-environment symlinks. The
cancellation unit test now isolates schema serialization from its scheduling
deadline, checks that the worker actually observes cancellation, and joins its
thread even if startup fails. All **52 affected tests passed in 87.243 seconds**.
The repaired full host snapshot then passed: **1,723 tests in 718.071 seconds,
33 skips, no failures or errors**. This snapshot captures the completed initial
batch before the next FreeCAD strengthening increment and OpenSCAD review fixes;
those changes have their own qualification and are not covered by this full-suite
result.

The serial Studio snapshot ran **371 tests: 367 passed, one failed and three
skipped**. Tracing reproduced the failure and identified a reload during an
in-flight Designer viewport save, which correctly raised the unsaved-work guard.
The integration test now waits for all windows to finish saving before reload.
It deliberately holds a real save to verify the wait. Six unchanged repetitions
had five failures; all six fixed repetitions passed. No production safeguard,
assertion or timeout was weakened. The final serial Studio suite passed:
**367 passed, zero failed, three skipped in 250.369 seconds**. The additional
OpenSCAD production-browser check passed separately in 2.492 seconds.

All 32 guidance providers have zero pending or stale entries. Both built-in
release-gate scans passed with no non-allowlisted hits and without reading private
patterns. Global admission still reports earlier delivery gaps in Inkscape,
CalculiX and ParaView, plus required-unknown metadata in several existing routes;
this is not a blanket all-provider admission pass. Scoped admission for the
newly delivered and strengthened routes passes.

Native receipts bind common framework and generated Help as well as each adaptor.
Adding another application's Help can therefore stale a previously current receipt.
Each completion note distinguishes its recorded native evidence from current-source
freshness. Fifteen providers passed common native conformance after batch generation
(ten new, four strengthened and the PrusaSlicer handoff). After the browser test
repair, all fifteen passed again and their registered receipts matched that
source snapshot. Subsequent adaptor changes require refreshed receipts before
acceptance. Generated-reference and Help drift checks passed for the same
snapshot (107 reference files, 1,065 Help topics).

After the independent review fixes and FreeCAD parameter-foundation integration,
all fifteen common native recipes passed again and their registered source hashes
were independently checked against the checkout. The generated reference, Help,
guidance and public release-gate checks passed; Help now contains 1,071 topics from
293 files. Fifteen targeted schema/reference integration tests passed. The full
1,723-test pass above remains bound to its earlier snapshot; it is not relabelled
as a full-suite run of these later changes.

The next pair comprises QPDF page assembly and Apache Arrow table preparation,
with FreeCAD as its existing-adaptor strengthening.

## FreeCAD phase one and Apache Arrow integration

Apache Arrow is the eleventh accepted new adaptor. Its six-type nullable CSV
preparation publishes Parquet checked by an independent standard-library reader;
fresh native acceptance also covers exact numeric and timestamp boundaries,
eleven tamper cases, SQLite handoff, reuse invalidation and cancellation.
Independent integration review and actual Studio discovery, Help, typed editing,
validation, cancellation and undo checks passed.

FreeCAD earns the sixth existing-adaptor strengthening through its first phase:
constrained sketches, native Body/Pad/through-all Pocket history and persistent
named dimensions. Both extended native suites passed again on the integrated
source (fourteen check groups each). Real isolated GUI checks cover correct
first-open visibility and fully constrained editable sketches; the Studio
ownership/history editing check also passed. The original assembly qualification
fixture now uses an equivalent literal input, preserving the original example
and its dimension-driven behaviour. Assemblies/placement and import/preparation
remain pending phases and will not count as additional strengthened adaptors.

All eighteen common native route qualifications across seventeen providers passed
and were registered with independently checked current source identities. The
generated 110 reference files and 1,085 Help topics pass drift checks; all
conceptual guidance is reviewed or sourced, and scoped FreeCAD/Arrow admission
has no required failures or unknowns. The public-path release scan found no
non-allowlisted hits. A new full host regression run has started on a frozen
snapshot; its result is pending and is separate from the earlier full-suite pass.

The cumulative ledger is eleven new adaptors and six existing strengthenings,
with no strengthening debt. QPDF remains in progress after its revised native
feasibility gate; it is not counted as delivered.
