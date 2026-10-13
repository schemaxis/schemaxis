# Durable scheduled execution

Schemaxis can retain a pinned executable document and run it later through the
existing planning, execution, budgeting and publication-verification service.
The schedule catalogue is a checksummed JSON file, not the proposed process
history database. No database or archive-management feature is implied.

A control client does not start a background process. Run `schemaxis schedule
--workspace <directory> serve` as an independently supervised foreground service.
Closing Studio or an AI transport leaves that owner running. Stopping the owner
requests cancellation through the execution service; unfinished occurrences are
recorded as interrupted and are never automatically replayed after restart.
Supervise the command with the operating system's normal service facilities if
it must survive logout or machine restart. Pending work cannot execute while the
owner or computer is stopped.

Preview and register a declaration, then start its worker in a separate terminal:

```sh
schemaxis schedule --workspace ./scheduled-work preview schedule.json
schemaxis schedule --workspace ./scheduled-work create schedule.json
schemaxis schedule --workspace ./scheduled-work list
schemaxis schedule --workspace ./scheduled-work serve
```

`show ID` returns occurrence history. `pause`, `resume`, `cancel` and `delete`
take `ID --revision N`; `update` takes `ID changes.json --revision N`. YAML files
are accepted with the optional host extra; stdin uses `--input-format yaml`.
Workers use ordinary private application configuration (`SCHEMAXIS_CONFIG` or
the local configuration in their working directory), never paths authored into
the schedule's trigger settings.

Studio's **Schedules** window captures the exact selected saved document,
previews triggers and provides pause/resume/cancel controls. Its **Worker setup**
panel shows the store's exact startup command. A changed saved document is
rejected at registration until refreshed. Changing the draft later does not
change the captured schedule.

The JSON-lines agent methods are `schedule_create`, `schedule_preview`,
`schedule_list`, `schedule_get`, `schedule_update`, `schedule_pause`,
`schedule_resume`, `schedule_cancel` and `schedule_delete`. Their declarations
live in `<agent workspace>/schedules`; run the worker against that directory.
Request `methods` for exact arguments. These tools register or control work;
they do not launch the independent owner.

## Schedule declaration

```json
{
  "objective": "Publish the captured engineering workflow each weekday",
  "document": {"version": "schemaxis.freecad/1", "nodes": [{"id": "body", "filter": "box"}], "output": "body"},
  "allowedProviders": ["freecad"],
  "trigger": {
    "kind": "calendar",
    "start": "2026-10-12T00:00:00-05:00",
    "timezone": "America/Winnipeg",
    "hour": 9,
    "minute": 0,
    "weekdays": [0, 1, 2, 3, 4]
  },
  "overlap": "coalesce",
  "misfire": "runOnce",
  "graceSeconds": 60,
  "maxCatchUp": 10,
  "maxOccurrences": 100,
  "maxRetries": 0,
  "expiresAt": "2027-01-01T00:00:00-06:00"
}
```

The document is copied and digested at registration. Registration performs
host-only planning and checks its providers against caller authorisation; no
native application starts. External file paths in the document remain references,
not captured dataset bytes. The actual document is re-planned at dispatch through
the execution service. This first version has no mutable template selection,
external resource bindings, arbitrary shell commands or arbitrary Python actions.

Triggers have exact fields:

| Kind | Fields |
| --- | --- |
| `once` | `kind`, `at` (ISO time with UTC offset) |
| `interval` | `kind`, `start` (offset time), `seconds` (finite, 1..3155760000) |
| `calendar` | `kind`, `start`, `timezone` (IANA name), `hour`, `minute`, `weekdays` |

Weekdays use Monday=0 through Sunday=6. Calendar triggers skip nonexistent wall
times during spring-forward and use the first occurrence of repeated wall times
during fall-back. Interval triggers measure elapsed seconds. Preview returns UTC
instants, and does not modify persistent state.

## Budgets and dispatch policies

The owner executes one occurrence at a time. Each occurrence receives a fresh
execution-service task budget. Optional `budget` fields are `maxAttempts`,
`maxRepeatedFailures`, `maxElapsedSeconds` and `timeoutPerStageSeconds`, with the
same bounds/defaults as ordinary agent tasks. `maxOccurrences` defaults to 100
and is bounded at 100000; skipped occurrences also consume this trigger budget.
Every revision has its own trigger budget. `maxRetries` defaults to zero and
must be below `maxAttempts`. Only failed execution is retried, using the same
pinned plan and existing attempt/repeated-failure/elapsed budgets. Interrupted
execution is never automatically retried. A retry rejected by those budgets
becomes terminal failure.

`overlap` controls a trigger arriving while that schedule has pending work:

- `queue`: retain it for serial execution.
- `skip`: record it as skipped.
- `coalesce`: retain at most one queued occurrence behind the active occurrence.

An occurrence is late when its due time precedes the current clock by more than
`graceSeconds` (default 60, range 0..86400). `misfire` then applies:

- `skip`: record one skipped missed occurrence and advance beyond the current time.
- `runOnce`: enqueue one missed occurrence and advance beyond the current time.
- `catchUp`: retain successive due times, processing at most `maxCatchUp` per
  owner tick (default 10, range 1..100), within the occurrence limit.

Overlap rules still apply to missed occurrences. `expiresAt` prevents new dispatch
past that instant and skips expired queued work; an already running job can
finish. Pause prevents future collection and queued dispatch, while an active job
finishes. Resume applies the declared misfire policy. Cancel cancels queued work
and requests cancellation of the active job on the next owner tick. Revision
checks protect control operations from stale writes.

## Recovery, output and inspection

Each occurrence has a stable identity derived from schedule ID, revision and due
instant. The claim is committed before native dispatch. A crash between claim and
completion results in an interrupted occurrence with unknown native state, rather
than duplicate execution. This deliberately does not promise exactly-once native
side effects. Inspect retained evidence before creating replacement work.

Execution workspaces live below `<workspace>/occurrences/`. Successful occurrence
status requires the execution service's verified publication result; file
existence alone is insufficient. Schedule inspection includes task, plan and job
IDs, the execution workspace, status, verification and faults. The normal
execution workspace preserves authored input and receipts.

Control clients can create, preview, list, inspect, revise, pause, resume, cancel
and delete schedules while the independent owner is running. Deleting a schedule
removes its catalogue and occurrence-index records, but deliberately retains its
execution evidence. Cancel/finish pending work before deletion or revision.
Revising a schedule reactivates it with a fresh occurrence count and the next
trigger at or after the current clock. Use ordinary task/job inspection on the
retained execution workspace for detailed evidence.

Corrupt checksum/version/state relationships stop catalogue operations without
silently discarding evidence. Only one runner owns a workspace, while short state
transactions allow concurrent control clients. The owner lock uses the existing
POSIX locking model used by the agent execution service.
