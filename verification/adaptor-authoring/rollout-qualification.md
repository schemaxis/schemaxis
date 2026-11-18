# Adaptor authoring rollout verification

Copyright (C) 2026 David L. F. Gaden.

The shared editor stages a compact edit and uses the owning adaptor or workflow
planner where declared settings depend on other elements. Studio reports a
planner fault before changing the draft. The native checks below used ordinary
documents equivalent to the rows produced by Studio.

| Scope | New evidence |
| --- | --- |
| FreeCAD Body seeds | The Workbench test rejects duplicate and occupied Bodies and Body-owned source solids. FreeCAD 1.1.4 rebuilt and independently verified two named Body histories, with measured volumes of 1,000 and 2,000 mm³. |
| HDF5 object and extract rows | The Workbench test rejects an object path already owned by a link, preserves the original settings, suggests a Name for the new extract and accepts an override. h5py 3.16.0 and h5dump 2.2.0 independently verified two datasets, two hard links and CSV publications `left_values.csv` and `right_values.csv`. |
| Blender production material bindings | The Workbench test rejects competing bindings on one object and then applies the corrected draft. Blender 5.2.3 saved and verified a scene with the same named material independently bound to both mesh objects. |
| ParaView scene rows | The Workbench test uses the Geometry subset control, preserves a saved scene Name and its settings, reopens the group and undoes the transaction. ParaView 5.13.3 verified two geometry artifacts with distinct scene and source identities. An editable state bundle requires one scene. |
| Gmsh physical groups | Gmsh rebuilt a hollow cylinder with separate planar end groups and named inner and outer cylindrical groups. The verifier checked physical names, selector membership and mesh topology. |
| ngspice inductors | ngspice verified an AC example with two inherited inductor records on different terminal pairs and checked the sampled results. The host planner continues to reject ideal loops and an inductive source short. |

These are bounded serial checks. Each ledger entry that claims native
qualification names its route and the applicable case.

## Rollout checks

| Check | Result |
| --- | --- |
| Studio module tests | 940 passed |
| Focused Studio browser tests | 53 passed, including HDF5 native source choices |
| Focused host tests | 315 passed |
| Additional host checks for Blender production, ExifTool Workbench and clock groups, FreeCAD assemblies and Premiere timelines | 188 passed, 3 skipped |
| ParaView and FreeCAD serial conformance suite | 7 passed |
| Inventory, schema reference, assessment index and packaged Help freshness | Passed |
| Inventory unit suite | 50 passed after adding the explicit Shotcut route to the asset and clip exclusions |
| Shotcut host suites | 29 passed |

The generated inventory covers 4,784 items across 54 adaptors and 67 routes.
It records 1,173 multi-mode implementations and 1,226 naming implementations.
The other item rows in those two dimensions have applicability reasons. The
subset inventory retains 793 implemented field surfaces, and four authoring
entries project Batch actions.

## Host failures carried into the rollout

The preceding full host log reported 6,471 tests with 10 failures, 166 errors
and 374 skips. The assessment reference differed from the current generated
report. It has been regenerated. MCP tests and tests using strict execution
admission failed while evaluating stale pins before reaching their intended
assertions.

A read-only snapshot comparison found drift on all six strict routes:
ExifTool, FFmpeg, NumPy, ParaView, SymPy and Workflow. Shared source hashes were
already stale at the starting Git revision. The dirty worktree adds further
source changes. ParaView adds an `authoringReferences` route binding and
widens 1,376 Name and reference patterns to accept a leading digit. The
registered route set, admitted operations, capture slots, forbidden pointers,
operation contexts and qualification references agree with the existing
snapshot. Approval to refresh requires reviewing the changed pinned shared
and adaptor sources and the ParaView route and grammar changes. The strict
snapshot remains pinned while that review is pending.

The focused extents suite reproduced one failure in five tests. Its assertion
allows exactly the `setup` and `native` bindings, while ParaView's frozen
identity implementation also declares `inspect` and `relabel`. The registry
admits those optional bindings. The test and declarations were left in place.
