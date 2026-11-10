# FreeCAD checked milling milestone

Qualification targets FreeCAD 1.1.4's native CAM Job, stock, toolbit/controller,
facing and closed planar-floor pocket operations, with trusted built-in LinuxCNC
posting. This bounded milestone does not complete broad CAM or FreeCAD coverage.

Independent fixtures use an enclosure with explicitly millable R2 cavity corners
and a D3 endmill, a held-out geometry/tool variant and a sharp-corner negative
control. Numerical CAD checks replay continuous posted line/arc/plunge sweeps in
constant-coverage depth slabs; they do not sample cutter positions or use the
producer Path algorithm. Area, extrusion and independent CAD cross-section
volume/centre-of-mass integrals and planar intersection/difference balances are
checked. Accumulated numerical balance discrepancies are added conservatively
to both reported finish volumes before applying both unchanged authored finish
limits. An early investigation
used an arbitrary quarter-limit numerical reserve; review removed that
unjustified additional cap. Every absolute discrepancy is still accumulated,
with unchanged per-step gross-inconsistency gates; none is subtracted or
cancelled. Failed rounds remain retained. This margin is numerical
consistency evidence, not a certified bound on all kernel error.

Oblique walls and curved-Z targets are explicitly outside this vertical-wall
2.5D milestone; broader surfacing remains unfinished.

`tools/qualify_freecad_cam.py` runs native FCStd/STEP and cutting-data variants,
fresh trusted geometry replay, editable save/fresh reopen, saved-property/proxy/
NC/material-summary tamper controls, unreachable-corner refusal, workflow reuse
and NC damage invalidation, and retained-source verification after original
source removal. Bulk receipts stay outside the source tree. Acceptance results
are recorded after the full frozen-source run; an early successful geometry
probe is not the full product-delivery result.

The fifth frozen round passed all three FCStd/STEP/held-out geometry/tool
deliveries, including fresh material replay, and ten hostile controls. It then
stopped at a GUI harness timeout on CAM's optional asset-migration dialogue.
The repair carries the finite native migration setting and runs actual GUI
qualification on a private Xvfb display, private D-Bus session and private
FreeCAD/XDG configuration, data, cache, runtime and temporary directories.
Native effective configuration paths are asserted after application startup.
Further reviewed admission guards require explicit NC reset/spindle state and
safe start/end Z for XY rapids, and bind the complete bounded serialised native
proxy state. Refreshed-digest attacks exercise these particular guards.

The sixth frozen round again passed the three native deliveries and reached
isolated GUI editing, then the workspace resource guard stopped native jobs
because the desktop application's memory allowance was exceeded. CAM's own
scope remained below 700 MiB. This is an interrupted round, not acceptance.
Inspection also found an extra closing group in the extended portable profile;
FreeCAD partially loaded its values despite reporting malformed XML. The
profile is corrected and a host XML/membership regression check is added.
Native portable edit/reopen/material and workflow acceptance remain pending.

The next candidate isolates every batch CAM worker with the shared adaptor
launcher and tightens posted arc radius closure to 0.0000001 mm. Saved native
Path data has a separate 0.000002 mm representation allowance, with absolute
six/eight-decimal endpoint/centre comparison and nonzero-K refusal. Portable
qualification now binds the actual edited saved Path to its repost, requires a
changed program and identical unchanged-reopen repost, and repeats edited
material replay in another fresh trusted process. These use an ideal circular
program model, not a controller or servo error bound. The qualifier can reuse
explicitly identified historical constructions while rerunning current host,
profile, fresh material and lifecycle checks; it does not relabel those old
construction receipts as current-source builds. Results remain pending.

That seventh round passed current verification of the three historical
constructions, 23 hostile controls, actual isolated GUI edit and fresh GUI
reopen/repost, saved-Path/program binding, two edited material replays and the
sharp-corner refusal. It then exposed a real workflow defect: the CAM manifest
omitted the native `cadScene` artifact kind consumed by its own example.
The manifest is repaired; workflow acceptance remains pending.

The following candidate closes native property types, extensions, transient
records and expression engines before initial publication. Fresh geometry replay
reconstructs the trusted builtin tool and binds its complete tool subtree,
including parameter dependencies, every tool BREP and resolved element maps.
Tool-coordinate rounding admits at most 64 binary ULPs at the tool/coordinate
scale; all integer topology and other lexical structure remain bound, apart
from the existing qualified OCCT cache flags. Actual unchanged GUI save controls
identified only presentation visibility, a transient touched bit and one closed
native local-tool identity transition. Geometry-only admission of that state
does not certify GUI restoration. Native surfaces independently establish the
flat tip and declared full-depth cutting cylinder. Modal conflicts and the
tiny-arc/full-circle ambiguity are refused. Qualification is still pending.

Focused follow-up controls passed 184 FreeCAD host tests and eight actual
refreshed-digest product attacks against tool attributes, revolution parameters,
expressions, extensions, external links, BREP geometry, map ownership and GUI
state. Companion bundles were refreshed, and guard-specific host/native fault
messages were required. The unchanged restore control passed. The current tool
comparator also accepted the retained seventh-round GUI edited/reopened document;
that rechecks current guards without relabelling its earlier GUI execution.
A separate native component probe preserved a 3.175 mm cutter/shank, 25.4 mm
cutting length and 50.8 mm overall length through fresh save/reopen and native
surface checks. Its first harness attempt had a syntax error; the corrected
bounded run passed. These focused controls do not replace the still-pending
current-source portable/workflow qualification or independent acceptance.

Unqualified families include exterior profiling/detachment and holding, drilling,
multiple tools, ramps/helices, ball/taper tools, adaptive roughing, machine and
fixture collision verification, additional postprocessors and multi-axis CAM.

## Frozen foundation follow-up outcome

The eighth round passed at source commit
`91c2f887e70074c700d753ce5dc5d1435da3416e`, source digest
`sha256:75b1cb29a291573d8afc822cd03b8fd5954651d50163b748287df9d11c6ffa3d`,
with FreeCAD 1.1.4. This supersedes the pending lifecycle statements above for
that exact source and named scope. Three explicitly historical construction
receipts were reused; current host guards, fresh geometry/tool reconstruction
and the current lifecycle tail were requalified. This is not a claim that those
three constructions were rebuilt by the current source.

The current run rejected 31 semantic attacks and passed the unchanged tool-graph
control. Actual private GUI editing, save and fresh GUI reopen produced a changed
program; unchanged reopening produced the same repost. Persisted paths bind to
the posted NC, and two fresh native material replays verify the edited program.
The sharp-corner negative returns `UNFINISHED_MATERIAL`. A new current native
CAD-to-CAM workflow passes reuse and damaged-NC recovery, rebuilding machining
while reusing the CAD source. Retained verification also passes after supplier
source removal.

These results close the pending foundation lifecycle proof. Independent master
review, exact integrated qualification and installed product gates remain open;
all broader CAM gaps listed above remain missing. The entire FreeCAD adaptor
remains incomplete.

## Whole-operation deadline and cancellation follow-up

Independent review found that reused batch runners gave each stage a fresh full
timeout and that fresh material verification wrapped lifecycle faults as generic
verification failures. Commit `5159709` applies the remaining outer budget before
each batch launch and checks it again after the native call and private-directory
cleanup. Fresh material verification preserves `RUNNER_TIMED_OUT` and
`RUNNER_CANCELLED`, including structured native receipts, and gates final return.

The 189-test FreeCAD host suite passes, including a three-stage 10/6/2-second
budget control, post-return expiry, invalid timeouts and fault preservation.
A focused actual product qualifier passes on source digest
`sha256:f81311fbb4cda93f185b0a6fbaab766bad21d1473dbafeb4fc66644a13ed61d7`:
unchanged fresh native material/tool replay succeeds, while separate actual CAM
workers are timed out and cancelled, return their original lifecycle fault codes
and are confirmed stopped. Real launches are observed without substituting
native processes, outputs or faults. The earlier r8 receipt retains its original
source identity; this is a separate focused repair qualification.
