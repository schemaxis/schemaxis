This example executes the first real Schemaxis ParaView capability: synthetic Wavelet
→ plane slice → VTP geometry export → reopened geometry verification. It uses
the existing catalogue, planner, executor, and provider result contract.

The authoring source is `src/schemaxis/adaptors/paraview/mvp/slice_export.py`: the `SliceExport`
class contains its declaration dictionary and configuration hook. Its arguments
are used by document validation and the Extension CLI contribution hook.
`capabilities/slice_export.json` is exported metadata, not a second hand-authored
specification. Static discovery reads only JSON. Execution refuses declaration
drift. `schemaxis.core.capabilities.CapabilityExtension` makes this pattern reusable.

From the repository root:

```bash
# Point to an installation, a superbuild root, or a pvbatch executable.
export SCHEMAXIS_PARAVIEW_ROOTS=/path/to/paraview
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp describe
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp run examples/paraview-slice/input.json
```

The output directory `slice-result` is relative to the working directory. Its
parent must exist, and the directory itself must not exist. To run again:

```bash
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp run examples/paraview-slice/input.json --output-directory /tmp/another-slice-result
```

The command prints the resolved plan and execution report as JSON, with artifact
URIs and SHA-256 digests. It exits nonzero on failure. The output directory holds
`slice.vtp`, `verification.json`, and the exact submitted `replay-*.py`, including
verification code. No Schemaxis installation is required inside pvbatch. A retained
replay reproduces the native commands but does not itself enforce the host's
exclusive-directory policy; review its output paths before manual replay.

Verification checks finite ordered bounds, nonempty cells and points, every
point's distance from the declared plane, the presence and finiteness of RTData,
and matching summaries after reopening the VTP. It is not a general proof of
scientific correctness or byte-for-byte equality of live and reopened arrays.
The synthetic source is deliberately small; full-data inspection here is not a
strategy for large distributed cases. No render representation is created.

After intentionally editing the declaration dictionary, regenerate its manifest:

```bash
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp export-manifest
```

This is one bounded composite capability, not yet independently composable
reader/filter/writer capabilities or a sweep schema. Case readers, time
selection, images, and nested publications remain subsequent work.

Additional slice arguments now include:

```json
{
  "crinkle": false,
  "triangulate": true,
  "pointMergeMethod": "uniformBinning"
}
```

`pointMergeMethod` also accepts `octreeBinning` and `none`. Crinkle mode writes
`slice.vtu`, retains whole intersected cells, and uses corresponding verification;
triangulation and locator settings are then reported as inapplicable. Native
locator selection is read back, but its effect on duplicate points depends on
the native algorithm/input and is not certified by the current verifier.

The reviewed option dictionaries are in `src/schemaxis/adaptors/paraview/mvp/slice_options.py`.
Other discovered native options are explicitly classified in the capability's
`nativeProperties` metadata; inventory does not imply execution support.

```bash
# Read retained upstream help without starting ParaView:
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp help-option crinkle
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp help-option UseDual

# Explicit developer intake: start the installed application and capture its
# metadata into a NEW directory for review; this does not change declarations:
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp inspect-native --group filters --proxy Cut --output-directory /tmp/slice-intake
```

Native help is attributed to the captured ParaView version. Its accompanying
notice is in `src/schemaxis/adaptors/paraview/mvp/native/ParaView-Copyright.txt`. Capture includes
nested property choices, domains and help but has explicit coverage limits in
the snapshot; it is not a lossless capture of every XML attribute or GUI rule.

Hierarchical browsing is now available:

```bash
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp list
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp list slice
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp help slice.crinkleSlice
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp list slice.sliceType.plane
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp help slice.sliceType.plane.origin
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp list groups.filters
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp help functions.SaveData
```

Add `--json` to `list` or `help` for structured results. These commands read
retained snapshots without starting ParaView. Hierarchical paths are help
addresses; current workflow arguments remain unchanged, and help reports their
mapping. `slice.crinkle` and native names are accepted as help aliases.

To refresh the broad inventory into a new directory for review:

```bash
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp inspect-commands --output-directory /tmp/paraview-command-intake
```

This inventories native definitions (including internal proxies) and public
Python functions; it does not enable new execution capabilities. For full
captured domains and nested choices of a selected proxy, use inspect-native.

A reused slice sweep:

```bash
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp run examples/paraview-slice/sweep.json
```

The optional `sweep` argument uses the shared linear-series declaration. Its
positions are signed distances from `origin` along the normalized `normal`:
`origin + distance * unitNormal`. The example visits x=-5, 0 and 5. Specify a
complete series, normally any three of start/end/spacing/count. This synthetic
provider does not yet inspect bounds to supply missing endpoints. `maxSlices`
defaults to 1000 (configurable up to 10000), checked before materialization or
application startup.

One native source and one slicer are created for the whole sweep. Each position
gets a `slice-NNNN` subdirectory containing geometry and its verification receipt.
The top-level receipt records resolved positions and their provenance, the native
slice identity, verified results, and completed/requested counts. A failure stops
the sweep, preserves already verified files, and identifies the failing position.
While running, progress is recorded before each position; interruption leaves an
incomplete receipt rather than a completed-success receipt. This is progress
evidence, not an automatic resume protocol.

This sequential sweep updates the plane origin; it is not ParaView's simultaneous
`SliceOffsetValues` option. Crinkle mode and oblique normals are supported. With
no sweep argument, the previous single-slice filenames and result shape remain.

A file can now define its own reusable sections and use typed document references:

```bash
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp plan examples/paraview-slice/references.json
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp run examples/paraview-slice/references.json \
  --output-directory /tmp/a-new-reference-sweep
# Both commands also accept JSON on stdin:
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.mvp plan - < examples/paraview-slice/references.json
```

`{"$document": "/dimensions/modelExtents/min"}` replaces a complete value,
retaining its type. References can also supply arrays and whole argument objects.
Custom sections are inert data. The marker uses JSON pointer paths and is
separate from runtime output references. Expressions and string interpolation
are not implemented. Duplicate JSON keys, non-finite values, missing references,
cycles and excessive expansion fail with structured faults.

The report includes the resolved document, reference provenance, CLI overrides,
and plan arguments with declaration defaults. `plan` does not start ParaView;
provider-specific value resolution and native verification still occur in `run`.
Human and AI callers use these same commands, or the same Python planner and
executor.

Relative references are also supported: `{"$document": "./keyword"}` reads a
sibling entry and `{"$document": "../keyword"}` reads from the parent container.
The base is the reference's containing object/array in its original definition;
copying a reusable dictionary does not rebind its internal references to the
consumer. Paths above the document root are rejected. The report retains both
the authored reference and its resolved absolute pointer.
