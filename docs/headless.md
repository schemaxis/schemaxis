# Headless installation and operation

The standard Schemaxis host installation is already headless: Python 3.10+ and
its standard library are sufficient for JSON inputs, discovery, schemas, planning,
CLI automation, the agent transport and the schedule worker. No GUI package is a
required dependency. Install in a dedicated virtual environment without extras:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/schemaxis --version
.venv/bin/schemaxis --help
.venv/bin/schemaxis capabilities browse
.venv/bin/schemaxis plan examples/schemaxis/gmsh-minimal.json
```

The package retains Studio's static assets so the same installation can serve it
when requested; those files do not launch or import a GUI. `console --web` opts
into the local Studio server. Ordinary CLI commands and `console` without `--web`
do not start that server. There is no separate `--headless` switch or GUI uninstall
step. Omit `yaml` and `test` extras when they are unnecessary; YAML source support
requires the optional `yaml` extra, while JSON workflows need neither extra.

Configure only the native applications needed for execution. Keep configuration
private, with an explicit path useful for services and batch jobs:

```sh
export SCHEMAXIS_CONFIG=/path/to/private/schemaxis.json
# Create the file once with {"version":1,"locations":{}} before using it.
schemaxis configure blender /path/to/blender
schemaxis run INPUT.json --output-directory NEW_OUTPUT_DIRECTORY
schemaxis verify NEW_OUTPUT_DIRECTORY
```

`configure` checks the selected location and records it without launching the
application. An explicitly selected missing configuration file is an error.
CLI executable flags override configuration. See [installation](installation.md)
for application-specific paths; use an absolute configuration path for workers
whose current directory differs from the interactive shell.

Headless host operation and headless native execution are separate properties.
Native applications still need their own installation, libraries and resources.
Blender uses its background launcher; Calc passes `--headless`; QGIS and bounded
FreeCAD batch routes request Qt's offscreen platform. These flags do not establish
that every rendering backend works without display/graphics drivers. FreeCAD live
GUI/assembly workflows and Premiere's UXP bridge have application GUI requirements;
Premiere acquisition also requires its supported platform. Check each adaptor's
guide and qualify representative workloads in the deployment environment.

Automated core checks block GUI/native imports during version, help, discovery,
keyword search and planning. The accompanying
[verification record](../verification/2026-10-17-core-usability.md) distinguishes
those host checks and a disposable clean installation from native qualification.
