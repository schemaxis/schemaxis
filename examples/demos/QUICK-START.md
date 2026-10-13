# Demonstration quick start

First configure application and case paths using the [CFD guide](../../docs/cfd-guide.md).
Replace all absolute-path placeholders below. `doctor NAME` checks only that demo.

```bash
cd /absolute/path/to/schemaxis
python3 examples/demos/demo.py doctor
```

## Web console

```bash
python3 examples/demos/demo.py console
```

Open the entire printed URL, including its token. In the page's **Command console**,
submit these one at a time, waiting for completion:

```text
open /absolute/path/to/schemaxis/examples/demos/pipe.input.json
live /absolute/bin/freecad
preview
set document dimensions '{"bendRadius":80,"outerRadius":18,"innerRadius":14,"bendAngle":90,"meshDeflection":0.05}'
preview
undo
preview
```

Drag to orbit; scroll to zoom; Fit restores the view. Section Z exposes the bore.
The separate prose composer records intent; it does not execute commands.
Close the server with Ctrl+C in its terminal.

## Batch demonstrations

```bash
python3 examples/demos/demo.py run pipe
python3 examples/demos/demo.py show pipe
python3 examples/demos/demo.py open pipe --app video
python3 examples/demos/demo.py open pipe --app freecad
python3 examples/demos/demo.py open pipe --app blender

python3 examples/demos/demo.py run inspection
python3 examples/demos/demo.py show inspection

python3 examples/demos/demo.py run vehicle
python3 examples/demos/demo.py movies vehicle
python3 examples/demos/demo.py show vehicle

python3 examples/demos/demo.py run region
python3 examples/demos/demo.py movies region
python3 examples/demos/demo.py show region

python3 examples/demos/demo.py run cfd-render
python3 examples/demos/demo.py open cfd-render --app video

python3 examples/demos/demo.py run site
python3 examples/demos/demo.py open site --app godot

python3 examples/demos/demo.py run sprite
python3 examples/demos/demo.py open sprite --app godot
python3 examples/demos/demo.py open sprite --app video
```

For prepared results, skip `run` and use `show` or `open` directly. Godot controls:
left-drag orbit, wheel zoom, R reset. `paths NAME` prints native output paths;
`verify NAME` checks the latest successful run. Every new run gets its own folder.

**Limits:** the vehicle inputs were prepared for a coupe case with no identified
mirror; `region` is an illustrative side-region study. No mesh or solver is run.
See the full README for which parameters to edit, raw CLI equivalents and
troubleshooting.
