# HDF5 multi-node MPI: future work and acceptance criteria

Status: **future, important; not part of v1.** Version 1 of `schemaxis.hdf5/1` supports MPI only on
one local machine: `parallelWrite` and `extractData` with `parallel` launch the configured `mpiexec`
with `--host localhost:N` and the shared-memory transport, and were qualified with Open MPI 4.1.7
and 2-3 ranks on one workstation. This scope was accepted explicitly for v1. Nothing in the product,
its readiness bundle or its evidence claims multi-node correctness, parallelisability on a cluster or
parallel performance. This document records what a future multi-node release must establish before
any such claim is made.

## Scope of the future work

1. **Deployment.** Launch ranks across nodes from trusted configuration (scheduler integration for at
   least Slurm, or an explicit host file), with the rank-to-node map recorded; keep authored input free
   of hosts, launch commands and environment. Inter-node transports (for example UCX or TCP) are
   configured, recorded and verified rather than inherited silently.
2. **Shared storage.** Run against a parallel or network file system (for example Lustre, GPFS or NFS)
   with the file system type, mount options and striping recorded; refuse node-local paths that other
   ranks cannot see.
3. **Correctness of parallel I/O.** Collective and independent writes and reads of row blocks, of
   non-contiguous hyperslabs and of chunked/compressed datasets (parallel compression); collective
   metadata operations and object creation; attribute writes from one rank; uneven and empty
   partitions; more ranks than rows.
4. **Failure handling and recovery.** Rank or node loss, a rank that fails before or inside a
   collective, a full or read-only target, file-system timeouts and scheduler pre-emption: the run
   must refuse with a located, structured fault, leave no file presented as complete, and be safe to
   rerun.
5. **Provenance.** Every rank receipt records rank, node, process, MPI implementation/version,
   transport, HDF5/h5py build and the file it opened; the host requires the complete, distinct set.
6. **Independent verification.** After the parallel job, the file is reopened on a different node
   than rank 0 by the serial runtime and by h5dump, and the values are compared with host-computed
   expectations, as in v1.

## Acceptance criteria

- **Distributed fixtures:** at least 2 nodes x 2-4 ranks per node; datasets large enough that every
  rank owns several chunks (for example 4 GiB float64 across 64 MiB chunks), plus small edge cases
  (rows < ranks, ragged last block, empty partitions, compound and big-endian elements).
- **Partitions:** axis-0 row blocks and strided hyperslab partitions, both collective and
  independent I/O, uncompressed and gzip-compressed (parallel compression) chunked storage.
- **Collectives:** collective metadata on/off, dataset creation and attribute writes performed
  collectively, verified by rank receipts and by a serial reopen.
- **Failure cases:** killed rank before and during a collective write, unwritable target, missing
  shared mount on one node; each yields a structured refusal at a stated location and no published
  output, followed by a successful rerun.
- **Recovery:** a rerun after each failure produces a byte-for-byte verifiable file and identical
  independent values.
- **Performance and scaling:** strong scaling (fixed total size, 1/2/4/8 ranks over 1/2/4 nodes) and
  weak scaling (fixed size per rank) for write and read, reporting throughput, wall time, per-rank
  peak memory and parallel efficiency, together with the hardware, network, file system, striping
  and library versions; results are compared with a serial baseline and recorded as evidence, with
  any regression threshold stated before the run.
- **Claims:** documentation, readiness and discovery are updated only for the configurations that
  were actually qualified.

## Not affected

Serial operations and local MPI remain as qualified in v1. This backlog changes no v1 behaviour.
