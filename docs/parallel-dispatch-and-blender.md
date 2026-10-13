# MPI dispatch and Blender presentation geometry

## Reproduced dispatch

`tools/qualify_paraview_mpi.py` reproduces normal parallel batch dispatch:

```sh
python3 tools/qualify_paraview_mpi.py \
  --pvbatch /path/to/paraview/bin/pvbatch \
  --mpiexec /path/to/matching/mpi/bin/mpiexec \
  --ranks 2 --output-directory evidence/mpi-probe
```

The tool requires a fresh output directory, captures the exact command and log,
limits the run time, terminates the process group on timeout, and verifies that
all requested ranks contributed geometry to a gathered sphere. Successful exit
alone does not pass. It is a qualification tool, not a new Schemaxis execution mode.

The inspected superbuild's `tests/paraview.test.cmake` launches `pvbatch script.py`
directly. Its launcher handles library selection and forwarding; it does not
allocate MPI ranks. The local `build-v5.13.3` enables system MPI and its ParaView
CMake cache identifies OpenMPI 4.1.7 under the user's ThirdParty installation.
Use that installation's `mpiexec` for this build. The downloaded ParaView package
has its own bundled launcher. Do not mix launchers between MPI implementations.

Normal `mpiexec -n N pvbatch script.py` executes the Python driver on rank zero,
while native parallel algorithms execute across ranks. `--symmetric` instead
executes the Python script on every rank. Schemaxis's current receipt writes and
publication checks were written for a single driver; symmetric execution would
need explicit ownership and collective ordering throughout.

On 2026-09-18, the source superbuild passed with two ranks and the downloaded
5.13.3 package passed with four ranks. Both tests verified distinct process IDs
in gathered geometry. This does not qualify distributed rendering, all writers,
decomposed CFD readers, or an entire Schemaxis workflow. Fetch gathers geometry to
the driver, so it is also not a scalable verification strategy for large cases.

The probe uses `ProcessIdScalars`, deprecated but available in the pinned 5.13
runtime. The replacement `ProcessIds` produced an identity array in serial, but
the array was absent after parallel Fetch in these experiments. Initial probes
failed rather than accepting missing rank evidence. Revisit materialisation of
implicit arrays before qualifying a newer ParaView release.

Public references:
[ParaView parallel processing](https://docs.paraview.org/en/v5.13.0/ReferenceManual/parallelDataVisualization.html)
and [Python batch options](https://www.paraview.org/paraview-docs/v5.13.3/python/paraview.html).

## Blender extensions

`assignMaterial` takes a mesh `input` and a typed `material` input. It copies the
evaluated mesh, preserves its world transform, and assigns the material to all
faces. The upstream object and material slots stay intact. This enables a CFD
surface to be restyled independently for multiple presentations.

`wireframe` exposes positive `thickness`, bounded `offset`, `replace`, and
`boundary` options through Blender's native modifier with property readback.
It participates in the existing analytic updates, dependency invalidation,
object identity checks, saved-scene reopening and image verification.
See [Blender's modifier API](https://docs.blender.org/api/main/bpy.types.WireframeModifier.html).

Run the bounded cross-application example:

```sh
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/paraview-blender-wireframe.json \
  --paraview-root /path/to/paraview --blender /path/to/blender \
  --output-directory evidence/wireframe
python3 examples/schemaxis/check_blender_wireframe.py evidence/wireframe/presentation
```

It exports a ParaView sphere, imports the verified artifact into Blender, assigns
a metallic blue material, and varies wire thickness across two states. It saves
two PNGs and two editable blend scenes. Independent checks establish sphere
volume, unchanged geometry after material assignment, source material isolation,
wireframe topology, thickness response and downstream-only invalidation. The
existing `solidify`, `boolean` and `transform` operations can be composed with
these nodes for shells, cutaways and contextual overlays.

This is presentation geometry: glTF does not establish CFD field or unit fidelity,
and a triangle wireframe shows tessellation rather than physical flow structure.
Wire thickness uses mesh-local units and inherits the source object's transform.
The example was visually inspected; its dense triangular cage is a technical
mesh view, not a finished scientific figure or manufactured lattice design.

## Development admission

This adaptor now provides the [development kit](adaptor-development.md) delivery
contract, operation selection guidance, explicit optional-feature decisions and
an editable [acceptance example](../examples/schemaxis/blender-admission.json).
Run the common host/native conformance recipe and inspect its scoped source-bound
receipt; structural admission alone is not native qualification. The
[current audit](design/adaptor-framework/AUDIT.md) records native availability and
exact qualification limits.
