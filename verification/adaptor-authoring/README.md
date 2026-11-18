# Adaptor authoring coverage

Copyright (C) 2026 David L. F. Gaden.

This directory holds the reproducible coverage inventory for the universal
authoring rollout described in [TODO.md](../../TODO.md) entry 3. It tracks
suggested Names for new instances, multi-mode and subset selection across all
built-in adaptor routes. It also records earlier evidence on changing saved
Names. The general reference-aware renaming rollout is deferred.

| File | Origin |
| --- | --- |
| `inventory.json` | Generated rows; never edited by hand. |
| `summary.md` | Generated human-readable totals, routes, commands and gaps. |
| `ledger.json` | Hand-maintained judged statuses, validated on every build. |
| [02-core-identity-preview.md](02-core-identity-preview.md) | Bounded core preview evidence and required follow-ups. |
| [04-durable-identity.md](04-durable-identity.md) | Accepted bounded durable Console history and resident graph identity support; host/native evidence and remaining scope. |
| [03-resident-live-data-identity.md](03-resident-live-data-identity.md) | Resident Live Data identity views: host and bounded native evidence, unqualified domains. |
| [05-resident-plan-transitions.md](05-resident-plan-transitions.md) | Accepted bounded ordinary resident transitions, failure ownership and serial Data/Graph evidence; host bridge remains required. |
| [06-preserving-data-host.md](06-preserving-data-host.md) | Accepted bounded public Live Data preserving host/wire support, exact old-window measurements and bounded native evidence. |
| [root-replacement-disclosure.md](root-replacement-disclosure.md) | Shared review of library requests that replace the whole input; reconciled routes and bounded host/browser checks. |
| [rollout-qualification.md](rollout-qualification.md) | Representative Workbench and native checks, with the inherited host failures and strict admission review. |

Read Name and multi-mode totals on the owning item rows. The field surfaces
retain schema addresses for controls, references and values. Subset choices
are counted on those field surfaces. The seven route gaps document the shared
Designer surfaces and the template contracts that have no literal Add schema.

```sh
PYTHONPATH=src python3 tools/inventory_adaptor_authoring.py            # regenerate
PYTHONPATH=src python3 tools/inventory_adaptor_authoring.py --check    # fail when stale
PYTHONPATH=src python3 tools/inventory_adaptor_authoring.py --external PATH
PYTHONPATH=src python3 -m unittest tests.unit.test_adaptor_authoring_inventory
```

The tracked inventory is built with plugins disabled for the generator process
only, so it is identical on every checkout. `--external PATH` (or
`--external=PATH`) writes installed external plugins to a separate file as owner
handoffs; it refuses to run when `SCHEMAXIS_ADAPTOR_PLUGINS` disables plugins,
and it cannot be combined with `--check`. Option abbreviations are refused.
Uninstalled plugins are not covered.

## Requirements the generator enforces

- **Complete denominator.** Every registered built-in adaptor and route (primary
  and secondary), the shared Studio workflow and workflow-design routes, and the
  workflow template and values contracts. Every schema address appears exactly
  once, owned by the nearest item. Declared operations missing from the Add
  catalogue, duplicate catalogue ids, stale guidance and failed projections are
  explicit gaps rather than omissions.
- **Authorable units.** Rows exist for catalogue operations and document items,
  definitions, nested collection members, map entries, discriminated variants
  (for example individual Blender shader-node kinds), declared native commands,
  workflow-design operation instances and validator-backed template/values units.
  A parent's singleton or not-applicable status never covers its nested units.
- **Four independent dimensions.** Naming, renaming, multi-mode and subset each
  carry separate assessment, implementation, review and native-qualification
  statuses on every item and every field-level surface. Derived statuses state a
  declaration or structural fact with its basis; anything else stays unassessed,
  unknown, not reviewed and not qualified.
- **Authoring surfaces.** Each item records Studio Add, Edit, Properties, quick
  rows, Batch actions, core, CLI, console and AI states. Only facts proven by
  code are projected or not-projected; the rest stay unassessed.
- **Semantic drift.** Each field row fingerprints its own validation keywords;
  items fingerprint declarations, catalogue entries and guidance authoring
  records; routes fingerprint schema and declarations; contract routes
  fingerprint their validators and the complete normalized template module, so
  helper functions and constants count too. Only schema annotations in keyword
  position (`description`, `title`, `$comment` and Studio guide annotations) and
  catalogue display prose are excluded. Literal `default`, `const` and `enum`
  values, property names and declaration contents are fingerprinted verbatim,
  whatever their member names. Each field's guidance `control`, `authoring` and
  `fileExtensions` records are part of that field's contract, including records
  on `$defs` definitions, and items list their fields' control and authoring
  records verbatim. Field guidance drifts only through its status, control,
  authoring and fileExtensions; its explanation, label, units, default meaning,
  pitfalls, examples, sources and question are documentation and do not drift. Identity constraints and input-port multiplicity
  are kept readable on their surfaces. Admitted identity/reference policy data,
  its exact route binding and generated port projection are fingerprinted on
  routes and applicable items. Policy presence alone earns no implementation,
  review or native qualification credit.
- **Route-scoped credit.** A ledger record that claims implementation or native
  qualification must list the exact route versions it applies to; credit is
  never carried between document versions.
- **Host-only discovery.** Run as a script, the generator blocks native
  application imports before any framework or plugin module loads and fails if
  one is attempted or already loaded.
- **One command-line parse.** The arguments are parsed once with argparse,
  before any framework import, and that parse alone selects the plugin policy.

## Regression cases

`tests/unit/test_adaptor_authoring_inventory.py` covers, among others:

- registry, declaration, Add catalogue and schema-address reconciliation;
- same-address mutations of identity patterns, command enums, bounds, defaults
  and enum choices, plus port multiplicity and command renames, each producing
  drift, while a prose-only change does not;
- identity policy selector, name constraint and reference-shape changes
  producing item and route drift without automatic implementation credit;
- one row per declared native command across all providers, reconciled with
  the `onVisit` schema enumeration;
- nested Blender production collections, material graphs and shader-node
  variants as independent unassessed rows;
- all four dimensions independently recordable on surfaces and nested units;
- template and values units, fields and gaps, and drift when validator keys,
  validator bodies, validator call sites, helper regular expressions or module
  constants change;
- guidance control targets changed with the same control kind (line
  endpoints, blocks input port, reader field, including the real ParaView
  `foam` regions control), field authoring and file-extension records, each
  producing drift, while explanation-only guidance edits do not;
- literal `default`, `const` and `enum` objects whose members are named
  `label`, `units`, `title` or `description`, schema properties and declaration
  options or inputs with such names, each producing drift, while annotation-only
  rewording does not;
- refusal of unscoped or cross-route ledger credit, and a behavioural check
  that each cited entry point accepts only the routes it is credited for;
- the CLI native-import blocker against a plugin that imports a native module
  during loading, and against native modules loaded before discovery;
- `--external PATH` and `--external=PATH` admitting the same installed fixture
  plugin with byte-identical output, refusal of abbreviations, of `--check`
  combined with `--external`, and of `--external` with plugins disabled, all
  without changing the tracked artifacts.

## Resolved review findings

| Finding | Resolution |
| --- | --- |
| Same-address semantic changes (identity pattern, command name) produced an identical inventory. | Field, item, route and contract fingerprints; readable identity constraints and ports. |
| Nested named collections were aggregated under their parent; field surfaces allowed one dimension. | Nested member, entry and variant rows; four-dimension records on every surface; explicit authoring-surface states. |
| Workflow template and values contracts were absent. | Validator-backed rows derived from closed-key calls, with no-literal-schema and no-catalogue gaps and source fingerprints. |
| Declared native commands had no rows. | One row per command with declaration evidence, schema reconciliation and unknown dimensions. |
| Workflow operation renaming credit was attached to the wrong route. | Standalone workflow/1 is not implemented; partial credit is scoped to workflow-design/2 with a behavioural entry-point test. |
| The CLI native-import check started after framework imports. | A blocker installed before any framework import, with plugin-injection regression tests. |
| A raw `--external` token check decided the plugin policy, so `--external=PATH` disabled plugins and wrote an empty handoff. | One argparse parse before framework imports, abbreviations disabled, `--check` and `--external` mutually exclusive, explicit refusal when plugins are disabled. |
| Template helper regular expressions and constants (`_SCOPES`, `_KINDS`) could change without drift. | The complete normalized template module AST is fingerprinted on every template and values route and unit. |
| Recursive prose filtering deleted literal members named like prose (`label`, `units`, …) from defaults, constants, enumerations and declarations. | Prose removal only at schema-keyword positions and in catalogue display fields; literal payloads and declarations are fingerprinted verbatim. |
| A field's guidance control target (for example the `foam` regions reader field) could change without drift; only the control kind was recorded. | Field contracts include the verbatim control, authoring and fileExtensions records; routes carry a guidance contract and items list the records. |

## Limits

The template module fingerprint is deliberately conservative: any change to
`workflow_templates.py`, including comments-free refactors that alter its syntax
tree, requires regeneration and a fresh look at the contract rows.

Structural surface kinds and nested units say that a unit exists, not that it
needs a Name, multi-mode or a subset control. Template and values contracts have
no literal schema; their rows come from validator call sites and can only be as
complete as those validators. None of these rows is native qualification.

- [Shotcut owner-local identity preview](shotcut-local-identity.md) covers the
  asset target and each ordered clip consumer within its timeline.
