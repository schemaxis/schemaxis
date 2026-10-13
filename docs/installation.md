# Installation and private configuration

Install Python 3.10 or newer, then run `python3 -m pip install .` from the repository.
Install the native applications you need from their official distributors. Schemaxis
keeps planning and discovery independent of those installations.

From the repository (or your workflow working directory), record application locations:

```bash
schemaxis configure blender /path/to/blender
schemaxis configure freecad /path/to/freecadcmd
schemaxis configure paraview /path/to/ParaView
schemaxis configure octave /path/to/octave-cli
schemaxis configure r /path/to/Rscript
schemaxis configure calc /path/to/soffice
schemaxis configure gmsh /path/to/gmsh-environment/bin/python
schemaxis configure calculix /path/to/ccx
schemaxis configure cantera /path/to/cantera-environment/bin/python
schemaxis configure ngspice /path/to/ngspice
schemaxis configure inkscape /path/to/inkscape
schemaxis configure ffmpeg /path/to/ffmpeg
schemaxis configure shotcut /path/to/Shotcut.app/melt
```

Use actual executable paths or, for ParaView, its installation root. Other providers
use the same command. Configuration does not run the executable or certify its version.
The command merges settings into `.schemaxis.local.json`, which Git ignores. Do not
commit this file. Each user maintains their own locations. A template is:

```json
{"version": 1, "locations": {"blender": "/path/to/blender", "freecad": "/path/to/freecadcmd", "roots": ["/path/to/ParaView"]}}
```

Configuration is read from the current working directory. To use a single personal
file from any directory, set `SCHEMAXIS_CONFIG` to its location before configuring or
running Schemaxis. Keep that file outside version control. No shell aliases or global
PATH modifications are necessary.

Explicit CLI flags and Python `locations` arguments override configured defaults;
existing adaptor environment variables and PATH searches remain fallbacks when no
location is configured. `run`, workflow execution, `inspect` and new console sessions
use these defaults. Saved console configurations take precedence until reconfigured.
Additional launcher keys such as `freecad_gui` can be added to `locations` for
assembly execution. FreeCAD's live GUI workflows may require a GUI launcher: use `console --executable`
or the console's configuration command when its launcher differs from batch FreeCAD.

Check host setup with `schemaxis discover` and `schemaxis plan INPUT.json`.
Native qualification is separate: execute a representative example and verify its
retained results. See [upstream updates](updates.md) for supported-version policy.

Gmsh uses a separate Python environment containing the native `gmsh` package,
qualified on 4.15.2. Pass that interpreter, not the Gmsh GUI executable. The host
Python remains dependency-free. See [the meshing guide](gmsh.md).

Cantera similarly uses an isolated Python environment with Cantera 3.2.x; the
qualified 3.2.0 h2o2 mechanism is checked by hash. Pass its Python interpreter
with `--cantera`; see [the thermochemistry guide](cantera.md).

The circuit adaptor is qualified on ngspice 47. Configure its batch executable
or use `--ngspice`; no graphical frontend, KiCad installation or user startup
script is required. See [the linear-circuit guide](ngspice.md).

The [R regression adaptor](r.md) uses R 4.6.1's `Rscript` with its base, stats and
utils packages; no CRAN add-on package is required. The
[CalculiX beam adaptor](calculix.md) targets the `ccx` 2.23 batch solver and
does not require a graphical postprocessor. Their executable overrides are
`--r` and `--calculix`. [Calc's bounded workbook requirements](calc.md) are
qualified on LibreOffice 26.8.1.1, using isolated headless profiles.

Inkscape uses its public CLI; the diagram slices were qualified on 1.4.4.
Shotcut uses its portable `melt` wrapper with the distribution's matching
`ffmpeg` and `ffprobe` siblings. Its bounded timeline qualification uses Shotcut
26.9.27's MLT 7.41.0 engine, including native reload/render and bundle relocation;
it does not establish GUI editing or arbitrary MLT project support. See the
[diagram-to-video setup](diagram-video.md) for their combined workflow.

The experimental [Premiere integration](premiere.md) uses a read-only UXP panel
inside Premiere on Windows/macOS. Supply an existing private job directory with
`--premiere-bridge`; it is a folder transport, not an executable location for
`configure`. It has host contract tests but no native qualification yet. Linux
can plan and inspect retained results; native acquisition reports
`NATIVE_ENVIRONMENT_UNAVAILABLE`.
