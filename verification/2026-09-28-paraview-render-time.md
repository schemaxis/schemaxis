# ParaView view-time defect and benchmark preflight

Independent preparation for the ParaView AI comparison exposed a silent defect:
geometry at later requested times was correct, but rendered images still used
time zero. The RenderView's `ViewTime` remained at its default; rendering could
update visible pipelines at that time despite earlier explicit pipeline updates.
Schemaxis's previous verification accepted those images. No AI contestant had
started when this was found.

The renderer now sets and reads back view time before showing/preparing geometry.
Batch publication passes the scheduled time and the live preview passes its active
time. New image artifacts record `viewTime`; receipts advertise `renderTimeVersion: 1`
and host verification rejects a missing or mismatched time in those receipts.
Older receipts retain their existing verification contract; they do not establish
this new render-time check. A passing time readback is not an independent pixel
oracle, which is why the benchmark also checks actual image contents.

## Evidence

- `evidence/paraview-pilot-proof-02/`: retained failing pre-fix native evidence.
  Later-time images were byte-identical to time-zero images despite differing
  numeric field outputs. The common grader rejected them.
- `evidence/paraview-pilot-proof-03/`: corrected two-round native proof, all
  110 geometry/image artifacts passed with exact pixel matches to independent
  ordinary ParaView rendering.
- `evidence/paraview-pilot-package-02/` and `paraview-pilot-proof-04/`: final
  benchmark fixture with a front and oblique camera. Both rounds pass all 110
  checks (40 initial, 70 revised). These are deterministic proofs, not AI scores.
- `evidence/paraview-pilot-challenges-02/`: all eight deliberate wrong-time,
  wrong-plane, wrong-association, wrong-camera, stale-image-time, missing-image,
  missing-case and wrong-colour-range mutations rejected. An earlier camera pair
  was insufficiently distinguishable under image tolerance; its failed challenge
  remains in `paraview-pilot-challenges/`. No grading tolerance was loosened.
- `evidence/paraview-render-time-qualification/`: the existing native adaptor kit
  passed both named cases and its integrity/lifecycle checks; its receipt was
  registered against the new source. This does not add MPI or exhaustive support.
- New host regression rejects new-format image receipts with incorrect/missing
  view time. Four benchmark host tests cover publication expansion, revised tasks,
  controlled fault injection, namespace isolation and real configuration loading.
- Full host regression: **786 passed, 22 skipped (808 total)** in 195.207 seconds,
  retained in `evidence/paraview-pilot-unit.log`. All 56 generated references pass
  their drift check. The software-rendering sandbox adjustment was subsequently
  checked by the four focused benchmark tests and actual namespace preflight.

The live preview now shares the corrected time preparation, but a live native
preview was not newly qualified here. The earlier private OpenFOAM time-zero
selection failure is separate; this PVD/image-data fixture neither fixes nor
qualifies that reader path.

See the [benchmark recipes](../examples/benchmarks/paraview/README.md) for the
three-method comparison protocol. The new tests use synthetic analytic fields,
not solved CFD, private colleague cases or cluster computation.
