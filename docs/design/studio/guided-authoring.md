# Guided authoring: calm diagnostics, snippet library, fill-in values

Status: design, 2026-10-05.
Milestone **S2b**, which comes before S6. It extends `architecture.md` §4.5, §6.3 and §6.4,
and supersedes `studio.json` version 1.

## 1. Requirements

1. **Fill in an input file according to its schema**, not only free-typing JSON.
2. **Calm warnings.** The bottom message currently complains at every keystroke.
   Ignore states the user is clearly about to fix: a trailing comma, a key without
   a value yet, an unfinished string. Report a syntax problem only when it will
   not disappear in the next few keystrokes.
3. **Snippet buttons.**
   - Rows of category buttons, each with an icon, text, or both. Clicking a
     category opens its snippets.
   - Around 100 sensible snippets per major adaptor, grouped by category.
   - "Big-picture" snippets as well as simple ones, for example "X, Y and Z slice
     arrays through the data volume" for ParaView.
4. **Insertion.**
   - A snippet goes in at the cursor, or intelligently on the next line or in the
     right collection.
   - Values still to fill are clearly highlighted, and the cursor visits each
     required value in turn.
   - For each value the user can type it, choose an expression (`$value`,
     `$document`, `$analytic`, `$axis`, `$expr`, and so on), or leave it for later.
   - A value left for later stays visibly marked as an unset variable.
5. **Templates** that create ready-made files with values still missing.
   Templates or snippets should be offered at every step: document, section and
   value.

## 2. Calm diagnostics

Studio must never nag while someone is mid-thought. Explicit actions (Validate,
Save, Preview, Run, Export, changing tabs) always show everything.

### 2.1 Classify

Every diagnostic carries a `source` and a `settle` class:

- `source` is one of `syntax` (tolerant parser), `schema` (client schema
  validation), `server` (`/api/validate`, plan) or `fill` (unfilled values, §4).
- `settle` is one of:
  - `transient`: a syntax state that typing usually completes;
  - `local`: a problem inside the object being edited;
  - `stable`: anything else.

### 2.2 The active edit region

The active edit region is the token containing the caret, the token immediately
before it, and the innermost object or array being edited. These count as
**transient** when they touch that region:

- a trailing comma before `}` or `]`;
- a key with no colon or value yet (`"origin"` or `"origin":`), and an empty value
  after a colon;
- an unterminated string or number (`1.`, `-`, `1e`);
- a missing comma between the current line and the next item;
- an unclosed bracket or brace while auto-close is pending;
- a duplicate key while the key is still being typed.

Required-key and type complaints inside the object being edited are **local**.

### 2.3 When to show

| Class | Inline squiggle | Editor footer count | Problems panel / toast |
| --- | --- | --- | --- |
| transient | after the caret leaves the region **and** 1.5 s idle, or on blur | same | never from typing |
| local | when the caret leaves that object, or 1.5 s idle | same | never from typing |
| stable | after 600 ms idle | yes | never from typing |
| any, after an explicit action | immediately | yes | yes, one grouped entry per action, not one toast per diagnostic |

- **Server validation while typing** is debounced (1 s), runs only when the source
  parses, and is suppressed while a transient syntax state exists.
- **Stale results:** results for an older text version are discarded.
- **Toasts:** `actions.mjs` currently raises one error toast per diagnostic. Replace
  this with one summary toast ("3 problems — see Problems") plus the Problems
  entries.
- **Status line:** the bottom message reflects the settled state only, and says
  calmly "Editing…" while transient states are suppressed.

Find the exact producer of the repeated bottom message by reproducing it (type
`{"nodes": [` in a Workbench). Candidates are the editor footer, the
`/api/authoring` source-retention diagnostics, and Workbench/Schema Editor status
text. Fix it at its source.

### 2.4 Tests

The pure "settle" classifier lives in a module with `node --test` cases for every
bullet in §2.2. A browser test types a realistic sequence character by character
and asserts that no squiggle, toast or Problems entry appears until the text is
genuinely wrong and has settled.

## 3. Snippet and template library: `schemaxis.studio-adaptor/2`

`adaptors/<id>/studio.json` becomes version 2. Version 1 is migrated by the server
loader.

```json
{
  "version": "schemaxis.studio-adaptor/2",
  "categories": [
    {"id": "slicing", "title": "Slicing & clipping", "icon": "slice", "description": "…"}
  ],
  "templates": [
    {"id": "cfd-overview", "title": "CFD overview report", "description": "…",
     "file": "studio/templates/cfd-overview.json", "fields": {"…": {}}}
  ],
  "snippets": [
    {
      "id": "xyz-slice-arrays",
      "category": "slicing",
      "title": "X, Y and Z slice arrays through the data volume",
      "icon": "slice-xyz",
      "description": "Evenly spaced slices along each axis, bounded by the source's observed bounds.",
      "complexity": "composite",
      "fields": {
        "source": {"label": "Data source", "type": "nodeRef", "required": true},
        "count": {"label": "Slices per axis", "type": "integer", "default": 5, "minimum": 1, "maximum": 50},
        "prefix": {"label": "ID prefix", "type": "id", "default": "slice"}
      },
      "inserts": [
        {"at": "/axes/-", "values": ["…"]},
        {"at": "/nodes/-", "values": ["…"]},
        {"at": "/scenes/0/visible", "merge": {"…": {}}}
      ]
    }
  ],
  "viewers": ["3d", "image"],
  "subsets": []
}
```

### 3.1 Placeholders

The library's bodies use the **field marker** `{"$fill": "fieldId"}` anywhere a
value is needed. String interpolation of a field inside a longer string
(`"${prefix}X"`) is allowed only for `id`-type fields. On insertion, the field
markers are written into the document as `{"$fill": "fieldId", "label": "…",
"type": "…"}`. This is valid JSON, visible in plain text, survives save/reload, and
is what "left for later" means.

### 3.2 Field types

`number`, `integer`, `boolean`, `string`, `enum` (with `values`), `vector3`,
`bounds`, `colour`, `path` (file, with `extensions`), `id` (auto-uniquified against
existing IDs in its collection), `nodeRef` (choose an existing node ID; filter by
`acceptsKinds` where the adaptor declares port kinds), `axisRef`, `field` (a data
array name; offer names from the last native observation when one exists), `json`.

### 3.3 Placement

- Each insert names a target pointer.
- `/-` appends to an array. A caret inside a compatible array inserts after the
  item containing the caret.
- `merge` deep-merges an object, with conflicts shown in the preview.
- `"at": "@cursor"` inserts a value at the caret's value position. This is used by
  value-level snippets.
- A missing intermediate container (for example no `axes` yet) is created.
- All inserts of one snippet are **one undo group**.
- The ghost preview (existing `editor-preview.mjs`) shows every insert before
  commit. Off-screen inserts are listed in the popover ("also adds 1 axis, 3 scene
  entries").

### 3.4 Backend contract for unfilled values

- `$fill` is accepted by the Studio editor and the schema completion (§5) as a
  marker wherever a value is allowed.
- `registry.plan`, `/api/validate`, the template binder and the Case Runner refuse
  a document containing `$fill`. They fail with a structured fault
  `UNFILLED_VALUES`, listing every pointer, label and type.
- Saving a draft with `$fill` is allowed: it is retained invalid source, exactly
  like other drafts.
- Exporting a template with `$fill` is refused unless the field is exposed as a
  template parameter.
- Add an "Expose unfilled values as parameters" action to the Designer.
- Tests cover every route.

### 3.5 Catalogue size and quality

The targets are guidance. Usefulness beats count. No snippet may duplicate another
or be trivial noise.

| Adaptor | Snippets | Templates | Example categories |
| --- | --- | --- | --- |
| ParaView | 90–110 | 8–12 | Readers & sources; Selection & extraction; Slicing & clipping; Contours & isosurfaces; Vectors, streamlines & glyphs; Calculators & derived fields (gradients, vorticity, Q criterion); Sampling, probes & lines; Integration & measurements; Time selection; Scenes & appearance; Cameras & orbits; Writers & exports; Sweeps (axes/analytics); CFD recipes (vehicle wake slices, pressure-coefficient surfaces, y⁺ checks, convergence-ready isosurface orbit) |
| Blender | 40–50 | 5 | Primitives; Modifiers; Materials; Lighting; Cameras & render; Import/export; Procedural; Sweeps |
| FreeCAD | 40–50 | 6 | Primitives; Sketches; Features; Booleans; Fillets/chamfers; Semantic selections; Measurements; Design studies; Assemblies; Exports |
| Godot | 20–25 | 4 | Scene; Primitives; Lighting; Sprites; Import |
| Gmsh | 15–20 | 4 | Import; Sizing; Named groups; Quality; Refinement studies |
| Octave | 15–20 | 3 | Sequences; Signal; Statistics; Tables |
| QGIS | 15–20 | 3 | Layers; Reprojection; Buffers & clips; Centroids; Maps |
| Aseprite | 12–15 | 3 | Canvas; Layers; Frames & tags; Drawing |
| ngspice | 12–15 | 4 | Networks; AC; Transients; Exports |
| Cantera | 8–12 | 3 | Properties; Equilibrium; Sweeps |
| Calc | 8–10 | 3 | Tables; Summaries |
| FFmpeg | 6–8 | 2 | Encoding; Sprite sheets |
| Workflow / design | 15–20 | 5 | Operations; Handoffs (`$artifact`, `$value`); Shared dimensions; Studies; Execution |

**Every snippet and template must be tested automatically** by one generated test
over the whole catalogue:

1. Its JSON is valid.
2. It is applied to its declared base document, or to the adaptor's empty
   document, with field defaults or test values substituted.
3. The result host-plans through `registry.plan`, or `workflow.inspect_plan`.
4. With fields left unfilled, the result yields `UNFILLED_VALUES` with the
   expected pointers.

Snippets that need native data (a real case file) declare a `requires` note and
use path fields. They must still plan, which may mean planning with a fixture path.

Verify the semantics against the actual operation declarations
(`schemaxis describe --provider X`) and the examples in `examples/schemaxis/`.
Do not invent options. Where a "big-picture" idea needs something the adaptor
cannot do, leave that snippet out and list it under "wanted" in the report.

## 4. Fill mode

After a snippet or template is inserted, the editor enters **fill mode**.

- **Highlighting:** every `$fill` marker from that insertion gets a
  placeholder-chip background (new tokens `--fill-bg`, `--fill-border`,
  `--fill-required` in both themes). Markers elsewhere in the document show the
  same chip in a quieter style.
- **Navigation:** the caret selects the first required field. Tab and Shift+Tab
  move to the next and previous field. Enter accepts. Esc leaves fill mode, and
  the markers stay.
- **The fill popover** is anchored at the marker. It offers:
  - **Type a value**, validated live against the field type and the schema at that
    pointer.
  - **Choose** from enum values, existing node or axis IDs, or recent values.
  - **An expression:** `$document` (pointer picker over the current document),
    `$value` (function picker with typed arguments), `$axis` (pick or create an
    axis), `$analytic` (linear, values or orbit form), `$expr`, and `$observe`,
    `$sample`, `$calc` and `$call` where that adaptor's schema allows them.
    - Only offer what the schema at that pointer accepts. The authored schemas
      reference `#/$defs/composition` and `#/$defs/analytic`.
    - Add `GET /api/functions` (from `schemaxis functions`) and an analytic type
      list for the pickers.
  - **Leave for later**, which keeps the marker.
- **Status:** a footer badge reads "4 values to fill". Clicking it restarts fill
  mode at the first unfilled marker.
- **Accessibility:** everything works by keyboard alone.

## 5. Schema-driven filling (beyond snippets)

- **Fill required properties:** in the Properties pane and from the completion
  popup, insert every missing required key of the object at the caret as `$fill`
  markers, then enter fill mode.
- **Discriminator follow-up:** after choosing a discriminator value (for example
  `"filter": "slice"`), offer to add that variant's common options as markers.
  The menu shows required options first, then frequently used ones from the
  snippet library.
- **Key completion:** completion inserts `"key": {"$fill": …}` for keys with no
  default, rather than a blank that triggers a syntax complaint.
- **Value completion:** completion offers expression snippets (§4) where the
  schema allows them.

## 6. "Every step of the way"

| Step | Offer |
| --- | --- |
| New document | Template gallery in the New Instance dialog and an empty Workbench: cards with title, description and the fields they will ask for |
| Empty or new section | A "Start this section" strip: the most relevant snippets for the collection the caret is in (`nodes`, `scenes`, `axes`) |
| Anywhere | The category button rows above the editor, in the Workbench Input tab and the Schema Editor |
| A value | Fill popover expressions and value snippets |
| Workflow Designer | An operation-level template picker when adding a node, plus snippets for ports, handoffs and parameters |

## 7. UI specification for the snippet bar

- **Bar:** a wrapping row of category buttons above the editor toolbar, each with
  an icon and a short label. In narrow windows it collapses to icons, with
  tooltips. Add icons to `assets/icons.svg` in the existing stroke style.
- **Category popover:** a grid of snippet buttons (icon, title, one-line
  description). It has a search box, and arrow keys move through it.
- **Preview:** hovering or focusing a snippet ghost-previews it at the computed
  insertion point and lists any off-screen inserts.
- **Inserting:** click or Enter inserts and enters fill mode.
- **Finding snippets:** recently used and favourite snippets come first. Ctrl+K
  also finds snippets by name ("Insert snippet: …").
- **Composite snippets** carry a "composite" badge and say what they add.
- **Quality:** use the existing visual language (tokens only, both themes, at
  least 12px text) and keep code readable. Take screenshots and inspect them.

## 8. Work packages (disjoint ownership)

| Package | Owns |
| --- | --- |
| W1 Calm diagnostics | `editor/settle.mjs` (new); `editor/editor.mjs` diagnostic scheduling; Workbench/Schema Editor status and validate-toast changes; tests |
| W2 Fill mode and expressions | `editor/fill*.mjs` (new), the expression pickers, `$fill` rendering in `highlight.mjs`, the completion changes in `schema-complete.mjs`; `/api/functions` (integrator wires the server); tests |
| W3 Library format and insertion | `studio.json` v2 loader and migration (server side), `editor/insert.mjs` multi-insert/merge/uniquify, the snippet bar and popover UI (`windows/workbench/library.mjs`, the Schema Editor integration), the generated catalogue test harness, and the backend `UNFILLED_VALUES` fault across plan, validate, bind and Runner |
| W4–W6 Content | Snippets and templates: W4 ParaView; W5 FreeCAD, Blender, Godot, Aseprite; W6 Gmsh, Octave, QGIS, ngspice, Cantera, Calc, FFmpeg and workflow. Each owns only its adaptors' `studio.json` and `studio/templates/` |

- **Contract first:** W4–W6 start once W3 has committed the v2 format and the
  catalogue test, so content is validated as it is written. Before that, they may
  draft against this document.
- **Integration:** the integrator owns `studio_server.py`, `shell/app.mjs`,
  `index.html` and `tokens.css`, wires every piece in, runs every check, and
  commits per sub-milestone:
  1. calm diagnostics;
  2. fill mode;
  3. library v2 and the bar;
  4. each content batch.

## 9. Exit checks

- The full Python suite, the Node tests and the browser tests all pass. The
  generated catalogue test covers 100% of snippets and templates.
- **Typing test:** realistic typing produces no premature complaints.
- **Insertion test:** inserting "X, Y and Z slice arrays" into the ParaView
  Workbench highlights its fields, then Tab-fills them:
  - the source is chosen from existing nodes;
  - the count is typed;
  - the prefix is left for later.

  The document then plans once the source and count are filled, and still reports
  `UNFILLED_VALUES` only when `$fill` remains.
- **Template test:** a template creates a new Workbench document, and fill mode
  walks its fields.
- **Screenshots:** the snippet bar, popover, ghost preview, fill mode and the
  calm footer, in light and dark. Inspect them.
- **Records:** add `verification/2026-10-xx-guided-authoring.md` with the exact
  commands and results.
