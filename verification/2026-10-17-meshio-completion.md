# meshio completion review — 17 October 2026

The new document route converts captured ASCII VTU and legacy VTK 4.2 meshes
with explicit coordinate units. It retains ordered triangle/tetra connectivity
and scalar/vector point/cell arrays. Unsupported formats, topology, metadata and
compression are refused, with no solver-specific integration.

Qualified runtime: meshio 5.3.5 with NumPy 2.5.4 under isolated Python 3.12 on
POSIX. Latest stable meshio 5.3.5 was checked against official PyPI and the
upstream release on 17 October 2026. The Schemaxis host remains dependency-free.
A final native receipt was registered after the frozen parser and shared
configuration fix, and its source digest matched the current tree at closeout.
Later programme source/Help generation requires a fresh receipt; prior successful
runs remain bounded historical evidence.

## Completion checklist

| Item | Review and retained evidence |
|---|---|
| registration | Active `schemaxis.meshio/1` manifest; closed document/process route, geometry handoffs, finite composition and serial resources. Root reviewed scope and activation. |
| schema | Every field required and typed, including units and strict loss policy. Shared authored-schema conformance checks baseline/variant, exact invalid-unit fault and unknown root rejection; eight host tests include literal schema/declaration parity. |
| semantics | Independent ASCII parsers enforce finite numeric bounds, declared integer ranges, IEEE Float32 interpretation, exact flattened topology and scale-relative triangle/tetra orientation. XML DTD/entities/extra sections/nonwhite structural text are refused before native assignment. |
| native-mapping | Public `meshio.read`, `Mesh.points` and `meshio.write(binary=False)` in an isolated worker. Conversion snapshot checks the independently parsed source; separate native process reopens the written output. Official meshio/VTK sources are recorded in readiness metadata. |
| execution | Captured source, trusted worker/config, consumed-input hashes, command/exit evidence, fixed publication membership and per-artifact digests. One deadline and shared process-tree cancellation, POSIX memory/file/CPU caps. Timeout, pre-launch cancellation and cancellation after a real 50,000-cell native process consumed inputs passed. |
| discovery | Curated interchange, VTU and coordinate-unit phrases; ambiguous mesh and negative OCR cases. Actual CLI capability search and all six targeted production Studio search/contextual Help tests passed. |
| guidance | All ten operation/field records reviewed, zero pending/stale. Coordinate units versus field units, exact ordering, required source and strict loss limits explained. |
| help | Local guide, generated operation/schema reference and packaged contextual Help resolve. Root owns common regeneration; final freshness follows the batch freeze. |
| examples | Editable standalone baseline/variant and invalid units. Two Studio starters require an explicit source placeholder. Filled planning, unfilled rejection, immutable insertion and source-edit/undo passed. Literal fixtures include nonzero origin, interleaved triangle/tetra/triangle and point/cell scalar/vector arrays. |
| tests | Eight host tests passed; native qualification includes two baseline/variant cases, seven refreshed-evidence tamper probes, six source refusals, two direct native parser refusals, Float32 and nonround large-origin probes, workflow handoff/reuse/invalidation and two-state finite composition. |
| qualification | Normal shared native conformance and the extended `tools/qualify_meshio.py` acceptance passed. Native consistency is distinguished from independent semantic verification and the known literal oracle. Final source-bound native receipt was registered and checked current at closeout; later common generation requires refresh. |
| maintenance | `upstream.json` pins absorbed meshio 5.3.5 only after successful host/native acceptance, with official release endpoint, scope and repeatable acceptance recipe. |

## Numerical and independent checks

The literal tetra has vertices (10,20,30), (12,20,30), (10,23,30), (10,20,34)
in millimetres, giving positive signed volume 4 mm³. The baseline produces
4e-9 m³. The reverse variant restores 4 mm³. Literal expected connectivity,
all five distinct node IDs, three region values and every scalar/vector tuple
are authored separately from native summaries. Both triangles retain their
position around the intervening tetra in flattened cell order.

Coordinates alone are scaled. Source integers are constrained to their declared
storage range and ±2^53 and compared exactly; Float32 ASCII is independently
rounded using the standard-library IEEE representation before comparison.
Float values compare at relative 1e-11 / absolute 1e-14, reflecting meshio's
roughly twelve-significant-digit VTU ASCII writer. A nonround field and a
1,234,567.891234567 mm origin verified with maximum coordinate error
4.566973075270653e-6 mm. Oriented triangle area vectors and signed tetra volumes
also compare at relative 1e-8 without an absolute floor. A hostile small-cell,
large-origin host case proves coordinate-relative tolerance alone cannot hide
area/volume distortion. Native conversion may therefore refuse a mesh whose
ASCII output cannot preserve these bounds.

Seven adversaries refresh ordinary hashes and framework publication metadata:
changed output field; changed ordered connectivity; changed fields in both
native snapshots; rebound captured-source identity; unexpected mesh output;
unexpected metadata sidecar; and altered trusted worker. Each is rejected.
Direct native malformed/unsupported mesh probes fail and produce no output.
These checks establish consistency and declared semantic preservation, not a
cryptographic signature against coordinated fabrication of every historical file.

## Reproduction and qualification limits

Run host tests with `PYTHONPATH=src python3 -m unittest discover -s tests/unit
-p test_meshio.py -v`, then `tools/qualify_meshio.py --meshio ISOLATED_PYTHON
--output-directory FRESH_DIRECTORY`. The latter runs normal Schemaxis native
conformance and independent extended checks, including a verified VTK artifact
handoff into reverse VTU conversion, unchanged workflow reuse, same-path source
byte invalidation and a two-state unit study. `--register` is reserved for a
fresh successful run after final common source/Help generation.

Source is limited to 16 MiB and output to 32 MiB; no compressed payload expands
behind those bounds. Meshes have at most 100,000 points/cells and sixteen arrays
per association. Native caps: 2 GiB address space, 32 MiB per file, 60 CPU seconds;
retained JSON files also have a 32 MiB read bound. Larger meshes, general mesh
quality/manifold checks, other formats, general metadata preservation, remeshing,
MPI, time batches, live editing and interactive native inspection are outside
this qualification. There is no native dynamic catalogue schema: common generated
literal/authored schemas apply, without manufacturing per-run native snapshots.

Public source material reviewed:
[meshio API](https://github.com/nschloe/meshio#python-library),
[PyPI release](https://pypi.org/project/meshio/5.3.5/),
[upstream release](https://github.com/nschloe/meshio/releases/tag/v5.3.5),
[VTK XML](https://docs.vtk.org/en/latest/vtk_file_formats/vtkxml_file_format.html),
[legacy VTK](https://docs.vtk.org/en/latest/vtk_file_formats/vtk_legacy_file_format.html).

The actual meshio environment also passed a disposable configuration/session
recovery check after the shared executable-symlink fix: both new and recovered
Studio sessions retained the venv interpreter spelling, imported meshio 5.3.5
and NumPy 2.5.4, and reported the intended environment prefix. No real user
configuration was modified.
