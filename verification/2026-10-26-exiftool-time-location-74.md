# ExifTool time and location workflows, objective E3: verification note

Status: **E3 implemented; focused host, native, lifecycle, workflow and mutant checks were run for this note's scope; independent family review and the global
union gates (all native qualifiers, the full host suite, shared fixtures, privacy and package checks) are separate and are not claimed here.** This note covers
`reconcileTime`, `locate`, `correctTime`, `setLocation` and `geotagFromTrack` on route `schemaxis.exiftool/1`. No upstream registration or qualification label is
changed by this work, and nothing here certifies photograph provenance, capture time or location.

## What was checked

| Area | Evidence |
| --- | --- |
| Foundations | Host tests with hand-written literals: calendar and offset arithmetic, geodesy (analytic equator and meridian cases), GPX security and bounds, location quantisation, edition classification, clock model groups, references, drift and simultaneity (`tests/unit/test_exiftool_e3_clocks.py`, `_geodesy.py`, `_gpx.py`, `_locations.py`, `_time.py`). |
| Read operations | `reconcileTime` and `locate` host and native cases (`tests/unit/test_exiftool_e3_read.py`). |
| Write operations | Real ExifTool 13.55 writes read back by the standard-library walkers: `test_exiftool_e3_correct.py` (T-cases, mixed-run slots, plan-only and plan application, mutants), `test_exiftool_e3_place.py` (L-cases, the edition matrix, cross-operation order tests, mutants), `test_exiftool_e3_geotag.py` (G-cases on analytic equator placements, gap, overlap, elevation, correction plans with forged offset, fraction, argument and target controls and genuine EXIF, XMP, IPTC and sub-second controls, mutants). |
| Lifecycle | `test_exiftool_e3_lifecycle.py`: a genuine write process of each new operation is held, its `/proc` argv (with the empty `-config` argument) recorded, its process group ended with SIGKILL before cleanup, and the absence of a success publication and of the safety-net kill checked. |
| Public workflows | `test_exiftool_e3_workflow.py` and `tools/qualify_exiftool_time_location_loop.py`: edit, correct, geotag, inspect and audit chains through `$artifact` bindings, typed slots, reuse and invalidation (changed reference, GPX or plan bytes, folder membership; a modification time alone reuses), folder and mixed folders and `TRACK_RESOURCE_LIMIT` at run time. |
| Surfaces | `test_exiftool_e3_surface.py`: schema, guidance, search cases (geotag and time shift positive; rename, raw tags, expressions and reverse geocoding negative), readiness and Studio starters. |

## Reproduce

Host (no native process unless `SCHEMAXIS_EXIFTOOL` names an absolute ExifTool 13.55 script, which also enables the native classes):

- `PYTHONPATH=src python3 -B -m unittest tests.unit.test_exiftool tests.unit.test_exiftool_workbench tests.unit.test_exiftool_write tests.unit.test_exiftool_write_complete` and the `tests.unit.test_exiftool_e3_*` modules.
- `python3 tools/studio_guidance.py --app exiftool --check` and the generate tools in `--check` mode.

Native, serial only (no MPI claim). Choose a fresh output directory for each command:

- `PYTHONPATH=src python3 tools/qualify_exiftool_time_location.py --exiftool /abs/exiftool-13.55/exiftool --output-directory DIR` runs the native, mutant and lifecycle classes.
- `PYTHONPATH=src python3 tools/qualify_exiftool_time_location_loop.py --exiftool /abs/exiftool-13.55/exiftool --output-directory DIR` runs the public agent loop and the workflow chains.
- `tools/qualify_exiftool_agent_loop.py` (the E1 read loop) also runs against the final source.

## Limits

- Every expected value is a literal derived by hand; ExifTool output is never the oracle for a value it wrote. Mutant cases are synthetic edits of retained records and are distinguished from real native observations in the reports.
- Declared references, assumed offsets, positions, vertical references and track datums are never verified; an interpolated position has no claimed accuracy.
- GPS-only 2.4 altitude semantics are an inference labelled as such; legacy readers may not recognise the sea-level references. A write that would create an Exif directory under an untouched height is refused.
- JPEG copies only. Exposure or location transfer between copies, sidecar altitude, renaming and reverse geocoding are not provided.
- Serial local runs of ExifTool 13.55 against a small private synthetic corpus; this is not an exhaustive or global acceptance.
