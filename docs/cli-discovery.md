# Version, help and topic discovery

The installed `schemaxis` command and `python3 -m schemaxis` use the same parser
and execution function. From an uninstalled checkout, set `PYTHONPATH=src`.

```sh
schemaxis --version
schemaxis --help
schemaxis run --help
schemaxis help run
schemaxis help capabilities search
schemaxis help extrusion --scope app/freecad
schemaxis help retained
schemaxis help plan --search
```

`--version` prints `schemaxis VERSION` from installed distribution metadata.
An uninstalled source checkout falls back to the existing `[project]` version in
`pyproject.toml`; no separate release number is maintained. The `schema --version`
option still selects an input document contract, independently of package version.

`help` with no topic prints top-level help. An exact command path prints that
command's ordinary `--help`. Other topics search both command names/summaries and
operation capabilities. Use `--search` to search an exact command name as keywords.
Results are JSON: `commands` holds matching command paths, summaries and help
commands; `capabilities` holds the unchanged shared capability-search response.
No match is a successful search with empty results.

Search is case-insensitive AND substring matching. Command summaries come directly
from the current parser, including nested commands. Operation search reuses
[capability discovery](capability-discovery.md), including its existing metadata,
ordering, scopes, kind facets, revisions, cursors and faults:

```sh
schemaxis help extrusion --input-kind profile --output-kind solid --limit 1
schemaxis capabilities browse
schemaxis capabilities describe operation/freecad/extrude --section requirements
```

`--scope`, `--input-kind` and `--output-kind` constrain operation results;
command results remain global. Repeat the same topic/options with `--cursor`
from `capabilities.page.nextCursor` to retrieve more operations. `--limit`
(default 12) and `--max-bytes` (default 8192) bound the nested capability response,
not the combined wrapper or command listing. Use `capabilities search` directly
when a byte bound is required on the whole response. `--revision` has the same
catalogue snapshot semantics as that command.

Exit status is 0 for version/help and valid searches, 1 for structured runtime or
discovery faults, and 2 for argument/usage errors. Argument help and version are
plain text; command results and structured faults are JSON. Usage diagnostics go
to stderr. Discovery does not start applications or establish native availability
or qualification. See [headless operation](headless.md).
