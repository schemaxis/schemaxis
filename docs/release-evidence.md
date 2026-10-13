# Release evidence

`tools/release_evidence.py` reruns the release showcase workflows through the
installed native applications. It writes one `summary.json` per workflow and an
`index.json` for the whole run. The public website uses only numbers and files
that these outputs contain. Nothing is estimated or edited by hand. A failed
run, check or qualifier is recorded as a failure, together with a log excerpt.

The runner uses only the standard library. Schemaxis and every application run
in subprocesses through the ordinary CLI (`python3 -m schemaxis run/verify`).
The workflows are listed in `tools/release_evidence_manifest.json`.

## What one workflow run does

For each manifest workflow, and for each of its parts:

1. **Initial run**: `schemaxis run` into `runs/<part>/`, followed by `schemaxis verify`.
2. **Independent checks** on the initial outputs. These are listed below.
3. **Qualifier**: the matching `tools/qualify_*.py`, if the manifest names one.
   It performs its own separate native run in `qualify/`.
4. **Unchanged rerun**: `schemaxis run --resume` into the same `runs/<part>/`,
   then `schemaxis verify`. This is the product's supported reuse path (see
   [parallel execution](parallel-execution.md#restart-and-cancellation)). The
   summary records which jobs were reused and which ran again. ParaView
   file-reader jobs rerun by design.
5. **Changed-document probe**: the variant document is passed with `--resume`
   to the initial directory. It must be refused with `RESUME_MISMATCH`, and the
   initial directory must still verify afterwards.
6. **Variant run**: the document with one authored parameter changed, run into
   a fresh `variant/<part>/`. Resume accepts only an unchanged document, so every
   variant job runs again, and the summary reports this.
7. **Known-issue probes**: listed in the manifest. Their observed fault code is
   recorded.
8. **Showcase**: chosen published artifacts are copied to `showcase/`, each with
   its SHA-256 and size. A browser-playable H.264 copy of a lossless MKV is a
   *derived* artifact. Its record includes the FFmpeg version and arguments.

The `reproducibility` workflow runs `tools/benchmark_workflows.py prepare` and
`prove`, then `tools/benchmark_challenges.py`. Its summary records the
case-round pass counts, the per-round job reuse and the rejected falsification
mutations. It sets `"timingsComparable": false`: these are reference
implementations, not AI trials (see [benchmarks](benchmarks.md)).

## Reproduce

1. Configure every application in a single private runtime file. The format is
   described in [installation](installation.md):
   `{"version": 1, "locations": {...}}`. The runner checks nothing beyond what
   `schemaxis run` checks. Run `python3 -m schemaxis discover` first.
2. Make sure `xvfb-run` is available. Godot previews (`sprite-godot`,
   `site-godot`) run under Xvfb.
3. From the repository root:

```sh
python3 tools/release_evidence.py list
python3 tools/release_evidence.py run \
  --config /absolute/private/release-runtimes.json \
  --output-root /absolute/evidence/release-YYYYMMDD \
  --case /absolute/path/to/case.foam            # only for cfd-coupe
python3 tools/release_evidence.py run ... --workflow beam-workbook   # one workflow
python3 tools/release_evidence.py index --config ... --output-root ...
```

The runner refuses to reuse an existing workflow directory. Move a failed
attempt aside, and keep it, before rerunning that workflow. `SCHEMAXIS_RELEASE_CASE`
can supply `--case`. The case path is never written to a summary. Copied inputs
replace it with `<coupe case (not distributed)>`. Workflows marked
`requiresCase` are skipped when no case is given.

## Output layout

```
<output-root>/index.json
<output-root>/<workflow-id>/summary.json   publishable
<output-root>/<workflow-id>/input/          publishable: authored inputs, private paths replaced
<output-root>/<workflow-id>/showcase/       publishable: website files
<output-root>/<workflow-id>/runs|variant|qualify|logs|work/   private native evidence
```

Native run directories contain workstation paths. Publish only `summary.json`,
`input/`, `showcase/` and `index.json`.

Summaries contain no absolute paths, hostname or username. Every path is
relative to the workflow directory, and applications are identified by name and
self-reported version. The runner audits each summary before writing it.
`summary.json` (`schemaxis.release-evidence.summary/1`) contains the following:
workflow id, title, apps and their self-reported versions, input files and
hashes, the variant definition, any authored adjustments, per-step wall time
and exit status, artifacts (with paths, kind and SHA-256), verification counts,
independent checks (with observed value, reference, difference and tolerance),
qualifier outcome, reuse counts, known issues, showcase files, failures with log
excerpts, timestamps, the machine and the code identity (commit and the runner
and manifest hashes). The machine block contains the CPU model, cores, RAM, OS
and kernel only.

## Independent checks

The runner reads native outputs directly, without Schemaxis's own assessment
code:

| Workflow | Check | Reference |
| --- | --- | --- |
| `cfd-coupe` | latest time selected; PNG sizes and counts; movie frames and rate (ffprobe); mesh cells from owner headers (informational) | authored settings, native time inspection |
| `cad-mesh-inspect` | Gmsh volume, tetrahedron determinant sum from `volume.vtu`, ParaView integrated volume, end-face areas | L × W × H, W × H |
| `cad-render-movie` | FreeCAD solid volume; orbit PNGs; movie frames | Pappus: π(Ro² − Ri²)·R·θ |
| `beam-workbook` | tip deflection (three meshes), root reaction and moment; Calc summary caches | Euler–Bernoulli F L³/(3EI), equilibrium, statistics recomputed from the CSV |
| `rlc-workbook` | complex V_out, magnitude, phase at each frequency; Calc summary caches | 1/(1 − ω²LC + jωRC) |
| `diagram-video` | decoded frames, rate and size; MLT timeline ranges; PNG sizes | authored clips, fps and mm × dpi |
| `regression-workbook` | coefficients, training RMSE, held-out error and predictions; Calc caches | Householder QR on the authored rows |
| `cantera-workbook` | cp, cv, density, enthalpy rise | monatomic ideal gas, M(Ar) = 39.95 g/mol |
| `sprite-godot`, `site-godot` | PNG and video decoding; clipped buffers within the study bounds | authored bounds |

A check that cannot read its source is recorded as failed. Informational
records (`"passed": null`) are not counted as passes.

## Authored adjustments

A workflow part may carry `adjustments`. These are JSON Patch operations
(`test`, `add`, `replace`) applied to the exported demo document before both the
initial and the variant runs. The manifest gives a reason for each, and
`summary.json` repeats it. `cfd-coupe` uses one adjustment. ParaView's
iso-surface for the coupe contains a duplicate triangle. Blender's validated STL
re-import drops it, so the Blender adaptor's exact STL round-trip check rejects
the published mesh. A 1 µm weld before shading removes the duplicate. The
check was not loosened.

## Demo location

The manifest field `demoDirectory` names the directory that contains `demo.py`.
Demo workflows are exported with `demo.py export NAME` and then run in the same
way as the examples. The vehicle study is wrapped as a one-operation workflow so
that `--resume` applies.
