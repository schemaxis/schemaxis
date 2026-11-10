# Gnuplot exported-run verification, 24 October 2026

Scope: the `schemaxis.gnuplot/1` plot route's `verify()` boundary for runs copied
with `schemaxis` export. No new native mapping, option or format; supported native
basis and absorbed version are unchanged (6.0.5).

**Defect.** Gnuplot rebuilt the trusted launcher, input bindings, native command
and publication paths from the currently selected directory, so an exported run
failed `VERIFICATION_FAILED` ("native command/completion differs") while verifying
in place, and the fault gave no recovery. **Repair.** Verification now resolves the
producing directory through the shared run-origin hint, reads every byte from the
selected directory, and requires launcher, input bindings, command and publication
paths to match that origin exactly. A hand-copied directory remains refused, now
with recovery naming `schemaxis` export. The receipt is never rewritten.

Host tests (`tests/unit/test_gnuplot_allocation.py`, stand-in executable and
stubbed inspection, no native process): exported copy and second hop verify with
the receipt bytes unchanged; hand copy refused with recovery; edited script,
image, captured CSV or launcher in an exported copy refused; an origin redirected
to an unrelated directory refused. Two of five failed before the repair. With the
seven existing gnuplot tests, 12 pass.

| Completion item | Result |
| --- | --- |
| registration, schema, semantics, native-mapping | Unchanged; no new fields or native commands. |
| execution | Verification of exported runs added; independent SVG/PNG inspection, trusted script and byte bindings unchanged. |
| discovery, guidance | Unchanged; no new operation or field. |
| help, examples | Local guide gains an export section and fault recovery. Shared Help/reference regeneration is outstanding for the integrator. |
| tests | Five new host tests above. |
| qualification | A local Gnuplot 6.0.2 run, export and verify succeeded as a separate unqualified check. The 6.0.5 receipt predates this source change and is stale until requalified. |
| maintenance | Official release page still lists 6.0.5; `absorbedVersion` unchanged. |

Open: host CSV parsing accepts quoted cells and header although the guide calls for
bare numeric cells. Native 6.0.2 read them identically, so no misreading was shown.
