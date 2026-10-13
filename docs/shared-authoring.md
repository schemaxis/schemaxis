# Shared JSON authoring

The terminal console, visual console and local agent tools now use the same
revision transitions, document records and undo history. `authoring.py` owns the
source/property/history operations; `AdaptorConsoleSession` retains durable
workspace and native-state ownership. `ExecutionService` captures the current
draft for the existing verified execution lifecycle.

This is the first M3 slice. It covers JSON documents supported by the console's
selected adaptor, including its assembly routes. [Workflow drafts](workflow-authoring.md)
now use the same source/history and `plan_draft` lifecycle. The next [typed inspection slice](typed-inspection.md) adds shared text/table/series
references and trusted workspace presets. YAML input remains future work.

## Visual and terminal editing

Start the ordinary console:

```sh
PYTHONPATH=src python3 -m schemaxis console --provider freecad --workspace evidence/my-authoring --web
```

Choose **Edit source / properties**. The dialog displays the current source,
revision and diagnostics. **Retain source** saves one undo group, including
invalid JSON. Closing and reopening the dialog keeps unsubmitted text in that
browser tab; only retained source survives a page/process restart. **Reload current
draft** explicitly discards local unsubmitted text. A stale revision blocks editing
until the client refreshes; background polling never replaces dirty editor text.

A property uses an RFC 6901 pointer such as `/nodes/0/options/height`. **Find in
source** selects the corresponding JSON value. **Inspect caret value** retrieves
the smallest value enclosing the source caret. **Apply property** replaces that
value through the same validated edit service. Source offsets count Unicode code
points; the browser converts them to DOM UTF-16 selection offsets.

Source edits retain the exact UTF-8 text. Property and command edits format the
whole JSON document; they preserve authored expressions and untouched values but
do not preserve whitespace or key ordering. Property groups are validated once at
their end, then persisted as one undo group. They support `add`, `replace`,
`remove` and `test`; there is no arbitrary code or implicit expression evaluation.

The terminal keeps existing commands and adds:

```text
draft
patch '[{"op":"replace","path":"/nodes/0/options/height","value":7.5}]'
undo
redo
write new-source.json
```

`source JSON_STRING` accepts a JSON-encoded source string as one shell-quoted
command argument. In Python, construct it with
`'source ' + shlex.quote(json.dumps(source))`. `open FILE` now retains invalid
UTF-8 JSON drafts rather than losing the attempted source. `inspect`, property
commands and native preview reject an invalid current draft (`INVALID_DRAFT`).
Syntax diagnostics include line, column and code-point offset; semantic diagnostics
retain the adaptor's structured fault location. Native geometry remains stale after
any authored edit or history travel, including undo to an earlier equal document.

## Agent authoring

Launch `schemaxis agent --workspace evidence/my-agent` as described in the
[agent guide](agent-service.md). Its authoring workspace is
`evidence/my-agent/authoring`, with the same `session.json` and exclusive ownership
lock as the console. No second editable document model is stored in agent state.

| Method | Purpose |
| --- | --- |
| `create_draft(provider, name?)` | Create a console-supported adaptor document. |
| `list_drafts(**page)` | Discover document identities, revisions and validity. |
| `draft(document_id, expected_revision, offset?, length?)` | Read exact source in slices, with diagnostics and history counts. |
| `edit_draft(document_id, expected_revision, source)` | Retain valid or invalid source in one undo group. |
| `patch_draft(document_id, expected_revision, edits)` | Apply an atomic group of validated pointer edits. |
| `locate_draft(document_id, expected_revision, pointer?, offset?)` | Map one pointer to a source range, or one caret to a value. |
| `undo_draft` / `redo_draft` | Travel one history group with a fresh monotonically increasing revision. |
| `draft_command(document_id, expected_revision, line)` | Run bounded authoring commands using the same console semantics. |
| `open_draft(document_id, expected_revision, filename)` | Retain source and its on-disk conflict baseline. |
| `write_draft(document_id, expected_revision, filename?)` | Write exact source with conflict detection. |
| `plan_draft(task_id, expected_revision, document_id, draft_revision, bindings?)` | Capture a valid draft under an authorised task. |

All edits require the displayed document identity and revision. Task-plan revisions
and document revisions are **different counters**: `plan_draft.expected_revision`
is the task's current plan revision, while `draft_revision` is the document revision.
Plans and jobs retain `draft: {document, revision, sourceDigest}`. An edit, undo or
redo after capture blocks that plan's execution, even if the JSON values return to
an earlier state. Capture a new plan to execute. The previous job and its evidence
remain observations of their original captured revision.

```json
{"id":1,"method":"create_draft","params":{"provider":"freecad","name":"Box study"}}
{"id":2,"method":"edit_draft","params":{"document_id":"DOCUMENT_ID","expected_revision":2,"source":"{\"version\":\"schemaxis.freecad/1\",\"nodes\":[{\"id\":\"body\",\"filter\":\"box\"}],\"output\":\"body\"}"}}
{"id":3,"method":"plan_draft","params":{"task_id":"TASK_ID","expected_revision":0,"document_id":"DOCUMENT_ID","draft_revision":3}}
```

Replace example identities/revisions with returned values. Create an authorised
task with `create_task` first; its provider and execution budgets still apply.
`draft_command` accepts only `add`, `set`, `remove`, `show`, `select`, `undo`, `redo`,
`patch` and `source`. It cannot invoke native preview, start live clients or change
runtime configuration to bypass the task's execution lifecycle.

The source limit is one MiB of UTF-8. Source reads default to 4,096 code points and
are capped at 16,384; each reply returns `nextOffset` and a source digest. Keep the
same expected revision across all slices. Located values are capped at 65,536
encoded bytes; inspect a smaller pointer if necessary. Structured property groups
contain 1–100 edits. Invalid groups and stale revisions publish no partial changes.

To continue in the terminal after the agent exits:

```sh
PYTHONPATH=src python3 -m schemaxis console --provider freecad --workspace evidence/my-agent/authoring
```

Reopening preserves draft identity and history. Two processes cannot own this
workspace simultaneously. Within one Python process, a console application may
use `service.authoring`, but callers must serialise access through a shared lock.
The current CLI does not launch simultaneous console and agent transports under
one process. Existing direct `plan(document, ...)` calls remain supported and do
not silently become linked to an unrelated draft.

## Files and recovery

The source editor persists into the workspace; it does not overwrite the input
file on every edit. `write` / `write_draft` writes exact current source, including
invalid drafts. Opening a file records its byte digest. Replacing that opened file
requires the digest still to match. Changed, deleted or symlinked destinations
raise `FILE_CONFLICT`; choose a new destination or reopen the external version.
A destination never opened by this workspace is created exclusively and cannot
silently replace an existing file. Existing `save FILE` keeps its previous
exclusive, validated document/native-export behaviour.

File baselines are separate from undo snapshots, so undo cannot roll the baseline
back and accidentally overwrite a later external change. Writes use atomic
publication and reconcile uncertain visible publication. Saving a source file and
updating session metadata is not a cross-file transaction; if the second step
fails, later writes conservatively conflict until the source is reopened. External
edit detection compares immediately before publication; it is not a filesystem
compare-and-swap against another process writing in that final interval.

Old session files remain readable; source is generated for legacy records until
the next edit. Invalid source, diagnostics and history live in the same checksummed
session file and survive restart. This is a trusted local editing service with
explicit paths, not an OS file-access sandbox.

## HTTP surface and verification

`POST /api/authoring` accepts `document`, `revision`, `action`, and action fields.
Actions are `read`, `source`, `patch`, `locate`, `undo`, `redo` and `write`. Existing
loopback token/origin checks apply. Busy console commands reject edits with
`SESSION_BUSY`; browser commands also carry document/revision guards. Existing
terminal command callers can continue to use serial command submission.

[Verification](../verification/2026-09-27-shared-authoring.md) records host checks,
browser interaction and native acceptance. Reproduce the native serial case with:

```sh
PYTHONPATH=src python3 tools/qualify_authoring.py --output-directory evidence/authoring-qualification
```
