# Reach a named CAD measurement target

A `designStudy` changes one bounded CAD length until a named scalar measurement
falls inside an explicit target band. It uses the shared verified feedback
controller, with fresh native CAD candidates and replayable decisions.

The [rounded-part example](../examples/schemaxis/freecad-design-target.json) changes
the blank's height to obtain 1000 ± 0.1 mm³ of finished volume:

```json
"designStudy": {
  "parameter": {
    "node": "blank", "option": "height",
    "minimum": 4, "maximum": 6
  },
  "target": {
    "measurement": "finishedVolume",
    "value": 1000, "tolerance": 0.1, "units": "mm^3"
  },
  "response": "increasing",
  "maxIterations": 16,
  "minimumStep": 0.000001
}
```

The model must also declare the named `finishedVolume`
[measurement](freecad-measurements.md). Target units must exactly match the
measurement's declared quantity. `tolerance` is an absolute positive tolerance in
those units, and both ends of the acceptance band are inclusive.

## Controls and search procedure

The parameter identifies one scalar native length option in mm: supported box,
cylinder, sphere, cone or torus dimensions; rectangle/circle profile dimensions;
extrusion length; fillet radius; or chamfer distance. It cannot name an arbitrary
property, vector, imported file or script. Both bounds must pass native-option
planning, and minimum must be less than maximum. Planning cannot guarantee that
every intermediate geometry is valid.

Eligible target quantities are `volume`, `surfaceArea`, `extentX`, `extentY`,
`extentZ` and `totalEdgeLength`. Vectors and discrete counts are excluded.
`response` is an explicit user assumption that the quantity increases or decreases
with the parameter. It is checked at measured candidates within target tolerance;
it is not a proof of global monotonicity or continuity.

1. Evaluate the minimum parameter. Accept immediately if its verified measurement
   is inside the target band.
2. Otherwise evaluate the maximum. If the target is not bracketed, retain an unmet
   result with reason `target_not_bracketed`.
3. Choose the midpoint of the tightest measured bracket, verify the new native
   candidate, and update the bracket from its measured response.
4. Stop on acceptance, violated sampled response assumption, iteration limit or
   parameter resolution limit.

The default maximum is twelve candidates, bounded to 2–20. Endpoint evaluations
count toward that limit. `minimumStep` is in mm, defaults to 1e-6 and is bounded
between 1e-9 and 1000; no midpoint is attempted when the bracket is that narrow.
Native failures, invalid geometry, changed STEP sources, cancellation and timeout
remain execution faults rather than ordinary rejected search samples.

## Relationship to expressions, analytics and native links

The common runtime resolves authored expressions, document/value references and
an outer analytic visit before starting this inner study. The study changes **one
resolved option**; all other resolved values remain fixed. Native linked features
recompute from that changed option, so a profile width can drive an extrusion and
its measured volume. This does not repeatedly re-evaluate arbitrary authored
expressions that originally referred to the controlled option.

Use outer analytic visits for coupled input variants, multiple target values or
operating conditions. Each visit gets an independent inner history. A target may
also come from a verified upstream value. The declared parameter bounds and target
are revalidated for each effective document.

This is batch study execution through the registry/CLI or a workflow. Persistent
GUI `apply` accepts one candidate and explicitly rejects `designStudy`; it does
not silently ignore a search request. Semantic selections and named measurements
remain available for ordinary live candidate edits.

## Evidence and downstream use

Every `attempt-00000` retains authored candidate inputs, native readback and its
four publications. `study-summary.json` and `study.html` record the measurement
bounds, sampled response checks and stopping reason. Verification regenerates
proposals, independently re-verifies each native attempt and replays every decision,
including rejected candidates. This also detects altered human reports.

A successful study publishes its selected candidate's STEP, STL, FCStd and named
measurement JSON in the usual order, followed by the two study reports. Thus a
consumer can still use CAD artifact 0 and measurement artifact 3. Unchanged
successful workflow jobs support ordinary scheduler reuse.

An unmet study retains its verified reports but exports no candidate. Public run
and verify raise `STUDY_REQUIREMENTS_NOT_MET`, so downstream consumers cannot
mistake a rejected design for an acceptable one. For diagnostic inspection,
`design_study.verify(path, require_acceptance=False)` distinguishes a valid unmet
history from corrupt or incomplete execution.

The total study timeout includes its candidates and final verification. Each
native CAD run now passes its remaining budget to build/reopen and checks budget
and cancellation before reporting publication success. A partial history is not
resumable in place; use a fresh study after a failure or changed declaration.

## Interpretation

The result is the first tested candidate satisfying the declared band and sampled
response checks. It is not a general sketch/assembly constraint solver, global
optimiser, proof of material adequacy, or proof that a geometric predicate retained
its identity. Shape validity, selection cardinality and measurements remain separate
contracts. See [native acceptance evidence](../verification/2026-09-30-freecad-design-studies.md).
