# Worker image definitions

All five definitions have local fixed-case observations against one exact core
and wheel, including contained planning and fresh verification. Broader route
acceptance and the stated distribution gates remain pending. No image is
published. See [the image contract, observations and licence decisions](../docs/images.md).
Runtime bundles and the Schemaxis wheel are separate digest-locked build inputs.

The five Dockerfiles share an official Python 3.14.4 Debian Trixie slim base,
pinned to its Linux/amd64 manifest rather than a mutable tag. Registry manifest
metadata was inspected on 29 October 2026 UTC (28 October in Winnipeg); this does not establish compatibility
or a security assessment of the base.

## Inputs

Use `containers/` as the build context. In its ignored `artifacts/` directory,
supply a pure-Python Schemaxis wheel as `schemaxis.whl` and a reviewed uncompressed
runtime tar as `<family>/runtime.tar`. The wheel must have been built from a
pinned source commit, including the required licence/notice files. Fill a private
copy of `inputs.template.json` with real SHA-256 values and the source commit;
nulls deliberately mean unavailable inputs. No public hash is invented for an
artifact that has not been prepared.

Each tar has only these top-level directories:

```text
runtime/
  bin/                  # application launchers, and Perl for ExifTool
  lib/                  # required native shared libraries
  LICENCES/             # application AND dependency notices/licence texts
  provenance.json       # reviewed source/build record
site-packages/          # optional packages for the pinned Python, not a venv
```

ParaView's complete relocated binary distribution occupies `runtime/` (its
`bin/pvpython`, libraries and resources stay together). ExifTool's Perl modules
must stay beside its script or in the bundled Perl's documented library search
path. FFmpeg requires sibling `bin/ffmpeg` and `bin/ffprobe`. SymPy and NumPy
packages go in `site-packages/`; their configured interpreter is the image's
`/usr/local/bin/python3`, never a copied virtual-environment symlink.

`provenance.json` must contain `family`, exact `version`, nonempty `sources` and
`build` records. Record source URLs and SHA-256/commit pins, build configuration,
compiler and dependency identities, base digest, relocation and licence/source
availability. This is reviewed supply-chain evidence; the assembler's structural
checks do not authenticate its truth or independently prove application identity.

Required runtime identities:

| Family | Application/build contract |
| --- | --- |
| `exiftool` | ExifTool 13.55; pinned Perl and required modules |
| `sympy` | SymPy 1.14.0, mpmath 1.3.0; Python 3.14.4 |
| `numpy` | NumPy 2.5.4, OpenBLAS 0.3.34, one BLAS thread; CPython 3.14.4 ABI |
| `ffmpeg` | FFmpeg 9.0.2 with explicit adaptor-required component list; x264 commit `b35605ace3ddf7c1a5d67a2eb553f034aef41d55` if using the GPL H.264 build |
| `paraview` | ParaView 5.13.3 Linux x86-64 distribution, with its bundled Python; serial qualification only |

Do not copy an arbitrary workstation runtime and mark it portable. Prepare
native packages against the pinned image ABI, or prove the complete official
binary bundle and required libraries compatible inside that exact image. NumPy
requires native building/relinking or a compatible pinned wheel plus the exact
OpenBLAS build; a generic NumPy wheel is not an equivalent runtime. ExifTool needs
a compatible Perl runtime bundle because the Python base does not promise Perl.
FFmpeg may reuse a reproducible retained build only after its libc/libm/zlib and
component compatibility are proved. ParaView similarly needs its native loader,
graphics and offscreen-rendering dependencies checked. Record these checks; host
qualification does not qualify any of these images.

Build arguments `RUNTIME_SHA256` and `WHEEL_SHA256` are mandatory; the assembler
refuses malformed hashes, mismatching artifacts, unsafe archive paths, missing
notices and mismatching family/version provenance. It does not download anything
or invoke native applications. The final image has package-manager executables,
pip and ensurepip removed. Trusted build inputs must not reintroduce managers;
audit the final filesystem before acceptance.

## Build resource plan: approval by evidence before a build

The host's bounded command wrapper alone does **not** constrain Docker daemon
workers. Do not execute a plain `docker build` and assume a wrapper's memory cap
applies to the build. Do not rely on BuildKit ignoring legacy `--memory` flags.

Before building, establish one dedicated builder with a verified cgroup enclosing
both its daemon and every build-stage process: a maximum of 4 GiB RAM,
`memory.swap.max=0`, bounded PIDs/CPU, a disk/inode quota and a wall deadline.
A Docker-container BuildKit driver with explicit memory/swap limits is a candidate,
not proof. Retain actual cgroup paths and limits from a bounded child-stage probe;
refuse building if stages escape that parent or zero-swap cannot be demonstrated.
The trusted supervisor must terminate the builder's container/process group on
timeout; killing only the Docker CLI is insufficient. Use one heavy job at a time.

Registry metadata identifies the Linux/amd64 manifest of
`moby/buildkit:buildx-stable-1` as
`sha256:98cc6a3fc46220d00f8224ae483f3274fc874e9be8d7dd1e2e2c5481209228b5`
(29 October 2026 UTC). This pins a possible dedicated builder, not its resource
qualification. Docker documents the `image`, `memory`, `memory-swap`, CPU and
restart-policy driver options; inspect their actual applied container limits
and probe a child build-stage cgroup before heavy work.
[Official docker-container driver options](https://docs.docker.com/build/builders/drivers/docker-container/).

The precise sequence after that gate is:

1. Record the pinned base manifest and transfer/pull it within a separately
   bounded, timed provisioning job. Provision application sources/runtimes once
   in the operator's persistent runtime area, not a session/source copy.
2. Prepare reviewed bundles with the identities above; retain their manifests,
   corresponding sources/licences and hashes. Build the core wheel once from a
   pinned commit. Populate `inputs.local.json` and check those exact hashes.
3. Use the proven builder, `--platform linux/amd64`, `--network none`, the relevant
   `<family>/Dockerfile`, and the two SHA-256 build arguments. Capture logs,
   resulting image ID/digest and full input manifest. No floating base override
   is offered by these definitions. Build stages only assemble trusted artifacts.
4. Destroy the dedicated builder after the bounded build sequence. Qualify images
   one at a time under the separate execution contract in `docs/images.md`.

All five local image rounds retained actual image/bundle pins and bounded
BuildKit child-stage memory/no-swap observations. These operator records do not
create a generally qualified builder or profile in this repository. Re-establish
the resource gate and exact runtime acceptance for each new image or platform.
