# Schemaxis Studio architecture

Status: approved direction, 2026-10-04.
This document replaces the visual console (`console_ui/`) as the target GUI. The
retained HTTP security model, revision-checked authoring and `workflow_design.py`
loop analysis are kept; the page shell, layout, canvas and messaging are rebuilt.

## 1. Names

The GUI is **Schemaxis Studio**. Each window has one job and one primary role.

| Window | Recommended name | Alternatives considered | Primary role | Job |
| --- | --- | --- | --- | --- |
| Home | **Start** | Launcher, Dashboard | all | Recent designs/runs, new design, new adaptor instance, open file |
| Inter-adaptor flowchart | **Workflow Designer** | Connection Window, Flow Canvas, Coupling Board | dev | Adaptor instances, ports, arrows, loops, parameters, outputs; exports a template |
| Single-adaptor window | **Adaptor Workbench** | Adaptor Window, Adaptor Studio | dev | One adaptor instance: input JSON, schema, templates/snippets, viewers, references |
| Template operation | **Case Runner** | Run Desk, Workflow Runner | user | Choose template, fill parameter values, run, watch progress, browse outputs |
| General JSON | **Schema Editor** | Multi-schema Editor | dev | Any JSON file against one or more selected adaptor schemas |
| Data views | **3D Viewer**, **Image Viewer**, **Text Viewer**, **Table Viewer** | Grep View, Column Inspector | all | Embedded in windows above, or opened alone on an artifact |
| Configuration | **Settings** | Preferences | admin/dev | Editor, output naming, applications, theme, role |
| Installation | **Application Setup** | Installer | admin | Locate native applications (`schemaxis configure`) and check readiness |

"Workflow Designer" is kept because users will recognise it. "Case" already
means "one set of values for a template" in the template architecture, so the
user's window is the **Case Runner** and the user's values file is a **case file**.

## 2. Roles

| Role | Can do |
| --- | --- |
| admin | Everything; Application Setup; organisation defaults in Settings (output index width, naming defaults, resource limits) |
| dev | Workflow Designer, Adaptor Workbench, Schema Editor; create/export templates; dev-level Settings |
| user | Case Runner, viewers, outputs; personal Settings (theme, editor) |

The current product is a local, single-person, loopback tool. Roles are therefore
**UI modes** chosen in the top bar, persisted in Settings. They shape navigation;
they are not a security boundary. Real multi-user authorisation belongs to a later
hosted deployment and must be enforced by the server, never by hiding UI.

## 3. Product flow

```text
dev:  Workflow Designer ──(adaptor instances, ports, arrows, parameters, outputs)──▶ template bundle
        │  ▲
        ▼  │ click instance
      Adaptor Workbench (input JSON + schema + snippets + viewers)

user: Case Runner ──(template + case file)──▶ bind ─▶ plan ─▶ run ─▶ verify ─▶ named outputs
```

A template is the existing `schemaxis.workflow-template/1` manifest plus an
ordinary `schemaxis.workflow/1` body. A case file is the existing
`schemaxis.workflow-values/1`: parameter values only, plus run options
(see §7). Nothing in Studio introduces a second execution path: the Case Runner
binds and runs through `workflow_templates.prepare_template` and the existing
workflow executor / execution service.

## 4. Data model additions

### 4.1 Workflow design version 2: ports

`schemaxis.workflow-design/2` extends version 1. Version 1 documents are migrated
on open (connections become anonymous port pairs). Ports are a **named,
typed interface on one operation instance**. They are not ParaView output ports.

```json
{
  "version": "schemaxis.workflow-design/2",
  "workflow": {"version": "schemaxis.workflow/1", "operations": [ ... ]},
  "ports": {
    "mesh": {
      "inputs":  {"geometry": {"target": "/nodes/0/options/file", "kind": "artifact",
                               "data": {"kind": "geometry", "formats": ["step"]}}},
      "outputs": {"volume":   {"artifact": 0, "kind": "artifact",
                               "data": {"kind": "geometry", "formats": ["vtu"]}},
                  "quality":  {"artifact": 1, "valuePath": "/minimumQuality", "kind": "value",
                               "data": {"kind": "number"}}}
    }
  },
  "connections": [
    {"id": "c1", "from": {"operation": "cad", "port": "solid"},
                 "to":   {"operation": "mesh", "port": "geometry"}}
  ],
  "controllers": {},
  "parameters": {},
  "outputs": {},
  "naming": {},
  "layout": {"nodes": {"cad": {"x": 80, "y": 120}}, "viewport": {"x": 0, "y": 0, "zoom": 1}}
}
```

Rules:

- An input port targets one existing runtime input of its operation (same scope rule
  as v1: `/dimensions`, `/definitions`, `/settings`, or `/nodes/N/options/...`).
  An output port names one producer artifact index, plus `valuePath` for values.
- One input port accepts at most one connection (fan-in uses several input ports).
  One output port may feed any number of input ports (fan-out / parallel branches).
- Each connection compiles to exactly one v1 connection
  (`targetPointer`, `kind`, `artifactIndex`, `valuePath`). Validation, loop
  detection (Tarjan SCC), controller identity and DAG compilation reuse the v1
  machinery unchanged. Ports add names and compatibility checks; they add no
  second semantics.
- `data` is descriptive metadata used for compatibility hints: `kind`
  (geometry, image, video, table, series, text, number, vector, audio, archive),
  optional `formats`, `units`, `layout` (`interleaved` x0 y0 z0 x1 … or `planar`
  x0 x1 … y0 y1 …), `streaming` (boolean), `contiguous` (boolean). Mismatches are
  warnings in the designer; the native planner remains authoritative.
- `layout` is presentation only. It is excluded from loop identity and from the
  template digest, so moving a box never invalidates saved feedback settings.
- Multiplicity: "Duplicate instance" copies an operation with a new ID. Sweeping
  N instances over a parameter uses the existing axes/analytics, not N boxes.

### 4.2 Parameters and named outputs live in the design

`parameters`, `outputs` and `naming` use the existing template contract
(`template-contract.md`). "Expose as parameter" on an operation option moves the
literal into `/settings/<id>` (or `/dimensions/<id>` for geometry) and replaces it
with `{"$document": "/settings/<id>", "scope": "workflow"}`, as one undo group.
**Export template** compiles the design (`workflow_design.compile`) and writes a
bundle directory: `template.json`, `workflow.json`, `cases/example.json`.

### 4.3 Feedback loops: keep it simple

When arrows close a loop, the designer shows it (orange) and the inspector offers
the configurable controllers already in `workflow_loop_controls`: fixed point and
constant relaxation, with maximum iterations and tolerances. Other methods (Aitken,
quasi-Newton, step doubling, STSC) are listed as future, with their requirements.
A later milestone may execute *fixed point with constant relaxation* through the
existing bounded `feedback.py` controller. STSC stays design-only.

### 4.4 Output naming

Native publication names stay unchanged; receipts and digests depend on them.
Naming is a **post-verification view**: after a run verifies, the runner creates
`named/` with hard links (copies across filesystems) named by a pattern, and
`named/naming.json` mapping each name to its verified artifact and sha256.

Pattern tokens: `{index}` (zero-padded to the admin/dev width, default 6),
`{operation}`, `{output}` (named output alias), `{param:ID}`, `{axis:NAME}`,
`{artifact}` (native index), `{ext}`. Values are sanitised: `.` → `p`, `-` → `m`,
spaces/other → `_`. Default pattern: `{index}-{operation}-{output}{ext}`. A dev
may choose e.g. `{index}-inlet_{param:inlet}-spoiler_{param:spoiler}{ext}`.
Collisions fail the naming step (never overwrite), and the run stays verified.

### 4.5 Adaptor snippets and starter templates

Each adaptor may ship `adaptors/<id>/studio.json` using
`schemaxis.studio-adaptor/2`. See [guided-authoring](guided-authoring.md) for the
complete field and interaction contract. Libraries declare category buttons,
templates and snippets with typed fields. Snippets contain an `inserts` array:
RFC 6901 `at` pointers place `values` or deep `merge` data. `-` appends;
`@cursor` replaces the selected value. The compatible caret collection takes
precedence over append, and missing declared containers are created. Every
insertion is one undo transaction and previews all changes, including conflicts.

Body markers `{"$fill":"field"}` become durable, self-describing markers when
inserted. `${field}` interpolation is restricted to declared ID fields; one
field may repeat across an ID and its references. Object-key interpolation is
unsupported. Templates may use a confined `file` under `studio/templates/` or
an inline `document`. The loader migrates v1 libraries into this same model.

The generated catalogue test fills all fields from `testValues`, field defaults
or deterministic type values, then host-plans every entry with process launch
prohibited. `baseDocument` supplies required context at library or item level;
`requires` explains that context to authors. `testCursor` is required for
`@cursor` entries. Each unfilled variant must report every exact marker pointer.

Markers may be saved as drafts. Planning, validation, binding and execution
return `UNFILLED_VALUES` until they are filled. A design may export markers only
at exact exposed parameter targets; the generated example case remains a draft
until its user supplies real values. **Expose unfilled values as parameters**
handles supported runtime scalar/vector inputs atomically; structural IDs,
filters and connected inputs cannot be exposed this way.

### 4.6 Sub-adaptors

An adaptor that is too large for one window may declare `subsets` in
`studio.json`: `[{"id": "filters", "operations": [...]}, ...]`. The new-instance
dialog offers each subset and "all". A subset restricts palette, completion and
snippets only; the document version and execution are unchanged.

## 5. Server

`console_server.py` keeps loopback binding, token, Host/Origin checks, CSP and
the one-MiB body limit. Changes:

- Static files come from `studio_ui/` and may use subdirectories (resolved and
  confined; only `.html .mjs .css .svg .json` served).
- `/api/state` returns a light summary (documents list with name, provider,
  revision; busy; jobs) without document bodies, and never waits for a native job:
  it reads a snapshot published after each mutation.
- Document bodies are fetched per document: `/api/document?id=` (source, parsed
  document, diagnostics, revision, undo/redo counts).
- Every mutation names its document explicitly (`document`, `revision`); the
  server activates it under the session lock. Windows on different documents can
  be open at once.

New endpoints (all JSON, token-protected):

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/adaptors` | Registered adaptors, routes, console/viewer capabilities, studio.json summaries |
| GET | `/api/schema?version=` | Authored JSON Schema for one document version (cached by catalogue revision) |
| POST | `/api/capabilities` | `browse`, `search`, `describe`, `schema` pass-through to `CapabilityCatalogue` |
| POST | `/api/documents` | `new` (name, provider, from template/snippet), `activate`, `rename`, `close`, `duplicate` |
| GET | `/api/document?id=` | Body, source, diagnostics, revision |
| POST | `/api/authoring` | Existing actions plus `validate_source` (diagnostics without saving) |
| POST | `/api/design` | v2 actions: `create`, `add_operation`, `remove_operation`, `rename_operation`, `duplicate_operation`, `set_ports`, `connect`, `disconnect`, `move` (layout), `configure_loop`, `expose_parameter`, `expose_unfilled`, `set_parameters`, `set_outputs`, `set_naming`, `compile`, `export_template` |
| GET | `/api/studio/adaptor?id=` | Validated v2 templates, categories, fields and snippets |
| GET | `/api/functions` | Pure function declarations and analytic names for fill pickers |
| POST | `/api/settings` | `read`, `write` (scoped by role) |
| POST | `/api/cases` | `inspect_template`, `bind`, `plan`, `run` (job), `outputs` |
| GET | `/api/jobs/{id}` | Job snapshot (unchanged) |
| GET | `/api/file?path=` | Read a run artifact for viewers, confined to the workspace and run directories |

## 6. Frontend

Dependency-free ES modules, no build step, served under a strict CSP. This keeps
the host dependency-free and offline. The discipline that the old console lacked
is enforced by structure and review:

```text
studio_ui/
  index.html            shell only
  styles/               tokens.css (light + dark), base.css, components.css, windows/*.css
  lib/                  dom.mjs (h()), store.mjs, api.mjs, events.mjs, keys.mjs, format.mjs
  shell/                app.mjs, layout (rail, tabs, panels), palette.mjs (Ctrl+K),
                        notify.mjs (toasts + Problems panel), dialog.mjs, menu.mjs
  editor/               json-lexer.mjs, json-parse.mjs (tolerant, pointer↔offset map),
                        schema.mjs (completion/hover/validation from JSON Schema),
                        editor.mjs (textarea + highlight overlay, completion popup,
                        ghost preview), snippets.mjs
  viewers/              viewer3d.mjs (+geometry.mjs from the old console), image.mjs
                        (pan/zoom/pick), text.mjs (search/regex/grep → table), table.mjs
  windows/              start.mjs, designer/*.mjs, workbench/*.mjs, runner/*.mjs,
                        schema-editor.mjs, settings.mjs, setup.mjs
  tests/                node --test unit tests; browser smoke tests via CDP
```

Rules for this code:

- Readable formatting: one statement per line, no line over 120 characters,
  no minified rule sets. Modules under ~400 lines; split otherwise.
- `h(tag, props, ...children)` builds DOM; no `innerHTML` with data.
- One store per window plus one app store; components subscribe and re-render
  their own subtree. No module-level mutable globals beyond the store.
- All colours, spacing, radii and font sizes come from `tokens.css`. Base font
  14px, minimum 12px. Light and dark themes (`prefers-color-scheme`, override in
  Settings).
- Diagnostics while typing stay inside the editor and settle by edit region.
  Explicit actions flush them and publish one summary toast with individual
  actionable Problems entries. Background validation is parse-gated and versioned.
  Other API faults retain the shell toast and Problems reporting path.
- Long operations show progress in the Jobs panel; the UI never blocks.
- Keyboard: Ctrl+K command palette, Ctrl+S save, Ctrl+Z/Y undo/redo, Delete removes
  selection in the canvas, F fits the view.

### 6.1 Shell layout

```text
┌ top bar: Schemaxis · workspace · [role: dev ▾] · search/palette · jobs · ⚙ ┐
├ rail ┬ tabs: [Start] [Designer: spoiler-study] [Workbench: cad] [Schema…]  ┤
│ ⌂    │                                                                    │
│ ⇄    │                     active window                                  │
│ ▣    │                                                                    │
│ ▶    │                                                                    │
│ {}   ├────────────────────────────────────────────────────────────────────┤
│ ⚙    │ bottom panel (collapsible): Problems · Jobs · Log · Console        │
└──────┴────────────────────────────────────────────────────────────────────┘
```

### 6.2 Workflow Designer

Left: **Adaptor palette** — search by name, purpose, operation, input or output
data kind (capabilities `search`), browse by application. Drag onto canvas or
double-click to add an instance (opens the New Instance dialog: instance ID,
subset, starter template).

Centre: **canvas** — pan (drag background / middle mouse), zoom (wheel, to cursor),
fit (F), drag nodes, marquee select. Nodes show application, instance ID, status
and port lists; input ports on the left, output ports on the right, coloured by
data kind. Drag output → input to connect; incompatible ports are dimmed while
dragging. Edges are curves; loop members and edges are orange. A minimap appears
when the graph exceeds the view.

Right: **Inspector** — for a node: identity, adaptor, ports (add/edit/remove),
exposed parameters, "Open in Workbench"; for an edge: endpoints and data kind;
for a loop: controller settings; for nothing: design summary and validation.

Bottom tabs: **Parameters** (table of template parameters), **Outputs** (named
outputs and naming pattern with live preview), **Source** (design JSON in the
editor), **Sample data** (attach a file to an output port to test downstream
text/grep and table views before any app runs).

### 6.3 Adaptor Workbench

Header: application, instance ID, document version, subset, native status
(configured / live / unavailable), actions (Validate, Preview, Run, Save).
Left: **Outline** (document nodes, selectable) and **Templates & Snippets**
(hover previews ghost text in the editor; Enter inserts). Centre tabs:
**Input** (JSON editor with schema completion), **Schema** (browsable schema of
the selected node), **3D**, **Image**, **Table**, **Text** — only the viewers the
adaptor declares. Right: **Properties** form for the selected node, generated
from the schema, and **References** (chips from viewer picks).

### 6.4 Schema Editor

Pick one or more document versions (adaptors). The editor validates and completes
against the matching schema of each document's `version`; for a workflow, each
operation's nested document uses its own adaptor schema. Open/save local files.

### 6.5 Case Runner

Choose a template bundle (directory). A form is generated from its parameters
(kind, units, constraints, help). Run options: output directory, parallel workers,
image size and accuracy when the template exposes them. Load/save a case file.
**Plan** shows the operations and expected outputs without starting applications;
**Run** starts a job; progress shows each operation's state on a read-only
diagram; **Outputs** shows named outputs with the matching viewer.

## 7. Case file run options

`schemaxis.workflow-values/1` gains an optional `run` object:
`{"outputDirectory": "...", "workers": 2, "naming": {"pattern": "...", "indexWidth": 6}}`.
Global presentation options such as image size or accuracy are ordinary template
parameters (the dev exposes them), so they stay validated and bound by the same
contract.

## 8. Milestones

| ID | Scope | Exit check |
| --- | --- | --- |
| S1 | Architecture; Studio shell (rail, tabs, panels, palette, toasts/Problems, themes, roles); light state; documents API; Start and Settings windows; old console UI removed | Host tests; browser smoke; screenshots in both themes |
| S2 | JSON editor (highlighting, tolerant parse, schema completion with toggle, diagnostics, ghost preview); `/api/schema`; Schema Editor window | Editor unit tests on real adaptor schemas; browser test |
| S3 | Workflow design v2 (ports, layout, parameters, outputs, naming, export) with migration; Designer canvas, palette and inspector | Python contract tests; browser test of connect/loop/export |
| S4 | Adaptor Workbench; studio.json snippets/templates for ParaView, FreeCAD, Blender, Gmsh, Calc; viewers (3D, image, table, text/grep) with reference chips | Starter templates plan; viewer unit tests; browser test |
| S5 | Case Runner; case run options; output naming view | Bind/plan/run with a host fixture; naming tests; native ParaView run |
| S6 | Fixed-point/relaxation loop execution; sub-adaptor subsets; text extraction operations | Separate design review first |

Each milestone is committed when its exit checks pass.
