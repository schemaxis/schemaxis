# Sandboxed worker images

Status: **five fixed image cases observed against the same final core and wheel**.
Local bounded checks passed on 29 October 2026 in Winnipeg for exact roots, PNG
metadata, PCA, audio encoding and a headless sphere render. The five families have
[Dockerfiles and an input contract](../containers/README.md). No worker image is
published; the measurements below support one shared bounded resource envelope,
with no assigned price.

Each definition pins the official Python 3.14.4 slim-trixie Linux/amd64 manifest
`sha256:2409290aa375de35f6492db84c700067d5c4c2aacfaf770c155d7528fb68bcf1`.
Application bundle and wheel hashes remain mandatory build inputs. A mutable tag, guessed hash or host installation is insufficient.

## Licence decisions

Schemaxis remains Apache-2.0. Native applications and image base components keep
their own licences. The core's `NOTICE` and `LICENSES/` cover material shipped in
the core; they are not the complete notices for redistributing native runtimes.
Include every binary distribution's own dependency notices and corresponding
source obligations in the image release materials. Review the actual pinned
build, not only the application's headline licence.

| Family | Pinned application | Redistribution decision | Required release material |
| --- | --- | --- | --- |
| ExifTool | 13.55 | Permitted under the Perl Artistic License or GPL; select and comply with one alternative. [Official upstream licence statement](https://raw.githubusercontent.com/exiftool/exiftool/master/README). | ExifTool copyright/licence; bundled Perl/module licences and notices; modification/build and source material required by the selected terms. |
| SymPy | 1.14.0, mpmath 1.3.0 | Permitted; SymPy BSD-3-Clause and dependency terms. [Official SymPy licence](https://github.com/sympy/sympy/blob/master/LICENSE), [mpmath licence](https://github.com/mpmath/mpmath/blob/master/LICENSE). | Copyright, licence/disclaimer and dependency notices; no implied endorsement. |
| NumPy | 2.5.4, OpenBLAS 0.3.34 | NumPy/OpenBLAS have BSD terms; the rebuilt bundle's GCC runtime dependency closure remains under review. [Official NumPy licence](https://numpy.org/doc/stable/license.html), [OpenBLAS licence](https://github.com/OpenMathLib/OpenBLAS/blob/develop/LICENSE). | Complete NumPy, OpenBLAS, GCC runtime and Python/base notices, plus corresponding source or other materials required by the actual dependency terms. |
| FFmpeg | 9.0.2, optional pinned x264 build | Permitted under the applicable GPL terms when built with `--enable-gpl --enable-libx264`; this image target is not described as LGPL-only. [Official FFmpeg legal page](https://ffmpeg.org/legal.html), [x264 project](https://www.videolan.org/developers/x264.html). | Matching FFmpeg/x264 source, build configuration and licence/notices. Confirm codec/patent obligations for the actual commercial distribution before release; copyright permission alone does not decide them. |
| ParaView | 5.13.3 OSMesa/MPI/Python 3.10 | ParaView itself is BSD-3-Clause; this binary bundle's redistribution gate remains unresolved. [Official licence and dependency-notice guidance](https://www.paraview.org/license/). | Complete distribution notices/SPDX records and corresponding source/relink material required by the included components, including graphics dependencies. No implied Kitware endorsement. |

The inspected official ParaView OSMesa archive has SHA256
`7c63b9aa349950358b8fd323b1dc0b8c7e6ad9439362dbbdd9a38180c92b4d77`.
Its bundled SPDX records declare, among other dependencies, Gmsh under
`GPL-3.0-interface-exception` and OCCT under `LGPL-2.1-or-later`. The full bundle
is therefore not classified as BSD-only. Source/relink release materials and
the additional graphics/GCC runtime closure require review before distribution.
Any proposed smaller plugin subset also needs measured dependency closure.
Native geometry/rendering acceptance does not resolve this distribution gate.

The rebuilt OpenBLAS target is specifically `HASWELL`, with dynamic architecture
dispatch disabled and one thread. It requires AVX2 and FMA CPU support;
`linux/amd64` alone does not establish compatibility. Those flags were observed
on every logical CPU of the build host. The corresponding NumPy image passed
the fixed PCA/runtime case on that CPU target. A different target needs its own
pinned build and native acceptance.

Premiere is excluded from hosted image distribution. Its existing local bridge
requires an independently licensed host application and has no native Linux
qualification. Other commercial/non-redistributable runtimes require their own
self-hosted arrangement and are not silently included.

## Execution contract

Definitions select UID/GID 10001, remove package managers from the final runtime,
provide read-only application configuration under `/opt/schemaxis`, and default to
`python3 -I -B -m schemaxis`. Their default working directory is `/job`.
**Dockerfile metadata does not enforce a read-only root or disable networking.**
The trusted runner must enforce all of the following before execution:

- Select an accepted immutable image digest from a trusted image resolver;
  documents cannot supply images, launch commands, mounts or runtime overrides.
- Fresh container, non-root UID/GID, no capabilities, no privilege escalation,
  no engine socket, no host credentials/configuration, no host namespaces/devices,
  and the platform's enforced syscall policy.
- No network, a read-only root, bounded memory with no swap, CPU, PIDs, time,
  output size and disk/inode use. A bind mount alone provides no disk quota.
- One owned job directory as the only writable filesystem mount. Use the same
  absolute job path on host and in container when receipts contain absolute paths;
  set the working directory explicitly. Do not rewrite receipt strings to pretend
  paths agree. Do not mount a writable `/tmp`, cache or home outside the job.
- Set `HOME`, `TMPDIR` and cache directories beneath that owned job directory,
  with ownership allowing UID 10001. The `/job` defaults only apply when that is
  the actual mount. Stage captures only through the trusted path policy.
- Independently supervise timeout/cancellation of the actual container and its
  native process groups, inspect its termination, and clean it up on every exit.
  Ending the engine client is not proof the worker stopped.

Reject an unsupported isolation setting or resource control instead of running
without it. A Docker daemon available on the host is not an isolation acceptance
result. Container inputs are trusted release artifacts; an untrusted authored
document never becomes a build input or arbitrary process command.

The ExifTool E5 work concerns TIFF, DNG, PNG, WebP and HEIF **file containers**.
Its protected-byte proofs, native lifecycle tests and metadata refusal cases do
not provide OCI/container isolation or image build machinery.

## Native qualification and measurements

Run every declared family's qualification cases inside its exact image, then
verify retained publications using the intended host/container path contract.
Retain input hashes, image digest, runtime and dependency identities, limits,
logs, receipts, native verification results and refusal cases. Run serially in a
proven bounded environment; [build-stage bounds](../containers/README.md) are
separate from worker-execution bounds.

| Family | Broader application scope beyond the fixed cases | Resource class | Coverage |
| --- | --- | --- | --- |
| ExifTool | Existing inspection, workbench, write, time/location, transfer and E5 container/public-loop qualifiers; retain named format refusals. | Not established | Further qualification required |
| SymPy | `tools/qualify_sympy.py`; exact intervals, multiplicities, independent certificates and lifecycle controls. | Not established | Further qualification required |
| NumPy | `tools/qualify_numpy.py`; exact NumPy/OpenBLAS build identity, independent PCA checks and lifecycle controls. | Not established | Further qualification required |
| FFmpeg | Existing video/audio, review, deliverable, frame-cache and audio-publish qualifiers for the declared image scope; independent decoded-output checks. | Not established | Further qualification required |
| ParaView | Existing catalogue/writer qualification and synthetic serial rendering proof; camera, colour, time and output data checks. No MPI claim. | Not established | Further qualification required |

The expected spread is lightweight metadata/symbolic work, numerical computation,
media processing and rendering. These are planning hypotheses, not measured weight
classes. Record CPU seconds, wall time, peak memory, image size and per-run disk
use; include errors, recovery and limits. Assign classes and calculate unit costs
only from retained inside-image results. Native process success alone never
promotes a run to verified. The observations below describe individual cases; no price has been assigned.

### Historical fixed image cases

These use source commit `5cfe1b0b698c37cc7203b7afb2c18af80c3e7d5e`, wheel
SHA-256 `a491fcd1f4327ceb35b68daa1bed3e4a4373cd6162dfda7db0bdfbdd244a47f0`,
and installed core Python/JSON package digest
`d5421fafedc100e0c8318341472f5c6fb51e6c74df446bca75f86753995370f8`.
Image digests identify locally retained OCI artifacts, not published registry
releases. Each passing case used an immutable fixture, ordinary core execution,
fresh isolated verification and host publication digest checks. ExifTool planning
also ran inside the image; SymPy used the admitted file-free host planner. These
cases do not admit hosted file uploads or qualify all upstream routes.

| Family | Image manifest SHA-256 | Observed case/result |
| --- | --- | --- |
| SymPy | `b161000aba10a7a06a3f6098b9342a7a4f76ae5c704e92b0bb208f577a326d74` | Exact square roots of two; run/fresh verification passed. Changed-publication verification refused. |
| ExifTool | `9e6a531d6b9110914ae9bad6c590fb72e672b26729d30f26a6b2f9bd8ab83c0e` | Title/description/creator edits on a generated 7×5 PNG; readback, preservation and fresh native replay passed; four publications validated. |
| NumPy | `ac9fabeb08a315f68a535335cd40b54e68e6789fd5d6912f6ac32bcf9820c08d` | Refused: the official wheel's mapped BLAS identity did not meet the adaptor's exact OpenBLAS 0.3.34 contract. The later source rebuild passed the final matched case below. |
| FFmpeg | Not built in this round | Original public-prefix build required a compatible toolchain; the later final matched case below passed. |
| ParaView | Not built in this round | The later final matched headless sphere/render case below passed. |

Passing cases used 512 MiB memory, zero swap, one CPU, 64 PIDs and a 32 MiB /
4,096-inode tmpfs, with no network and a read-only root. Each run and verifier
reported zero remaining native processes and actual container exit/removal.
Times below are single observations, not statistical performance estimates.

| Case | Run wall / CPU seconds | Run peak memory bytes | Fresh verify wall / CPU seconds | Verify peak memory bytes |
| --- | --- | --- | --- | --- |
| SymPy exact roots | 4.1964 / 4.011303 | 91,885,568 | 0.6997 / 0.497285 | 36,233,216 |
| ExifTool PNG metadata | 4.6482 / 3.918298 | 85,344,256 | 2.2370 / 1.730972 | 80,244,736 |

Wall time is measured by the supervisor. CPU and peak memory are observed cgroup
samples through native quiescence before export; they exclude export/teardown.
SymPy additionally passed actual byte/inode exhaustion, PID exhaustion, CPU
throttling, deliberate memory OOM, no-network/read-only-root checks, owner-SIGKILL
watchdog/recovery and controlled delayed-create reconciliation cases. These
containment observations are separate from full application coverage and must be
repeated where a new image or platform changes the relevant assumptions.

### Matched contained-planning observations

The current round uses source commit
`28f4360ac3c2525797189520e7693257acf79bfe`, wheel SHA-256
`2e6ac7788d877680d85d277562fabe172a9a885eaa8ee03c28da1b679a3d053d`, and
installed Python/JSON package digest
`5980f01a7ce7dbd4534863418d698ac03f8c70a6bbf0e049dbf2aebe32f58487`.
The earlier `c840081` round remains historical evidence.
Historical image evidence was not transferred to this source.

| Family | Image manifest SHA-256 | Observed capability and case |
| --- | --- | --- |
| SymPy | `491ed7fda0b6f8b924601c8f5657fad9effbd03b72bae98ce2531b74e7dd0e3c` | `isolated-planning-v1`: exact roots, contained capture and stale-plan check, native execution and fresh verification. |
| ExifTool | `54fb4a853963d40d408a17707531f72fa5d3388d7b2692668d2fa107385b8211` | `captured-input-planning-v1`: generated PNG metadata edit, contained capture/stale check/run/fresh verification, exact individual read-only input mount and unchanged input device/inode/size/mode/hash. |
| NumPy | `fe1df97c414cf9f44548949a5ba442cf78308cabbc868a521132dd8091f92db4` | Captured eight-row, two-channel PCA with independent numerical checks and exact NumPy/OpenBLAS identity. |
| FFmpeg | `a6ff10e4c24d38bcb5d4669358d7537b4c25f386dd4c2f2970e43f1cce494515` | Captured one-second PCM audio encoded at 96 kbit/s; independent decoded-output error/size checks. |
| ParaView | `ff9d6bf57f66430b28ee56d0b52b1e41d10953894d95f8022308ad4dcc395013` | One exact canonical synthetic sphere/render document under an operator qualification-only policy; no hosted workflow admission. |

All five exact images separately passed actual memory/no-swap, byte/inode
exhaustion, CPU/PID, offline/read-only-root, owner-SIGKILL/watchdog,
exact-container recovery and delayed-create refusal/reconciliation probes. All
refused deliberate publication corruption during fresh verification. Native
fragments cover their named case and policy; exact-root host storage and
controller capacity need separate observations before production admission.
There is no built-in qualified profile.

Every observed case fits the same `bounded-512m-1cpu` envelope: 512 MiB memory,
zero swap, one CPU and 64 PIDs. The four smaller cases used a 32 MiB /
4,096-inode job tmpfs and 60-second operation ceiling. ParaView used 64 MiB /
8,192 inodes and 90 seconds. These are supported tested bounds, not measured
minimums or distinct commercial weight classes. Watchdog fault injection used
shorter deadlines: two seconds for SymPy/ExifTool, a 0.5-second run stage for
NumPy/FFmpeg, and six seconds for ParaView after observing its actual native child.

| Case | Image inspect size / OCI archive bytes | Run wall / CPU seconds | Run memory HWM bytes | Maximum sampled run tmpfs bytes / inodes |
| --- | --- | --- | --- | --- |
| SymPy exact roots | 332,030,886 / 59,512,832 | 4.603538 / 4.185421 | 101,445,632 | 86,016 / 36 |
| ExifTool PNG metadata | 319,427,862 / 58,935,296 | 4.946836 / 4.149743 | 96,329,728 | 516,096 / 106 |
| NumPy PCA | 357,622,290 / 68,421,632 | 1.966852 / 1.466978 | 67,289,088 | 126,976 / 41 |
| FFmpeg audio | 313,729,694 / 59,439,104 | 3.241623 / 1.973661 | 58,503,168 | 413,696 / 107 |
| ParaView sphere/render | 2,847,643,302 / 658,758,656 | 10.225514 / 7.178376 | 295,477,248 | 17,092,608 / 44 |

The whole observers completed six operations each, including extra verification
and deliberate corruption refusal, in 11.042489, 16.046043, 9.030054, 12.045667
and 25.049898 seconds respectively. These are not normal single-job latencies.
CPU and memory high-water marks stop at native quiescence before export. A fixed
100 ms statvfs observer supplies lower-bound disk peaks; its overhead is included.
Complete native export/teardown CPU, final memory peaks and lifetime tmpfs peaks
remain unobserved. Image inspect sizes and OCI archive transport bytes have
different scopes. These are single local observations, not cloud capacity estimates.

ParaView's independent bounded publication checks found 530 unit-radius vertices
(within 1e-6), 1,056 triangles, exactly two incident triangles per edge and Euler
characteristic two. The 64×64 PNG passed CRC, bounded decompression and nonflat
raster checks; the ordinary core also reopened the geometry and freshly verified
its retained publications. The policy admits only the exact canonical JSON
fixture. It does not widen hosted file or workflow admission, establish MPI
coverage or clear the mixed-licence redistribution gate.

The first ParaView native round failed on `libglapi.so.0`. An offline loader
closure check identified only that missing SONAME; the official bundle already
contained it under `lib/mesa`. The corrected bundle exposes it through the
[recorded relative symlink](../containers/paraview/README.md). Failed build/export
rounds and a pre-request crash-injection failure remain separate retained
records. The successful ParaView assembly used an observed 1 GiB controller plus
3 GiB BuildKit limit, both zero-swap; the native worker remained at 512 MiB.
Assembly limits are separate from the measured application envelope.

## Executor implementation and remaining acceptance

`ExecutionService(..., executor=None)` retains the existing local executor by
default. Opt-in `ContainerExecutor` accepts a trusted `ImageResolver` and pure
file-admission object. There is no built-in qualified profile: missing admission,
image qualification or provider/route coverage fails with `ISOLATION_UNAVAILABLE`.
External resource bindings remain refused. Admission runs before any adaptor planning
hook and before dispatch; it cannot be replaced by a native planning hook.

The isolated layout is `runs/<job>/run`; the unique parent is a Docker-managed
tmpfs at the same absolute spelling as the host job parent. It has explicit byte
and inode bounds, counts against container memory, and uses zero memory swap.
No host directory is bind-mounted. The captured-input capability permits only
individually validated immutable files mounted read-only at identical paths.
Request documents and
retained evidence for fresh verification travel through a bounded binary stdin
protocol. The worker checks the actual cgroup and tmpfs bounds before native work.

The ordinary core executes and verifies in the pinned worker. Publication
metadata collection also runs there, because its checks may grow native readers.
The service separately invokes the verifier in a fresh container before committing
success; an execution response's `verified` field alone cannot skip it. The host
performs only regular-file containment and byte-digest checks on exported
publications. Reverification imports the retained bounded archive and refuses
any changed file inventory. The archive includes the run and only the immutable
schema objects named by its retained schema manifests. References may identify the
same owned job parent or a directory inside the run; references outside that job
are refused. Schema objects share the archive's byte/inode bounds and must match
their digest filenames. Shared indexes, unrelated parent files and scratch are
excluded. Captured documents and receipts are never rewritten.

Docker documents that `docker cp` cannot copy tmpfs contents; therefore pausing a
worker followed by `docker cp` is not the export mechanism. The fixed PID-1
supervisor owns an exporter child. That child kills native namespace processes
with bounded retries while the supervisor reaps orphans, requires an
empty remaining-process list, then exports its regular-file-only evidence archive
through stdout while the tmpfs exists. Native stdout/stderr are redirected to a
bounded-volume log. The host bounds stdout and archive members/bytes, validates
the complete archive before extraction, rejects symlinks/hardlinks/special files,
and requires actual container exit and confirmed removal before accepting it.
[Docker copy limitations](https://docs.docker.com/reference/cli/docker/container/cp/#corner-cases),
[tmpfs persistence and limits](https://docs.docker.com/engine/storage/tmpfs/).

These protocol records are **not authenticated attestation**. A compromised
same-UID application or worker remains a threat requiring separate image/security
review; the stream's claimed success or process count is insufficient by itself.
Trusted immutable images, fresh core verification and host digest/containment
checks are all required. Unknown cleanup is an explicit failure. Abrupt timeout
or cancellation kills/removes the actual container and preserves its structured
fault/cleanup evidence; unexported tmpfs artifacts are lost. Graceful interrupted
artifact export is not implemented.

Before engine creation, a durable checksum-bound ownership intent records the
job/plan, action, unique labelled name/nonce, image and total deadline. The exact
container ID is journalled after creation. An ambiguous create is reconciled by
its exact name and ownership labels. On service reopening under the exclusive
workspace lock, pending intents are killed/removed and marked reconciled before
new work is accepted. A corrupt journal or uncertain cleanup blocks recovery.
The journal is ordinary owned state, not authenticated third-party attestation.
If creation has no durable or observed container ID and its name is absent,
recovery remains unresolved: a daemon RPC could still create it later. An absent
name or finite quarantine is not proof against delayed creation. Recovery refuses
new work until the exact labelled container becomes observable and is removed, or
an operator establishes a separate daemon reconciliation barrier. No automatic
barrier or timeout-based clearance is implemented.

The cgroup CPU sample has the explicit boundary
`post-native-quiescence-pre-export`. It includes container startup, input staging
and application work through native quiescence, and excludes archive export and
container teardown. It is an observed application-workload sample, not final
container CPU accounting. A hosted meter must qualify this exact scope and check
quiescence, container exit and cleanup evidence before consuming the sample.

The PID-1 supervisor never executes planner or application code. It enforces a
startup input deadline and then an absolute monotonic total deadline, killing its
worker/native children and exiting on timeout even if the controller disappeared
or the exporter is stuck in native code. This avoids relying on a child process
to force-kill namespace init. Total-deadline exit is a distinct limit failure.

Trusted embeddings can use `verify_with_control(job_id, cancellation=..., deadline=...)`
and `jobs_for_plan(plan_id)` for cancellation/deadline control and crash-before-ID
reconciliation. These helpers are not added to the agent tool catalogue; the
ordinary `verify(job_id)` tool signature is unchanged. `isolation_recovery` holds
the constructor's completed reconciliation records for a trusted embedding.

The implementation's 25 host-double tests and 23 existing execution-service tests
passed under a 4 GiB, zero-swap wrapper. They exercise forged stream refusal,
archive escape/type/byte bounds, weaker-limit refusal, cancellation/cleanup and
injected service run/reverification without host native or metadata hooks, durable
ambiguous-launch recovery, independent watchdog decisions and admission before
workflow-design planning and exact schema-dependency closure. The separate
inside-image observations above supply the stated native evidence. Broader
application routes and platforms still require their own acceptance; host doubles
cannot supply native evidence.

The optional FFmpeg [runtime rebuild recipe](../containers/ffmpeg/build_runtime.py)
checks the retained release archive and every corresponding source file, and the
clean pinned x264 commit, before building the reviewed component subset. It uses
`/opt/runtime`, maps source/build paths in compiler output, installs through
`DESTDIR`, records toolchain and binary hashes, and refuses retained private paths.
It writes every configure/build/install transcript to both the selected log
directory and the required home transcript. Invoke it inside an independently
enforced memory/no-swap/deadline envelope; `make -j2` alone is not that envelope.
The original workstation build required a compatible toolchain for the pinned
runtime base. A subsequent Debian GCC 14.2.0-19 build passed all six configure,
build and install stages and the final binary path audit on 29 October 2026
(Winnipeg). The build container had an observed 3 GiB memory cap, zero swap,
two CPUs and 128 PIDs; its controller had a separate 512 MiB cap. The container
exited successfully and its removal was confirmed. The resulting binary SHA256
values are `00207fe319d140901f5fcd2bf7ca614c6167e4194a3696785278683c387339ac`
for FFmpeg and `c9b22bf6d6901177cf7bf942c50d265f8b60eff3f38220a927018295300abd4c`
for FFprobe. These are build observations; the matched fixed audio image case is recorded
above, with no broader route or price claim.

Contained planning and captured-input mounts have the separately pinned native
observations above. Trusted `PlanningRequest` operations retain their
operation identity and capture/stale-check phase in isolation evidence. A profile
must explicitly qualify `isolated-planning-v1` or `captured-input-planning-v1`;
existing route coverage does not grant either capability. Captured-input mode
additionally requires a trusted `CapturePolicy`, pure closed-slot admission before
file validation, leased immutable file identities and individually inspected
read-only mounts at the same absolute path. The job tmpfs remains the only
writable application mount. Planning cannot export run evidence. Further images, routes and platforms require their own matched native evidence.

A focused set of 85 container, service, captured-input and admission tests passed
under a 1 GiB, zero-swap wrapper. Those tests use explicit host doubles and do not
run Docker. They include planning capability refusal, prevention of host planner
hooks, exact read-only mount validation and capture leases retained through
unknown cleanup until recovery proves container absence.
