# Isolated local MCP and immutable inputs

The strict profile exposes declared tools without a shell. Execution and fresh
verification require an explicitly configured isolated backend; without one they
return `ISOLATION_UNAVAILABLE`. Discovery and file-free host planning remain
available. The separate trusted-local profile is an operator choice and does not
make this containment promise.

```sh
schemaxis mcp --workspace /srv/local-session --isolation-config /srv/operator.json
```

The operator supplies this file at startup, outside tool arguments. Its complete
shape is below. Replace the example image digest, qualification identity and
input digest with the exact reviewed records for the installed image. This
example grants no default image permission and is not native qualification.

```json
{
  "version": 1,
  "profiles": [
    {
      "image": "example/numeric@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "providers": ["numpy"],
      "routes": ["schemaxis.numpy/1"],
      "qualification_id": "operator-reviewed-native-qualification",
      "capabilities": ["captured-input-planning-v1"],
      "limits": {
        "memory_bytes": 536870912,
        "cpus": 1,
        "pids": 64,
        "disk_bytes": 33554432,
        "inodes": 4096,
        "wall_seconds": 60
      }
    }
  ],
  "captures": {
    "root": "/srv/local-captures",
    "namespace": "local-inputs",
    "max_bytes": 16777216,
    "max_files": 32
  },
  "inputs": [
    {
      "id": "measurements",
      "source": "/srv/user-supplied/measurements.csv",
      "label": "User-supplied measurements",
      "sha256": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  ]
}
```

Provision the capture directory owned by the service user with mode `0700`.
Configuration must be owned and not group/world writable. Source inputs must be
bounded regular files without symlinks or hardlinks. Startup copies each newly
named input, checks its digest and makes the capture read-only. A retained ID
cannot silently change content. Reconcile an interrupted inventory publication
before restarting writes; unreferenced captured files still consume capacity.
The operator remains responsible for reviewing the image qualification record,
version and applicable redistribution rights. A configuration label is not proof.

After `create_task`, the agent calls `inputs_list(task_id)` to obtain opaque IDs,
labels, sizes, suffixes and digests. It authors those IDs into declared file
slots, such as a numeric operation's `source`. Generated admission validates the
complete document before resolving captures or invoking a planner. Planning,
stale checks, execution and fresh verification use the ordinary isolated backend
and exact retained bindings. Authored filesystem bindings are refused.

An explicit `input_from_resource(task_id, resource_id)` call re-verifies the
producer, checks the declared publication and copies its exact digest into a new
immutable capture. The returned opaque ID can feed a subsequent application
task. This is an explicitly requested artifact handoff, not automatic retrieval
or cross-task learning. Promotion consumes the same finite file/byte allowance;
it cannot turn a failed or changed artifact into an input.

This store has one local owner. Every task in that session can select its
operator-provided inputs. It does not implement hosted tenant separation.
Use the authenticated hosted service for multiple projects; the loopback HTTP
development binding does not load this stdio-only configuration.

Bounded observations and receipts may contain data. The interface restricts
direct access and execution; it does not claim to hide all content from a model.
Catalogue admission also does not establish native success for every input or
upstream application feature. Consult the generated operation coverage and
image-specific qualification limits.
