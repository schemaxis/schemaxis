# Native evidence numeric types — 4 November 2026

Independent integration review found that Python equality could treat JSON
booleans as expected numeric native metadata. OpenSees now requires finite
non-boolean coordinate values, integer connectivity/support identifiers, distinct
positive integer process IDs and integer successful exit codes. Elmer likewise
requires an integer successful exit code. These checks preserve the existing
physical solution and independent verification tolerances.

The OpenSees native acceptance passes 28 checks, including five refreshed-digest
boolean attacks on process identity, coordinates, connectivity, restraints and
exit status. Elmer's eight canonical cases and specialised acceptance pass with
an additional refreshed-digest boolean exit-status attack. Restoring each attack
recovers successful offline verification. The probes use real successful native
outputs; a refusal caused only by an unchanged stale digest does not count.

These are malformed-evidence controls. Retained writable records are not a signed
proof of provenance or protection against forging an entire execution history.
Final integrated source-bound receipts are recorded after shared Help generation.

The unchanged scaffold import guard also found that Elmer imported a host-safe
SIF/mesh/parser helper named `native` during discovery. The helper is now named
`formats`; planning imports no native application module. The guard remains
unchanged and is rerun with the Elmer host tests before the whole-suite repeat.
