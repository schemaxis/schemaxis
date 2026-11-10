# MCP tools

Run `schemaxis mcp --workspace DIRECTORY` in an installed Python 3.10+ environment.
The server has no required MCP SDK dependency. The existing `schemaxis agent`
JSON-lines interface remains available; MCP delegates to its shared catalogue and
execution service. See [the lifecycle](agent-service.md) and
[the implementation contract](design/mcp.md).

Stdio supports modern MCP `2026-07-28` and legacy `2025-11-25`. The modern profile
uses per-request version/client-capability metadata; the legacy profile uses
`initialize` followed by `notifications/initialized`. Choose one era per process.
Modern request metadata requires protocol version and client capabilities;
`clientInfo` is optional and, when supplied, includes string `name` and `version`.
It is self-reported display metadata and grants no authority. See the
[protocol metadata contract](https://modelcontextprotocol.io/specification/2026-07-28/basic/index#meta).
Only MCP JSON appears on stdout. Keep stdin open while executing/polling/cancelling;
EOF cancels owned active work and closes the service.

The default `declared-documents` profile reads generated admission contracts
from the adaptor catalogue before any planner hook. The current records cover
all declared SymPy (1), NumPy (1), FFmpeg (6) and ExifTool (16) operation families,
and 108 ParaView operations with scoped historical native evidence. ParaView's
537 other declarations remain unqualified for this profile. Discovering an
operation does not establish admission or an available worker image;
`FileAdmission.coverage()` reports exact identities and limitations. See the
[adaptor-owned contract](mcp-admission.md).

A bounded `schemaxis.workflow/1` wrapper may compose up to 32 admitted operations.
Literal file-backed children retain exact capture-pointer prefixes. Scalar
workflow metadata references remain supported for file-free children; execution
overrides and arbitrary artifact references are refused. Materialisation stops
at 32,768 visited values, 1 MiB of compact UTF-8 JSON tokens or 64 output nesting
levels before planner hooks. Keys, escaping, punctuation, reference syntax and
every expanded occurrence count, including unused metadata. Repeated references
cannot evade the limits; exhaustion returns `MCP_POLICY_DENIED`.

Strict native execution and fresh verification require explicit qualified images
through `--isolation-config`, described in [local isolation](mcp-isolation.md).
Without that operator configuration the default server can discover capabilities
and plan admitted file-free declarations, but native execution refuses with
`ISOLATION_UNAVAILABLE`. Admission is a pure input contract; the configured
executor supplies the operating-system isolation.

All inherited methods have MCP equivalents, including authoring, inspection and
basic schedule controls. Capability names replace dots with underscores:
`capabilities.search` becomes `capabilities_search`. `methods` returns the shared
service method/default catalogue. The strict profile refuses file-based template,
draft and inspection entry points, and authoring/scheduling methods, explicitly
with `MCP_POLICY_DENIED`. `--profile trusted-local` is an operator opt-in to the
existing local filesystem contract; do not use it for untrusted remote callers.

`run_tool` accepts an exact archive digest already imported into the workspace's
local package store. It binds declared values into an ordinary plan and defaults
to `execute: false`; `execute: true` uses the same task authorisation and budgets.
No package URL is fetched. Do not interpret the presence of a listed tool as
qualification of its runtime.

## Trusted captured-input admission

The pure embedding API `FileAdmission.check(document, context=None, *, bound=False)`
uses the same generated canonical schemas and adaptor-owned file slots for local
and hosted clients. JSON requests cannot supply trusted
`execution_inputs.InputBindings` objects. In a configured local session,
`inputs_list(task_id)` exposes opaque IDs for operator-provided immutable files;
plans use those IDs in declared slots. No input bytes or source paths are exposed
by that listing. `input_from_resource(task_id, resource_id)` freshly verifies a declared
producer output and copies it into a new immutable input without returning its
bytes. Each consumer executes in its own fresh worker container.

| Application | Admitted operation families | File contract |
| --- | --- | --- |
| SymPy | 1 of 1 | Exact rational literal data; no input files |
| NumPy | 1 of 1 | One immutable numeric CSV |
| ExifTool | 16 of 16 | Explicit media items, declared sidecars, copy source files, GPX tracks and name plans |
| FFmpeg | 6 of 6 | Declared PNG frames/sheets, timing JSON, video, audio and captions |
| ParaView | 108 of 645 declarations | Qualified generators, filters, resources and writers; captured PNG and closed ASCII VTK XML slots; managed GenericIO readback |

These are operation-family counts, not claims that every variant, dataset or
upstream option combination has been qualified. ExifTool folder scanning and
saved E3 time/location plans remain refused because their indirect input closure
is not yet represented by immutable file captures. Inline intent and explicit
items cover all 16 families. ParaView's failed writers, unqualified generated
operations, unresolved external readers and auxiliary OBJ texture-reference option
remain refused. The literal ParaView graph profile also refuses axes, definitions,
dimensions, views and settings metadata sections; their expansion is not admitted
by the current file-closure contract. Native verification still decides whether actual bytes meet the
adaptor's scientific or media contract.

`FileAdmission.input_slots(document)` supplies frozen `InputSlot(pointer,
suffixes, max_bytes)` records after checking the entire canonical schema,
operation qualification, source pins and opaque IDs, without reading input files
or importing planner hooks. Optional and wildcard slots expand from the literal
document; suffixes and byte limits come from the adaptor's records. An embedding
must resolve IDs in its owned task and then perform full admission with their
actual descriptors; it must not maintain another application classifier.

Immutable `CapturedInput` descriptors carry an opaque identity, stable absolute
path, SHA-256, byte length, device and inode. `InputBindings` supplies its owned
namespace and canonical JSON pointers. Before binding, each leaf must equal its
opaque capture ID. After trusted `bind_document`, `bound=True` requires that
capture's exact stable path. Missing, additional, duplicate, overlapping or unused
bindings refuse. `FileAdmission.operations(document)` reports validated declared
selection identities for qualification tools; it does not certify execution.

The executor separately uses `CapturePolicy` to prove ownership, immutable
regular-file identity and digest under a retained lease. It admits before binding
or planner hooks, repeats bound admission for isolated planning, execution and
verification, and mounts only each admitted immutable file read-only. These
records do not qualify a new executor, image, application release or hosted
deployment. A host planner must never open bound paths before isolation.
`--profile trusted-local` retains a separate operator-owned filesystem contract.

## Client launch configuration

Replace `/opt/schemaxis/bin/schemaxis` with the absolute installed executable and
`/path/to/session` with a private writable workspace. Give separate service owners
separate workspace directories; the service enforces an exclusive workspace lock.
These are discovery/planning configuration recipes, not evidence of testing each
named host. Append `--isolation-config /path/to/operator.json` to the command or
argument list for strict native execution; the configuration is operator-owned
and contains immutable image pins and capture policy, never agent-authored paths.

For Claude Code:

```sh
claude mcp add schemaxis -- /opt/schemaxis/bin/schemaxis mcp --workspace /path/to/session
```

The MCP project's [host connection guide](https://py.sdk.modelcontextprotocol.io/get-started/real-host/)
documents the CLI launch registration and Claude Desktop configuration form.
For Claude Desktop, merge this server entry into `claude_desktop_config.json`,
then fully restart the host:

```json
{
  "mcpServers": {
    "schemaxis": {
      "command": "/opt/schemaxis/bin/schemaxis",
      "args": ["mcp", "--workspace", "/path/to/session"]
    }
  }
}
```

For Cursor, put the same entry in `.cursor/mcp.json`, adding `"type": "stdio"`
inside the server entry, following [Cursor's MCP configuration](https://cursor.com/docs/mcp).
Generic clients launch the same executable/arguments and use `tools/list`,
`tools/call` and `resources/read` under their supported wire profile.

The [installed-client qualification](../verification/2026-10-29-mcp-clients.md)
passed with MCP Python SDK 2.3.0 in modern and legacy modes, OpenAI Agents SDK
0.24.0 for direct MCP list/call operations, and Claude Agent SDK 0.2.174 for
connection/status and tool discovery. The first two clients also created and
observed real host plans and checked strict input refusal. Claude's check did
not enter its model loop or call a tool. A separate model-free follow-up through
both MCP modes and the OpenAI wrapper executed real local SymPy jobs, requested
fresh verification and captured all three publications. Those historical checks established the former local
host-native lifecycle. The current strict profile requires configured containers;
the earlier receipts do not qualify that new source or isolation configuration.
Neither check qualifies the Desktop/Cursor recipes above, autonomous model use
or the HTTP binding with an external client.

`tools/qualify_mcp_clients.py` repeats this check in an optional environment
containing the selected SDKs. It keeps temporary service workspaces separate from
the output directory and removes them after each run. The retained `clients.json`
contains request/response evidence, SDK versions and the source commit. Use a
private output directory because transcripts can contain local paths. `--native`
additionally requests execution and fresh verification; it is opt-in and requires
`--isolation-config` with separately qualified immutable worker images. Native
application configuration alone does not authorise the strict executor. Captured responses remain historical evidence
after temporary workspaces are removed.

## Results, resources and control

A tool returns `structuredContent` with `ok` and an exact `result` or structured
`fault`. The same carrier appears as JSON text for older clients. Always inspect
`isError` and the core verification state. A returned plan/job ID does not establish
objective satisfaction. Task budgets and expected-revision checks are unchanged.

Large service results return `resultResource` with URI, size, digest and expiry.
Read it progressively through `resources/read`; member pointers recover complete
JSON. Oversized strings have explicit encoded-token byte-range resources. Never
retry a mutation to retrieve its result. The response store is bounded to 64 MiB,
with 16 MiB per result and 24-hour expiry. Cancellation and compact status replies
remain available when that quota is full. Ordinary retained job evidence keeps
the existing workspace lifetime.

`schemaxis://workspace/...` URIs identify only owned observations, captured
receipts, digest-checked publications and retained response pages. Reads are
bounded, reject foreign namespaces and never dereference arbitrary file/HTTP
paths. Receipt observations are captured evidence; `verify(job_id)` performs a
fresh check and can invalidate success. Treat artifact text as untrusted data.

## HTTP embedding and local development

`schemaxis.mcp_http.McpHttpBinding` accepts an `HttpRequest` and a trusted
`RequestContext` supplied by an embedding host. It supports modern Streamable
HTTP POST with JSON responses, standard header/body validation and exact Origin
allow-lists. GET/DELETE return 405; no protocol session ID is minted. Hosting owns
authentication, namespace routing, TLS and execution-owner lifetime. A disconnect
does not close the durable owner or automatically cancel a returned job.

The optional loopback development host binds only `127.0.0.1`:

```sh
# Supply SCHEMAXIS_MCP_TOKEN privately: at least 32 printable ASCII characters.
schemaxis mcp --workspace /path/to/session --transport streamable-http --port 8766
```

Clients supply `Authorization: Bearer ...`, the modern request metadata, the
matching `MCP-Protocol-Version` and `Mcp-Method` headers, and `Mcp-Name` when
calling a tool or reading a resource. A present Origin must match an explicitly
configured `--allow-origin`. This development host is not an OAuth provider or a
production hosting recipe. Legacy HTTP, SSE subscriptions, MCP Tasks, sampling
and elicitation are not advertised.

Host doubles cover method parity, protocol profiles, strict admission, HTTP
validation, bounded resources and quota-independent cancellation. They establish
neither actual native/container qualification nor named-host interoperability;
the installed SDK checks above are separate evidence.
The initial selected host regression batch passed 90 checks across MCP/packages,
execution service, CLI/discovery, basic scheduling and capability navigation.

## Local declared packages

The core's `tool_packages` module and [manifest schema](../src/schemaxis/tool-package.schema.json)
define one format for local CLI/MCP consumers and future sharing/view hosts.
`tool.json` (`schemaxis.tool/1`) references the existing
`schemaxis.workflow-template/1` and workflow. It includes identity/revision,
display text, SPDX licence, tags, declarative display hints, execution tier,
derived requirements and provenance. `package.json`
(`schemaxis.tool-package/1`) inventories every payload file by path, size and
SHA-256. The archive digest additionally binds the inventory itself.

Prepare a local data directory containing `tool.json`, its template and workflow,
then pack/import it with output outside that source directory:

```sh
schemaxis tool pack /path/to/tool-source --output /path/to/tool.schemaxis-tool
schemaxis tool check /path/to/tool.schemaxis-tool
schemaxis tool import /path/to/tool.schemaxis-tool --workspace /path/to/session
```

Packing derives requirements and provenance; it never edits source files.
Import returns the immutable `sha256:...` digest for `run_tool`. Its arguments are
`task_id`, `package_digest`, a parameter-value object `values`, `expected_revision`
and optional `execute`. The result includes binding/package provenance and the
ordinary plan, plus a job when requested. A dispatch refusal after successful
capture reports the plan ID/revision; capture is not rolled back.

The first runner supports local-tier, self-contained workflows admitted by the
file-free policy, with existing scalar/vector template parameters and defaults
for every required parameter. It refuses uploaded files, runtime asset
dependencies and unsupported execution tiers. Requirement version ranges remain
`unknown` where no common version-range declaration exists; the native adaptor
still enforces its actual runtime version. This is not a parallel sharing-service
format, a general browser evaluator or an executable plugin package.

Only JSON, text/CSV and display image members are accepted. Archives reject
executable/special/symlink members, traversal, duplicates, normalized case
collisions and inventory/digest mismatches. Limits are 16 MiB compressed, 64 MiB
decompressed total, 8 MiB per member, 256 files and 64 JSON nesting levels. Package
contents are never extracted as executable code. Immutable captured documents
contain all runtime input for this slice; display/example assets are not native
dependencies. Archive identity is rechecked before package dispatch, while the
normal verifier checks the exact retained execution document and publications.
