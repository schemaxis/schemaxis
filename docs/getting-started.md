# Start here: edit, plan, run, verify

Schemaxis turns a JSON description into work in a native application. The command
is `schemaxis`. Start by editing and planning a small example; neither step needs
a native application.

## First ten minutes: a CAD input

Open the repository folder containing `pyproject.toml` in your editor. In a
terminal in that same folder:

```bash
export PYTHONPATH=src
python3 -m schemaxis discover
python3 -m schemaxis describe --provider freecad
python3 -m schemaxis plan examples/schemaxis/freecad-bracket.json
```

`discover` lists the installed adaptors and their operations. `describe` shows
the FreeCAD operations with their options, types and bounds. The example builds
an angle bracket in millimetres:

1. Two `box` nodes, `foot` and `upright`, are joined by `fuse` into `blank`.
2. Four `cylinder` nodes are subtracted from it by a chain of `cut` nodes.
3. `output` names the final solid, `cut3`.

Planning describes this work. It does not start FreeCAD or create a solid.

Copy [the example](../examples/schemaxis/freecad-bracket.json) to a new
`input.json` in the repository root, leaving any existing file intact. Change the
`height` of the `foot` box from `8` to `12`, then run:

```bash
python3 -m schemaxis plan input.json
python3 -m schemaxis describe box --provider freecad
```

Read the resulting plan: it includes the resolved options and the number of
expected publications. Each `id` names a step; `inputs` names the earlier steps it
uses (`base` and `tool` for `fuse` and `cut`); `output` names the final step.

Try changing the `radius` of `drill0` to `0`: the editor should flag the value,
and `plan` rejects it with `INVALID_ARGUMENT` at `$.arguments.radius`. Restore `5`.
Then try changing `output` to `"cut4"`: it is a valid string, so the editor
accepts it, but `plan` rejects it with `INVALID_SELECTION` because no node has
that name. Restore `"cut3"`. This is why both editor checks and planning matter.

## Get completion and validation in your editor

The generated schema already exists. In VS Code, opening this repository as the
workspace loads [.vscode/settings.json](../.vscode/settings.json), which associates
the authored schema with root `input.json`, JSON files under `inputs/`, files
ending in `.schemaxis.json`, and top-level `examples/schemaxis/*.json` examples.

Enter the literal `version` first, then use completion (Ctrl+Space) while editing
keys and values. Schema assistance includes declared options, required fields,
enums and numeric bounds. Complex alternatives can produce broad suggestions;
the provider-specific schema is useful when working with just one application.
Do not add `$schema` to the input itself: Schemaxis currently rejects that root key.

For another workspace or IDE, follow the [editor setup](schema-guide.md#editor-setup).
The generator and refresh commands are in that guide too. No native application
is needed to generate schemas. An editor check does not run the planner or certify
native results.

## Choose your next exercise

| What you want to learn | Start with | Then read |
| --- | --- | --- |
| CAD features and editable solids | [FreeCAD bracket](../examples/schemaxis/freecad-bracket.json) | [FreeCAD examples](freecad-examples.md) |
| CFD/data post-processing | [Branching pipeline](../examples/schemaxis/branching.json) | [ParaView catalogue](paraview-catalogue.md) |
| Meshes, materials and images | [Blender example in the input reference](json-input.md#3-complete-blender-example) | [CAD and mesh workflows](cad-and-mesh-workflows.md) |
| Interactive authoring and visual inspection | [First console session](user-guide.md#first-console-session-without-native-execution) | [Visual console](visual-console.md) |
| Reuse, sweeps and simulation times | [User guide, section 6](user-guide.md#6-reuse-values-vary-parameters-and-select-times) | [JSON input reference](json-input.md) |
| Pass files between applications | [User guide, section 7](user-guide.md#7-connect-jobs-and-run-them-in-parallel) | [Parallel execution](parallel-execution.md) |
| Images to video, or GIS | [Media workflows](media-workflows.md) | [QGIS](qgis.md) |

Examples are templates, with application-specific rules and runtime requirements.
Start with `plan`; configure the appropriate native executable before `run`.

## When you are ready to run

The repeatable cycle is **edit → plan → run → verify → inspect the native output**.
Use a fresh output directory and keep the entire directory afterwards, including
logs and receipts. The [user guide's first batch run](user-guide.md#first-batch-publication)
walks through this using FreeCAD.

`plan` validates intent without starting an application. `run` performs native
work and the adaptor's checks. `verify` rechecks retained evidence; its exact
scope depends on the adaptor. A verified result still needs your engineering
judgement. For FreeCAD, `run` reopens the saved model in a fresh process and checks
the solid, its dimensions and the published STEP/STL files; a later `verify`
rechecks those retained observations and the artifact digests. Neither judges the
suitability of the design.

Use the [user guide](user-guide.md) as the full manual, the
[quick reference](quick-reference.md) for commands, and the generated
[operation references](generated/freecad-operations.md) for exact option names.
