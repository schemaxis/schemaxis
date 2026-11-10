# MCP implementation contract

Design checkpoint: 28 October 2026, against core `f46412e`. This document is a
proposed contract, not evidence of a shipped MCP server, package runner or hard
isolation. The existing `schemaxis.agent/1` JSON-lines transport remains available.
Its 55 declared methods and special `methods` request are the parity baseline.

## Scope and dependency decision

Add `schemaxis mcp --workspace DIRECTORY`, using stdio by default. MCP is a
transport over `ExecutionService`, the capability catalogue, shared authoring and
inspection stores, and the existing scheduler. It must not acquire another graph
language, application registry, planner, executor or success classifier. Existing
documents, task budgets, provider authorisation, revisions, bindings and faults
remain authoritative. A completed process is insufficient evidence of success.

The default admission profile is `declared-documents`: only owned declared inputs
and service-managed state are accessible. `--profile trusted-local` is an explicit
operator choice for the existing caller-local file/authoring contract. Profiles
come from trusted launch configuration, never tool arguments. Neither profile
claims hard isolation unless a qualified container executor is selected.

Implement the bounded protocol surface with Python 3.10+ standard-library modules.
No required dependency or `mcp` extra is proposed for this slice. This is feasible
because the server needs JSON-RPC dispatch, bounded JSON serialization, stdio and a
JSON-response HTTP binding, and does not request client sampling, elicitation or
roots. Do not implement an OAuth provider or production HTTP server in the core.
If interoperability exposes a necessary dependency, revise this decision with its
exact version, supported protocol revisions and measured benefit before adding it.

Task records and owned receipts remain ordinary local state. The transport adds
no cross-task learning, retrieval service, account database, billing or fleet.
Core must remain usable without any hosted product.

## Versioned protocol boundary

Official sources checked on the checkpoint date identify `2026-07-28` as the
modern revision, with per-request version/capability metadata, and `2025-11-25`
as a legacy revision with initialization. These are different wire profiles;
do not mix their envelopes or infer a profile from an HTTP session ID.
[MCP versioning](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)

| Binding | Required implementation profile | Lifecycle |
| --- | --- | --- |
| stdio | `2026-07-28` and `2025-11-25` | Modern requests are self-contained; legacy clients initialize first. |
| Streamable HTTP | `2026-07-28` | POST requests with explicit metadata; no protocol session. |
| Earlier revisions, legacy HTTP+SSE | Unsupported | Return a version/method diagnostic; no silent compatibility claim. |

Modern requests require
`params._meta["io.modelcontextprotocol/protocolVersion"]` and
`params._meta["io.modelcontextprotocol/clientCapabilities"]`.
`clientInfo` is optional. Missing required metadata is `-32602`; unsupported
versions are `-32022` with `data.supported` and `data.requested`. Include
`io.modelcontextprotocol/serverInfo` in result metadata. Identity metadata is
self-reported, never authorisation.
[MCP base protocol](https://modelcontextprotocol.io/specification/2026-07-28/basic)

Implement modern `server/discover` with implementation identity, supported
versions and capabilities, using the dated schema. Advertise `tools: {}` and
`resources: {}`; omit subscription, list-change and optional extension claims.
Implement `tools/list`, `tools/call`, `resources/list`,
`resources/templates/list` and `resources/read`. The server produces only complete
modern results (`resultType: "complete"`), never multi-round-trip input requests.
Return the specified method/capability error for unsupported optional requests.
[Server discovery](https://modelcontextprotocol.io/specification/2026-07-28/server/discover)

Modern discovery, list and resource-read complete results include the required
`cacheScope` and `ttlMs` fields. Initially use `private` and `0` consistently,
including every page, so authorisation-dependent data is never marked public.
[Caching](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching)

For legacy stdio, implement `initialize`, `notifications/initialized` and `ping`
with `protocolVersion: "2025-11-25"`, server identity and the same declared
capabilities. Before initialization, reject ordinary legacy requests. Omit modern
`resultType` and per-request metadata requirements on this profile. Do not
advertise experimental MCP Tasks: Schemaxis task/job handles are tool data.
Freeze the chosen era for a stdio process after its first valid discovery or
initialization request; reject cross-era traffic explicitly.
[Legacy lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)

Stdio is UTF-8 newline-delimited JSON-RPC; stdout contains protocol messages only
and diagnostics go to stderr. Closing stdin closes this local service owner,
requests cancellation and waits for native ownership to finish, matching the
existing transport. It is not a detached execution interface.
[Stdio binding](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)

### Streamable HTTP integration

The core supplies `McpHttpBinding.handle(request, context) -> HttpResponse` for an
embedding server, plus a loopback-only development adapter. Both use the same
`McpDispatcher`; network code never constructs a service from caller-supplied
workspace paths. An embedding host supplies the authenticated context and owns
TLS, credentials, rate limits and the lifetime of execution owners.

The modern endpoint accepts POST, returns `application/json`, and returns 405 for
GET and DELETE. Require the standard `Accept`, `MCP-Protocol-Version`,
`Mcp-Method` and applicable `Mcp-Name` headers, checking decoded values against the
body. Header mismatches use HTTP 400 / `-32020`; unsupported versions use 400 /
`-32022`; unknown RPC methods use 404 / `-32601`. Validate any present Origin
against a configured exact allow-list (invalid: 403). Do not mint or echo
`Mcp-Session-Id`, support SSE resumption, or advertise subscriptions. A JSON
response is a permitted Streamable HTTP implementation.
[Streamable HTTP binding](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)

`RequestContext` is trusted constructor data: principal/namespace identity,
service-owner reference, method/path/provider policy, and transport disconnect
token. It is never derived from tool arguments, client labels, resource URIs or
MCP metadata. Recheck object ownership on every call and resource read. HTTP
disconnection must not close the namespace's durable service owner. A returned
job remains controllable by its ID; `cancel(job_id)` is explicit job cancellation.
Request cancellation cannot undo an already committed state transition. Implement
stdio request cancellation separately from job cancellation; never interpret an
arbitrary RPC ID as a job ID.

Protected public MCP HTTP endpoints need an authorisation integration that follows
the dated MCP OAuth resource-server contract, including protected-resource
metadata and token audience validation. API keys for a separate hosted REST API
are not by themselves a claim of generic MCP OAuth interoperability. The core's
loopback development endpoint must say it is a trusted local endpoint and require
an explicitly configured credential before accepting mutations.
[MCP authorisation](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)

## Shared tool catalogue and complete transport parity

Introduce `schemaxis.service_contracts.ToolCatalogue` as the shared declarative
catalogue of service actions. Each `ToolSpec` contains `method`, `mcp_name`,
`summary`, `input_schema`, `effect`, `path_policy`, `contract_sources` and a
registered callable target. Generate agent `METHODS`/`methods` metadata and MCP
tool definitions from these same entries. Never expose arbitrary attributes with
`getattr` on user text or create a second list of handwritten MCP descriptions.
Startup compares catalogue entries with the old explicit allow-list during the
migration; any missing entry, name collision or signature mismatch is fatal.

The application `CapabilityCatalogue` remains the authority for application
names, operation purposes, schemas, requirements, examples and provenance.
`ToolCatalogue` descriptions compose the service action summary with stable
links to these catalogue contracts. Search/describe results return those exact
projections. Do not paste application inventories into each tool description,
invent availability from manifests, or make every native operation a direct
execution tool. A task still captures ordinary declared documents through `plan`.

The current framework actions are absent from `CapabilityCatalogue`: treating
their Python signatures as complete JSON Schemas would be incorrect. Their new
declarations supply parameter types and descriptions once for every frontend;
operation-specific prose continues to come from adaptor declarations/guidance.
Hash service declarations together with the application catalogue revision for
`toolCatalogueRevision`. Stable metadata ordering permits deterministic caching.

Mapping is exact: replace `.` with `_` in the four capability method names;
all other names are unchanged. `methods` is also a tool (not an alias for
`tools/list`), retaining its service-method metadata. MCP protocol metadata stays
outside `arguments` and is never forwarded as service keyword arguments.

In the tables, `P` expands to the observation fields
`pointer="", offset=0, limit=12, max_bytes=8192, revision=null`; `C` expands to
`limit=12, cursor=null, revision=null, max_bytes=8192`. Every parameter lacking a
default is required. `**page` is replaced by the named `P` fields, never arbitrary
keyword passthrough. Keyword-only Python markers have no wire meaning.

| Service method / MCP name when different | Arguments |
| --- | --- |
| `methods` | none |
| `capabilities.browse` / `capabilities_browse` | `scope="root", C` |
| `capabilities.search` / `capabilities_search` | `query, scope="root", input_kind=null, output_kind=null, C` |
| `capabilities.describe` / `capabilities_describe` | `identity, sections=null, known_digest=null, revision=null` |
| `capabilities.schema` / `capabilities_schema` | `identity, pointer="", C` |
| `adaptor_context` | `version, P` |
| `prepare_template` | `filename, values, planning=false` |
| `create_task` | `objective, allowed_providers, budget=null` |
| `list_tasks` | `P` |
| `task` | `task_id` |
| `plan` | `task_id, document, expected_revision, bindings=null` |
| `plan_draft` | `task_id, expected_revision, document_id, draft_revision, bindings=null` |
| `execute` | `plan_id, expected_revision` |
| `job` | `job_id` |
| `observe` | `job_id=null, plan_id=null, section="verification", P` |
| `cancel` | `job_id` |
| `verify` | `job_id` |
| `resource` | `resource_id, offset=0, length=4096` |
| `inspect_resource` | `resource_id, P` |
| `inspect_resource_metadata` | `resource_id, P` |

| Authoring method / MCP name | Arguments |
| --- | --- |
| `create_draft` | `provider, name="Untitled"` |
| `list_drafts` | `P` |
| `draft` | `document_id, expected_revision, offset=0, length=4096` |
| `locate_draft` | `document_id, expected_revision, pointer=null, offset=null` |
| `edit_draft` | `document_id, expected_revision, source, format=null` |
| `patch_draft` | `document_id, expected_revision, edits` |
| `undo_draft` | `document_id, expected_revision` |
| `redo_draft` | `document_id, expected_revision` |
| `draft_command` | `document_id, expected_revision, line` |
| `open_draft` | `document_id, expected_revision, filename` |
| `write_draft` | `document_id, expected_revision, filename=null` |
| `workflow_graph` | `document_id, expected_revision, P` |
| `rewire_workflow` | `document_id, expected_revision, pointer, source, artifact_index` |
| `create_workflow_design` | `document_id, expected_revision` |
| `connect_workflow` | `document_id, expected_revision, connection` |
| `disconnect_workflow` | `document_id, expected_revision, connection_id` |
| `configure_workflow_feedback` | `document_id, expected_revision, loop_id, config` |
| `compile_workflow_design` | `document_id, expected_revision` |
| `reference_workflow` | `document_id, expected_revision, operation_id` |

| Inspection method / MCP name | Arguments |
| --- | --- |
| `inspection_workspace` | `preset=null, resource_id=null` |
| `inspection_resources` | `P` |
| `capture_inspection` | `filename, kind, resource_id=null, expected_revision=null` |
| `snapshot_resource` | `resource_id, kind` |
| `inspect_snapshot` | `resource_id, revision, view, offset=0, limit=50, columns=null, x_column=null, y_column=null` |
| `reference_snapshot` | `resource_id, revision, kind, selection` |
| `inspect_selection` | `reference_id, P` |
| `selections` | `P` |

| Scheduling method / MCP name | Arguments |
| --- | --- |
| `schedule_create` | `spec` |
| `schedule_preview` | `spec, count=5` |
| `schedule_list` | none |
| `schedule_get` | `schedule_id` |
| `schedule_update` | `schedule_id, expected_revision, changes` |
| `schedule_pause` | `schedule_id, expected_revision` |
| `schedule_resume` | `schedule_id, expected_revision` |
| `schedule_cancel` | `schedule_id, expected_revision` |
| `schedule_delete` | `schedule_id, expected_revision` |

Schedule mutations retain expected-revision checks. `schedule_create` declares
future work but launches no worker. The independent `SchedulerRunner` remains
the only schedule dispatcher; MCP does not start one implicitly. Scheduled work
must inherit the selected execution/isolation policy through its trusted service
factory. Closing stdio therefore does not cancel independent scheduled work.

### Schema and effect rules

Every `inputSchema` is an object with `additionalProperties: false`, declared
required fields, defaults matching the table and explicit nullable alternatives.
Do not coerce booleans to integers or strings to numbers. Use the existing
authoring/inspection/template validators for nested contracts, rather than
weakening them to make MCP calls pass. Schema declarations link to these same
contracts; semantic validation and faults remain in the service.
For a well-formed `tools/call`, do not replace an existing service validation
fault with a generic JSON Schema/protocol error. Shared argument binding retains
`INVALID_REQUEST` for unknown/missing service arguments, while the registered
validator retains its more specific value/range fault. `-32602` describes the
MCP call envelope or unknown tool, not a rewritten task/provider/path fault.

The following reusable field definitions are required:

- IDs, source, names, filenames, pointers, kinds, query and version are strings;
  revisions/offsets/indexes are nonnegative integers except snapshot/evidence
  revisions (including `capture_inspection.expected_revision`), which are digest
  strings. `source` in `rewire_workflow` is an
  operation ID; `source` in `edit_draft` is authored text.
- `document`, `spec`, `changes`, `connection`, `config`, `selection` and template
  `values` are objects. `edits` and `columns` are arrays with their existing
  element contracts. `bindings` maps existing JSON pointers to resource ID strings.
  `allowed_providers` is a nonempty array of registered provider strings.
- `P.limit` and `C.limit` are 1..100; `max_bytes` is 2048..65536.
  `resource.length` is 1..16384 bytes. Capability cursors remain distinct from
  observation offsets. `observe` requires exactly one of job/plan ID; its section
  is one of `document`, `plan`, `result`, `verification`, `resources`, `fault`.
- Preserve the current task defaults: 4 attempts, 2 repeated failures,
  600 elapsed seconds, 120 seconds per stage. Attempt limits are 1..100; time
  limits are finite, positive and at most 86400. No tool can expand them later.
- Inspection `view` is `text`, `table` or `series`; snapshot `kind` is `text` or
  `table`; selection `kind` is `text-span`, `table-range` or `series-interval`.
  `preset` is a nullable string from the trusted `workspaces.PRESETS` keys.
  Draft `format` and structured edits use their existing source/patch contracts.
  Draft `length` is 1..16384 characters; snapshot limits are view-specific:
  text 1..16384 characters, table 1..100 rows, series 1..200 points.

Annotations describe effects conservatively. `verify` may invalidate successful
state; `inspection_workspace` can mutate a preset; reads of drafts can activate a
document. Do not mark these universally read-only. `draft_command` retains its
bounded authored-command allow-list; it is not a shell command tool. MCP tool
annotations never grant permission or bypass service checks.

### Result and fault encoding

For a fitting result, `structuredContent` is the exact service carrier
`{"ok":true,"result":VALUE}`. On a service fault it is
`{"ok":false,"fault":FAULT}` and `isError` is true. Return the same carrier as
serialized JSON in one text block for older clients. Preserve every structured
fault field, including code, location, expected/observed data and recovery.
Malformed JSON-RPC, unknown RPC methods and unknown tools are protocol errors;
service input, scope, revision and execution failures are tool errors.
[MCP tool results](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)

Use `ToolResult = InlineSuccess | DeferredSuccess | Failure` as the shared output
schema. `DeferredSuccess` is
`{"ok":true,"resultResource":{"uri":URI,"sha256":DIGEST,"bytes":N}}`, with a
resource-link content block and a small matching JSON text block. It means a
service return value exists, not that a job succeeded. Snapshot the exact value
before returning the reference; dereferencing reconstructs the ordinary result
losslessly. Never rerun a mutating method to recover a lost response. Callers use
`task`, `job` and retained evidence after an uncertain connection outcome.

## Bounded resource contract

Limit each incoming stdio line or HTTP body to 1 MiB, JSON depth to 64, and request
IDs to strings/integers whose rendered form is at most 128 characters. Reject
batches, duplicate JSON keys and non-finite numbers. Drain an oversized stdio line
through its newline before accepting another request. Notifications receive no
JSON-RPC response. Bound concurrent RPC admission independently of native jobs;
keep one active top-level execution per `ExecutionService` as today.

All limits below concern encoded UTF-8 bytes, including JSON escaping and the
complete MCP envelope. The maximum serialized response is 256 KiB. Structured
page payloads retain the service's 8192-byte default and 65536-byte maximum;
small text compatibility copies must also fit the envelope. Catalogue/list pages
contain at most 12 entries by default and 100 absolutely. MCP list cursors bind
the catalogue/namespace revision, authorization profile and list kind. Expired or
mismatched cursors fail explicitly; they never silently restart.

Some existing calls are not bounded: `capabilities.describe` returns complete
sections; `schedule_list/get`, task and authoring results can also grow. Preserve
their service values and use `DeferredSuccess` when the MCP envelope would exceed
256 KiB. This changes delivery, not validation or execution semantics. A captured
result may occupy at most 16 MiB in the response store, with a 64 MiB total
response-store quota per namespace. Reserve storage before a potentially large
mutating call; quota exhaustion fails before that mutation. This reservation
must never gate cancellation, job status, compact lifecycle replies or protocol
errors. Give those control replies their own fixed, preallocated bounded buffer,
independent of snapshot quota; `cancel` needs no 16 MiB reservation. A saturated
response store must still permit cancellation and a bounded acknowledgement.
For other mutations, retain a compact control record independently of large
result storage. A result exceeding its reservation returns a compact durable
fault recording the committed action's IDs and
`outcome: "committed-result-unavailable"`; clients must inspect state, never retry
blindly. Do not claim that output byte bounds limit total planner memory.

Resource URIs use the custom `schemaxis://` scheme, fixed authority `workspace`,
and a persistent opaque namespace ID `N` assigned to the service workspace. `N`
is a routing name, never a credential or filesystem path. All identifiers and
query fields are parsed once, percent-decoded once and validated before lookup.
Unknown/duplicate query keys, fragments, userinfo, ports, path traversal and
unsupported authorities are rejected. No `file:`, arbitrary `http:` or caller
path is dereferenced. URI ownership is checked against `RequestContext`.

| URI template | Meaning and underlying check |
| --- | --- |
| `schemaxis://workspace/N/jobs/J/observations/S{?pointer,offset,limit,max_bytes,revision}` | `observe(job_id=J, section=S, ...)`; exact service section rules. |
| `schemaxis://workspace/N/plans/P/observations/S{?pointer,offset,limit,max_bytes,revision}` | `observe(plan_id=P, section=S, ...)`; only `document` and `plan`. |
| `schemaxis://workspace/N/jobs/J/receipt{?pointer,offset,limit,max_bytes,revision}` | Bounded captured `verification` observation, with historical-evidence label. |
| `schemaxis://workspace/N/resources/R/bytes{?offset,length}` | Exact `resource(R, ...)` descriptor plus bounded base64 bytes. |
| `schemaxis://workspace/N/resources/R/metadata{?pointer,offset,limit,max_bytes,revision}` | `inspect_resource_metadata(R, ...)`, with publication/provenance digest checks. |
| `schemaxis://workspace/N/responses/D{?pointer,offset,limit,max_bytes,revision}` | Immutable captured complete service result addressed by its content digest; bounded JSON observation. |
| `schemaxis://workspace/N/responses/D/scalars{?pointer,offset,length}` | Explicit UTF-8 byte ranges of an oversized JSON string's canonical encoded token, base64 encoded; no silent truncation. |

`S` uses the `observe` section enum. Responses are `application/json` text
contents; an encoded byte page is still JSON with encoding, range, full size and
next offset. Scalar ranges default to 4096 and cap at 16384 bytes, use offsets in
the encoded token, and carry its full SHA-256. This makes large schema/source
strings recoverable when `bounded()` correctly rejects an oversized scalar.
Numbers, booleans and null are returned whole or fail a size limit.

`resources/read` returns the requested page, never an entire large artifact.
`resources/templates/list` exposes these templates and describes their bounds;
`resources/list` lists bounded roots for owned captured responses and retained
jobs/publications. Resource links may point to pages absent from that listing.
Resource failures become JSON-RPC errors with the original service fault in
`error.data.fault`; never emit a success resource containing an unlabeled fault.
The protocol defines URI resource lookup independently of arbitrary file access.
[MCP resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)

Receipt reads describe captured evidence. `verify(job_id)` performs a fresh
check and may invalidate the job and block publication reads. Resource byte and
metadata reads recheck receipt/publication digests; neither URI access nor a
cached result promotes verification. Historical snapshots remain historical.
Returned artifact text is untrusted data, never instructions or executable code.

Response snapshots persist for at most 24 hours from capture, or until explicit
workspace deletion; advertise expiry with references. Ordinary task/job evidence
retains the existing workspace lifetime. Quota cleanup removes expired response
snapshots only, never job evidence to make room. A hosted download signer may
return a separately authorized, expiring HTTPS reference for large outputs; that
private hook is absent from the local core and is not an MCP resource bypass.

## Local tool packages: one format for every consumer

Add `run_tool` to the shared service catalogue and agent transport as well as MCP:

```text
run_tool(task_id, package_digest, values, expected_revision, execute=false)
```

`package_digest` is `sha256:` followed by 64 lowercase hexadecimal characters,
identifying the exact `.schemaxis-tool` archive bytes. Trusted configuration
supplies a local content-addressed package store. This method accepts no package
path, URL, registry name, executable, environment or image override. A separate
local CLI can import/check a package into that store; an MCP call cannot fetch
one. Authors and consumers use the same public package modules and schemas that
future Studio, static exports and a sharing service will consume.

Use a zip container with these versioned contracts, defined once in the core:

- `tool.json`, version `schemaxis.tool/1`: `id`, positive integer `revision`,
  `title`, one-sentence `summary`, Markdown-subset `description`, `tags`, display
  name `author`, tool-document SPDX `licence`, confined relative `template` path,
  `display`, `execution`, derived `requirements`, and `provenance`.
- The referenced existing `schemaxis.workflow-template/1`, its confined workflow,
  named example values and optional declared data assets. Preserve its parameter
  kinds, target restrictions and `schemaxis.workflow-values/1` behaviour.
- `display` holds parameter groups/order, unit labels, widget hints, named value
  examples, selected output aliases/view kinds and an optional recorded-run
  thumbnail. It cannot supply scripts, HTML, expressions or additional bindings.
- `execution` declares `tier` (`browser`, `local`, `runner`), duration class and
  uploaded-input policy/bounds. The minimum runner accepts `local` only and no
  uploaded file parameters or execution-time external file dependencies.
  Unsupported tiers/widgets/inputs fail explicitly;
  do not silently reinterpret them. Scalar/vector parameters supported by the
  existing template binder remain available.
- `requirements` is recomputed from the bound workflow and adaptor manifests:
  provider/adaptor, application/version requirement where declared, and optional
  trusted image identity. Missing version constraints remain `unknown`; author
  requirements cannot narrow the actual provider set or choose a runtime image.
- `package.json`, version `schemaxis.tool-package/1`, lists every payload file
  other than itself as sorted `{path, bytes, sha256}` entries, including
  `tool.json`. `tool.json.provenance.files` covers its template, workflow, values
  and assets (excluding itself and `package.json` to avoid a recursive hash).
  The archive digest binds `package.json` too. Identity/revision are labels;
  digest validation establishes content identity, not publisher trust.

These names and fields are the proposed shared package contract, not an
MCP-specific fork. Implementation must first confirm no shared tool-format work
has already landed; if it has, consume that schema rather than introduce a second
one. Package validation/packing should live in `schemaxis.tool_packages` with
`check_package`, `import_package` and `resolve_package`; no dependency on a sharing
service. `ToolCatalogue` calls it through the `ExecutionService` façade.

Minimum archive limits: 16 MiB compressed, 64 MiB actual decompressed total,
8 MiB per member, 256 regular members and 64 JSON nesting levels. Reject encrypted
members, symlinks, special files, duplicate and case-colliding normalized paths,
absolute/drive/UNC paths, backslashes, NUL, empty/dot/parent components and
unlisted extras. Enforce actual streamed decompression counts, not just zip
headers; use exclusive creation in a fresh owned staging directory. Verify
digests before publication into the immutable store. Do not use unrestricted
`extractall`, resolve external references or import code from package content.

`run_tool` performs this sequence under the same task revision discipline:

1. Resolve and recheck the exact archive digest and payload inventory; validate
   manifest/template/workflow and reject unavailable execution tiers.
2. Bind `values` with the existing template binder into an ordinary workflow;
   independently derive requirements/provider scope and check task authorisation.
   Display/example assets are confined to the immutable package. The initial
   runner refuses execution asset dependencies until the input-staging contract
   below is qualified; it does not smuggle package-store paths into a container.
3. Capture through the normal `plan` path with package/template/values digests
   retained as plan provenance. No native work occurs for `execute=false`.
4. If `execute=true`, call normal `execute` with the new plan revision, counting
   exactly one attempt. Recheck package inputs before dispatch and after execution.
   A stale revision/budget/scope failure retains its ordinary fault; it cannot
   create a replacement task or widen authorisation automatically.
5. Return package identity/digest, binding provenance, plan summary and, when
   requested, job status/ID. Subsequent observation, cancellation and verification
   are the ordinary lifecycle; no opaque package-only success state exists.

`run_tool` is a convenience capture/dispatch operation, not atomic rollback:
planning can advance the task even if dispatch is later refused. Its fault must
then identify the captured plan/revision so a client can inspect it. Package
validation is host-only and is not a native receipt. Package Markdown, examples
and artifact contents cannot modify budgets or become higher-priority prompts.

## Isolation integration contract

The current `SerialJobs`, scheduler resource reservations and
`dispatch.SubprocessRunner` process-tree tracking are cancellation/resource hints,
not hard CPU/memory/disk/network isolation. Native run and verifier calls must
share the isolated execution policy; moving only execution into a container and
then invoking a host native verifier would violate the boundary.

Introduce a trusted, transport-independent executor injection:

```python
ExecutionService(workspace, *, locations=None, executor=None)

executor.run(request: ExecutionRequest, cancellation: Cancellation) -> ExecutionOutcome
executor.verify(request: VerificationRequest, cancellation: Cancellation) -> VerificationOutcome
```

The default executor delegates to the existing `workflow.execute` / `registry.run`
and verifier paths without changed behaviour. `ExecutionRequest` carries job/plan
IDs, exact captured ordinary document and plan digests, job directory, derived
providers, verified input bindings, stage timeout and enclosing monotonic
deadline. `VerificationRequest` identifies the retained run, captured document,
expected receipt digests and the same trusted isolation profile. Requests are
internal dataclasses, not authored JSON extensions.

`ExecutionOutcome` contains the ordinary execution response and a retained
`isolation` record. `VerificationOutcome` contains the ordinary verifier response
and its isolation record. The service still controls task attempts, `_verify_run`,
publication `_collect`, digest rechecks and the final cancellation check before
committing success. `_verify_run` delegates native work through `executor.verify`
and retains its existing authored-input equality and `verified is True` checks.
An isolated worker's exit status or self-reported boolean alone cannot bypass
the existing core verifier contract.

Audit collection and resource paths as part of each runtime-family qualification.
If a route's publication metadata or inspection check needs native execution,
that work also goes through the executor boundary; no host native fallback is
permitted after selecting isolation.

An opt-in `ContainerExecutor` uses a trusted `ImageResolver.resolve(providers,
routes) -> IsolationProfile`. The profile pins an image by OCI digest, configured
runtime family, application versions, CPU/memory/PID/disk/time limits and declared
network policy. No application-name branch belongs in MCP or the framework;
unsupported provider combinations return `ISOLATION_UNAVAILABLE`. A first image
may qualify one runtime family; a multi-provider workflow is refused until its
trusted image or stage-isolation policy is qualified. It never falls back to host
execution after isolation was requested.

Each attempt launches fresh non-root containers with read-only roots, no network
by default and a single writable owned job volume; immutable declared inputs are
staged into that volume and checked by digest. Runtime scratch, home and temporary
directories live within that volume. No host home, configuration directory,
container-engine socket or writable package store is mounted. Trusted adaptor
code may generate native scripts as today; authored documents cannot supply code.
The profile cannot expand network access based on untrusted artifact text.

Staging must preserve captured-input identity. Any required path transformation
is a declared preparation step before final host planning/capture, and the
prepared plan records both original input digests and staged document digest.
Never edit a captured document or receipt to make it fit a container. Existing
external service bindings support standalone documents only; isolated workflow
handoffs using external inputs remain unavailable until their staging/replanning
contract is qualified. Self-contained generated documents remain a viable first
isolation slice.

Keep the run-directory spelling identical inside the container and on the host
for this slice because current receipts can contain absolute paths. Bind that
one directory only. Do not rewrite signed/hashed receipt paths on return or claim
relocatable receipts. Future portable evidence must be a separately versioned
contract. A publication leaves the boundary only after normal core collection
checks for regular files, owned-root containment and matching provenance.

`Cancellation` reaches container termination and deadline enforcement; terminate
the container/process tree, retain partial evidence and return unverified native
state on interruption. Hard memory/disk/PID policy failures use distinct
`ISOLATION_LIMIT_EXCEEDED` faults with the limit and observed cause. Missing image,
runtime, unqualified policy and launch failure are distinct faults. Retain image
digest, enforced limits, exit reason and bounded metrics without describing
sampled RSS as an enforced memory cap. Scheduled service factories inject the
same executor, including reverification.

### Admission profiles and trusted local parity

The existing transport permits caller-local `prepare_template`, `open_draft`,
`write_draft` and `capture_inspection` filenames. The opt-in `trusted-local`
profile preserves that contract and documents its trust requirement. The default
`declared-documents` profile denies these four methods with `MCP_POLICY_DENIED`
until an owned-input/file broker exists. It also rejects authored file options
and template values that reach outside staged owned inputs, including symlink
ancestors; denying only the four filename methods is insufficient. The profile
permits service-owned task/plan/authoring control records; all native writes stay
inside the attempt's owned job directory. File/path contracts come from adaptor
declarations and validation; a route without a qualified confinement contract is
unavailable in the strict profile, even when hosted on loopback.

Apply `FileAdmission.check(document, context) -> InputAdmission` before calling
`registry.plan`, `workflow.inspect_plan`, a template binder or any route hook
that can read authored files. Containerizing execution alone does not prevent
host planning from reading a caller-selected path. Admission uses only trusted
declarations and pure schema/document inspection, recursively over workflow
operations and template-bound values. Its result records the route's qualified
file-access classification and owned input identities; unknown classification
fails closed. The existing `reusableInputs` hook is not a safe preflight
classifier because it may open/hash the files it reports. After pure admission,
resolve/copy verified inputs with a confined broker and then plan the prepared
document. Reject any pathname not covered by that contract, including paths in
otherwise valid authored operation options. No application-name branches or
heuristics based on keys containing `file` are permitted.

A hosted profile can further deny draft/presentation and schedule operations;
the embedding host publishes that exact allow-list and never starts an implicit
authoring or scheduler service. The profile is returned by `methods` metadata
and tool descriptions, with explicit unavailable/recovery information. The
bounded declared-command parser in `draft_command` remains the only command
contract; no profile exposes Python, shell execution or arbitrary native calls.

Keep method descriptors present with their policy requirements, and fail before
calling the service for denied operations. Allowed calls have identical service
results/faults; explicit admission denials are additional transport-policy faults.
Policies never silently ignore requested fields, redact evidence into a new
success state, or promise an unrestricted hosted authoring surface. Hosted path
display/redaction is a separate labelled projection over retained original
evidence, not a mutation of core receipts.

## Implementation checkpoints and acceptance

The next implementation order is shared service contracts, stdio dispatcher,
bounded resource store, local packages, then the HTTP binding and executor seam.
Keep the old agent transport working throughout. Client configuration examples
belong in `docs/mcp.md` after actual client interoperability is demonstrated.

Required checks for the implementation owner:

- Freeze the current allow-list in a parity test: all 55 methods plus `methods`
  map once; compare arguments, defaults and exact faults through both transports.
  Add `run_tool` to both surfaces together. Inventory new methods automatically.
- Use fake service/client fixtures for both wire eras: startup/discovery,
  initialization, unknown methods/tools, IDs, notification silence, malformed
  JSON, depth/body bounds, stdout purity and recoverable subsequent requests.
- Compare generated descriptions/schema fragments with shared catalogue sources;
  reject missing descriptions or callable/schema signature drift. Block native
  application imports in discovery, tool listing, schema and planning checks.
- Exercise small/oversized returns, member/scalar reconstruction, changed
  observation digests, forged/cross-namespace URIs, expiry/quota handling and
  artifact/receipt tampering. Fill response storage completely, cancel a running
  job, and establish that cancellation/status/compact replies still work without
  reserving large-result space. Never retry a mutation while paging its response.
- Exercise HTTP Origin, credentials/context, required headers/body mismatch,
  version errors, method statuses, connection-independent ownership and explicit
  job cancellation. Test path options as well as path-based service methods.
- Exercise malicious packages, decompression limits, digest changes, provider
  mismatches, unsupported tiers, plan-only and one-attempt execution. Demonstrate
  the same package validates through the shared CLI and MCP entry points.
- Qualify container execution and reverification with a fake runtime first,
  then bounded native cases for selected images: no network, read-only root,
  outside-write refusal, limits, cancellation and preserved receipt semantics.
  Host-only mocks do not establish real container isolation.

This design change itself runs no build, unit suite, native job or live model.
Its checkpoint is the complete method inventory, dated protocol decisions,
resource/package boundaries and proposed injection signatures above. Open
implementation risks are receipt path dependence, missing route-wide file
confinement declarations, the bounded response-store reservation edge case and
actual interoperability with clients that support only the legacy era. Do not
advertise hosted safety or broad client compatibility until those checks pass.
