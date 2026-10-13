# ParaView recipe comparison

These two complete reusable procedures consume the same task manifest. They are
benchmark examples, not a new product recipe service. `native_recipe.py` runs with
ParaView's pvbatch; `schemaxis_recipe.py` runs with host Python and configured
Schemaxis. Both retain editable inputs and publish the same neutral filenames.
The native procedure is also the independent rendering reference, an explicit
advantage of the ordinary-template control. Geometry and field checks use analytic
expectations rather than either procedure's receipts.

The Schemaxis procedure uses one declarative pipeline per case. Its time list,
slice axis, appearances and camera list expand inside one native process. Artifact
identities drive publication collection; internal attempt filenames are not guessed.
The native procedure implements the same loops, view state and publications directly.
Both supplied procedures regenerate all outputs; agents may add validated reuse.

The coordinator `tools/run_paraview_ai_pilot.py` prepares synthetic PVD/VTK image
data. Point and cell arrays both named `T` intentionally contain different values.
Point values vary with position and time; cell values vary with time. These are
analytic test fixtures, not solved CFD or colleague/customer data.

The initial batch has two cases, two times and two slice positions. Each slice
produces geometry plus two appearances at two camera angles: 40 publications.
The revision changes a slice axis, positions, times and a fixed colour range and
adds a third case: 70 publications. Time zero is included. Image size is 192×160;
one camera faces the slice and the other is oblique. All task parameters are explicit.

The benchmark methods are native scripting from scratch, a supplied native recipe,
and a supplied Schemaxis recipe with framework execution required. All receive the
same manifest, read-only inputs, native runtime, wall bound and CLI budget setting.
Initial, unchanged repeat, revision and damaged-output recovery use continued
conversations. Starting recipes are never regenerated after the initial round.
Method order rotates, but one conversation per method is not statistical replication.

The grader reads every slice and decoded PNG. It checks area, bounds, point/cell
values and image difference from the specified native camera/colour reference.
Tolerance allows small raster-edge differences; it does not establish universal
cross-platform pixel equivalence or subjective visual quality. Eight deliberate
mutations must be rejected before model trials. A missing geometry and substituted
wrong-appearance image are introduced before the final repair round.

```sh
PYTHONPATH=src python3 tools/run_paraview_ai_pilot.py prepare \
  --config /path/to/config.json --output-directory evidence/pv-package
PYTHONPATH=src python3 tools/run_paraview_ai_pilot.py prove \
  --config /path/to/config.json --package evidence/pv-package \
  --output-directory evidence/pv-proof
PYTHONPATH=src python3 tools/run_paraview_ai_pilot.py challenge \
  --config /path/to/config.json --package evidence/pv-package \
  --output-directory evidence/pv-challenges
PYTHONPATH=src python3 tools/run_paraview_ai_pilot.py run \
  --config /path/to/config.json --package evidence/pv-package \
  --output-directory evidence/pv-ai --model MODEL
```

Actual AI execution requires Linux bubblewrap, Xvfb/xvfb-run, a working ParaView
installation and an authenticated Claude CLI. Credentials are mounted read-only
from the existing account. The coordinator and other workspaces are absent from
each namespace. Native and independently graded namespace preflight happens before
timing models; preflight scripts/results are removed from contestant workspaces.
Provider API errors stop the pilot and remain unscored. Usage is measured from
actual transcripts with resumed-conversation accounting. No model training occurs.

## Onboarding comparison

`tools/run_paraview_onboarding_pilot.py` uses fresh case parameters and six fresh
conversations: native and Schemaxis recipes under each of three introductions.
`baseline` keeps the earlier instructions, `brief` adds exact invocation and scoped
qualification evidence, and `checked` also supplies `check_outputs.py`. Each follows
the same initial/repeat/revision/repair sequence. Recipe order is balanced within
each condition across the four rounds. There is one conversation per cell, so
this is an exploratory comparison without independent statistical replicates.

Both recipes get equivalent guidance. Qualification statements are generated only
after executing and independently grading the exact recipe in its actual namespace.
The statement identifies initial task/input, recipe, source and native binary
digests. It applies to the initial task, not all future inputs. Baseline contestants
receive the same preflight but are not shown its evidence. Native code, fixtures,
hidden grading thresholds and model settings are otherwise shared.

The public checker runs inside pvbatch and reads every required VTP/PNG. It checks
analytic geometry/fields, PNG dimensions and visible surface/background content.
`--record FILE` saves task/input/publication hashes only on success;
`--baseline FILE` additionally requires unchanged task, inputs and publications.
It does **not** independently establish correct image camera, colour mapping or
image time. Saved hashes prove unchanged bytes, not semantic correctness. The
hidden evaluator continues checking those image properties against its references;
neither references nor grader are exposed to the contestants. This is a bounded
fixture checker, not a general ParaView scientific validator or new product API.

Use the same four commands above with `run_paraview_onboarding_pilot.py` and fresh
output directories. The run records preflight wall time separately. Model timing
includes instructions, execution and any agent checks, but excludes coordinator
setup and independent grading. Recipe/checker development time is not amortised
into model costs. Preserve these boundaries when interpreting onboarding savings.

The [completed onboarding comparison](../../../verification/2026-09-28-paraview-onboarding.md)
records all 24 turns, the corrected digest presentation, initial and full-workflow
costs, independent grades, validator limitations and native display recovery.
