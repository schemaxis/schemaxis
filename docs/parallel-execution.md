# Parallel execution and restartable workflows

Schemaxis can now schedule independent native jobs concurrently, reserve resources,
retry incomplete jobs, and render groups of views from a previously prepared Blender
scene. Legacy workflows without execution settings keep their serial schedule.
Native objects remain process-local. Only verified files cross job boundaries.

## Start with a bounded allocation

```json
{
  "version": "schemaxis.workflow/1",
  "execution": {"maxWorkers": 2, "cpus": 4, "memoryMB": 4096, "gpus": 1},
  "operations": [
    {
      "id": "surfaces",
      "execution": {"threads": 2, "memoryMB": 1024, "timeChunkSize": 2},
      "document": {"version": "schemaxis/1", "times": [0, 1, 2, 3], "nodes": [], "scenes": []}
    }
  ]
}
```

The empty nodes/scenes above are placeholders. Runnable examples are
[parallel-timesteps.json](../examples/schemaxis/parallel-timesteps.json),
[blender-render-groups.json](../examples/schemaxis/blender-render-groups.json), and
[mpi-sphere-slice.json](../examples/schemaxis/mpi-sphere-slice.json). A complete CFD
volume/slice/reduction and file-handoff example is
[foam-native-parallel.json](../examples/schemaxis/foam-native-parallel.json).

The coordinator starts a job when every referenced producer operation has verified
all its batches and the job fits the remaining resource budget. Unrelated operations
can overlap. References still point to earlier operations in the authored list;
that list is a valid topological ordering, not a mandatory serial execution order.
The coordinator records results in planned order regardless of completion order.

Global execution settings:

| Setting | Default | Meaning |
| --- | --- | --- |
| `maxWorkers` | 1 | Maximum concurrent native jobs |
| `cpus` | Host logical CPU count | Shared CPU-slot budget |
| `memoryMB` | 8192 | Shared declared RAM budget |
| `gpus` | 1 | GPU render slots; currently only 0 or 1 is supported |

Operation execution settings:

| Setting | Default | Meaning |
| --- | --- | --- |
| `threads` | 1 for ParaView; Blender render threads otherwise | Threads per MPI rank or Blender process |
| `ranks` | 1 | ParaView MPI ranks; reservation is ranks × threads |
| `mpiexec` | None | Required absolute launcher path when ranks > 1 |
| `memoryMB` | 1024 | Reservation for the entire job, including all ranks |
| `gpus` | 1 for CUDA/OPTIX, otherwise 0 | Exclusive GPU slot reservation |
| `timeChunkSize` | No splitting | Number of explicit timesteps per independent batch |

RAM reservations are estimates used for admission, not OS-enforced limits. Set them
from measured memory consumption, with headroom for the OS and other applications.
Thread settings constrain common OpenMP, BLAS and VTK pools; they are not CPU affinity
or cgroup limits. Blender's reservation must match `render.threads`. The single GPU
slot prevents simultaneous renders competing for the same device; multi-GPU device
assignment and cluster scheduling remain future work.

## Batches, identities and limits

Time batching requires a finite, explicit `times` list. Each contiguous batch keeps
the full analytic parameter sweep and native object reuse within its own process.
The original unsplit expansion/publication budgets are checked before splitting.
Automatic source-time discovery and splitting an analytic axis are not supported by
this first batching contract. Use separate operations for independent parameter
sets, or keep the analytic sweep together when reuse is valuable.

Jobs have stable identities `operation/batch`, with original `timeIndices` recorded
alongside each batch. Native state indices and object identities are local to that
batch. Artifacts are concatenated in batch order, so `$artifact` indices do not
change with completion order. Every artifact is checked for exact planned membership;
missing or duplicate jobs fail verification. A downstream operation currently waits
for the producer's entire operation, not individual early artifacts.

## Restart and cancellation

```sh
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/parallel-timesteps.json \
  --paraview-root /path/to/paraview --output-directory evidence/parallel-run
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/parallel-timesteps.json \
  --paraview-root /path/to/paraview --output-directory evidence/parallel-run --resume
PYTHONPATH=src python3 -m schemaxis verify evidence/parallel-run
```

Resume requires the unchanged authored workflow. Completed attempts are reused only
after native receipt/artifact verification, authored-plan checks, dependency checks
and available input fingerprints. Generated geometry is reusable. Blender's explicit
glTF and blend inputs are fingerprinted. ParaView external readers conservatively
rerun because an individual filename does not describe all case files, companion
files or resources. This is deliberately not a general dependency cache.

Every attempt gets a new directory such as `surfaces/batch-0/attempt-0002`. Earlier
attempts remain for diagnosis. A process or file existing is never enough to reuse
an attempt: it needs a complete verified job receipt. Successful jobs retain the
runtime archive that actually produced them, so a resumed workflow may contain
verified attempts from different runtime snapshots.

On a job failure, the coordinator stops admitting jobs and cancels active siblings.
Native execution uses isolated process groups; cancellation and timeout terminate
those groups and tracked local descendants, including MPI workers that create
separate process groups. Linux process birth times protect against PID reuse. Completed verified attempts are retained.
Ctrl-C follows the same cleanup path. The coordinator holds a filesystem lock to
prevent two resumptions writing the same workflow simultaneously. Version probing
uses the existing separately bounded interpreter probe and can delay cancellation
during startup; remote MPI process cleanup is not qualified.

## Blender: prepare once, render view groups

Set `scenes[0].prepareOnly` to `true` in an ordinary Blender document. It still needs
one camera writer to establish the saved camera, but publishes only the saved scenes
and performs the normal fresh-process scene reopening check.

Then reference a scene from a render operation:

```json
{
  "id": "front",
  "document": {
    "version": "schemaxis.blender.render/1",
    "sceneFile": {"$artifact": "prepare", "index": 0},
    "render": {"threads": 2, "samples": 16},
    "size": [320, 240],
    "cameras": [{"direction": [1, -2, 1]}]
  }
}
```

Several render operations can share that source. Each opens a retained local scene
copy, configures lighting/render settings, renders its camera group and checks that
geometry/material snapshots remain unchanged. Images are decoded natively and their
hashes, dimensions and camera state are checked. Source digests are checked again
on verification/resume. Scene loading disables Python auto-execution. Inputs must
be Schemaxis scenes containing metadata and self-contained assets; linked libraries
and unpacked external images are rejected. Existing scenes created before metadata
support must be prepared again. Saved-scene cameras are literal, not analytic markers.

Discover the contract with `schemaxis query`, `schemaxis plan`, or
`schemaxis schema --section saved-scene-render`. A generated schema is retained as
[blender-render.schema.json](generated/blender-render.schema.json).

## MPI qualification boundary

MPI uses `mpiexec -n N pvbatch`, with one Python driver, never `--symmetric`.
Select the launcher matching the ParaView build's MPI installation. The native
controller's process count must match the requested rank count and is recorded in
the receipt. Resources account for ranks multiplied by per-rank threads.

The qualified operation subset is `sphere`, `slice`, `foam`, `merge`, `calculator`,
`surface`, `outline`, `integrate`, `readParallelPolyData` and
`readParallelUnstructuredGrid`. Adaptor capability discovery reports this policy;
the generic scheduler does not need to know ParaView filter names. Other operations,
explicit export writers, glTF publication and global tuple sampling are rejected
before MPI dispatch. Serial operation remains available.

ParaView owns mesh partitioning, filter execution, reductions and rendering.
Geometry uses native parallel XML writers (`.pvtp`/`.pvtu` with their piece files).
Schemaxis never gathers the full MPI mesh for publication. Each rank fingerprints
its coordinates, topology and point/cell/field arrays in bounded chunks. Only compact
fingerprint records return to the driver. Native readback must reproduce every
nonempty piece exactly; whole pieces may move between ranks. Arbitrary repartitioning
is not covered by this verification contract. Empty ranks are allowed but every rank
must report. Companion-file manifests cover the entire referenced file closure;
verification streams hashes and rejects missing, changed or escaping files.

MPI measurement tables must target `integrate` outputs. Native ParaView computes
the global reduction; Schemaxis collects only the resulting scalar records and
checks the CSV against rank evidence. It does not fetch backing geometry arrays.
Downstream operations can reopen the parallel XML artifact with the corresponding
parallel reader. Metadata and every piece must remain together on a filesystem
accessible to all ranks. This is qualified locally; `pvserver`, remote launch,
cluster scheduling and arbitrary filters have not been qualified.

Reproduce the local tutorial qualification with explicit paths:

```sh
PYTHONPATH=src python3 tools/qualify_cfd_parallel.py \
  --case /path/to/coupe_AMI.foam --paraview-root /path/to/paraview \
  --mpiexec /path/to/matching/mpiexec --ranks 2 \
  --output-directory evidence/cfd-qualification
```

The case must be decomposed. The example camera targets the vehicle tutorial;
adapt its framing and colour range for other cases. Source-time discovery works
within a native job; automatic source-time splitting into independent jobs remains
unsupported.

## Measurements and acceptance

Every native dispatch retains full stdout/stderr logs and a metrics JSON file with
elapsed time, command, reservation and sampled aggregate process-tree RSS, plus process-group RSS for compatibility.
Tracking includes local MPI workers outside the launcher process group. RSS is
Linux-specific, includes shared pages more than once, and can miss short peaks.
It is a diagnostic measurement, not an exact physical-memory high-water mark.
Native receipts include apply/publication timings for ParaView and geometry/render/
save timings for Blender. Saved-scene renders separate load and render time.

`tools/qualify_parallel_execution.py` runs alternating serial/parallel benchmarks,
checks exact geometry hashes and observations, deliberately fails a worker after
native execution, then checks verified reuse and retained retry attempts. On this
machine, the first qualification measured a 1.51× median speedup (15.41 s → 10.19 s)
for five small geometry jobs. This demonstrates scheduler throughput, with startup
cost prominent; it does not predict scaling for large CFD cases or GPU rendering.

The 004 CFD tutorial qualification used 1,234,240 cells across two ranks. Native
distributed volume and slice readback passed, and a downstream operation reopened
the volume and reproduced its integrals. Serial/MPI integrals agreed within relative
1e-8 and absolute 1e-7 tolerance. Two source-selected timesteps (0.8 and 1.0) also
passed. The full suite passed 375 tests. See the retained
[qualification summary](../verification/2026-09-19-native-parallel-cfd.json).
These timings are not an equal-work speedup benchmark: serial omits full-volume
publication. Sampled aggregate RSS was about 1.98 GB for MPI and 1.44 GB for serial;
shared pages may be counted repeatedly. MPI shared-memory windows are not added by
Schemaxis; native applications retain ownership of their memory layout.

The execution model is local and bounded. Future steps are broader case-specific
MPI qualification, manifests for external input reuse, richer state partitioning,
per-artifact readiness, explicit multi-GPU placement and remote dispatch.
