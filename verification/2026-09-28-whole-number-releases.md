# Whole-number upstream releases and refreshed qualifications

Ngspice uses whole-number stable releases such as `47`. The shared release monitor
previously required a dotted version, so its otherwise valid upstream version was
rejected. The exact stable-version parser now permits one to four integer parts,
normalising missing parts to zero for comparison: `47` equals `47.0.0` and exceeds
`46.2`. Prerelease and suffix rejection remains intact. The upstream latest-stable
policy, source checks and evidence requirements are unchanged.

All ten release-maintenance tests pass, including whole-number ordering. Because
shared source changes invalidate qualification fingerprints, all **thirteen
previously qualified routes were freshly rerun and explicitly recorded** through
`tools/qualify_adaptor_migration.py --native --record`, using the ignored extension
configuration and only configured providers. Every route passed its native kit:
**34 cases, 352 integrity probes and 26 lifecycle probes**. This is fresh evidence,
not a digest rewrite. Bulk results are under `evidence/adaptor-extension-refresh/`.

The experimental case-preparation route remains unavailable natively; it was not
selected for native execution and has no successful native receipt. Existing app
absorbed versions are unchanged. This refresh qualifies only the existing named
cases and recorded runtimes, not all operations, MPI or optional profiles.
