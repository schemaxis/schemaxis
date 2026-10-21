# Changelog

All notable changes are recorded here. Versions follow
[semantic versioning](https://semver.org/); during 0.x, minor versions may
change input contracts, with migration notes.

## 0.4.0 (unreleased): first public preview

- First public release under the Apache License 2.0.
- External adaptor packages: adaptors can be installed as separate
  distributions through the `schemaxis.adaptors` entry-point group.
- Studio authoring, contextual workflow validation, local case execution,
  scheduling, saved-run portability and explicit storage preservation.
- Expanded application adaptors, including SQLite relational summaries and
  Apache Arrow table interchange, plus bounded FreeCAD, NumPy and pyproj
  acceptance. See the dated verification records for tested versions and limits.
- Explicit distribution boundary: general-purpose database adaptors stay in
  core; integrated database services and CFD case/solver integrations remain
  separate. No integrated case-history database is included in this preview.
- Release evidence runner (`tools/release_evidence.py`) for reproducible,
  verified showcase runs.
- Release gate (`tools/release_gate.py`) checks the tree and built archives
  for private or machine-specific content.
