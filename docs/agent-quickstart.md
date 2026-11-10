# Agent quickstart

Install Schemaxis in a virtual environment and register its installed executable
with your MCP client as described in [MCP tools](mcp.md). No model account or API
call is needed to explore tools and capture a host plan.

Ask your client to list tools and search for `exact polynomial roots` with
`capabilities_search`. Read `operation/sympy/isolateRealRoots` with
`capabilities_describe`. Discovery returns declarations and qualification scope;
it does not probe a native installation.

Call `create_task` with an objective and authorised provider:

```json
{"objective":"Isolate every real root of x squared minus two","allowed_providers":["sympy"],"budget":{"maxAttempts":2,"maxElapsedSeconds":120}}
```

Use the returned task ID and revision in `plan`:

```json
{
  "task_id": "TASK_ID",
  "expected_revision": 0,
  "document": {
    "version": "schemaxis.sympy/1",
    "operation": "isolateRealRoots",
    "coefficients": ["1", "0", "-2"],
    "maximumIntervalWidth": "1/1000"
  }
}
```

This is a useful host-only checkpoint: the default admission profile checks a
digest-pinned file-free contract, and the ordinary planner validates exact
rational input. It does not execute an application. Inspect the captured plan
using `observe` with `plan_id` and `section: "plan"`.

For native execution, first configure the qualified interpreter using
[the SymPy installation instructions](sympy.md). Call `execute` with the returned
plan ID and its returned revision. Poll `job`, inspect `observe` with sections
`verification`, `resources` and `fault`, and call `verify` for a fresh check.
Use `cancel` if needed. Report the actual verification scope and evidence relevant
to the objective; a successful process or existing output alone is insufficient.

The JSON objects above are tool arguments, not raw MCP envelopes. Modern clients
add `tools/call`, JSON-RPC IDs and required `_meta` fields; legacy clients perform
their initialization handshake. Keep the subprocess alive throughout the flow.
Unknown routes, external file inputs and caller-local filename tools are refused
by default. The client cannot expand an existing task's authorisation or budgets.

This quickstart is a declared workflow recipe. It is not a recorded autonomous
model evaluation or a claim of tested compatibility with every MCP host.
