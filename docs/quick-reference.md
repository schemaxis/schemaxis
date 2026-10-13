# Quick reference

Start with the [ten-minute walkthrough](getting-started.md), then the
[user’s guide](user-guide.md). For the full language and option
catalogues, see [JSON input format](json-input.md) and [schemas](schema-guide.md).

Run from the repository root with `export PYTHONPATH=src`, or install with `pip install .`.
All output directories must be new; their parents must already exist.

| Task | Command |
| --- | --- |
| Discover providers and GPU render options | `python3 -m schemaxis discover` |
| Export all Schemaxis input formats | `python3 -m schemaxis schema --all` |
| Refresh generated schemas and option references | `python3 -m schemaxis reference` |
| Check generated references are current | `python3 -m schemaxis reference --check` |
| Export provider authored schema | `python3 -m schemaxis schema --provider paraview --authored` |
| Export expanded pipeline schema | `python3 -m schemaxis schema --provider paraview --expanded` |
| List ParaView operations | `python3 -m schemaxis describe` |
| Describe one ParaView operation | `python3 -m schemaxis describe extractSubset` |
| List Blender operations | `python3 -m schemaxis describe --provider blender` |
| Describe one Blender operation | `python3 -m schemaxis describe boolean --provider blender` |
| List FreeCAD operations | `python3 -m schemaxis describe --provider freecad` |
| Plan a CAD example without FreeCAD | `python3 -m schemaxis plan examples/schemaxis/freecad-bracket.json` |
| Validate and expand without native apps | `python3 -m schemaxis plan INPUT.json` |
| Execute ParaView | `python3 -m schemaxis run INPUT.json --paraview-root /path/to/ParaView --output-directory RUN` |
| Execute Blender | `python3 -m schemaxis run INPUT.json --blender /path/to/blender --output-directory RUN` |
| Execute FreeCAD | `python3 -m schemaxis run INPUT.json --freecad /path/to/freecadcmd --output-directory RUN` |
| Execute Godot | `python3 -m schemaxis run INPUT.json --godot /path/to/godot --output-directory RUN` |
| Execute Aseprite | `python3 -m schemaxis run INPUT.json --aseprite /path/to/aseprite --output-directory RUN` |
| Terminal console | `python3 -m schemaxis console --workspace .schemaxis` |
| Visual console | `python3 -m schemaxis console --workspace .schemaxis --web` |
| Discover input requirements | `python3 -m schemaxis query INPUT.json` |
| Recheck retained evidence | `python3 -m schemaxis verify RUN` |
| Observe a selected node | `python3 -m schemaxis inspect INPUT.json --node NODE --visit 0 --output-directory RUN --blender /path/to/blender` |
| Host tests | `PYTHONPATH=src python3 -m unittest discover -s tests/unit -q` |

Versions: `schemaxis/1` (ParaView), `schemaxis.blender/1` (Blender),
`schemaxis.blender.render/1` (saved-scene rendering), `schemaxis.freecad/1` (CAD),
`schemaxis.freecad.assembly/1` (fixed assemblies), `schemaxis.godot/1`,
`schemaxis.aseprite/1`, `schemaxis.ffmpeg/1`, `schemaxis.qgis/1`,
and `schemaxis.workflow/1` (application operations).
Workflows currently accept ParaView, Blender, saved-scene rendering and FreeCAD
solids, Godot, Aseprite, FFmpeg and QGIS. Assemblies remain standalone and
nested workflows are unsupported.
Native applications run in separate processes; discovery and planning do not
require them to be installed.

Start with `examples/schemaxis/source-coverage.json`, `blender-gallery.json`,
`blender-showcase.json`, or `paraview-to-blender.json`.
The gallery requests OPTIX; use `"render":{"device":"CPU"}` on a machine without it.

Expressions: `$axis` selects an iteration value; `$observe` and `$sample` read
upstream results; `$call` calls the typed functions listed by `schemaxis functions`. `$expr` performs
authored document composition/arithmetic before planning.
Copy their exact shapes from the examples and declarations rather than guessing.
These expressions are not universal: Godot, Aseprite, FFmpeg, QGIS and saved-scene rendering
accept literal inputs. See the user’s guide for the per-format support table.

In the console, `help` lists commands; `configure PROVIDER /absolute/path`
enables batch execution. `live /absolute/path` starts the active FreeCAD,
Blender or ParaView live worker. `preview` without either configuration only
plans—it does not create native geometry. In the visual companion, click native
geometry or image pixels while writing to insert reference chips; type `@` to
reuse current references. **Save request records intent, not a model edit.**
See [terminal console](console.md) and [visual console](visual-console.md).
