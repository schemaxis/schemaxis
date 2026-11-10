# Installation and private configuration

Install Python 3.10 or newer, then run `python3 -m pip install .` from the repository.
Install the native applications you need from their official distributors. Schemaxis
keeps planning and discovery independent of those installations.

Managed CLI runs and Studio Case Runner default to packaged application modules.
See [application modules](application-modules.md) for image registration, fetching,
offline downloads, cache inspection and reviewed cleanup. A public module catalogue
and native desktop installer are not bundled here. Use `--backend native` on
`run`, or save the native preference, to use the separate installations described
below. Native interactive consoles retain their existing application setup.

The base installation supports [headless CLI operation](headless.md) without a
Schemaxis GUI dependency. Use `schemaxis --version`, `schemaxis --help` or
`schemaxis help TOPIC` for [command and capability discovery](cli-discovery.md).
See [storage management](storage-management.md) for explicit inventory, reviewed
backup/archive plans and restoration; these commands preserve source data.

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
schemaxis configure webp /path/to/cwebp
schemaxis configure flac /path/to/flac
schemaxis configure espeakng /path/to/espeak-ng
schemaxis configure shotcut /path/to/Shotcut.app/melt
schemaxis configure kicad /path/to/kicad-cli
schemaxis configure imagej /path/to/java
schemaxis configure prusaslicer /path/to/prusa-slicer
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
Executable locations preserve the selected absolute path, including a Python
virtual environment's interpreter symlink. Resolving that symlink to the system
interpreter would lose the environment's installed native packages. Installation
root locations are canonicalised separately.
Additional launcher keys such as `freecad_gui` can be added to `locations` for
assembly execution. FreeCAD's live GUI workflows may require a GUI launcher: use `console --executable`
or the console's configuration command when its launcher differs from batch FreeCAD.

The [WebP image publisher](webp.md) uses libwebp 1.6 tools. Execution needs
both `cwebp` and `dwebp`; use `--webp` and `--dwebp` on `run`, or store `webp` and
`dwebp` paths in the private configuration's `locations` object. `configure` names
adaptors, so add the auxiliary `dwebp` key to that JSON file directly, or set
`SCHEMAXIS_DWEBP`. Later `schemaxis verify` needs that trusted decoder to reopen
the actual retained WebP bytes. Executable paths in a receipt are never used to
choose a command. Discovery and planning do not need either native tool.

The [FLAC recording and archive bridge](flac.md) uses FLAC 1.5.x; bounded native
acceptance exercised 1.5.0. Set the `flac` location or `SCHEMAXIS_FLAC`, or pass
`--flac` for execution. Both execution and later verification require this trusted
executable to decode the actual retained FLAC bytes. Verification does not use PATH
or executable paths from receipts. The bounded route accepts PCM16 mono/stereo
recordings and can hand decoded WAV to SoX; it does not preserve tags in WAV.

The [offline synthetic narration adaptor](espeakng.md) uses eSpeak NG 1.52.0 with
its English (United States) voice and matching native data. Set the `espeakng`
location or `SCHEMAXIS_ESPEAKNG`, or pass `--espeakng` for execution. Verification
re-synthesises the captured text with the trusted executable and its data; it
requires the matching runtime and data even when a changed data file would produce
the same PCM. Keep that installation available for retained runs. The bounded
qualification used a file-output-only build with Sonic, MBROLA and playback
disabled; other builds need their own qualification. Discovery and planning load
no speech engine. Output remains a synthetic draft for a person to listen to.

Check host setup with `schemaxis discover` and `schemaxis plan INPUT.json`.
Native qualification is separate: execute a representative example and verify its
retained results. See [upstream updates](updates.md) for supported-version policy.

Gmsh uses a separate Python environment containing the native `gmsh` package,
qualified on 4.15.2. Pass that interpreter, not the Gmsh GUI executable. The host
Python remains dependency-free. See [the meshing guide](gmsh.md).

Cantera similarly uses an isolated Python environment with Cantera 3.2.x; the
qualified 3.2.0 h2o2 mechanism is checked by hash. Pass its Python interpreter
with `--cantera`; see [the thermochemistry guide](cantera.md).

[KiCad board inspection and drill export](kicad.md) use `kicad-cli` 10.0.7.
[PrusaSlicer](prusaslicer.md) uses the 2.9.6 console executable for bounded FFF
slicing; no printer connection is needed. Their overrides are `--kicad` and
`--prusaslicer`.

[ImageJ particle measurement](imagej.md) uses the ImageJ 1.54t core `ij.jar` and a
full JDK with the Java source launcher (11 or newer; qualified on OpenJDK 21).
Configure `imagej` as the Java executable, then add `"imagejJar": "/path/to/ij.jar"`
to the private configuration's `locations` object, or pass `--imagej-jar`.
The Fiji launcher and plugins are outside this bounded integration.

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

## Structural and solid thermal runtimes

The [OpenSees planar truss adaptor](opensees.md) uses an isolated Python with
OpenSeesPy 3.8.0.0 and OpenSees engine 3.8.0. Configure that interpreter under
`opensees`, or pass `--opensees /absolute/path/to/python`; the host never imports
OpenSeesPy. Missing packages and unsupported versions have distinct recovery
faults. The supported product is linear elastic planar trusses, with independent
stiffness and equilibrium checks.

The [Elmer solid-conduction adaptor](elmer.md) uses a serial ElmerSolver built
from stable 26.2.1. Configure `elmer`, or pass `--elmer /absolute/path/to/ElmerSolver`.
The binary reports only major/minor 26.2; retain the release-source provenance
separately. Its native ASCII restart retains full-precision temperature values;
the exported ASCII VTU has eight significant digits. The declared product covers
layered steady solids, source and end-condition alternatives, and sampled limits.

The [FreeCAD finite-depth machining examples](freecad-part-design.md#blind-pockets-and-counterbores) are
qualified on FreeCAD 1.1.4. Keep an older installation alongside an update when
existing workflows depend on it, and select the intended executable explicitly.
