# Studio starter: sample and scale

This small workflow generates a table in GNU Octave, verifies it, then passes its
CSV publication to a second Octave operation that scales the y values. It uses
three parameters, and every parameter changes the executed input:

| Parameter | Effect | Default |
| --- | --- | --- |
| `stop` | Inclusive upper endpoint of the sequence, beginning at zero | 4 |
| `count` | Number of sample rows, including both endpoints | 5 |
| `factor` | Multiplier applied to y in the second operation; x is preserved | 2 |

The [sequence-study](sequence-study) directory contains an editable
[design](sequence-study/design.json), a [template manifest](sequence-study/template.json),
the compiled [workflow](sequence-study/workflow.json), and two cases:
[example](sequence-study/cases/example.json) and [dense](sequence-study/cases/dense.json).
The dense case uses nine rows, an endpoint of 6.5 and a factor of 1.5.

## Check it without native applications

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 examples/studio/check.py
PYTHONPATH=src python3 -m schemaxis template plan \
  examples/studio/sequence-study/template.json \
  --values examples/studio/sequence-study/cases/dense.json
```

The checker validates the design, confirms that its compiled workflow matches the
bundle, binds both exact template identities, checks the three effective inputs,
and reproduces the bundle by exporting the design into a temporary directory.
It also checks the output-name previews. It prohibits native process launch.
The second operation's native plan remains deferred until its producer has
published a verified CSV; a host plan is not a completed run.

## Open the design in Studio

From the repository root:

```bash
PYTHONPATH=src python3 -m schemaxis console \
  --provider workflow-design --workspace .schemaxis/studio \
  --command 'open examples/studio/sequence-study/design.json' --web
```

Open the printed loopback URL, including its token. In **Start**, select the
recent design. The **Developer** role exposes **Workflow Designer**, **Adaptor
Workbench**, **Schema Editor** and **Case Runner**. Reuse the same workspace to
recover saved drafts; opening Studio itself does not start Octave.

1. In **Workflow Designer**, inspect `samples.table → scaled.source`. These are
   named artifact ports with CSV/table metadata. Each operation also declares a
   statistics output. Drag the boxes or press **F** to fit; layout is presentation
   data and does not change the template identity. The named connection describes
   an existing `$artifact` handoff in the workflow source. If experimenting with
   disconnection, edit that underlying source reference as well.
2. Select an operation and open its **Adaptor Workbench**. The **Input** tab shows
   the operation's JSON; **Schema** and **Properties** help inspect declared
   options. The three exposed values use workflow-scoped `$document` references.
   **Save** on this nested Workbench writes back to the parent design. Use **Case
   Runner** for the complete workflow; an isolated operation with workflow
   references is not a bound case.
3. In the Designer's **Parameters** tab, inspect the labels, defaults, ranges and
   targets. **Outputs** contains four aliases and the naming pattern
   `{index}-{operation}-{output}-gain_{param:factor}{ext}`, with four index digits.
   These declarations are already present in the supplied design.
4. Choose **Export template** and a new or empty directory, such as
   `.schemaxis/studio/templates/my-sequence` resolved from the repository root.
   Keep the exported paths shown by the dialog. Export writes `template.json`,
   `workflow.json` and `cases/example.json`; it does not overwrite a bundle.
5. Open **Case Runner**, enter that exported directory and click **Inspect
   template**. Load its `cases/example.json` using the absolute path shown at
   export. Loading the case carries the design's output naming preferences;
   inspecting the template alone uses the Studio naming defaults.
6. Change the values and click **Plan**. To retain an edited case, choose a new
   filename inside the Studio workspace, such as `cases/my-sequence.json`, and
   **Save case**. Relative Runner paths are resolved inside that workspace, not
   inside this example directory. Existing cases must first be loaded before
   they can be overwritten; external edits cause a conflict.
7. To execute, switch to **Admin**, open **Application Setup** through **Ctrl+K**,
   and locate the GNU Octave executable. **Save location** records it for this
   workspace. A located executable has not yet passed a native run. Return to
   **Developer** or **User**, then click **Run** in the Runner.
8. The job executes `samples`, verifies its CSV, then executes `scaled`. Successful
   completion produces four publications: two CSV tables and two JSON statistics
   files. Select a named output for the Table or Text viewer. A default case name
   includes `0001-samples-samples-gain_2.csv`; the exact paths appear in the UI.

The prebuilt bundle can also be used directly: enter its absolute directory in
Case Runner and load either supplied case. Leave the output directory blank for
a fresh workspace run directory. The dense case permits two workers, but its
producer/consumer dependency still orders the two operations.

## Editing and evidence boundaries

Designer canvas edits persist to the workspace automatically. Its **Source** tab
uses **Apply source** for an explicit revision-checked edit. For a standalone
file, **Schema Editor → Open JSON → Save draft** creates a workspace document;
**Export JSON** downloads the current text and does not silently rewrite the
original file. Closing a tab does not delete the saved workspace document.

Sample attachments in **Sample data** stay in that window. They support text,
grep and table exploration without replacing workflow inputs or entering an
exported template. Workbench viewer picks create inspectable, removable chips;
a pixel, table cell or tessellated triangle is not automatically a native CAD
selection or a universally usable workflow reference.

Case identity includes the template ID, revision and digest. Editing the template
or compiled workflow requires a matching newly exported case. Runs retain native
receipts and their bound authored input; post-verification naming adds a `named/`
view without renaming those native publications. A naming failure is reported
separately from native verification.

Closed feedback loops can be drawn and configured, but cannot be compiled or
executed here. Native loop execution remains S6 work requiring a separate design
review. See the [Studio guide](../../docs/visual-console.md) for security, save
behaviour, viewer limits and the rest of the interface.
