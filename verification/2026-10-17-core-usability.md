# Core usability host verification — 2026-10-17

Scope: shared CLI version/help/topic discovery and practical headless host setup.
No native qualification is claimed.

- `PYTHONPATH=src python3 -m unittest tests.unit.test_cli_discovery tests.unit.test_schemaxis_cli -q`: 8 tests passed. Checks module and console entry functions, exact nested help equivalence, distribution metadata/source version fallback, command keyword matches, capability-search response equivalence, empty results and exit codes 0/1/2.
- An import blocker rejects native packages and GUI/server imports during version,
  help, discovery, keyword search and a Gmsh host plan. All five paths passed.
- Disposable copied-source wheel build, followed by a clean venv installation with
  `pip install --no-index --no-deps WHEEL`, passed. Installed packages were only pip
  and Schemaxis. Metadata lists dependencies solely behind optional extras.
- Eighteen actual installed-command / installed-module cases passed with DISPLAY
  and WAYLAND_DISPLAY absent: version, help, nested help, scoped search, discovery,
  planning, private configuration, structured discovery fault (1), usage error (2).
  Both entry points reported `schemaxis 0.4.0`.
- Configuration used a disposable private JSON file and an executable fixture that
  exits 97 if launched. Configure succeeded and recorded the selected path without
  executing it. No user configuration or installation was changed.

Bulk qualification script, build/install logs and case results are retained in
`evidence/programme-20261017/core-usability/` (ignored). Tests ran on Python 3.12;
other supported Python versions were not executed here. Studio assets remain in
the wheel; their presence is separate from GUI dependencies or server startup.

See [CLI usage](../docs/cli-discovery.md) and [headless configuration](../docs/headless.md).

## Integrated storage and focused review

Latest targeted command:
`PYTHONPATH=src python3 -m unittest tests.unit.test_storage_management tests.unit.test_cli_discovery tests.unit.test_schemaxis_cli -q`
passed **23 tests** in 6.856 s. The capability regression command
`PYTHONPATH=src python3 -m unittest tests.unit.test_progressive_capabilities -q`
passed **19 tests** in 5.271 s. `git diff --check` passed for the owned files.

The final disposable wheel/venv rerun passed **26 actual installed command/module
cases**, including saved compression plans, explicit digest application and
restoration through both entry points. Installed packages remained only pip and
Schemaxis. Additional import-blocked headless checks passed schedule listing and
the non-web workflow console using disposable private configuration/workspaces.

Storage checks cover:

- Portable directory backup, ZIP stored archive and ZIP deflate compression, with
  explicit reviewed plan digests and unchanged source requirements.
- Nested shared schema dependencies remaining readable after the fixture original
  run and shared store were removed; original application artifacts/logs retain
  their bytes, file modes and empty directories.
- Wrong confirmation, stale sources, duplicate/overlapping/outside-root selection,
  destination collisions, links, special files and held owner locks, including
  workflow/study `.coordinator.lock`.
- Archive tampering, missing/extra/duplicate members, traversal in a self-consistent
  malicious manifest, symlink members, manifest-size and total-restoration limits.
- Verification/extraction on the same ZIP descriptor, refusal when its pathname is
  replaced before publication, and enforcement of actual extracted byte bounds.
- Incomplete/tampered directory backups, malformed plans/policies, unknown
  installation ownership/usage and age-gated opt-in policy previews.

Sources are retained by every operation. Policies produce plans when invoked;
there is no running cleanup scheduler. Removal of sources/installations, derived
pruning and automatic recurring cleanup remain unimplemented because reliable
ownership, shared dependency and active-run lifecycle records are absent. Task E
is therefore an implemented safe subset, **not complete in its broader requested
scope**. No user data, installation or configuration was removed or modified.

Integrity verification is process-level; crash durability, ACLs, extended
attributes and ownership preservation were not qualified. Schema/content
portability does not prove relocated application verification or native reuse:
existing receipts may depend on absolute artifact, attempt or external input
paths, binaries, plugins and resources. None were rewritten or newly qualified.

## Synthetic storage tradeoff measurement

One disposable fixture contained repeated CSV/log text, deterministic random
binary data and an external shared schema. Source run size: 2,482,549 B; external
schema: 468,072 B; portable content: 2,950,903 B. This is a compressible synthetic
fixture, not a claim about native publication compression ratios.

| Preservation | Stored bytes | Save and verify | Restore and verify |
| --- | ---: | ---: | ---: |
| Directory backup | 2,952,261 | 0.051 s | 0.030 s |
| ZIP stored | 2,953,569 | 0.045 s | 0.025 s |
| ZIP deflate level 6 | 271,245 | 0.056 s | 0.024 s |

The compressed destination used 90.8% fewer bytes than portable content, with
roughly 0.011 s more save/verification time than ZIP stored in this one run.
Originals remain, so net disk consumption **increased** by each destination's
stored bytes; no freed-space savings are claimed. Existing compressed/native
outputs can behave differently. Timing is a single local run, not a benchmark
qualification. The script and JSON measurements are under the ignored bulk
evidence directory noted above.

See [storage usage and limitations](../docs/storage-management.md).

## Isolated interpreter configuration

Review of the meshio integration exposed executable symlink resolution in both
configuration entry points. A virtual environment's Python path was replaced by
its system interpreter target, losing the selected environment. Configuration now
retains the absolute executable spelling; installation roots still resolve to
their canonical directories. New and recovered console sessions retain the same
executable path.

The focused configuration/console regression run passed 40 tests in 8.727 seconds.
A disposable real symlink-based virtual environment checks its process prefix
through new and recovered sessions. A separate actual meshio environment check
imported meshio 5.3.5 and NumPy 2.5.4 through both session paths with the intended
prefix. No user configuration was changed.
