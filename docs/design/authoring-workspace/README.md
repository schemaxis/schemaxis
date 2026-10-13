# Authoring workspace design

Interactive design for the next Schemaxis authoring interface. This is a separate
prototype; production implementation is recorded separately below.

The M1 runtime slice is now implemented separately from this prototype: see
[capability discovery](../../capability-discovery.md) and the
[implementation verification](../../../verification/2026-09-27-capability-discovery.md).
M2's [shared job/resource lifecycle and local agent transport](../../agent-service.md)
now have [native qualification](../../../verification/2026-09-27-agent-service.md).
The first M3 [shared authoring slice](../../shared-authoring.md) is now implemented
in the production console and agent tools. The next [typed inspection slice](../../typed-inspection.md)
adds text/table/series references and trusted production workspace presets.
[Workflow study](../../workflow-authoring.md) now supplies operation/artifact
graphs and validated handoff edits. Broader agent evaluation and reusable selectors
remain open.

The [revised architecture](architecture.md) treats AI-driven capability discovery
and reusable human-authored workflows as equal purposes. Its [delivery plan](delivery-plan.md)
starts with the shared capability protocol and an agent execution loop, then
develops typed inspection for geometry, text/log extraction, tables and plots.
The [workspace catalogue](workspaces.md) defines reusable panels and task-oriented
arrangements, including workflow diagrams, UML/class views and concept maps.
The existing CAD screen is an initial interaction study, not the complete GUI
architecture or a demonstration of the proposed headless agent protocol.

Open [index.html](index.html) in a browser, or serve this directory locally:

```bash
python3 -m http.server 8766 --bind 127.0.0.1 --directory docs/design/authoring-workspace
```

Then open `http://127.0.0.1:8766`. Stop the server with Ctrl+C.

Try these flows:

1. Change **Bend radius** in Properties; observe the JSON update. Use **Preview
   design** to refresh the illustrative geometry, then **Undo**.
2. **Pick inlet**, name the selection and **Add extension to draft**. Inspect the
   four added features and their source. Export the authored input if wanted.
3. Choose **Source**, introduce invalid JSON, and inspect the draft error. **Undo**
   restores usable source. YAML is a read-only export preview in this prototype.
4. Open **Add operation** for snippets generated from current FreeCAD declarations.
   Browse the adaptor selector by a functionality keyword such as `CFD` or `1D`.
5. Open **Assistant**, show the example suggestion and apply its reviewed change.
   The suggestion is scripted; no AI service receives data.
6. Explore **Set up workspace** for the functionality/application/AI sequence.
   Preferences are illustrative and no applications are installed.

The canvas is an illustration, not native tessellation. Local draft checks do not
replace Schemaxis planning. Only JSON edits, property changes, history, bounded
snippet insertion and exports act on real in-tab document data. Nothing persists
across reload except files the user explicitly exports.

See [architecture and acceptance criteria](architecture.md) for the shared editing
service, document lifecycle, JSON/YAML policy, selection design, AI boundary,
installer scope and implementation sequence. [Verification notes](verification.md)
record checks performed on this design.
