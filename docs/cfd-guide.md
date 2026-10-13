# CFD post-processing guide

For a guided introduction, demonstration map, ParaView schemas and expression
examples, start with [the CFD README](../CFD-README.md). For a completed case,
follow the [step-by-step post-processing guide](cfd-postprocessing.md).

This guide covers setup, the demonstration commands and the qualification
boundary for post-processing OpenFOAM-format cases with ParaView.

## Capability and acceptance boundary

| Area | Implemented | Qualification and limits |
| --- | --- | --- |
| ParaView post-processing | OpenFOAM readers, slices, contours, streamlines, measurements and verified publications | Recorded real-case and bounded MPI qualification exists. Your target versions and representative cases still need acceptance; output verification does not certify the CFD solution. |
| Orchestration | ParaView participates in scheduled `schemaxis.workflow/1` operations, including handoffs to Blender and FFmpeg | Handoffs carry declared artifacts such as glTF geometry or images, not complete CFD data. |
| Case preparation, meshing and solving | Not included | No adaptor in this repository prepares a case, generates a CFD mesh or runs a solver. Such providers can be installed separately as [external adaptor packages](adaptor-development.md). |

Historical evidence: [real-case two-rank CFD qualification](../verification/2026-09-19-native-parallel-cfd.json).
Verification records preserve their original observations; they are not new
acceptance runs or runtime dependencies. Bulk evidence and the source CFD case are
not included in a fresh clone.

## Host setup and authoring

From the cloned repository root, with Python 3.10 or newer:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
schemaxis discover
schemaxis plan examples/schemaxis/branching.json
```

Alternatively use `PYTHONPATH=src python3 -m schemaxis` without installing. Planning
requires no native application.

Composition-capable adaptors share a bounded host-side resolver: put shared values
in `dimensions`, `settings` or `definitions`, reference them with `$document`, and
use declared `$expr`/`$value` calculations where needed. Normal `plan` and `run`
resolve these before typed adaptor validation. Unknown options, wrong resolved
types, missing/cyclic references and unsupported operations still fail. No native
methods or arbitrary Python are exposed. Export
`schemaxis schema --authored --provider paraview` for an editor; expanded schemas
describe the resolved values. Schemas check structure; planning checks reference
targets and semantics.

For direct use of the demonstration `site.input.json`, set `settings.source` to
the absolute path of `examples/demos/sites.geojson` in your checkout. The
demonstration helper sets that path from its own checkout location. Native
resource paths must be absolute.

## Reading OpenFOAM-format cases

ParaView's OpenFOAM reader opens a case through an empty `.foam` marker file in
the case root. Cases written by other OpenFOAM-derived codes can often be read the
same way, but confirm that your ParaView release reads your output format,
multi-region layout and processor decomposition before relying on it. See
[preparing the case](cfd-postprocessing.md#1-prepare-the-case-and-the-two-python-environments).

## ParaView demonstration

Provide an external ParaView installation with `bin/pvbatch` and an OpenFOAM case
with its `.foam` marker and underlying data. Recorded work used ParaView 5.13.3;
other target installations need acceptance. The supplied vehicle/mirror inputs
contain illustrative geometry, field names, patch groups and camera bounds for a
case that is not distributed. Review and adapt these to your case before executing;
replacing only the path does not adapt the physics or geometry.

```bash
export SCHEMAXIS_DEMO_PARAVIEW_ROOT=/absolute/ParaView
export SCHEMAXIS_DEMO_CASE=/absolute/case/case.foam
python3 examples/demos/demo.py doctor vehicle
python3 examples/demos/demo.py plan vehicle
python3 examples/demos/demo.py run vehicle
python3 examples/demos/demo.py show vehicle
```

`--paraview-root` and `--case` override those environment variables. The helper
retains the configured input, expanded command, native logs and verification in a
fresh `evidence/demos` directory. `plan vehicle` substitutes time 1.0 **only for
planning**; `run` and `export` keep native latest-time discovery. For direct CLI
use, export the configured input, then run it:

```bash
python3 examples/demos/demo.py export vehicle
schemaxis run evidence/demos/inputs/vehicle.json \
  --paraview-root "$SCHEMAXIS_DEMO_PARAVIEW_ROOT" \
  --output-directory evidence/paraview-first-acceptance --timeout 600
schemaxis verify evidence/paraview-first-acceptance
```

Only the selected demonstration's applications are required. Optional CAD,
rendering and video demonstrations accept `--freecad`, `--freecad-gui`,
`--blender`, `--ffmpeg`, `--qgis`, `--godot` and `--aseprite`, or
`SCHEMAXIS_DEMO_` plus the upper-case option name with hyphens changed to
underscores. Use actual configured launchers; FFmpeg needs its matching FFprobe
installation and QGIS needs a Python environment with QGIS. `doctor NAME` checks
relevant files/executables, not licences or API compatibility. ParaView PATH is
not changed.
