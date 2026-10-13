# ParaView AI comparison: scripts, native recipes and Schemaxis recipes

This comparison tests a richer use of Schemaxis than the preceding RLC pilot:
each case expands over times, physical slice positions, appearances and cameras.
The three methods are ordinary native scripting from scratch, a supplied reusable
native Python procedure, and a supplied reusable Schemaxis procedure. It therefore
separates access to a reusable procedure from access to Schemaxis itself.

## Results

All twelve model invocations completed, with no provider errors, permission
denials, timeouts or human corrections. Both supplied-procedure methods passed
every case. Schemaxis did not improve overall time or estimated cost over the
native-procedure control in this pilot.

| Method | Case-round checks | Artifact checks | Wall seconds | Estimated USD | Output tokens | Input tokens, including cache |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Native scripting from scratch | 6/10 | 216/220 | 272.047 | 0.8359312 | 17,947 | 795,929 |
| Supplied native recipe | 10/10 | 220/220 | 286.697 | 1.0651470 | 21,653 | 1,038,787 |
| Supplied Schemaxis recipe | 10/10 | 220/220 | 305.667 | 1.4993230 | 23,462 | 2,068,088 |

The ten case checks are repeated assessments across four rounds, not ten
independent trials. Forty initial artifacts comprise 8 VTP files and 32 PNGs;
the revised 70 comprise 14 VTP files and 56 PNGs. Counting the unchanged repeat
and repair gives 220 artifact checks per method, not 220 independent outputs.

| Round | From scratch: seconds, cases | Native recipe: seconds, cases | Schemaxis recipe: seconds, cases |
| --- | ---: | ---: | ---: |
| Initial | 111.341, 1/2 | 124.176, 2/2 | 162.557, 2/2 |
| Unchanged repeat | 27.235, 1/2 | 40.775, 2/2 | 24.927, 2/2 |
| Revision | 68.989, 2/3 | 78.067, 3/3 | 43.433, 3/3 |
| Damaged-publication repair | 64.482, 2/3 | 43.680, 3/3 | 74.751, 3/3 |

Against the native recipe, Schemaxis used 6.6% more wall time, 40.8% more estimated
cost and 8.4% more output tokens overall. Including cached reads, its input-token
total was 99.1% higher; repeated cache reads are not unique prompt size and are
priced differently from uncached input.

Initial Schemaxis work was particularly expensive. After that setup, its three
follow-up turns together took 143.110 seconds and $0.577246, against 162.522 seconds
and $0.664583 for the native recipe: 11.9% faster and 13.1% cheaper. This is an
interesting reuse hypothesis, not an established saving or a break-even forecast.
The repair turn alone was slower and more expensive with Schemaxis. Different
self-checking choices and this single sequence preclude a general ranking.

### What the transcripts and diagnostics establish

The from-scratch script omitted `_DisableFirstRenderCameraReset()`. ParaView
overrode the first explicitly configured camera, producing the wrong scale in
`field-a/slice-0-0-appearance-0-camera-0.png` in every round. Its self-checks accepted
that image. All other artifacts passed, including both deliberately damaged
publications after repair. The repair failure is the retained camera defect,
not a failure to regenerate the two injected corruptions.

A post-trial diagnostic reran the original initial script in the same isolated
environment, then reran a copy adding only the import and call that disable the
automatic camera reset. The original reproduced the one-image failure; the fixed
copy passed all 40 outputs. This diagnostic is excluded from AI scores and shows
a missed native state rule, not an inability of an AI to fix it. Both supplied
recipes already handled that rule.

The native-recipe contestant left the seed file unchanged and wrote a derivative
procedure with additional explicit time updates, bounds-based focal points and
colour-range readback. The supplied seed already passed preflight; these edits
are not evidence that the seed needed repair. Its own image validator initially
missed a stale colour range, then was strengthened. During publication repair it
regenerated the two affected cases and retained the unaffected third case.

The Schemaxis contestant kept its supplied recipe unchanged throughout. Initial
work included substantial documentation/source inspection, repeated execution and
building an image validator. Revision required no recipe changes. During repair,
it used retained artifact hashes to locate the damaged publications, wrote a
checker for the published copies and regenerated all cases. That is a concrete
benefit of durable receipts, but does not demonstrate built-in selective recovery
or incremental execution across edited pipeline definitions.

Schemaxis's last natural-language answer miscounted the final publications as
100 files, including 70 PNGs and 14 VTPs. Actual artifacts and independent grades
show 70 files: 56 PNGs and 14 VTPs. Artifact correctness does not guarantee accurate
agent narration.

One from-scratch revision attempt encountered a bad X-server connection; a later
attempt with the same native code succeeded. The cause is unconfirmed. Its measured
time and usage include display diagnosis and retries, so that method's timing is
not a clean measurement of authoring alone. Neither supplied-recipe method had
that observed failure. No guessed adjustment has been subtracted. The runner's
zero tool-error totals do not count every failed command hidden by shell pipelines
or semantic self-check; the transcript audit is necessary.

### Development implications

This result supports reusable, independently checked procedures. It does not yet
demonstrate a Schemaxis efficiency or reliability advantage over an equally
well-prepared native procedure. The next improvement should reduce the agent work
around an existing recipe: bounded discovery, an explicit input/output contract,
and one supported way to inspect and check named publications. The initial source
audits and custom validators show where that work still leaks through.

A follow-up comparison should retain the native-recipe control, include all setup
costs, use fresh cases and independent repeated conversations with balanced order,
and measure correctness, repair, tokens and time together. A cheaper model can be
another controlled factor later. Neither model-specific training nor expansion
to more adaptors follows from this evidence alone.

## Conditions and grading

All methods use Claude Opus 5.5 (`claude-opus-5-5`), high effort, Claude Code
2.1.284 and ParaView 5.13.3. Each invocation has a 600-second bound and the same
`--max-budget-usd 6` CLI setting. The three conversations retain their work across
initial, unchanged-repeat, revision and damaged-publication repair rounds.
Order rotates as declared in the runner. These are single conversations per method,
not independent repeated trials or a statistical model comparison.

Each namespace has identical read-only native binaries and inputs, its own writable
home/workspace and process namespace, and Mesa software rendering under a private
Xvfb. Only the Schemaxis namespace contains Schemaxis. Neither the coordinator,
grader, golden images, another method's work nor the future revision is available.
Network access is available for permitted public native documentation; no human
corrective hints or grader findings are sent to contestants.

Initial input consists of two synthetic PVD/image-data cases, each with two times,
two slice positions, two appearances and two cameras: 40 publications. Arrays named
`T` exist on both points and cells with deliberately different values. The revision
changes one slice axis, positions and times, changes the point colour range and adds
a third case: 70 publications. The common repair round deletes one VTP and replaces
one PNG with a different appearance/view. Regeneration is allowed; the task does
not require a particular caching implementation.

The common grader reads actual VTP geometry and scalar fields, checking area,
bounds and every point/cell value against analytic expectations. It decodes PNGs
and compares the specified camera and colour mapping with a native reference,
allowing small raster-edge differences. All eight deliberate corruptions were
rejected before the trial. Producer verification flags do not determine grades.
The ordinary supplied recipe is also the rendering reference implementation;
this favours that control transparently. Geometry/field expectations are analytic.

Both supplied recipes initially regenerate their outputs. Schemaxis performs the
time/slice/appearance/camera expansion inside a pipeline per case; the native
procedure writes those loops and view operations directly. The supplied Schemaxis
wrapper also collects named publications using artifact identities. These are
complete benchmark examples, not a newly shipped general recipe-management API.

Wall time includes each agent invocation and its native work, self-checking and
response. Staging, preflight and independent grading are excluded. Usage accounting
uses per-invocation tokens and differences of resumed-session cumulative costs;
list-price estimates are not actual subscription billing. Neither one-time recipe
authoring nor framework maintenance is included in those costs.

## Defects and preflight exclusions

Before any model work, the independent grader found that Schemaxis rendered later
times at time zero while exporting correct later-time geometry. Its own verifier
accepted those images. That defect was fixed and independently retested before
freezing this comparison. See the [render-time evidence](2026-09-28-paraview-render-time.md).
This matters when interpreting robustness: Schemaxis is not inherently immune to
the state-management mistakes that affect ordinary native scripting.

An earlier namespace preflight crashed Xvfb while selecting NVIDIA EGL in the
device-isolated environment. No model calls ran. Explicit Mesa selection fixed
that infrastructure issue equally for all methods. The failed attempt remains in
`evidence/ai-paraview-recipes-01/` and is excluded from AI scoring.

The final namespace preflights passed all output checks for every method before
model timing. Maximum mean channel error against the host references was about
0.00152 on the 0–255 scale, well below the unchanged grader threshold of 2.0.

## Where the adaptor abstraction differs

The current adaptors do not all supply the same layer of abstraction:

- ParaView and Blender use the shared definition graph and runtime machinery for
  dependency selection, parameter axes, times, object reuse and publication.
  ParaView's native application already has a pipeline; Schemaxis adds declarative
  orchestration and coordinated output around it.
- FreeCAD supplies bounded editable feature/assembly construction and native-file
  readback; QGIS supplies bounded geospatial operations and checks. Their routes
  do not expose all of ParaView's time/axis/presentation machinery.
- Ngspice, Cantera, Gmsh, Calc and Octave expose bounded domain operations with
  validation, durable handoffs and verification. For example, ngspice supplies an
  independent circuit solver check and Calc checks native formula/value round trips.
  These add guarantees but need not reduce the amount of orchestration an agent
  writes for a small task.

Some individual operation bindings, including generated ParaView bindings, are
close translations of native properties. The larger benefit comes from the
framework and domain contracts above those bindings. A successful registration or
operation count alone is not evidence of reduced AI effort.

## Reproduction and retained evidence

Tested source: `6509fa8`, following render-time fix and benchmark setup `3b66122`.
The source, recipes, manifests and grading criteria remained fixed during the
model runs. Exact task prompts and invocation prompts are retained with each method.

- `evidence/ai-paraview-recipes-02/`: raw report, measurements, model transcripts,
  independently graded namespace preflights and frozen per-round workspaces.
- `evidence/paraview-pilot-package-02/`: frozen initial/revised inputs and references.
- `evidence/paraview-pilot-proof-04/`: passing deterministic Schemaxis preflight.
- `evidence/paraview-pilot-challenges-02/`: eight rejected artifact corruptions.
- `evidence/paraview-camera-counterfactual/`: original/fixed scripts, their hashes,
  native outputs and independent grades for the post-trial camera diagnosis.
- `evidence/ai-paraview-recipes-02/adjudication.json`: concise transcript audit,
  exclusions and score interpretation; raw runner grades remain unchanged.
- [Portable recipes and commands](../examples/benchmarks/paraview/README.md).

These small analytic datasets exercise state and publication correctness. They do
not establish performance on large CFD cases, MPI, HPC deployment, arbitrary data
or upstream application upgrades. No private case data, cluster jobs or model
training were used.
