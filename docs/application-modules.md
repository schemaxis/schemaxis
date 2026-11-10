# Packaged applications and cache management

Managed CLI runs and Studio Case Runner default to container execution. Each
module contains its application, dependencies, Schemaxis adaptor and worker.
A workflow selects independent modules; it never builds an image for every app
combination. The ordinary scheduler owns dependencies, verified artifact/value
handoffs, immutable attempts and resume.

This local implementation targets Linux x86-64 with Docker Engine. Other hosts,
Docker Desktop VM backends, GPU rendering and interactive container GUIs require
separate qualification. Existing native consoles and live sessions remain usable.
The Python API retains native dispatch unless a trusted caller wraps execution
in `schemaxis.module_runtime.runtime(document)`. Hosted policies are unchanged.

## Installation and execution

Install the [Python package](installation.md) and configure Docker Engine
separately. Schemaxis does not install the engine or modify system applications.
There is no published module catalogue in this checkout. A publisher must build
and qualify an image and supply its reviewed manifest. Registration is a trusted
local administrator operation; workflows cannot select images or register code.

```sh
schemaxis modules register /path/to/reviewed-module.json
schemaxis modules list
schemaxis modules fetch blender freecad
schemaxis run workflow.json --output-directory results/new-run
schemaxis verify results/new-run
```

The example IDs must match registered manifests. Missing registered images are
fetched on workflow startup when downloads are enabled. Installed images are
reused; absent/unqualified modules refuse, without native fallback. Discovery and
planning do not provision apps. Registration does not install host adaptor plugins:
the matching adaptor discovery/planning package must already be installed.

Keep additional download archives for offline restoration:

```sh
schemaxis modules fetch blender --keep-download
schemaxis modules settings --offline
schemaxis modules fetch blender --offline
```

Offline mode restores verified saved archives but never pulls. Archives have
separate byte counts and SHA-256 receipts. Docker save/load can lose registry
digest metadata: installation receipts bind the original reference to the exact
local image content ID used for execution. Images plus archives cost extra disk.

Use existing native applications explicitly:

```sh
schemaxis configure blender /path/to/blender
schemaxis run workflow.json --backend native --output-directory results/native-run
schemaxis modules settings --backend native
# Restore the default and permit missing-module downloads:
schemaxis modules settings --backend container --allow-downloads
```

Native execution retains existing dependency/location checks. System apps are
neither copied into containers nor uninstalled. Interactive consoles and authoring
previews retain their native route; batch workers do not provide full desktop GUIs.
Explicit `--executable` or application executable flags also select native execution;
combining those overrides with `--backend container` refuses as conflicting choices.

## Cache inspection and cleanup

Studio **Application Setup** shows modules, runtime/download sizes, preferences,
registration, fetch/restore and cleanup review. Native application locations
remain below those controls. Equivalent CLI operations are:

```sh
schemaxis modules list
schemaxis modules cache plan --module blender --module freecad --save cleanup.json
schemaxis modules cache clear cleanup.json --confirm CONFIRMATION_FROM_PLAN
```

By default, cleanup removes only removable managed runtime references. Add
`--downloads` to the **plan** to select saved archives too. Plans bind exact
manifests, engine/image identities and archive hashes. Changed state requires a
fresh review. Cleanup always preserves registrations, installation receipts,
preferences, native configuration, projects, adopted inputs, retained captures,
results, and system applications. Pre-existing images are usable but never claimed
as owned merely because Schemaxis found them.

A shared execution lease prevents cache mutation during managed workflows.
Containers referencing selected images, including stopped containers, block
removal. Images shared by unselected installed modules are preserved. No system
prune, forced image removal, container stopping or recursive deletion of a
user-selected directory is performed. Other tags can retain layers. Image sizes
include shared layers; they are not a promise of reclaimed disk space.

Catalogue/preferences/receipts and archives live beneath
`$XDG_DATA_HOME/schemaxis/modules`, default `~/.local/share/schemaxis/modules`.
`SCHEMAXIS_MODULE_HOME` can select another private owned directory. Images live
in Docker's storage. Per-run `.schemaxis-module-inputs` directories hold execution
evidence alongside attempts; they are not disposable application cache. Removing
a runtime can require restoring it before verifying old results. Removing its
saved download too can require network access to retrieve the exact version.

## Publisher manifest

Every `schemaxis.app-module/1` manifest requires these fields:

| Field | Contract |
| --- | --- |
| `id`, `provider` | Bounded module ID and installed host adaptor ID; one registered module per route. |
| `applicationVersion`, `coreVersion` | Exact app/host versions. Workers independently repeat effective planning. |
| `image` | Immutable `repository@sha256:…` or local `sha256:…` content ID; mutable tags refuse. |
| `platform` | Currently `linux/amd64`. |
| `routes` | Supported document versions. |
| `qualification` | Reference to actual native acceptance evidence; pending placeholders refuse. Registration checks structure, not the truth of the claim. |
| `limits` | Complete `IsolationLimits`: `memory_bytes`, `cpus`, `pids`, `disk_bytes`, `inodes`, `wall_seconds`. Existing bounded worker limits apply. |
| `inputFiles` | List of JSON pointer patterns for every route; `*` expands arrays/objects. Empty means file-free. |

The image implements `schemaxis.container_worker`; use the
[worker build contract](../containers/README.md) and
[generic application definition](../containers/app/README.md).
Each file slot must become a literal saved individual file after handoff resolution.
Files are copied, hashed and mounted read-only. No host directory or engine socket
is exposed. Directory inputs and implicit sibling-file discovery are unsupported;
publishers must declare and qualify the complete supported input closure.

Outer attempts retain logical inputs/publications; `run/` retains exact worker
evidence. Fresh verification checks captures and publications in the matching
worker. Original source files may be absent after completion; captures must remain
intact. Native handles never cross workers. Packaging does not establish compatible
formats, units or scientific meaning; existing handoff contracts still apply.
